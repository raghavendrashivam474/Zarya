"""
S6: Verified Multi-Step Work — bounded, evidence-grounded multi-step work execution.

Consumes structured work plans, validates them, checks authorization boundaries,
and executes steps sequentially. Integrates with S4 failure reasoning and
S5 closed-loop recovery at the step level.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .registry import TOOLS, load_all

# Ensure tools are loaded when work executor is imported
load_all()

log = logging.getLogger("elysia.work")

# ---------------------------------------------------------------------------
# Constants & Bounds
# ---------------------------------------------------------------------------
MAX_STEPS = 16

# Work-level outcomes
OUTCOME_VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
OUTCOME_VERIFIED_FAILURE = "VERIFIED_FAILURE"
OUTCOME_UNKNOWN = "UNKNOWN"
OUTCOME_INCOMPLETE = "INCOMPLETE"

# Step statuses
STEP_SUCCESS = "VERIFIED_SUCCESS"
STEP_RECOVERED = "RECOVERED"
STEP_FAILURE = "VERIFIED_FAILURE"
STEP_UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Validation & Orchestration Helpers
# ---------------------------------------------------------------------------

def validate_plan(plan: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate plan structure, bounds, and arguments before execution.

    Returns:
        (is_valid, reason) tuple.
    """
    if not isinstance(plan, dict):
        return False, "Plan must be a structured dictionary."

    steps = plan.get("steps")
    if not steps:
        return False, "Plan must contain a non-empty list of steps."

    if not isinstance(steps, list):
        return False, "Steps must be a list."

    if len(steps) > MAX_STEPS:
        return False, f"Plan exceeds maximum allowed steps of {MAX_STEPS} (got {len(steps)})."

    seen_ids = set()
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            return False, f"Step at index {index} must be a dictionary."

        step_id = step.get("id")
        if not step_id or not isinstance(step_id, str):
            return False, f"Step at index {index} is missing a valid string 'id'."

        if step_id in seen_ids:
            return False, f"Duplicate step ID found: '{step_id}'."
        seen_ids.add(step_id)

        tool = step.get("tool")
        if not tool or not isinstance(tool, str):
            return False, f"Step '{step_id}' must specify a string 'tool'."

        if tool not in TOOLS:
            return False, f"Step '{step_id}' references unknown tool: '{tool}'."

        args = step.get("args")
        if args is not None and not isinstance(args, dict):
            return False, f"Step '{step_id}' 'args' must be a dictionary if provided."

    return True, "Plan is valid."


def _evaluate_step_outcome(response: Dict[str, Any], unverified_ok: bool) -> tuple[str, str]:
    """Analyze tool response and S5 payload to determine step outcome.

    Returns:
        (step_status, detail_message) tuple.
    """
    verification = response.get("verification")
    recovery = response.get("recovery")

    # If verification payload is absent
    if not verification:
        if unverified_ok:
            return STEP_SUCCESS, "Step executed successfully (unverified_ok=True)."
        return STEP_UNKNOWN, "Step returned no verification payload and unverified_ok is False."

    v_status = verification.get("status", "UNKNOWN")

    if v_status == "VERIFIED_SUCCESS":
        return STEP_SUCCESS, verification.get("detail", "Step verified successfully.")

    if v_status == "VERIFIED_FAILURE":
        # S5 closed-loop recovery check
        if recovery and recovery.get("status") == "RECOVERED":
            return STEP_RECOVERED, f"Step failed initially but S5 recovery succeeded: {recovery.get('reason')}"
        
        detail_msg = verification.get("detail", "Step verification failed.")
        if recovery and recovery.get("status") in ("FAILED", "UNKNOWN"):
            detail_msg += f" S5 recovery attempt status: {recovery.get('status')} ({recovery.get('reason')})"
        return STEP_FAILURE, detail_msg

    # UNKNOWN step verification
    if unverified_ok:
        return STEP_SUCCESS, f"Step verification status was UNKNOWN but permitted by unverified_ok=True."
    return STEP_UNKNOWN, verification.get("detail", "Step verification returned UNKNOWN.")


# ---------------------------------------------------------------------------
# Core Executor
# ---------------------------------------------------------------------------

