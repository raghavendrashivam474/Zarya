"""
Zarya S6: Verified Multi-Step Work Unit Tests.

Validates:
1. Plan validation (structure, step counts, tool registration, uniqueness).
2. Authorization gating (explicit authorized flag required).
3. Bounded sequential execution and partial state preservation.
4. Immediate halt on VERIFIED_FAILURE or UNKNOWN step outcomes.
5. S5 closed-loop recovery integration (RECOVERED step enables continuation).
6. Non-verified tool behavior and `unverified_ok` policy.
7. Exception containment during step execution.

Mocking notes:
    We patch `agent.work.TOOLS` (not `agent.registry.TOOLS`) because
    `agent/work.py` imports the name `TOOLS` into its own module namespace
    at load time. Patching where the name is looked up is the standard
    unittest.mock convention. See https://docs.python.org/3/library/unittest.mock.html#where-to-patch
"""

import unittest
from unittest.mock import patch

from agent.work import (
    MAX_STEPS,
    OUTCOME_INCOMPLETE,
    OUTCOME_UNKNOWN,
    OUTCOME_VERIFIED_FAILURE,
    OUTCOME_VERIFIED_SUCCESS,
    STEP_FAILURE,
    STEP_RECOVERED,
    STEP_SUCCESS,
    STEP_UNKNOWN,
    execute_work,
    validate_plan,
)


# ---------------------------------------------------------------------------
# Helpers to build fake tool registries as plain dicts
# (mirrors the real production shape of agent.registry.TOOLS)
# ---------------------------------------------------------------------------

def _make_success_tool(detail: str = "ok"):
    def _tool(args):
        return {
            "result": "done",
            "verification": {"status": "VERIFIED_SUCCESS", "detail": detail},
            "state": {"freshness": "CURRENT"},
            "failure": None,
            "recovery": {"status": "NOT_ELIGIBLE"},
        }
    return _tool


def _make_failure_tool(detail: str = "failed"):
    def _tool(args):
        return {
            "verification": {"status": "VERIFIED_FAILURE", "detail": detail},
            "failure": {"category": "FILE_NOT_CREATED"},
            "recovery": {"status": "NOT_ELIGIBLE"},
        }
    return _tool


def _make_unknown_tool(detail: str = "inconclusive"):
    def _tool(args):
        return {
            "verification": {"status": "UNKNOWN", "detail": detail},
            "failure": {"category": "INSUFFICIENT_EVIDENCE"},
            "recovery": {"status": "NOT_ELIGIBLE"},
        }
    return _tool


def _make_recovered_tool():
    def _tool(args):
        return {
            "verification": {"status": "VERIFIED_FAILURE", "detail": "initial failure"},
            "failure": {"category": "APPLICATION_NOT_OBSERVED"},
            "recovery": {
                "status": "RECOVERED",
                "action": "RELAUNCH_APPLICATION",
                "attempts": 1,
                "reason": "Recovery relaunch verified successfully.",
            },
        }
    return _tool


def _make_unverified_tool():
    def _tool(args):
        return {"result": "Some unverified text"}
    return _tool


def _make_exception_tool(exc: Exception):
    def _tool(args):
        raise exc
    return _tool


# ---------------------------------------------------------------------------
# Plan validation tests (no patching needed — validate_plan uses TOOLS at
# call time via `tool not in TOOLS`, which resolves against agent.work.TOOLS)
# ---------------------------------------------------------------------------

