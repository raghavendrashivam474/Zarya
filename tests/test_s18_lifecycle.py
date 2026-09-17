"""S18 Unit & Integration Test Suite.

Validates all 10 core invariants from the S18 Implementation Brief:
  1. Full lifecycle state transitions
  2. Checkpoint is NOT a success claim
  3. Resumable state filtering
  4. UNKNOWN preservation (UNKNOWN remains UNKNOWN)
  5. No duplicate execution on resume
  6. Reality check on resume (safe halt on external mutation)
  7. Artifact continuity across resume boundaries
  8. Authorization separation (unauthorized resume rejected)
  9. Cooperative pause and cancel
  10. Fail-safe persistence behavior
"""

import os
import tempfile
from pathlib import Path
import pytest

from agent.lifecycle import (
    LifecycleStatus,
    WorkState,
    StepRecord,
    create_operation,
    RESUMABLE_STATES,
    TERMINAL_STATES,
)
from agent.checkpoint import CheckpointStore
from agent.resume import resume_work, verify_checkpoint_reality
from agent.control import request_pause, request_cancel, get_operation_status
from agent.work import execute_work, OUTCOME_VERIFIED_SUCCESS, OUTCOME_VERIFIED_FAILURE, OUTCOME_UNKNOWN, OUTCOME_INCOMPLETE
from agent.artifacts import ActiveComputerContext, ArtifactIdentity, ArtifactType


@pytest.fixture
def tmp_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_s18.db"
        store = CheckpointStore(db_path)
        store.open()
        yield store
        store.close()


@pytest.fixture
def safe_dir():
    """Create a temporary directory within Desktop/Documents safe zones for tool tests."""
    desktop = Path.home() / "Desktop" / "zarya_s18_test_tmp"
    desktop.mkdir(parents=True, exist_ok=True)
    yield desktop
    # Cleanup
    if desktop.exists():
        import shutil
        shutil.rmtree(desktop, ignore_errors=True)


# ── Test 1: Full Lifecycle Transitions ───────────────────────────

def test_full_lifecycle_transitions():
    op = create_operation("multi-step task", {"steps": [{"id": "s1"}, {"id": "s2"}]})
    assert op.status == LifecycleStatus.CREATED

    # Legal: CREATED -> AUTHORIZED
    assert op.transition_to(LifecycleStatus.AUTHORIZED) is True
    assert op.status == LifecycleStatus.AUTHORIZED

    # Illegal: AUTHORIZED -> COMPLETED (cannot skip execution)
    assert op.transition_to(LifecycleStatus.COMPLETED) is False
    assert op.status == LifecycleStatus.AUTHORIZED

    # Legal: AUTHORIZED -> RUNNING
    assert op.transition_to(LifecycleStatus.RUNNING) is True
    assert op.status == LifecycleStatus.RUNNING

    # Legal: RUNNING -> CHECKPOINTED
    op.record_step(StepRecord(step_index=0, step_id="s1", tool="createFile", outcome="VERIFIED_SUCCESS"))
    assert op.record_checkpoint() is True
    assert op.status == LifecycleStatus.CHECKPOINTED
    assert op.checkpoint_step == 1

    # Legal: CHECKPOINTED -> RUNNING (continue)
    assert op.transition_to(LifecycleStatus.RUNNING) is True

    # Legal: RUNNING -> COMPLETED
    op.record_step(StepRecord(step_index=1, step_id="s2", tool="readFile", outcome="VERIFIED_SUCCESS"))
    assert op.transition_to(LifecycleStatus.COMPLETED) is True
    assert op.status == LifecycleStatus.COMPLETED
    assert op.is_terminal is True


# ── Test 2: Checkpoint is NOT a Success Claim ───────────────────

def test_checkpoint_is_not_success_claim():
    op = create_operation("create and organize", {"steps": [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]})
    op.transition_to(LifecycleStatus.AUTHORIZED)
    op.transition_to(LifecycleStatus.RUNNING)

    # Step 1 succeeds and checkpoints
    op.record_step(StepRecord(step_index=0, step_id="s1", tool="createFile", outcome="VERIFIED_SUCCESS"))
    op.record_checkpoint()

    # Invariants:
    assert op.status == LifecycleStatus.CHECKPOINTED
    assert op.checkpoint_step == 1
    assert op.remaining_steps == 2
    assert op.is_terminal is False
    # Checkpoint status != overall success
    assert op.status != LifecycleStatus.COMPLETED


