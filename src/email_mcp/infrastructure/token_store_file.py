"""File-backed TokenStore.

Stores the OAuth token payload as JSON on local disk with owner-only
permissions. This is the MVP implementation of `ports.token_store.TokenStore`;
production deployments should provide an alternative implementation backed by
a Secret Manager/Vault - no other code needs to change to do so, since
`providers/gmail/auth.py` depends only on the `TokenStore` protocol.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any


class FileTokenStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        return json.loads(self._path.read_text())

    def save(self, token: dict[str, Any]) -> None:
        self._path.write_text(json.dumps(token))
        # Best-effort: restrict to owner read/write only (POSIX).
        try:
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
