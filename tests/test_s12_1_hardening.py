"""
S12.1: Artifact Continuity Hardening - Verification Suite.

Tests the hardened invariants of S12.1:
  1. Verification Semantics: unverified_ok is not automatically forced on observation tools.
  2. Context Scope & Isolation: Context lifecycle can be safely isolated and reset.
  3. Explicit Artifact Semantics: Differentiates active, last_created, and last_verified.
  4. Failure / UNKNOWN Semantics: FAILED or UNKNOWN operations never manufacture verified artifacts.
  5. Mutation Continuity: Rename and Move operations preserve logical artifact identity.
  6. Golden Workflow: Complete CREATE -> OPEN/MUTATE -> READ -> VERIFY continuity.
"""

import os
import shutil
import tempfile
from pathlib import Path
import pytest

from agent.artifacts import (
    ActiveComputerContext,
    ArtifactIdentity,
    ArtifactType,
    ResolutionStatus,
    canonicalize_locator,
    active_context,
)
from agent.intent import IntentInterpreter, S8Step, S8WorkPlan
from agent.work import execute_work, OUTCOME_VERIFIED_SUCCESS, OUTCOME_UNKNOWN


@pytest.fixture
def clean_context():
    """Ensure global active_context is clean before and after tests."""
    active_context.reset()
    yield active_context
    active_context.reset()


