"""N5 — Unit tests for identity and state modules.

Tests the core N5 contracts:
    1. continuity_id generation and format
    2. ContinuityOperation immutability and correlation
    3. ContinuityState terminal/recoverable/success classification
    4. N4 → ContinuityState derivation (especially UNKNOWN preservation)
    5. S18 → ContinuityState derivation
    6. Idempotency: same inputs → same derivations
"""

import sys
import os

# Ensure agent/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from agent.continuity.identity import (
    generate_continuity_id,
    ContinuityOperation,
)
from agent.continuity.state import (
    ContinuityState,
    is_terminal,
    is_recoverable,
    is_success,
    derive_from_n4_status,
    derive_from_s18_status,
)


# ── Identity Tests ──

class TestContinuityIdGeneration:
    def test_format_prefix(self):
        cid = generate_continuity_id()
        assert cid.startswith("cont-"), f"Expected 'cont-' prefix, got {cid}"

    def test_uniqueness(self):
        ids = {generate_continuity_id() for _ in range(100)}
        assert len(ids) == 100, "continuity_ids must be unique"

    def test_not_empty(self):
        cid = generate_continuity_id()
        assert len(cid) > 5


class TestContinuityOperation:
    def test_creation(self):
        op = ContinuityOperation(
            continuity_id="cont-test-001",
            work_id="W123",
            source_device_id="laptop-a",
            source_operation_id="op-src-001",
        )
        assert op.continuity_id == "cont-test-001"
        assert op.work_id == "W123"
        assert op.target_device_id is None
        assert not op.is_target_assigned

    def test_immutability(self):
        op = ContinuityOperation(
            continuity_id="cont-test-002",
            work_id="W456",
            source_device_id="laptop-a",
            source_operation_id="op-src-002",
        )
        with pytest.raises(AttributeError):
            op.work_id = "W999"  # type: ignore

    def test_with_target_creates_new_instance(self):
        op = ContinuityOperation(
            continuity_id="cont-test-003",
            work_id="W789",
            source_device_id="laptop-a",
            source_operation_id="op-src-003",
        )
        op2 = op.with_target("tablet-b", "op-tgt-003")
        assert op.target_device_id is None  # original unchanged
        assert op2.target_device_id == "tablet-b"
        assert op2.target_operation_id == "op-tgt-003"
        assert op2.is_target_assigned
        assert op2.is_target_executing
        assert op2.continuity_id == op.continuity_id  # same handoff

    def test_with_transport(self):
        op = ContinuityOperation(
            continuity_id="cont-test-004",
            work_id="W100",
            source_device_id="laptop-a",
            source_operation_id="op-src-004",
        )
        op2 = op.with_transport("flux-xfer-abc")
        assert op2.transport_reference == "flux-xfer-abc"
        assert op.transport_reference is None  # original unchanged

    def test_validate_good(self):
        op = ContinuityOperation(
            continuity_id="cont-test-005",
            work_id="W200",
            source_device_id="laptop-a",
            source_operation_id="op-src-005",
        )
        assert op.validate() == []

    def test_validate_bad_prefix(self):
        op = ContinuityOperation(
            continuity_id="bad-prefix-005",
            work_id="W200",
            source_device_id="laptop-a",
            source_operation_id="op-src-005",
        )
        errors = op.validate()
        assert any("cont-" in e for e in errors)

    def test_validate_empty_work_id(self):
        op = ContinuityOperation(
            continuity_id="cont-test-006",
            work_id="",
            source_device_id="laptop-a",
            source_operation_id="op-src-006",
        )
        errors = op.validate()
        assert any("work_id" in e for e in errors)

    def test_three_identities_distinct(self):
        """Verify work_id, operation_id, continuity_id are NOT collapsed."""
        op = ContinuityOperation(
            continuity_id="cont-abc",
            work_id="W-same-logical-work",
            source_device_id="laptop",
            source_operation_id="op-source-exec",
        )
        op2 = op.with_target("tablet", "op-target-exec")
        # Same work
        assert op2.work_id == op.work_id
        # Different operations
        assert op2.source_operation_id != op2.target_operation_id
        # Same continuity
        assert op2.continuity_id == op.continuity_id


