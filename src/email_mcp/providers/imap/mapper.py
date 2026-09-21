"""Pure functions mapping RFC 822 messages <-> domain models, and the id
encoding this provider hands out.

No network calls happen here and nothing here is async - directly
unit-testable against constructed `email.message.EmailMessage` fixtures.
This is the only place in the codebase allowed to know this provider's id
encoding or MIME-parsing details.

Threading note: standard IMAP has no server-side concept of a "thread" the
way Gmail's API does. This provider builds one out of ordinary RFC 5322
headers instead - a message's thread_id is the root Message-ID of its
References chain (or its own Message-ID, if it starts a new chain). See
`_thread_id_for` and `ImapEmailProvider.get_thread`, which searches by that
same value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.message import EmailMessage, Message
from email.utils import getaddresses, make_msgid, parsedate_to_datetime
from typing import cast

from email_mcp.domain.models import Attachment, Email, EmailAddress, EmailDraft

# --- id encoding: "<role>:<uid>", e.g. "inbox:1042" -------------------------
#
# IMAP UIDs are only unique within one folder, and folder names are not
# standardized across hosts (INBOX.Drafts vs [Gmail]/Drafts vs Drafts) - so a
# raw uid can't be a provider-neutral id by itself, and a raw folder name is
# an implementation detail this provider's ids should not leak to callers.
# Every id is instead "<role>:<uid>", where role is one of a small fixed set
# (inbox/drafts/sent) `provider.py` understands and resolves to this
# account's actual configured folder name.


class UnknownIdError(ValueError):
    pass


def encode_id(role: str, uid: int) -> str:
    return f"{role}:{uid}"


def decode_id(email_id: str) -> tuple[str, int]:
    role, sep, uid = email_id.partition(":")
    if not sep or not uid.isdigit():
        raise UnknownIdError(f"Not a valid IMAP-provider id: {email_id!r}")
    return role, int(uid)


def parse_address_list(header_value: str | None) -> list[EmailAddress]:
    if not header_value:
        return []
    return [
        EmailAddress(email=addr, name=display_name or None)
        for display_name, addr in getaddresses([header_value])
        if addr
    ]


def parse_single_address(header_value: str | None) -> EmailAddress:
    addresses = parse_address_list(header_value)
    if addresses:
        return addresses[0]
    return EmailAddress(email="unknown@unknown.invalid", name=None)


def _header(msg: Message, name: str) -> str | None:
    value = msg.get(name)
    return str(value).strip() if value is not None else None


def _received_at(msg: Message) -> datetime:
    date_header = _header(msg, "Date")
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            pass
    return datetime.now(UTC)


def _thread_id_for(msg: Message) -> str | None:
    references = _header(msg, "References")
    if references:
        return references.split()[0]
    in_reply_to = _header(msg, "In-Reply-To")
    if in_reply_to:
        return in_reply_to
    return _header(msg, "Message-ID")


def _walk_body_and_attachments(msg: Message) -> tuple[str, str | None, list[Attachment]]:
    body_text = ""
    body_html: str | None = None
    attachments: list[Attachment] = []
    index = 0

    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        is_attachment = (part.get_content_disposition() or "").lower() == "attachment" or bool(filename)
        if is_attachment:
            payload = part.get_payload(decode=True)
            size_bytes = len(payload) if isinstance(payload, bytes) else 0
            attachments.append(
                Attachment(
                    id=str(index),
                    filename=filename or f"attachment-{index}",
                    content_type=part.get_content_type(),
                    size_bytes=size_bytes,
                )
            )
            index += 1
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain" and not body_text:
            body_text = cast(EmailMessage, part).get_content()
        elif content_type == "text/html" and body_html is None:
            body_html = cast(EmailMessage, part).get_content()

    return body_text, body_html, attachments


def message_id_and_references(raw: bytes) -> tuple[str | None, str | None]:
    """Raw Message-ID/References of an already-built message - used to chain
    In-Reply-To/References when replying, and to locate a just-sent message
    by its own Message-ID (see `ImapEmailProvider.send_draft`)."""
    msg = message_from_bytes(raw, policy=policy.default)
    return _header(msg, "Message-ID"), _header(msg, "References")


def imap_message_to_email(email_id: str, raw: bytes, flags: set[str]) -> Email:
    msg = message_from_bytes(raw, policy=policy.default)
    body_text, body_html, attachments = _walk_body_and_attachments(msg)
    return Email(
        id=email_id,
        thread_id=_thread_id_for(msg),
        sender=parse_single_address(_header(msg, "From")),
        recipients=parse_address_list(_header(msg, "To")),
        cc=parse_address_list(_header(msg, "Cc")),
        subject=_header(msg, "Subject") or "",
        body_text=body_text,
        body_html=body_html,
        attachments=attachments,
        received_at=_received_at(msg),
        is_read="\\Seen" in flags,
    )


def imap_message_to_draft(draft_id: str, raw: bytes) -> EmailDraft:
    msg = message_from_bytes(raw, policy=policy.default)
    body_text, _body_html, _attachments = _walk_body_and_attachments(msg)
    return EmailDraft(
        id=draft_id,
        thread_id=_thread_id_for(msg),
        to=parse_address_list(_header(msg, "To")),
        cc=parse_address_list(_header(msg, "Cc")),
        subject=_header(msg, "Subject") or "",
        body_text=body_text,
        created_at=_received_at(msg),
    )


def extract_attachment_bytes(raw: bytes, attachment_id: str) -> bytes:
    """Re-walks `raw` the same deterministic way as `_walk_body_and_attachments`
    to recover one attachment's decoded bytes by its positional id."""
    msg = message_from_bytes(raw, policy=policy.default)
    index = 0
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        is_attachment = (part.get_content_disposition() or "").lower() == "attachment" or bool(filename)
        if not is_attachment:
            continue
        if str(index) == attachment_id:
            payload = part.get_payload(decode=True)
            return payload if isinstance(payload, bytes) else b""
        index += 1
    raise KeyError(attachment_id)


def build_raw_message(
    to: list[EmailAddress],
    subject: str,
    body_text: str,
    cc: list[EmailAddress] | None = None,
    in_reply_to_message_id: str | None = None,
    references: str | None = None,
    from_addr: str | None = None,
) -> tuple[bytes, str]:
    """Build an RFC 822 message. Returns (raw_bytes, message_id).

    The Message-ID is always assigned here (never left for the server to
    mint one on APPEND) because this provider locates a just-appended
    message by searching for it (see `ImapSmtpClient.append_and_locate`)
    rather than depending on the UIDPLUS extension, which not every IMAP
    server supports.
    """
    msg = EmailMessage()
    if from_addr:
        msg["From"] = from_addr
    msg["To"] = ", ".join(_format_address(a) for a in to)
    if cc:
        msg["Cc"] = ", ".join(_format_address(a) for a in cc)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    if in_reply_to_message_id:
        msg["In-Reply-To"] = in_reply_to_message_id
    if references:
        msg["References"] = references
    msg.set_content(body_text)
    return msg.as_bytes(), str(msg["Message-ID"])


def _format_address(address: EmailAddress) -> str:
    return f"{address.name} <{address.email}>" if address.name else address.email