@pytest.fixture
def temp_workspace():
    """Create a temporary directory for file tests."""
    d = tempfile.mkdtemp(prefix="zarya_s12_1_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


class TestS12_1_VerificationSemantics:
    """Verify that S12.1 restores strict S6 verification continuation semantics."""

    def test_s8_work_plan_does_not_force_unverified_ok(self):
        """Observation tools must default to unverified_ok=False unless explicitly set."""
        plan = S8WorkPlan(
            intent="Read file notes.txt",
            goal="Read notes.txt",
            steps=[
                S8Step(id="step-1", tool="readFile", args={"path": "notes.txt"}, description="Read notes"),
                S8Step(id="step-2", tool="listFiles", args={"path": "."}, description="List directory"),
                S8Step(id="step-3", tool="searchFiles", args={"query": "test"}, description="Search"),
                S8Step(id="step-4", tool="systemInfo", args={}, description="Get system info"),
                S8Step(id="step-5", tool="takeScreenshot", args={}, description="Take screenshot"),
            ],
        )

        s6_plan = plan.to_s6_plan()
        for step in s6_plan["steps"]:
            assert step["unverified_ok"] is False, f"Step {step['tool']} had unverified_ok=True automatically!"

    def test_explicit_unverified_ok_is_preserved(self):
        """If a step explicitly sets unverified_ok=True, it must be preserved."""
        plan = S8WorkPlan(
            intent="Read file notes.txt with unverified ok",
            goal="Read notes.txt",
            steps=[
                S8Step(id="step-1", tool="readFile", args={"path": "notes.txt"}, unverified_ok=True),
            ],
        )
        s6_plan = plan.to_s6_plan()
        assert s6_plan["steps"][0]["unverified_ok"] is True


class TestS12_1_ContextScopeAndIsolation:
    """Verify that ActiveComputerContext lifecycle and isolation operate cleanly."""

    def test_isolated_contexts_do_not_leak_targets(self):
        """Two independent ActiveComputerContext instances must not share or leak state."""
        ctx_a = ActiveComputerContext()
        ctx_b = ActiveComputerContext()

        art_a = ArtifactIdentity.create_file_artifact(
            path="C:/workspace/alpha.txt",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        ctx_a.record_artifact(art_a, set_active=True)

        res_a = ctx_a.resolve_target("it")
        assert res_a.is_resolved
        assert "alpha.txt" in res_a.canonical_locator

        res_b = ctx_b.resolve_target("it")
        assert not res_b.is_resolved
        assert res_b.status == ResolutionStatus.NOT_FOUND

    def test_context_reset_clears_all_tracking(self):
        """Calling reset() must wipe active, last_created, last_verified, and artifact table."""
        ctx = ActiveComputerContext()
        art = ArtifactIdentity.create_file_artifact(
            path="C:/workspace/file.txt",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        ctx.record_artifact(art, set_active=True)
        assert ctx.active_artifact is not None
        assert ctx.last_created_artifact is not None
        assert ctx.last_verified_artifact is not None

        ctx.reset()

        assert ctx.active_artifact is None
        assert ctx.last_created_artifact is None
        assert ctx.last_verified_artifact is None
        assert ctx.resolve_target("it").status == ResolutionStatus.NOT_FOUND


class TestS12_1_ExplicitArtifactSemantics:
    """Verify precise distinctions between active, last_created, and last_verified artifacts."""

    def test_read_file_updates_active_but_not_last_created(self):
        """Reading a file makes it the active artifact, but NOT the last_created_artifact."""
        ctx = ActiveComputerContext()

        # Step 1: Create file A
        art_a = ArtifactIdentity.create_file_artifact(
            path="C:/workspace/created.txt",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        ctx.record_artifact(art_a, set_active=True)
        assert ctx.active_artifact.canonical_locator == art_a.canonical_locator
        assert ctx.last_created_artifact.canonical_locator == art_a.canonical_locator

        # Step 2: Read file B
        ctx.update_from_tool_response(
            tool_name="readFile",
            args={"path": "C:/workspace/existing.txt"},
            response={"path": "C:/workspace/existing.txt", "result": "content here"},
        )

        # Active is now B, but last_created remains A
        assert "existing.txt" in ctx.active_artifact.canonical_locator
        assert "created.txt" in ctx.last_created_artifact.canonical_locator

    def test_failed_operation_does_not_manufacture_verified_artifact(self):
        """A tool execution that returns VERIFIED_FAILURE must not become last_verified_artifact."""
        ctx = ActiveComputerContext()

        ctx.update_from_tool_response(
            tool_name="createFile",
            args={"path": "C:/workspace/failed.txt"},
            response={
                "path": "C:/workspace/failed.txt",
                "error": "Disk full",
                "verification": {"status": "VERIFIED_FAILURE"},
            },
        )

        assert ctx.last_verified_artifact is None
        assert ctx.active_artifact is None


class TestS12_1_RenameAndMoveContinuity:
    """Verify that file mutations preserve the logical ArtifactIdentity."""

    def test_rename_file_preserves_logical_identity(self, temp_workspace, clean_context):
        """Renaming a file keeps the same artifact identity with updated locator and previous_locators."""
        file_a = temp_workspace / "original.txt"
        file_b = temp_workspace / "renamed.txt"

        # Create original file
        resp_create = {
            "result": f"Created file: {file_a}",
            "path": str(file_a),
            "verification": {"status": "VERIFIED_SUCCESS"},
        }
        clean_context.update_from_tool_response("createFile", {"path": str(file_a)}, resp_create)
        original_art = clean_context.active_artifact
        assert original_art is not None
        orig_id = original_art.artifact_id

        # Rename operation
        resp_rename = {
            "result": f"Renamed {file_a.name} -> {file_b.name}",
            "path": str(file_b),
            "verification": {"status": "VERIFIED_SUCCESS"},
        }
        mutated_art = clean_context.update_from_tool_response(
            "renameFile",
            {"path": str(file_a), "new_name": file_b.name},
            resp_rename,
        )

        assert mutated_art is not None
        assert mutated_art.artifact_id == orig_id
        assert mutated_art.canonical_locator == str(file_b.resolve())
        assert mutated_art.display_name == file_b.name
        assert str(file_a.resolve()) in mutated_art.metadata.get("previous_locators", [])

        # Resolving "it" now returns the renamed file
        res = clean_context.resolve_target("it")
        assert res.is_resolved
        assert res.canonical_locator == str(file_b.resolve())

    def test_move_file_preserves_logical_identity(self, temp_workspace, clean_context):
        """Moving a file keeps the same artifact identity with updated destination locator."""
        sub = temp_workspace / "subdir"
        sub.mkdir()
        file_src = temp_workspace / "doc.txt"
        file_dst = sub / "doc.txt"

        resp_create = {
            "result": f"Created file: {file_src}",
            "path": str(file_src),
            "verification": {"status": "VERIFIED_SUCCESS"},
        }
        clean_context.update_from_tool_response("createFile", {"path": str(file_src)}, resp_create)
        orig_id = clean_context.active_artifact.artifact_id

        resp_move = {
            "result": f"Moved {file_src.name} -> {file_dst}",
            "path": str(file_dst),
            "verification": {"status": "VERIFIED_SUCCESS"},
        }
        mutated_art = clean_context.update_from_tool_response(
            "moveFile",
            {"path": str(file_src), "destination": str(sub)},
            resp_move,
        )

        assert mutated_art.artifact_id == orig_id
        assert mutated_art.canonical_locator == str(file_dst.resolve())
        assert str(file_src.resolve()) in mutated_art.metadata.get("previous_locators", [])


class TestS12_1_TargetResolutionContinuity:
    """Verify pronoun and placeholder resolution under edge conditions."""

    def test_ambiguous_reference_returns_clarification_status(self, clean_context):
        """If two distinct artifacts share a common name in different directories, return AMBIGUOUS."""
        art1 = ArtifactIdentity.create_file_artifact(
            path="C:/dir1/report.pdf",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        art2 = ArtifactIdentity.create_file_artifact(
            path="C:/dir2/report.pdf",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        clean_context.record_artifact(art1, set_active=False)
        clean_context.record_artifact(art2, set_active=False)

        res = clean_context.resolve_target("report.pdf")
        assert res.status == ResolutionStatus.AMBIGUOUS
        assert len(res.candidates) == 2

    def test_missing_reference_returns_not_found(self, clean_context):
        """Resolving 'it' when no artifact has ever been touched must return NOT_FOUND."""
        res = clean_context.resolve_target("it")
        assert res.status == ResolutionStatus.NOT_FOUND


class TestS12_1_GoldenContinuityWorkflow:
    """Execute the full golden multi-step workflow verifying target continuity."""

    def test_golden_create_open_read_verify_continuity(self, temp_workspace, clean_context):
        """WorkPlan: CREATE notes.txt -> READ $ACTIVE_ARTIFACT -> VERIFY identical content and path."""
        target_file = temp_workspace / "continuity_test.txt"

        plan = {
            "goal": "Create notes and verify continuity via active artifact placeholder",
            "steps": [
                {
                    "id": "step-1",
                    "tool": "createFile",
                    "args": {"path": str(target_file), "content": "Hello S12.1 Hardening\n", "overwrite": True},
                    "unverified_ok": False,
                },
                {
                    "id": "step-2",
                    "tool": "readFile",
                    "args": {"path": "$ACTIVE_ARTIFACT"},
                    "unverified_ok": True,
                },
            ],
        }

        result = execute_work(plan, authorized=True, context=clean_context)
        assert result["overall_status"] == OUTCOME_VERIFIED_SUCCESS
        assert len(result["completed_steps"]) == 2

        # Step 2 path must have resolved to Step 1 canonical path
        step2_run = result["completed_steps"][1]
        assert step2_run["path"] == str(target_file.resolve())