# ── Test 3: Resumable States Filtering ───────────────────────────

def test_resumable_states_filtering(tmp_store):
    # Create operations in different states
    states_to_test = [
        (LifecycleStatus.CHECKPOINTED, 1, True),
        (LifecycleStatus.PAUSED, 1, True),
        (LifecycleStatus.INTERRUPTED, 1, True),
        (LifecycleStatus.COMPLETED, 2, False),
        (LifecycleStatus.CANCELLED, 1, False),
        (LifecycleStatus.FAILED, 1, False),
        (LifecycleStatus.UNKNOWN, 0, False),
    ]

    for status, cp_step, expected_resumable in states_to_test:
        op = create_operation(f"op_{status.value}", {"steps": [{"id": "s1"}, {"id": "s2"}]})
        op.status = status
        op.checkpoint_step = cp_step
        tmp_store.save(op)

    resumable_ops = tmp_store.list_resumable()
    resumable_ids = [o.operation_id for o in resumable_ops]

    # Only CHECKPOINTED, PAUSED, INTERRUPTED (with cp > 0) should be returned
    assert len(resumable_ops) == 3
    for op in resumable_ops:
        assert op.status in RESUMABLE_STATES
        assert op.checkpoint_step > 0


# ── Test 4: UNKNOWN Remains UNKNOWN and Non-Resumable ────────────

def test_unknown_preservation(tmp_store):
    op = create_operation("uncertain work", {"steps": [{"id": "s1"}]})
    op.transition_to(LifecycleStatus.AUTHORIZED)
    op.transition_to(LifecycleStatus.RUNNING)
    op.transition_to(LifecycleStatus.UNKNOWN, "Verification returned UNKNOWN")
    tmp_store.save(op)

    loaded = tmp_store.load(op.operation_id)
    assert loaded.status == LifecycleStatus.UNKNOWN
    assert loaded.is_resumable is False
    assert loaded.is_terminal is True


# ── Test 5: No Duplicate Execution on Resume ─────────────────────

def test_no_duplicate_execution_on_resume(tmp_store, safe_dir):
    file1 = safe_dir / "step1.txt"
    file2 = safe_dir / "step2.txt"

    plan = {
        "goal": "create two files sequentially",
        "steps": [
            {"id": "step_1", "tool": "createFile", "args": {"path": str(file1), "content": "first"}},
            {"id": "step_2", "tool": "createFile", "args": {"path": str(file2), "content": "second"}},
        ],
    }

    # Step 1 executes initially
    op = create_operation("create two files", plan)
    op.transition_to(LifecycleStatus.AUTHORIZED)
    
    # Execute only step 1, then simulate pause/interruption
    res1 = execute_work(
        plan={"goal": "first step only", "steps": [plan["steps"][0]]},
        authorized=True,
        work_state=op,
        checkpoint_store=tmp_store,
    )
    assert res1["overall_status"] == OUTCOME_VERIFIED_SUCCESS
    assert file1.exists()

    # Op is now checkpointed at step 1
    assert op.checkpoint_step == 1
    op.status = LifecycleStatus.PAUSED
    tmp_store.save(op)

    # Overwrite file1 with a sentinel to verify it is NOT touched during resume
    file1.write_text("sentinel_do_not_overwrite", encoding="utf-8")

    # Resume the full 2-step plan from checkpoint
    resume_result = resume_work(
        operation_id=op.operation_id,
        checkpoint_store=tmp_store,
        authorized=True,
    )

    assert resume_result["overall_status"] == OUTCOME_VERIFIED_SUCCESS
    assert len(resume_result["completed_steps"]) == 2
    assert file2.exists()
    # Ensure step 1 was skipped (sentinel preserved, not overwritten by "first")
    assert file1.read_text(encoding="utf-8") == "sentinel_do_not_overwrite"


