"""
S5: Closed-Loop Recovery -- bounded, evidence-grounded recovery layer.

Consumes S4 failure reasoning and S3 state to determine whether a
single, justified recovery action should be attempted after a verified
failure. Recovery is itself an action that must be observed and verified.

Design principles:
  - One failure -> one recovery opportunity -> verify -> STOP.
  - Recovery eligibility is policy-driven, not speculative.
  - Authorization is checked explicitly as a policy gate in this layer,
    never assumed from parameter validation or tool capability.
  - UNKNOWN failures are NEVER recovered (epistemic safety rule).
  - Original failure is preserved, never overwritten.
  - No loops, no planning, no persistence, no LLM.
  - Recursion guard prevents recovery-of-recovery.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Tuple

from .failure import (
    CAT_APP_NOT_OBSERVED,
    CAT_INSUFFICIENT,
    CONFIDENCE_UNKNOWN,
)


# ---------------------------------------------------------------------------
# Recovery status constants
# ---------------------------------------------------------------------------

RECOVERED = "RECOVERED"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"
NOT_ELIGIBLE = "NOT_ELIGIBLE"
NOT_ATTEMPTED = "NOT_ATTEMPTED"


# ---------------------------------------------------------------------------
# Recursion guard
# ---------------------------------------------------------------------------

_recovery_state = threading.local()


def is_recovery_in_progress() -> bool:
    """Check whether a recovery action is currently executing.

    Prevents infinite recursion when recovery re-invokes a tool
    that itself triggers recovery logic.
    """
    return getattr(_recovery_state, "active", False)


# ---------------------------------------------------------------------------
# Recovery policy matrix (Hardened)
# ---------------------------------------------------------------------------

RECOVERY_POLICY: Dict[str, Dict[str, Any]] = {
    CAT_APP_NOT_OBSERVED: {
        "recovery_action": "RELAUNCH_APPLICATION",
        "tool_name": "openApplication",
        "requires_authorization": True,
        "max_attempts": 1,
        "requires_freshness": "CURRENT",
    },
    # Filesystem recovery (CAT_FILE_NOT_CREATED) is deliberately deferred to
    # avoid destructive TOCTOU overwrite race conditions in S5.
}


# ---------------------------------------------------------------------------
# Eligibility check
# ---------------------------------------------------------------------------

def check_eligibility(
    failure: Optional[Dict[str, Any]],
    state: Dict[str, Any],
) -> Tuple[bool, str]:
    """Determine whether recovery is eligible for this failure.

    Returns:
        (is_eligible, reason) tuple.
    """
    if failure is None:
        return False, "No failure to recover from."

    category = failure.get("category", "")
    confidence = failure.get("confidence", "")
    freshness = state.get("freshness", "UNKNOWN")

    # Epistemic safety rule: UNKNOWN != permission to act
    if confidence == CONFIDENCE_UNKNOWN:
        return False, "Insufficient evidence to justify recovery."

    if category == CAT_INSUFFICIENT:
        return False, "INSUFFICIENT_EVIDENCE failures are not recoverable."

    # Freshness gate
    if freshness in ("REQUIRES_REFRESH", "UNKNOWN"):
        return False, (
            f"State freshness '{freshness}' too degraded for safe recovery."
        )

    # Policy lookup
    policy = RECOVERY_POLICY.get(category)
    if policy is None:
        return False, f"No recovery policy for category '{category}'."

    # Strict freshness requirement
    required_freshness = policy.get("requires_freshness", "CURRENT")
    if freshness != required_freshness:
        return False, (
            f"Recovery for '{category}' requires {required_freshness} "
            f"freshness, got '{freshness}'."
        )

    return True, "Recovery eligible per policy."


# ---------------------------------------------------------------------------
# Explicit Policy Authorization Check
# ---------------------------------------------------------------------------

def check_authorization(
    failure: Dict[str, Any],
    original_tool_name: str,
    original_args: Dict[str, Any],
) -> Tuple[bool, str]:
    """Determine if recovery is authorized by explicit policy.

    We do not infer authorization from parameter validation (like _ensure_safe
    or _resolve_app). S5 recovery authorization is an explicit policy decision
    enforced inside this layer. General multi-tenant / untrusted user
    authorization infrastructure is deferred.

    Returns:
        (is_authorized, reason) tuple.
    """
    category = failure.get("category", "")
    policy = RECOVERY_POLICY.get(category)

    if policy is None:
        return False, f"No recovery policy mapped for '{category}'."

    # Gate explicitly on policy requirements
    if policy.get("requires_authorization"):
        if category == CAT_APP_NOT_OBSERVED:
            return True, "Authorized: Relaunching application is safe and explicitly permitted by policy."
        return False, f"Unauthorized: Recovery policy for '{category}' does not authorize automatic recovery."

    return True, "Authorized: Policy does not require explicit recovery-level authorization."


# ---------------------------------------------------------------------------
# Recovery action execution
# ---------------------------------------------------------------------------

def _perform_recovery_action(
    recovery_action: str,
    tool_name: str,
    original_args: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute the bounded recovery action by re-invoking the original tool.

    Returns the inner tool's verification dict.
    """
    from .registry import TOOLS

    if tool_name not in TOOLS:
        return {
            "status": "UNKNOWN",
            "method": "none",
            "detail": f"Recovery tool '{tool_name}' not found in registry.",
        }

    if recovery_action == "RELAUNCH_APPLICATION":
        result = TOOLS[tool_name](original_args)
        return result.get("verification", {"status": "UNKNOWN"})

    return {
        "status": "UNKNOWN",
        "method": "none",
        "detail": f"Unknown recovery action: {recovery_action}",
    }


