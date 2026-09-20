"""Provider-neutral domain models.

No Gmail (or any other provider) concept may appear here: no label ids, no
Gmail message/thread id formats, no Graph-specific fields. Every provider
adapter is responsible for mapping its native objects onto these models
(see `providers/gmail/mapper.py`).

IDs are opaque strings from the domain's point of view; the application layer
never parses or interprets them, it only ever passes them back to the same
provider that issued them.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from email_mcp.domain.enums import ApprovalStatus


class DomainModel(BaseModel):
    """Base class: immutable, no undeclared fields leak in from a provider mapper."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class EmailAddress(DomainModel):
    email: EmailStr
    name: str | None = None


class Attachment(DomainModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int = Field(ge=0)


class AttachmentContent(DomainModel):
    """One attachment's actual bytes, fetched separately from the email that
    references it (both Gmail and Graph return attachment content via a
    distinct call, keyed by the attachment id from `Attachment.id`)."""

    filename: str
    content_type: str
    size_bytes: int = Field(ge=0)
    data: bytes


class EmailMetadata(DomainModel):
    """Lightweight, body-free view of an email - used wherever full content is not needed."""

    id: str
    thread_id: str | None = None
    sender: EmailAddress
    subject: str
    snippet: str = ""
    received_at: datetime
    is_read: bool = False


class Email(DomainModel):
    id: str
    thread_id: str | None = None
    sender: EmailAddress
    recipients: list[EmailAddress] = Field(default_factory=list)
    cc: list[EmailAddress] = Field(default_factory=list)
    subject: str
    body_text: str
    body_html: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    received_at: datetime
    is_read: bool = False

    def to_metadata(self) -> EmailMetadata:
        return EmailMetadata(
            id=self.id,
            thread_id=self.thread_id,
            sender=self.sender,
            subject=self.subject,
            snippet=self.body_text[:200],
            received_at=self.received_at,
            is_read=self.is_read,
        )


class EmailThread(DomainModel):
    id: str
    subject: str
    emails: list[Email] = Field(default_factory=list)


class EmailDraft(DomainModel):
    id: str
    thread_id: str | None = None
    to: list[EmailAddress]
    cc: list[EmailAddress] = Field(default_factory=list)
    subject: str
    body_text: str
    reply_to_email_id: str | None = None
    created_at: datetime


class ApprovalRequest(DomainModel):
    """A pending/decided human-approval gate for one sensitive action.

    `payload` holds a redaction-safe-for-human-review snapshot (e.g. recipient
    addresses, subject, a body preview) so a human can review it via
    `scripts/approve_request.py` without the MCP server needing to re-fetch it
    from the provider. This payload is stored only in the ApprovalStore -
    application/infrastructure logging must never dump it into logs.
    """

    id: str
    tenant_id: str
    action: str
    resource_id: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    payload: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    expires_at: datetime | None = None
