#!/usr/bin/env python3
"""One-time interactive IMAP/SMTP credential intake for one tenant's mailbox.

Unlike Gmail, plain IMAP/SMTP has no OAuth - there is no consent flow to run,
only a username/password (or app-specific password) to store. Run this once
per mailbox you're onboarding (the server's own `DEFAULT_TENANT_ID` mailbox
still comes from `IMAP_*` environment variables, not this script - see
.env.example - this is for *additional* tenants, e.g. a friend's mailbox
reachable only via a shared Telegram bot).

The password is read via getpass (never echoed, never logged, never passed
as a CLI argument) and stored through the same TokenStore Gmail's OAuth
tokens use, keyed by --tenant - see `providers/factory.py` for how a
tenant's stored record is told apart from a Gmail one (by which fields are
present, not an explicit "provider" field).

Usage:
    python scripts/imap_auth.py --tenant friend-name
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from email_mcp.domain.identity import DEFAULT_TENANT_ID, validate_tenant_id
from email_mcp.infrastructure.config import get_settings
from email_mcp.infrastructure.token_store_file import FileTokenStore


def _prompt(label: str, *, default: str | None = None, required: bool = True) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if not value and default is not None:
            return default
        if value or not required:
            return value
        print("This value is required.")


def _prompt_int(label: str, *, default: int) -> int:
    raw = _prompt(label, default=str(default))
    try:
        return int(raw)
    except ValueError:
        print(f"Not a number, using default {default}.")
        return default


def _prompt_bool(label: str, *, default: bool) -> bool:
    raw = _prompt(label, default="y" if default else "n").strip().lower()
    return raw in ("y", "yes", "true", "1")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--tenant",
        required=True,
        help=(
            "Tenant id to store this mailbox's credentials under. Must differ from "
            f"{DEFAULT_TENANT_ID!r} (that tenant's mailbox is configured via IMAP_* "
            "environment variables instead - see .env.example)."
        ),
    )
    args = parser.parse_args()

    tenant_id = validate_tenant_id(args.tenant)
    if tenant_id == DEFAULT_TENANT_ID:
        print(
            f"--tenant cannot be {DEFAULT_TENANT_ID!r} - that mailbox is configured via "
            "IMAP_* environment variables (see .env.example), not this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Onboarding a new IMAP/SMTP mailbox for tenant_id={tenant_id!r}.\n")
    imap_host = _prompt("IMAP host (e.g. imap.example.com)")
    imap_port = _prompt_int("IMAP port", default=993)
    smtp_host = _prompt("SMTP host (e.g. smtp.example.com)", default=imap_host)
    smtp_port = _prompt_int("SMTP port", default=587)
    smtp_use_ssl = _prompt_bool("Use implicit TLS for SMTP (typically port 465)? y/N", default=False)
    username = _prompt("Username (usually the full email address)")
    password = getpass.getpass("Password (or app-specific password): ")
    if not password:
        print("Password is required.", file=sys.stderr)
        sys.exit(1)
    from_address = _prompt("From: address for outgoing mail", default=username)
    inbox_folder = _prompt("Inbox folder name", default="INBOX")
    drafts_folder = _prompt("Drafts folder name", default="Drafts")
    sent_folder = _prompt("Sent folder name", default="Sent")

    record = {
        "imap_host": imap_host,
        "imap_port": imap_port,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_use_ssl": smtp_use_ssl,
        "username": username,
        "password": password,
        "from_address": from_address,
        "inbox_folder": inbox_folder,
        "drafts_folder": drafts_folder,
        "sent_folder": sent_folder,
    }

    settings = get_settings()
    token_store = FileTokenStore(settings.oauth_token_storage)
    token_store.save(tenant_id, record)

    print(f"\nDone. Credentials stored at {settings.oauth_token_storage}/{tenant_id}.json (owner-read/write only).")
    print(f"This tenant is ready to use as soon as a caller sends X-Tenant-Id: {tenant_id}.")


if __name__ == "__main__":
    main()
