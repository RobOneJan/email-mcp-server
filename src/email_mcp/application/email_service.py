"""Provider-neutral email use cases, called by MCP tools.

This is the only layer that talks to both `EmailProvider` and
`ApprovalService` - it is where the approval gate is actually enforced before
`send_draft` is ever called. Write/action-category calls are audited; reads
are not (see `infrastructure/audit.py`).
"""

from __future__ import annotations

from email_mcp.application.approval_service import ApprovalService
from email_mcp.domain.models import (
    ApprovalRequest,
    AttachmentContent,
    Email,
    EmailAddress,
    EmailDraft,
    EmailMetadata,
    EmailThread,
)
from email_mcp.infrastructure.audit import AuditEntry, AuditLogger
from email_mcp.ports.email_provider import EmailProvider

SEND_EMAIL_ACTION = "send_email"
DEFAULT_ACTOR = "mcp-agent"  # stdio MCP is single-user in the MVP; see README limitations.


class EmailService:
    def __init__(
        self,
        provider: EmailProvider,
        approval_service: ApprovalService,
        audit_logger: AuditLogger,
        provider_name: str,
    ) -> None:
        self._provider = provider
        self._approvals = approval_service
        self._audit = audit_logger
        self._provider_name = provider_name

    async def search_emails(self, query: str | None, limit: int) -> list[EmailMetadata]:
        return await self._provider.search_emails(query=query, limit=limit)

    async def get_email(self, email_id: str) -> Email:
        return await self._provider.get_email(email_id)

    async def get_thread(self, thread_id: str) -> EmailThread:
        return await self._provider.get_thread(thread_id)

    async def create_draft(
        self,
        to: list[EmailAddress],
        subject: str,
        body_text: str,
        cc: list[EmailAddress] | None = None,
        reply_to_email_id: str | None = None,
    ) -> EmailDraft:
        draft = await self._provider.create_draft(
            to=to, subject=subject, body_text=body_text, cc=cc, reply_to_email_id=reply_to_email_id
        )
        self._record(action="create_draft", resource_id=draft.id, result="ok")
        return draft

    async def request_send_approval(self, draft_id: str) -> ApprovalRequest:
        draft = await self._provider.get_draft(draft_id)
        preview = {
            "to": ", ".join(addr.email for addr in draft.to),
            "cc": ", ".join(addr.email for addr in draft.cc),
            "subject": draft.subject,
            "body_preview": draft.body_text[:500],
        }
        request = self._approvals.request_approval(
            action=SEND_EMAIL_ACTION, resource_id=draft_id, payload=preview
        )
        self._record(action="request_send_approval", resource_id=draft_id, result="ok")
        return request

    async def get_approval_status(self, approval_id: str) -> ApprovalRequest:
        return self._approvals.get_status(approval_id)

    async def send_email(self, draft_id: str, approval_id: str) -> str:
        try:
            self._approvals.consume_if_approved(
                approval_id, action=SEND_EMAIL_ACTION, resource_id=draft_id
            )
        except Exception as exc:
            self._record(
                action=SEND_EMAIL_ACTION,
                resource_id=draft_id,
                approval_id=approval_id,
                result=f"denied: {type(exc).__name__}",
            )
            raise
        sent_id = await self._provider.send_draft(draft_id)
        self._record(
            action=SEND_EMAIL_ACTION,
            resource_id=draft_id,
            approval_id=approval_id,
            result=f"sent:{sent_id}",
        )
        return sent_id

    async def mark_as_read(self, email_id: str) -> None:
        await self._provider.mark_as_read(email_id)
        self._record(action="mark_as_read", resource_id=email_id, result="ok")

    async def get_attachment(self, email_id: str, attachment_id: str) -> AttachmentContent:
        return await self._provider.get_attachment(email_id, attachment_id)

    def _record(
        self, action: str, resource_id: str, result: str, approval_id: str | None = None
    ) -> None:
        self._audit.record(
            AuditEntry(
                actor=DEFAULT_ACTOR,
                tool=action,
                provider=self._provider_name,
                action=action,
                resource_id=resource_id,
                approval_id=approval_id,
                result=result,
            )
        )
