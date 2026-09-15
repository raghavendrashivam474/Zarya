"""
S13 Active Computer Context Test Suite
======================================
Tests:
  1. Desktop Observer (WindowObservation, DesktopObservation, Win32 introspection)
  2. ActiveComputerContext S13 state, properties, and freshness semantics
  3. Window-to-Artifact Association logic
  4. Context-aware natural reference resolution ("the active document", "the current window", etc.)
  5. S13 Registered Tools (getActiveWindow, getActiveContext) and S2 Verification
  6. S8 Intent interpretation for desktop context queries
  7. End-to-end Work Execution integration
  8. Disruption, ambiguity, and historical/current separation scenarios
"""

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.artifacts import (
    ActiveComputerContext,
    ArtifactIdentity,
    ArtifactType,
    ResolutionStatus,
    active_context,
    canonicalize_locator,
)
from agent.intent import IntentInterpreter, process_natural_intent
from agent.registry import TOOLS, load_all
from agent.tools.desktop_observer import (
    DesktopObservation,
    WindowObservation,
    observe_active_window,
)
from agent.work import (
    OUTCOME_VERIFIED_SUCCESS,
    execute_work,
)


class TestS13DesktopObserver(unittest.TestCase):
    """Unit tests for desktop observation substrate."""

    def test_window_observation_to_dict(self):
        obs = WindowObservation(
            title="notes.txt - Notepad",
            hwnd=12345,
            process_name="notepad.exe",
            process_id=999,
            observed_at="2026-09-15T00:00:00Z",
            freshness="CURRENT",
            evidence="Win32 GetForegroundWindow hwnd=12345",
        )
        d = obs.to_dict()
        self.assertEqual(d["title"], "notes.txt - Notepad")
        self.assertEqual(d["hwnd"], 12345)
        self.assertEqual(d["process_name"], "notepad.exe")
        self.assertEqual(d["process_id"], 999)
        self.assertEqual(d["freshness"], "CURRENT")
        self.assertIn("hwnd=12345", d["evidence"])

    def test_desktop_observation_available(self):
        w_obs = WindowObservation(
            title="Code - Zarya",
            hwnd=54321,
            process_name="Code.exe",
            process_id=1001,
            observed_at="2026-09-15T00:00:00Z",
            freshness="CURRENT",
            evidence="Win32 GetForegroundWindow",
        )
        d_obs = DesktopObservation(
            active_window=w_obs,
            observed_at="2026-09-15T00:00:00Z",
            freshness="CURRENT",
        )
        self.assertTrue(d_obs.is_available)
        self.assertIsNone(d_obs.error)

    def test_desktop_observation_unavailable(self):
        d_obs = DesktopObservation(
            active_window=None,
            observed_at="2026-09-15T00:00:00Z",
            freshness="UNKNOWN",
            error="Window observation failed",
        )
        self.assertFalse(d_obs.is_available)
        self.assertEqual(d_obs.freshness, "UNKNOWN")
        self.assertEqual(d_obs.error, "Window observation failed")

    def test_live_observe_active_window(self):
        """Live test on running host — should return a valid DesktopObservation."""
        obs = observe_active_window()
        self.assertIsInstance(obs, DesktopObservation)
        self.assertIn(obs.freshness, ("CURRENT", "UNKNOWN"))
        if obs.is_available:
            self.assertIsNotNone(obs.active_window)
            self.assertIsInstance(obs.active_window.title, str)
            self.assertIsInstance(obs.active_window.process_name, str)