# ── State Tests ──

class TestContinuityState:
    def test_all_states_are_strings(self):
        for state in ContinuityState:
            assert isinstance(state.value, str)

    @pytest.mark.parametrize("state", [
        ContinuityState.TARGET_COMPLETED,
        ContinuityState.TARGET_FAILED,
        ContinuityState.TARGET_REJECTED,
        ContinuityState.TRANSFER_FAILED,
        ContinuityState.CANCELLED,
        ContinuityState.UNKNOWN,
    ])
    def test_terminal_states(self, state):
        assert is_terminal(state), f"{state} should be terminal"

    @pytest.mark.parametrize("state", [
        ContinuityState.HANDOFF_REQUESTED,
        ContinuityState.HANDOFF_PREPARING,
        ContinuityState.TRANSFERRING,
        ContinuityState.TARGET_ACCEPTED,
        ContinuityState.TARGET_RUNNING,
    ])
    def test_non_terminal_states(self, state):
        assert not is_terminal(state), f"{state} should NOT be terminal"

    def test_success_only_target_completed(self):
        assert is_success(ContinuityState.TARGET_COMPLETED)
        for state in ContinuityState:
            if state != ContinuityState.TARGET_COMPLETED:
                assert not is_success(state), (
                    f"{state} must NOT be treated as success"
                )

    def test_unknown_is_never_success(self):
        """CRITICAL: UNKNOWN must never be treated as success."""
        assert not is_success(ContinuityState.UNKNOWN)
        assert is_terminal(ContinuityState.UNKNOWN)


class TestN4Derivation:
    def test_verified_success(self):
        assert derive_from_n4_status("verified_success") == ContinuityState.TARGET_COMPLETED

    def test_verified_failure(self):
        assert derive_from_n4_status("verified_failure") == ContinuityState.TARGET_FAILED

    def test_unauthorized(self):
        assert derive_from_n4_status("unauthorized") == ContinuityState.TARGET_REJECTED

    def test_unsupported(self):
        assert derive_from_n4_status("unsupported") == ContinuityState.TARGET_REJECTED

    def test_unknown_preserved(self):
        """CRITICAL: N4 UNKNOWN must map to N5 UNKNOWN, never to success."""
        result = derive_from_n4_status("unknown")
        assert result == ContinuityState.UNKNOWN
        assert not is_success(result)

    def test_in_progress(self):
        assert derive_from_n4_status("in_progress") == ContinuityState.TARGET_RUNNING

    def test_unknown_input_defaults_to_unknown(self):
        """Any unrecognized N4 status must safely default to UNKNOWN."""
        assert derive_from_n4_status("totally_bogus") == ContinuityState.UNKNOWN
        assert derive_from_n4_status("") == ContinuityState.UNKNOWN


class TestS18Derivation:
    def test_running(self):
        assert derive_from_s18_status("RUNNING") == ContinuityState.TARGET_RUNNING

    def test_completed(self):
        assert derive_from_s18_status("COMPLETED") == ContinuityState.TARGET_COMPLETED

    def test_failed(self):
        assert derive_from_s18_status("FAILED") == ContinuityState.TARGET_FAILED

    def test_paused_is_ambiguous(self):
        """PAUSED alone doesn't tell us source vs target — returns None."""
        assert derive_from_s18_status("PAUSED") is None

    def test_case_insensitive(self):
        assert derive_from_s18_status("running") == ContinuityState.TARGET_RUNNING
        assert derive_from_s18_status("completed") == ContinuityState.TARGET_COMPLETED


class TestRecoverability:
    def test_transfer_failed_is_recoverable(self):
        assert is_recoverable(ContinuityState.TRANSFER_FAILED)

    def test_target_rejected_is_recoverable(self):
        assert is_recoverable(ContinuityState.TARGET_REJECTED)

    def test_target_completed_is_not_recoverable(self):
        """Completed work doesn't need recovery."""
        assert not is_recoverable(ContinuityState.TARGET_COMPLETED)

    def test_unknown_is_not_recoverable(self):
        """UNKNOWN is terminal and NOT safe to resume blindly."""
        assert not is_recoverable(ContinuityState.UNKNOWN)
