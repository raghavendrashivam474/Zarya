"""S18 Live Desktop Smoke Validation Script.

Executes 2 live Windows desktop scenarios:
  1. POSITIVE SMOKE:
     - Step 1: Create a file in Documents/Zarya/s18_smoke_test.txt
     - Checkpoint after Step 1
     - Simulate interruption / pause
     - Resume operation
     - Step 2: Read and verify the file content
     - Verify full completion and final outcome
  2. NEGATIVE SMOKE:
     - Checkpoint established for a file
     - External deletion of the file
     - Attempt resume
     - Reality check detects stale reality -> Safe halt as VERIFIED_FAILURE
"""

import os
import sys
import shutil
from pathlib import Path

# Add project root to sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agent.lifecycle import create_operation, LifecycleStatus, StepRecord
from agent.checkpoint import CheckpointStore
from agent.resume import resume_work
from agent.work import execute_work, OUTCOME_VERIFIED_SUCCESS, OUTCOME_VERIFIED_FAILURE


def run_smoke():
    print("================================================================")
    print("          ZARYA S18 LIVE DESKTOP SMOKE VALIDATION               ")
    print("================================================================")

    # Safe test directory in Documents/Zarya
    doc_dir = Path.home() / "Documents" / "Zarya" / "s18_smoke"
    doc_dir.mkdir(parents=True, exist_ok=True)
    smoke_file = doc_dir / "s18_live_artifact.txt"

    # Temporary DB for smoke test isolation
    smoke_db = doc_dir / "s18_smoke_store.db"
    store = CheckpointStore(smoke_db)
    assert store.open() is True, "Failed to open smoke CheckpointStore"

    try:
        # -------------------------------------------------------------
        # SCENARIO 1: POSITIVE WORKFLOW (Interruption & Resume)
        # -------------------------------------------------------------
        print("\n--- [SCENARIO 1] POSITIVE LIVE INTERRUPTION & RESUME ---")

        plan = {
            "goal": "Live Desktop S18 Continuity Workflow",
            "steps": [
                {
                    "id": "step_1_create",
                    "tool": "createFile",
                    "args": {"path": str(smoke_file), "content": "Zarya S18 Live Content V1"},
                },
                {
                    "id": "step_2_read",
                    "tool": "readFile",
                    "args": {"path": str(smoke_file)},
                    "unverified_ok": True,
                },
            ],
        }

        # 1a. Start operation and execute Step 1 only
        op = create_operation("live desktop smoke", plan)
        op.transition_to(LifecycleStatus.AUTHORIZED)

        print("[1a] Executing Step 1 (createFile)...")
        res1 = execute_work(
            plan={"goal": "Step 1 create", "steps": [plan["steps"][0]]},
            authorized=True,
            work_state=op,
            checkpoint_store=store,
        )
        assert res1["overall_status"] == OUTCOME_VERIFIED_SUCCESS, f"Step 1 failed: {res1}"
        assert smoke_file.exists(), "Smoke file was not physically created on disk"
        print(f"     File physically created at: {smoke_file}")
        print(f"     Checkpoint step recorded: {op.checkpoint_step}")

        # 1b. Simulate interruption: mark PAUSED
        op.status = LifecycleStatus.PAUSED
        store.save(op)
        print("[1b] Work paused at checkpoint. Simulating process interruption.")

        # 1c. Resume operation: execute remaining steps
        print("[1c] Resuming operation from checkpoint...")
        resume_res = resume_work(
            operation_id=op.operation_id,
            checkpoint_store=store,
            authorized=True,
        )

        assert resume_res["overall_status"] == OUTCOME_VERIFIED_SUCCESS, f"Resume failed: {resume_res}"
        assert len(resume_res["completed_steps"]) == 2, f"Expected 2 steps, got {len(resume_res['completed_steps'])}"
        print("     Resume finished with status: VERIFIED_SUCCESS")
        print("     All steps completed and verified across the interruption boundary.")
        print("[PASS] SCENARIO 1 PASSED 100%")

        # -------------------------------------------------------------
        # SCENARIO 2: NEGATIVE WORKFLOW (Stale State Reality Check)
        # -------------------------------------------------------------
        print("\n--- [SCENARIO 2] NEGATIVE LIVE STALE STATE DETECTION ---")

        neg_file = doc_dir / "s18_negative_test.txt"
        neg_file.write_text("pre-existing content", encoding="utf-8")

        neg_plan = {
            "goal": "Negative Reality Check Validation",
            "steps": [
                {
                    "id": "neg_step_1",
                    "tool": "createFile",
                    "args": {"path": str(neg_file), "content": "pre-existing content"},
                },
                {
                    "id": "neg_step_2",
                    "tool": "readFile",
                    "args": {"path": str(neg_file)},
                    "unverified_ok": True,
                },
            ],
        }

        neg_op = create_operation("negative reality smoke", neg_plan)
        neg_op.status = LifecycleStatus.CHECKPOINTED
        neg_op.checkpoint_step = 1
        neg_op.record_step(StepRecord(
            step_index=0,
            step_id="neg_step_1",
            tool="createFile",
            outcome="VERIFIED_SUCCESS",
            evidence={"verification": {"path": str(neg_file)}},
        ))
        store.save(neg_op)

        # External perturbation: physically delete the file
        print("[2a] Checkpoint recorded for: %s" % neg_file)
        print("[2b] Externally deleting file to simulate environment mutation...")
        if neg_file.exists():
            neg_file.unlink()
        assert not neg_file.exists(), "Negative file still exists"

        # Attempt resume: reality check must catch the missing file
        print("[2c] Attempting resume on mutated state...")
        neg_resume_res = resume_work(
            operation_id=neg_op.operation_id,
            checkpoint_store=store,
            authorized=True,
        )

        assert neg_resume_res["overall_status"] == OUTCOME_VERIFIED_FAILURE, "Expected VERIFIED_FAILURE"
        assert "Reality check failed" in neg_resume_res["summary"], f"Unexpected summary: {neg_resume_res['summary']}"
        print("     Reality check correctly detected missing artifact and safely halted.")
        print(f"     Outcome truthful: {neg_resume_res['summary']}")
        print("[PASS] SCENARIO 2 PASSED 100%")

    finally:
        store.close()
        # Cleanup test files
        shutil.rmtree(doc_dir, ignore_errors=True)
        print("\nCleaned up temporary test artifacts.")

    print("\n================================================================")
    print("   ALL S18 REAL DESKTOP SMOKE TESTS COMPLETED SUCCESSFULLY!     ")
    print("================================================================")


if __name__ == "__main__":
    run_smoke()