"""Builds the configured EmailProvider for one tenant.

This is the single place that knows how to turn config into a concrete
adapter. `application/` and `mcp/` never import a provider module directly.

Called once per tenant (see `application/tenant_registry.py`) - a Gmail/IMAP
provider carries that tenant's own credentials, so it is never shared across
tenants.

Two ways a tenant's provider gets chosen:

- `DEFAULT_TENANT_ID` (this server's own original single mailbox) is
  configured the original way: `EMAIL_PROVIDER`/`GOOGLE_CLIENT_*`/`IMAP_*` in
  `Settings`, i.e. plain environment variables. Nothing about this path
  changed - existing single-tenant deployments need zero migration.
- Any other `tenant_id` (a second, third, ... onboarded mailbox) has no
  environment variables of its own - there's no `IMAP_HOST_<tenant>` to add
  per mailbox. Instead its whole provider record - which provider type, and
  that provider's own credentials - lives in one place: the same
  `TokenStore` record `scripts/gmail_auth.py --tenant <id>` or
  `scripts/imap_auth.py --tenant <id>` already writes there. The provider
  type isn't stored as an explicit field there (a Gmail record shares no keys
  with an OAuth-authorization-code exchange's design that would motivate
  that) - it's inferred from which fields are present (`imap_host` vs.
  `refresh_token`), the same shape-based approach used elsewhere in this
  project's Telegram bot for detecting tool results by shape, not by name.
"""

from __future__ import annotations

from typing import Any

from email_mcp.domain.enums import EmailProviderName
from email_mcp.domain.errors import ProviderAuthError
from email_mcp.domain.identity import DEFAULT_TENANT_ID
from email_mcp.infrastructure.config import Settings
from email_mcp.ports.email_provider import EmailProvider
from email_mcp.ports.token_store import TokenStore

_ONBOARDING_HINT = (
    "Run `python scripts/gmail_auth.py --tenant {tenant_id}` (Gmail) or "
    "`python scripts/imap_auth.py --tenant {tenant_id}` (any other IMAP/SMTP "
    "mailbox) once to onboard this tenant."
)


def get_email_provider(settings: Settings, tenant_id: str, token_store: TokenStore) -> EmailProvider:
    if tenant_id == DEFAULT_TENANT_ID:
        return _provider_from_settings(settings, tenant_id, token_store)
    return _provider_from_tenant_record(settings, tenant_id, token_store)


def get_provider_name(settings: Settings, tenant_id: str, token_store: TokenStore) -> str:
    """The provider type a tenant resolves to, for audit/logging metadata only
    - mirrors `get_email_provider`'s own routing without building a provider."""
    if tenant_id == DEFAULT_TENANT_ID:
        return settings.email_provider.value
    record = token_store.load(tenant_id)
    return _record_provider_name(record) if record else "unknown"


def _record_provider_name(record: dict[str, Any]) -> str:
    if "imap_host" in record:
        return "imap"
    if "refresh_token" in record or "token_uri" in record:
        return "gmail"
    return "unknown"


def _provider_from_settings(settings: Settings, tenant_id: str, token_store: TokenStore) -> EmailProvider:
    if settings.email_provider == EmailProviderName.FAKE:
        from email_mcp.providers.fake.provider import FakeEmailProvider

        return FakeEmailProvider()

    if settings.email_provider == EmailProviderName.GMAIL:
        if not settings.google_client_id or not settings.google_client_secret:
            raise ProviderAuthError(
                "EMAIL_PROVIDER=gmail requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
                "(see .env.example). Run scripts/gmail_auth.py once to obtain a token."
            )
        return _build_gmail_provider(settings, tenant_id, token_store)

    if settings.email_provider == EmailProviderName.IMAP:
        if not settings.imap_host or not settings.smtp_host or not settings.imap_username or not settings.imap_password:
            raise ProviderAuthError(
                "EMAIL_PROVIDER=imap requires IMAP_HOST, SMTP_HOST, IMAP_USERNAME and "
                "IMAP_PASSWORD (see .env.example)."
            )
        return _build_imap_provider(
            imap_host=settings.imap_host,
            imap_port=settings.imap_port,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            username=settings.imap_username,
            password=settings.imap_password,
            smtp_use_ssl=settings.smtp_use_ssl,
            from_address=settings.imap_from_address or settings.imap_username,
            inbox_folder=settings.imap_inbox_folder,
            drafts_folder=settings.imap_drafts_folder,
            sent_folder=settings.imap_sent_folder,
        )

    raise ValueError(f"Unknown EMAIL_PROVIDER: {settings.email_provider!r}")


def _provider_from_tenant_record(settings: Settings, tenant_id: str, token_store: TokenStore) -> EmailProvider:
    record = token_store.load(tenant_id)
    if record is None:
        raise ProviderAuthError(
            f"No credentials configured for tenant_id={tenant_id!r}. " + _ONBOARDING_HINT.format(tenant_id=tenant_id)
        )

    name = _record_provider_name(record)
    if name == "imap":
        return _build_imap_provider(
            imap_host=record["imap_host"],
            imap_port=record.get("imap_port", 993),
            smtp_host=record["smtp_host"],
            smtp_port=record.get("smtp_port", 587),
            username=record["username"],
            password=record["password"],
            smtp_use_ssl=record.get("smtp_use_ssl", False),
            from_address=record.get("from_address") or record["username"],
            inbox_folder=record.get("inbox_folder", "INBOX"),
            drafts_folder=record.get("drafts_folder", "Drafts"),
            sent_folder=record.get("sent_folder", "Sent"),
        )
    if name == "gmail":
        if not settings.google_client_id or not settings.google_client_secret:
            raise ProviderAuthError(
                f"Tenant_id={tenant_id!r} has a Gmail token, but this server has no "
                "GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET configured (see .env.example) - "
                "one registered Google OAuth app is shared by every Gmail tenant."
            )
        return _build_gmail_provider(settings, tenant_id, token_store)

    raise ProviderAuthError(
        f"Stored credentials for tenant_id={tenant_id!r} are in an unrecognized format."
    )


def _build_gmail_provider(settings: Settings, tenant_id: str, token_store: TokenStore) -> EmailProvider:
    from email_mcp.providers.gmail.auth import GmailAuth
    from email_mcp.providers.gmail.client import GmailClient
    from email_mcp.providers.gmail.provider import GmailEmailProvider

    auth = GmailAuth(
        client_id=settings.google_client_id,  # type: ignore[arg-type]  # checked by both callers above
        client_secret=settings.google_client_secret,  # type: ignore[arg-type]
        redirect_uri=settings.google_redirect_uri,
        token_store=token_store,
        tenant_id=tenant_id,
    )
    return GmailEmailProvider(client=GmailClient(auth=auth))


def _build_imap_provider(
    *,
    imap_host: str,
    imap_port: int,
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
    smtp_use_ssl: bool,
    from_address: str,
    inbox_folder: str,
    drafts_folder: str,
    sent_folder: str,
) -> EmailProvider:
    from email_mcp.providers.imap.client import ImapSmtpClient
    from email_mcp.providers.imap.provider import ImapEmailProvider

    client = ImapSmtpClient(
        imap_host=imap_host,
        imap_port=imap_port,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        username=username,
        password=password,
        smtp_use_ssl=smtp_use_ssl,
    )
    return ImapEmailProvider(
        client=client,
        from_address=from_address,
        inbox_folder=inbox_folder,
        drafts_folder=drafts_folder,
        sent_folder=sent_folder,
    )
