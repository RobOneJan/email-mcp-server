"""Builds the configured EmailProvider for one tenant.

This is the single place that knows how to turn `EMAIL_PROVIDER=<name>` into a
concrete adapter. Adding Microsoft Graph later means adding one branch here -
`application/` and `mcp/` never import a provider module directly.

Called once per tenant (see `application/tenant_registry.py`) - a Gmail/Graph
provider carries that tenant's own credentials via `token_store`, so it is
never shared across tenants.
"""

from __future__ import annotations

from email_mcp.domain.enums import EmailProviderName
from email_mcp.domain.errors import ProviderAuthError
from email_mcp.infrastructure.config import Settings
from email_mcp.ports.email_provider import EmailProvider
from email_mcp.ports.token_store import TokenStore


def get_email_provider(settings: Settings, tenant_id: str, token_store: TokenStore) -> EmailProvider:
    if settings.email_provider == EmailProviderName.FAKE:
        from email_mcp.providers.fake.provider import FakeEmailProvider

        return FakeEmailProvider()

    if settings.email_provider == EmailProviderName.GMAIL:
        if not settings.google_client_id or not settings.google_client_secret:
            raise ProviderAuthError(
                "EMAIL_PROVIDER=gmail requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
                "(see .env.example). Run scripts/gmail_auth.py once to obtain a token."
            )
        from email_mcp.providers.gmail.auth import GmailAuth
        from email_mcp.providers.gmail.client import GmailClient
        from email_mcp.providers.gmail.provider import GmailEmailProvider

        auth = GmailAuth(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=settings.google_redirect_uri,
            token_store=token_store,
            tenant_id=tenant_id,
        )
        client = GmailClient(auth=auth)
        return GmailEmailProvider(client=client)

    if settings.email_provider == EmailProviderName.IMAP:
        if not settings.imap_host or not settings.smtp_host or not settings.imap_username or not settings.imap_password:
            raise ProviderAuthError(
                "EMAIL_PROVIDER=imap requires IMAP_HOST, SMTP_HOST, IMAP_USERNAME and "
                "IMAP_PASSWORD (see .env.example)."
            )
        from email_mcp.providers.imap.client import ImapSmtpClient
        from email_mcp.providers.imap.provider import ImapEmailProvider

        imap_client = ImapSmtpClient(
            imap_host=settings.imap_host,
            imap_port=settings.imap_port,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            username=settings.imap_username,
            password=settings.imap_password,
            smtp_use_ssl=settings.smtp_use_ssl,
        )
        return ImapEmailProvider(
            client=imap_client,
            from_address=settings.imap_from_address or settings.imap_username,
            inbox_folder=settings.imap_inbox_folder,
            drafts_folder=settings.imap_drafts_folder,
            sent_folder=settings.imap_sent_folder,
        )

    raise ValueError(f"Unknown EMAIL_PROVIDER: {settings.email_provider!r}")