def execute_work(plan: Dict[str, Any], authorized: bool = False) -> Dict[str, Any]:
    """Execute a validated work plan sequentially.

    Ensures safety limits, failure isolation, S5 recovery checks,
    and returns a structured WorkResult.
    """
    goal = plan.get("goal", "Execute multi-step task")
    steps = plan.get("steps", [])

    # Step 1: Pre-execution Plan Validation
    valid, validation_reason = validate_plan(plan)
    if not valid:
        return {
            "goal": goal,
            "overall_status": OUTCOME_INCOMPLETE,
            "summary": f"Plan validation failed: {validation_reason}",
            "completed_steps": [],
            "failed_step": None,
            "skipped_steps": [s.get("id") for s in steps if isinstance(s, dict) and s.get("id")]
        }

    # Step 2: Work Authorization Boundary Check
    if not authorized:
        return {
            "goal": goal,
            "overall_status": OUTCOME_INCOMPLETE,
            "summary": "Plan execution rejected: Plan was not authorized.",
            "completed_steps": [],
            "failed_step": None,
            "skipped_steps": [s["id"] for s in steps]
        }

    completed_steps = []
    failed_step_info = None
    skipped_steps = [s["id"] for s in steps]

    overall_status = OUTCOME_VERIFIED_SUCCESS
    summary_message = "All steps completed and verified successfully."

    # Step 3: Sequential execution loop
    for step in steps:
        step_id = step["id"]
        tool_name = step["tool"]
        args = step.get("args") or {}
        unverified_ok = bool(step.get("unverified_ok", False))

        # Update tracking
        skipped_steps.remove(step_id)

        log.info("Executing step '%s' via tool '%s' with args %s", step_id, tool_name, args)

        try:
            # Synchronous invocation of the registered tool
            tool_handler = TOOLS[tool_name]
            response = tool_handler(args)
        except Exception as exc:
            # Handle catastrophic tool or unexpected exceptions
            log.exception("Catastrophic error during execution of step '%s'", step_id)
            overall_status = OUTCOME_VERIFIED_FAILURE
            summary_message = f"Halted at step '{step_id}' due to unexpected error: {exc}"
            failed_step_info = {
                "step_id": step_id,
                "tool": tool_name,
                "status": STEP_FAILURE,
                "summary": f"Unexpected execution error: {exc}",
                "verification": {"status": "UNKNOWN", "detail": str(exc)},
                "state": {},
                "failure": {
                    "category": "TERMINAL_ERROR_DETECTED" if tool_name == "runTerminalCommand" else "APPLICATION_VERIFICATION_FAILED",
                    "summary": f"Step raised exception: {exc}",
                    "confidence": "HIGH"
                },
                "recovery": {"status": "NOT_ATTEMPTED", "reason": "Execution crash bypasses recovery."}
            }
            break

        # Step 4: Evaluate outcome
        step_status, detail_msg = _evaluate_step_outcome(response, unverified_ok)

        recorded_step = {
            "step_id": step_id,
            "tool": tool_name,
            "status": step_status,
            "verification": response.get("verification"),
            "state": response.get("state"),
            "failure": response.get("failure"),
            "recovery": response.get("recovery")
        }

        completed_steps.append(recorded_step)

        # Halt immediately if step did not succeed or recover successfully
        if step_status not in (STEP_SUCCESS, STEP_RECOVERED):
            if step_status == STEP_UNKNOWN:
                overall_status = OUTCOME_UNKNOWN
                summary_message = f"Halted at step '{step_id}': outcome is UNKNOWN. {detail_msg}"
            else:
                overall_status = OUTCOME_VERIFIED_FAILURE
                summary_message = f"Halted at step '{step_id}': verification failed. {detail_msg}"

            failed_step_info = recorded_step
            break

    return {
        "goal": goal,
        "overall_status": overall_status,
        "summary": summary_message,
        "completed_steps": completed_steps,
        "failed_step": failed_step_info,
        "skipped_steps": skipped_steps
    }


__all__ = [
    "execute_work",
    "validate_plan",
    "MAX_STEPS",
    "OUTCOME_VERIFIED_SUCCESS",
    "OUTCOME_VERIFIED_FAILURE",
    "OUTCOME_UNKNOWN",
    "OUTCOME_INCOMPLETE",
    "STEP_SUCCESS",
    "STEP_RECOVERED",
    "STEP_FAILURE",
    "STEP_UNKNOWN"
]
