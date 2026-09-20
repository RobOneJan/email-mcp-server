import json
from datetime import timedelta

import pytest

from email_mcp.application.approval_service import ApprovalService
from email_mcp.application.email_service import EmailService
from email_mcp.domain.errors import (
    ApprovalNotFoundError,
    ApprovalNotGrantedError,
    EmailNotFoundError,
)
from email_mcp.domain.models import EmailAddress
from email_mcp.infrastructure.approval_store_file import FileApprovalStore
from email_mcp.infrastructure.audit import AuditLogger
from email_mcp.providers.fake.provider import FakeEmailProvider

TENANT = "tenant-a"


@pytest.fixture
def email_service(tmp_path) -> EmailService:
    provider = FakeEmailProvider()
    approvals = ApprovalService(
        FileApprovalStore(tmp_path / "approvals.json"), ttl=timedelta(minutes=30)
    )
    audit = AuditLogger(tmp_path / "audit.log")
    return EmailService(provider, approvals, audit, provider_name="fake", tenant_id=TENANT)


async def test_search_then_get_email(email_service: EmailService) -> None:
    results = await email_service.search_emails(query="roadmap", limit=10)
    assert results
    email = await email_service.get_email(results[0].id)
    assert email.id == results[0].id


async def test_get_unknown_email_raises_not_found(email_service: EmailService) -> None:
    with pytest.raises(EmailNotFoundError):
        await email_service.get_email("does-not-exist")


async def test_send_email_without_approval_is_denied(email_service: EmailService) -> None:
    draft = await email_service.create_draft(
        to=[EmailAddress(email="alice@example.com")], subject="Hi", body_text="Hello"
    )
    approval = await email_service.request_send_approval(draft.id)  # still PENDING
    with pytest.raises(ApprovalNotGrantedError):
        await email_service.send_email(draft_id=draft.id, approval_id=approval.id)


async def test_send_email_with_unknown_approval_id_is_denied(email_service: EmailService) -> None:
    draft = await email_service.create_draft(
        to=[EmailAddress(email="alice@example.com")], subject="Hi", body_text="Hello"
    )
    with pytest.raises(ApprovalNotFoundError):
        await email_service.send_email(draft_id=draft.id, approval_id="never-requested")


async def test_full_approval_flow_sends_and_audits(email_service: EmailService, tmp_path) -> None:
    draft = await email_service.create_draft(
        to=[EmailAddress(email="alice@example.com")], subject="Hi", body_text="Hello"
    )
    approval = await email_service.request_send_approval(draft.id)

    # Simulate the human deciding out-of-band (never through EmailService/MCP).
    email_service._approvals.decide(approval.id, TENANT, approve=True)

    sent_id = await email_service.send_email(draft_id=draft.id, approval_id=approval.id)
    assert sent_id

    sent_email = await email_service.get_email(sent_id)
    assert sent_email.subject == "Hi"

    audit_lines = (tmp_path / "audit.log").read_text().strip().splitlines()
    entries = [json.loads(line) for line in audit_lines]
    assert any(e["action"] == "send_email" and e["result"].startswith("sent:") for e in entries)
    # No email body/content ever ends up in the audit log.
    assert all("Hello" not in line for line in audit_lines)


async def test_mark_as_read(email_service: EmailService) -> None:
    results = await email_service.search_emails(query=None, limit=50)
    unread = next(r for r in results if not r.is_read)
    await email_service.mark_as_read(unread.id)
    refreshed = await email_service.get_email(unread.id)
    assert refreshed.is_read is True
