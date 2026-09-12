"""
Zarya S6: Verified Multi-Step Work Integration Tests.

Validates end-to-end execution of multi-step plans with real filesystem and
terminal tools, as well as mocked multi-domain flows including S5 recovery.
"""

from pathlib import Path
import pytest
from unittest.mock import patch

from agent.work import (
    execute_work,
    OUTCOME_VERIFIED_SUCCESS,
    OUTCOME_VERIFIED_FAILURE,
    STEP_SUCCESS,
    STEP_RECOVERED,
    STEP_FAILURE,
)
from agent.state import cache as state_cache


def test_real_filesystem_multi_step_workflow(tmp_path: Path) -> None:
    """Execute a real 3-step file workflow: create -> read -> create another."""
    state_cache.clear()

    file1 = tmp_path / "step1.txt"
    file2 = tmp_path / "step2.txt"

    plan = {
        "goal": "Create two files and read one",
        "steps": [
            {
                "id": "s1",
                "tool": "createFile",
                "args": {"path": str(file1), "content": "Content One", "overwrite": True},
            },
            {
                "id": "s2",
                "tool": "readFile",
                "args": {"path": str(file1)},
                "unverified_ok": True,  # readFile does not have verification envelope
            },
            {
                "id": "s3",
                "tool": "createFile",
                "args": {"path": str(file2), "content": "Content Two", "overwrite": True},
            },
        ],
    }

    result = execute_work(plan, authorized=True)

    assert result["overall_status"] == OUTCOME_VERIFIED_SUCCESS
    assert len(result["completed_steps"]) == 3
    assert result["failed_step"] is None
    assert len(result["skipped_steps"]) == 0

    assert file1.exists() and file1.read_text(encoding="utf-8") == "Content One"
    assert file2.exists() and file2.read_text(encoding="utf-8") == "Content Two"


def test_real_multi_domain_failure_stops_subsequent_steps(tmp_path: Path) -> None:
    """Execute a plan where Step 1 succeeds, Step 2 fails verification, Step 3 never runs."""
    state_cache.clear()

    file1 = tmp_path / "step1_success.txt"
    file3 = tmp_path / "step3_should_not_exist.txt"

    # Mock createFile verification failure on the second step
    original_create = None

    plan = {
        "goal": "Demonstrate bounded stopping on verification failure",
        "steps": [
            {
                "id": "step-1",
                "tool": "createFile",
                "args": {"path": str(file1), "content": "Valid step", "overwrite": True},
            },
            {
                "id": "step-2",
                "tool": "runTerminalCommand",
                "args": {"command": "invalid_probe_command_error_guaranteed_xyz"},
            },
            {
                "id": "step-3",
                "tool": "createFile",
                "args": {"path": str(file3), "content": "Should not run", "overwrite": True},
            },
        ],
    }

    result = execute_work(plan, authorized=True)

    # Step 1 succeeded
    assert result["completed_steps"][0]["step_id"] == "step-1"
    assert result["completed_steps"][0]["status"] == STEP_SUCCESS
    assert file1.exists()

    # Step 2 failed
    assert result["completed_steps"][1]["step_id"] == "step-2"
    assert result["completed_steps"][1]["status"] == STEP_FAILURE
    assert result["failed_step"]["step_id"] == "step-2"

    # Step 3 skipped and file was never created
    assert result["skipped_steps"] == ["step-3"]
    assert not file3.exists()

    # Overall outcome is verified failure
    assert result["overall_status"] == OUTCOME_VERIFIED_FAILURE


def test_multi_step_with_closed_loop_recovery(tmp_path: Path) -> None:
    """Demonstrate a multi-step plan where Step 1 recovers via S5 and Step 2 succeeds."""
    state_cache.clear()

    target_file = tmp_path / "post_recovery.txt"
    app_launch_calls = 0

    def mock_app_verify(spec, timeout_s=3.0, interval_s=0.5):
        nonlocal app_launch_calls
        app_launch_calls += 1
        if app_launch_calls == 1:
            return {
                "status": "VERIFIED_FAILURE",
                "method": "process_image_check",
                "image": "notepad.exe",
                "detail": "Simulated initial launch timeout.",
            }
        return {
            "status": "VERIFIED_SUCCESS",
            "method": "process_image_check",
            "image": "notepad.exe",
            "detail": "Process found on S5 recovery relaunch.",
        }

    with patch("agent.tools.applications.get_backend"), patch("agent.tools.applications._verify_application_launched", side_effect=mock_app_verify):
        plan = {
            "goal": "Recover app launch and create file",
            "steps": [
                {
                    "id": "step-1",
                    "tool": "openApplication",
                    "args": {"name": "notepad"},
                },
                {
                    "id": "step-2",
                    "tool": "createFile",
                    "args": {"path": str(target_file), "content": "Recovered work success.", "overwrite": True},
                },
            ],
        }

        result = execute_work(plan, authorized=True)

        assert result["overall_status"] == OUTCOME_VERIFIED_SUCCESS
        assert len(result["completed_steps"]) == 2
        assert result["completed_steps"][0]["status"] == STEP_RECOVERED
        assert result["completed_steps"][1]["status"] == STEP_SUCCESS
        assert target_file.exists()
