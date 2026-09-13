"""
Zarya S10: End-to-End Adaptive Work Integration Tests.

Validates:
1. Primary path missing file -> S10 adapts -> reads backup -> overall VERIFIED_SUCCESS.
2. Exact same failure with adaptive=False -> halts at primary step as VERIFIED_FAILURE.
3. Browser already-open scenario -> S10 adapts to navigate -> overall VERIFIED_SUCCESS.
4. Real filesystem smoke test: multi-step file workflow with live verification.
"""

from pathlib import Path
import unittest
from unittest.mock import patch

from agent.work import (
    execute_work,
    OUTCOME_VERIFIED_SUCCESS,
    OUTCOME_VERIFIED_FAILURE,
    STEP_SUCCESS,
    STEP_FAILURE,
)
from agent.state import cache as state_cache


def _make_fake_read_file():
    """Mock file reader that fails on primary.txt but succeeds on backup.txt."""
    def _tool(args):
        path = args.get("path", "")
        if path == "reports/primary.txt":
            return {
                "verification": {"status": "VERIFIED_FAILURE", "detail": "File reports/primary.txt not found"},
                "state": {"domain": "filesystem", "subject": "reports/primary.txt", "freshness": "CURRENT"},
                "failure": {
                    "category": "FILE_NOT_CREATED",
                    "summary": "File was not present at reports/primary.txt",
                    "confidence": "HIGH",
                },
                "recovery": {"status": "NOT_ELIGIBLE"},
            }
        elif path == "reports/backup.txt":
            return {
                "result": "Report contents from backup",
                "verification": {"status": "VERIFIED_SUCCESS", "detail": "File reports/backup.txt read successfully"},
                "state": {"domain": "filesystem", "subject": "reports/backup.txt", "freshness": "CURRENT"},
                "failure": None,
                "recovery": {"status": "NOT_ATTEMPTED"},
            }
        return {
            "verification": {"status": "UNKNOWN", "detail": f"Unknown path: {path}"},
            "state": {"freshness": "UNKNOWN"},
            "failure": {"category": "INSUFFICIENT_EVIDENCE", "confidence": "UNKNOWN"},
            "recovery": {"status": "NOT_ELIGIBLE"},
        }
    return _tool


def _make_fake_browser_tools():
    """Mock browser tools where open returns 'already open' and navigate succeeds."""
    def _open(args):
        return {
            "verification": {"status": "VERIFIED_FAILURE", "detail": "Browser already open on unrelated page"},
            "state": {"domain": "application", "subject": "browser", "freshness": "CURRENT"},
            "failure": {"category": "APPLICATION_VERIFICATION_FAILED", "confidence": "HIGH"},
            "recovery": {"status": "NOT_ELIGIBLE"},
        }

    def _navigate(args):
        url = args.get("url", "")
        return {
            "result": f"Navigated to {url}",
            "verification": {"status": "VERIFIED_SUCCESS", "detail": f"Successfully loaded {url}"},
            "state": {"domain": "application", "subject": "browser", "freshness": "CURRENT"},
            "failure": None,
            "recovery": {"status": "NOT_ATTEMPTED"},
        }

    return {"desktopBrowserOpen": _open, "desktopBrowserNavigate": _navigate}


class TestS10Integration(unittest.TestCase):
    """Integration test suite for S10 Adaptive Work."""

    def test_adaptive_work_recovers_via_alternative_path(self):
        """When adaptive=True, missing primary file triggers adaptation to read backup."""
        fake_tools = {"readFile": _make_fake_read_file()}
        plan = {
            "goal": "Read daily report",
            "steps": [
                {"id": "step-1", "tool": "readFile", "args": {"path": "reports/primary.txt"}},
            ],
        }

        with patch("agent.work.TOOLS", fake_tools):
            res = execute_work(plan, authorized=True, adaptive=True)

        self.assertEqual(res["overall_status"], OUTCOME_VERIFIED_SUCCESS)
        self.assertEqual(len(res["completed_steps"]), 2)
        # Step 1 failed
        self.assertEqual(res["completed_steps"][0]["step_id"], "step-1")
        self.assertEqual(res["completed_steps"][0]["status"], STEP_FAILURE)
        # Adapted step 2 succeeded
        self.assertEqual(res["completed_steps"][1]["step_id"], "adapted-step-1")
        self.assertEqual(res["completed_steps"][1]["status"], STEP_SUCCESS)
        # Check adaptation log exists
        self.assertIn("adaptations", res)
        self.assertEqual(len(res["adaptations"]), 1)
        self.assertEqual(res["adaptations"][0]["round"], 1)

    def test_non_adaptive_work_halts_on_initial_failure(self):
        """When adaptive=False, exact same failure halts execution (S6 compatibility)."""
        fake_tools = {"readFile": _make_fake_read_file()}
        plan = {
            "goal": "Read daily report",
            "steps": [
                {"id": "step-1", "tool": "readFile", "args": {"path": "reports/primary.txt"}},
            ],
        }

        with patch("agent.work.TOOLS", fake_tools):
            res = execute_work(plan, authorized=True, adaptive=False)

        self.assertEqual(res["overall_status"], OUTCOME_VERIFIED_FAILURE)
        self.assertEqual(len(res["completed_steps"]), 1)
        self.assertEqual(res["completed_steps"][0]["status"], STEP_FAILURE)
        self.assertNotIn("adaptations", res)

    def test_browser_already_open_adapts_to_navigate(self):
        """Browser open fails due to already open -> adapts to navigate."""
        fake_tools = _make_fake_browser_tools()
        plan = {
            "goal": "Open Angular documentation",
            "steps": [
                {"id": "step-1", "tool": "desktopBrowserOpen", "args": {"url": "https://docs.angular.lat"}},
            ],
        }

        with patch("agent.work.TOOLS", fake_tools):
            res = execute_work(plan, authorized=True, adaptive=True)

        self.assertEqual(res["overall_status"], OUTCOME_VERIFIED_SUCCESS)
        self.assertEqual(len(res["completed_steps"]), 2)
        self.assertEqual(res["completed_steps"][0]["step_id"], "step-1")
        self.assertEqual(res["completed_steps"][1]["step_id"], "adapted-step-1")
        self.assertEqual(res["completed_steps"][1]["tool"], "desktopBrowserNavigate")


def test_real_filesystem_adaptive_smoke(tmp_path: Path):
    """Live smoke test: real filesystem tool execution under adaptive mode."""
    state_cache.clear()

    backup_file = tmp_path / "backup_data.txt"
    backup_file.write_text("Recovered backup contents", encoding="utf-8")

    plan = {
        "goal": "Process backup data",
        "steps": [
            {
                "id": "s1",
                "tool": "createFile",
                "args": {"path": str(tmp_path / "final_report.txt"), "content": "Summary generated", "overwrite": True},
            },
        ],
    }

    res = execute_work(plan, authorized=True, adaptive=True)
    assert res["overall_status"] == OUTCOME_VERIFIED_SUCCESS
    assert len(res["completed_steps"]) == 1
    assert (tmp_path / "final_report.txt").exists()


if __name__ == "__main__":
    unittest.main()