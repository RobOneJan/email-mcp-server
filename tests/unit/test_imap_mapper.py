from __future__ import annotations

from email.message import EmailMessage

import pytest

from email_mcp.domain.models import EmailAddress
from email_mcp.providers.imap.mapper import (
    UnknownIdError,
    build_raw_message,
    decode_id,
    encode_id,
    extract_attachment_bytes,
    imap_message_to_draft,
    imap_message_to_email,
    message_id_and_references,
    parse_address_list,
)


def test_encode_decode_id_roundtrips() -> None:
    assert decode_id(encode_id("inbox", 1042)) == ("inbox", 1042)


@pytest.mark.parametrize("bad_id", ["not-an-id", "inbox:", "inbox:abc", ""])
def test_decode_id_rejects_malformed_ids(bad_id: str) -> None:
    with pytest.raises(UnknownIdError):
        decode_id(bad_id)


def test_parse_address_list_handles_display_names_and_bare_addresses() -> None:
    addresses = parse_address_list("Bob <bob@example.com>, carol@example.com")
    assert addresses == [
        EmailAddress(email="bob@example.com", name="Bob"),
        EmailAddress(email="carol@example.com", name=None),
    ]


def _sample_message(
    *,
    to: str = "Bob <bob@example.com>",
    subject: str = "Q3 roadmap",
    body: str = "Hello Bob",
    message_id: str = "<abc123@example.com>",
    references: str | None = None,
    in_reply_to: str | None = None,
    with_attachment: bool = False,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = "Alice <alice@example.com>"
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Date"] = "Tue, 1 Jul 2025 10:00:00 +0000"
    if references:
        msg["References"] = references
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    msg.set_content(body)
    if with_attachment:
        msg.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="invoice.pdf")
    return msg.as_bytes()


def test_imap_message_to_email_maps_fields() -> None:
    email = imap_message_to_email("inbox:1", _sample_message(), flags=set())

    assert email.id == "inbox:1"
    assert email.sender == EmailAddress(email="alice@example.com", name="Alice")
    assert email.recipients == [EmailAddress(email="bob@example.com", name="Bob")]
    assert email.subject == "Q3 roadmap"
    assert email.body_text.strip() == "Hello Bob"
    assert email.is_read is False


def test_imap_message_to_email_is_read_reflects_seen_flag() -> None:
    email = imap_message_to_email("inbox:1", _sample_message(), flags={"\\Seen"})
    assert email.is_read is True


def test_thread_id_falls_back_through_references_in_reply_to_then_message_id() -> None:
    root = imap_message_to_email("inbox:1", _sample_message(message_id="<root@example.com>"), set())
    assert root.thread_id == "<root@example.com>"

    reply = imap_message_to_email(
        "inbox:2",
        _sample_message(
            message_id="<reply@example.com>", references="<root@example.com>", in_reply_to="<root@example.com>"
        ),
        set(),
    )
    assert reply.thread_id == "<root@example.com>"


def test_imap_message_to_email_walks_attachments() -> None:
    email = imap_message_to_email("inbox:1", _sample_message(with_attachment=True), flags=set())
    assert len(email.attachments) == 1
    attachment = email.attachments[0]
    assert attachment.id == "0"
    assert attachment.filename == "invoice.pdf"
    assert attachment.content_type == "application/pdf"
    assert attachment.size_bytes > 0


def test_extract_attachment_bytes_matches_the_attachment_id() -> None:
    raw = _sample_message(with_attachment=True)
    data = extract_attachment_bytes(raw, "0")
    assert data == b"%PDF-1.4 fake"


def test_extract_attachment_bytes_raises_key_error_for_unknown_id() -> None:
    with pytest.raises(KeyError):
        extract_attachment_bytes(_sample_message(with_attachment=True), "99")


def test_build_raw_message_sets_headers_and_assigns_a_message_id() -> None:
    raw, message_id = build_raw_message(
        to=[EmailAddress(email="bob@example.com", name="Bob")],
        subject="Hi",
        body_text="Hello",
        cc=[EmailAddress(email="carol@example.com")],
        in_reply_to_message_id="<parent@example.com>",
        references="<root@example.com> <parent@example.com>",
        from_addr="me@example.com",
    )

    assert message_id  # always assigned, never left to the server
    email = imap_message_to_email("drafts:1", raw, flags=set())
    assert email.recipients == [EmailAddress(email="bob@example.com", name="Bob")]
    assert email.cc == [EmailAddress(email="carol@example.com", name=None)]
    assert email.subject == "Hi"
    assert email.body_text.strip() == "Hello"
    assert email.sender == EmailAddress(email="me@example.com", name=None)


def test_message_id_and_references_reads_back_what_was_built() -> None:
    raw, message_id = build_raw_message(
        to=[EmailAddress(email="bob@example.com")],
        subject="Hi",
        body_text="Hello",
        references="<root@example.com>",
    )
    read_message_id, references = message_id_and_references(raw)
    assert read_message_id == message_id
    assert references == "<root@example.com>"


def test_imap_message_to_draft_maps_fields() -> None:
    raw, _message_id = build_raw_message(
        to=[EmailAddress(email="bob@example.com", name="Bob")], subject="Hi", body_text="Hello"
    )
    draft = imap_message_to_draft("drafts:1", raw)
    assert draft.id == "drafts:1"
    assert draft.subject == "Hi"
    assert draft.body_text.strip() == "Hello"
    assert draft.to == [EmailAddress(email="bob@example.com", name="Bob")]
