"""Append-only audit log for write/action-category tool calls.

Deliberately separate from `logging.py`: the audit log has a fixed, typed
schema and by construction never carries free-text content (email bodies,
tokens) - only ids and outcomes. Read-only tools (search/get_email/get_thread)
are not audited; only actions with an external/state-changing effect are
(create_draft, request_send_approval, send_email, mark_as_read).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class AuditEntry:
    actor: str
    tool: str
    provider: str
    action: str
    resource_id: str
    result: str
    approval_id: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class AuditLogger:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry: AuditEntry) -> None:
        with open(self._path, "a") as fh:
            fh.write(json.dumps(asdict(entry)) + "\n")
