"""The provider-neutral port every email backend adapter must implement.

Design notes (see plan for full rationale):
- `send_draft(draft_id)` takes only an id, not free-form to/subject/body. The
  content that gets sent is exactly the content a human reviewed and approved
  via `request_send_approval` - a caller cannot swap in different content at
  send time while reusing the same approval.
- All methods are async; adapters that wrap a synchronous SDK (e.g. Gmail's
  google-api-python-client) are responsible for offloading blocking calls
  (e.g. via `asyncio.to_thread`) so they never block the MCP event loop.
- Adapters must translate their own SDK exceptions into `domain.errors`
  types before they propagate out of this interface.
"""

from __future__ import annotations

from typing import Protocol

from email_mcp.domain.models import (
    AttachmentContent,
    Email,
    EmailAddress,
    EmailDraft,
    EmailMetadata,
    EmailThread,
)


class EmailProvider(Protocol):
    async def search_emails(
        self,
        query: str | None = None,
        limit: int = 50,
    ) -> list[EmailMetadata]:
        """Search the mailbox. Returns metadata only (no bodies) to keep results cheap."""
        ...

    async def get_email(self, email_id: str) -> Email:
        """Fetch one email including its full body."""
        ...

    async def get_thread(self, thread_id: str) -> EmailThread:
        """Fetch a full thread (all messages) by id."""
        ...

    async def create_draft(
        self,
        to: list[EmailAddress],
        subject: str,
        body_text: str,
        cc: list[EmailAddress] | None = None,
        reply_to_email_id: str | None = None,
    ) -> EmailDraft:
        """Create (but do not send) a draft. Never sends anything by itself."""
        ...

    async def get_draft(self, draft_id: str) -> EmailDraft:
        """Fetch a previously created draft - used to build the human-review
        preview for an approval request, without duplicating its content
        elsewhere."""
        ...

    async def send_draft(self, draft_id: str) -> str:
        """Send a previously created draft, unchanged. Returns the sent email's id.

        Callers (application layer) must only invoke this after a human
        approval has been verified for this exact draft - this method itself
        performs no approval checking, that is the application layer's job.
        """
        ...

    async def mark_as_read(self, email_id: str) -> None: ...

    async def get_attachment(self, email_id: str, attachment_id: str) -> AttachmentContent:
        """Fetch one attachment's content by id (see `Attachment.id` on a
        previously fetched `Email`). Raises `AttachmentTooLargeError` instead
        of returning content above `security.MAX_ATTACHMENT_SIZE_BYTES`."""
        ...
