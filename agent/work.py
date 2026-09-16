"""
S6: Verified Multi-Step Work System.

Core orchestration engine for executing bounded, sequential multi-step plans
with per-step verification, S3 state observation, S4 failure reasoning,
S5 autonomous recovery, S10 runtime adaptation, and S12 artifact identity continuity.

Invariants:
  1. Multi-step work must not run unboundedly (hard MAX_STEPS = 10 cap).
  2. Plan execution stops on unrecovered failure or UNKNOWN without fallback.
  3. Every step outcome must carry S2 verification status and evidence.
  4. Final WorkResult is truthful and non-hallucinated.
  5. Recovery authority remains with S5; adaptation authority with S10.
  6. S12: Concrete artifact identity is preserved and propagated across steps.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .registry import TOOLS, load_all
from .adaptive_work import (
    DECISION_ADAPT,
            MAX_ADAPTATION_ROUNDS,
    reassess,
)
from .artifacts import active_context, resolve_target, PRONOUN_REFERENCES, ResolutionStatus
from agent.context.resolver import resolve_context_reference
from agent.context.references import classify_reference, CanonicalReference

# Ensure tools are loaded when work executor is imported
load_all()

log = logging.getLogger("zarya.work")

# Hard execution bounds
MAX_STEPS = 10

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


def _interpolate_step_args(
    tool_name: str,
    args: Dict[str, Any],
    completed_steps: List[Dict[str, Any]],
    context: Optional[Any] = None,
) -> Dict[str, Any]:
    """Resolve referential placeholders and pronouns in step args to canonical targets.

    S12 Invariant: If an argument references 'it', '$ACTIVE_ARTIFACT', or 'that file',
    resolve it deterministically to the active artifact locator.
    """
    ctx = context or active_context
    resolved_args = dict(args)

    # Check common target fields
    target_keys = ["path", "target", "target_path", "filepath", "name", "query", "command"]
    for k in list(resolved_args.keys()):
        val = resolved_args[k]
        if isinstance(val, str):
            val_strip = val.strip()
            val_lower = val_strip.lower()

            # S16: Try unified context resolver first for natural-language references
            # Skip template variables ($, {{) ? those are S12's domain
            if not val_strip.startswith("$") and "{{" not in val_strip:
                ref_type = classify_reference(val_strip)
                if ref_type not in (CanonicalReference.UNKNOWN,):
                    s16_result = resolve_context_reference(val_strip, ctx)
                    if s16_result.status == "RESOLVED" and s16_result.target:
                        resolved_args[k] = s16_result.target
                        log.info("S16 work: resolved arg '%s': '%s' -> '%s' (via %s, freshness=%s)",
                                 k, val, s16_result.target, s16_result.evidence_source, s16_result.freshness)
                        continue  # Skip S12 fallback for this arg

            # S12: Exact pronoun / placeholder reference (fallback)
            if val_lower in PRONOUN_REFERENCES or val_strip.startswith("$") or "{{" in val_strip:
                resolution = ctx.resolve_target(val_strip)
                if resolution.is_resolved and resolution.canonical_locator:
                    resolved_args[k] = resolution.canonical_locator
                    log.info("S12 work: resolved arg '%s': '%s' -> '%s'", k, val, resolution.canonical_locator)

    # If openApplication was given without target, but active artifact exists and step description implies it
    if tool_name == "openApplication" and not resolved_args.get("target"):
        if ctx.active_artifact and ctx.active_artifact.artifact_type == "file":
            # Check if there was a preceding file step in this plan
            if completed_steps:
                last_step = completed_steps[-1]
                if last_step.get("tool") in ("createFile", "readFile", "writeCodeFile", "createPythonFile"):
                    resolved_args["target"] = ctx.active_artifact.canonical_locator
                    log.info("S12 work: auto-attached active artifact target to openApplication: %s", resolved_args["target"])

    return resolved_args


# ---------------------------------------------------------------------------
# Validation & Orchestration Helpers
# ---------------------------------------------------------------------------

def validate_plan(plan: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate plan structure, bounds, and arguments before execution."""
    if not isinstance(plan, dict):
        return False, "Plan must be a structured dictionary."

    steps = plan.get("steps")
    if not isinstance(steps, list):
        return False, "Plan must contain a 'steps' list."

    if len(steps) == 0:
        return False, "Plan steps must be a non-empty list."

    if len(steps) > MAX_STEPS:
        return False, f"Plan exceeds maximum allowed steps ({len(steps)} > {MAX_STEPS})."

    seen_ids = set()
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            return False, f"Step #{idx} must be a dict."

        step_id = step.get("id")
        if not step_id or not isinstance(step_id, str):
            return False, f"Step #{idx} must specify a non-empty string 'id'."

        if step_id in seen_ids:
            return False, f"Duplicate step ID '{step_id}' found in plan."
        seen_ids.add(step_id)

        tool = step.get("tool")
        if not tool or not isinstance(tool, str):
            return False, f"Step '{step_id}' must specify a string 'tool'."

        if tool not in TOOLS:
            return False, f"Step '{step_id}' references unknown tool: '{tool}'."

        args = step.get("args")
        if args is not None and not isinstance(args, dict):
            return False, f"Step '{step_id}' 'args' must be a dictionary."

    return True, "Plan is valid."


