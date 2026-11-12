"""Graph listing: slim fields, odd senders, retries on outages."""

from __future__ import annotations

import pytest
import requests

from email_mcp.providers.graph import client as graph_client
from email_mcp.providers.graph.mapper import SUMMARY_FIELDS, graph_message_to_metadata


def _message(**overrides) -> dict:
    message = {
        "id": "m1",
        "conversationId": "c1",
        "subject": "Rechnung 6089443652",
        "from": {"emailAddress": {"address": "rechnung@wuerth.de", "name": "Würth"}},
        "receivedDateTime": "2026-11-12T07:30:00Z",
        "isRead": False,
        "bodyPreview": "Sehr geehrte Damen und Herren, anbei Ihre Rechnung",
        "hasAttachments": True,
    }
    message.update(overrides)
    return message


def test_listing_entry_has_preview_and_attachment_flag() -> None:
    metadata = graph_message_to_metadata(_message())
    assert metadata.has_attachments is True
    assert metadata.snippet.startswith("Sehr geehrte")  # also for HTML mails, from bodyPreview
    assert metadata.sender.email == "rechnung@wuerth.de"


@pytest.mark.parametrize(
    "sender",
    [
        {"emailAddress": {"address": "/O=EXCHANGELABS/OU=EXCHANGE ADMINISTRATIVE GROUP/CN=RECIPIENTS/CN=SVEN", "name": "Sven"}},
        {"emailAddress": {"address": "MAILER-DAEMON", "name": None}},
        {"emailAddress": {}},
        None,
    ],
)
def test_odd_senders_do_not_break_the_listing(sender) -> None:
    metadata = graph_message_to_metadata(_message(**{"from": sender}))
    assert metadata.sender.email == "unknown@unknown.example"


def test_odd_sender_keeps_a_name_to_show() -> None:
    metadata = graph_message_to_metadata(_message(**{"from": {"emailAddress": {"address": "MAILER-DAEMON"}}}))
    assert metadata.sender.name == "MAILER-DAEMON"


class _Auth:
    def get_access_token(self) -> str:
        return "t"


def _response(status: int, json: dict | None = None, headers: dict | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = (__import__("json").dumps(json or {})).encode()
    response.headers.update(headers or {})
    return response


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list:
    monkeypatch.setattr(graph_client.time, "sleep", lambda seconds: None)
    return []


def _client(monkeypatch: pytest.MonkeyPatch, calls: list, answers: list) -> graph_client.GraphClient:
    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("params")))
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(graph_client.requests, "request", fake_request)
    return graph_client.GraphClient(_Auth())


def test_listing_asks_only_for_summary_fields(monkeypatch: pytest.MonkeyPatch, calls: list) -> None:
    client = _client(monkeypatch, calls, [_response(200, {"value": [_message()]})])
    assert client.list_messages(None, 50)[0]["id"] == "m1"
    assert calls[0][2]["$select"] == SUMMARY_FIELDS
    assert "body" not in SUMMARY_FIELDS.split(",")


def test_listing_retries_a_graph_outage(monkeypatch: pytest.MonkeyPatch, calls: list) -> None:
    client = _client(
        monkeypatch, calls, [_response(503), requests.Timeout("slow"), _response(200, {"value": [_message()]})]
    )
    assert len(client.list_messages(None, 50)) == 1
    assert len(calls) == 3


def test_listing_gives_up_after_three_attempts(monkeypatch: pytest.MonkeyPatch, calls: list) -> None:
    client = _client(monkeypatch, calls, [_response(503), _response(503), _response(503)])
    with pytest.raises(requests.HTTPError):
        client.list_messages(None, 50)
    assert len(calls) == 3


def test_writes_are_not_retried(monkeypatch: pytest.MonkeyPatch, calls: list) -> None:
    client = _client(monkeypatch, calls, [_response(503)])
    with pytest.raises(requests.HTTPError):
        client.create_draft({"subject": "x"})
    assert len(calls) == 1


def test_placeholder_address_is_itself_valid() -> None:
    from email_mcp.domain.models import EmailAddress

    EmailAddress(email="unknown@unknown.example")
