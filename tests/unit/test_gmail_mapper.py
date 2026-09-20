import base64

from email_mcp.domain.models import EmailAddress
from email_mcp.providers.gmail.mapper import (
    build_raw_message,
    decode_b64url_bytes,
    gmail_draft_to_domain,
    gmail_message_to_email,
    gmail_thread_to_domain,
    parse_address_list,
)


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _sample_message(
    message_id: str = "18f0a1", thread_id: str = "18f0a0", unread: bool = True
) -> dict:
    return {
        "id": message_id,
        "threadId": thread_id,
        "labelIds": ["INBOX"] + (["UNREAD"] if unread else []),
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "Bob <bob@example.com>, carol@example.com"},
                {"name": "Subject", "value": "Q3 roadmap"},
                {"name": "Message-ID", "value": "<abc123@mail.gmail.com>"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("Hello Bob")}},
                {
                    "mimeType": "application/pdf",
                    "filename": "roadmap.pdf",
                    "body": {"attachmentId": "att-1", "size": 1234},
                },
            ],
        },
    }


def test_parse_address_list_handles_display_names_and_bare_addresses() -> None:
    addresses = parse_address_list("Bob <bob@example.com>, carol@example.com")
    assert addresses == [
        EmailAddress(email="bob@example.com", name="Bob"),
        EmailAddress(email="carol@example.com", name=None),
    ]


def test_gmail_message_to_email_maps_fields() -> None:
    email = gmail_message_to_email(_sample_message())

    assert email.id == "18f0a1"
    assert email.thread_id == "18f0a0"
    assert email.sender == EmailAddress(email="alice@example.com", name="Alice")
    assert email.recipients == [
        EmailAddress(email="bob@example.com", name="Bob"),
        EmailAddress(email="carol@example.com", name=None),
    ]
    assert email.subject == "Q3 roadmap"
    assert email.body_text == "Hello Bob"
    assert email.is_read is False  # UNREAD label present
    assert len(email.attachments) == 1
    assert email.attachments[0].filename == "roadmap.pdf"
    assert email.attachments[0].id == "att-1"


def test_gmail_message_to_email_is_read_when_no_unread_label() -> None:
    email = gmail_message_to_email(_sample_message(unread=False))
    assert email.is_read is True


def test_gmail_thread_to_domain_orders_by_received_at() -> None:
    older = _sample_message(message_id="m1")
    older["internalDate"] = "1600000000000"
    newer = _sample_message(message_id="m2")
    newer["internalDate"] = "1700000000000"

    thread = gmail_thread_to_domain({"id": "18f0a0", "messages": [newer, older]})

    assert [e.id for e in thread.emails] == ["m1", "m2"]
    assert thread.subject == "Q3 roadmap"


def test_gmail_draft_to_domain_maps_fields() -> None:
    draft_payload = {
        "id": "draft-1",
        "message": {
            "threadId": "18f0a0",
            "internalDate": "1700000000000",
            "payload": {
                "headers": [
                    {"name": "To", "value": "alice@example.com"},
                    {"name": "Subject", "value": "Re: hi"},
                ],
                "mimeType": "text/plain",
                "body": {"data": _b64("Sounds good")},
            },
        },
    }
    draft = gmail_draft_to_domain("draft-1", draft_payload)

    assert draft.id == "draft-1"
    assert draft.thread_id == "18f0a0"
    assert draft.to == [EmailAddress(email="alice@example.com", name=None)]
    assert draft.subject == "Re: hi"
    assert draft.body_text == "Sounds good"


def test_decode_b64url_bytes_roundtrips_binary_data() -> None:
    # Bytes that are not valid UTF-8 (e.g. a PDF's magic number/binary body)
    # must survive intact - unlike the text-oriented `_decode_b64url`, this
    # must never attempt a text decode.
    raw = b"%PDF-1.4\xff\xfe\x00binary"
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")  # unpadded, like Gmail
    assert decode_b64url_bytes(encoded) == raw


def test_build_raw_message_is_valid_base64_and_contains_headers() -> None:
    raw = build_raw_message(
        to=[EmailAddress(email="alice@example.com", name="Alice")],
        subject="Hello",
        body_text="Hi there",
        in_reply_to_message_id="<abc123@mail.gmail.com>",
    )
    decoded = base64.urlsafe_b64decode(raw).decode("utf-8")

    assert "To: Alice <alice@example.com>" in decoded
    assert "Subject: Hello" in decoded
    assert "In-Reply-To: <abc123@mail.gmail.com>" in decoded
    assert "Hi there" in decoded