def _evaluate_step_outcome(response: Dict[str, Any], unverified_ok: bool) -> tuple[str, str]:
    """Analyze tool response and S5 payload to determine step outcome."""
    verification = response.get("verification")
    recovery = response.get("recovery")

    if not verification:
        if unverified_ok:
            return STEP_SUCCESS, "Step executed successfully (unverified_ok=True)."
        return STEP_UNKNOWN, "Step returned no verification payload and unverified_ok is False."

    v_status = verification.get("status", "UNKNOWN")

    if v_status == "VERIFIED_SUCCESS":
        return STEP_SUCCESS, verification.get("detail", "Verified successfully.")

    if recovery and isinstance(recovery, dict):
        rec_status = recovery.get("status")
        if rec_status == "RECOVERED":
            return STEP_RECOVERED, f"Step recovered via S5: {recovery.get('strategy_name', 'recovery')}"
        elif rec_status == "EXHAUSTED":
            return STEP_FAILURE, f"Recovery exhausted: {recovery.get('reason', 'all strategies failed')}"

    if v_status == "VERIFIED_FAILURE":
        return STEP_FAILURE, verification.get("detail", "Verification failed.")

    return STEP_UNKNOWN, verification.get("detail", "Verification returned UNKNOWN.")


def _emit_step_event(
    callback: Optional[Callable[[Dict[str, Any]], None]],
    event_type: str,
    step_id: str,
    tool_name: str,
    step_index: int,
    total_steps: int,
    state: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """Safely emit an S11 step event via the provided callback."""
    if callback is None:
        return
    try:
        evt = {
            "event": event_type,
            "step_id": step_id,
            "tool": tool_name,
            "step_index": step_index,
            "total_steps": total_steps,
            "state": state,
            "payload": payload or {},
        }
        callback(evt)
    except Exception as exc:
        log.warning("S11 step event emission failed for '%s': %s", event_type, exc)


# ---------------------------------------------------------------------------
# Main Multi-Step Work Executor
# ---------------------------------------------------------------------------

def execute_work(
    plan: Dict[str, Any],
    authorized: bool = False,
    step_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    adaptive: bool = False,
    context: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute a validated WorkPlan sequentially with S12 context continuity."""
    is_valid, validation_reason = validate_plan(plan)
    goal = plan.get("goal", "") if isinstance(plan, dict) else ""
    initial_steps = plan.get("steps", []) if isinstance(plan, dict) and isinstance(plan.get("steps"), list) else []

    if not is_valid:
        return {
            "goal": goal,
            "overall_status": OUTCOME_INCOMPLETE,
            "summary": f"Plan validation failed: {validation_reason}",
            "completed_steps": [],
            "failed_step": None,
            "skipped_steps": [s.get("id") for s in initial_steps if isinstance(s, dict) and s.get("id")],
        }

    if not authorized:
        return {
            "goal": goal,
            "overall_status": OUTCOME_INCOMPLETE,
            "summary": "Plan execution rejected: Plan was not authorized.",
            "completed_steps": [],
            "failed_step": None,
            "skipped_steps": [s["id"] for s in initial_steps],
        }

    completed_steps: List[Dict[str, Any]] = []
    failed_step_info: Optional[Dict[str, Any]] = None
    execution_queue: List[Dict[str, Any]] = list(initial_steps)

    overall_status = OUTCOME_VERIFIED_SUCCESS
    summary_message = "All steps completed and verified successfully."

    adaptation_round = 0
    adaptations_log: List[Dict[str, Any]] = []

    while execution_queue:
        if len(completed_steps) >= MAX_STEPS:
            overall_status = OUTCOME_INCOMPLETE
            summary_message = f"Execution reached maximum step limit ({MAX_STEPS})."
            break

        step = execution_queue.pop(0)
        step_id = step["id"]
        tool_name = step["tool"]
        raw_args = step.get("args") or {}
        unverified_ok = bool(step.get("unverified_ok", False))

        # S12: Interpolate referential placeholders with active artifact context
        ctx = context or active_context
        args = _interpolate_step_args(tool_name, raw_args, completed_steps, context=ctx)

        log.info("Executing step '%s' via tool '%s' with args %s", step_id, tool_name, args)

        _emit_step_event(
            callback=step_callback,
            event_type="work_step_started",
            step_id=step_id,
            tool_name=tool_name,
            step_index=len(completed_steps),
            total_steps=len(initial_steps),
            state="WORKING",
            payload={"args": args},
        )

        try:
            tool_handler = TOOLS[tool_name]
            response = tool_handler(args)
        except Exception as exc:
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
                    "confidence": "HIGH",
                },
                "recovery": {"status": "NOT_ATTEMPTED", "reason": "Execution crash bypasses recovery."},
            }
            break

        # Step 4: Evaluate outcome
        step_status, detail_msg = _evaluate_step_outcome(response, unverified_ok)

        # S12: Update active context with verified tool outcome
        ctx.update_from_tool_response(tool_name, args, response)

        recorded_step = {
            "step_id": step_id,
            "tool": tool_name,
            "status": step_status,
            "verification": response.get("verification"),
            "state": response.get("state"),
            "failure": response.get("failure"),
            "recovery": response.get("recovery"),
        }
        if "path" in response:
            recorded_step["path"] = response["path"]
        if "target" in response:
            recorded_step["target"] = response["target"]

        completed_steps.append(recorded_step)

        event_state = "VERIFIED_SUCCESS" if step_status in (STEP_SUCCESS, STEP_RECOVERED) else (
            "UNKNOWN" if step_status == STEP_UNKNOWN else "VERIFIED_FAILURE"
        )
        _emit_step_event(
            callback=step_callback,
            event_type="work_step_completed",
            step_id=step_id,
            tool_name=tool_name,
            step_index=len(completed_steps) - 1,
            total_steps=len(initial_steps),
            state=event_state,
            payload={
                "status": step_status,
                "detail": detail_msg,
                "verification": response.get("verification"),
                "recovery": response.get("recovery"),
                "state": response.get("state"),
            },
        )

        if step_status not in (STEP_SUCCESS, STEP_RECOVERED):
            if adaptive:
                decision_dict = reassess(
                    goal=goal,
                    remaining_steps=execution_queue,
                    last_step_result=recorded_step,
                    adaptation_round=adaptation_round,
                )
                decision = decision_dict.get("decision")
                reason = decision_dict.get("reason", "")
                candidate_steps = decision_dict.get("candidate_steps", [])

                if decision == DECISION_ADAPT and candidate_steps:
                    adaptation_round += 1
                    adaptations_log.append({
                        "round": adaptation_round,
                        "trigger_step": step_id,
                        "reason": reason,
                        "injected_steps": [s["id"] for s in candidate_steps],
                    })
                    log.info("S10 Adaptation #%d triggered: %s. Injecting %d steps.", adaptation_round, reason, len(candidate_steps))
                    execution_queue = candidate_steps + execution_queue
                    continue

            if step_status == STEP_UNKNOWN:
                overall_status = OUTCOME_UNKNOWN
                summary_message = f"Halted at step '{step_id}': outcome is UNKNOWN. {detail_msg}"
            else:
                overall_status = OUTCOME_VERIFIED_FAILURE
                summary_message = f"Halted at step '{step_id}': verification failed. {detail_msg}"

            failed_step_info = recorded_step
            break

    skipped_steps = [s["id"] for s in execution_queue]

    result: Dict[str, Any] = {
        "goal": goal,
        "overall_status": overall_status,
        "summary": summary_message,
        "completed_steps": completed_steps,
        "failed_step": failed_step_info,
        "skipped_steps": skipped_steps,
    }

    if adaptive:
        result["adaptations"] = adaptations_log

    return result


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
    "STEP_UNKNOWN",
]


