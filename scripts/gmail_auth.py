#!/usr/bin/env python3
"""One-time interactive Gmail OAuth 2.0 consent flow.

Run this once (and again whenever the refresh token is revoked/expired). It
opens a browser for you to sign in and grant access, then stores the
resulting token via the configured TokenStore - never printed, never logged.

Usage:
    python scripts/gmail_auth.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from email_mcp.domain.identity import DEFAULT_TENANT_ID
from email_mcp.infrastructure.config import get_settings
from email_mcp.infrastructure.token_store_file import FileTokenStore
from email_mcp.providers.gmail.auth import GmailAuth


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant",
        default=DEFAULT_TENANT_ID,
        help=(
            f"Tenant id to store this mailbox's token under (default: {DEFAULT_TENANT_ID!r}). "
            "Use a distinct value per connected mailbox once onboarding more than one."
        ),
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        print(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set (see .env.example) "
            "before running this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    auth = GmailAuth(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=settings.google_redirect_uri,
        token_store=FileTokenStore(settings.oauth_token_storage),
        tenant_id=args.tenant,
    )
    print("Opening a browser to complete Gmail OAuth consent...")
    auth.run_installed_app_flow()
    print(f"Done. Token stored at {settings.oauth_token_storage}/{args.tenant}.json.")
    print("Set EMAIL_PROVIDER=gmail in your .env to use it.")


if __name__ == "__main__":
    main()
