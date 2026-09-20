"""File-backed ApprovalStore.

Approval requests are read and written by two independent processes - the
running MCP server and the human-run `scripts/approve_request.py` CLI - so
every read-modify-write is done under an advisory file lock (POSIX `flock`)
to avoid a lost update. This is intentionally simple (a single JSON file);
swapping in a database-backed ApprovalStore later requires no change outside
this module, since callers only depend on `ports.approval_store.ApprovalStore`.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from email_mcp.domain.enums import ApprovalStatus
from email_mcp.domain.errors import ApprovalNotFoundError
from email_mcp.domain.models import ApprovalRequest


class FileApprovalStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("{}")

    def save(self, request: ApprovalRequest) -> None:
        with self._locked_file("r+") as (fh, data):
            data[request.id] = json.loads(request.model_dump_json())
            self._write(fh, data)

    def get(self, approval_id: str) -> ApprovalRequest | None:
        with self._locked_file("r") as (_fh, data):
            raw = data.get(approval_id)
            return ApprovalRequest.model_validate(raw) if raw else None

    def update_status(self, approval_id: str, status: ApprovalStatus) -> ApprovalRequest:
        with self._locked_file("r+") as (fh, data):
            raw = data.get(approval_id)
            if raw is None:
                raise ApprovalNotFoundError(approval_id)
            updated = ApprovalRequest.model_validate(raw).model_copy(update={"status": status})
            data[approval_id] = json.loads(updated.model_dump_json())
            self._write(fh, data)
            return updated

    def list_pending(self) -> list[ApprovalRequest]:
        with self._locked_file("r") as (_fh, data):
            return [
                ApprovalRequest.model_validate(raw)
                for raw in data.values()
                if raw.get("status") == ApprovalStatus.PENDING.value
            ]

    def _locked_file(self, mode: str):
        return _LockedJsonFile(self._path, mode)

    @staticmethod
    def _write(fh, data: dict) -> None:
        fh.seek(0)
        fh.truncate()
        json.dump(data, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())


class _LockedJsonFile:
    """Context manager: opens `path`, takes an exclusive flock, yields (fh, parsed_json)."""

    def __init__(self, path: Path, mode: str) -> None:
        self._path = path
        self._mode = mode
        self._fh = None

    def __enter__(self):
        self._fh = open(self._path, self._mode)
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        self._fh.seek(0)
        content = self._fh.read()
        data = json.loads(content) if content.strip() else {}
        return self._fh, data

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self._fh is not None
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()
