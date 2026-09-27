"""Pure functions mapping Microsoft Graph API JSON <-> domain models.

No network calls happen here and nothing here is async - mirrors
`providers/gmail/mapper.py`'s role for Gmail. This is the only place in the
codebase allowed to know Graph's message/recipient/attachment JSON shape.
"""

from __future__ import annotations

from datetime import UTC, datetime

from email_mcp.domain.models import Attachment, Email, EmailAddress, EmailDraft


def _graph_address(recipient: dict | None) -> EmailAddress:
    if not recipient:
        return EmailAddress(email="unknown@unknown.invalid", name=None)
    addr = recipient.get("emailAddress", {})
    return EmailAddress(email=addr.get("address") or "unknown@unknown.invalid", name=addr.get("name") or None)


def _graph_address_list(recipients: list[dict] | None) -> list[EmailAddress]:
    return [_graph_address(r) for r in (recipients or [])]


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    # Graph returns ISO 8601 with a trailing "Z"; fromisoformat needs an
    # explicit offset instead.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _body_text(message: dict) -> str:
    # Same fidelity tradeoff as providers/gmail/mapper.py's _walk_body: an
    # HTML-only message yields an empty body_text here rather than a stripped
    # approximation - body_html still carries the full content in that case.
    body = message.get("body", {})
    return body.get("content", "") if body.get("contentType") == "text" else ""


def _body_html(message: dict) -> str | None:
    body = message.get("body", {})
    return body.get("content") if body.get("contentType") == "html" else None


def graph_attachment_meta(raw: dict) -> Attachment:
    return Attachment(
        id=raw["id"],
        filename=raw.get("name", "attachment"),
        content_type=raw.get("contentType", "application/octet-stream"),
        size_bytes=raw.get("size", 0),
    )


def graph_message_to_email(message: dict, attachments: list[Attachment] | None = None) -> Email:
    return Email(
        id=message["id"],
        thread_id=message.get("conversationId"),
        sender=_graph_address(message.get("from")),
        recipients=_graph_address_list(message.get("toRecipients")),
        cc=_graph_address_list(message.get("ccRecipients")),
        subject=message.get("subject") or "",
        body_text=_body_text(message),
        body_html=_body_html(message),
        attachments=attachments or [],
        received_at=_parse_datetime(message.get("receivedDateTime")),
        is_read=bool(message.get("isRead", False)),
    )


def graph_message_to_draft(message: dict) -> EmailDraft:
    return EmailDraft(
        id=message["id"],
        thread_id=message.get("conversationId"),
        to=_graph_address_list(message.get("toRecipients")),
        cc=_graph_address_list(message.get("ccRecipients")),
        subject=message.get("subject") or "",
        body_text=_body_text(message),
        created_at=_parse_datetime(message.get("createdDateTime")),
    )