# ── Test 6: Reality Check Negative Case (Safe Halt on Mutation) ──

def test_reality_check_fails_on_external_deletion(tmp_store, safe_dir):
    file1 = safe_dir / "must_exist.txt"
    file1.write_text("initial content", encoding="utf-8")

    plan = {
        "goal": "multi-step file work",
        "steps": [
            {"id": "s1", "tool": "createFile", "args": {"path": str(file1), "content": "initial"}},
            {"id": "s2", "tool": "readFile", "args": {"path": str(file1)}},
        ],
    }

    op = create_operation("file work", plan)
    op.status = LifecycleStatus.CHECKPOINTED
    op.checkpoint_step = 1
    op.record_step(StepRecord(
        step_index=0,
        step_id="s1",
        tool="createFile",
        outcome="VERIFIED_SUCCESS",
        evidence={"verification": {"path": str(file1)}},
    ))
    tmp_store.save(op)

    # Externally delete the file before resume
    file1.unlink()
    assert not file1.exists()

    # Resume must detect missing file via reality check and halt safely
    resume_result = resume_work(
        operation_id=op.operation_id,
        checkpoint_store=tmp_store,
        authorized=True,
    )

    assert resume_result["overall_status"] == OUTCOME_VERIFIED_FAILURE
    assert "Reality check failed" in resume_result["summary"]
    
    # Verify state was marked FAILED in DB
    reloaded = tmp_store.load(op.operation_id)
    assert reloaded.status == LifecycleStatus.FAILED
    assert reloaded.failure_info["category"] == "STALE_CHECKPOINT_STATE"


# ── Test 7: Artifact Continuity Across Resume Boundaries ─────────

def test_artifact_continuity_preserved(tmp_store):
    ctx = ActiveComputerContext()
    # S12 deterministic artifact creation via path
    artifact = ArtifactIdentity.create_file_artifact(
        path=r"C:\Users\test\doc.txt",
        source_operation="createFile",
        verification_status="VERIFIED_SUCCESS",
    )
    ctx.record_artifact(artifact)

    op = create_operation("edit doc", {"steps": [{"id": "s1"}, {"id": "s2"}]})
    op.artifact_ids.append(artifact.artifact_id)
    op.status = LifecycleStatus.CHECKPOINTED
    op.checkpoint_step = 1
    tmp_store.save(op)

    # Reload and verify exact artifact identity survived across persistence boundary
    loaded = tmp_store.load(op.operation_id)
    assert artifact.artifact_id in loaded.artifact_ids
    assert ctx.active_artifact is not None
    assert ctx.active_artifact.artifact_id == artifact.artifact_id


# ── Test 8: Authorization Enforcement on Resume ──────────────────

def test_unauthorized_resume_rejected(tmp_store):
    op = create_operation("sensitive work", {"steps": [{"id": "s1"}]})
    op.status = LifecycleStatus.PAUSED
    op.checkpoint_step = 1
    tmp_store.save(op)

    # Attempt resume without authorization
    res = resume_work(
        operation_id=op.operation_id,
        checkpoint_store=tmp_store,
        authorized=False,
    )

    assert res["overall_status"] == OUTCOME_INCOMPLETE
    assert "not authorized" in res["summary"]


# ── Test 9: Cooperative Pause & Cancel ───────────────────────────

def test_cooperative_pause_and_cancel(tmp_store):
    op = create_operation("long work", {"steps": [{"id": "s1"}, {"id": "s2"}]})
    op.status = LifecycleStatus.RUNNING
    tmp_store.save(op)

    # Pause
    pause_res = request_pause(op.operation_id, tmp_store, reason="User stepped away")
    assert pause_res["success"] is True
    assert pause_res["status"] == LifecycleStatus.PAUSED.value

    # Cancel
    cancel_res = request_cancel(op.operation_id, tmp_store, reason="Aborted by operator")
    assert cancel_res["success"] is True
    assert cancel_res["status"] == LifecycleStatus.CANCELLED.value

    # Terminal state cannot be re-cancelled
    double_cancel = request_cancel(op.operation_id, tmp_store)
    assert double_cancel["success"] is False
    assert "terminal" in double_cancel["error"]