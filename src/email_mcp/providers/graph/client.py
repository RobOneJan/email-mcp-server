"""Thin synchronous wrapper around the Microsoft Graph v1.0 REST API's mail
endpoints.

Deliberately dumb, mirroring `providers/gmail/client.py`'s role for Gmail:
every method is a near-1:1 HTTP call, returning raw Graph JSON dicts. No
mapping to domain models and no error translation happens here - that's
`mapper.py` and `provider.py`'s job, respectively. Kept synchronous on
purpose; `provider.py` offloads calls to a thread so the async event loop is
never blocked - the `requests` package has no async API of its own.
"""

from __future__ import annotations

import requests

from email_mcp.providers.graph.auth import GraphAuth

_BASE_URL = "https://graph.microsoft.com/v1.0/me"
_TIMEOUT = 30


class GraphClient:
    def __init__(self, auth: GraphAuth) -> None:
        self._auth = auth

    def _request(self, method: str, path: str, **kwargs: object) -> requests.Response:
        # Token fetched fresh on every call (mirrors GmailClient._get_service):
        # cheap when cached/still valid, and MSAL's own silent-refresh check
        # inside get_access_token means this never re-does a full OBO exchange
        # here.
        headers = {"Authorization": f"Bearer {self._auth.get_access_token()}"}
        response = requests.request(method, f"{_BASE_URL}{path}", headers=headers, timeout=_TIMEOUT, **kwargs)
        response.raise_for_status()
        return response

    def list_messages(self, query: str | None, top: int) -> list[dict]:
        # $orderby is rejected by Graph when combined with $search, so the
        # two query shapes are mutually exclusive, not just optional extras.
        params: dict[str, object] = (
            {"$search": f'"{query}"', "$top": top} if query else {"$top": top, "$orderby": "receivedDateTime desc"}
        )
        response = self._request("GET", "/messages", params=params)
        return response.json().get("value", [])

    def get_message(self, message_id: str) -> dict:
        return self._request("GET", f"/messages/{message_id}").json()

    def list_thread_messages(self, conversation_id: str) -> list[dict]:
        params = {"$filter": f"conversationId eq '{conversation_id}'", "$orderby": "receivedDateTime asc"}
        response = self._request("GET", "/messages", params=params)
        return response.json().get("value", [])

    def create_draft(self, body: dict) -> dict:
        return self._request("POST", "/messages", json=body).json()

    def create_reply_draft(self, message_id: str) -> dict:
        """POST .../createReply returns a new draft message pre-linked to the
        original (conversationId, In-Reply-To) with a quoted-body/subject
        Graph fills in itself - the caller then PATCHes it (update_message)
        with the actual desired subject/body/recipients."""
        return self._request("POST", f"/messages/{message_id}/createReply", json={}).json()

    def update_message(self, message_id: str, body: dict) -> dict:
        return self._request("PATCH", f"/messages/{message_id}", json=body).json()

    def send_draft(self, message_id: str) -> None:
        # Graph returns 202 Accepted with an empty body - nothing to parse.
        self._request("POST", f"/messages/{message_id}/send")

    def mark_as_read(self, message_id: str) -> None:
        self._request("PATCH", f"/messages/{message_id}", json={"isRead": True})

    def list_attachments(self, message_id: str) -> list[dict]:
        # $select excludes contentBytes - metadata only, same size/cost
        # tradeoff as Gmail's separate list-vs-fetch attachment calls.
        params = {"$select": "id,name,contentType,size"}
        response = self._request("GET", f"/messages/{message_id}/attachments", params=params)
        return response.json().get("value", [])

    def get_attachment(self, message_id: str, attachment_id: str) -> dict:
        return self._request("GET", f"/messages/{message_id}/attachments/{attachment_id}").json()
