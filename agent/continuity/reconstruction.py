# N4.3 — Work Reconstruction & Authorization Adapter
# Phase: N | Sprint: N4
# Baseline: N3 v1.3.0-n3 (frozen)
#
# Responsibility:
#   1. Authorize continuation request via existing target boundaries.
#   2. Translate abstract portable structures into S18-executable inputs.
#   3. Map abstract artifact references to target physical paths inside the plan.

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("zarya.n4.reconstruction")

try:
    from agent.ecosystem.authorization import validate_token as eip1_validate_token
    _EIP1_AUTH_AVAILABLE = True
except ImportError:
    _EIP1_AUTH_AVAILABLE = False
    log.warning("EIP-1 authorization module not available; using local policy fallback")


@dataclass
class ReconstructedWork:
    """The final, authorized, executable structure prepared for S18 execution."""
    work_id: str
    intent: str  # User's high level logical goal, maps to S18 WorkState.goal
    target_operation_id: str
    source_operation_id: Optional[str]
    plan: Dict[str, Any]
    authorized: bool = False
    auth_reason: str = ""


def authorize_continuation(
    portable_dict: Dict[str, Any],
    auth_token: Optional[str] = None,
    local_policy_override: bool = False,
) -> tuple[bool, str]:
    """Determine if this target instance authorizes continuation of this work."""
    if local_policy_override:
        return True, "Authorized: Local administrative policy override active."

    auth_metadata = portable_dict.get("authorization_metadata") or {}
    requires_eip1 = auth_metadata.get("requires_token", False)

    if requires_eip1 or auth_token:
        if not _EIP1_AUTH_AVAILABLE:
            return False, "Unauthorized: EIP-1 validation required but authorization engine is unavailable."
        
        if not auth_token:
            return False, "Unauthorized: Direct EIP-1 authorization token is missing."

        if eip1_validate_token(auth_token):
            return True, "Authorized: EIP-1 token validated successfully."
        else:
            return False, "Unauthorized: Provided EIP-1 token is invalid on this target."

    # Inspect plan steps to check for critical tools
    plan_ref = portable_dict.get("plan_reference") or {}
    steps = plan_ref.get("steps") or []
    for step in steps:
        action = step.get("action", "").lower()
        if action in ("terminal", "os_input", "hyprland", "windows"):
            return False, f"Unauthorized: Plan requests critical tool '{action}' which requires explicit token authorization."

    return True, "Authorized: Standard local work operation."


def reconstruct_executable_work(
    portable_dict: Dict[str, Any],
    resolved_paths: Dict[str, str],
    is_authorized: bool,
    auth_reason: str,
) -> ReconstructedWork:
    """Translate portable plan into a physical, target-side executable plan."""
    work_id = portable_dict.get("work_id", "")
    intent = portable_dict.get("intent", "") or f"Logical work {work_id}"
    source_op_id = portable_dict.get("execution_reference")

    # Generate deterministic target operation id based on logical work_id
    namespace_uuid = uuid.UUID("745bf2e2-9b2b-42ef-a8dc-91304523d21b")
    target_op_id = f"op-{uuid.uuid5(namespace_uuid, work_id).hex[:12]}"

    raw_plan = portable_dict.get("plan_reference") or {}
    reconstructed_plan = _substitute_paths_in_plan(raw_plan, resolved_paths)

    return ReconstructedWork(
        work_id=work_id,
        intent=intent,
        target_operation_id=target_op_id,
        source_operation_id=source_op_id,
        plan=reconstructed_plan,
        authorized=is_authorized,
        auth_reason=auth_reason,
    )


def _substitute_paths_in_plan(plan_node: Any, resolved_paths: Dict[str, str]) -> Any:
    """Recursively traverse plan structure and substitute artifact references."""
    if isinstance(plan_node, dict):
        new_dict = {}
        for k, v in plan_node.items():
            if isinstance(v, str) and v in resolved_paths:
                new_dict[k] = resolved_paths[v]
                log.info("N4 Reconstruction Mapping: Substitute '%s' -> '%s' in field '%s'", v, resolved_paths[v], k)
            else:
                new_dict[k] = _substitute_paths_in_plan(v, resolved_paths)
        return new_dict
    elif isinstance(plan_node, list):
        return [_substitute_paths_in_plan(item, resolved_paths) for item in plan_node]
    elif isinstance(plan_node, str) and plan_node in resolved_paths:
        return resolved_paths[plan_node]
    else:
        return plan_node