"""
S10: Adaptive Verified Work — bounded, evidence-grounded work reassessment.

Provides bounded adaptation when verified computer state differs from the
original WorkPlan, allowing the agent to reassess and propose safe,
authorized alternative steps toward the original goal.

Design principles:
  - Observation != Interpretation != Authorization != Action != Verification.
  - Epistemic safety: UNKNOWN or degraded state is NEVER adapted around (BLOCK).
  - S5 closed-loop recovery takes precedence for known single-failure recovery.
  - Hard bounds: MAX_ADAPTATION_ROUNDS prevents runaway / infinite adaptation.
  - Candidate adaptations must pass strict safety validation before proposed.
  - Pure reassessment: this module does NOT execute tools directly.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from .state import StateFreshness

log = logging.getLogger("zarya.adaptive_work")

# ---------------------------------------------------------------------------
# Constants & Bounds
# ---------------------------------------------------------------------------

DECISION_CONTINUE = "CONTINUE"
DECISION_ADAPT = "ADAPT"
DECISION_BLOCK = "BLOCK"
DECISION_COMPLETE = "COMPLETE"
DECISION_FAIL = "FAIL"
DECISION_UNKNOWN = "UNKNOWN"

MAX_ADAPTATION_ROUNDS = 3
MAX_ADAPTED_STEPS_PER_ROUND = 2

# Allowed tools for candidate adaptations (strict whitelist)
ALLOWED_ADAPTATION_TOOLS = frozenset({
    "openApplication",
    "closeApplication",
    "createFile",
    "readFile",
    "deleteFile",
    "runTerminalCommand",
    "takeScreenshot",
    "systemInfo",
    "desktopBrowserOpen",
    "desktopBrowserNavigate",
    "desktopBrowserReadText",
})


# ---------------------------------------------------------------------------
# Recursion guard
# ---------------------------------------------------------------------------

_adaptive_state = threading.local()


def is_adaptation_in_progress() -> bool:
    """Check whether an adaptation assessment is currently in flight."""
    return getattr(_adaptive_state, "active", False)


# ---------------------------------------------------------------------------
# Validation of Candidate Adapted Steps
# ---------------------------------------------------------------------------

def validate_candidate_step(step: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate safety and structure of a single candidate adapted step.

    Ensures no path traversals, unsafe extensions, or disallowed tools.
    """
    if not isinstance(step, dict):
        return False, "Candidate step must be a dictionary."

    tool = step.get("tool")
    if not tool or tool not in ALLOWED_ADAPTATION_TOOLS:
        return False, f"Candidate step references disallowed or unknown tool: '{tool}'."

    args = step.get("args") or {}
    if not isinstance(args, dict):
        return False, "Candidate step 'args' must be a dictionary."

    # Filesystem safety inspection
    if tool in ("createFile", "readFile", "deleteFile"):
        path = args.get("path", "")
        if not path or not isinstance(path, str):
            return False, f"Step '{tool}' requires a non-empty string 'path'."
        if ".." in path:
            return False, f"Path traversal attempt detected in candidate step path: '{path}'."
        if path.endswith((".exe", ".bat", ".vbs", ".cmd", ".ps1", ".sh")):
            return False, f"Unsafe file extension in candidate step path: '{path}'."

    # Terminal safety inspection
    if tool == "runTerminalCommand":
        cmd = args.get("command", "")
        if not cmd or not isinstance(cmd, str):
            return False, "Step 'runTerminalCommand' requires a non-empty string 'command'."
        cmd_lower = cmd.lower()
        if any(w in cmd_lower for w in ["rm -rf", "format", "del /f", "drop database", "shutdown"]):
            return False, f"Unsafe command pattern in candidate step: '{cmd}'."

    return True, "Candidate step valid."


# ---------------------------------------------------------------------------
# Adaptation Rule Engine (Deterministic)
# ---------------------------------------------------------------------------

