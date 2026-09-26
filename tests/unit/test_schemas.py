"""EmailDTO is the actual LLM-facing shape (see schemas.py's own docstring on
why it's kept distinct from the domain model) - these tests guard the two
token-hygiene rules applied there: no `body_html` ever reaches an LLM
caller, and a read body is bounded even when the source mailbox isn't."""

from __future__ import annotations

from datetime import UTC, datetime

from email_mcp.domain.models import Email, EmailAddress
from email_mcp.infrastructure.security import MAX_READ_BODY_LENGTH
from email_mcp.mcp.schemas import EmailDTO


def _email(body_text: str, body_html: str | None = None) -> Email:
    return Email(
        id="msg-1",
        thread_id=None,
        sender=EmailAddress(email="alice@example.com", name="Alice"),
        recipients=[],
        cc=[],
        subject="Hi",
        body_text=body_text,
        body_html=body_html,
        attachments=[],
        received_at=datetime.now(UTC),
        is_read=True,
    )


def test_email_dto_never_exposes_body_html() -> None:
    dto = EmailDTO.from_domain(_email("short body", body_html="<p>short body</p>"))
    assert "body_html" not in dto.model_dump()
    assert not hasattr(dto, "body_html")


def test_email_dto_keeps_a_short_body_unchanged() -> None:
    dto = EmailDTO.from_domain(_email("short body"))
    assert dto.body_text == "short body"


def test_email_dto_truncates_a_body_over_the_read_limit() -> None:
    long_body = "x" * (MAX_READ_BODY_LENGTH + 500)

    dto = EmailDTO.from_domain(_email(long_body))

    assert len(dto.body_text) < len(long_body)
    assert dto.body_text.startswith("x" * 100)
    assert f"{len(long_body)} characters total" in dto.body_text


def test_email_dto_does_not_truncate_exactly_at_the_limit() -> None:
    exact_body = "x" * MAX_READ_BODY_LENGTH
    dto = EmailDTO.from_domain(_email(exact_body))
    assert dto.body_text == exact_body
