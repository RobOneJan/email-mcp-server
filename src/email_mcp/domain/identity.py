"""Tenant identity - provider-neutral, transport-neutral.

`tenant_id` identifies whose mailbox/credentials/approvals a call belongs to.
It is threaded through every store and service from here on, but there is
still only one real source of truth for it: `DEFAULT_TENANT_ID` below, used
everywhere a caller is resolved. That single constant is deliberately the
*only* place this MVP fabricates an identity - once the MCP server gets real
per-caller authentication (see README roadmap: MCP-level OAuth), replacing
this constant with the authenticated caller's id is the only change needed;
every store/service downstream already takes `tenant_id` as a parameter.
"""

from __future__ import annotations

DEFAULT_TENANT_ID = "default"
