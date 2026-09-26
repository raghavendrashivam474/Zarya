"""
N6 Contract Smoke Tests
Verifies that Zarya N5 frozen continuity contracts interface seamlessly
with Shyam S16/S17 provider structures without schema drift.
"""

import pytest
import uuid
from typing import Any, Dict

from agent.continuity.coordination import (
    ContinuityCoordinator,
    ContinuityTransferRequest,
    DefaultTransportAdapter,
    TransportResult,
)
from agent.continuity.handoff import HandoffRequest, HandoffSession, RecoveryPolicy
from agent.continuity.identity import ContinuityOperation
from agent.continuity.state import ContinuityState
from agent.continuity.reconciliation import ContinuityReconciler, ContinuityReconciliationReport
from agent.continuity.result import ContinuationResult, ContinuationStatus, ContinuationStage
from agent.continuity import continue_portable_work


@pytest.fixture
def golden_portable_work() -> Dict[str, Any]:
    return {
        "format_version": "n3-portable-v1",
        "work_id": f"work-{uuid.uuid4().hex[:8]}",
        "intent": "N6 cross-device contract smoke verification",
        "plan_reference": {
            "plan_id": "plan-n6-smoke-1",
            "steps": [
                {
                    "step_id": "step-1",
                    "action": "file_write",
                    "parameters": {
                        "path": "output.txt",
                        "data": "Verified N6 Handshake",
                    },
                }
            ],
        },
        "source_node": {
            "device_id": "node-alpha",
            "operation_id": "op-alpha-001",
        },
        "target_requirements": {
            "capabilities": ["file_system"],
            "artifacts": [],
        },
        "runtime_state": {
            "status": "PAUSED",
            "progress_pct": 50,
            "variables": {},
        },
    }


class TestN6ContractSmoke:
    """Smoke tests validating boundary contracts between Zarya N5 and Shyam."""

    def test_zarya_transfer_request_carries_complete_shyam_routing(self, golden_portable_work):
        """Verify Zarya ContinuityTransferRequest contains all fields needed by Shyam & Flux."""
        handoff_req = HandoffRequest(
            work_id=golden_portable_work["work_id"],
            source_device_id="node-a",
            source_operation_id="op-100",
            target_device_id="node-b",
        )
        session = HandoffSession.create(handoff_req)
        coordinator = ContinuityCoordinator()

        transfer_req = coordinator.prepare_transfer_request(
            session=session,
            target_device_id="node-b",
            portable_work_payload=golden_portable_work,
            artifact_requirements=[],
        )

        assert transfer_req.work_id == golden_portable_work["work_id"]
        assert transfer_req.source_device_id == "node-a"
        assert transfer_req.target_device_id == "node-b"
        assert transfer_req.continuity_id.startswith("cont-")
        assert transfer_req.portable_work_payload == golden_portable_work

    def test_shyam_continuation_payload_ingestion(self, golden_portable_work):
        """Verify payload received from Shyam target continuation executes through continue_portable_work."""
        # Execute target continuation pipeline (N4 entry point)
        res = continue_portable_work(
            portable_work=golden_portable_work,
            local_policy_override=True,
        )

        assert res.stage != ContinuationStage.VALIDATE or res.status != ContinuationStatus.VERIFIED_FAILURE
        assert res.work_id == golden_portable_work["work_id"]

    def test_transport_success_is_not_work_success(self, golden_portable_work):
        """Inviolable Rule: Transport success alone does NOT equal work success."""
        handoff_req = HandoffRequest(
            work_id=golden_portable_work["work_id"],
            source_device_id="node-a",
            source_operation_id="op-100",
            target_device_id="node-b",
        )
        session = HandoffSession.create(handoff_req)
        coordinator = ContinuityCoordinator()
        transfer_req = coordinator.prepare_transfer_request(
            session=session,
            target_device_id="node-b",
            portable_work_payload=golden_portable_work,
        )

        # Transport succeeds
        t_res = TransportResult(
            continuity_id=session.operation.continuity_id,
            success=True,
            transport_reference="flux-tx-1234",
        )
        session.transition_to(ContinuityState.TRANSFERRING)
        session.transition_to(ContinuityState.TARGET_ACCEPTED)

        # Target execution fails
        target_n4_result = ContinuationResult(
            work_id=golden_portable_work["work_id"],
            operation_id="op-target-999",
            stage=ContinuationStage.EXECUTE,
            status=ContinuationStatus.VERIFIED_FAILURE,
            reason="Execution failed on target",
        )

        reconciler = ContinuityReconciler()
        report = reconciler.reconcile(
            session=session,
            transport_result=t_res,
            target_result=target_n4_result,
        )

        assert report.final_state == ContinuityState.TARGET_FAILED
        assert not report.is_success

    def test_unknown_remains_unknown(self, golden_portable_work):
        """UNKNOWN state is terminal and never converted to SUCCESS."""
        handoff_req = HandoffRequest(
            work_id=golden_portable_work["work_id"],
            source_device_id="node-a",
            source_operation_id="op-100",
            target_device_id="node-b",
        )
        session = HandoffSession.create(handoff_req)
        session.transition_to(ContinuityState.HANDOFF_PREPARING)
        session.transition_to(ContinuityState.TRANSFERRING)

        t_res = TransportResult(
            continuity_id=session.operation.continuity_id,
            success=True,
            transport_reference="flux-tx-5678",
        )
        target_n4_result = ContinuationResult(
            work_id=golden_portable_work["work_id"],
            operation_id="op-target-unknown",
            stage=ContinuationStage.EXECUTE,
            status=ContinuationStatus.UNKNOWN,
        )

        reconciler = ContinuityReconciler()
        report = reconciler.reconcile(
            session=session,
            transport_result=t_res,
            target_result=target_n4_result,
        )

        assert report.final_state == ContinuityState.UNKNOWN
        assert not report.is_success