class TestS6PlanValidation(unittest.TestCase):
    """Test WorkPlan schema validation and bounds checks."""

    def test_non_dict_plan_rejected(self):
        valid, reason = validate_plan(["not a dict"])
        self.assertFalse(valid)
        self.assertIn("structured dictionary", reason)

    def test_empty_steps_rejected(self):
        valid, reason = validate_plan({"goal": "Test", "steps": []})
        self.assertFalse(valid)
        self.assertIn("non-empty list", reason)

    def test_exceeds_max_steps_rejected(self):
        steps = [{"id": f"step-{i}", "tool": "createFile"} for i in range(MAX_STEPS + 1)]
        valid, reason = validate_plan({"goal": "Big plan", "steps": steps})
        self.assertFalse(valid)
        self.assertIn("exceeds maximum allowed steps", reason)

    def test_duplicate_step_ids_rejected(self):
        plan = {
            "steps": [
                {"id": "step-1", "tool": "createFile"},
                {"id": "step-1", "tool": "createFile"},
            ]
        }
        valid, reason = validate_plan(plan)
        self.assertFalse(valid)
        self.assertIn("Duplicate step ID", reason)

    def test_unknown_tool_rejected(self):
        plan = {"steps": [{"id": "step-1", "tool": "nonExistentTool123"}]}
        valid, reason = validate_plan(plan)
        self.assertFalse(valid)
        self.assertIn("unknown tool", reason)

    def test_invalid_args_format_rejected(self):
        plan = {"steps": [{"id": "step-1", "tool": "createFile", "args": "invalid_args_string"}]}
        valid, reason = validate_plan(plan)
        self.assertFalse(valid)
        self.assertIn("must be a dictionary", reason)

    def test_valid_plan_passes(self):
        plan = {
            "goal": "Valid task",
            "steps": [
                {"id": "step-1", "tool": "createFile", "args": {"path": "test.txt", "content": "hello"}},
                {"id": "step-2", "tool": "openApplication", "args": {"name": "notepad"}},
            ],
        }
        valid, reason = validate_plan(plan)
        self.assertTrue(valid)
        self.assertEqual(reason, "Plan is valid.")


# ---------------------------------------------------------------------------
# Authorization tests
# ---------------------------------------------------------------------------

class TestS6Authorization(unittest.TestCase):
    """Validate explicit work authorization enforcement."""

    def test_unauthorized_plan_rejected(self):
        plan = {
            "goal": "Unauthorized run",
            "steps": [{"id": "step-1", "tool": "createFile", "args": {"path": "a.txt"}}],
        }
        res = execute_work(plan, authorized=False)
        self.assertEqual(res["overall_status"], OUTCOME_INCOMPLETE)
        self.assertIn("not authorized", res["summary"])
        self.assertEqual(len(res["completed_steps"]), 0)
        self.assertEqual(res["skipped_steps"], ["step-1"])


# ---------------------------------------------------------------------------
# Execution flow tests: patch agent.work.TOOLS with a real dict of fakes
# ---------------------------------------------------------------------------

class TestS6ExecutionFlow(unittest.TestCase):
    """Validate sequential execution, verification evaluation, and halting behavior."""

    def test_multi_step_all_success(self):
        fake_tools = {
            "fakeCreate": _make_success_tool("file created"),
            "fakeOpen": _make_success_tool("app launched"),
        }
        plan = {
            "goal": "2 step success",
            "steps": [
                {"id": "step-1", "tool": "fakeCreate"},
                {"id": "step-2", "tool": "fakeOpen"},
            ],
        }

        with patch("agent.work.TOOLS", fake_tools):
            res = execute_work(plan, authorized=True)

        self.assertEqual(res["overall_status"], OUTCOME_VERIFIED_SUCCESS)
        self.assertEqual(len(res["completed_steps"]), 2)
        self.assertIsNone(res["failed_step"])
        self.assertEqual(len(res["skipped_steps"]), 0)
        self.assertEqual(res["completed_steps"][0]["status"], STEP_SUCCESS)
        self.assertEqual(res["completed_steps"][1]["status"], STEP_SUCCESS)

    def test_step_failure_stops_execution(self):
        fake_tools = {
            "toolA": _make_success_tool(),
            "toolB": _make_failure_tool("Disk write failure."),
            "toolC": _make_success_tool(),
        }
        plan = {
            "goal": "Halt on failure",
            "steps": [
                {"id": "step-1", "tool": "toolA"},
                {"id": "step-2", "tool": "toolB"},
                {"id": "step-3", "tool": "toolC"},
            ],
        }

        with patch("agent.work.TOOLS", fake_tools):
            res = execute_work(plan, authorized=True)

        self.assertEqual(res["overall_status"], OUTCOME_VERIFIED_FAILURE)
        self.assertIn("Halted at step 'step-2'", res["summary"])
        self.assertEqual(len(res["completed_steps"]), 2)
        self.assertEqual(res["completed_steps"][0]["status"], STEP_SUCCESS)
        self.assertEqual(res["completed_steps"][1]["status"], STEP_FAILURE)
        self.assertIsNotNone(res["failed_step"])
        self.assertEqual(res["failed_step"]["step_id"], "step-2")
        self.assertEqual(res["skipped_steps"], ["step-3"])

    def test_step_unknown_stops_execution(self):
        fake_tools = {
            "anyTool": _make_unknown_tool("Probe inconclusive"),
            "anotherTool": _make_success_tool(),
        }
        plan = {
            "goal": "Unknown halt",
            "steps": [
                {"id": "step-1", "tool": "anyTool"},
                {"id": "step-2", "tool": "anotherTool"},
            ],
        }

        with patch("agent.work.TOOLS", fake_tools):
            res = execute_work(plan, authorized=True)

        self.assertEqual(res["overall_status"], OUTCOME_UNKNOWN)
        self.assertIn("outcome is UNKNOWN", res["summary"])
        self.assertEqual(len(res["completed_steps"]), 1)
        self.assertEqual(res["completed_steps"][0]["status"], STEP_UNKNOWN)
        self.assertEqual(res["skipped_steps"], ["step-2"])


