"""GmailEmailProvider: the only place that turns Gmail API objects into
domain models (via `mapper.py`) and Gmail's own exceptions into
`domain.errors` types. Nothing in `application/` or `mcp/` ever sees a Gmail
API dict or a `googleapiclient`/`google.auth` exception.

`google-api-python-client` is synchronous, so every call is offloaded via
`asyncio.to_thread` to avoid blocking the MCP server's event loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError

from email_mcp.domain.errors import (
    AttachmentTooLargeError,
    EmailNotFoundError,
    EmailProviderError,
    InvalidEmailRequestError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from email_mcp.domain.models import (
    AttachmentContent,
    Email,
    EmailAddress,
    EmailDraft,
    EmailMetadata,
    EmailThread,
)
from email_mcp.infrastructure.security import MAX_ATTACHMENT_SIZE_BYTES
from email_mcp.providers.gmail.client import GmailClient
from email_mcp.providers.gmail.mapper import (
    build_raw_message,
    decode_b64url_bytes,
    gmail_draft_to_domain,
    gmail_message_header,
    gmail_message_to_email,
    gmail_thread_to_domain,
)

T = TypeVar("T")


class GmailEmailProvider:
    def __init__(self, client: GmailClient) -> None:
        self._client = client

    async def search_emails(
        self, query: str | None = None, limit: int = 50
    ) -> list[EmailMetadata]:
        ids = await self._call(self._client.list_message_ids, query, limit)
        emails = await asyncio.gather(
            *(self._call(self._client.get_message, mid) for mid in ids)
        )
        return [gmail_message_to_email(m).to_metadata() for m in emails]

    async def get_email(self, email_id: str) -> Email:
        message = await self._call(self._client.get_message, email_id)
        return gmail_message_to_email(message)

    async def get_thread(self, thread_id: str) -> EmailThread:
        thread = await self._call(self._client.get_thread, thread_id)
        return gmail_thread_to_domain(thread)

    async def create_draft(
        self,
        to: list[EmailAddress],
        subject: str,
        body_text: str,
        cc: list[EmailAddress] | None = None,
        reply_to_email_id: str | None = None,
    ) -> EmailDraft:
        thread_id: str | None = None
        in_reply_to: str | None = None
        references: str | None = None

        if reply_to_email_id is not None:
            original = await self._call(self._client.get_message, reply_to_email_id)
            thread_id = original.get("threadId")
            in_reply_to = gmail_message_header(original, "Message-ID")
            references = gmail_message_header(original, "References") or in_reply_to

        raw = build_raw_message(
            to=to,
            subject=subject,
            body_text=body_text,
            cc=cc,
            in_reply_to_message_id=in_reply_to,
            references=references,
        )
        draft = await self._call(self._client.create_draft, raw, thread_id)
        return gmail_draft_to_domain(draft["id"], draft)

    async def get_draft(self, draft_id: str) -> EmailDraft:
        draft = await self._call(self._client.get_draft, draft_id)
        return gmail_draft_to_domain(draft["id"], draft)

    async def send_draft(self, draft_id: str) -> str:
        sent = await self._call(self._client.send_draft, draft_id)
        return sent["id"]

    async def mark_as_read(self, email_id: str) -> None:
        await self._call(self._client.modify_message_labels, email_id, None, ["UNREAD"])

    async def get_attachment(self, email_id: str, attachment_id: str) -> AttachmentContent:
        # Gmail mints a fresh `attachmentId` token on every `messages.get` call
        # for the same message - it is not stable across calls, so it cannot be
        # matched against a listing fetched separately (e.g. from an earlier
        # get_email). It works fine, however, when passed straight through to
        # `attachments.get` as-is (Gmail validates it against `email_id`
        # itself, which also gives us existence checking for free via the
        # normal HttpError -> EmailNotFoundError translation below).
        raw = await self._call(self._client.get_attachment, email_id, attachment_id)
        size_bytes = raw.get("size", 0)
        if size_bytes > MAX_ATTACHMENT_SIZE_BYTES:
            raise AttachmentTooLargeError(
                f"Attachment is {size_bytes} bytes, over the "
                f"{MAX_ATTACHMENT_SIZE_BYTES}-byte limit for inline fetch."
            )
        # attachments.get returns only size/data, no filename/content_type -
        # recover those from a fresh metadata listing, joined on size_bytes
        # since (unlike the id) it is deterministic and shared across calls.
        message = await self._call(self._client.get_message, email_id)
        candidates = gmail_message_to_email(message).attachments
        meta = next((a for a in candidates if a.size_bytes == size_bytes), None)
        return AttachmentContent(
            filename=meta.filename if meta else "attachment",
            content_type=meta.content_type if meta else "application/octet-stream",
            size_bytes=size_bytes,
            data=decode_b64url_bytes(raw["data"]),
        )

    async def _call(self, fn: Callable[..., T], *args: object) -> T:
        try:
            return await asyncio.to_thread(fn, *args)
        except HttpError as exc:
            raise _translate_http_error(exc) from exc
        except GoogleAuthError as exc:
            raise ProviderAuthError(str(exc)) from exc


def _translate_http_error(exc: HttpError) -> EmailProviderError:
    status = exc.resp.status if exc.resp is not None else None
    if status == 404:
        return EmailNotFoundError("Gmail resource not found")
    if status in (401, 403):
        return ProviderAuthError("Gmail rejected the request's credentials/scope")
    if status == 429:
        return ProviderRateLimitError("Gmail API rate limit exceeded")
    if status is not None and status >= 500:
        return ProviderUnavailableError("Gmail API is currently unavailable")
    if status == 400:
        return InvalidEmailRequestError("Gmail rejected the request as malformed")
    return ProviderUnavailableError(f"Unexpected Gmail API error (status={status})")
