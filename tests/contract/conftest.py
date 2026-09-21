"""Shared fixtures for provider contract tests.

The Fake arm always runs (it's the primary correctness gate for this
project - see README). The Gmail and IMAP arms only run when a human has
explicitly opted in via RUN_LIVE_GMAIL_CONTRACT_TESTS=1 / RUN_LIVE_IMAP_CONTRACT_TESTS=1
*and* real credentials are present - contract tests create a real draft (and
send a real message) in the configured mailbox, which is a genuine (if
reversible) side effect and must never happen by accident just because
credentials happen to be configured in the environment.
"""

from __future__ import annotations

import os

import pytest

from email_mcp.ports.email_provider import EmailProvider
from email_mcp.providers.fake.provider import FakeEmailProvider


def _gmail_contract_provider() -> EmailProvider:
    from email_mcp.domain.identity import DEFAULT_TENANT_ID
    from email_mcp.infrastructure.config import get_settings
    from email_mcp.infrastructure.token_store_file import FileTokenStore
    from email_mcp.providers.factory import get_email_provider

    settings = get_settings()
    token_store = FileTokenStore(settings.oauth_token_storage)
    return get_email_provider(settings, DEFAULT_TENANT_ID, token_store)


def _gmail_available() -> bool:
    return bool(
        os.environ.get("RUN_LIVE_GMAIL_CONTRACT_TESTS")
        and os.environ.get("GOOGLE_CLIENT_ID")
        and os.environ.get("GOOGLE_CLIENT_SECRET")
    )


def _imap_contract_provider() -> EmailProvider:
    from email_mcp.domain.identity import DEFAULT_TENANT_ID
    from email_mcp.infrastructure.config import get_settings
    from email_mcp.infrastructure.token_store_file import FileTokenStore
    from email_mcp.providers.factory import get_email_provider

    settings = get_settings()
    token_store = FileTokenStore(settings.oauth_token_storage)  # unused by the imap branch; kept for a uniform signature
    return get_email_provider(settings, DEFAULT_TENANT_ID, token_store)


def _imap_available() -> bool:
    return bool(
        os.environ.get("RUN_LIVE_IMAP_CONTRACT_TESTS")
        and os.environ.get("IMAP_HOST")
        and os.environ.get("SMTP_HOST")
        and os.environ.get("IMAP_USERNAME")
        and os.environ.get("IMAP_PASSWORD")
    )


@pytest.fixture(
    params=[
        pytest.param("fake", id="fake"),
        pytest.param(
            "gmail",
            id="gmail",
            marks=pytest.mark.skipif(
                not _gmail_available(),
                reason=(
                    "set RUN_LIVE_GMAIL_CONTRACT_TESTS=1 plus Gmail credentials/token "
                    "to run the live Gmail contract tests (they create a real draft)"
                ),
            ),
        ),
        pytest.param(
            "imap",
            id="imap",
            marks=pytest.mark.skipif(
                not _imap_available(),
                reason=(
                    "set RUN_LIVE_IMAP_CONTRACT_TESTS=1 plus IMAP_HOST/SMTP_HOST/IMAP_USERNAME/"
                    "IMAP_PASSWORD to run the live IMAP contract tests (they create a real draft "
                    "and send a real message)"
                ),
            ),
        ),
    ]
)
def provider(request: pytest.FixtureRequest) -> EmailProvider:
    if request.param == "fake":
        return FakeEmailProvider()
    if request.param == "gmail":
        return _gmail_contract_provider()
    return _imap_contract_provider()
