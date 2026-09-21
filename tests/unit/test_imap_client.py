"""Unit tests for ImapSmtpClient against mocked `imaplib`/`smtplib` - there is
no live IMAP/SMTP server in this environment, so these verify the exact
commands issued and how responses are parsed, not real network behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from email_mcp.providers.imap.client import ImapCommandError, ImapNotFoundError, ImapSmtpClient

_ARGS = {
    "imap_host": "imap.example.com",
    "imap_port": 993,
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "username": "user@example.com",
    "password": "secret",
}


def _make_client(**overrides: object) -> ImapSmtpClient:
    return ImapSmtpClient(**{**_ARGS, **overrides})


@patch("email_mcp.providers.imap.client.imaplib.IMAP4_SSL")
def test_search_returns_parsed_uids(mock_imap_cls: MagicMock) -> None:
    conn = mock_imap_cls.return_value
    conn.uid.return_value = ("OK", [b"3 1 2"])

    uids = _make_client().search("INBOX", "ALL")

    assert uids == [3, 1, 2]
    conn.login.assert_called_once_with("user@example.com", "secret")
    conn.select.assert_called_once_with("INBOX", readonly=True)
    conn.uid.assert_called_once_with("search", None, "ALL")
    conn.logout.assert_called_once()


@patch("email_mcp.providers.imap.client.imaplib.IMAP4_SSL")
def test_search_with_no_matches_returns_empty_list(mock_imap_cls: MagicMock) -> None:
    conn = mock_imap_cls.return_value
    conn.uid.return_value = ("OK", [b""])

    assert _make_client().search("INBOX", "ALL") == []


@patch("email_mcp.providers.imap.client.imaplib.IMAP4_SSL")
def test_search_raises_on_non_ok_status(mock_imap_cls: MagicMock) -> None:
    conn = mock_imap_cls.return_value
    conn.uid.return_value = ("NO", [b"permission denied"])

    with pytest.raises(ImapCommandError):
        _make_client().search("INBOX", "ALL")


@patch("email_mcp.providers.imap.client.imaplib.IMAP4_SSL")
def test_fetch_message_extracts_raw_bytes_and_flags(mock_imap_cls: MagicMock) -> None:
    conn = mock_imap_cls.return_value
    conn.uid.return_value = (
        "OK",
        [(b"1 (FLAGS (\\Seen \\Answered) RFC822 {13}", b"raw message"), b")"],
    )

    raw, flags = _make_client().fetch_message("INBOX", 1)

    assert raw == b"raw message"
    assert flags == {"\\Seen", "\\Answered"}
    conn.select.assert_called_once_with("INBOX", readonly=True)


@patch("email_mcp.providers.imap.client.imaplib.IMAP4_SSL")
def test_fetch_message_raises_not_found_for_missing_uid(mock_imap_cls: MagicMock) -> None:
    conn = mock_imap_cls.return_value
    conn.uid.return_value = ("OK", [None])

    with pytest.raises(ImapNotFoundError):
        _make_client().fetch_message("INBOX", 999)


@patch("email_mcp.providers.imap.client.imaplib.IMAP4_SSL")
def test_append_and_locate_finds_uid_by_message_id(mock_imap_cls: MagicMock) -> None:
    conn = mock_imap_cls.return_value
    conn.append.return_value = ("OK", [b"APPEND completed"])
    conn.uid.return_value = ("OK", [b"42"])

    uid = _make_client().append_and_locate("Drafts", b"raw", "<msg-1@example.com>")

    assert uid == 42
    conn.append.assert_called_once_with("Drafts", None, None, b"raw")
    conn.uid.assert_called_once_with("search", None, '(HEADER Message-ID "<msg-1@example.com>")')


@patch("email_mcp.providers.imap.client.imaplib.IMAP4_SSL")
def test_append_and_locate_raises_if_message_cannot_be_found_afterward(mock_imap_cls: MagicMock) -> None:
    conn = mock_imap_cls.return_value
    conn.append.return_value = ("OK", [b"APPEND completed"])
    conn.uid.return_value = ("OK", [b""])

    with pytest.raises(ImapNotFoundError):
        _make_client().append_and_locate("Drafts", b"raw", "<msg-1@example.com>")


@patch("email_mcp.providers.imap.client.imaplib.IMAP4_SSL")
def test_append_and_locate_raises_on_append_failure(mock_imap_cls: MagicMock) -> None:
    conn = mock_imap_cls.return_value
    conn.append.return_value = ("NO", [b"quota exceeded"])

    with pytest.raises(ImapCommandError):
        _make_client().append_and_locate("Drafts", b"raw", "<msg-1@example.com>")


@patch("email_mcp.providers.imap.client.imaplib.IMAP4_SSL")
def test_set_flag_issues_store_with_correct_sign(mock_imap_cls: MagicMock) -> None:
    conn = mock_imap_cls.return_value
    conn.uid.return_value = ("OK", [b"done"])

    _make_client().set_flag("INBOX", 5, "\\Seen", add=True)
    conn.uid.assert_called_with("store", "5", "+FLAGS", "(\\Seen)")

    _make_client().set_flag("INBOX", 5, "\\Seen", add=False)
    conn.uid.assert_called_with("store", "5", "-FLAGS", "(\\Seen)")


@patch("email_mcp.providers.imap.client.imaplib.IMAP4_SSL")
def test_delete_stores_deleted_flag_then_expunges(mock_imap_cls: MagicMock) -> None:
    conn = mock_imap_cls.return_value
    conn.uid.return_value = ("OK", [b"done"])

    _make_client().delete("Drafts", 7)

    conn.uid.assert_called_once_with("store", "7", "+FLAGS", "(\\Deleted)")
    conn.expunge.assert_called_once()


@patch("email_mcp.providers.imap.client.smtplib.SMTP")
def test_send_uses_starttls_by_default(mock_smtp_cls: MagicMock) -> None:
    smtp = mock_smtp_cls.return_value.__enter__.return_value

    _make_client().send(b"raw", "me@example.com", ["bob@example.com"])

    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("user@example.com", "secret")
    smtp.sendmail.assert_called_once_with("me@example.com", ["bob@example.com"], b"raw")


@patch("email_mcp.providers.imap.client.smtplib.SMTP_SSL")
def test_send_skips_starttls_when_using_implicit_tls(mock_smtp_ssl_cls: MagicMock) -> None:
    smtp = mock_smtp_ssl_cls.return_value.__enter__.return_value

    _make_client(smtp_use_ssl=True).send(b"raw", "me@example.com", ["bob@example.com"])

    smtp.starttls.assert_not_called()
    smtp.login.assert_called_once_with("user@example.com", "secret")
