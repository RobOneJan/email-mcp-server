"""Minimal health check, independent of any transport.

Not wired to an HTTP server in the MVP (the server runs over MCP stdio by
default) - kept as a plain function so a future HTTP/SSE deployment can
expose it without any change to `mcp/` or `application/`.
"""

from __future__ import annotations

from email_mcp.infrastructure.config import Settings


def check_health(settings: Settings) -> dict[str, str]:
    return {"status": "ok", "provider": settings.email_provider.value}
