"""EIP-1 Status Projection.

Maps Zarya's internal LifecycleStatus values to a small set of
externally meaningful availability states.

This is a PROJECTION, not a new state machine. The authoritative
lifecycle remains in agent.lifecycle.WorkState.

External status vocabulary:
  READY       - Zarya is running and can accept work
  BUSY        - Zarya is running but currently occupied
  STARTING    - Zarya is initializing
  UNAVAILABLE - Zarya cannot accept work right now
  STOPPING    - Zarya is shutting down
"""

import logging

from agent.lifecycle import LifecycleStatus

log = logging.getLogger("zarya.ecosystem.status")

# Map S18 lifecycle states to ecosystem availability.
# Authoritative values from agent.lifecycle.LifecycleStatus:
#   CREATED, AUTHORIZED, RUNNING, CHECKPOINTED, PAUSED,
#   CANCELLING, CANCELLED, INTERRUPTED, FAILED, COMPLETED, UNKNOWN
_LIFECYCLE_TO_ECOSYSTEM = {
    LifecycleStatus.CREATED: "STARTING",
    LifecycleStatus.AUTHORIZED: "STARTING",
    LifecycleStatus.RUNNING: "BUSY",
    LifecycleStatus.CHECKPOINTED: "BUSY",
    LifecycleStatus.PAUSED: "READY",
    LifecycleStatus.CANCELLING: "STOPPING",
    LifecycleStatus.CANCELLED: "READY",
    LifecycleStatus.INTERRUPTED: "READY",
    LifecycleStatus.FAILED: "READY",
    LifecycleStatus.COMPLETED: "READY",
    LifecycleStatus.UNKNOWN: "UNAVAILABLE",
}


def project_lifecycle_status(lifecycle_status) -> str:
    """Map a LifecycleStatus enum value to an ecosystem status string.

    Args:
        lifecycle_status: A LifecycleStatus enum member or its string value.

    Returns:
        An ecosystem status string.
    """
    if isinstance(lifecycle_status, str):
        try:
            lifecycle_status = LifecycleStatus(lifecycle_status)
        except ValueError:
            return "UNKNOWN"
    return _LIFECYCLE_TO_ECOSYSTEM.get(lifecycle_status, "UNKNOWN")


def get_global_status(active_operation_count: int = 0) -> dict:
    """Return global Zarya availability.

    Args:
        active_operation_count: Number of currently active S18 operations.
            If > 0, Zarya is BUSY. Otherwise READY.

    Returns:
        A status descriptor dict.
    """
    if active_operation_count > 0:
        status = "BUSY"
    else:
        status = "READY"

    return {
        "status": status,
        "active_operations": active_operation_count,
    }
