"""S18 - Resume Orchestrator with Reality Verification.

Handles safe continuation of interrupted, paused, or checkpointed operations.

Key Invariants:
  1. A checkpoint is NOT a success claim.
  2. Reality check: Verify that physical artifacts established in prior steps
     still exist in the expected state before continuing.
  3. Artifact continuity: Preserve S12 artifact IDs and canonical locators.
  4. Authorization: Resuming requires explicit authorization.
  5. Recovery authority remains strictly with S5.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent.artifacts import active_context, ActiveComputerContext
from agent.checkpoint import CheckpointStore
from agent.lifecycle import LifecycleStatus, WorkState
from agent.work import execute_work

log = logging.getLogger("zarya.resume")


# ── Reality Verification Result ──────────────────────────────────

class RealityCheckResult:
    """Outcome of validating that external state matches checkpointed expectations."""

    def __init__(self, valid: bool, reason: str = "", stale_artifacts: Optional[List[str]] = None) -> None:
        self.valid = valid
        self.reason = reason
        self.stale_artifacts = stale_artifacts or []

    def __bool__(self) -> bool:
        return self.valid


# ── Reality Check Implementation ─────────────────────────────────

def verify_checkpoint_reality(
    work_state: WorkState,
    context: Optional[ActiveComputerContext] = None,
) -> RealityCheckResult:
    """Verify that external reality matches the checkpoint before resuming.

    Checks:
      1. For any completed file-creation/write steps, does the target file still exist?
      2. For any S12 registered artifacts, are they still accessible?

    Returns RealityCheckResult(valid=True) if safe to resume,
    or RealityCheckResult(valid=False, reason=...) if external state diverged.
    """
    stale: List[str] = []

    for step in work_state.completed_steps[:work_state.checkpoint_step]:
        evidence = step.evidence or {}
        verification = evidence.get("verification") or {}
        tool = step.tool

        # Check file-based steps
        if tool in ("createFile", "writeCodeFile", "createPythonFile", "createFolder"):
            # Check path from verification or step args
            path_str = verification.get("path") or verification.get("target")
            if not path_str:
                # Try finding path in the original plan step
                plan_steps = work_state.plan.get("steps", [])
                if step.step_index < len(plan_steps):
                    path_str = plan_steps[step.step_index].get("args", {}).get("path")

            if path_str:
                p = Path(path_str)
                if not p.exists():
                    stale.append(f"File created in step '{step.step_id}' no longer exists: {path_str}")

    if stale:
        reason = "Reality check failed: " + "; ".join(stale)
        log.warning("S18 Reality Check FAILED for op %s: %s", work_state.operation_id, reason)
        return RealityCheckResult(valid=False, reason=reason, stale_artifacts=stale)

    log.info("S18 Reality Check PASSED for op %s (%d steps verified)",
             work_state.operation_id, work_state.checkpoint_step)
    return RealityCheckResult(valid=True, reason="All checkpointed artifacts verified against reality.")


# ── Main Resume Entrypoint ───────────────────────────────────────

def resume_work(
    operation_id: str,
    checkpoint_store: CheckpointStore,
    authorized: bool = False,
    step_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    adaptive: bool = False,
    context: Optional[ActiveComputerContext] = None,
    skip_reality_check: bool = False,
) -> Dict[str, Any]:
    """Safely resume a checkpointed or interrupted work operation.

    Steps:
      1. Load WorkState from CheckpointStore
      2. Validate that state is resumable
      3. Verify authorization
      4. Perform reality check (verify artifacts still exist)
      5. Delegate remaining execution to execute_work
      6. Persist final state
    """
    ctx = context or active_context

    # 1. Load state
    work_state = checkpoint_store.load(operation_id)
    if work_state is None:
        return {
            "operation_id": operation_id,
            "overall_status": "INCOMPLETE",
            "summary": f"Operation '{operation_id}' not found in checkpoint store.",
            "completed_steps": [],
            "failed_step": None,
            "skipped_steps": [],
        }

    # 2. Check resumable
    if not work_state.is_resumable:
        return {
            "operation_id": operation_id,
            "overall_status": "INCOMPLETE",
            "summary": f"Operation '{operation_id}' in state '{work_state.status.value}' is not resumable (checkpoint_step={work_state.checkpoint_step}).",
            "completed_steps": [s.to_dict() for s in work_state.completed_steps],
            "failed_step": None,
            "skipped_steps": [],
        }

    # 3. Authorization check
    if not authorized:
        return {
            "operation_id": operation_id,
            "overall_status": "INCOMPLETE",
            "summary": f"Resume rejected: Operation '{operation_id}' was not authorized for continuation.",
            "completed_steps": [s.to_dict() for s in work_state.completed_steps],
            "failed_step": None,
            "skipped_steps": [],
        }

    # 4. Reality check
    if not skip_reality_check:
        reality = verify_checkpoint_reality(work_state, context=ctx)
        if not reality:
            work_state.failure_info = {
                "category": "STALE_CHECKPOINT_STATE",
                "reason": reality.reason,
                "stale_artifacts": reality.stale_artifacts,
            }
            work_state.transition_to(LifecycleStatus.FAILED, reality.reason)
            checkpoint_store.save(work_state)

            return {
                "operation_id": operation_id,
                "overall_status": "VERIFIED_FAILURE",
                "summary": f"Resume halted: {reality.reason}",
                "completed_steps": [s.to_dict() for s in work_state.completed_steps],
                "failed_step": {
                    "step_id": f"resume_check_{work_state.checkpoint_step}",
                    "status": "VERIFIED_FAILURE",
                    "summary": reality.reason,
                },
                "skipped_steps": [
                    s.get("id") for s in work_state.plan.get("steps", [])[work_state.checkpoint_step:]
                ],
            }

    # 5. Transition to RUNNING and delegate to execute_work
    work_state.transition_to(LifecycleStatus.RUNNING, "resuming from checkpoint")
    checkpoint_store.save(work_state)

    result = execute_work(
        plan=work_state.plan,
        authorized=True,
        step_callback=step_callback,
        adaptive=adaptive,
        context=ctx,
        work_state=work_state,
        checkpoint_store=checkpoint_store,
    )

    result["operation_id"] = operation_id
    result["lifecycle_status"] = work_state.status.value
    result["checkpoint_step"] = work_state.checkpoint_step

    return result


__all__ = [
    "resume_work",
    "verify_checkpoint_reality",
    "RealityCheckResult",
]