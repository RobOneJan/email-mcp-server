"""Storage port for ApprovalRequest records.

This is deliberately *not* an MCP tool boundary: the MCP server only ever
calls `save` and `get` (to create a request and let the LLM poll its status).
The `update_status` mutator is only ever invoked by `application.ApprovalService`
on behalf of the human-run `scripts/approve_request.py` CLI, never in response
to an MCP tool call - that separation is what makes approval genuinely
out-of-band from the LLM.

`get`/`update_status`/`list_pending` all take `tenant_id` and scope strictly to
it: an approval belonging to another tenant must be invisible, not just
inaccessible - `get`/`update_status` return/raise not-found rather than a
cross-tenant hit, so a caller can never even learn that a foreign approval_id
exists.
"""

from __future__ import annotations

from typing import Protocol

from email_mcp.domain.enums import ApprovalStatus
from email_mcp.domain.models import ApprovalRequest


class ApprovalStore(Protocol):
    def save(self, request: ApprovalRequest) -> None: ...

    def get(self, approval_id: str, tenant_id: str) -> ApprovalRequest | None: ...

    def update_status(
        self, approval_id: str, tenant_id: str, status: ApprovalStatus
    ) -> ApprovalRequest: ...

    def list_pending(self, tenant_id: str) -> list[ApprovalRequest]: ...
