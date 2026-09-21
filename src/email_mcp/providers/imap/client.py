"""Thin synchronous wrapper around stdlib `imaplib`/`smtplib`.

Deliberately dumb, mirroring `providers/gmail/client.py`: every method is a
near-1:1 IMAP/SMTP operation, returning raw bytes/uids/flags. No mapping to
domain models and no error translation to `domain.errors` happens here -
that's `mapper.py` and `provider.py`'s job, respectively. This module only
raises `ImapCommandError`/`ImapNotFoundError` (for a command that itself
reported non-OK status) or lets `imaplib`/`smtplib`'s own exceptions
propagate - `provider.py` translates all of it.

Unlike Gmail (one API, one set of ids), IMAP and SMTP are two separate
protocols/connections. A connection is opened fresh per call rather than
kept alive across calls, for the same reason as `GmailClient._get_service`:
callers run concurrent calls on separate threads via `asyncio.to_thread`,
and neither `imaplib.IMAP4_SSL` nor `smtplib.SMTP` is thread-safe.

IMAP UIDs are only assigned by the server, so there is no way to request one
on APPEND without depending on the (not universally supported) UIDPLUS
extension. Instead, every appended message carries an explicit `Message-ID`
(see `mapper.build_raw_message`), and `append_and_locate` recovers its UID by
searching for that Message-ID immediately afterward - this works against any
RFC 3501-compliant server, no extension required.
"""

from __future__ import annotations

import imaplib
import re
import smtplib

_FLAGS_RE = re.compile(rb"FLAGS \(([^)]*)\)")


class ImapCommandError(Exception):
    """An IMAP command itself reported non-OK status."""


class ImapNotFoundError(ImapCommandError):
    """The requested uid does not exist in the given folder."""


class ImapSmtpClient:
    def __init__(
        self,
        imap_host: str,
        imap_port: int,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        smtp_use_ssl: bool = False,
    ) -> None:
        self._imap_host = imap_host
        self._imap_port = imap_port
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._username = username
        self._password = password
        self._smtp_use_ssl = smtp_use_ssl

    def _connect(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self._imap_host, self._imap_port)
        conn.login(self._username, self._password)
        return conn

    def search(self, folder: str, criteria: str) -> list[int]:
        """Returns UIDs matching an IMAP SEARCH criteria string (e.g. "ALL", '(HEADER Subject "x")')."""
        conn = self._connect()
        try:
            conn.select(folder, readonly=True)
            status, data = conn.uid("search", None, criteria)  # type: ignore[arg-type]
            if status != "OK":
                raise ImapCommandError(f"SEARCH failed in {folder!r}: {status} {data!r}")
            return [int(uid) for uid in data[0].split()] if data and data[0] else []
        finally:
            _disconnect(conn)

    def fetch_message(self, folder: str, uid: int) -> tuple[bytes, set[str]]:
        """Returns (raw RFC 822 bytes, flags) for one UID in `folder`."""
        conn = self._connect()
        try:
            conn.select(folder, readonly=True)
            status, data = conn.uid("fetch", str(uid), "(RFC822 FLAGS)")
            if status != "OK" or not data or data[0] is None:
                raise ImapNotFoundError(f"No message uid={uid} in folder {folder!r}")
            return _extract_rfc822(data), _extract_flags(data)
        finally:
            _disconnect(conn)

    def append_and_locate(self, folder: str, raw_message: bytes, message_id: str) -> int:
        """Appends `raw_message` to `folder` and returns its new UID, found by
        searching for the Message-ID the caller already put in it."""
        conn = self._connect()
        try:
            conn.select(folder)
            status, resp = conn.append(folder, None, None, raw_message)
            if status != "OK":
                raise ImapCommandError(f"APPEND to {folder!r} failed: {status} {resp!r}")
            search_status, data = conn.uid(
                "search", None, f'(HEADER Message-ID "{message_id}")'  # type: ignore[arg-type]
            )
            if search_status != "OK" or not data or not data[0]:
                raise ImapNotFoundError(
                    f"Appended message to {folder!r} but could not locate it by Message-ID={message_id!r}"
                )
            return max(int(uid) for uid in data[0].split())
        finally:
            _disconnect(conn)

    def set_flag(self, folder: str, uid: int, flag: str, add: bool) -> None:
        conn = self._connect()
        try:
            conn.select(folder)
            sign = "+FLAGS" if add else "-FLAGS"
            status, data = conn.uid("store", str(uid), sign, f"({flag})")
            if status != "OK":
                raise ImapNotFoundError(f"STORE failed for uid={uid} in {folder!r}: {status} {data!r}")
        finally:
            _disconnect(conn)

    def delete(self, folder: str, uid: int) -> None:
        conn = self._connect()
        try:
            conn.select(folder)
            status, data = conn.uid("store", str(uid), "+FLAGS", "(\\Deleted)")
            if status != "OK":
                raise ImapNotFoundError(f"STORE (\\Deleted) failed for uid={uid} in {folder!r}: {status} {data!r}")
            conn.expunge()
        finally:
            _disconnect(conn)

    def send(self, raw_message: bytes, from_addr: str, to_addrs: list[str]) -> None:
        smtp_cls = smtplib.SMTP_SSL if self._smtp_use_ssl else smtplib.SMTP
        with smtp_cls(self._smtp_host, self._smtp_port) as smtp:
            if not self._smtp_use_ssl:
                smtp.starttls()
            smtp.login(self._username, self._password)
            smtp.sendmail(from_addr, to_addrs, raw_message)


def _disconnect(conn: imaplib.IMAP4_SSL) -> None:
    try:
        conn.close()
    except imaplib.IMAP4.error:
        pass  # no mailbox was ever selected, or select() itself failed
    conn.logout()


def _extract_rfc822(fetch_data: list) -> bytes:
    for item in fetch_data:
        if isinstance(item, tuple) and len(item) == 2:
            return item[1]
    raise ImapCommandError("FETCH response did not include a message literal")


def _extract_flags(fetch_data: list) -> set[str]:
    for item in fetch_data:
        header = item[0] if isinstance(item, tuple) else item
        if not isinstance(header, bytes):
            continue
        match = _FLAGS_RE.search(header)
        if match:
            return {f.decode("ascii") for f in match.group(1).split()}
    return set()
