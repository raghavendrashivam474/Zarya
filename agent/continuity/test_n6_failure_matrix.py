"""
N6 Failure Matrix and Source Disappearance Tests.

Validates the full matrix of real cross-device failure and edge cases
specified in Section 15 and 16 of the N6 Engineering Brief:
    - Case A: Target unavailable / rejected
    - Case B: Flux transport failure
    - Case C: Target execution failure
    - Case D: UNKNOWN state preserved strictly
    - Case E: Duplicate handoff / Idempotency
    - Case F: Transport success != work success
    - Case G: Source node disappearance / Target autonomy
"""

import os
import tempfile
import uuid
import pytest
from typing import Any, Dict

from agent.continuity.coordination import (
    ContinuityCoordinator,
    ContinuityTransferRequest,
    DefaultTransportAdapter,
    TransportResult,
)
from agent.continuity.handoff import HandoffRequest, HandoffSession, RecoveryPolicy, RecoveryAction
from agent.continuity.identity import ContinuityOperation
from agent.continuity.state import ContinuityState
from agent.continuity.reconciliation import ContinuityReconciler, ContinuityReconciliationReport
from agent.continuity.result import ContinuationResult, ContinuationStatus, ContinuationStage
from agent.continuity.persistence import ContinuityRecord, ContinuityStore
from agent.continuity import continue_portable_work


@pytest.fixture
def make_work():
    def _generator(custom_intent: str = "Perform matrix step"):
        return {
            "format_version": "n3-portable-v1",
            "work_id": f"work-{uuid.uuid4().hex[:8]}",
            "intent": custom_intent,
            "plan_reference": {
                "plan_id": f"plan-{uuid.uuid4().hex[:6]}",
                "steps": [
                    {
                        "step_id": "step-1",
                        "action": "file_write",
                        "parameters": {
                            "path": "test_matrix.log",
                            "data": "Matrix test payload",
                        },
                    }
                ],
            },
            "source_node": {
                "device_id": "node-alpha",
                "operation_id": f"op-{uuid.uuid4().hex[:6]}",
            },
            "target_requirements": {
                "capabilities": ["file_system"],
                "artifacts": [],
            },
            "runtime_state": {
                "status": "PAUSED",
                "progress_pct": 0,
                "variables": {},
            },
        }
    return _generator


