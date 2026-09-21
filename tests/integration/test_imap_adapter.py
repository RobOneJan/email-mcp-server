"""Live integration tests against a real IMAP/SMTP mailbox.

Skipped by default - these require a real mailbox's IMAP/SMTP host and
credentials (see .env.example). Run explicitly with:

    RUN_LIVE_IMAP_CONTRACT_TESTS=1 pytest tests/integration -m integration

These overlap in spirit with tests/contract/test_email_provider_contract.py's
`imap` arm; this file is the place for anything IMAP-specific that doesn't
fit the provider-neutral contract (e.g. real folder-name/auth-error behavior
against a specific host).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

_SKIP_REASON = (
    "set RUN_LIVE_IMAP_CONTRACT_TESTS=1 plus IMAP_HOST/SMTP_HOST/IMAP_USERNAME/IMAP_PASSWORD "
    "to run live IMAP integration tests"
)


def _live_imap_configured() -> bool:
    return bool(
        os.environ.get("RUN_LIVE_IMAP_CONTRACT_TESTS")
        and os.environ.get("IMAP_HOST")
        and os.environ.get("SMTP_HOST")
        and os.environ.get("IMAP_USERNAME")
        and os.environ.get("IMAP_PASSWORD")
    )


@pytest.mark.skipif(not _live_imap_configured(), reason=_SKIP_REASON)
async def test_search_emails_against_real_mailbox() -> None:
    from email_mcp.domain.identity import DEFAULT_TENANT_ID
    from email_mcp.infrastructure.config import get_settings
    from email_mcp.infrastructure.token_store_file import FileTokenStore
    from email_mcp.providers.factory import get_email_provider

    settings = get_settings()
    provider = get_email_provider(settings, DEFAULT_TENANT_ID, FileTokenStore(settings.oauth_token_storage))
    results = await provider.search_emails(limit=5)
    assert isinstance(results, list)
