"""Builds the configured EmailProvider.

This is the single place that knows how to turn `EMAIL_PROVIDER=<name>` into a
concrete adapter. Adding Microsoft Graph later means adding one branch here -
`application/` and `mcp/` never import a provider module directly.
"""

from __future__ import annotations

from email_mcp.domain.enums import EmailProviderName
from email_mcp.domain.errors import ProviderAuthError
from email_mcp.infrastructure.config import Settings
from email_mcp.ports.email_provider import EmailProvider


def get_email_provider(settings: Settings) -> EmailProvider:
    if settings.email_provider == EmailProviderName.FAKE:
        from email_mcp.providers.fake.provider import FakeEmailProvider

        return FakeEmailProvider()

    if settings.email_provider == EmailProviderName.GMAIL:
        if not settings.google_client_id or not settings.google_client_secret:
            raise ProviderAuthError(
                "EMAIL_PROVIDER=gmail requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
                "(see .env.example). Run scripts/gmail_auth.py once to obtain a token."
            )
        from email_mcp.infrastructure.token_store_file import FileTokenStore
        from email_mcp.providers.gmail.auth import GmailAuth
        from email_mcp.providers.gmail.client import GmailClient
        from email_mcp.providers.gmail.provider import GmailEmailProvider

        token_store = FileTokenStore(settings.oauth_token_storage)
        auth = GmailAuth(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=settings.google_redirect_uri,
            token_store=token_store,
        )
        client = GmailClient(auth=auth)
        return GmailEmailProvider(client=client)

    raise ValueError(f"Unknown EMAIL_PROVIDER: {settings.email_provider!r}")
