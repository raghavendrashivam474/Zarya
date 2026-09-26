"""
N6 Golden Two-Device Continuity Lifecycle Test.

Validates the complete vertical integration loop:
    Source Node A (Zarya N5)
          │
          │ HandoffRequest
          ▼
    Shyam Continuity Orchestration
          │
          │ Target Resolution (flux_peer_id, zarya_url)
          ▼
    Aryntra Flux Transport (ContinuityTransferRequest)
          │
          ▼
    Target Node B (Zarya N4/S18)
          │
          │ N4 Reconstruction -> Physical Slice S18 Verification
          ▼
    VERIFIED_SUCCESS Outcome
          │
          ▼
    Reconciliation & Store (W -> C -> O Spine)
"""

import os
import tempfile
import uuid
from pathlib import Path
import pytest
from typing import Any, Dict

from agent.continuity.coordination import (
    ContinuityCoordinator,
    ContinuityTransferRequest,
    FluxTransportProvider,
    TransportResult,
)
from agent.continuity.handoff import HandoffRequest, HandoffSession, RecoveryPolicy, RecoveryAction
from agent.continuity.identity import ContinuityOperation
from agent.continuity.state import ContinuityState
from agent.continuity.reconciliation import ContinuityReconciler, ContinuityReconciliationReport
from agent.continuity.result import ContinuationResult, ContinuationStatus, ContinuationStage
from agent.continuity.persistence import ContinuityRecord, ContinuityStore
from agent.continuity.validation import PORTABLE_WORK_FORMAT_VERSION
from agent.continuity import continue_portable_work
import agent.continuity.execution as n4_exec


class SimulatedFluxBridge:
    """Simulates the Aryntra Flux transport layer moving payload from Node A to Node B."""

    def __init__(self, target_node_callback):
        self.target_node_callback = target_node_callback
        self.transfers = []
        self.latest_target_result = None

    def transfer(self, request: ContinuityTransferRequest) -> TransportResult:
        self.transfers.append(request)
        # Deliver payload to target Zarya instance
        self.latest_target_result = self.target_node_callback(request.portable_work_payload)
        
        return TransportResult(
            continuity_id=request.continuity_id,
            transport_reference=f"flux-peer-tx-{uuid.uuid4().hex[:8]}",
            success=True,
            error_message=None,
        )


