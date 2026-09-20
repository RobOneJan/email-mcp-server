"""Human-approval gate for sensitive actions.

This service is provider-independent and LLM-independent: it only knows about
`ApprovalRequest`/`ApprovalStore`. The *only* code path that flips a request
from PENDING to APPROVED/REJECTED is `scripts/approve_request.py`, which calls
`decide()` directly against the same store - never through an MCP tool. See
`mcp/tools.py` for what is (and, importantly, is not) exposed to the LLM.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from email_mcp.domain.enums import ApprovalStatus
from email_mcp.domain.errors import (
    ApprovalExpiredError,
    ApprovalMismatchError,
    ApprovalNotFoundError,
    ApprovalNotGrantedError,
)
from email_mcp.domain.models import ApprovalRequest
from email_mcp.ports.approval_store import ApprovalStore


class ApprovalService:
    def __init__(self, store: ApprovalStore, ttl: timedelta = timedelta(minutes=30)) -> None:
        self._store = store
        self._ttl = ttl

    def request_approval(
        self,
        action: str,
        resource_id: str,
        payload: dict[str, str],
    ) -> ApprovalRequest:
        now = datetime.now(UTC)
        request = ApprovalRequest(
            id=str(uuid.uuid4()),
            action=action,
            resource_id=resource_id,
            status=ApprovalStatus.PENDING,
            payload=payload,
            created_at=now,
            expires_at=now + self._ttl,
        )
        self._store.save(request)
        return request

    def get_status(self, approval_id: str) -> ApprovalRequest:
        request = self._store.get(approval_id)
        if request is None:
            raise ApprovalNotFoundError(approval_id)
        return self._resolve_expiry(request)

    def decide(self, approval_id: str, approve: bool) -> ApprovalRequest:
        """Called only by the human-run CLI, never by an MCP tool."""
        request = self.get_status(approval_id)
        if request.status != ApprovalStatus.PENDING:
            raise ApprovalMismatchError(
                f"approval {approval_id} is {request.status}, not pending"
            )
        new_status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        return self._store.update_status(approval_id, new_status)

    def consume_if_approved(self, approval_id: str, action: str, resource_id: str) -> None:
        """Verify `approval_id` grants `action` on `resource_id`, then consume it.

        Raises ApprovalNotFoundError / ApprovalMismatchError / ApprovalExpiredError /
        ApprovalNotGrantedError if the action must not proceed. Only returns
        normally (and only then, atomically marks the approval CONSUMED) if the
        send may go ahead.
        """
        request = self.get_status(approval_id)
        if request.action != action or request.resource_id != resource_id:
            raise ApprovalMismatchError(
                f"approval {approval_id} was granted for {request.action}/{request.resource_id}, "
                f"not {action}/{resource_id}"
            )
        if request.status == ApprovalStatus.EXPIRED:
            raise ApprovalExpiredError(approval_id)
        if request.status != ApprovalStatus.APPROVED:
            raise ApprovalNotGrantedError(f"approval {approval_id} is {request.status}")
        self._store.update_status(approval_id, ApprovalStatus.CONSUMED)

    def list_pending(self) -> list[ApprovalRequest]:
        return self._store.list_pending()

    def _resolve_expiry(self, request: ApprovalRequest) -> ApprovalRequest:
        if (
            request.status in (ApprovalStatus.PENDING, ApprovalStatus.APPROVED)
            and request.expires_at is not None
            and datetime.now(UTC) > request.expires_at
        ):
            return self._store.update_status(request.id, ApprovalStatus.EXPIRED)
        return request
