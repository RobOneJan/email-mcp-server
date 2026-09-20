"""Structured logging setup with built-in secret/content redaction.

Application code should log short, structured messages (ids, counts, status)
via `log()` below, passing context as keyword args - never raw email bodies
or OAuth tokens. As a second line of defense, `RedactingFilter` masks any
known-sensitive key found in that context before it reaches a handler.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from email_mcp.infrastructure.security import redact


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = getattr(record, "context", None)
        record.context_str = f" {redact(context)}" if isinstance(context, dict) and context else ""
        record.context_dict = redact(context) if isinstance(context, dict) and context else {}
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, auto-parsed as structured logs by Cloud Logging.

    Maps `levelname` to Cloud Logging's `severity` field so log-based metrics
    and severity filters in the GCP console work without extra config.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            **getattr(record, "context_dict", {}),
        }
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", format_: str = "text") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.addFilter(RedactingFilter())
    if format_ == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s%(context_str)s"))
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log(logger: logging.Logger, level: int, message: str, **context: Any) -> None:
    """Log `message` with structured `context`, redacted before it reaches any handler."""
    logger.log(level, message, extra={"context": context})
