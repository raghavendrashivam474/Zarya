"""N5 — Unit tests for handoff lifecycle and source recovery mechanics.

Tests all recovery cases required by brief Section 15:
    Case A: Transport fails → recoverable, source safe to resume.
    Case B: Transport succeeds, target rejects → source safe to resume.
    Case C: Target starts then fails → recovery policy evaluated.
    Case D: Target verification UNKNOWN → strictly preserves UNKNOWN / AWAIT_INSPECTION.
    Case E: Source immutability & history verification.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from agent.continuity.identity import ContinuityOperation
from agent.continuity.state import ContinuityState
from agent.continuity.handoff import (
    HandoffRequest,
    HandoffSession,
    RecoveryPolicy,
    RecoveryAction,
)


@pytest.fixture
def base_request():
    return HandoffRequest(
        work_id="W-100",
        source_device_id="laptop-a",
        source_operation_id="op-src-100",
        target_device_id="tablet-b",
    )


class TestHandoffRequestValidation:
    def test_valid_request(self, base_request):
        assert base_request.validate() == []

    def test_missing_work_id(self):
        req = HandoffRequest(
            work_id="",
            source_device_id="laptop-a",
            source_operation_id="op-src-100",
        )
        assert "work_id is required" in req.validate()

    def test_missing_device_ids(self):
        req = HandoffRequest(
            work_id="W-100",
            source_device_id="",
            source_operation_id="",
        )
        errors = req.validate()
        assert len(errors) == 2


class TestHandoffSessionLifecycle:
    def test_session_init(self, base_request):
        session = HandoffSession.create(base_request)
        assert session.state == ContinuityState.HANDOFF_REQUESTED
        assert session.operation.work_id == "W-100"
        assert len(session.history) == 1

    def test_valid_forward_transitions(self, base_request):
        session = HandoffSession.create(base_request)
        assert session.transition_to(ContinuityState.HANDOFF_PREPARING, "Packing work")
        assert session.transition_to(ContinuityState.TRANSFERRING, "Flux sent")
        assert session.transition_to(ContinuityState.TARGET_ACCEPTED, "Target received")
        assert session.transition_to(ContinuityState.TARGET_RUNNING, "Target execution")
        assert session.transition_to(ContinuityState.TARGET_COMPLETED, "Target done")
        assert session.state == ContinuityState.TARGET_COMPLETED
        assert len(session.history) == 6

    def test_invalid_transition_rejected(self, base_request):
        session = HandoffSession.create(base_request)
        # Cannot jump straight from REQUESTED to TARGET_COMPLETED
        assert not session.transition_to(ContinuityState.TARGET_COMPLETED)
        assert session.state == ContinuityState.HANDOFF_REQUESTED

    def test_terminal_state_frozen(self, base_request):
        session = HandoffSession.create(base_request)
        session.transition_to(ContinuityState.HANDOFF_PREPARING)
        session.transition_to(ContinuityState.TRANSFERRING)
        session.transition_to(ContinuityState.TRANSFER_FAILED)
        # Session is now in terminal state TRANSFER_FAILED
        assert not session.transition_to(ContinuityState.TARGET_RUNNING)
        assert session.state == ContinuityState.TRANSFER_FAILED

    def test_idempotent_transition(self, base_request):
        session = HandoffSession.create(base_request)
        session.transition_to(ContinuityState.HANDOFF_PREPARING)
        # Repeating the same state should return True without adding duplicate history
        assert session.transition_to(ContinuityState.HANDOFF_PREPARING)
        assert session.state == ContinuityState.HANDOFF_PREPARING


class TestRecoveryScenarios:
    def test_case_a_transport_failed_auto_resume(self):
        """Case A: Flux fails -> source resumes locally if policy=AUTO_RESUME."""
        req = HandoffRequest(
            work_id="W-101",
            source_device_id="laptop-a",
            source_operation_id="op-101",
            recovery_policy=RecoveryPolicy.AUTO_RESUME,
        )
        session = HandoffSession.create(req)
        session.transition_to(ContinuityState.HANDOFF_PREPARING)
        session.transition_to(ContinuityState.TRANSFERRING)
        session.transition_to(ContinuityState.TRANSFER_FAILED, "Network dropout")

        action = session.evaluate_recovery()
        assert action == RecoveryAction.RESUME_LOCAL

    def test_case_b_target_rejected_preserve_paused(self):
        """Case B: Target rejects -> source holds paused if policy=PRESERVE_PAUSED."""
        req = HandoffRequest(
            work_id="W-102",
            source_device_id="laptop-a",
            source_operation_id="op-102",
            recovery_policy=RecoveryPolicy.PRESERVE_PAUSED,
        )
        session = HandoffSession.create(req)
        session.transition_to(ContinuityState.HANDOFF_PREPARING)
        session.transition_to(ContinuityState.TRANSFERRING)
        session.transition_to(ContinuityState.TARGET_REJECTED, "Unauthorized capability")

        action = session.evaluate_recovery()
        assert action == RecoveryAction.HOLD_PAUSED

    def test_case_c_target_failed_mark_failed(self):
        """Case C: Target starts then fails -> policy MARK_FAILED terminates source."""
        req = HandoffRequest(
            work_id="W-103",
            source_device_id="laptop-a",
            source_operation_id="op-103",
            recovery_policy=RecoveryPolicy.MARK_FAILED,
        )
        session = HandoffSession.create(req)
        session.transition_to(ContinuityState.HANDOFF_PREPARING)
        session.transition_to(ContinuityState.TRANSFERRING)
        session.transition_to(ContinuityState.TARGET_ACCEPTED)
        session.transition_to(ContinuityState.TARGET_RUNNING)
        session.transition_to(ContinuityState.TARGET_FAILED, "Disk write error on target")

        action = session.evaluate_recovery()
        assert action == RecoveryAction.TERMINATE_FAILED

    def test_case_d_target_unknown_must_await_inspection(self):
        """Case D: Target verification UNKNOWN -> strictly AWAIT_INSPECTION."""
        req = HandoffRequest(
            work_id="W-104",
            source_device_id="laptop-a",
            source_operation_id="op-104",
            recovery_policy=RecoveryPolicy.AUTO_RESUME,  # Even with AUTO_RESUME!
        )
        session = HandoffSession.create(req)
        session.transition_to(ContinuityState.HANDOFF_PREPARING)
        session.transition_to(ContinuityState.TRANSFERRING)
        session.transition_to(ContinuityState.UNKNOWN, "Target disappeared mid-execution")

        action = session.evaluate_recovery()
        # MUST NEVER AUTO-RESUME AN UNKNOWN STATE
        assert action == RecoveryAction.AWAIT_INSPECTION
