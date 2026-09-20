from datetime import UTC, datetime, timedelta

import pytest

from email_mcp.application.approval_service import ApprovalService
from email_mcp.domain.enums import ApprovalStatus
from email_mcp.domain.errors import (
    ApprovalExpiredError,
    ApprovalMismatchError,
    ApprovalNotFoundError,
    ApprovalNotGrantedError,
)
from email_mcp.infrastructure.approval_store_file import FileApprovalStore


@pytest.fixture
def store(tmp_path) -> FileApprovalStore:
    return FileApprovalStore(tmp_path / "approvals.json")


@pytest.fixture
def service(store: FileApprovalStore) -> ApprovalService:
    return ApprovalService(store, ttl=timedelta(minutes=30))


def test_request_approval_is_pending(service: ApprovalService) -> None:
    request = service.request_approval("send_email", "draft-1", payload={"subject": "hi"})
    assert request.status == ApprovalStatus.PENDING
    assert service.get_status(request.id).id == request.id


def test_consume_before_approval_is_denied(service: ApprovalService) -> None:
    request = service.request_approval("send_email", "draft-1", payload={})
    with pytest.raises(ApprovalNotGrantedError):
        service.consume_if_approved(request.id, action="send_email", resource_id="draft-1")


def test_consume_after_approval_succeeds_and_then_is_replay_protected(
    service: ApprovalService,
) -> None:
    request = service.request_approval("send_email", "draft-1", payload={})
    service.decide(request.id, approve=True)

    service.consume_if_approved(request.id, action="send_email", resource_id="draft-1")

    with pytest.raises(ApprovalNotGrantedError):
        service.consume_if_approved(request.id, action="send_email", resource_id="draft-1")


def test_consume_rejects_mismatched_resource(service: ApprovalService) -> None:
    request = service.request_approval("send_email", "draft-1", payload={})
    service.decide(request.id, approve=True)

    with pytest.raises(ApprovalMismatchError):
        service.consume_if_approved(request.id, action="send_email", resource_id="draft-OTHER")


def test_rejected_approval_cannot_be_consumed(service: ApprovalService) -> None:
    request = service.request_approval("send_email", "draft-1", payload={})
    service.decide(request.id, approve=False)

    with pytest.raises(ApprovalNotGrantedError):
        service.consume_if_approved(request.id, action="send_email", resource_id="draft-1")


def test_deciding_twice_is_rejected(service: ApprovalService) -> None:
    request = service.request_approval("send_email", "draft-1", payload={})
    service.decide(request.id, approve=True)
    with pytest.raises(ApprovalMismatchError):
        service.decide(request.id, approve=True)


def test_expired_request_cannot_be_consumed(
    service: ApprovalService, store: FileApprovalStore
) -> None:
    request = service.request_approval("send_email", "draft-1", payload={})
    service.decide(request.id, approve=True)

    # Simulate time passing past expiry (approved-but-stale, e.g. a human
    # approved it but the agent didn't act on it before the TTL ran out).
    approved = store.get(request.id)
    assert approved is not None
    store.save(approved.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}))

    with pytest.raises(ApprovalExpiredError):
        service.consume_if_approved(request.id, action="send_email", resource_id="draft-1")


def test_unknown_approval_id_raises_not_found(service: ApprovalService) -> None:
    with pytest.raises(ApprovalNotFoundError):
        service.get_status("does-not-exist")
