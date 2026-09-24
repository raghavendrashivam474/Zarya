"""N5 — Source-Side Handoff Lifecycle & Recovery Engine.

This module owns the source-side handoff protocol and recovery mechanics.

Key Principles:
    1. Source work is NEVER marked completed just because transfer succeeded.
    2. S18 owns the underlying execution state; N5 tracks the handoff lifecycle.
    3. Failure in transport or target execution triggers deterministic recovery policies.
    4. UNKNOWN target outcomes are strictly preserved — never masked as success.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.continuity.identity import ContinuityOperation, generate_continuity_id
from agent.continuity.state import (
    ContinuityState,
    is_recoverable,
    is_terminal,
    is_success,
)


class RecoveryPolicy(str, enum.Enum):
    """Policy for handling source-side state when target continuation fails."""
    AUTO_RESUME = "auto_resume"          # Source can automatically resume local execution
    PRESERVE_PAUSED = "preserve_paused"  # Keep source paused for human / Shyam intervention
    MARK_FAILED = "mark_failed"          # Fail the source operation deterministically
    MANUAL = "manual"                    # Require explicit operator command


class RecoveryAction(str, enum.Enum):
    """The concrete action instructed by the recovery engine for source execution."""
    RESUME_LOCAL = "resume_local"
    HOLD_PAUSED = "hold_paused"
    TERMINATE_FAILED = "terminate_failed"
    AWAIT_INSPECTION = "await_inspection"


@dataclass(frozen=True)
class HandoffRequest:
    """Request initiated by source or Shyam to hand off work to another device."""
    work_id: str
    source_device_id: str
    source_operation_id: str
    target_device_id: Optional[str] = None
    continuity_id: Optional[str] = None
    portable_work_payload: Optional[Dict[str, Any]] = None
    recovery_policy: RecoveryPolicy = RecoveryPolicy.PRESERVE_PAUSED
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.work_id:
            errors.append("work_id is required")
        if not self.source_device_id:
            errors.append("source_device_id is required")
        if not self.source_operation_id:
            errors.append("source_operation_id is required")
        return errors


@dataclass
class HandoffSession:
    """Stateful coordinator for an active source-side handoff operation."""
    operation: ContinuityOperation
    state: ContinuityState = ContinuityState.HANDOFF_REQUESTED
    recovery_policy: RecoveryPolicy = RecoveryPolicy.PRESERVE_PAUSED
    history: List[Dict[str, Any]] = field(default_factory=list)
    failure_reason: Optional[str] = None

    @classmethod
    def create(cls, request: HandoffRequest) -> HandoffSession:
        """Create a new HandoffSession from a validated HandoffRequest."""
        val_errors = request.validate()
        if val_errors:
            raise ValueError(f"Invalid HandoffRequest: {', '.join(val_errors)}")

        cid = request.continuity_id or generate_continuity_id()
        op = ContinuityOperation(
            continuity_id=cid,
            work_id=request.work_id,
            source_device_id=request.source_device_id,
            source_operation_id=request.source_operation_id,
            target_device_id=request.target_device_id,
        )
        session = cls(
            operation=op,
            state=ContinuityState.HANDOFF_REQUESTED,
            recovery_policy=request.recovery_policy,
        )
        session._record_transition(
            from_state=None,
            to_state=ContinuityState.HANDOFF_REQUESTED,
            reason="Handoff session initialized",
        )
        return session

    def _record_transition(
        self,
        from_state: Optional[ContinuityState],
        to_state: ContinuityState,
        reason: str = "",
    ) -> None:
        self.history.append({
            "from_state": from_state.value if from_state else None,
            "to_state": to_state.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        })

    def transition_to(self, new_state: ContinuityState, reason: str = "") -> bool:
        """Perform a validated state transition.

        Returns:
            True if transition succeeded, False if rejected or already in terminal state.
        """
        if self.state == new_state:
            # Idempotent no-op
            return True

        if is_terminal(self.state):
            # Terminal states cannot be transitioned away from
            return False

        # Valid forward transitions across the handoff lifecycle
        valid_transitions = {
            ContinuityState.HANDOFF_REQUESTED: {
                ContinuityState.HANDOFF_PREPARING,
                ContinuityState.TRANSFERRING,
                ContinuityState.TARGET_ACCEPTED,
                ContinuityState.TARGET_REJECTED,
                ContinuityState.TRANSFER_FAILED,
                ContinuityState.CANCELLED,
                ContinuityState.UNKNOWN,
            },
            ContinuityState.HANDOFF_PREPARING: {
                ContinuityState.TRANSFERRING,
                ContinuityState.TARGET_ACCEPTED,
                ContinuityState.TARGET_REJECTED,
                ContinuityState.TRANSFER_FAILED,
                ContinuityState.CANCELLED,
                ContinuityState.UNKNOWN,
            },
            ContinuityState.TRANSFERRING: {
                ContinuityState.TARGET_ACCEPTED,
                ContinuityState.TARGET_RUNNING,
                ContinuityState.TARGET_COMPLETED,
                ContinuityState.TARGET_FAILED,
                ContinuityState.TARGET_REJECTED,
                ContinuityState.TRANSFER_FAILED,
                ContinuityState.CANCELLED,
                ContinuityState.UNKNOWN,
            },
            ContinuityState.TARGET_ACCEPTED: {
                ContinuityState.TARGET_RUNNING,
                ContinuityState.TARGET_COMPLETED,
                ContinuityState.TARGET_FAILED,
                ContinuityState.TARGET_REJECTED,
                ContinuityState.CANCELLED,
                ContinuityState.UNKNOWN,
            },
            ContinuityState.TARGET_RUNNING: {
                ContinuityState.TARGET_COMPLETED,
                ContinuityState.TARGET_FAILED,
                ContinuityState.CANCELLED,
                ContinuityState.UNKNOWN,
            },
        }

        allowed = valid_transitions.get(self.state, set())
        if new_state not in allowed:
            return False

        prev = self.state
        self.state = new_state
        self._record_transition(prev, new_state, reason)
        return True

    def evaluate_recovery(self) -> RecoveryAction:
        """Evaluate source recovery action based on current state and policy.

        Strict invariants:
            - If TARGET_COMPLETED: No recovery needed (work completed).
            - If UNKNOWN: Strictly returns AWAIT_INSPECTION (never auto-resume).
            - If TRANSFER_FAILED or TARGET_REJECTED: Work never executed on target;
              safe to AUTO_RESUME if policy permits.
            - If TARGET_FAILED: Depends on configured RecoveryPolicy.
        """
        if self.state == ContinuityState.TARGET_COMPLETED:
            return RecoveryAction.HOLD_PAUSED

        if self.state == ContinuityState.UNKNOWN:
            # GOLDEN RULE: UNKNOWN is never guessed or blindly resumed
            return RecoveryAction.AWAIT_INSPECTION

        if self.state in {ContinuityState.TRANSFER_FAILED, ContinuityState.TARGET_REJECTED}:
            if self.recovery_policy == RecoveryPolicy.AUTO_RESUME:
                return RecoveryAction.RESUME_LOCAL
            elif self.recovery_policy == RecoveryPolicy.MARK_FAILED:
                return RecoveryAction.TERMINATE_FAILED
            else:
                return RecoveryAction.HOLD_PAUSED

        if self.state == ContinuityState.TARGET_FAILED:
            if self.recovery_policy == RecoveryPolicy.AUTO_RESUME:
                return RecoveryAction.RESUME_LOCAL
            elif self.recovery_policy == RecoveryPolicy.MARK_FAILED:
                return RecoveryAction.TERMINATE_FAILED
            else:
                return RecoveryAction.HOLD_PAUSED

        return RecoveryAction.HOLD_PAUSED
