"""Storage port for ApprovalRequest records.

This is deliberately *not* an MCP tool boundary: the MCP server only ever
calls `save` and `get` (to create a request and let the LLM poll its status).
The `update_status` mutator is only ever invoked by `application.ApprovalService`
on behalf of the human-run `scripts/approve_request.py` CLI, never in response
to an MCP tool call - that separation is what makes approval genuinely
out-of-band from the LLM.
"""

from __future__ import annotations

from typing import Protocol

from email_mcp.domain.enums import ApprovalStatus
from email_mcp.domain.models import ApprovalRequest


class ApprovalStore(Protocol):
    def save(self, request: ApprovalRequest) -> None: ...

    def get(self, approval_id: str) -> ApprovalRequest | None: ...

    def update_status(self, approval_id: str, status: ApprovalStatus) -> ApprovalRequest: ...

    def list_pending(self) -> list[ApprovalRequest]: ...
