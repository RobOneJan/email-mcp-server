"""Live integration tests against the real Gmail API.

Skipped by default - these require a real Google Cloud OAuth client and a
token obtained via `scripts/gmail_auth.py` against a real (ideally
disposable/test) mailbox. Run explicitly with:

    RUN_LIVE_GMAIL_CONTRACT_TESTS=1 pytest tests/integration -m integration

These overlap in spirit with tests/contract/test_email_provider_contract.py's
`gmail` arm; this file is the place for anything Gmail-specific that doesn't
fit the provider-neutral contract (e.g. asserting on real OAuth error
behavior against Google's servers, or Gmail-specific label semantics).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

_SKIP_REASON = (
    "set RUN_LIVE_GMAIL_CONTRACT_TESTS=1 plus GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET "
    "and a token from scripts/gmail_auth.py to run live Gmail integration tests"
)


def _live_gmail_configured() -> bool:
    return bool(
        os.environ.get("RUN_LIVE_GMAIL_CONTRACT_TESTS")
        and os.environ.get("GOOGLE_CLIENT_ID")
        and os.environ.get("GOOGLE_CLIENT_SECRET")
    )


@pytest.mark.skipif(not _live_gmail_configured(), reason=_SKIP_REASON)
async def test_search_emails_against_real_mailbox() -> None:
    from email_mcp.domain.identity import DEFAULT_TENANT_ID
    from email_mcp.infrastructure.config import get_settings
    from email_mcp.infrastructure.token_store_file import FileTokenStore
    from email_mcp.providers.factory import get_email_provider

    settings = get_settings()
    provider = get_email_provider(settings, DEFAULT_TENANT_ID, FileTokenStore(settings.oauth_token_storage))
    results = await provider.search_emails(limit=5)
    assert isinstance(results, list)
