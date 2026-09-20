"""File-backed TokenStore.

Stores one OAuth token payload per tenant as JSON on local disk with
owner-only permissions, under `<base_dir>/<tenant_id>.json`. This is the MVP
implementation of `ports.token_store.TokenStore`; production deployments
should provide an alternative implementation backed by a Secret Manager/Vault
- no other code needs to change to do so, since `providers/gmail/auth.py`
depends only on the `TokenStore` protocol.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from email_mcp.domain.identity import validate_tenant_id


class FileTokenStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: str) -> Path:
        return self._base_dir / f"{validate_tenant_id(tenant_id)}.json"

    def load(self, tenant_id: str) -> dict[str, Any] | None:
        path = self._path(tenant_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def save(self, tenant_id: str, token: dict[str, Any]) -> None:
        path = self._path(tenant_id)
        path.write_text(json.dumps(token))
        # Best-effort: restrict to owner read/write only (POSIX).
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
