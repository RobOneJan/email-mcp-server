"""Provider-neutral enumerations used throughout the domain and application layers."""

from __future__ import annotations

from enum import StrEnum


class ApprovalStatus(StrEnum):
    """Lifecycle of a human approval request for a sensitive action (e.g. sending email)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    # Set once an APPROVED request has been used to perform its action, so it
    # can never be replayed to trigger a second send.
    CONSUMED = "consumed"


class EmailProviderName(StrEnum):
    """Selects which EmailProvider adapter the application wires up at startup."""

    FAKE = "fake"
    GMAIL = "gmail"
    IMAP = "imap"
    # MICROSOFT_GRAPH = "microsoft_graph"  # future
