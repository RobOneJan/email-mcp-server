"""Provider-neutral error hierarchy.

Every provider adapter (Gmail, and later Microsoft Graph/IMAP/SMTP) must catch its
own SDK-specific exceptions and re-raise one of these instead. Nothing outside
`providers/<name>/` may import or handle a provider-specific exception type -
this keeps the application and MCP layers isolated from any single provider's
failure modes ("provider error isolation").
"""

from __future__ import annotations


class EmailProviderError(Exception):
    """Base class for all provider-neutral email errors."""


class EmailNotFoundError(EmailProviderError):
    """Raised when an email_id/thread_id/draft_id does not exist for this provider."""


class ProviderAuthError(EmailProviderError):
    """Raised when the provider rejects/lacks valid credentials (e.g. expired OAuth token)."""


class ProviderRateLimitError(EmailProviderError):
    """Raised when the provider's API throttles the request."""


class ProviderUnavailableError(EmailProviderError):
    """Raised for transient/network failures talking to the provider."""


class InvalidEmailRequestError(EmailProviderError):
    """Raised when a request is structurally invalid for this provider (e.g. bad recipient)."""


class AttachmentTooLargeError(EmailProviderError):
    """Raised when an attachment exceeds MAX_ATTACHMENT_SIZE_BYTES - fetching it
    inline would flood the caller's context with a huge base64 blob."""


# --- Approval errors (application layer, not provider-specific) ---


class ApprovalError(Exception):
    """Base class for approval-flow errors."""


class ApprovalNotFoundError(ApprovalError):
    """No approval request exists for the given id."""


class ApprovalNotGrantedError(ApprovalError):
    """The approval request exists but is not (yet) APPROVED."""


class ApprovalExpiredError(ApprovalError):
    """The approval request expired before being consumed."""


class ApprovalMismatchError(ApprovalError):
    """The approval request does not match the action/resource it is being used for."""
