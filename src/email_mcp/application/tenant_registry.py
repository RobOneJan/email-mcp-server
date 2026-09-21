"""Resolves an `EmailService` for a given tenant, building and caching one
lazily on first use.

`ApprovalService`/`AuditLogger`/`TokenStore` are shared across all tenants -
each of their methods already takes `tenant_id` and scopes to it. Only the
`EmailProvider` genuinely differs per tenant (it carries that tenant's own
mailbox credentials), so it - and the `EmailService` wrapping it - is built
once per tenant and cached here.
"""

from __future__ import annotations

from email_mcp.application.approval_service import ApprovalService
from email_mcp.application.email_service import EmailService
from email_mcp.infrastructure.audit import AuditLogger
from email_mcp.infrastructure.config import Settings
from email_mcp.ports.token_store import TokenStore
from email_mcp.providers.factory import get_email_provider, get_provider_name


class TenantRegistry:
    def __init__(
        self,
        settings: Settings,
        approval_service: ApprovalService,
        audit_logger: AuditLogger,
        token_store: TokenStore,
    ) -> None:
        self._settings = settings
        self._approvals = approval_service
        self._audit = audit_logger
        self._token_store = token_store
        self._services: dict[str, EmailService] = {}

    def get(self, tenant_id: str) -> EmailService:
        service = self._services.get(tenant_id)
        if service is None:
            provider = get_email_provider(self._settings, tenant_id, self._token_store)
            service = EmailService(
                provider=provider,
                approval_service=self._approvals,
                audit_logger=self._audit,
                provider_name=get_provider_name(self._settings, tenant_id, self._token_store),
                tenant_id=tenant_id,
            )
            self._services[tenant_id] = service
        return service
