"""Unit tests for ImapEmailProvider against an in-memory fake of
ImapSmtpClient (see FakeImapSmtpClient below) - there is no live IMAP/SMTP
server in this environment. This exercises the provider's own logic (id
encoding, reply threading, draft-to-sent handoff, error translation)
end-to-end without needing a real server; tests/contract's "imap" arm covers
the same contract against a real mailbox once credentials are available.
"""

from __future__ import annotations

import re

import pytest

from email_mcp.domain.errors import EmailNotFoundError, ProviderAuthError, ProviderUnavailableError
from email_mcp.domain.models import EmailAddress
from email_mcp.providers.imap.client import ImapNotFoundError
from email_mcp.providers.imap.provider import ImapEmailProvider

FROM_ADDRESS = "me@example.com"


class FakeImapSmtpClient:
    """In-memory stand-in for ImapSmtpClient, keyed the same way a real IMAP
    server would be: {folder: {uid: (raw_bytes, flags)}}. Only understands
    the small set of SEARCH criteria strings provider.py actually emits."""

    def __init__(self) -> None:
        self.folders: dict[str, dict[int, tuple[bytes, set[str]]]] = {}
        self._next_uid = 1
        self.sent: list[tuple[bytes, str, list[str]]] = []

    def seed(self, folder: str, raw: bytes, flags: set[str] | None = None) -> int:
        uid = self._next_uid
        self._next_uid += 1
        self.folders.setdefault(folder, {})[uid] = (raw, flags or set())
        return uid

    def search(self, folder: str, criteria: str) -> list[int]:
        messages = self.folders.get(folder, {})
        if criteria == "ALL":
            return list(messages.keys())
        quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', criteria)
        if not quoted:
            raise AssertionError(f"FakeImapSmtpClient does not understand criteria: {criteria!r}")
        target = quoted[0].encode()
        return [uid for uid, (raw, _flags) in messages.items() if target in raw]

    def fetch_message(self, folder: str, uid: int) -> tuple[bytes, set[str]]:
        try:
            return self.folders[folder][uid]
        except KeyError:
            raise ImapNotFoundError(f"no uid={uid} in {folder!r}") from None

    def append_and_locate(self, folder: str, raw_message: bytes, message_id: str) -> int:
        return self.seed(folder, raw_message)

    def set_flag(self, folder: str, uid: int, flag: str, add: bool) -> None:
        raw, flags = self.fetch_message(folder, uid)
        flags = set(flags)
        (flags.add if add else flags.discard)(flag)
        self.folders[folder][uid] = (raw, flags)

    def delete(self, folder: str, uid: int) -> None:
        self.folders.get(folder, {}).pop(uid, None)

    def send(self, raw_message: bytes, from_addr: str, to_addrs: list[str]) -> None:
        self.sent.append((raw_message, from_addr, to_addrs))


@pytest.fixture
def client() -> FakeImapSmtpClient:
    return FakeImapSmtpClient()


@pytest.fixture
def provider(client: FakeImapSmtpClient) -> ImapEmailProvider:
    return ImapEmailProvider(client=client, from_address=FROM_ADDRESS)  # type: ignore[arg-type]


async def test_create_draft_roundtrips_through_get_draft(provider: ImapEmailProvider) -> None:
    draft = await provider.create_draft(
        to=[EmailAddress(email="alice@example.com", name="Alice")],
        subject="Contract test draft",
        body_text="This is a contract test draft body.",
    )
    assert draft.id.startswith("drafts:")

    fetched = await provider.get_draft(draft.id)
    assert fetched.id == draft.id
    assert fetched.subject == "Contract test draft"
    assert fetched.body_text.strip() == "This is a contract test draft body."
    assert fetched.to == draft.to


async def test_get_draft_for_unknown_id_raises_not_found(provider: ImapEmailProvider) -> None:
    with pytest.raises(EmailNotFoundError):
        await provider.get_draft("drafts:9999")


async def test_get_draft_for_a_non_draft_id_raises_not_found(
    provider: ImapEmailProvider, client: FakeImapSmtpClient
) -> None:
    uid = client.seed("INBOX", b"From: a@example.com\r\n\r\nhi")
    with pytest.raises(EmailNotFoundError):
        await provider.get_draft(f"inbox:{uid}")


async def test_get_email_for_unknown_id_raises_not_found(provider: ImapEmailProvider) -> None:
    with pytest.raises(EmailNotFoundError):
        await provider.get_email("inbox:9999")


async def test_get_email_for_a_malformed_id_raises_not_found(provider: ImapEmailProvider) -> None:
    with pytest.raises(EmailNotFoundError):
        await provider.get_email("not-a-valid-id")


async def test_search_emails_returns_metadata_shaped_results(
    provider: ImapEmailProvider, client: FakeImapSmtpClient
) -> None:
    client.seed("INBOX", b"From: a@example.com\r\nSubject: Hi\r\n\r\nbody")
    results = await provider.search_emails(limit=3)
    assert results
    for item in results:
        assert item.id
        assert isinstance(item.subject, str)
        assert not hasattr(item, "body_text")


async def test_get_email_matches_a_search_result(provider: ImapEmailProvider, client: FakeImapSmtpClient) -> None:
    client.seed("INBOX", b"From: a@example.com\r\nSubject: Hi\r\n\r\nbody text")
    results = await provider.search_emails(limit=1)
    email = await provider.get_email(results[0].id)
    assert email.id == results[0].id
    assert "body text" in email.body_text