# ---------------------------------------------------------------------------
# Result builder
# ---------------------------------------------------------------------------

def _build_result(
    status: str,
    reason: str,
    action: Optional[str] = None,
    authorized: bool = False,
    attempts: int = 0,
    verification: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construct a standardized recovery result dict."""
    return {
        "status": status,
        "reason": reason,
        "action": action,
        "authorized": authorized,
        "attempts": attempts,
        "verification": verification,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def attempt_recovery(
    failure: Optional[Dict[str, Any]],
    verification: Dict[str, Any],
    state: Dict[str, Any],
    original_tool_name: str,
    original_args: Dict[str, Any],
) -> Dict[str, Any]:
    """Attempt bounded recovery after a verified failure.

    This is the main S5 entry point, called by tool handlers after
    S4 failure reasoning.

    Returns:
        Recovery result dict.
    """
    # Recursion guard
    if is_recovery_in_progress():
        return _build_result(
            NOT_ATTEMPTED,
            "Recovery already in progress (recursion guard).",
        )

    # Step 1: Eligibility
    eligible, eligibility_reason = check_eligibility(failure, state)
    if not eligible:
        return _build_result(NOT_ELIGIBLE, eligibility_reason)

    # Step 2: Explicit Authorization Check
    authorized, auth_reason = check_authorization(
        failure, original_tool_name, original_args
    )
    if not authorized:
        return _build_result(
            NOT_ATTEMPTED,
            f"Not authorized: {auth_reason}",
        )

    # Step 3: Execute ONE bounded recovery
    category = failure.get("category", "")
    policy = RECOVERY_POLICY[category]
    recovery_action = policy["recovery_action"]
    tool_name = policy["tool_name"]

    _recovery_state.active = True
    try:
        recovery_verification = _perform_recovery_action(
            recovery_action, tool_name, original_args
        )
    except Exception as exc:
        return _build_result(
            FAILED,
            f"Recovery action raised exception: {exc}",
            action=recovery_action,
            authorized=True,
            attempts=1,
        )
    finally:
        _recovery_state.active = False

    # Step 4: Assess recovery outcome
    recovery_status = recovery_verification.get("status", "UNKNOWN")

    if recovery_status == "VERIFIED_SUCCESS":
        return _build_result(
            RECOVERED,
            "Recovery action verified successfully.",
            action=recovery_action,
            authorized=True,
            attempts=1,
            verification=recovery_verification,
        )

    if recovery_status == "VERIFIED_FAILURE":
        return _build_result(
            FAILED,
            "Recovery action executed but verification still failed.",
            action=recovery_action,
            authorized=True,
            attempts=1,
            verification=recovery_verification,
        )

    # UNKNOWN or anything else
    return _build_result(
        UNKNOWN,
        "Recovery action executed but outcome could not be determined.",
        action=recovery_action,
        authorized=True,
        attempts=1,
        verification=recovery_verification,
    )


__all__ = [
    "attempt_recovery",
    "check_eligibility",
    "check_authorization",
    "is_recovery_in_progress",
    "RECOVERED",
    "FAILED",
    "UNKNOWN",
    "NOT_ELIGIBLE",
    "NOT_ATTEMPTED",
    "RECOVERY_POLICY",
]
