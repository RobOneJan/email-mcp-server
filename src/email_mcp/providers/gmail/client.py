"""Thin synchronous wrapper around `googleapiclient`'s Gmail v1 API.

Deliberately dumb: every method is a near-1:1 call into the Gmail SDK,
returning raw Gmail API dicts. No mapping to domain models and no error
translation happens here - that's `mapper.py` and `provider.py`'s job,
respectively. Kept synchronous on purpose; `provider.py` offloads calls to a
thread so the async event loop is never blocked.
"""

from __future__ import annotations

from googleapiclient.discovery import Resource, build

from email_mcp.providers.gmail.auth import GmailAuth

_USER_ID = "me"


class GmailClient:
    def __init__(self, auth: GmailAuth) -> None:
        self._auth = auth

    def _get_service(self) -> Resource:
        # Built fresh on every call rather than cached: callers (see
        # GmailEmailProvider.search_emails) run concurrent calls on separate
        # threads via asyncio.to_thread, and a single Resource's underlying
        # httplib2 connection is not thread-safe - sharing it corrupts the
        # TLS stream (SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC). Credentials
        # are also re-checked/refreshed here since access tokens are
        # short-lived.
        creds = self._auth.get_credentials()
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def list_message_ids(self, query: str | None, max_results: int) -> list[str]:
        request = self._get_service().users().messages().list(
            userId=_USER_ID, q=query, maxResults=max_results
        )
        response = request.execute()
        return [m["id"] for m in response.get("messages", [])]

    def get_message(self, message_id: str, fmt: str = "full") -> dict:
        return (
            self._get_service()
            .users()
            .messages()
            .get(userId=_USER_ID, id=message_id, format=fmt)
            .execute()
        )

    def get_thread(self, thread_id: str) -> dict:
        return (
            self._get_service()
            .users()
            .threads()
            .get(userId=_USER_ID, id=thread_id, format="full")
            .execute()
        )

    def create_draft(self, raw_message: str, thread_id: str | None = None) -> dict:
        message_body: dict = {"raw": raw_message}
        if thread_id:
            message_body["threadId"] = thread_id
        return (
            self._get_service()
            .users()
            .drafts()
            .create(userId=_USER_ID, body={"message": message_body})
            .execute()
        )

    def get_draft(self, draft_id: str) -> dict:
        return self._get_service().users().drafts().get(userId=_USER_ID, id=draft_id).execute()

    def send_draft(self, draft_id: str) -> dict:
        return (
            self._get_service()
            .users()
            .drafts()
            .send(userId=_USER_ID, body={"id": draft_id})
            .execute()
        )

    def get_attachment(self, message_id: str, attachment_id: str) -> dict:
        return (
            self._get_service()
            .users()
            .messages()
            .attachments()
            .get(userId=_USER_ID, messageId=message_id, id=attachment_id)
            .execute()
        )

    def modify_message_labels(
        self, message_id: str, add: list[str] | None = None, remove: list[str] | None = None
    ) -> dict:
        body = {"addLabelIds": add or [], "removeLabelIds": remove or []}
        return (
            self._get_service()
            .users()
            .messages()
            .modify(userId=_USER_ID, id=message_id, body=body)
            .execute()
        )
