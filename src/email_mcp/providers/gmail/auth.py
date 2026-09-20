"""Gmail OAuth 2.0 credential management.

Only a single scope is requested (`gmail.modify`), which is Google's
least-privilege scope that still covers everything this MVP needs: read,
create/send drafts, and change the UNREAD label - short of permanently
deleting anything. Token persistence goes through the generic `TokenStore`
port (see `ports/token_store.py`), not a hardcoded file path, so a future
Secret Manager/Vault-backed store drops in without touching this module.

This module never logs a token value - only whether one is present/expired.
"""

from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from email_mcp.domain.errors import ProviderAuthError
from email_mcp.ports.token_store import TokenStore

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailAuth:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_store: TokenStore,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._token_store = token_store

    def _client_config(self) -> dict:
        return {
            "installed": {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uris": [self._redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

    def get_credentials(self) -> Credentials:
        """Load and, if needed, refresh stored credentials.

        Raises ProviderAuthError (never a raw google-auth exception) if no
        usable token exists - the caller should be told to run
        `scripts/gmail_auth.py` once, interactively.
        """
        raw = self._token_store.load()
        if raw is None:
            raise ProviderAuthError(
                "No Gmail OAuth token found. Run `python scripts/gmail_auth.py` once "
                "to complete the consent flow."
            )
        creds = Credentials.from_authorized_user_info(raw, scopes=GMAIL_SCOPES)
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._token_store.save(_credentials_to_dict(creds))
            return creds
        raise ProviderAuthError(
            "Gmail OAuth token is invalid/expired and cannot be refreshed. "
            "Run `python scripts/gmail_auth.py` again."
        )

    def run_installed_app_flow(self) -> Credentials:
        """Interactive, one-time consent flow. Only ever called from
        scripts/gmail_auth.py, never from the running MCP server."""
        flow = InstalledAppFlow.from_client_config(self._client_config(), scopes=GMAIL_SCOPES)
        creds = flow.run_local_server(port=0)
        self._token_store.save(_credentials_to_dict(creds))
        return creds


def _credentials_to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
