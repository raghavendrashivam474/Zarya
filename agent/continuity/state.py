"""N5 — Continuity State Machine (Projection Layer).

GOLDEN RULE:
    S18 owns execution state   (LifecycleStatus)
    N4 owns continuation state (ContinuationStatus)
    Shyam owns orchestration state
    Flux owns transport state
    N5 owns CONTINUITY state   (ContinuityState)  ← this file

ContinuityState is a PROJECTION across subsystem boundaries.
It does NOT drive execution. It OBSERVES and CORRELATES.

State derivation:
    ContinuityState is computed from the combination of:
        - N4 ContinuationStatus (target side)
        - S18 LifecycleStatus (source and target execution)
        - Flux transport outcome
    It is NOT an independent state machine that issues commands.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ContinuityState(str, Enum):
    """Cross-device handoff lifecycle states.

    These are PROJECTIONS — they reflect what N5 observes from
    N4 + S18 + Flux, not commands N5 issues to those systems.

    Terminal states: TARGET_COMPLETED, TARGET_FAILED, TARGET_REJECTED,
                     TRANSFER_FAILED, CANCELLED, UNKNOWN
    """

    # ── Source-side initiation ──
    HANDOFF_REQUESTED = "handoff_requested"
    #   Source user/Shyam signaled "continue this elsewhere."
    #   S18 source is still RUNNING or PAUSED.

    HANDOFF_PREPARING = "handoff_preparing"
    #   Source Zarya is packaging PortableWork via N3.
    #   S18 source may transition to PAUSED.

    # ── Transport ──
    TRANSFERRING = "transferring"
    #   Flux is moving PortableWork + artifacts to target.
    #   Source S18 is PAUSED. Target has not yet received work.

    TRANSFER_FAILED = "transfer_failed"
    #   Flux reported transport failure.
    #   Target never received the work. Source is recoverable.
    #   TERMINAL for this continuity operation.

    # ── Target-side acceptance ──
    TARGET_ACCEPTED = "target_accepted"
    #   Target Zarya received PortableWork.
    #   N4 validation passed. S18 target operation CREATED/AUTHORIZED.

    TARGET_REJECTED = "target_rejected"
    #   N4 rejected the work (UNAUTHORIZED, UNSUPPORTED, etc.).
    #   TERMINAL for this continuity operation.

    # ── Target-side execution ──
    TARGET_RUNNING = "target_running"
    #   Target S18 is RUNNING.
    #   N4 ContinuationStatus is IN_PROGRESS.

    TARGET_COMPLETED = "target_completed"
    #   Target S18 reached COMPLETED.
    #   N4 ContinuationStatus is VERIFIED_SUCCESS.
    #   TERMINAL — success.

    TARGET_FAILED = "target_failed"
    #   Target S18 reached FAILED.
    #   N4 ContinuationStatus is VERIFIED_FAILURE.
    #   TERMINAL — failure. Source recovery policy applies.

    # ── Catch-all ──
    CANCELLED = "cancelled"
    #   Handoff was cancelled by user/Shyam before completion.
    #   TERMINAL.

    UNKNOWN = "unknown"
    #   State cannot be determined from available signals.
    #   TERMINAL. NEVER treat as success. NEVER treat as resumable.
    #   This preserves the N4/S18 contract: UNKNOWN means UNKNOWN.


def is_terminal(state: ContinuityState) -> bool:
    """Return True if the continuity state is a final/terminal state.

    Terminal states indicate the handoff operation has concluded
    (successfully, unsuccessfully, or indeterminately).
    """
    return state in {
        ContinuityState.TARGET_COMPLETED,
        ContinuityState.TARGET_FAILED,
        ContinuityState.TARGET_REJECTED,
        ContinuityState.TRANSFER_FAILED,
        ContinuityState.CANCELLED,
        ContinuityState.UNKNOWN,
    }


def is_recoverable(state: ContinuityState) -> bool:
    """Return True if the source work can potentially be resumed locally.

    A handoff that failed during transport or was rejected by the target
    means the source work was never completed elsewhere and may be
    resumed on the source device.

    TARGET_FAILED is context-dependent — the source recovery policy
    (agreed with S16) determines whether to resume or escalate.
    We conservatively mark it as recoverable here.
    """
    return state in {
        ContinuityState.TRANSFER_FAILED,
        ContinuityState.TARGET_REJECTED,
        ContinuityState.TARGET_FAILED,
        ContinuityState.CANCELLED,
    }


def is_success(state: ContinuityState) -> bool:
    """Return True ONLY for verified target completion.

    CRITICAL: Transport success is NOT work success.
    Only TARGET_COMPLETED (backed by N4 VERIFIED_SUCCESS) counts.
    """
    return state == ContinuityState.TARGET_COMPLETED


def derive_from_n4_status(n4_status: str) -> ContinuityState:
    """Map an N4 ContinuationStatus string to a ContinuityState.

    This is a one-way projection. N5 reads N4's outcome and reflects
    it in continuity terms. N5 does NOT write back to N4.

    Args:
        n4_status: The string value of N4's ContinuationStatus enum.
                   e.g., "verified_success", "unauthorized", "unknown"

    Returns:
        The corresponding ContinuityState projection.
    """
    mapping = {
        "pending": ContinuityState.TARGET_ACCEPTED,
        "in_progress": ContinuityState.TARGET_RUNNING,
        "verified_success": ContinuityState.TARGET_COMPLETED,
        "verified_failure": ContinuityState.TARGET_FAILED,
        "blocked": ContinuityState.TARGET_RUNNING,  # still alive, just stuck
        "unauthorized": ContinuityState.TARGET_REJECTED,
        "unsupported": ContinuityState.TARGET_REJECTED,
        "reconstruction_failed": ContinuityState.TARGET_FAILED,
        "unknown": ContinuityState.UNKNOWN,  # PRESERVE — never guess
    }
    return mapping.get(n4_status.lower(), ContinuityState.UNKNOWN)


def derive_from_s18_status(s18_status: str) -> Optional[ContinuityState]:
    """Map an S18 LifecycleStatus string to a ContinuityState hint.

    This provides a WEAKER signal than N4 because S18 status alone
    doesn't tell us whether the work was a continuation or original.
    Use derive_from_n4_status() when N4 data is available.

    Returns None if the S18 status doesn't map to a specific
    continuity state (e.g., CREATED, CHECKPOINTED are ambiguous
    without N4 context).
    """
    mapping = {
        "RUNNING": ContinuityState.TARGET_RUNNING,
        "COMPLETED": ContinuityState.TARGET_COMPLETED,
        "FAILED": ContinuityState.TARGET_FAILED,
        "CANCELLED": ContinuityState.CANCELLED,
        "PAUSED": None,  # ambiguous — could be source or target
        "INTERRUPTED": ContinuityState.TARGET_FAILED,
    }
    return mapping.get(s18_status.upper())
