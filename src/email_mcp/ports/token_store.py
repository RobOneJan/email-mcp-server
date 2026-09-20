"""Storage port for OAuth tokens.

Generic on purpose: Gmail's `providers/gmail/auth.py` depends only on this
interface, not on a file path or any storage technology. Swapping the file
based implementation for a Secret Manager/Vault backed one - or reusing it
unchanged for a future Microsoft Graph adapter - requires no change here.
"""

from __future__ import annotations

from typing import Any, Protocol


class TokenStore(Protocol):
    def load(self) -> dict[str, Any] | None:
        """Return the persisted token payload, or None if none has been stored yet."""
        ...

    def save(self, token: dict[str, Any]) -> None:
        """Persist a token payload, overwriting any previous one."""
        ...
