"""Microsoft Graph OAuth via the On-Behalf-Of (OBO) flow.

Unlike Gmail (one-time interactive consent via `scripts/gmail_auth.py`,
refreshed silently forever after) or IMAP (a static password), a
Graph-backed tenant is bootstrapped through Teams SSO: the channel adapter
(agent-hub's `teams_bot.py`) obtains a short-lived Azure AD token scoped to
this app's own `access_as_user` scope from the signed-in Teams user, and
forwards it once to `/internal/graph/bootstrap`. `complete_obo_bootstrap`
exchanges that token for a Graph token via MSAL's on-behalf-of flow and
persists the resulting MSAL token cache (which holds a refresh token)
through the generic `TokenStore` port - after that one-time bootstrap, every
later call resolves silently via `get_access_token`, exactly like Gmail's
`GmailAuth.get_credentials()`.

Delegated access, not application-only: whichever mailboxes the signed-in
Teams user can already see in Outlook (their own, or one they have
delegate/shared access to) is exactly what the resulting token can see - see
providers/factory.py's module docstring and this project's README for the
reasoning behind that choice over a tenant-wide application-permission grant.

This module never logs a token value - only whether one is present/expired.
"""

from __future__ import annotations

import msal

from email_mcp.domain.errors import ProviderAuthError
from email_mcp.ports.token_store import TokenStore

# Mail.ReadWrite covers drafts/mark-as-read; Mail.Send is required
# separately by Graph to send an existing draft/message by id.
GRAPH_SCOPES = [
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/Mail.Send",
]

_CACHE_KEY = "msal_cache"


class GraphAuth:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        token_store: TokenStore,
        mailbox_tenant_id: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._authority = f"https://login.microsoftonline.com/{tenant_id}"
        self._token_store = token_store
        # This project's own `tenant_id` concept (one per connected mailbox,
        # see domain/identity.py) - distinct from the Azure AD `tenant_id`
        # above, which is the same for every Graph-backed mailbox in one
        # organization.
        self._mailbox_tenant_id = mailbox_tenant_id

    def _load_cache(self) -> msal.SerializableTokenCache:
        cache = msal.SerializableTokenCache()
        raw = self._token_store.load(self._mailbox_tenant_id)
        if raw and _CACHE_KEY in raw:
            cache.deserialize(raw[_CACHE_KEY])
        return cache

    def _save_cache(self, cache: msal.SerializableTokenCache) -> None:
        if cache.has_state_changed:
            self._token_store.save(self._mailbox_tenant_id, {_CACHE_KEY: cache.serialize()})

    def _app(self, cache: msal.SerializableTokenCache) -> msal.ConfidentialClientApplication:
        return msal.ConfidentialClientApplication(
            self._client_id,
            authority=self._authority,
            client_credential=self._client_secret,
            token_cache=cache,
        )

    def get_access_token(self) -> str:
        """Return a valid Graph access token, refreshed silently from the
        cached MSAL token cache. Raises ProviderAuthError if this mailbox has
        never completed the one-time Teams SSO bootstrap, or its refresh
        token is no longer valid - the caller (agent-hub's teams_bot.py) must
        trigger a fresh Teams sign-in and bootstrap again in that case."""
        cache = self._load_cache()
        app = self._app(cache)
        accounts = app.get_accounts()
        if not accounts:
            raise ProviderAuthError(
                "No Microsoft Graph credentials for this mailbox yet. Sign in "
                "through Teams once to complete the on-behalf-of bootstrap."
            )
        result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])
        self._save_cache(cache)
        if not result or "access_token" not in result:
            raise ProviderAuthError(
                "Microsoft Graph token could not be silently refreshed - sign "
                "in through Teams again to re-bootstrap this mailbox."
            )
        return result["access_token"]

    def complete_obo_bootstrap(self, user_assertion: str) -> None:
        """One-time (or re-run-on-expiry) exchange of a Teams SSO token for a
        Graph token, persisting the resulting refresh token so every later
        call can go through `get_access_token` silently."""
        cache = self._load_cache()
        app = self._app(cache)
        result = app.acquire_token_on_behalf_of(user_assertion=user_assertion, scopes=GRAPH_SCOPES)
        self._save_cache(cache)
        if "access_token" not in result:
            raise ProviderAuthError(
                "Microsoft Graph on-behalf-of exchange failed: "
                f"{result.get('error_description', result.get('error', 'unknown error'))}"
            )
