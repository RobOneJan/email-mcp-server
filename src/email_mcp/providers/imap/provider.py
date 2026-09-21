"""ImapEmailProvider: implements EmailProvider over plain IMAP (read) + SMTP
(send) - for any mail host that isn't Gmail/Graph and only offers standard
protocols, the common case for a personal or small-business mailbox.

Unlike Gmail, standard IMAP has no server-side "thread" concept and no API-
level distinction for a drafts/sent folder - this provider builds both out
of ordinary folders and RFC 5322 headers (see `mapper.py`). Authentication
is plain username/password over TLS (no OAuth): the credential shape the
overwhelming majority of non-Gmail/non-Graph IMAP/SMTP hosts require.

`google-api-python-client`-style offloading applies here too: `imaplib`/
`smtplib` are synchronous, so every call goes through `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import imaplib
import smtplib
from collections.abc import Callable
from typing import TypeVar

from email_mcp.domain.errors import (
    AttachmentTooLargeError,
    EmailNotFoundError,
    EmailProviderError,
    ProviderAuthError,
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
from email_mcp.providers.imap.client import ImapCommandError, ImapNotFoundError, ImapSmtpClient
from email_mcp.providers.imap.mapper import (
    UnknownIdError,
    build_raw_message,
    decode_id,
    encode_id,
    extract_attachment_bytes,
    imap_message_to_draft,
    imap_message_to_email,
    message_id_and_references,
)

T = TypeVar("T")

_ROLE_INBOX = "inbox"
_ROLE_DRAFTS = "drafts"
_ROLE_SENT = "sent"
_KNOWN_ROLES = (_ROLE_INBOX, _ROLE_DRAFTS, _ROLE_SENT)


class ImapEmailProvider:
    def __init__(
        self,
        client: ImapSmtpClient,
        from_address: str,
        inbox_folder: str = "INBOX",
        drafts_folder: str = "Drafts",
        sent_folder: str = "Sent",
    ) -> None:
        self._client = client
        self._from_address = from_address
        self._folders = {
            _ROLE_INBOX: inbox_folder,
            _ROLE_DRAFTS: drafts_folder,
            _ROLE_SENT: sent_folder,
        }

    async def search_emails(self, query: str | None = None, limit: int = 50) -> list[EmailMetadata]:
        criteria = f'(TEXT "{_escape(query)}")' if query else "ALL"
        uids = await self._call(self._client.search, self._folders[_ROLE_INBOX], criteria)
        # IMAP UIDs increase monotonically with delivery order (RFC 3501) -
        # sorting them descending approximates "most recent first" without a
        # second round-trip to read INTERNALDATE for every candidate.
        uids = sorted(uids, reverse=True)[:limit]
        emails = await asyncio.gather(*(self._get(_ROLE_INBOX, uid) for uid in uids))
        return [email.to_metadata() for email in emails]

    async def get_email(self, email_id: str) -> Email:
        role, uid = _decode_or_not_found(email_id)
        return await self._get(role, uid)

    async def _get(self, role: str, uid: int) -> Email:
        raw, flags = await self._call(self._client.fetch_message, self._folders[role], uid)
        return imap_message_to_email(encode_id(role, uid), raw, flags)

    async def get_thread(self, thread_id: str) -> EmailThread:
        # No native IMAP threading - search Inbox and Sent for anything whose
        # own Message-ID matches (the thread root itself) or whose References
        # chain contains it (any reply, however deep - see mapper.py).
        criteria = f'(OR (HEADER Message-ID "{_escape(thread_id)}") (HEADER References "{_escape(thread_id)}"))'
        emails: list[Email] = []
        for role in (_ROLE_INBOX, _ROLE_SENT):
            uids = await self._call(self._client.search, self._folders[role], criteria)
            emails.extend(await asyncio.gather(*(self._get(role, uid) for uid in uids)))
        if not emails:
            raise EmailNotFoundError(f"No messages found for thread {thread_id!r}")
        emails.sort(key=lambda e: e.received_at)
        return EmailThread(id=thread_id, subject=emails[0].subject, emails=emails)

    async def create_draft(
        self,
        to: list[EmailAddress],
        subject: str,
        body_text: str,
        cc: list[EmailAddress] | None = None,
        reply_to_email_id: str | None = None,
    ) -> EmailDraft:
        in_reply_to: str | None = None
        references: str | None = None

        if reply_to_email_id is not None:
            role, uid = _decode_or_not_found(reply_to_email_id)
            raw, _flags = await self._call(self._client.fetch_message, self._folders[role], uid)
            original_message_id, original_references = message_id_and_references(raw)
            in_reply_to = original_message_id
            if original_references and original_message_id:
                references = f"{original_references} {original_message_id}"
            else:
                references = original_message_id or original_references

        raw_message, message_id = build_raw_message(
            to=to,
            subject=subject,
            body_text=body_text,
            cc=cc,
            in_reply_to_message_id=in_reply_to,
            references=references,
            from_addr=self._from_address,
        )
        uid = await self._call(
            self._client.append_and_locate, self._folders[_ROLE_DRAFTS], raw_message, message_id
        )
        return imap_message_to_draft(encode_id(_ROLE_DRAFTS, uid), raw_message)

    async def get_draft(self, draft_id: str) -> EmailDraft:
        raw = await self._fetch_draft_raw(draft_id)
        return imap_message_to_draft(draft_id, raw)

    async def send_draft(self, draft_id: str) -> str:
        role, uid = _decode_or_not_found(draft_id)
        if role != _ROLE_DRAFTS:
            raise EmailNotFoundError(f"{draft_id!r} is not a draft id")
        raw, _flags = await self._call(self._client.fetch_message, self._folders[_ROLE_DRAFTS], uid)
        draft = imap_message_to_draft(draft_id, raw)

        to_addrs = [a.email for a in (*draft.to, *draft.cc)]
        await self._call(self._client.send, raw, self._from_address, to_addrs)

        # Most non-Gmail/Graph SMTP servers do not auto-copy a sent message
        # into a "Sent" folder the way Gmail's own SMTP does - append it
        # ourselves so get_email/get_thread on the returned id work like any
        # other provider's.
        message_id, _references = message_id_and_references(raw)
        sent_uid = await self._call(
            self._client.append_and_locate, self._folders[_ROLE_SENT], raw, message_id or ""
        )
        await self._call(self._client.delete, self._folders[_ROLE_DRAFTS], uid)
        return encode_id(_ROLE_SENT, sent_uid)

    async def mark_as_read(self, email_id: str) -> None:
        role, uid = _decode_or_not_found(email_id)
        await self._call(self._client.set_flag, self._folders[role], uid, "\\Seen", True)

    async def get_attachment(self, email_id: str, attachment_id: str) -> AttachmentContent:
        role, uid = _decode_or_not_found(email_id)
        raw, flags = await self._call(self._client.fetch_message, self._folders[role], uid)
        email = imap_message_to_email(email_id, raw, flags)
        meta = next((a for a in email.attachments if a.id == attachment_id), None)
        if meta is None:
            raise EmailNotFoundError(f"No attachment {attachment_id!r} on {email_id!r}")
        if meta.size_bytes > MAX_ATTACHMENT_SIZE_BYTES:
            raise AttachmentTooLargeError(
                f"Attachment is {meta.size_bytes} bytes, over the "
                f"{MAX_ATTACHMENT_SIZE_BYTES}-byte limit for inline fetch."
            )
        try:
            data = extract_attachment_bytes(raw, attachment_id)
        except KeyError:
            raise EmailNotFoundError(f"No attachment {attachment_id!r} on {email_id!r}") from None
        return AttachmentContent(
            filename=meta.filename, content_type=meta.content_type, size_bytes=meta.size_bytes, data=data
        )

    async def _fetch_draft_raw(self, draft_id: str) -> bytes:
        role, uid = _decode_or_not_found(draft_id)
        if role != _ROLE_DRAFTS:
            raise EmailNotFoundError(f"{draft_id!r} is not a draft id")
        raw, _flags = await self._call(self._client.fetch_message, self._folders[_ROLE_DRAFTS], uid)
        return raw

    async def _call(self, fn: Callable[..., T], *args: object) -> T:
        try:
            return await asyncio.to_thread(fn, *args)
        except ImapNotFoundError as exc:
            raise EmailNotFoundError(str(exc)) from exc
        except ImapCommandError as exc:
            raise ProviderUnavailableError(str(exc)) from exc
        except imaplib.IMAP4.error as exc:
            raise _translate_imap_error(exc) from exc
        except smtplib.SMTPAuthenticationError as exc:
            raise ProviderAuthError(f"SMTP rejected the request's credentials: {exc}") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise ProviderUnavailableError(str(exc)) from exc


def _decode_or_not_found(email_id: str) -> tuple[str, int]:
    try:
        role, uid = decode_id(email_id)
    except UnknownIdError as exc:
        raise EmailNotFoundError(str(exc)) from exc
    if role not in _KNOWN_ROLES:
        raise EmailNotFoundError(f"Unknown folder role in id {email_id!r}")
    return role, uid


def _translate_imap_error(exc: imaplib.IMAP4.error) -> EmailProviderError:
    # imaplib has no typed auth-failure exception (unlike smtplib) - the
    # server's rejection reason only ever comes back as free text in the
    # error message (e.g. "[AUTHENTICATIONFAILED] Invalid credentials").
    message = str(exc).lower()
    if "auth" in message or "login" in message or "credential" in message:
        return ProviderAuthError(f"IMAP rejected the request's credentials: {exc}")
    return ProviderUnavailableError(f"IMAP command failed: {exc}")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
