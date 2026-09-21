"""Environment-driven configuration.

All secrets/config come from environment variables (optionally loaded from a
local `.env` via python-dotenv) - never hardcoded, never committed. See
`.env.example` for the full list of supported variables.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from email_mcp.domain.enums import EmailProviderName


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    email_provider: EmailProviderName = EmailProviderName.FAKE

    # Gmail OAuth
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8765/oauth2/callback"
    # A directory, not a file: one token per tenant is stored at
    # <oauth_token_storage>/<tenant_id>.json (see infrastructure/token_store_file.py).
    oauth_token_storage: str = "./var/tokens"

    # IMAP/SMTP (required only when EMAIL_PROVIDER=imap) - plain username/
    # password over TLS, the credential shape the overwhelming majority of
    # non-Gmail/non-Graph mail hosts require (an app-specific password where
    # the host mandates one, e.g. many consumer webmail hosts with 2FA).
    # Single account today, same as Gmail's own current single-tenant reality
    # - see providers/factory.py.
    imap_host: str | None = None
    imap_port: int = 993
    imap_username: str | None = None
    imap_password: str | None = None
    # Folder names are not standardized across IMAP hosts (INBOX.Drafts vs
    # [Gmail]/Drafts vs Drafts, Sent vs "Sent Items", ...) - override per host.
    imap_inbox_folder: str = "INBOX"
    imap_drafts_folder: str = "Drafts"
    imap_sent_folder: str = "Sent"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_use_ssl: bool = False  # True for implicit-TLS SMTP (typically port 465); False = STARTTLS (587)
    # From: header / SMTP envelope sender for outgoing mail. Defaults to
    # imap_username, which is correct for the common case of one mailbox = one
    # login = one send-as address.
    imap_from_address: str | None = None

    # Approval store
    approval_store_path: str = "./var/approvals.json"
    approval_ttl_minutes: int = Field(default=30, gt=0)

    # Logging / audit
    log_level: str = "INFO"
    log_format: str = "text"  # "text" for local dev, "json" for Cloud Logging
    audit_log_path: str = "./var/audit.log"

    # Transport: "stdio" for local MCP clients, "streamable-http" for hosted
    # deployments (e.g. Cloud Run, which requires listening on $PORT over HTTP).
    mcp_transport: str = "stdio"
    port: int = Field(default=8080, gt=0)


def get_settings() -> Settings:
    """Load settings fresh from the environment (cheap; call once at startup)."""
    return Settings()