async def test_create_draft_then_send_produces_a_gettable_sent_email(
    provider: ImapEmailProvider, client: FakeImapSmtpClient
) -> None:
    draft = await provider.create_draft(
        to=[EmailAddress(email="alice@example.com", name="Alice")],
        subject="Contract test send",
        body_text="Sent by the provider test suite.",
    )
    sent_id = await provider.send_draft(draft.id)
    assert sent_id.startswith("sent:")

    sent = await provider.get_email(sent_id)
    assert sent.subject == "Contract test send"
    assert len(client.sent) == 1

    with pytest.raises(EmailNotFoundError):
        await provider.get_draft(draft.id)  # a sent draft is no longer a pending draft


async def test_send_draft_of_unknown_id_raises_not_found(provider: ImapEmailProvider) -> None:
    with pytest.raises(EmailNotFoundError):
        await provider.send_draft("drafts:12345")


async def test_reply_chains_in_reply_to_and_references(
    provider: ImapEmailProvider, client: FakeImapSmtpClient
) -> None:
    original = await provider.create_draft(
        to=[EmailAddress(email="alice@example.com")], subject="Original", body_text="Hi"
    )
    sent_id = await provider.send_draft(original.id)

    reply = await provider.create_draft(
        to=[EmailAddress(email="alice@example.com")],
        subject="Re: Original",
        body_text="Following up",
        reply_to_email_id=sent_id,
    )
    reply_id = await provider.send_draft(reply.id)

    sent_original = await provider.get_email(sent_id)
    sent_reply = await provider.get_email(reply_id)
    assert sent_reply.thread_id == sent_original.thread_id


async def test_get_thread_returns_all_messages_in_a_reply_chain(
    provider: ImapEmailProvider, client: FakeImapSmtpClient
) -> None:
    original = await provider.create_draft(
        to=[EmailAddress(email="alice@example.com")], subject="Original", body_text="Hi"
    )
    original_sent_id = await provider.send_draft(original.id)
    reply = await provider.create_draft(
        to=[EmailAddress(email="alice@example.com")],
        subject="Re: Original",
        body_text="Following up",
        reply_to_email_id=original_sent_id,
    )
    await provider.send_draft(reply.id)

    original_email = await provider.get_email(original_sent_id)
    thread = await provider.get_thread(original_email.thread_id)

    assert len(thread.emails) == 2
    assert thread.subject == "Original"


async def test_get_thread_for_unknown_id_raises_not_found(provider: ImapEmailProvider) -> None:
    with pytest.raises(EmailNotFoundError):
        await provider.get_thread("<does-not-exist@example.com>")


async def test_mark_as_read_sets_seen_flag(provider: ImapEmailProvider, client: FakeImapSmtpClient) -> None:
    uid = client.seed("INBOX", b"From: a@example.com\r\nSubject: Hi\r\n\r\nbody")
    email_id = f"inbox:{uid}"

    before = await provider.get_email(email_id)
    assert before.is_read is False

    await provider.mark_as_read(email_id)

    after = await provider.get_email(email_id)
    assert after.is_read is True


async def test_get_attachment_for_unknown_id_raises_not_found(provider: ImapEmailProvider) -> None:
    with pytest.raises(EmailNotFoundError):
        await provider.get_attachment("inbox:9999", "0")


async def test_get_attachment_matches_its_own_metadata(
    provider: ImapEmailProvider, client: FakeImapSmtpClient
) -> None:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "a@example.com"
    msg["Subject"] = "Invoice"
    msg.set_content("see attached")
    msg.add_attachment(b"%PDF fake bytes", maintype="application", subtype="pdf", filename="invoice.pdf")
    uid = client.seed("INBOX", msg.as_bytes())
    email = await provider.get_email(f"inbox:{uid}")
    attachment_meta = email.attachments[0]

    content = await provider.get_attachment(email.id, attachment_meta.id)

    assert content.filename == "invoice.pdf"
    assert content.content_type == "application/pdf"
    assert content.data == b"%PDF fake bytes"


async def test_get_attachment_for_unknown_attachment_id_raises_not_found(
    provider: ImapEmailProvider, client: FakeImapSmtpClient
) -> None:
    uid = client.seed("INBOX", b"From: a@example.com\r\nSubject: Hi\r\n\r\nno attachments here")
    with pytest.raises(EmailNotFoundError):
        await provider.get_attachment(f"inbox:{uid}", "0")


async def test_imap_auth_failure_is_translated_to_provider_auth_error() -> None:
    import imaplib

    class RaisingClient(FakeImapSmtpClient):
        def search(self, folder: str, criteria: str) -> list[int]:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")

    provider = ImapEmailProvider(client=RaisingClient(), from_address=FROM_ADDRESS)  # type: ignore[arg-type]
    with pytest.raises(ProviderAuthError):
        await provider.search_emails()


async def test_imap_command_failure_is_translated_to_provider_unavailable_error() -> None:
    import imaplib

    class RaisingClient(FakeImapSmtpClient):
        def search(self, folder: str, criteria: str) -> list[int]:
            raise imaplib.IMAP4.error("mailbox temporarily unavailable")

    provider = ImapEmailProvider(client=RaisingClient(), from_address=FROM_ADDRESS)  # type: ignore[arg-type]
    with pytest.raises(ProviderUnavailableError):
        await provider.search_emails()
