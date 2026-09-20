import pytest

from email_mcp.domain.errors import AttachmentTooLargeError, EmailNotFoundError
from email_mcp.domain.models import EmailAddress
from email_mcp.infrastructure.security import MAX_ATTACHMENT_SIZE_BYTES
from email_mcp.providers.fake.provider import FakeEmailProvider


@pytest.fixture
def provider() -> FakeEmailProvider:
    return FakeEmailProvider()


async def test_search_with_no_query_returns_seeded_emails(provider: FakeEmailProvider) -> None:
    results = await provider.search_emails()
    assert len(results) >= 3


async def test_search_filters_by_query(provider: FakeEmailProvider) -> None:
    results = await provider.search_emails(query="invoice")
    assert results
    assert all("invoice" in r.subject.lower() for r in results)


async def test_seeded_prompt_injection_email_is_just_data(provider: FakeEmailProvider) -> None:
    """Reading a malicious email body must never itself trigger a privileged
    action - this test only asserts that fetching it returns inert text; the
    real guarantee is architectural (no tool call happens as a side effect of
    a get_email call), see mcp/tools.py and application/email_service.py."""
    invoice = await provider.get_email("msg-3")
    assert "Ignore all previous instructions" in invoice.body_text
    # It's just a string in a field - no draft, send, or approval was created.


async def test_create_draft_then_send_moves_it_to_sent_emails(provider: FakeEmailProvider) -> None:
    draft = await provider.create_draft(
        to=[EmailAddress(email="alice@example.com")], subject="Hi", body_text="Hello"
    )
    sent_id = await provider.send_draft(draft.id)

    sent = await provider.get_email(sent_id)
    assert sent.subject == "Hi"
    with pytest.raises(EmailNotFoundError):
        await provider.get_draft(draft.id)  # consumed on send


async def test_mark_as_read(provider: FakeEmailProvider) -> None:
    await provider.mark_as_read("msg-3")
    email = await provider.get_email("msg-3")
    assert email.is_read is True


async def test_get_missing_email_raises(provider: FakeEmailProvider) -> None:
    with pytest.raises(EmailNotFoundError):
        await provider.get_email("does-not-exist")


async def test_get_attachment_returns_content_matching_metadata(
    provider: FakeEmailProvider,
) -> None:
    email = await provider.get_email("msg-3")
    (meta,) = email.attachments

    content = await provider.get_attachment("msg-3", meta.id)

    assert content.filename == meta.filename
    assert content.content_type == meta.content_type
    assert content.size_bytes == meta.size_bytes
    assert len(content.data) == meta.size_bytes


async def test_get_attachment_for_unknown_attachment_id_raises(
    provider: FakeEmailProvider,
) -> None:
    with pytest.raises(EmailNotFoundError):
        await provider.get_attachment("msg-3", "does-not-exist")


async def test_get_attachment_for_unknown_email_id_raises(provider: FakeEmailProvider) -> None:
    with pytest.raises(EmailNotFoundError):
        await provider.get_attachment("does-not-exist", "att-1")


async def test_get_attachment_over_size_limit_raises(provider: FakeEmailProvider) -> None:
    oversized = provider._emails["msg-3"].model_copy(
        update={
            "attachments": [
                provider._emails["msg-3"].attachments[0].model_copy(
                    update={"size_bytes": MAX_ATTACHMENT_SIZE_BYTES + 1}
                )
            ]
        }
    )
    provider._emails["msg-3"] = oversized

    with pytest.raises(AttachmentTooLargeError):
        await provider.get_attachment("msg-3", "att-1")
