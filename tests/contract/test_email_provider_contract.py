"""Contract tests: FakeEmailProvider and GmailEmailProvider must satisfy the
same observable behavior for anything the application layer relies on. Only
assertions true for *any* correct EmailProvider belong here - no seeded-data
specifics (those live in tests/unit/test_fake_provider.py).
"""

from __future__ import annotations

import pytest

from email_mcp.domain.errors import EmailNotFoundError
from email_mcp.domain.models import EmailAddress
from email_mcp.ports.email_provider import EmailProvider

# NOTE: no module-level `integration` mark here - the `fake` arm of the
# `provider` fixture must run as part of the default `pytest` invocation
# (see README/plan verification). Only the `gmail` arm is gated, via the
# skipif on that fixture param in conftest.py.


async def test_create_draft_roundtrips_through_get_draft(provider: EmailProvider) -> None:
    draft = await provider.create_draft(
        to=[EmailAddress(email="alice@example.com", name="Alice")],
        subject="Contract test draft",
        body_text="This is a contract test draft body.",
    )

    fetched = await provider.get_draft(draft.id)

    assert fetched.id == draft.id
    assert fetched.subject == "Contract test draft"
    assert fetched.body_text.strip() == "This is a contract test draft body."
    assert fetched.to == draft.to


async def test_get_draft_for_unknown_id_raises_not_found(provider: EmailProvider) -> None:
    with pytest.raises(EmailNotFoundError):
        await provider.get_draft("definitely-does-not-exist")


async def test_get_email_for_unknown_id_raises_not_found(provider: EmailProvider) -> None:
    with pytest.raises(EmailNotFoundError):
        await provider.get_email("definitely-does-not-exist")


async def test_search_emails_returns_metadata_shaped_results(provider: EmailProvider) -> None:
    results = await provider.search_emails(limit=3)
    if not results:
        pytest.skip("mailbox has no messages to search")
    for item in results:
        assert item.id
        assert isinstance(item.subject, str)
        assert not hasattr(item, "body_text")  # metadata is body-free by design


async def test_get_email_matches_a_search_result(provider: EmailProvider) -> None:
    results = await provider.search_emails(limit=1)
    if not results:
        pytest.skip("mailbox has no messages to fetch")
    email = await provider.get_email(results[0].id)
    assert email.id == results[0].id
    assert isinstance(email.body_text, str)


async def test_get_attachment_for_unknown_id_raises_not_found(provider: EmailProvider) -> None:
    with pytest.raises(EmailNotFoundError):
        await provider.get_attachment("definitely-does-not-exist", "also-not-real")


async def test_get_attachment_matches_its_own_metadata(provider: EmailProvider) -> None:
    results = await provider.search_emails(limit=20)
    email_with_attachment = None
    attachment_meta = None
    for summary in results:
        email = await provider.get_email(summary.id)
        if email.attachments:
            email_with_attachment = email
            attachment_meta = email.attachments[0]
            break
    if email_with_attachment is None or attachment_meta is None:
        pytest.skip("mailbox has no email with an attachment to fetch")

    content = await provider.get_attachment(email_with_attachment.id, attachment_meta.id)

    assert content.filename == attachment_meta.filename
    assert content.content_type == attachment_meta.content_type
    assert isinstance(content.data, bytes)


async def test_create_draft_then_send_produces_a_gettable_sent_email(
    provider: EmailProvider,
) -> None:
    draft = await provider.create_draft(
        to=[EmailAddress(email="alice@example.com", name="Alice")],
        subject="Contract test send",
        body_text="Sent by the provider contract test suite.",
    )
    sent_id = await provider.send_draft(draft.id)

    sent = await provider.get_email(sent_id)
    assert sent.subject == "Contract test send"

    with pytest.raises(EmailNotFoundError):
        await provider.get_draft(draft.id)  # a sent draft is no longer a pending draft
