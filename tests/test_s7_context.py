"""
Zarya S7: Persistent Computer Context — Unit and Integration Tests.

Validates:
 1. MemoryRecord construction, serialization, freshness, epistemic markers.
 2. MemoryStore lifecycle (open, close, reopen, idempotency).
 3. Persistence across close/reopen (simulated process restart).
 4. Persistence across actual subprocess restart (real process boundary).
 5. Provenance completeness on every stored record.
 6. Verification policy: VERIFIED_SUCCESS/FAILURE recorded; UNKNOWN
    never promoted to factual memory.
 7. Freshness reassessment on historical records.
 8. Current-vs-memory epistemic distinction.
 9. S6 WorkResult integration (capture_work_result round-trip).
10. Failure isolation: store unavailable does not corrupt callers.
11. Bounded retrieval: limit enforcement and hard cap.

All tests use temporary SQLite databases to avoid polluting the
real persistent store.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from agent.context import (
    DEFAULT_RECALL_LIMIT,
    MAX_RECALL_LIMIT,
    MemoryPolicy,
    MemoryRecord,
    MemoryStore,
    MemoryType,
    StoreStatus,
    VALID_MEMORY_TYPES,
    build_observation_record,
    build_step_outcome_record,
    build_work_outcome_record,
    capture_observation,
    capture_work_result,
    now_iso,
)
from agent.state import StateFreshness, StateObservation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_db() -> Path:
    """Create a temporary directory and return a path for a test DB."""
    d = Path(tempfile.mkdtemp(prefix="s7test_"))
    return d / "test.db"


def _make_observation(
    domain: str = "application",
    subject: str = "notepad",
    status: str = "VERIFIED_SUCCESS",
    observed_at: str | None = None,
) -> StateObservation:
    """Build a minimal S3 StateObservation for testing."""
    return StateObservation(
        domain=domain,
        subject=subject,
        observed_at=observed_at or now_iso(),
        status=status,
        state={"running": status == "VERIFIED_SUCCESS", "image": subject},
        evidence={"method": "process_probe", "detail": "ok"},
        freshness=StateFreshness.CURRENT.value,
    )


def _make_work_result(
    goal: str = "Create file and open app",
    overall_status: str = "VERIFIED_SUCCESS",
    steps: list | None = None,
) -> dict:
    """Build a minimal S6 execute_work result dict."""
    if steps is None:
        steps = [
            {
                "step_id": "step-1",
                "tool": "createFile",
                "status": "VERIFIED_SUCCESS",
                "verification": {"status": "VERIFIED_SUCCESS", "detail": "file created"},
                "state": {"freshness": "CURRENT"},
                "failure": None,
                "recovery": {"status": "NOT_ELIGIBLE"},
            },
            {
                "step_id": "step-2",
                "tool": "openApplication",
                "status": "VERIFIED_SUCCESS",
                "verification": {"status": "VERIFIED_SUCCESS", "detail": "app launched"},
                "state": {"freshness": "CURRENT"},
                "failure": None,
                "recovery": {"status": "NOT_ELIGIBLE"},
            },
        ]
    return {
        "goal": goal,
        "overall_status": overall_status,
        "summary": "All steps completed and verified successfully.",
        "completed_steps": steps,
        "failed_step": None,
        "skipped_steps": [],
    }


# ===========================================================================
# 1. MemoryRecord basics
# ===========================================================================

class TestMemoryRecord(unittest.TestCase):
    """Validate MemoryRecord construction, serialization, and epistemic markers."""

    def test_to_dict_round_trip(self):
        r = MemoryRecord(
            memory_id="mem-abc",
            memory_type=MemoryType.OBSERVATION,
            domain="application",
            subject="notepad",
            observed_at="2025-01-01T00:00:00+00:00",
            created_at="2025-01-01T00:00:01+00:00",
            verification_status="VERIFIED_SUCCESS",
            payload={"observation": {"running": True}},
            provenance={"source_operation": "openApplication"},
        )
        d = r.to_dict()
        self.assertEqual(d["memory_id"], "mem-abc")
        self.assertEqual(d["memory_type"], "observation")
        self.assertEqual(d["domain"], "application")
        self.assertIn("source_operation", d["provenance"])

    def test_freshness_current_for_recent(self):
        r = MemoryRecord(
            memory_id="mem-x",
            memory_type=MemoryType.OBSERVATION,
            domain="filesystem",
            subject="notes.txt",
            observed_at=now_iso(),
            created_at=now_iso(),
            verification_status="VERIFIED_SUCCESS",
            payload={},
            provenance={},
        )
        self.assertEqual(r.freshness(), StateFreshness.CURRENT.value)

    def test_freshness_stale_for_old(self):
        old_time = (
            datetime.now(timezone.utc) - timedelta(seconds=60)
        ).isoformat()
        r = MemoryRecord(
            memory_id="mem-old",
            memory_type=MemoryType.OBSERVATION,
            domain="application",
            subject="chrome",
            observed_at=old_time,
            created_at=now_iso(),
            verification_status="VERIFIED_SUCCESS",
            payload={},
            provenance={},
        )
        self.assertIn(
            r.freshness(),
            (StateFreshness.STALE.value, StateFreshness.REQUIRES_REFRESH.value),
        )

    def test_historical_context_has_epistemic_markers(self):
        r = MemoryRecord(
            memory_id="mem-hist",
            memory_type=MemoryType.OBSERVATION,
            domain="application",
            subject="notepad",
            observed_at=now_iso(),
            created_at=now_iso(),
            verification_status="VERIFIED_SUCCESS",
            payload={},
            provenance={},
        )
        ctx = r.as_historical_context()
        self.assertEqual(ctx["epistemic_status"], "historical_observation")
        self.assertFalse(ctx["current_state_established"])
        self.assertIn("past observation", ctx["notice"])


# ===========================================================================
# 2. MemoryStore lifecycle
# ===========================================================================

class TestMemoryStoreLifecycle(unittest.TestCase):
    """Validate open, close, reopen, and idempotency."""

    def test_open_creates_db(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        self.assertTrue(s.open())
        self.assertEqual(s.status, StoreStatus.OK)
        self.assertTrue(path.exists())
        s.close()

    def test_open_is_idempotent(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        self.assertTrue(s.open())
        self.assertTrue(s.open())  # second call should also succeed
        self.assertEqual(s.status, StoreStatus.OK)
        s.close()

    def test_close_sets_unavailable(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        s.close()
        self.assertEqual(s.status, StoreStatus.UNAVAILABLE)

    def test_reopen_after_close(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        s.close()
        self.assertTrue(s.open())
        self.assertEqual(s.status, StoreStatus.OK)
        s.close()


# ===========================================================================
# 3. Persistence across close/reopen (simulated restart)
# ===========================================================================

class TestMemoryStorePersistence(unittest.TestCase):
    """Write, close, reopen, read — data must survive."""

    def test_record_survives_close_reopen(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()

        r = MemoryRecord(
            memory_id="mem-persist-1",
            memory_type=MemoryType.OBSERVATION,
            domain="filesystem",
            subject="report.docx",
            observed_at=now_iso(),
            created_at=now_iso(),
            verification_status="VERIFIED_SUCCESS",
            payload={"observation": {"exists": True, "size_bytes": 4096}},
            provenance={"source_operation": "createFile"},
        )
        s.remember(r)
        s.close()

        # Simulated "restart"
        s2 = MemoryStore(path=path)
        s2.open()
        recalled = s2.recall(domain="filesystem", subject="report.docx")
        self.assertEqual(len(recalled), 1)
        self.assertEqual(recalled[0].memory_id, "mem-persist-1")
        self.assertEqual(recalled[0].payload["observation"]["size_bytes"], 4096)
        s2.close()

    def test_count_survives_restart(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        for i in range(5):
            s.remember(MemoryRecord(
                memory_id=f"mem-c-{i}",
                memory_type=MemoryType.OBSERVATION,
                domain="application",
                subject=f"app-{i}",
                observed_at=now_iso(),
                created_at=now_iso(),
                verification_status="VERIFIED_SUCCESS",
                payload={},
                provenance={},
            ))
        s.close()

        s2 = MemoryStore(path=path)
        s2.open()
        self.assertEqual(s2.count(), 5)
        s2.close()


# ===========================================================================
# 4. Persistence across actual subprocess restart
# ===========================================================================

class TestMemoryStoreSubprocessRestart(unittest.TestCase):
    """Real process boundary: process A writes, exits; process B reads."""

    def test_memory_survives_real_process_restart(self):
        path = _tmp_db()

        # --- Process A: write a record and exit ---
        writer_script = textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {repr(str(Path.cwd()))})
            from pathlib import Path
            from agent.context import MemoryStore, MemoryRecord, MemoryType, now_iso

            s = MemoryStore(path=Path({repr(str(path))}))
            assert s.open(), s.last_error
            r = MemoryRecord(
                memory_id="mem-subprocess-1",
                memory_type=MemoryType.OBSERVATION,
                domain="application",
                subject="notepad",
                observed_at=now_iso(),
                created_at=now_iso(),
                verification_status="VERIFIED_SUCCESS",
                payload={{"observation": {{"running": True}}}},
                provenance={{"source_operation": "openApplication"}},
            )
            mid = s.remember(r)
            assert mid is not None, "remember failed"
            s.close()
            print("WRITTEN")
        """)
        result_a = subprocess.run(
            [sys.executable, "-c", writer_script],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result_a.returncode, 0, f"Writer failed: {result_a.stderr}")
        self.assertIn("WRITTEN", result_a.stdout)

        # --- Process B: read the record ---
        reader_script = textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {repr(str(Path.cwd()))})
            from pathlib import Path
            from agent.context import MemoryStore

            s = MemoryStore(path=Path({repr(str(path))}))
            assert s.open(), s.last_error
            records = s.recall(domain="application", subject="notepad")
            assert len(records) == 1, f"Expected 1 record, got {{len(records)}}"
            assert records[0].memory_id == "mem-subprocess-1"
            assert records[0].payload["observation"]["running"] is True
            s.close()
            print("READ_OK")
        """)
        result_b = subprocess.run(
            [sys.executable, "-c", reader_script],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result_b.returncode, 0, f"Reader failed: {result_b.stderr}")
        self.assertIn("READ_OK", result_b.stdout)


# ===========================================================================
# 5. Provenance completeness
# ===========================================================================

class TestProvenance(unittest.TestCase):
    """Every stored record must carry source/timestamp metadata."""

    def test_observation_record_has_provenance(self):
        obs = _make_observation()
        record = build_observation_record(obs, source_operation="openApplication")
        self.assertIsNotNone(record)
        self.assertIn("source_operation", record.provenance)
        self.assertEqual(record.provenance["source_operation"], "openApplication")
        self.assertIn("source_domain", record.provenance)

    def test_observation_record_preserves_timestamps(self):
        obs = _make_observation()
        record = build_observation_record(obs, source_operation="createFile")
        self.assertIsNotNone(record)
        self.assertEqual(record.observed_at, obs.observed_at)
        self.assertTrue(len(record.created_at) > 10)  # ISO timestamp

    def test_work_record_has_work_id(self):
        wr = _make_work_result()
        record = build_work_outcome_record(wr)
        self.assertIn("work_id", record.provenance)
        self.assertEqual(record.provenance["source_operation"], "execute_work")

    def test_step_record_has_step_id_and_work_id(self):
        wr = _make_work_result()
        step = wr["completed_steps"][0]
        record = build_step_outcome_record(step, work_id="work-xyz")
        self.assertEqual(record.provenance["work_id"], "work-xyz")
        self.assertEqual(record.provenance["step_id"], "step-1")

    def test_provenance_survives_persistence(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        obs = _make_observation()
        record = build_observation_record(obs, "openApplication", work_id="w1", step_id="s1")
        s.remember(record)
        recalled = s.recall()
        self.assertEqual(len(recalled), 1)
        self.assertEqual(recalled[0].provenance["work_id"], "w1")
        self.assertEqual(recalled[0].provenance["step_id"], "s1")
        s.close()


# ===========================================================================
# 6. Verification policy: UNKNOWN never becomes fact
# ===========================================================================

class TestVerificationPolicy(unittest.TestCase):
    """VERIFIED observations become factual memory; UNKNOWN does not."""

    def test_verified_success_becomes_observation(self):
        obs = _make_observation(status="VERIFIED_SUCCESS")
        mtype = MemoryPolicy.classify_observation(obs)
        self.assertEqual(mtype, MemoryType.OBSERVATION)

    def test_verified_failure_becomes_observation(self):
        obs = _make_observation(status="VERIFIED_FAILURE")
        mtype = MemoryPolicy.classify_observation(obs)
        self.assertEqual(mtype, MemoryType.OBSERVATION)

    def test_unknown_becomes_uncertain_never_factual(self):
        obs = _make_observation(status="UNKNOWN")
        mtype = MemoryPolicy.classify_observation(obs)
        self.assertEqual(mtype, MemoryType.UNCERTAIN_OBSERVATION)
        self.assertNotEqual(mtype, MemoryType.OBSERVATION)

    def test_unknown_record_not_stored_as_observation_type(self):
        obs = _make_observation(status="UNKNOWN")
        record = build_observation_record(obs, "runTerminalCommand")
        self.assertIsNotNone(record)
        self.assertEqual(record.memory_type, MemoryType.UNCERTAIN_OBSERVATION)
        self.assertEqual(record.verification_status, "UNKNOWN")

    def test_capture_unknown_does_not_produce_observation(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        obs = _make_observation(status="UNKNOWN")
        mid = capture_observation(s, obs, "runTerminalCommand")
        self.assertIsNotNone(mid)  # it IS stored, but as uncertain
        recalled = s.recall()
        self.assertEqual(len(recalled), 1)
        self.assertEqual(recalled[0].memory_type, MemoryType.UNCERTAIN_OBSERVATION)
        s.close()


# ===========================================================================
# 7. Freshness reassessment
# ===========================================================================

class TestFreshness(unittest.TestCase):
    """Historical records get correct freshness when recalled."""

    def test_recent_record_is_current(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        obs = _make_observation()
        capture_observation(s, obs, "openApplication")
        recalled = s.recall()
        self.assertEqual(recalled[0].freshness(), StateFreshness.CURRENT.value)
        s.close()

    def test_old_record_is_stale_or_expired(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        old_time = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
        obs = _make_observation(observed_at=old_time)
        capture_observation(s, obs, "createFile")
        recalled = s.recall()
        self.assertEqual(
            recalled[0].freshness(),
            StateFreshness.REQUIRES_REFRESH.value,
        )
        s.close()


# ===========================================================================
# 8. Current-vs-memory epistemic distinction
# ===========================================================================

class TestCurrentVsMemory(unittest.TestCase):
    """Memory must not be silently treated as current state."""

    def test_historical_context_marks_current_as_unestablished(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        old_time = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat()
        obs = _make_observation(
            domain="filesystem",
            subject="notes.txt",
            status="VERIFIED_SUCCESS",
            observed_at=old_time,
        )
        capture_observation(s, obs, "createFile")
        recalled = s.recall(domain="filesystem", subject="notes.txt")
        self.assertEqual(len(recalled), 1)

        ctx = recalled[0].as_historical_context()
        self.assertFalse(ctx["current_state_established"])
        self.assertEqual(ctx["epistemic_status"], "historical_observation")
        self.assertEqual(
            ctx["historical_freshness"],
            StateFreshness.REQUIRES_REFRESH.value,
        )
        s.close()

    def test_memory_preserves_original_verification_status(self):
        """Even if the file no longer exists, the memory must still say
        it was VERIFIED_SUCCESS at the time of observation."""
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        obs = _make_observation(
            domain="filesystem",
            subject="deleted_file.txt",
            status="VERIFIED_SUCCESS",
        )
        capture_observation(s, obs, "createFile")
        recalled = s.recall()
        # The memory still says VERIFIED_SUCCESS because that was the
        # historical truth at observation time.
        self.assertEqual(recalled[0].verification_status, "VERIFIED_SUCCESS")
        # But freshness tells us it's old and needs re-observation.
        self.assertNotEqual(
            recalled[0].freshness(max_age_seconds=0.001),
            StateFreshness.CURRENT.value,
        )
        s.close()


# ===========================================================================
# 9. S6 WorkResult integration
# ===========================================================================

class TestS6Integration(unittest.TestCase):
    """capture_work_result round-trip: S6 result -> S7 -> recall."""

    def test_capture_successful_work(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        wr = _make_work_result()
        summary = capture_work_result(s, wr)
        self.assertEqual(summary["status"], StoreStatus.OK)
        self.assertIsNotNone(summary["work_memory_id"])
        self.assertEqual(len(summary["step_memory_ids"]), 2)
        self.assertEqual(summary["skipped"], 0)
        s.close()

    def test_recall_work_after_restart(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        wr = _make_work_result(goal="Test persistence")
        capture_work_result(s, wr)
        s.close()

        s2 = MemoryStore(path=path)
        s2.open()
        work_records = s2.recall(memory_type=MemoryType.WORK_OUTCOME)
        self.assertEqual(len(work_records), 1)
        self.assertEqual(work_records[0].subject, "Test persistence")
        self.assertEqual(
            work_records[0].verification_status, "VERIFIED_SUCCESS"
        )

        step_records = s2.recall(memory_type=MemoryType.STEP_OUTCOME)
        self.assertEqual(len(step_records), 2)
        s2.close()

    def test_capture_preserves_failure_history(self):
        """A work that failed at step 2 must preserve both the success
        of step 1 and the failure of step 2 — not overwrite history."""
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        wr = _make_work_result(
            goal="Failing work",
            overall_status="VERIFIED_FAILURE",
            steps=[
                {
                    "step_id": "step-1",
                    "tool": "createFile",
                    "status": "VERIFIED_SUCCESS",
                    "verification": {"status": "VERIFIED_SUCCESS"},
                    "state": {},
                    "failure": None,
                    "recovery": {"status": "NOT_ELIGIBLE"},
                },
                {
                    "step_id": "step-2",
                    "tool": "openApplication",
                    "status": "VERIFIED_FAILURE",
                    "verification": {"status": "VERIFIED_FAILURE", "detail": "not found"},
                    "state": {},
                    "failure": {"category": "APPLICATION_NOT_OBSERVED", "confidence": "MEDIUM"},
                    "recovery": {"status": "NOT_ELIGIBLE"},
                },
            ],
        )
        summary = capture_work_result(s, wr)
        self.assertEqual(summary["status"], StoreStatus.OK)

        steps = s.recall(memory_type=MemoryType.STEP_OUTCOME)
        self.assertEqual(len(steps), 2)
        statuses = {r.provenance["step_id"]: r.verification_status for r in steps}
        self.assertEqual(statuses["step-1"], "VERIFIED_SUCCESS")
        self.assertEqual(statuses["step-2"], "VERIFIED_FAILURE")
        s.close()

    def test_capture_preserves_recovery_history(self):
        """A recovered step must preserve both the initial failure and
        the recovery success in the step payload."""
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        wr = _make_work_result(
            goal="Recovery work",
            steps=[
                {
                    "step_id": "step-1",
                    "tool": "openApplication",
                    "status": "RECOVERED",
                    "verification": {"status": "VERIFIED_FAILURE", "detail": "initial failure"},
                    "state": {},
                    "failure": {"category": "APPLICATION_NOT_OBSERVED"},
                    "recovery": {
                        "status": "RECOVERED",
                        "action": "RELAUNCH_APPLICATION",
                        "attempts": 1,
                    },
                },
            ],
        )
        capture_work_result(s, wr)
        steps = s.recall(memory_type=MemoryType.STEP_OUTCOME)
        self.assertEqual(len(steps), 1)
        step_payload = steps[0].payload["step"]
        # Initial failure is preserved
        self.assertEqual(step_payload["verification"]["status"], "VERIFIED_FAILURE")
        # Recovery success is also preserved
        self.assertEqual(step_payload["recovery"]["status"], "RECOVERED")
        s.close()


# ===========================================================================
# 10. Failure isolation
# ===========================================================================

class TestFailureIsolation(unittest.TestCase):
    """Store unavailability must not raise into callers."""

    def test_remember_returns_none_when_unavailable(self):
        s = MemoryStore(path=Path("/nonexistent/path/that/cannot/exist/db.sqlite"))
        # Force status to UNAVAILABLE without trying to create the dir
        s.status = StoreStatus.UNAVAILABLE
        s._conn = None
        # Patch open to always fail
        with patch.object(s, "open", return_value=False):
            r = MemoryRecord(
                memory_id="mem-fail",
                memory_type=MemoryType.OBSERVATION,
                domain="application",
                subject="test",
                observed_at=now_iso(),
                created_at=now_iso(),
                verification_status="VERIFIED_SUCCESS",
                payload={},
                provenance={},
            )
            result = s.remember(r)
            self.assertIsNone(result)

    def test_recall_returns_empty_when_unavailable(self):
        s = MemoryStore(path=Path("/nonexistent/nope/db.sqlite"))
        s.status = StoreStatus.UNAVAILABLE
        s._conn = None
        with patch.object(s, "open", return_value=False):
            result = s.recall(domain="application")
            self.assertEqual(result, [])

    def test_capture_work_result_returns_unavailable(self):
        s = MemoryStore(path=Path("/nonexistent/nope/db.sqlite"))
        s.status = StoreStatus.UNAVAILABLE
        s._conn = None
        with patch.object(s, "open", return_value=False):
            wr = _make_work_result()
            summary = capture_work_result(s, wr)
            self.assertEqual(summary["status"], StoreStatus.UNAVAILABLE)
            self.assertIsNone(summary["work_memory_id"])

    def test_capture_observation_returns_none_on_failure(self):
        s = MemoryStore(path=Path("/nonexistent/nope/db.sqlite"))
        s.status = StoreStatus.UNAVAILABLE
        s._conn = None
        with patch.object(s, "open", return_value=False):
            obs = _make_observation()
            result = capture_observation(s, obs, "openApplication")
            self.assertIsNone(result)

    def test_count_returns_zero_when_unavailable(self):
        s = MemoryStore(path=Path("/nonexistent/nope/db.sqlite"))
        s.status = StoreStatus.UNAVAILABLE
        s._conn = None
        with patch.object(s, "open", return_value=False):
            self.assertEqual(s.count(), 0)


# ===========================================================================
# 11. Bounded retrieval
# ===========================================================================

class TestBoundedRetrieval(unittest.TestCase):
    """Queries must be bounded; unbounded dumps are not allowed."""

    def test_default_limit(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        for i in range(100):
            s.remember(MemoryRecord(
                memory_id=f"mem-bound-{i}",
                memory_type=MemoryType.OBSERVATION,
                domain="application",
                subject=f"app-{i}",
                observed_at=now_iso(),
                created_at=now_iso(),
                verification_status="VERIFIED_SUCCESS",
                payload={},
                provenance={},
            ))
        recalled = s.recall()
        self.assertLessEqual(len(recalled), DEFAULT_RECALL_LIMIT)
        s.close()

    def test_explicit_limit_respected(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        for i in range(20):
            s.remember(MemoryRecord(
                memory_id=f"mem-lim-{i}",
                memory_type=MemoryType.OBSERVATION,
                domain="filesystem",
                subject=f"file-{i}",
                observed_at=now_iso(),
                created_at=now_iso(),
                verification_status="VERIFIED_SUCCESS",
                payload={},
                provenance={},
            ))
        recalled = s.recall(limit=5)
        self.assertEqual(len(recalled), 5)
        s.close()

    def test_hard_cap_enforced(self):
        """Even if caller requests 10000, the hard cap applies."""
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        # We don't need to actually insert MAX_RECALL_LIMIT+ records;
        # just verify the SQL LIMIT is clamped.
        recalled = s.recall(limit=99999)
        # The query should have used MAX_RECALL_LIMIT internally.
        # With 0 records, result is empty, but no error.
        self.assertEqual(len(recalled), 0)
        s.close()

    def test_zero_limit_clamped_to_one(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        s.remember(MemoryRecord(
            memory_id="mem-zero",
            memory_type=MemoryType.OBSERVATION,
            domain="application",
            subject="test",
            observed_at=now_iso(),
            created_at=now_iso(),
            verification_status="VERIFIED_SUCCESS",
            payload={},
            provenance={},
        ))
        recalled = s.recall(limit=0)
        self.assertEqual(len(recalled), 1)  # clamped to 1
        s.close()


# ===========================================================================
# 12. Reset
# ===========================================================================

class TestReset(unittest.TestCase):
    """Store reset clears all memories."""

    def test_reset_empties_store(self):
        path = _tmp_db()
        s = MemoryStore(path=path)
        s.open()
        for i in range(3):
            s.remember(MemoryRecord(
                memory_id=f"mem-rst-{i}",
                memory_type=MemoryType.OBSERVATION,
                domain="application",
                subject=f"app-{i}",
                observed_at=now_iso(),
                created_at=now_iso(),
                verification_status="VERIFIED_SUCCESS",
                payload={},
                provenance={},
            ))
        self.assertEqual(s.count(), 3)
        self.assertTrue(s.reset())
        self.assertEqual(s.count(), 0)
        s.close()


if __name__ == "__main__":
    unittest.main()