class TestN6GoldenTwoDeviceContinuity:
    """Full vertical continuity handshake between Node Alpha and Node Beta."""

    def test_complete_vertical_two_device_lifecycle(self):
        """Validates the full W -> C -> O -> VERIFIED_SUCCESS spine."""

        original_s18_flag = n4_exec._S18_EXECUTION_AVAILABLE
        n4_exec._S18_EXECUTION_AVAILABLE = False

        with tempfile.TemporaryDirectory() as shared_tmp:
            source_store_file = os.path.join(shared_tmp, "source_store.json")
            target_store_file = os.path.join(shared_tmp, "target_store.json")
            target_output_file = Path(shared_tmp) / "summary_report.txt"

            source_store = ContinuityStore(storage_path=source_store_file)
            target_store = ContinuityStore(storage_path=target_store_file)

            work_id = f"work-golden-{uuid.uuid4().hex[:6]}"
            source_device = "device-macbook-alpha"
            target_device = "device-linux-beta"
            source_op_id = f"op-src-{uuid.uuid4().hex[:6]}"

            # 1. Source Node A: Construct Canonical Portable Work Payload
            portable_work = {
                "format_version": PORTABLE_WORK_FORMAT_VERSION,
                "work_id": work_id,
                "operation_id": source_op_id,
                "intent": "Compile quarterly analytics summary on target node",
                "plan_reference": {
                    "steps": [
                        {
                            "action": "write_file",
                            "parameters": {
                                "path": str(target_output_file.resolve()),
                                "content": "metric,value\nthroughput,98.6\nlatency,12ms\nstatus,VERIFIED",
                            },
                        }
                    ]
                },
                "execution_reference": f"exec-{uuid.uuid4().hex[:6]}",
                "lifecycle_status": "PAUSED",
                "relevant_context": {},
                "artifact_references": [],
                "authorization_reference": "auth-cross-device-token-verified",
                "observations": ["Source initialized payload on Node Alpha"],
                "outcome": None,
            }

            try:
                # 2. Source Node A: Initiate Handoff
                handoff_req = HandoffRequest(
                    work_id=work_id,
                    source_device_id=source_device,
                    source_operation_id=source_op_id,
                    target_device_id=target_device,
                    recovery_policy=RecoveryPolicy.AUTO_RESUME,
                )
                session = HandoffSession.create(handoff_req)
                assert session.state == ContinuityState.HANDOFF_REQUESTED
                continuity_id = session.operation.continuity_id

                # Save initial state in source store
                source_store.save(ContinuityRecord.from_session(session))

                # 3. Target Node B Execution Callback
                def target_zarya_receiver(delivered_payload: Dict[str, Any]) -> ContinuationResult:
                    """Simulates Node Beta receiving and executing the portable work."""
                    res = continue_portable_work(
                        portable_work=delivered_payload,
                        local_policy_override=True,
                    )

                    target_rec = ContinuityRecord(
                        continuity_id=continuity_id,
                        work_id=work_id,
                        source_device_id=source_device,
                        source_operation_id=source_op_id,
                        target_device_id=target_device,
                        target_operation_id=res.operation_id,
                        state=ContinuityState.TARGET_COMPLETED.value if res.is_success else ContinuityState.TARGET_FAILED.value,
                        details={"continuation_status": str(res.status.value)},
                    )
                    target_store.save(target_rec)
                    return res

                # 4. Shyam / Flux: Coordinate Transport
                flux_bridge = SimulatedFluxBridge(target_node_callback=target_zarya_receiver)
                coordinator = ContinuityCoordinator(transport=flux_bridge)

                transfer_req = coordinator.prepare_transfer_request(
                    session=session,
                    target_device_id=target_device,
                    portable_work_payload=portable_work,
                )
                assert session.state == ContinuityState.HANDOFF_PREPARING

                # Dispatch across Flux
                t_res = coordinator.dispatch_transfer(session, transfer_req)
                assert t_res.success is True
                assert session.state == ContinuityState.TRANSFERRING

                # 5. Extract Target Execution Result
                target_result: ContinuationResult = flux_bridge.latest_target_result
                assert target_result.status == ContinuationStatus.VERIFIED_SUCCESS
                assert target_result.stage == ContinuationStage.OUTCOME
                target_operation_id = target_result.operation_id

                # Verify file was physically written by target slice
                assert target_output_file.is_file()
                assert "status,VERIFIED" in target_output_file.read_text(encoding="utf-8")

                # Update session to Target Accepted -> Target Running
                session.transition_to(ContinuityState.TARGET_ACCEPTED)
                session.transition_to(ContinuityState.TARGET_RUNNING)

                # 6. Reconcile Final Outcome
                reconciler = ContinuityReconciler()
                report: ContinuityReconciliationReport = reconciler.reconcile(
                    session=session,
                    transport_result=t_res,
                    target_result=target_result,
                )

                # 7. Assert Full Correlation Spine & Final State
                assert report.final_state == ContinuityState.TARGET_COMPLETED
                assert report.is_success is True
                assert report.continuity_id == continuity_id
                assert report.work_id == work_id
                assert report.source_device_id == source_device
                assert report.target_device_id == target_device
                assert report.source_operation_id == source_op_id
                assert report.target_operation_id == target_operation_id

                # 8. Verify Source and Target Stores Are Quiescent & Idempotent
                source_store.save(ContinuityRecord.from_session(session))
                reloaded_source = source_store.get(continuity_id)
                assert reloaded_source.state == ContinuityState.TARGET_COMPLETED.value
                assert reloaded_source.is_terminal is True

                reloaded_target = target_store.get(continuity_id)
                assert reloaded_target.target_operation_id == target_operation_id
                assert reloaded_target.state == ContinuityState.TARGET_COMPLETED.value

            finally:
                n4_exec._S18_EXECUTION_AVAILABLE = original_s18_flag
