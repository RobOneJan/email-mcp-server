"""Security helpers shared by the MCP tool boundary.

Two concerns live here:
1. Input bounds - tool arguments come from an LLM and must never be trusted
   to be well-behaved (a huge `limit`, an absurdly long body, etc.).
2. Redaction - a single place that knows which fields/keys are sensitive, so
   logging and audit code can't accidentally forget one.
"""

from __future__ import annotations

from typing import Any

MAX_SEARCH_LIMIT = 200
MAX_SUBJECT_LENGTH = 998  # RFC 5322 practical header line limit
MAX_BODY_LENGTH = 200_000
MAX_ID_LENGTH = 512
# Attachment content is returned to an LLM caller as base64 (~1.37x size) in a
# single tool result; 512 KiB comfortably covers a typical invoice/receipt PDF
# while blocking anything large enough to flood the caller's context.
MAX_ATTACHMENT_SIZE_BYTES = 512_000

_SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "token",
    "password",
    "client_secret",
    "body",
    "body_text",
    "body_html",
    "authorization",
}


def clamp_limit(limit: int, *, maximum: int = MAX_SEARCH_LIMIT) -> int:
    """Clamp a caller-supplied page size into a safe, always-positive range."""
    return max(1, min(limit, maximum))


def redact(data: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of `data` with known-sensitive keys masked.

    Used before anything derived from tool calls/provider payloads is passed
    to a logger. Domain email bodies and OAuth tokens must never appear in
    application logs (they may still live in the approval store, which is a
    separate, purpose-built, non-log persistence path for human review).
    """
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in _SENSITIVE_KEYS:
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted
