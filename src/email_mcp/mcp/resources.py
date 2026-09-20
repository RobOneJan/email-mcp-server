"""MCP Resources - intentionally unused in the MVP.

`search_emails` / `get_email` / `get_thread` already cover the read path with
proper parameters (query, limit, ids) that static resource URIs handle
awkwardly. Exposing e.g. a thread as `email://thread/{id}` would duplicate
that path without giving a concrete client an advantage yet, so it's left
undone rather than added for its own sake.

If a real MCP client benefits from resource-based context (e.g. caching a
thread across multiple prompts), add it here as:

    @app.resource("email://thread/{thread_id}")
    async def thread_resource(thread_id: str) -> str: ...

wired to the same `EmailService.get_thread` used by the `get_thread` tool -
never a second code path to the provider.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from email_mcp.application.email_service import EmailService


def register_resources(app: MCPServer, service: EmailService) -> None:
    """No-op for now; kept as the wiring point described above."""
    return
