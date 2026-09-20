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
