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

import time

import requests

from email_mcp.providers.graph.auth import GraphAuth
from email_mcp.providers.graph.mapper import SUMMARY_FIELDS

_BASE_URL = "https://graph.microsoft.com/v1.0/me"
_TIMEOUT = 30
# Two retries for reads that hit a Graph outage, throttling or a timeout.
_RETRY_PAUSES = (1.0, 3.0)
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_PAUSE = 10.0


def _retry_after(response: requests.Response) -> float | None:
    try:
        return float(response.headers.get("Retry-After", ""))
    except ValueError:
        return None


class GraphClient:
    def __init__(self, auth: GraphAuth) -> None:
        self._auth = auth

    def _request(self, method: str, path: str, **kwargs: object) -> requests.Response:
        # Token fetched fresh on every call (mirrors GmailClient._get_service):
        # cheap when cached/still valid, and MSAL's own silent-refresh check
        # inside get_access_token means this never re-does a full OBO exchange
        # here.
        headers = {"Authorization": f"Bearer {self._auth.get_access_token()}"}
        url = f"{_BASE_URL}{path}"
        for attempt, pause in enumerate((*_RETRY_PAUSES, None)):
            try:
                response = requests.request(method, url, headers=headers, timeout=_TIMEOUT, **kwargs)
            except (requests.ConnectionError, requests.Timeout):
                if pause is None:
                    raise
                time.sleep(pause)
                continue
            # Graph has short outages and throttles; retrying a read is safe.
            # Writes are not retried: a timed-out POST may have gone through.
            if response.status_code in _RETRY_STATUSES and pause is not None and method == "GET":
                time.sleep(min(_retry_after(response) or pause, _MAX_PAUSE))
                continue
            response.raise_for_status()
            return response
        raise AssertionError("unreachable")

    def list_messages(self, query: str | None, top: int) -> list[dict]:
        # $orderby is rejected by Graph when combined with $search, so the
        # two query shapes are mutually exclusive, not just optional extras.
        params: dict[str, object] = (
            {"$search": f'"{query}"', "$top": top} if query else {"$top": top, "$orderby": "receivedDateTime desc"}
        )
        params["$select"] = SUMMARY_FIELDS
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
