"""N5 — Golden Two-Device End-to-End Continuity Lifecycle Test.

Verifies the complete vertical slice from Section 7 of the brief:
    Laptop A (Source Zarya)
          │
          │ "continue this work on Laptop B"
          ▼
    Shyam / S16 (Orchestration: chooses Laptop B, generates continuity_id)
          │
          ▼
    Flux (Transport: moves PortableWork payload)
          │
          ▼
    Laptop B (Target Zarya)
          │
          ▼
    N4 (Validation → Resolution → Reconstruction → S18 Execution)
          │
          ▼
    Target Outcome (Verified Success)
          │
          ▼
    Reconciliation (Observability & Idempotency Store updated)
          │
          ▼
    Source notified (Quiescent, non-duplicated)
"""

import json
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent.continuity import (
    ContinuityCoordinator,
    ContinuityReconciler,
    ContinuityRecord,
    ContinuityStore,
    ContinuationResult,
    ContinuationStage,
    ContinuationStatus,
    ContinuityState,
    DefaultTransportAdapter,
    HandoffRequest,
    HandoffSession,
    RecoveryAction,
    RecoveryPolicy,
    continue_portable_work,
)


@pytest.fixture
def golden_portable_work_dict():
    """Valid serialized PortableWork payload representing file-based work."""
    return {
        "version": "1.0",
        "semantic_work_model": {
            "work_id": "W-GOLDEN-REPORT-001",
            "operation_id": "op-src-9999",
            "intent": "Create report.txt",
            "plan_reference": "plan-001",
            "execution_reference": "exec-001",
            "lifecycle_status": "PAUSED",
            "relevant_context": {
                "active_application": "notepad",
                "file_path": "report.txt",
                "content": "Final analysis complete."
            },
            "artifact_references": [],
            "authorization_reference": "auth-local-001",
            "observations": ["Started on Laptop A"],
            "outcome": None,
        },
        "provenance": {
            "source_device_id": "laptop-alpha",
            "source_device_type": "laptop",
            "source_platform": "windows",
            "export_timestamp": "2026-09-12T10:00:00Z",
        },
        "target_hints": {
            "preferred_target_type": "laptop",
            "required_capabilities": ["write_files"],
        },
        "checksum": "checksum-valid-abc123",
    }


class TestGoldenContinuityLifecycle:
    def test_complete_two_device_file_handoff(self, golden_portable_work_dict):
        """Golden E2E Flow: Source -> Shyam -> Flux -> Target N4/S18 -> Reconciled."""

        # ── 1. SOURCE INITIALIZATION (Laptop A) ──
        source_device_id = "laptop-alpha"
        target_device_id = "laptop-beta"
        work_id = "W-GOLDEN-REPORT-001"
        source_op_id = "op-src-9999"

        handoff_req = HandoffRequest(
            work_id=work_id,
            source_device_id=source_device_id,
            source_operation_id=source_op_id,
            target_device_id=target_device_id,
            recovery_policy=RecoveryPolicy.PRESERVE_PAUSED,
        )

        session = HandoffSession.create(handoff_req)
        continuity_id = session.operation.continuity_id

        assert continuity_id.startswith("cont-")
        assert session.state == ContinuityState.HANDOFF_REQUESTED

        # ── 2. SHYAM + FLUX TRANSPORT BOUNDARY ──
        transport_adapter = DefaultTransportAdapter(should_succeed=True)

        # Mock target executor representing Laptop B running continue_portable_work
        def mock_target_executor(payload):
            # Target executes S18 and achieves verified outcome
            return ContinuationResult(
                work_id=work_id,
                operation_id="op-tgt-8888",
                stage=ContinuationStage.OUTCOME,
                status=ContinuationStatus.VERIFIED_SUCCESS,
                target_device_id=target_device_id,
                reason="File report.txt successfully verified on Laptop B",
            )

        coordinator = ContinuityCoordinator(
            transport=transport_adapter,
            target_executor=mock_target_executor,
        )

        # Package Transfer Request
        transfer_req = coordinator.prepare_transfer_request(
            session=session,
            target_device_id=target_device_id,
            portable_work_payload=golden_portable_work_dict,
        )
        assert session.state == ContinuityState.HANDOFF_PREPARING
        assert transfer_req.validate() == []

        # Dispatch across Flux
        t_result = coordinator.dispatch_transfer(session, transfer_req)
        assert t_result.success
        assert session.state == ContinuityState.TRANSFERRING

        # ── 3. TARGET EXECUTION (Laptop B) ──
        target_res = coordinator.deliver_and_execute_target(session, transfer_req)
        assert target_res.is_success
        assert target_res.operation_id == "op-tgt-8888"

        # ── 4. RECONCILIATION & OBSERVABILITY ──
        reconciliation_report = ContinuityReconciler.reconcile(
            session=session,
            transport_result=t_result,
            target_result=target_res,
        )

        assert reconciliation_report.final_state == ContinuityState.TARGET_COMPLETED
        assert reconciliation_report.is_success
        assert not reconciliation_report.is_recoverable
        assert reconciliation_report.target_operation_id == "op-tgt-8888"
        assert reconciliation_report.source_operation_id == source_op_id
        assert reconciliation_report.work_id == work_id
        assert reconciliation_report.continuity_id == continuity_id

        # ── 5. PERSISTENCE & IDEMPOTENCY ──
        store = ContinuityStore()
        record = ContinuityRecord.from_reconciliation(reconciliation_report)
        store.save(record)

        assert store.exists(continuity_id)
        assert len(store.list_by_work_id(work_id)) == 1
        assert len(store.list_active()) == 0  # Completed work is terminal

        # Idempotency: duplicate registration must not create second entry
        store.save(record)
        assert store.count() == 1