# ---------------------------------------------------------------------------
# S5 recovery integration tests (unit level, mocked)
# ---------------------------------------------------------------------------

class TestS6RecoveryIntegration(unittest.TestCase):
    """Validate S5 closed-loop recovery integration during multi-step work."""

    def test_recovered_step_allows_work_to_continue(self):
        fake_tools = {
            "openApplication": _make_recovered_tool(),
            "createFile": _make_success_tool(),
        }
        plan = {
            "goal": "Recover and continue",
            "steps": [
                {"id": "step-1", "tool": "openApplication"},
                {"id": "step-2", "tool": "createFile"},
            ],
        }

        with patch("agent.work.TOOLS", fake_tools):
            res = execute_work(plan, authorized=True)

        self.assertEqual(res["overall_status"], OUTCOME_VERIFIED_SUCCESS)
        self.assertEqual(len(res["completed_steps"]), 2)
        self.assertEqual(res["completed_steps"][0]["status"], STEP_RECOVERED)
        self.assertEqual(res["completed_steps"][1]["status"], STEP_SUCCESS)
        self.assertEqual(len(res["skipped_steps"]), 0)


# ---------------------------------------------------------------------------
# Unverified tools + exception containment
# ---------------------------------------------------------------------------

class TestS6UnverifiedAndExceptions(unittest.TestCase):
    """Validate behavior with unverified tools and catastrophic tool exceptions."""

    def test_unverified_tool_without_flag_fails_as_unknown(self):
        fake_tools = {"readFile": _make_unverified_tool()}
        plan = {"steps": [{"id": "step-1", "tool": "readFile", "unverified_ok": False}]}

        with patch("agent.work.TOOLS", fake_tools):
            res = execute_work(plan, authorized=True)

        self.assertEqual(res["overall_status"], OUTCOME_UNKNOWN)
        self.assertEqual(res["completed_steps"][0]["status"], STEP_UNKNOWN)

    def test_unverified_tool_with_flag_succeeds(self):
        fake_tools = {"readFile": _make_unverified_tool()}
        plan = {"steps": [{"id": "step-1", "tool": "readFile", "unverified_ok": True}]}

        with patch("agent.work.TOOLS", fake_tools):
            res = execute_work(plan, authorized=True)

        self.assertEqual(res["overall_status"], OUTCOME_VERIFIED_SUCCESS)
        self.assertEqual(res["completed_steps"][0]["status"], STEP_SUCCESS)

    def test_exception_in_tool_stops_execution(self):
        fake_tools = {
            "runTerminalCommand": _make_exception_tool(RuntimeError("Hardware communication crash")),
            "createFile": _make_success_tool(),
        }
        plan = {
            "steps": [
                {"id": "step-1", "tool": "runTerminalCommand"},
                {"id": "step-2", "tool": "createFile"},
            ],
        }

        with patch("agent.work.TOOLS", fake_tools):
            res = execute_work(plan, authorized=True)

        self.assertEqual(res["overall_status"], OUTCOME_VERIFIED_FAILURE)
        self.assertIn("Hardware communication crash", res["summary"])
        self.assertEqual(res["skipped_steps"], ["step-2"])
        self.assertEqual(res["failed_step"]["step_id"], "step-1")


if __name__ == "__main__":
    unittest.main()
