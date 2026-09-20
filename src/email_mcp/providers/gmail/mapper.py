"""Pure functions mapping Gmail API JSON <-> domain models.

No network calls happen here and nothing here is async - these are simple,
directly unit-testable functions against recorded/handwritten Gmail API JSON
fixtures. This is the only place in the codebase allowed to know Gmail's
message/payload/header shape.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime

from email_mcp.domain.models import Attachment, Email, EmailAddress, EmailDraft, EmailThread

_UNREAD_LABEL = "UNREAD"


def _header_value(headers: list[dict], name: str) -> str | None:
    name = name.lower()
    for header in headers:
        if header.get("name", "").lower() == name:
            return header.get("value")
    return None


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


def decode_b64url_bytes(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded)


def _decode_b64url(data: str) -> str:
    return decode_b64url_bytes(data).decode("utf-8", errors="replace")


def _walk_body(payload: dict) -> tuple[str, str | None]:
    """Depth-first walk of `payload`/`parts`, returning (text_plain, text_html)."""
    text_plain = ""
    text_html: str | None = None

    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {})
    data = body.get("data")

    if mime_type == "text/plain" and data:
        text_plain = _decode_b64url(data)
    elif mime_type == "text/html" and data:
        text_html = _decode_b64url(data)

    for part in payload.get("parts", []) or []:
        # Skip attachment parts (they have a filename); only descend into
        # inline text/html and further multipart containers.
        if part.get("filename"):
            continue
        part_text, part_html = _walk_body(part)
        text_plain = text_plain or part_text
        text_html = text_html or part_html

    return text_plain, text_html


def _walk_attachments(payload: dict) -> list[Attachment]:
    attachments: list[Attachment] = []
    filename = payload.get("filename")
    body = payload.get("body", {})
    if filename and body.get("attachmentId"):
        attachments.append(
            Attachment(
                id=body["attachmentId"],
                filename=filename,
                content_type=payload.get("mimeType", "application/octet-stream"),
                size_bytes=body.get("size", 0),
            )
        )
    for part in payload.get("parts", []) or []:
        attachments.extend(_walk_attachments(part))
    return attachments


def _received_at(message: dict, headers: list[dict]) -> datetime:
    internal_date = message.get("internalDate")
    if internal_date is not None:
        return datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)
    date_header = _header_value(headers, "Date")
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            pass
    return datetime.now(UTC)


def gmail_message_to_email(message: dict) -> Email:
    payload = message.get("payload", {})
    headers = payload.get("headers", []) or []
    body_text, body_html = _walk_body(payload)
    label_ids = message.get("labelIds", []) or []

    return Email(
        id=message["id"],
        thread_id=message.get("threadId"),
        sender=parse_single_address(_header_value(headers, "From")),
        recipients=parse_address_list(_header_value(headers, "To")),
        cc=parse_address_list(_header_value(headers, "Cc")),
        subject=_header_value(headers, "Subject") or "",
        body_text=body_text,
        body_html=body_html,
        attachments=_walk_attachments(payload),
        received_at=_received_at(message, headers),
        is_read=_UNREAD_LABEL not in label_ids,
    )


def gmail_thread_to_domain(thread: dict) -> EmailThread:
    messages = [gmail_message_to_email(m) for m in thread.get("messages", [])]
    messages.sort(key=lambda e: e.received_at)
    subject = messages[0].subject if messages else ""
    return EmailThread(id=thread["id"], subject=subject, emails=messages)


def gmail_draft_to_domain(draft_id: str, draft: dict) -> EmailDraft:
    message = draft.get("message", {})
    payload = message.get("payload", {})
    headers = payload.get("headers", []) or []
    body_text, _body_html = _walk_body(payload)

    internal_date = message.get("internalDate")
    created_at = (
        datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)
        if internal_date
        else datetime.now(UTC)
    )

    return EmailDraft(
        id=draft_id,
        thread_id=message.get("threadId"),
        to=parse_address_list(_header_value(headers, "To")),
        cc=parse_address_list(_header_value(headers, "Cc")),
        subject=_header_value(headers, "Subject") or "",
        body_text=body_text,
        created_at=created_at,
    )


def gmail_message_header(message: dict, name: str) -> str | None:
    """Expose a single raw header value from a Gmail message (e.g. Message-ID)
    for use when building In-Reply-To/References headers on a reply draft."""
    return _header_value(message.get("payload", {}).get("headers", []) or [], name)


def build_raw_message(
    to: list[EmailAddress],
    subject: str,
    body_text: str,
    cc: list[EmailAddress] | None = None,
    in_reply_to_message_id: str | None = None,
    references: str | None = None,
) -> str:
    """Build a base64url-encoded RFC 822 message for the Gmail API's `raw` field."""
    msg = EmailMessage()
    msg["To"] = ", ".join(_format_address(a) for a in to)
    if cc:
        msg["Cc"] = ", ".join(_format_address(a) for a in cc)
    msg["Subject"] = subject
    if in_reply_to_message_id:
        msg["In-Reply-To"] = in_reply_to_message_id
    if references:
        msg["References"] = references
    msg.set_content(body_text)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def _format_address(address: EmailAddress) -> str:
    return f"{address.name} <{address.email}>" if address.name else address.email
