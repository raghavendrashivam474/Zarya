"""N5 — Outcome Reconciliation Engine.

This module reconciles the multi-party continuity outcome:
    - Flux TransportResult
    - Target N4 ContinuationResult
    - Source HandoffSession state

Rules:
    1. Transport success != work success.
    2. UNKNOWN from N4 is STRICTLY mapped to ContinuityState.UNKNOWN.
    3. Source is updated to terminal TARGET_COMPLETED only on verified success.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agent.continuity.coordination import TransportResult
from agent.continuity.handoff import HandoffSession, RecoveryAction
from agent.continuity.result import ContinuationResult, ContinuationStatus
from agent.continuity.state import (
    ContinuityState,
    derive_from_n4_status,
    is_recoverable,
    is_success,
    is_terminal,
)


@dataclass(frozen=True)
class ContinuityReconciliationReport:
    """Comprehensive, immutable audit of a completed continuity lifecycle."""
    continuity_id: str
    work_id: str
    source_device_id: str
    target_device_id: Optional[str]
    final_state: ContinuityState
    is_success: bool
    is_recoverable: bool
    recovery_action: RecoveryAction
    source_operation_id: str
    target_operation_id: Optional[str] = None
    target_status: Optional[str] = None
    transport_reference: Optional[str] = None
    reconciled_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    details: Dict[str, Any] = field(default_factory=dict)


class ContinuityReconciler:
    """Reconciles transport and continuation outcomes against a HandoffSession."""

    @staticmethod
    def reconcile(
        session: HandoffSession,
        transport_result: Optional[TransportResult] = None,
        target_result: Optional[ContinuationResult] = None,
    ) -> ContinuityReconciliationReport:
        """Reconcile session state with transport and target execution results."""

        # Case 1: Transport failure
        if transport_result and not transport_result.success:
            session.transition_to(
                ContinuityState.TRANSFER_FAILED,
                reason=transport_result.error_message or "Transport failure",
            )
            recovery_act = session.evaluate_recovery()
            return ContinuityReconciliationReport(
                continuity_id=session.operation.continuity_id,
                work_id=session.operation.work_id,
                source_device_id=session.operation.source_device_id,
                target_device_id=session.operation.target_device_id,
                final_state=ContinuityState.TRANSFER_FAILED,
                is_success=False,
                is_recoverable=is_recoverable(ContinuityState.TRANSFER_FAILED),
                recovery_action=recovery_act,
                source_operation_id=session.operation.source_operation_id,
                transport_reference=transport_result.transport_reference,
                details={"error": transport_result.error_message},
            )

        # Case 2: Target Continuation Result available
        if target_result:
            target_status_val = (
                target_result.status.value
                if hasattr(target_result.status, "value")
                else str(target_result.status)
            )
            projected_state = derive_from_n4_status(target_status_val)
            session.transition_to(
                projected_state,
                reason=f"N4 target outcome: {target_status_val} - {target_result.reason}",
            )

            # Link target operation ID if available
            target_op_id = target_result.operation_id
            if target_op_id and session.operation.target_operation_id != target_op_id:
                session.operation = session.operation.with_target(
                    target_device_id=session.operation.target_device_id or target_result.target_device_id or "unknown-target",
                    target_operation_id=target_op_id,
                )

            recovery_act = session.evaluate_recovery()
            success_flag = is_success(projected_state)

            return ContinuityReconciliationReport(
                continuity_id=session.operation.continuity_id,
                work_id=session.operation.work_id,
                source_device_id=session.operation.source_device_id,
                target_device_id=session.operation.target_device_id,
                final_state=projected_state,
                is_success=success_flag,
                is_recoverable=is_recoverable(projected_state),
                recovery_action=recovery_act,
                source_operation_id=session.operation.source_operation_id,
                target_operation_id=target_op_id,
                target_status=target_status_val,
                transport_reference=transport_result.transport_reference if transport_result else None,
                details={"reason": target_result.reason, "stage": target_result.stage.value if hasattr(target_result.stage, "value") else str(target_result.stage)},
            )

        # Case 3: In-flight or unresolved
        recovery_act = session.evaluate_recovery()
        return ContinuityReconciliationReport(
            continuity_id=session.operation.continuity_id,
            work_id=session.operation.work_id,
            source_device_id=session.operation.source_device_id,
            target_device_id=session.operation.target_device_id,
            final_state=session.state,
            is_success=is_success(session.state),
            is_recoverable=is_recoverable(session.state),
            recovery_action=recovery_act,
            source_operation_id=session.operation.source_operation_id,
        )
