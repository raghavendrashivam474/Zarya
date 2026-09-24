"""N5 — Unit tests for continuity metadata persistence and idempotency store.

Tests:
    1. ContinuityRecord derivation from HandoffSession and ContinuityReconciliationReport.
    2. In-memory & JSON file persistence.
    3. Idempotency checks: detecting existing continuity_ids.
    4. Querying by work_id and filtering active vs terminal operations.
    5. Ensuring NO execution checkpoint duplication occurs.
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent.continuity.handoff import HandoffRequest, HandoffSession, RecoveryAction, RecoveryPolicy
from agent.continuity.identity import ContinuityOperation
from agent.continuity.persistence import ContinuityRecord, ContinuityStore
from agent.continuity.reconciliation import ContinuityReconciliationReport
from agent.continuity.state import ContinuityState


@pytest.fixture
def sample_session():
    req = HandoffRequest(
        work_id="W-PERSIST-01",
        source_device_id="laptop-1",
        source_operation_id="op-src-1",
        target_device_id="tablet-2",
    )
    session = HandoffSession.create(req)
    session.transition_to(ContinuityState.HANDOFF_PREPARING)
    return session


class TestContinuityRecord:
    def test_from_session(self, sample_session):
        rec = ContinuityRecord.from_session(sample_session)
        assert rec.continuity_id == sample_session.operation.continuity_id
        assert rec.work_id == "W-PERSIST-01"
        assert rec.state == ContinuityState.HANDOFF_PREPARING.value
        assert not rec.is_terminal

    def test_from_reconciliation_terminal(self):
        report = ContinuityReconciliationReport(
            continuity_id="cont-done-999",
            work_id="W-PERSIST-02",
            source_device_id="laptop-1",
            target_device_id="tablet-2",
            final_state=ContinuityState.TARGET_COMPLETED,
            is_success=True,
            is_recoverable=False,
            recovery_action=RecoveryAction.HOLD_PAUSED,
            source_operation_id="op-src-2",
            target_operation_id="op-tgt-2",
            target_status="verified_success",
        )
        rec = ContinuityRecord.from_reconciliation(report)
        assert rec.continuity_id == "cont-done-999"
        assert rec.is_terminal
        assert rec.details["is_success"] is True

    def test_dict_serialization_roundtrip(self, sample_session):
        rec = ContinuityRecord.from_session(sample_session)
        d = rec.to_dict()
        rec2 = ContinuityRecord.from_dict(d)
        assert rec2.continuity_id == rec.continuity_id
        assert rec2.work_id == rec.work_id
        assert rec2.state == rec.state


class TestContinuityStore:
    def test_in_memory_save_and_get(self, sample_session):
        store = ContinuityStore()
        rec = ContinuityRecord.from_session(sample_session)
        store.save(rec)

        assert store.exists(rec.continuity_id)
        fetched = store.get(rec.continuity_id)
        assert fetched is not None
        assert fetched.work_id == "W-PERSIST-01"
        assert store.count() == 1

    def test_idempotency_detection(self, sample_session):
        store = ContinuityStore()
        rec = ContinuityRecord.from_session(sample_session)
        store.save(rec)

        # Duplicate check
        assert store.exists(rec.continuity_id)
        # Re-saving same ID updates record without duplicating count
        rec.state = ContinuityState.TRANSFERRING.value
        store.save(rec)
        assert store.count() == 1
        assert store.get(rec.continuity_id).state == ContinuityState.TRANSFERRING.value

    def test_list_by_work_id(self):
        store = ContinuityStore()
        rec1 = ContinuityRecord(
            continuity_id="cont-01",
            work_id="W-COMMON",
            source_device_id="dev-1",
            source_operation_id="op-1",
        )
        rec2 = ContinuityRecord(
            continuity_id="cont-02",
            work_id="W-COMMON",
            source_device_id="dev-2",
            source_operation_id="op-2",
        )
        rec3 = ContinuityRecord(
            continuity_id="cont-03",
            work_id="W-OTHER",
            source_device_id="dev-1",
            source_operation_id="op-3",
        )
        store.save(rec1)
        store.save(rec2)
        store.save(rec3)

        common_records = store.list_by_work_id("W-COMMON")
        assert len(common_records) == 2
        assert {r.continuity_id for r in common_records} == {"cont-01", "cont-02"}

    def test_list_active_filters_terminal(self):
        store = ContinuityStore()
        rec_active = ContinuityRecord(
            continuity_id="cont-active",
            work_id="W-1",
            source_device_id="dev-1",
            source_operation_id="op-1",
            is_terminal=False,
        )
        rec_terminal = ContinuityRecord(
            continuity_id="cont-terminal",
            work_id="W-2",
            source_device_id="dev-1",
            source_operation_id="op-2",
            is_terminal=True,
        )
        store.save(rec_active)
        store.save(rec_terminal)

        active = store.list_active()
        assert len(active) == 1
        assert active[0].continuity_id == "cont-active"

    def test_file_persistence(self, sample_session):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "continuity_store.json")
            store1 = ContinuityStore(storage_path=file_path)
            rec = ContinuityRecord.from_session(sample_session)
            store1.save(rec)

            # Create a second store pointing to the same file
            store2 = ContinuityStore(storage_path=file_path)
            assert store2.exists(rec.continuity_id)
            fetched = store2.get(rec.continuity_id)
            assert fetched.work_id == rec.work_id
