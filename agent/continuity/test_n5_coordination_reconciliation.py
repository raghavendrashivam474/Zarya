"""N5 — Integration and Unit Tests for Coordination & Reconciliation Modules."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from agent.continuity.coordination import (
    ContinuityCoordinator,
    ContinuityTransferRequest,
    DefaultTransportAdapter,
    TransportResult,
)
from agent.continuity.handoff import HandoffRequest, HandoffSession, RecoveryPolicy, RecoveryAction
from agent.continuity.reconciliation import ContinuityReconciler
from agent.continuity.result import ContinuationResult, ContinuationStatus, ContinuationStage
from agent.continuity.state import ContinuityState


@pytest.fixture
def base_session():
    req = HandoffRequest(
        work_id="W-GOLDEN-01",
        source_device_id="laptop-alpha",
        source_operation_id="op-src-01",
        target_device_id="tablet-beta",
        recovery_policy=RecoveryPolicy.AUTO_RESUME,
    )
    return HandoffSession.create(req)


class TestContinuityCoordinator:
    def test_prepare_transfer_request(self, base_session):
        coordinator = ContinuityCoordinator()
        payload = {"intent": "Create report.txt", "work_id": "W-GOLDEN-01"}
        req = coordinator.prepare_transfer_request(
            session=base_session,
            target_device_id="tablet-beta",
            portable_work_payload=payload,
            artifact_requirements=["art-1"],
        )
        assert req.continuity_id == base_session.operation.continuity_id
        assert req.target_device_id == "tablet-beta"
        assert req.validate() == []
        assert base_session.state == ContinuityState.HANDOFF_PREPARING

    def test_dispatch_transfer_success(self, base_session):
        adapter = DefaultTransportAdapter(should_succeed=True)
        coordinator = ContinuityCoordinator(transport=adapter)
        req = coordinator.prepare_transfer_request(
            session=base_session,
            target_device_id="tablet-beta",
            portable_work_payload={"work": "test"},
        )
        t_res = coordinator.dispatch_transfer(base_session, req)
        assert t_res.success
        assert base_session.state == ContinuityState.TRANSFERRING

    def test_dispatch_transfer_failure(self, base_session):
        adapter = DefaultTransportAdapter(should_succeed=False, error_msg="Link unreachable")
        coordinator = ContinuityCoordinator(transport=adapter)
        req = coordinator.prepare_transfer_request(
            session=base_session,
            target_device_id="tablet-beta",
            portable_work_payload={"work": "test"},
        )
        t_res = coordinator.dispatch_transfer(base_session, req)
        assert not t_res.success
        assert base_session.state == ContinuityState.TRANSFER_FAILED


class TestContinuityReconciler:
    def test_reconcile_verified_success(self, base_session):
        base_session.transition_to(ContinuityState.HANDOFF_PREPARING)
        base_session.transition_to(ContinuityState.TRANSFERRING)
        base_session.transition_to(ContinuityState.TARGET_ACCEPTED)
        base_session.transition_to(ContinuityState.TARGET_RUNNING)

        t_res = TransportResult(
            continuity_id=base_session.operation.continuity_id,
            success=True,
            transport_reference="flux-123",
        )
        n4_res = ContinuationResult(
            work_id="W-GOLDEN-01",
            operation_id="op-tgt-88",
            stage=ContinuationStage.OUTCOME,
            status=ContinuationStatus.VERIFIED_SUCCESS,
            target_device_id="tablet-beta",
            reason="All steps completed and verified",
        )

        report = ContinuityReconciler.reconcile(
            session=base_session,
            transport_result=t_res,
            target_result=n4_res,
        )

        assert report.final_state == ContinuityState.TARGET_COMPLETED
        assert report.is_success
        assert not report.is_recoverable
        assert report.target_operation_id == "op-tgt-88"
        assert base_session.operation.target_operation_id == "op-tgt-88"

    def test_reconcile_target_unauthorized(self, base_session):
        base_session.transition_to(ContinuityState.HANDOFF_PREPARING)
        base_session.transition_to(ContinuityState.TRANSFERRING)

        t_res = TransportResult(
            continuity_id=base_session.operation.continuity_id,
            success=True,
            transport_reference="flux-123",
        )
        n4_res = ContinuationResult(
            work_id="W-GOLDEN-01",
            operation_id="op-tgt-unauth",
            stage=ContinuationStage.AUTHORIZE,
            status=ContinuationStatus.UNAUTHORIZED,
            reason="Missing write_files permission on target",
        )

        report = ContinuityReconciler.reconcile(
            session=base_session,
            transport_result=t_res,
            target_result=n4_res,
        )

        assert report.final_state == ContinuityState.TARGET_REJECTED
        assert not report.is_success
        assert report.is_recoverable
        assert report.recovery_action == RecoveryAction.RESUME_LOCAL

    def test_reconcile_target_unknown_strict_preservation(self, base_session):
        """CRITICAL: UNKNOWN from N4 must never be marked as success or auto-resumed."""
        base_session.transition_to(ContinuityState.HANDOFF_PREPARING)
        base_session.transition_to(ContinuityState.TRANSFERRING)

        t_res = TransportResult(
            continuity_id=base_session.operation.continuity_id,
            success=True,
            transport_reference="flux-123",
        )
        n4_res = ContinuationResult(
            work_id="W-GOLDEN-01",
            operation_id="op-tgt-unknown",
            stage=ContinuationStage.VERIFY,
            status=ContinuationStatus.UNKNOWN,
            reason="Process disappeared without exit code",
        )

        report = ContinuityReconciler.reconcile(
            session=base_session,
            transport_result=t_res,
            target_result=n4_res,
        )

        assert report.final_state == ContinuityState.UNKNOWN
        assert not report.is_success
        assert not report.is_recoverable
        assert report.recovery_action == RecoveryAction.AWAIT_INSPECTION
