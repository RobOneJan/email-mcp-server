"""Tests for providers/factory.py's tenant routing: DEFAULT_TENANT_ID stays
driven by Settings (env vars) unchanged, while any other tenant_id is routed
entirely from its own stored TokenStore record - see factory.py's docstring
for why the record's provider type is inferred from its shape."""

from __future__ import annotations

import pytest

from email_mcp.domain.enums import EmailProviderName
from email_mcp.domain.errors import ProviderAuthError
from email_mcp.domain.identity import DEFAULT_TENANT_ID
from email_mcp.infrastructure.config import Settings
from email_mcp.infrastructure.token_store_file import FileTokenStore
from email_mcp.providers.factory import get_email_provider, get_provider_name
from email_mcp.providers.fake.provider import FakeEmailProvider
from email_mcp.providers.imap.provider import ImapEmailProvider

FRIEND = "friend-terbox"


@pytest.fixture
def token_store(tmp_path) -> FileTokenStore:
    return FileTokenStore(tmp_path / "tokens")


def test_default_tenant_still_uses_settings_fake_provider(token_store: FileTokenStore) -> None:
    settings = Settings(email_provider=EmailProviderName.FAKE)
    provider = get_email_provider(settings, DEFAULT_TENANT_ID, token_store)
    assert isinstance(provider, FakeEmailProvider)
    assert get_provider_name(settings, DEFAULT_TENANT_ID, token_store) == "fake"


def test_default_tenant_still_uses_settings_imap_config(token_store: FileTokenStore) -> None:
    settings = Settings(
        email_provider=EmailProviderName.IMAP,
        imap_host="imap.example.com",
        smtp_host="smtp.example.com",
        imap_username="me@example.com",
        imap_password="secret",
    )
    provider = get_email_provider(settings, DEFAULT_TENANT_ID, token_store)
    assert isinstance(provider, ImapEmailProvider)


def test_unknown_tenant_with_no_stored_record_raises_provider_auth_error(token_store: FileTokenStore) -> None:
    settings = Settings(email_provider=EmailProviderName.FAKE)
    with pytest.raises(ProviderAuthError):
        get_email_provider(settings, FRIEND, token_store)


def test_tenant_with_imap_shaped_record_builds_imap_provider(token_store: FileTokenStore) -> None:
    settings = Settings(email_provider=EmailProviderName.FAKE)  # server default is irrelevant to other tenants
    token_store.save(
        FRIEND,
        {
            "imap_host": "imap.terbox.com",
            "smtp_host": "smtp.terbox.com",
            "username": "info@terbox.com",
            "password": "secret",
        },
    )

    provider = get_email_provider(settings, FRIEND, token_store)

    assert isinstance(provider, ImapEmailProvider)
    assert get_provider_name(settings, FRIEND, token_store) == "imap"


def test_tenant_with_gmail_shaped_record_but_no_oauth_app_configured_raises(token_store: FileTokenStore) -> None:
    # Explicit None, not just omitted - a real .env file (e.g. this repo's own
    # dev setup) would otherwise leak real GOOGLE_CLIENT_ID/SECRET in here.
    settings = Settings(email_provider=EmailProviderName.FAKE, google_client_id=None, google_client_secret=None)
    token_store.save(FRIEND, {"token": "x", "refresh_token": "y", "token_uri": "https://oauth2.googleapis.com/token"})

    with pytest.raises(ProviderAuthError):
        get_email_provider(settings, FRIEND, token_store)

    assert get_provider_name(settings, FRIEND, token_store) == "gmail"


def test_tenant_with_unrecognized_record_shape_raises(token_store: FileTokenStore) -> None:
    settings = Settings(email_provider=EmailProviderName.FAKE)
    token_store.save(FRIEND, {"some_other_field": "x"})

    with pytest.raises(ProviderAuthError):
        get_email_provider(settings, FRIEND, token_store)

    assert get_provider_name(settings, FRIEND, token_store) == "unknown"


def test_provider_name_for_unonboarded_tenant_is_unknown(token_store: FileTokenStore) -> None:
    settings = Settings(email_provider=EmailProviderName.FAKE)
    assert get_provider_name(settings, FRIEND, token_store) == "unknown"
