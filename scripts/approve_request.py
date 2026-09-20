#!/usr/bin/env python3
"""Human-only CLI to review and decide on pending send approvals.

This is the ONLY place in the whole system that can move an ApprovalRequest
from PENDING to APPROVED/REJECTED. It is deliberately a standalone script, not
an MCP tool - the LLM driving the MCP server has no way to invoke it, which is
what makes "human approval" actually mean a human decided, not the agent.

Usage:
    python scripts/approve_request.py list
    python scripts/approve_request.py show <approval_id>
    python scripts/approve_request.py approve <approval_id>
    python scripts/approve_request.py reject <approval_id>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from datetime import timedelta

from email_mcp.application.approval_service import ApprovalService
from email_mcp.domain.errors import ApprovalError
from email_mcp.infrastructure.approval_store_file import FileApprovalStore
from email_mcp.infrastructure.config import get_settings


def build_service() -> ApprovalService:
    settings = get_settings()
    store = FileApprovalStore(settings.approval_store_path)
    return ApprovalService(store, ttl=timedelta(minutes=settings.approval_ttl_minutes))


def cmd_list(service: ApprovalService, _args: argparse.Namespace) -> None:
    pending = service.list_pending()
    if not pending:
        print("No pending approval requests.")
        return
    for req in pending:
        print(f"{req.id}  action={req.action}  resource={req.resource_id}  expires={req.expires_at}")


def cmd_show(service: ApprovalService, args: argparse.Namespace) -> None:
    req = service.get_status(args.approval_id)
    print(f"id:        {req.id}")
    print(f"action:    {req.action}")
    print(f"resource:  {req.resource_id}")
    print(f"status:    {req.status}")
    print(f"created:   {req.created_at}")
    print(f"expires:   {req.expires_at}")
    print("--- content for review ---")
    for key, value in req.payload.items():
        print(f"{key}: {value}")


def cmd_decide(service: ApprovalService, args: argparse.Namespace, *, approve: bool) -> None:
    req = service.decide(args.approval_id, approve=approve)
    verb = "APPROVED" if approve else "REJECTED"
    print(f"{req.id} is now {verb} ({req.status}).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List pending approval requests.")

    show_parser = sub.add_parser("show", help="Show the full details of one approval request.")
    show_parser.add_argument("approval_id")

    approve_parser = sub.add_parser("approve", help="Approve a pending request.")
    approve_parser.add_argument("approval_id")

    reject_parser = sub.add_parser("reject", help="Reject a pending request.")
    reject_parser.add_argument("approval_id")

    args = parser.parse_args()
    service = build_service()

    try:
        if args.command == "list":
            cmd_list(service, args)
        elif args.command == "show":
            cmd_show(service, args)
        elif args.command == "approve":
            cmd_decide(service, args, approve=True)
        elif args.command == "reject":
            cmd_decide(service, args, approve=False)
    except ApprovalError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
