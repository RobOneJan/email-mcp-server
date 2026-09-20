"""MCP tool wire contracts.

Deliberately separate from `domain/models.py`: these are the exact shapes
exposed to an LLM caller across the MCP boundary - which is the real trust
boundary in this system, since tool arguments come from an untrusted model.
Keeping them distinct means the domain model is free to evolve without
silently changing what a client sees, and every field an LLM can send is
bounded here (length/size caps from `infrastructure/security.py`).

Converters (`*_to_domain` / `from_domain`) are the only place a schema and a
domain model meet.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from email_mcp.domain.enums import ApprovalStatus
from email_mcp.domain.models import (
    ApprovalRequest,
    AttachmentContent,
    Email,
    EmailAddress,
    EmailDraft,
    EmailMetadata,
    EmailThread,
)
from email_mcp.infrastructure.security import (
    MAX_BODY_LENGTH,
    MAX_ID_LENGTH,
    MAX_SEARCH_LIMIT,
    MAX_SUBJECT_LENGTH,
)

# --- Reusable constrained parameter types (used directly in tool signatures) ---

IdParam = Annotated[str, Field(min_length=1, max_length=MAX_ID_LENGTH)]
QueryParam = Annotated[str | None, Field(default=None, max_length=500)]
LimitParam = Annotated[int, Field(default=50, ge=1, le=MAX_SEARCH_LIMIT)]
SubjectParam = Annotated[str, Field(min_length=1, max_length=MAX_SUBJECT_LENGTH)]
BodyParam = Annotated[str, Field(min_length=1, max_length=MAX_BODY_LENGTH)]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailAddressDTO(WireModel):
    email: EmailStr
    name: str | None = None

    def to_domain(self) -> EmailAddress:
        return EmailAddress(email=self.email, name=self.name)

    @classmethod
    def from_domain(cls, address: EmailAddress) -> EmailAddressDTO:
        return cls(email=address.email, name=address.name)


class AttachmentDTO(WireModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int


class AttachmentContentDTO(WireModel):
    filename: str
    content_type: str
    size_bytes: int
    content_base64: str

    @classmethod
    def from_domain(cls, content: AttachmentContent) -> AttachmentContentDTO:
        return cls(
            filename=content.filename,
            content_type=content.content_type,
            size_bytes=content.size_bytes,
            content_base64=base64.b64encode(content.data).decode("ascii"),
        )


class EmailSummaryDTO(WireModel):
    id: str
    thread_id: str | None
    sender: EmailAddressDTO
    subject: str
    snippet: str
    received_at: datetime
    is_read: bool

    @classmethod
    def from_domain(cls, metadata: EmailMetadata) -> EmailSummaryDTO:
        return cls(
            id=metadata.id,
            thread_id=metadata.thread_id,
            sender=EmailAddressDTO.from_domain(metadata.sender),
            subject=metadata.subject,
            snippet=metadata.snippet,
            received_at=metadata.received_at,
            is_read=metadata.is_read,
        )


class EmailDTO(WireModel):
    id: str
    thread_id: str | None
    sender: EmailAddressDTO
    recipients: list[EmailAddressDTO]
    cc: list[EmailAddressDTO]
    subject: str
    body_text: str
    body_html: str | None
    attachments: list[AttachmentDTO]
    received_at: datetime
    is_read: bool

    @classmethod
    def from_domain(cls, email: Email) -> EmailDTO:
        return cls(
            id=email.id,
            thread_id=email.thread_id,
            sender=EmailAddressDTO.from_domain(email.sender),
            recipients=[EmailAddressDTO.from_domain(a) for a in email.recipients],
            cc=[EmailAddressDTO.from_domain(a) for a in email.cc],
            subject=email.subject,
            body_text=email.body_text,
            body_html=email.body_html,
            attachments=[AttachmentDTO(**a.model_dump()) for a in email.attachments],
            received_at=email.received_at,
            is_read=email.is_read,
        )


class EmailThreadDTO(WireModel):
    id: str
    subject: str
    emails: list[EmailDTO]

    @classmethod
    def from_domain(cls, thread: EmailThread) -> EmailThreadDTO:
        return cls(
            id=thread.id,
            subject=thread.subject,
            emails=[EmailDTO.from_domain(e) for e in thread.emails],
        )


class EmailDraftDTO(WireModel):
    id: str
    thread_id: str | None
    to: list[EmailAddressDTO]
    cc: list[EmailAddressDTO]
    subject: str
    body_text: str
    created_at: datetime

    @classmethod
    def from_domain(cls, draft: EmailDraft) -> EmailDraftDTO:
        return cls(
            id=draft.id,
            thread_id=draft.thread_id,
            to=[EmailAddressDTO.from_domain(a) for a in draft.to],
            cc=[EmailAddressDTO.from_domain(a) for a in draft.cc],
            subject=draft.subject,
            body_text=draft.body_text,
            created_at=draft.created_at,
        )


class ApprovalRequestDTO(WireModel):
    id: str
    status: ApprovalStatus
    resource_id: str
    created_at: datetime
    expires_at: datetime | None
    message: str

    @classmethod
    def from_domain(cls, request: ApprovalRequest, message: str) -> ApprovalRequestDTO:
        return cls(
            id=request.id,
            status=request.status,
            resource_id=request.resource_id,
            created_at=request.created_at,
            expires_at=request.expires_at,
            message=message,
        )


class SendEmailResultDTO(WireModel):
    sent_email_id: str


class SuccessDTO(WireModel):
    success: bool = True
