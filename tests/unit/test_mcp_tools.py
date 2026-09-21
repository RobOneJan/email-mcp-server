"""Tests at the actual MCP boundary: tool registration, input validation, and
the guarantee that send_email cannot succeed without a prior human decision
reached out-of-band (never through a tool call)."""

import base64
from datetime import timedelta

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from email_mcp.application.approval_service import ApprovalService
from email_mcp.application.tenant_registry import TenantRegistry
from email_mcp.domain.enums import EmailProviderName
from email_mcp.domain.identity import DEFAULT_TENANT_ID
from email_mcp.infrastructure.approval_store_file import FileApprovalStore
from email_mcp.infrastructure.audit import AuditLogger
from email_mcp.infrastructure.config import Settings
from email_mcp.infrastructure.security import MAX_SEARCH_LIMIT
from email_mcp.infrastructure.token_store_file import FileTokenStore
from email_mcp.mcp.tools import _resolve_tenant_id, register_tools


class _FakeContext:
    """Duck-typed stand-in for mcp.server.mcpserver.Context - _resolve_tenant_id
    only ever touches `.headers`, so a real Context (with its request-context
    machinery) isn't needed to test it in isolation."""

    def __init__(self, headers: dict[str, str] | None = None, *, no_request_context: bool = False) -> None:
        self._headers = headers
        self._no_request_context = no_request_context

    @property
    def headers(self) -> dict[str, str] | None:
        if self._no_request_context:
            raise ValueError("Context is not available outside of a request")
        return self._headers


@pytest.fixture
def app(tmp_path) -> MCPServer:
    settings = Settings(email_provider=EmailProviderName.FAKE)
    approvals = ApprovalService(
        FileApprovalStore(tmp_path / "approvals.json"), ttl=timedelta(minutes=30)
    )
    audit = AuditLogger(tmp_path / "audit.log")
    token_store = FileTokenStore(tmp_path / "tokens")
    registry = TenantRegistry(settings, approvals, audit, token_store)
    server = MCPServer("test-email-mcp-server")
    register_tools(server, registry)
    return server


def test_resolve_tenant_id_defaults_when_no_header_present() -> None:
    assert _resolve_tenant_id(_FakeContext(headers={})) == DEFAULT_TENANT_ID
    assert _resolve_tenant_id(_FakeContext(headers=None)) == DEFAULT_TENANT_ID


def test_resolve_tenant_id_defaults_on_stdio_transport() -> None:
    # stdio (and a tool invoked directly, bypassing a real MCP request) has no
    # request context at all - Context.headers raises ValueError in that case.
    assert _resolve_tenant_id(_FakeContext(no_request_context=True)) == DEFAULT_TENANT_ID


def test_resolve_tenant_id_reads_the_tenant_header() -> None:
    assert _resolve_tenant_id(_FakeContext(headers={"X-Tenant-Id": "friend"})) == "friend"


def test_resolve_tenant_id_is_case_insensitive_to_the_header_name() -> None:
    assert _resolve_tenant_id(_FakeContext(headers={"x-tenant-id": "friend"})) == "friend"


def test_resolve_tenant_id_rejects_a_malformed_header_value() -> None:
    with pytest.raises(ValueError):
        _resolve_tenant_id(_FakeContext(headers={"X-Tenant-Id": "not a valid id!"}))


async def test_all_expected_tools_are_registered(app: MCPServer) -> None:
    names = {t.name for t in app._tool_manager.list_tools()}
    assert names == {
        "search_emails",
        "get_email",
        "get_thread",
        "create_draft",
        "request_send_approval",
        "get_approval_status",
        "send_email",
        "mark_as_read",
        "get_attachment",
    }


async def test_send_email_is_marked_destructive(app: MCPServer) -> None:
    tool = next(t for t in app._tool_manager.list_tools() if t.name == "send_email")
    assert tool.annotations is not None
    assert tool.annotations.destructive_hint is True


async def test_search_emails_rejects_oversized_limit(app: MCPServer) -> None:
    with pytest.raises(ToolError):
        await app.call_tool("search_emails", {"limit": MAX_SEARCH_LIMIT + 1})


async def test_get_email_rejects_empty_id(app: MCPServer) -> None:
    with pytest.raises(ToolError):
        await app.call_tool("get_email", {"email_id": ""})


async def test_create_draft_rejects_malformed_recipient(app: MCPServer) -> None:
    with pytest.raises(ToolError):
        await app.call_tool(
            "create_draft",
            {"to": [{"email": "not-an-email"}], "subject": "Hi", "body_text": "Hello"},
        )


async def test_send_email_fails_without_prior_human_approval(app: MCPServer) -> None:
    draft_result = await app.call_tool(
        "create_draft",
        {
            "to": [{"email": "alice@example.com"}],
            "subject": "Hi",
            "body_text": "Hello",
        },
    )
    draft_id = draft_result.structured_content["id"]

    # An LLM cannot approve its own send: no tool exists to flip an approval
    # to APPROVED, so any approval_id it invents or requests stays useless.
    approval_result = await app.call_tool("request_send_approval", {"draft_id": draft_id})
    approval_id = approval_result.structured_content["id"]

    with pytest.raises(ToolError):
        await app.call_tool("send_email", {"draft_id": draft_id, "approval_id": approval_id})


async def test_mark_as_read_returns_success(app: MCPServer) -> None:
    result = await app.call_tool("mark_as_read", {"email_id": "msg-1"})
    assert result.structured_content == {"success": True}


async def test_get_attachment_returns_base64_content(app: MCPServer) -> None:
    email_result = await app.call_tool("get_email", {"email_id": "msg-3"})
    attachment_id = email_result.structured_content["attachments"][0]["id"]

    result = await app.call_tool(
        "get_attachment", {"email_id": "msg-3", "attachment_id": attachment_id}
    )

    assert result.structured_content["filename"] == "invoice-4711.txt"
    decoded = base64.b64decode(result.structured_content["content_base64"])
    assert decoded == b"Invoice #4711\nAmount due: $250.00\n"


async def test_get_attachment_for_unknown_id_raises(app: MCPServer) -> None:
    with pytest.raises(ToolError):
        await app.call_tool(
            "get_attachment", {"email_id": "msg-3", "attachment_id": "does-not-exist"}
        )
