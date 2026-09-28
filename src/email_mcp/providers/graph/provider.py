"""GraphEmailProvider: the only place that turns Microsoft Graph API objects
into domain models (via `mapper.py`) and Graph's own HTTP errors into
`domain.errors` types. Nothing in `application/` or `mcp/` ever sees a Graph
API dict or a `requests` exception - mirrors `providers/gmail/provider.py`'s
role for Gmail.

`requests` is synchronous, so every call is offloaded via `asyncio.to_thread`
to avoid blocking the MCP server's event loop.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from typing import TypeVar

import requests

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
    Attachment,
    AttachmentContent,
    Email,
    EmailAddress,
    EmailDraft,
    EmailMetadata,
    EmailThread,
)
from email_mcp.infrastructure.security import MAX_ATTACHMENT_SIZE_BYTES
from email_mcp.providers.graph.client import GraphClient
from email_mcp.providers.graph.mapper import (
    graph_attachment_meta,
    graph_message_to_draft,
    graph_message_to_email,
)

T = TypeVar("T")


class GraphEmailProvider:
    def __init__(self, client: GraphClient) -> None:
        self._client = client

    async def search_emails(self, query: str | None = None, limit: int = 50) -> list[EmailMetadata]:
        messages = await self._call(self._client.list_messages, query, limit)
        return [graph_message_to_email(m).to_metadata() for m in messages]

    async def get_email(self, email_id: str) -> Email:
        message = await self._call(self._client.get_message, email_id)
        attachments = await self._attachments(email_id) if message.get("hasAttachments") else []
        return graph_message_to_email(message, attachments)

    async def get_thread(self, thread_id: str) -> EmailThread:
        messages = await self._call(self._client.list_thread_messages, thread_id)
        emails = sorted((graph_message_to_email(m) for m in messages), key=lambda e: e.received_at)
        subject = emails[0].subject if emails else ""
        return EmailThread(id=thread_id, subject=subject, emails=emails)

    async def create_draft(
        self,
        to: list[EmailAddress],
        subject: str,
        body_text: str,
        cc: list[EmailAddress] | None = None,
        reply_to_email_id: str | None = None,
    ) -> EmailDraft:
        content = {
            "subject": subject,
            "body": {"contentType": "text", "content": body_text},
            "toRecipients": [_to_graph_recipient(a) for a in to],
            "ccRecipients": [_to_graph_recipient(a) for a in (cc or [])],
        }
        if reply_to_email_id is not None:
            # createReply pre-links the new draft to the original message
            # (conversationId, In-Reply-To/References) with its own quoted
            # body/subject - PATCH straight over that with the caller's own
            # content, keeping only the threading Graph just set up.
            draft = await self._call(self._client.create_reply_draft, reply_to_email_id)
            draft = await self._call(self._client.update_message, draft["id"], content)
        else:
            draft = await self._call(self._client.create_draft, content)
        return graph_message_to_draft(draft)

    async def get_draft(self, draft_id: str) -> EmailDraft:
        message = await self._call(self._client.get_message, draft_id)
        return graph_message_to_draft(message)

    async def update_draft(
        self, draft_id: str, subject: str | None = None, body_text: str | None = None
    ) -> EmailDraft:
        # Graph's PATCH /messages/{id} supports partial updates natively -
        # unlike Gmail, no need to resend unrelated fields (see
        # `update_message`'s other caller, create_draft's reply-draft path,
        # for the same PATCH-over-existing-content pattern).
        content: dict = {}
        if subject is not None:
            content["subject"] = subject
        if body_text is not None:
            content["body"] = {"contentType": "text", "content": body_text}
        if content:
            await self._call(self._client.update_message, draft_id, content)
        return await self.get_draft(draft_id)

    async def send_draft(self, draft_id: str) -> str:
        await self._call(self._client.send_draft, draft_id)
        # Graph's send-by-id endpoint returns no body and keeps the sent
        # message under the same id the draft had.
        return draft_id

    async def mark_as_read(self, email_id: str) -> None:
        await self._call(self._client.mark_as_read, email_id)

    async def get_attachment(self, email_id: str, attachment_id: str) -> AttachmentContent:
        raw = await self._call(self._client.get_attachment, email_id, attachment_id)
        size_bytes = raw.get("size", 0)
        if size_bytes > MAX_ATTACHMENT_SIZE_BYTES:
            raise AttachmentTooLargeError(
                f"Attachment is {size_bytes} bytes, over the {MAX_ATTACHMENT_SIZE_BYTES}-byte limit for inline fetch."
            )
        return AttachmentContent(
            filename=raw.get("name", "attachment"),
            content_type=raw.get("contentType", "application/octet-stream"),
            size_bytes=size_bytes,
            data=base64.b64decode(raw["contentBytes"]),
        )

    async def _attachments(self, email_id: str) -> list[Attachment]:
        raws = await self._call(self._client.list_attachments, email_id)
        return [graph_attachment_meta(r) for r in raws]

    async def _call(self, fn: Callable[..., T], *args: object) -> T:
        try:
            return await asyncio.to_thread(fn, *args)
        except requests.HTTPError as exc:
            raise _translate_http_error(exc) from exc
        except requests.RequestException as exc:
            raise ProviderUnavailableError(str(exc)) from exc


def _to_graph_recipient(address: EmailAddress) -> dict:
    entry: dict = {"emailAddress": {"address": address.email}}
    if address.name:
        entry["emailAddress"]["name"] = address.name
    return entry


def _translate_http_error(exc: requests.HTTPError) -> EmailProviderError:
    status = exc.response.status_code if exc.response is not None else None
    if status == 404:
        return EmailNotFoundError("Graph resource not found")
    if status in (401, 403):
        return ProviderAuthError("Microsoft Graph rejected the request's credentials/scope")
    if status == 429:
        return ProviderRateLimitError("Microsoft Graph API rate limit exceeded")
    if status is not None and status >= 500:
        return ProviderUnavailableError("Microsoft Graph API is currently unavailable")
    if status == 400:
        return InvalidEmailRequestError("Microsoft Graph rejected the request as malformed")
    return ProviderUnavailableError(f"Unexpected Microsoft Graph API error (status={status})")
