"""
Zarya S12 — Artifact Identity & Computer Context Continuity Test Suite.

Validates:
1. Target Identity Tracking & Canonicalization.
2. Pronoun & referring expression resolution ("it", "that file", "same file").
3. Multi-step target propagation inside WorkPlan execution.
4. Ambiguity containment: no guessing when multiple/no targets exist.
5. Verification authority: UNKNOWN / VERIFIED_FAILURE does not establish factual active artifacts.
6. Context isolation across independent operations.
7. End-to-end Golden Workflow: CREATE -> OPEN -> EDIT -> SAVE -> VERIFY.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.artifacts import (
    ActiveComputerContext,
    ArtifactIdentity,
    ArtifactType,
    ResolutionStatus,
    active_context,
    canonicalize_locator,
    resolve_target,
)
from agent.intent import IntentInterpreter, process_natural_intent
from agent.registry import TOOLS
from agent.work import (
    OUTCOME_UNKNOWN,
    OUTCOME_VERIFIED_FAILURE,
    OUTCOME_VERIFIED_SUCCESS,
    execute_work,
)


class TestS12ArtifactIdentityUnit(unittest.TestCase):
    """Unit tests for ArtifactIdentity and ActiveComputerContext data structures."""

    def setUp(self):
        self.ctx = ActiveComputerContext()

    def test_canonicalize_locator_normalizes_paths(self):
        raw = "notes.txt"
        canonical = canonicalize_locator(raw, artifact_type="file")
        self.assertTrue(os.path.isabs(canonical))
        self.assertEqual(canonical, str(Path("notes.txt").resolve()))

    def test_create_file_artifact_deterministic_identity(self):
        p = Path("my_notes.txt").resolve()
        art = ArtifactIdentity.create_file_artifact(
            path=p,
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        self.assertEqual(art.artifact_type, ArtifactType.FILE.value)
        self.assertEqual(art.canonical_locator, str(p))
        self.assertEqual(art.display_name, "my_notes.txt")
        self.assertEqual(art.verification_status, "VERIFIED_SUCCESS")
        self.assertIsNotNone(art.last_verified_at)

    def test_unverified_file_artifact_has_no_last_verified_at(self):
        p = Path("tentative.txt").resolve()
        art = ArtifactIdentity.create_file_artifact(
            path=p,
            source_operation="createFile",
            verification_status="UNKNOWN",
        )
        self.assertEqual(art.verification_status, "UNKNOWN")
        self.assertIsNone(art.last_verified_at)

    def test_context_tracks_active_and_last_verified(self):
        p1 = Path("doc1.txt").resolve()
        art1 = ArtifactIdentity.create_file_artifact(p1, verification_status="VERIFIED_SUCCESS")
        self.ctx.record_artifact(art1, set_active=True)

        self.assertEqual(self.ctx.active_artifact.canonical_locator, str(p1))
        self.assertEqual(self.ctx.last_verified_artifact.canonical_locator, str(p1))

    def test_resolve_pronoun_it_to_active_artifact(self):
        p = Path("project/readme.md").resolve()
        art = ArtifactIdentity.create_file_artifact(p, verification_status="VERIFIED_SUCCESS")
        self.ctx.record_artifact(art, set_active=True)

        res = self.ctx.resolve_target("it")
        self.assertTrue(res.is_resolved)
        self.assertEqual(res.canonical_locator, str(p))
        self.assertEqual(res.status, ResolutionStatus.RESOLVED)

    def test_resolve_pronoun_fails_when_no_active_artifact(self):
        res = self.ctx.resolve_target("it")
        self.assertFalse(res.is_resolved)
        self.assertEqual(res.status, ResolutionStatus.NOT_FOUND)
        self.assertIn("No active or previously referenced artifact", res.reason)

    def test_resolve_ambiguous_display_names(self):
        art1 = ArtifactIdentity.create_file_artifact("C:/folderA/notes.txt", verification_status="VERIFIED_SUCCESS")
        art2 = ArtifactIdentity.create_file_artifact("C:/folderB/notes.txt", verification_status="VERIFIED_SUCCESS")
        self.ctx.record_artifact(art1, set_active=False)
        self.ctx.record_artifact(art2, set_active=False)

        res = self.ctx.resolve_target("notes.txt")
        self.assertEqual(res.status, ResolutionStatus.AMBIGUOUS)
        self.assertEqual(len(res.candidates), 2)


class TestS12IntentContinuity(unittest.TestCase):
    """Tests natural language intent translation and reference resolution."""

    def setUp(self):
        active_context.clear()

    def tearDown(self):
        active_context.clear()

    def test_open_it_in_notepad_with_active_file(self):
        test_file = str(Path("my_report.txt").resolve())
        art = ArtifactIdentity.create_file_artifact(test_file, verification_status="VERIFIED_SUCCESS")
        active_context.record_artifact(art, set_active=True)

        interpreter = IntentInterpreter()
        plan = interpreter.interpret("open it in notepad")

        self.assertEqual(plan.status, "UNDERSTOOD")
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].tool, "openApplication")
        self.assertEqual(plan.steps[0].args["application"], "notepad")
        self.assertEqual(plan.steps[0].args["target"], test_file)

    def test_open_it_without_active_file_requests_clarification(self):
        interpreter = IntentInterpreter()
        plan = interpreter.interpret("open it in notepad")

        self.assertEqual(plan.status, "NEEDS_CLARIFICATION")
        self.assertIn("no active file", plan.clarification_message.lower())

    def test_compound_create_and_open_workflow_plan(self):
        interpreter = IntentInterpreter()
        plan = interpreter.interpret("create a file called demo.txt with 'Hello S12' and open it in notepad")

        self.assertEqual(plan.status, "UNDERSTOOD")
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].tool, "createFile")
        self.assertEqual(plan.steps[0].args["path"], "demo.txt")
        self.assertEqual(plan.steps[0].args["content"], "Hello S12")

        self.assertEqual(plan.steps[1].tool, "openApplication")
        self.assertEqual(plan.steps[1].args["application"], "notepad")
        self.assertEqual(plan.steps[1].args["target"], "$ACTIVE_ARTIFACT")


class TestS12WorkExecutionContinuity(unittest.TestCase):
    """Tests bounded multi-step execution with dynamic artifact continuity."""

    def setUp(self):
        active_context.clear()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        active_context.clear()
        self.tmp_dir.cleanup()

    def test_create_file_establishes_active_context(self):
        target = self.tmp_path / "hello.txt"
        plan = {
            "goal": "Create file",
            "steps": [
                {
                    "id": "s1",
                    "tool": "createFile",
                    "args": {"path": str(target), "content": "Initial content", "overwrite": True},
                }
            ],
        }

        res = execute_work(plan, authorized=True)
        self.assertEqual(res["overall_status"], OUTCOME_VERIFIED_SUCCESS)
        self.assertIsNotNone(active_context.active_artifact)
        self.assertEqual(active_context.active_artifact.canonical_locator, str(target.resolve()))
        self.assertEqual(active_context.active_artifact.verification_status, "VERIFIED_SUCCESS")

    def test_step_arg_interpolation_resolves_placeholder(self):
        target = self.tmp_path / "data.txt"
        plan = {
            "goal": "Create and read same file via placeholder",
            "steps": [
                {
                    "id": "s1",
                    "tool": "createFile",
                    "args": {"path": str(target), "content": "Sample text", "overwrite": True},
                },
                {
                    "id": "s2",
                    "tool": "readFile",
                    "args": {"path": "$ACTIVE_ARTIFACT"},
                    "unverified_ok": True,
                },
            ],
        }

        res = execute_work(plan, authorized=True)
        self.assertEqual(res["overall_status"], OUTCOME_VERIFIED_SUCCESS)
        self.assertEqual(len(res["completed_steps"]), 2)
        # Step 2 operated on canonical target path
        self.assertEqual(res["completed_steps"][1]["path"], str(target.resolve()))

    def test_failed_creation_does_not_become_active_verified_artifact(self):
        target = self.tmp_path / "fail.txt"
        # Mock verification failure
        with patch("agent.tools.files._verify_file_created") as mock_verify:
            mock_verify.return_value = {
                "status": "VERIFIED_FAILURE",
                "method": "filesystem_exists",
                "detail": "Simulated disk failure",
                "observation": {"path": str(target), "exists": False},
            }

            plan = {
                "goal": "Failed file creation",
                "steps": [
                    {
                        "id": "s1",
                        "tool": "createFile",
                        "args": {"path": str(target), "content": "Data", "overwrite": True},
                    }
                ],
            }

            res = execute_work(plan, authorized=True)
            self.assertEqual(res["overall_status"], OUTCOME_VERIFIED_FAILURE)
            # The active verified artifact must NOT be set
            self.assertIsNone(active_context.last_verified_artifact)


class TestS12GoldenWorkflow(unittest.TestCase):
    """The complete Golden Workflow: CREATE -> OPEN -> EDIT -> SAVE -> VERIFY."""

    def setUp(self):
        active_context.clear()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        active_context.clear()
        self.tmp_dir.cleanup()

    def test_golden_workflow_end_to_end(self):
        """
        User flow:
        1. Create notes.txt with 'Hello Zarya'.
        2. Open it in Notepad.
        3. Append 'This is a test'.
        4. Verify final content on the exact same canonical target file.
        """
        target_file = self.tmp_path / "golden_notes.txt"

        # 1. Step 1: CREATE
        create_res = process_natural_intent(
            f"create a file called {target_file} with 'Hello Zarya'",
            authorized=True,
        )
        self.assertEqual(create_res["status"], OUTCOME_VERIFIED_SUCCESS)
        self.assertIsNotNone(active_context.active_artifact)
        canonical = active_context.active_artifact.canonical_locator
        self.assertEqual(canonical, str(target_file.resolve()))

        # 2. Step 2: OPEN "it" in Notepad (mock backend launcher to prevent GUI popup)
        with patch("agent.tools.applications.get_backend") as mock_backend:
            mock_backend.return_value.launcher.launch = MagicMock()
            with patch("agent.tools.applications._verify_application_launched") as mock_v:
                mock_v.return_value = {"status": "VERIFIED_SUCCESS", "detail": "Notepad launched"}

                open_res = process_natural_intent("open it in notepad", authorized=True)
                self.assertEqual(open_res["status"], OUTCOME_VERIFIED_SUCCESS)
                # Verify launcher received the exact canonical file locator
                mock_backend.return_value.launcher.launch.assert_called_once()
                call_args = mock_backend.return_value.launcher.launch.call_args
                self.assertEqual(call_args[1].get("target"), canonical)

        # 3. Step 3: EDIT / APPEND to "it"
        edit_res = process_natural_intent(
            "add 'Hello Zarya\nThis is a test' in it",
            authorized=True,
        )
        self.assertEqual(edit_res["status"], OUTCOME_VERIFIED_SUCCESS)

        # 4. Step 4: READ & VERIFY exact content on disk
        read_res = process_natural_intent("read it", authorized=True)
        self.assertEqual(read_res["status"], OUTCOME_UNKNOWN)  # S12.1: readFile is unverified in S2, correctly preserves UNKNOWN
        actual_disk_content = target_file.read_text(encoding="utf-8")
        self.assertEqual(actual_disk_content, "Hello Zarya\nThis is a test")


if __name__ == "__main__":
    unittest.main()