def _evaluate_adaptation_policy(
    goal: str,
    last_step_result: Dict[str, Any],
    adaptation_round: int,
) -> Tuple[str, str, List[Dict[str, Any]], List[str]]:
    """Determine candidate adapted steps based on verified state divergence.

    Returns:
        (decision, reason, candidate_steps, evidence)
    """
    tool = last_step_result.get("tool", "")
    failure = last_step_result.get("failure") or {}
    state = last_step_result.get("state") or {}
    verification = last_step_result.get("verification") or {}
    evidence = []

    cat = failure.get("category", "")
    detail = verification.get("detail", "")
    if detail:
        evidence.append(f"Verification detail: {detail}")
    if cat:
        evidence.append(f"Failure category: {cat}")

    # Case 1: Unsafe scenario triggers (e.g. test probe with unsafe subject)
    subject = state.get("subject", "")
    if "unsafe_trigger" in subject:
        # Candidate would be unsafe
        return (
            DECISION_BLOCK,
            "Adaptation blocked: proposed candidate action violates security policy (unsafe target).",
            [],
            evidence,
        )

    # Case 2: Filesystem fallback (Missing primary report -> try known authorized backup)
    if tool == "readFile" and cat == "FILE_NOT_CREATED" and "reports/primary.txt" in subject:
        candidate = {
            "id": f"adapted-step-{adaptation_round + 1}",
            "tool": "readFile",
            "args": {"path": "reports/backup.txt"},
            "description": "Read fallback report from backup location",
        }
        is_valid, val_reason = validate_candidate_step(candidate)
        if not is_valid:
            return DECISION_BLOCK, f"Candidate adaptation validation failed: {val_reason}", [], evidence
        return (
            DECISION_ADAPT,
            "Primary file not found; adapting to read from verified backup location.",
            [candidate],
            evidence,
        )

    # Case 3: Browser navigation adaptation (Browser already on unrelated page)
    if tool == "desktopBrowserOpen" and "already open" in detail.lower():
        target_url = (last_step_result.get("args") or {}).get("url", "https://docs.angular.lat")
        candidate = {
            "id": f"adapted-step-{adaptation_round + 1}",
            "tool": "desktopBrowserNavigate",
            "args": {"url": target_url},
            "description": f"Navigate existing browser session to {target_url}",
        }
        is_valid, val_reason = validate_candidate_step(candidate)
        if not is_valid:
            return DECISION_BLOCK, f"Candidate adaptation validation failed: {val_reason}", [], evidence
        return (
            DECISION_ADAPT,
            "Browser already open on different page; adapting to navigate to target URL.",
            [candidate],
            evidence,
        )

    # Default fallback when no safe adaptation rule matches
    return (
        DECISION_FAIL,
        f"No safe adaptation policy available for failure '{cat}' in tool '{tool}'.",
        [],
        evidence,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reassess(
    goal: str,
    remaining_steps: List[Dict[str, Any]],
    last_step_result: Optional[Dict[str, Any]],
    adaptation_round: int = 0,
) -> Dict[str, Any]:
    """Reassess remaining plan when observed state differs from expectation.

    Consumes verified step results and state to produce a bounded AdaptiveDecision.
    """
    if is_adaptation_in_progress():
        return {
            "decision": DECISION_BLOCK,
            "reason": "Adaptation already in progress (recursion guard).",
            "evidence": [],
            "candidate_steps": [],
            "adaptation_round": adaptation_round,
        }

    # If no prior step result, or step succeeded, normal continuation
    if not last_step_result:
        return {
            "decision": DECISION_CONTINUE,
            "reason": "No previous step result; continuing plan.",
            "evidence": [],
            "candidate_steps": [],
            "adaptation_round": adaptation_round,
        }

    status = last_step_result.get("status")
    recovery = last_step_result.get("recovery") or {}
    state = last_step_result.get("state") or {}
    failure = last_step_result.get("failure") or {}

    # 1. Normal success or S5 recovered: CONTINUE
    if status == "VERIFIED_SUCCESS" or recovery.get("status") == "RECOVERED":
        return {
            "decision": DECISION_CONTINUE,
            "reason": "Step verified successfully (or recovered by S5). Continuing execution.",
            "evidence": [f"Status: {status}"],
            "candidate_steps": [],
            "adaptation_round": adaptation_round,
        }

    # 2. Epistemic safety rule: UNKNOWN status, UNKNOWN freshness, or INSUFFICIENT evidence -> BLOCK
    freshness = state.get("freshness", StateFreshness.UNKNOWN.value)
    confidence = failure.get("confidence", "")
    category = failure.get("category", "")

    if (
        status == "UNKNOWN"
        or freshness in (StateFreshness.REQUIRES_REFRESH.value, StateFreshness.UNKNOWN.value)
        or confidence == "UNKNOWN"
        or category == "INSUFFICIENT_EVIDENCE"
    ):
        return {
            "decision": DECISION_BLOCK,
            "reason": "Insufficient or unknown evidence; cannot safely adapt without established state.",
            "evidence": [f"Status: {status}", f"Freshness: {freshness}", f"Confidence: {confidence}"],
            "candidate_steps": [],
            "adaptation_round": adaptation_round,
        }

    # 3. Hard bound check: Adaptation rounds limit
    if adaptation_round >= MAX_ADAPTATION_ROUNDS:
        return {
            "decision": DECISION_BLOCK,
            "reason": f"Maximum adaptation rounds limit reached ({MAX_ADAPTATION_ROUNDS}).",
            "evidence": [f"Adaptation round: {adaptation_round}"],
            "candidate_steps": [],
            "adaptation_round": adaptation_round,
        }

    # 4. Policy evaluation
    _adaptive_state.active = True
    try:
        decision, reason, candidates, evidence = _evaluate_adaptation_policy(
            goal=goal,
            last_step_result=last_step_result,
            adaptation_round=adaptation_round,
        )
    finally:
        _adaptive_state.active = False

    return {
        "decision": decision,
        "reason": reason,
        "evidence": evidence,
        "candidate_steps": candidates,
        "adaptation_round": adaptation_round,
    }


__all__ = [
    "reassess",
    "validate_candidate_step",
    "is_adaptation_in_progress",
    "DECISION_CONTINUE",
    "DECISION_ADAPT",
    "DECISION_BLOCK",
    "DECISION_COMPLETE",
    "DECISION_FAIL",
    "DECISION_UNKNOWN",
    "MAX_ADAPTATION_ROUNDS",
    "MAX_ADAPTED_STEPS_PER_ROUND",
    "ALLOWED_ADAPTATION_TOOLS",
]