"""Unit-testable slice of the OAuth flow: credential loading/error paths.

The interactive consent flow itself (`run_installed_app_flow`) opens a real
browser and cannot be unit tested; it's exercised manually via
`scripts/gmail_auth.py` and covered by `tests/integration/test_gmail_adapter.py`
(skipped unless live credentials are configured).
"""

from __future__ import annotations

from typing import Any

import pytest

from email_mcp.domain.errors import ProviderAuthError
from email_mcp.providers.gmail.auth import GmailAuth


class _InMemoryTokenStore:
    def __init__(self, token: dict[str, Any] | None = None) -> None:
        self._token = token

    def load(self, tenant_id: str) -> dict[str, Any] | None:
        return self._token

    def save(self, tenant_id: str, token: dict[str, Any]) -> None:
        self._token = token


def _auth(token_store: _InMemoryTokenStore) -> GmailAuth:
    return GmailAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://localhost:8765/oauth2/callback",
        token_store=token_store,
        tenant_id="tenant-a",
    )


def test_get_credentials_without_stored_token_raises_provider_auth_error() -> None:
    auth = _auth(_InMemoryTokenStore(token=None))
    with pytest.raises(ProviderAuthError, match="scripts/gmail_auth.py"):
        auth.get_credentials()


def test_get_credentials_with_expired_token_and_no_refresh_token_raises() -> None:
    # A token with no refresh_token and an obviously-expired access token
    # cannot be silently refreshed - the user must re-run the consent flow.
    stale_token = {
        "token": "expired-access-token",
        "refresh_token": None,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
        "expiry": "2000-01-01T00:00:00Z",
    }
    auth = _auth(_InMemoryTokenStore(token=stale_token))
    with pytest.raises(ProviderAuthError):
        auth.get_credentials()