class TestS13ActiveComputerContextState(unittest.TestCase):
    """Unit tests for ActiveComputerContext S13 state and freshness management."""

    def setUp(self):
        self.ctx = ActiveComputerContext()

    def tearDown(self):
        self.ctx.clear()

    def test_initial_state(self):
        self.assertEqual(self.ctx.desktop_freshness, "UNKNOWN")
        self.assertIsNone(self.ctx.active_window_title)
        self.assertIsNone(self.ctx.active_window_process)
        self.assertIsNone(self.ctx.active_application)

    def test_observe_desktop_updates_state(self):
        fake_window = WindowObservation(
            title="document.docx - Word",
            hwnd=111,
            process_name="winword.exe",
            process_id=222,
            observed_at="2026-09-15T01:00:00Z",
            freshness="CURRENT",
            evidence="mock",
        )
        fake_obs = DesktopObservation(
            active_window=fake_window,
            observed_at="2026-09-15T01:00:00Z",
            freshness="CURRENT",
        )

        with patch("agent.tools.desktop_observer.observe_active_window", return_value=fake_obs):
            res = self.ctx.observe_desktop()

        self.assertEqual(self.ctx.desktop_freshness, "CURRENT")
        self.assertEqual(self.ctx.active_window_title, "document.docx - Word")
        self.assertEqual(self.ctx.active_window_process, "winword.exe")
        self.assertEqual(self.ctx.active_application, "winword.exe")

    def test_clear_resets_s13_state(self):
        self.ctx._active_window_title = "Test Window"
        self.ctx._active_window_process = "test.exe"
        self.ctx._desktop_freshness = "CURRENT"

        self.ctx.clear()
        self.assertEqual(self.ctx.desktop_freshness, "UNKNOWN")
        self.assertIsNone(self.ctx.active_window_title)
        self.assertIsNone(self.ctx.active_window_process)

    def test_get_desktop_snapshot(self):
        art = ArtifactIdentity.create_file_artifact(
            path="C:/test/file.txt",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        self.ctx.record_artifact(art, set_active=True)
        self.ctx._active_window_title = "file.txt - Notepad"
        self.ctx._active_window_process = "notepad.exe"
        self.ctx._active_application = "notepad.exe"
        self.ctx._desktop_freshness = "CURRENT"
        self.ctx._desktop_observed_at = "2026-09-15T02:00:00Z"

        snap = self.ctx.get_desktop_snapshot()
        self.assertEqual(snap["active_application"], "notepad.exe")
        self.assertEqual(snap["active_window_title"], "file.txt - Notepad")
        self.assertEqual(snap["active_artifact"], art.canonical_locator)
        self.assertEqual(snap["desktop_freshness"], "CURRENT")


class TestS13WindowArtifactAssociation(unittest.TestCase):
    """Unit tests for matching window titles to known tracked artifacts."""

    def setUp(self):
        self.ctx = ActiveComputerContext()

    def tearDown(self):
        self.ctx.clear()

    def test_exact_filename_in_window_title_matches(self):
        art = ArtifactIdentity.create_file_artifact(
            path="C:/Users/workspace/project/notes.txt",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        self.ctx.record_artifact(art, set_active=False)

        matched = self.ctx.match_artifact_to_window("notes.txt - Notepad")
        self.assertIsNotNone(matched)
        self.assertEqual(matched.canonical_locator, art.canonical_locator)

    def test_unrelated_window_title_returns_none(self):
        art = ArtifactIdentity.create_file_artifact(
            path="C:/Users/workspace/project/notes.txt",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        self.ctx.record_artifact(art, set_active=False)

        matched = self.ctx.match_artifact_to_window("Inbox - Outlook")
        self.assertIsNone(matched)

    def test_ambiguous_window_title_returns_none_safely(self):
        """If two different tracked artifacts have the same filename in different directories."""
        art1 = ArtifactIdentity.create_file_artifact(
            path="C:/dirA/report.txt",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        art2 = ArtifactIdentity.create_file_artifact(
            path="C:/dirB/report.txt",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        self.ctx.record_artifact(art1, set_active=False)
        self.ctx.record_artifact(art2, set_active=False)

        # Since two artifacts match 'report.txt', single match must return None to avoid guessing
        matched = self.ctx.match_artifact_to_window("report.txt - Notepad")
        self.assertIsNone(matched)


class TestS13ContextResolution(unittest.TestCase):
    """Unit tests for context-aware reference resolution."""

    def setUp(self):
        self.ctx = ActiveComputerContext()

    def tearDown(self):
        self.ctx.clear()

    def test_resolve_active_document_via_window_matching(self):
        art = ArtifactIdentity.create_file_artifact(
            path="C:/workspace/todo.txt",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        self.ctx.record_artifact(art, set_active=False)

        self.ctx._active_window_title = "todo.txt - Notepad"
        self.ctx._desktop_freshness = "CURRENT"

        res = self.ctx.resolve_target("the active document")
        self.assertEqual(res.status, ResolutionStatus.RESOLVED)
        self.assertEqual(res.canonical_locator, art.canonical_locator)
        self.assertIn("todo.txt - Notepad", res.reason)

    def test_resolve_active_window_phrase(self):
        art = ArtifactIdentity.create_file_artifact(
            path="C:/workspace/main.py",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        self.ctx.record_artifact(art, set_active=False)

        self.ctx._active_window_title = "main.py - Visual Studio Code"
        self.ctx._desktop_freshness = "CURRENT"

        res = self.ctx.resolve_target("the active window")
        self.assertEqual(res.status, ResolutionStatus.RESOLVED)
        self.assertEqual(res.canonical_locator, art.canonical_locator)

    def test_fallback_to_active_artifact_when_no_window_evidence(self):
        art = ArtifactIdentity.create_file_artifact(
            path="C:/workspace/fallback.txt",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        self.ctx.record_artifact(art, set_active=True)

        # Freshness is UNKNOWN (no desktop observation)
        self.ctx._desktop_freshness = "UNKNOWN"
        self.ctx._active_window_title = None

        res = self.ctx.resolve_target("it")
        self.assertEqual(res.status, ResolutionStatus.RESOLVED)
        self.assertEqual(res.canonical_locator, art.canonical_locator)


class TestS13RegisteredTools(unittest.TestCase):
    """Unit tests for getActiveWindow and getActiveContext tool handlers."""

    @classmethod
    def setUpClass(cls):
        load_all()

    def setUp(self):
        active_context.clear()

    def tearDown(self):
        active_context.clear()

    def test_get_active_window_tool_execution(self):
        self.assertIn("getActiveWindow", TOOLS)
        tool_fn = TOOLS["getActiveWindow"]

        fake_w = WindowObservation(
            title="test.py - Editor",
            hwnd=777,
            process_name="editor.exe",
            process_id=888,
            observed_at="2026-09-15T03:00:00Z",
            freshness="CURRENT",
            evidence="Win32",
        )
        fake_obs = DesktopObservation(
            active_window=fake_w,
            observed_at="2026-09-15T03:00:00Z",
            freshness="CURRENT",
        )

        with patch("agent.tools.desktop_observer.observe_active_window", return_value=fake_obs):
            res = tool_fn({})

        self.assertEqual(res["title"], "test.py - Editor")
        self.assertEqual(res["process_name"], "editor.exe")
        self.assertEqual(res["freshness"], "CURRENT")
        self.assertEqual(res["verification"]["status"], "VERIFIED_SUCCESS")
        self.assertEqual(active_context.active_window_title, "test.py - Editor")

    def test_get_active_context_tool_execution(self):
        self.assertIn("getActiveContext", TOOLS)
        tool_fn = TOOLS["getActiveContext"]

        fake_w = WindowObservation(
            title="workspace - Visual Studio Code",
            hwnd=999,
            process_name="Code.exe",
            process_id=1234,
            observed_at="2026-09-15T04:00:00Z",
            freshness="CURRENT",
            evidence="Win32",
        )
        fake_obs = DesktopObservation(
            active_window=fake_w,
            observed_at="2026-09-15T04:00:00Z",
            freshness="CURRENT",
        )

        with patch("agent.tools.desktop_observer.observe_active_window", return_value=fake_obs):
            res = tool_fn({})

        self.assertEqual(res["active_application"], "Code.exe")
        self.assertEqual(res["active_window"], "workspace - Visual Studio Code")
        self.assertEqual(res["freshness"], "CURRENT")
        self.assertIn("working_directory", res)
        self.assertEqual(res["verification"]["status"], "VERIFIED_SUCCESS")


class TestS13IntentInterpretation(unittest.TestCase):
    """Unit tests for S8 IntentInterpreter recognizing S13 desktop context queries."""

    def setUp(self):
        self.interp = IntentInterpreter()
        active_context.clear()

    def tearDown(self):
        active_context.clear()

    def test_intent_active_window_queries(self):
        queries = [
            "What is the active window?",
            "what's the active window",
            "What is the current window",
            "Get active window",
            "check active window",
        ]
        for q in queries:
            plan = self.interp.interpret(q)
            self.assertEqual(plan.status, "UNDERSTOOD", f"Failed on query: {q}")
            self.assertEqual(len(plan.steps), 1)
            self.assertEqual(plan.steps[0].tool, "getActiveWindow")

    def test_intent_active_context_queries(self):
        queries = [
            "What is the active context?",
            "what is the current context",
            "What app am I using?",
            "what am i working on",
            "get active context",
        ]
        for q in queries:
            plan = self.interp.interpret(q)
            self.assertEqual(plan.status, "UNDERSTOOD", f"Failed on query: {q}")
            self.assertEqual(len(plan.steps), 1)
            self.assertEqual(plan.steps[0].tool, "getActiveContext")


class TestS13WorkExecutionIntegration(unittest.TestCase):
    """Integration tests executing work plans with desktop context tools."""

    @classmethod
    def setUpClass(cls):
        load_all()

    def setUp(self):
        active_context.clear()

    def tearDown(self):
        active_context.clear()

    def test_execute_work_get_active_context(self):
        plan = {
            "goal": "Observe desktop context before action",
            "steps": [
                {
                    "id": "step-1",
                    "tool": "getActiveContext",
                    "args": {},
                    "unverified_ok": True,
                }
            ],
        }
        res = execute_work(plan, authorized=True)
        self.assertEqual(res["overall_status"], OUTCOME_VERIFIED_SUCCESS)
        completed = res.get("completed_steps", [])
        self.assertEqual(len(completed), 1)
        step_res = completed[0]
        self.assertEqual(step_res["status"], OUTCOME_VERIFIED_SUCCESS)
        self.assertEqual(step_res["tool"], "getActiveContext")
        self.assertEqual(step_res["verification"]["status"], "VERIFIED_SUCCESS")
        self.assertIn(active_context.desktop_freshness, ("CURRENT", "UNKNOWN"))


class TestS13DisruptionAndHistoricalSeparation(unittest.TestCase):
    """Tests ensuring S13 preserves uncertainty and does NOT promote S7 memory into current state."""

    def setUp(self):
        self.ctx = ActiveComputerContext()

    def tearDown(self):
        self.ctx.clear()

    def test_window_observation_failure_preserves_unknown(self):
        fake_obs = DesktopObservation(
            active_window=None,
            observed_at="2026-09-15T05:00:00Z",
            freshness="UNKNOWN",
            error="Access denied",
        )
        with patch("agent.tools.desktop_observer.observe_active_window", return_value=fake_obs):
            self.ctx.observe_desktop()

        self.assertEqual(self.ctx.desktop_freshness, "UNKNOWN")
        self.assertIsNone(self.ctx.active_window_title)

    def test_historical_memory_does_not_alter_desktop_freshness(self):
        """Historical knowledge of a file does not manufacture CURRENT desktop freshness."""
        art = ArtifactIdentity.create_file_artifact(
            path="C:/historical/past_notes.txt",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
            metadata={"source": "s7_persistent_memory"},
        )
        self.ctx.record_artifact(art, set_active=False)

        # Freshness MUST remain UNKNOWN unless an actual observation occurred
        self.assertEqual(self.ctx.desktop_freshness, "UNKNOWN")
        self.assertIsNone(self.ctx.active_window_title)

        # Resolving 'the active document' without live window evidence should NOT match
        matched = self.ctx.match_artifact_to_window()
        self.assertIsNone(matched)
