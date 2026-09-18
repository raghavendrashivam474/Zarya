"""EIP-1 FastAPI Routes.

Provides the HTTP endpoints for the ecosystem boundary.
This router is mounted onto the existing agent.server.app
as /ecosystem/v1/*.

All endpoints (except auth-info) require the X-Ecosystem-Token header.
"""

import logging
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

from fastapi import APIRouter, Header, HTTPException

from agent.ecosystem.protocol import PROTOCOL_VERSION
from agent.ecosystem.identity import get_instance_identity
from agent.ecosystem.capabilities import (
    get_capabilities,
    is_tool_allowed,
    get_allowed_tools,
)
from agent.ecosystem.status import get_global_status, project_lifecycle_status
from agent.ecosystem.authorization import validate_token, get_auth_instructions
from agent.ecosystem.errors import EcosystemErrorCode, make_error

# Core runtime imports
from agent.work import execute_work
from agent.checkpoint import CheckpointStore
from agent.control import get_operation_status

log = logging.getLogger("zarya.ecosystem.routes")

router = APIRouter(prefix="/ecosystem/v1", tags=["ecosystem"])


# ── Pydantic Request Models ──────────────────────────────────

class EcosystemExecuteRequest(BaseModel):
    """Ecosystem work execution contract."""
    tool: str = Field(..., description="The name of the tool to execute.")
    args: Dict[str, Any] = Field(default_factory=dict, description="Arguments for the tool.")


# ── Auth helper ──────────────────────────────────────────────

def _require_auth(token: Optional[str]) -> None:
    """Validate ecosystem token or raise 401."""
    if not token or not validate_token(token):
        raise HTTPException(
            status_code=401,
            detail=make_error(
                EcosystemErrorCode.UNAUTHORIZED,
                "Invalid or missing X-Ecosystem-Token header.",
            ),
        )


# ── Discovery endpoints ──────────────────────────────────────

@router.get("/identity")
async def ecosystem_identity(
    x_ecosystem_token: Optional[str] = Header(None),
):
    """Return this Zarya instance's identity."""
    _require_auth(x_ecosystem_token)
    return get_instance_identity()


@router.get("/capabilities")
async def ecosystem_capabilities(
    x_ecosystem_token: Optional[str] = Header(None),
):
    """Return advertised capabilities and allowed tools."""
    _require_auth(x_ecosystem_token)
    return {
        "protocol": PROTOCOL_VERSION,
        "capabilities": get_capabilities(),
        "allowed_tools": get_allowed_tools(),
    }


@router.get("/status")
async def ecosystem_status(
    x_ecosystem_token: Optional[str] = Header(None),
):
    """Return current Zarya availability."""
    _require_auth(x_ecosystem_token)
    return get_global_status()


@router.get("/auth-info")
async def ecosystem_auth_info():
    """Return authentication instructions (no token required)."""
    return get_auth_instructions()


@router.get("/protocol")
async def ecosystem_protocol(
    x_ecosystem_token: Optional[str] = Header(None),
):
    """Return supported protocol versions."""
    _require_auth(x_ecosystem_token)
    from agent.ecosystem.protocol import SUPPORTED_VERSIONS
    return {
        "current": PROTOCOL_VERSION,
        "supported": sorted(SUPPORTED_VERSIONS),
    }


# ── Operational endpoints ────────────────────────────────────

@router.post("/work/execute")
async def ecosystem_execute(
    req: EcosystemExecuteRequest,
    x_ecosystem_token: Optional[str] = Header(None),
):
    """Execute a permitted tool through Zarya's verified work runtime.

    This wraps the tool call in an internal, single-step WorkPlan
    to preserve context continuity, verification, and failure reasoning.
    """
    _require_auth(x_ecosystem_token)

    # 1. Enforce strict tool allow-list boundary
    if not is_tool_allowed(req.tool):
        raise HTTPException(
            status_code=403,
            detail=make_error(
                EcosystemErrorCode.TOOL_NOT_ALLOWED,
                f"Tool '{req.tool}' is not permitted through the ecosystem boundary.",
                {"allowed_tools": get_allowed_tools()}
            ),
        )

    # 2. Build a compliant single-step WorkPlan internally
    internal_plan = {
        "name": f"Ecosystem Request: {req.tool}",
        "steps": [
            {
                "step": 1,
                "tool": req.tool,
                "args": req.args,
            }
        ]
    }

    log.info("EIP-1 dispatching verified execution: tool=%s", req.tool)

    try:
        # 3. Call authoritative executor with authorized=True (derived from our token authorization)
        result = execute_work(
            plan=internal_plan,
            authorized=True,
            step_callback=None
        )

        # 4. Format a clean, structured ecosystem response (avoiding arbitrary object serialization)
        # Extract outcomes from step records if they exist
        step_records = result.get("steps", [])
        verified = False
        outcome = "UNKNOWN"
        tool_result = {}

        if step_records:
            step_one = step_records[0]
            outcome = step_one.get("outcome", "UNKNOWN")
            verified = outcome == "VERIFIED_SUCCESS"
            tool_result = step_one.get("result", {})

        return {
            "tool": req.tool,
            "outcome": outcome,
            "verified": verified,
            "result": tool_result,
            "summary": result.get("summary", ""),
        }

    except Exception as e:
        log.exception("Error executing ecosystem tool %s", req.tool)
        raise HTTPException(
            status_code=500,
            detail=make_error(
                EcosystemErrorCode.EXECUTION_FAILED,
                f"An internal error occurred during execution: {str(e)}"
            )
        )


@router.get("/work/status/{operation_id}")
async def ecosystem_operation_status(
    operation_id: str,
    x_ecosystem_token: Optional[str] = Header(None),
):
    """Query S18 operation status, projected to ecosystem availability states."""
    _require_auth(x_ecosystem_token)

    store = CheckpointStore()
    status_info = get_operation_status(operation_id, store)

    if not status_info:
        raise HTTPException(
            status_code=404,
            detail=make_error(
                EcosystemErrorCode.INVALID_REQUEST,
                f"Operation '{operation_id}' not found."
            )
        )

    # Map S18 lifecycle status to ecosystem availability
    lifecycle_str = status_info.get("status", "UNKNOWN")
    eco_status = project_lifecycle_status(lifecycle_str)

    return {
        "operation_id": operation_id,
        "ecosystem_status": eco_status,
        "lifecycle_status": lifecycle_str,
        "detail": status_info,
    }
