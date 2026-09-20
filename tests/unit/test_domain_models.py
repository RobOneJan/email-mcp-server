from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from email_mcp.domain.models import Email, EmailAddress


def _address(email: str = "alice@example.com") -> EmailAddress:
    return EmailAddress(email=email, name="Alice")


def test_email_address_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        EmailAddress(email="not-an-email")


def test_email_to_metadata_strips_body_and_truncates_snippet() -> None:
    email = Email(
        id="msg-1",
        thread_id="thread-1",
        sender=_address(),
        recipients=[_address("bob@example.com")],
        subject="Hello",
        body_text="x" * 500,
        received_at=datetime.now(UTC),
        is_read=False,
    )
    metadata = email.to_metadata()

    assert metadata.id == email.id
    assert metadata.subject == email.subject
    assert len(metadata.snippet) == 200
    assert not hasattr(metadata, "body_text")


def test_domain_models_are_frozen() -> None:
    email = Email(
        id="msg-1",
        sender=_address(),
        subject="Hello",
        body_text="hi",
        received_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError):
        email.is_read = True  # type: ignore[misc]


def test_email_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Email(
            id="msg-1",
            sender=_address(),
            subject="Hello",
            body_text="hi",
            received_at=datetime.now(UTC),
            gmail_label_ids=["INBOX"],  # provider-specific field must never leak in
        )
