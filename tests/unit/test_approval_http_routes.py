"""These two HTTP routes are the one and only way to approve/reject a send
from outside `scripts/approve_request.py` - they are deliberately not MCP
tools (see mcp/server.py's comment), so no sequence of tool calls the LLM
makes can ever reach them. These tests exercise them the way a channel
adapter's human-triggered callback would (see agent-hub's README)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from starlette.testclient import TestClient

from email_mcp.application.approval_service import ApprovalService
from email_mcp.domain.enums import EmailProviderName
from email_mcp.domain.identity import DEFAULT_TENANT_ID
from email_mcp.infrastructure.approval_store_file import FileApprovalStore
from email_mcp.infrastructure.config import Settings
from email_mcp.mcp.server import create_server


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        email_provider=EmailProviderName.FAKE,
        approval_store_path=str(tmp_path / "approvals.json"),
        audit_log_path=str(tmp_path / "audit.log"),
        oauth_token_storage=str(tmp_path / "tokens"),
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_server(settings)
    with TestClient(app.streamable_http_app()) as c:
        yield c


def _seed_pending_approval(settings: Settings, tenant_id: str = DEFAULT_TENANT_ID) -> str:
    store = FileApprovalStore(settings.approval_store_path)
    service = ApprovalService(store, ttl=timedelta(minutes=30))
    request = service.request_approval(tenant_id, "send_email", "draft-1", payload={"subject": "hi"})
    return request.id


def test_approve_route_moves_pending_to_approved(client: TestClient, settings: Settings) -> None:
    approval_id = _seed_pending_approval(settings)

    resp = client.post(f"/internal/approvals/{approval_id}/approve")

    assert resp.status_code == 200
    assert resp.json() == {"id": approval_id, "status": "approved", "resource_id": "draft-1"}


def test_reject_route_moves_pending_to_rejected(client: TestClient, settings: Settings) -> None:
    approval_id = _seed_pending_approval(settings)

    resp = client.post(f"/internal/approvals/{approval_id}/reject")

    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_unknown_approval_id_is_404(client: TestClient) -> None:
    resp = client.post("/internal/approvals/does-not-exist/approve")
    assert resp.status_code == 404


def test_deciding_an_already_decided_approval_is_409(client: TestClient, settings: Settings) -> None:
    approval_id = _seed_pending_approval(settings)
    client.post(f"/internal/approvals/{approval_id}/approve")

    resp = client.post(f"/internal/approvals/{approval_id}/approve")

    assert resp.status_code == 409


def test_wrong_tenant_cannot_see_or_decide_the_approval(client: TestClient, settings: Settings) -> None:
    approval_id = _seed_pending_approval(settings, tenant_id=DEFAULT_TENANT_ID)

    resp = client.post(f"/internal/approvals/{approval_id}/approve", params={"tenant": "someone-elses-tenant"})

    assert resp.status_code == 404
