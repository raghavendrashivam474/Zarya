"""EIP-1 Capability Advertisement.

Explicitly declares what Zarya exposes through the ecosystem
boundary. This is a DELIBERATE ALLOW-LIST, not an auto-exposure
of all internal tools.

Internal functionality != externally advertised capability.

The registry.TOOLS dict may contain 30+ tools. We expose a
small, reviewed subset through the ecosystem boundary.
"""

import logging

log = logging.getLogger("zarya.ecosystem.capabilities")

# ── Explicit allow-list ──────────────────────────────────────
# Each capability is deliberately declared with its contract.
# Adding a new capability here requires a conscious decision.

ADVERTISED_CAPABILITIES = [
    {
        "id": "system.health",
        "version": "1.0",
        "description": "Check Zarya instance liveness and basic readiness.",
        "operations": ["check"],
        "input_schema": None,
        "output_schema": {
            "status": "string (READY | BUSY | UNAVAILABLE)",
        },
    },
    {
        "id": "work.execute",
        "version": "1.0",
        "description": (
            "Execute a single authorized tool operation through "
            "Zarya's existing work pipeline."
        ),
        "operations": ["execute"],
        "input_schema": {
            "tool": "string (must be in allowed_tools)",
            "args": "object (tool-specific arguments)",
        },
        "output_schema": {
            "result": "object (tool-specific result)",
            "verified": "boolean",
        },
    },
    {
        "id": "work.status",
        "version": "1.0",
        "description": (
            "Query the lifecycle status of a work operation. "
            "Projects from S18 WorkState."
        ),
        "operations": ["query"],
        "input_schema": {
            "operation_id": "string",
        },
        "output_schema": {
            "operation_id": "string",
            "status": "string (ecosystem status)",
            "lifecycle_status": "string (S18 LifecycleStatus)",
        },
    },
]

# ── Allowed tools for work.execute ───────────────────────────
# Even within work.execute, not all tools are permitted.
# This list is the intersection of "exists in registry" AND
# "safe to expose to ecosystem consumers."

ALLOWED_ECOSYSTEM_TOOLS = frozenset({
    "getWeather",
    "getNews",
    "listFiles",
    "openWebsite",
    "openApplication",
    "getSystemInfo",
})


def get_capabilities() -> list:
    """Return the list of advertised capability descriptors."""
    return ADVERTISED_CAPABILITIES


def is_capability_advertised(capability_id: str) -> bool:
    """Check if a capability ID is in the advertised list."""
    return any(c["id"] == capability_id for c in ADVERTISED_CAPABILITIES)


def is_tool_allowed(tool_name: str) -> bool:
    """Check if a specific tool is permitted through the ecosystem boundary."""
    return tool_name in ALLOWED_ECOSYSTEM_TOOLS


def get_allowed_tools() -> list:
    """Return the list of tool names permitted for ecosystem execution."""
    return sorted(ALLOWED_ECOSYSTEM_TOOLS)
