"""S18 - Cooperative Work Control (Pause, Resume, Cancel).

Provides non-destructive, cooperative control mechanisms for long-running work.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from agent.checkpoint import CheckpointStore
from agent.lifecycle import LifecycleStatus, WorkState

log = logging.getLogger("zarya.control")


def request_pause(operation_id: str, checkpoint_store: CheckpointStore, reason: str = "User requested pause") -> Dict[str, Any]:
    """Request a cooperative pause on an active operation.

    The running execute_work loop checks this state at step boundaries
    and cleanly transitions to PAUSED with a valid checkpoint.
    """
    work_state = checkpoint_store.load(operation_id)
    if not work_state:
        return {"success": False, "error": f"Operation '{operation_id}' not found."}

    if work_state.status not in (LifecycleStatus.RUNNING, LifecycleStatus.CHECKPOINTED):
        return {
            "success": False,
            "error": f"Cannot pause operation in state '{work_state.status.value}'.",
        }

    # Set status to PAUSED
    work_state.status = LifecycleStatus.PAUSED
    work_state.interruption_info = {"type": "PAUSE", "reason": reason}
    checkpoint_store.save(work_state)
    log.info("Operation '%s' marked as PAUSED.", operation_id)
    return {"success": True, "operation_id": operation_id, "status": work_state.status.value}


def request_cancel(operation_id: str, checkpoint_store: CheckpointStore, reason: str = "User requested cancellation") -> Dict[str, Any]:
    """Request cooperative cancellation on an active operation."""
    work_state = checkpoint_store.load(operation_id)
    if not work_state:
        return {"success": False, "error": f"Operation '{operation_id}' not found."}

    if work_state.is_terminal:
        return {
            "success": False,
            "error": f"Cannot cancel operation already in terminal state '{work_state.status.value}'.",
        }

    # Set status to CANCELLED
    work_state.status = LifecycleStatus.CANCELLED
    work_state.interruption_info = {"type": "CANCEL", "reason": reason}
    checkpoint_store.save(work_state)
    log.info("Operation '%s' marked as CANCELLED.", operation_id)
    return {"success": True, "operation_id": operation_id, "status": work_state.status.value}


def get_operation_status(operation_id: str, checkpoint_store: CheckpointStore) -> Optional[Dict[str, Any]]:
    """Retrieve full durable status of an operation."""
    work_state = checkpoint_store.load(operation_id)
    if not work_state:
        return None
    return work_state.to_dict()