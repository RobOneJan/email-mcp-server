"""Storage port for OAuth tokens.

Generic on purpose: Gmail's `providers/gmail/auth.py` depends only on this
interface, not on a file path or any storage technology. Swapping the file
based implementation for a Secret Manager/Vault backed one - or reusing it
unchanged for a future Microsoft Graph adapter - requires no change here.

Every method is keyed by `tenant_id` (see `domain/identity.py`) so one store
instance can hold one token per connected mailbox, not just one globally.
"""

from __future__ import annotations

from typing import Any, Protocol


class TokenStore(Protocol):
    def load(self, tenant_id: str) -> dict[str, Any] | None:
        """Return `tenant_id`'s persisted token payload, or None if none stored yet."""
        ...

    def save(self, tenant_id: str, token: dict[str, Any]) -> None:
        """Persist `tenant_id`'s token payload, overwriting any previous one."""
        ...