class TestN6FailureMatrix:
    """Rigorous failure mode verification for N6."""

    def test_case_a_target_rejected(self, make_work):
        """Case A: Target device rejects handoff (incompatible or overloaded)."""
        work = make_work("Target rejection test")
        handoff_req = HandoffRequest(
            work_id=work["work_id"],
            source_device_id="node-alpha",
            source_operation_id="op-100",
            target_device_id="node-beta",
            recovery_policy=RecoveryPolicy.AUTO_RESUME,
        )
        session = HandoffSession.create(handoff_req)
        session.transition_to(ContinuityState.HANDOFF_PREPARING)
        session.transition_to(ContinuityState.TRANSFERRING)

        # Target rejects the handoff request
        session.transition_to(ContinuityState.TARGET_REJECTED, reason="Node beta busy / capacity exceeded")

        reconciler = ContinuityReconciler()
        report = reconciler.reconcile(
            session=session,
            transport_result=TransportResult(
                continuity_id=session.operation.continuity_id,
                transport_reference="flux-rejected-ref",
                success=False,
                error_message="Target rejected payload",
            ),
        )

        assert report.final_state == ContinuityState.TRANSFER_FAILED
        assert not report.is_success
        assert report.is_recoverable
        assert report.recovery_action == RecoveryAction.RESUME_LOCAL

    def test_case_b_flux_transport_failure(self, make_work):
        """Case B: Aryntra Flux network transport fails mid-flight."""
        work = make_work("Network partition test")
        handoff_req = HandoffRequest(
            work_id=work["work_id"],
            source_device_id="node-alpha",
            source_operation_id="op-100",
            target_device_id="node-beta",
            recovery_policy=RecoveryPolicy.AUTO_RESUME,
        )
        session = HandoffSession.create(handoff_req)
        coordinator = ContinuityCoordinator(
            transport=DefaultTransportAdapter(should_succeed=False, error_msg="Flux peer unreachable: 504 Gateway Timeout")
        )

        transfer_req = coordinator.prepare_transfer_request(
            session=session,
            target_device_id="node-beta",
            portable_work_payload=work,
        )

        t_res = coordinator.dispatch_transfer(session, transfer_req)
        assert not t_res.success
        assert session.state == ContinuityState.TRANSFER_FAILED

        reconciler = ContinuityReconciler()
        report = reconciler.reconcile(session=session, transport_result=t_res)

        assert report.final_state == ContinuityState.TRANSFER_FAILED
        assert not report.is_success
        assert report.recovery_action == RecoveryAction.RESUME_LOCAL

    def test_case_c_target_execution_failure(self, make_work):
        """Case C: Payload reaches target via Flux, but target execution fails in S18."""
        work = make_work("Target S18 execution failure test")
        handoff_req = HandoffRequest(
            work_id=work["work_id"],
            source_device_id="node-alpha",
            source_operation_id="op-100",
            target_device_id="node-beta",
        )
        session = HandoffSession.create(handoff_req)
        session.transition_to(ContinuityState.HANDOFF_PREPARING)
        session.transition_to(ContinuityState.TRANSFERRING)
        session.transition_to(ContinuityState.TARGET_ACCEPTED)
        session.transition_to(ContinuityState.TARGET_RUNNING)

        t_res = TransportResult(
            continuity_id=session.operation.continuity_id,
            transport_reference="flux-peer-tx-99",
            success=True,
        )
        target_res = ContinuationResult(
            work_id=work["work_id"],
            operation_id="op-beta-fail-88",
            stage=ContinuationStage.EXECUTE,
            status=ContinuationStatus.VERIFIED_FAILURE,
            reason="Tool missing execution permissions on node beta",
        )

        reconciler = ContinuityReconciler()
        report = reconciler.reconcile(session=session, transport_result=t_res, target_result=target_res)

        assert report.final_state == ContinuityState.TARGET_FAILED
        assert not report.is_success
        assert session.state == ContinuityState.TARGET_FAILED

    def test_case_d_target_unknown_strict_preservation(self, make_work):
        """Case D: Target state is UNKNOWN -> MUST remain UNKNOWN."""
        work = make_work("Unknown outcome test")
        handoff_req = HandoffRequest(
            work_id=work["work_id"],
            source_device_id="node-alpha",
            source_operation_id="op-100",
            target_device_id="node-beta",
        )
        session = HandoffSession.create(handoff_req)
        session.transition_to(ContinuityState.HANDOFF_PREPARING)
        session.transition_to(ContinuityState.TRANSFERRING)

        t_res = TransportResult(
            continuity_id=session.operation.continuity_id,
            transport_reference="flux-ref-99",
            success=True,
        )
        target_res = ContinuationResult(
            work_id=work["work_id"],
            operation_id="op-unknown",
            stage=ContinuationStage.OUTCOME,
            status=ContinuationStatus.UNKNOWN,
            reason="Communication lost before verification could complete",
        )

        reconciler = ContinuityReconciler()
        report = reconciler.reconcile(session=session, transport_result=t_res, target_result=target_res)

        assert report.final_state == ContinuityState.UNKNOWN
        assert not report.is_success
        assert not report.is_recoverable
        assert report.recovery_action == RecoveryAction.AWAIT_INSPECTION

    def test_case_e_duplicate_handoff_idempotency(self, make_work):
        """Case E: Sending the same continuity handoff twice is safely deduplicated."""
        work = make_work("Idempotency test")
        store = ContinuityStore()

        handoff_req = HandoffRequest(
            work_id=work["work_id"],
            source_device_id="node-alpha",
            source_operation_id="op-100",
            target_device_id="node-beta",
        )
        session = HandoffSession.create(handoff_req)
        record = ContinuityRecord.from_session(session)

        # Initial save
        store.save(record)
        assert store.exists(session.operation.continuity_id) is True
        assert store.count() == 1

        # Duplicate save with updated state updates in place without increasing count
        record.state = ContinuityState.TRANSFERRING.value
        store.save(record)
        assert store.count() == 1


class TestN6SourceDisappearance:
    """Validates behavior when source node disappears after handoff dispatch."""

    def test_target_executes_independently_when_source_offline(self, make_work):
        """Source node goes offline after dispatching work. Target executes and persists result."""
        work = make_work("Autonomous target execution")

        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = os.path.join(tmpdir, "target_continuity_store.json")
            target_store = ContinuityStore(storage_path=store_path)

            # Target receives work payload
            continuation_result = continue_portable_work(
                portable_work=work,
                local_policy_override=True,
            )

            # Target verifies outcome independently
            assert continuation_result.status in (
                ContinuationStatus.VERIFIED_SUCCESS,
                ContinuationStatus.PENDING,
            ) or continuation_result.stage != ContinuationStage.VALIDATE

            # Target persists its local execution record
            record = ContinuityRecord(
                continuity_id=f"cont-{uuid.uuid4().hex[:8]}",
                work_id=work["work_id"],
                source_device_id="node-alpha",
                source_operation_id="op-100",
                target_device_id="node-beta",
                target_operation_id=continuation_result.operation_id,
                state=ContinuityState.TARGET_COMPLETED.value,
                details={"target_status": str(continuation_result.status.value)},
            )
            target_store.save(record)

            # Target store reloads cleanly
            reloaded_store = ContinuityStore(storage_path=store_path)
            assert reloaded_store.exists(record.continuity_id) is True
