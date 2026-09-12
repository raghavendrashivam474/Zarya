"""
Zarya S5: Cross-Domain Closed-Loop Recovery Integration Tests (Hardened).

Validates that real tool invocations across applications, files, and terminal:
1. Include the additive "recovery" payload.
2. Execute closed-loop recovery for authorized application launch failures.
3. Keep filesystem and terminal failures as NOT_ELIGIBLE for recovery in S5.
4. Preserve the original failure reasoning without overwriting.
5. Correctly transition from VERIFIED_FAILURE -> RECOVERED upon successful relaunch.
"""

from __future__ import annotations

from pathlib import Path
import pytest
from unittest.mock import patch

from agent.registry import TOOLS, load_all
from agent.state import cache as state_cache
from agent.recovery import RECOVERED, FAILED, NOT_ELIGIBLE

load_all()


def test_create_file_integration_success_recovery_not_eligible(tmp_path: Path) -> None:
    """When createFile succeeds on the first try, recovery is NOT_ELIGIBLE."""
    state_cache.clear()
    test_file = tmp_path / "s5_first_try_success.txt"

    response = TOOLS["createFile"]({
        "path": str(test_file),
        "content": "first try success",
        "overwrite": True,
    })

    assert response["verification"]["status"] == "VERIFIED_SUCCESS"
    assert response["failure"] is None
    assert "recovery" in response
    assert response["recovery"]["status"] == NOT_ELIGIBLE
    assert response["recovery"]["attempts"] == 0


def test_create_file_failure_is_not_eligible_for_recovery_in_s5(tmp_path: Path) -> None:
    """Filesystem creation failure must NOT trigger automatic recovery in S5 (deferred)."""
    state_cache.clear()
    test_file = tmp_path / "s5_no_file_recovery.txt"

    with patch("agent.tools.files._verify_file_created") as mock_verify:
        mock_verify.return_value = {
            "status": "VERIFIED_FAILURE",
            "method": "filesystem_exists",
            "detail": "File did not exist after creation.",
            "observation": {"path": str(test_file), "exists": False},
        }

        response = TOOLS["createFile"]({
            "path": str(test_file),
            "content": "test data",
            "overwrite": True,
        })

        # Original failure reasoning is preserved
        assert response["verification"]["status"] == "VERIFIED_FAILURE"
        assert response["failure"] is not None
        assert response["failure"]["category"] == "FILE_NOT_CREATED"

        # Recovery is NOT_ELIGIBLE per S5 policy
        assert "recovery" in response
        assert response["recovery"]["status"] == NOT_ELIGIBLE
        assert response["recovery"]["attempts"] == 0


def test_open_application_closed_loop_recovery_success() -> None:
    """When openApplication fails initially, closed-loop relaunch succeeds."""
    state_cache.clear()

    call_count = 0

    def mock_verify_app(spec, timeout_s=3.0, interval_s=0.5):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "status": "VERIFIED_FAILURE",
                "method": "process_image_check",
                "image": "notepad.exe",
                "detail": "Process not found on first launch.",
            }
        return {
            "status": "VERIFIED_SUCCESS",
            "method": "process_image_check",
            "image": "notepad.exe",
            "detail": "Process found on recovery relaunch.",
        }

    with patch("agent.tools.applications.get_backend"), patch("agent.tools.applications._verify_application_launched", side_effect=mock_verify_app):
        response = TOOLS["openApplication"]({"name": "notepad"})

        # Original failure preserved
        assert response["verification"]["status"] == "VERIFIED_FAILURE"
        assert response["failure"]["category"] == "APPLICATION_NOT_OBSERVED"

        # Recovery verified success
        assert response["recovery"]["status"] == RECOVERED
        assert response["recovery"]["action"] == "RELAUNCH_APPLICATION"
        assert response["recovery"]["attempts"] == 1
        assert response["recovery"]["verification"]["status"] == "VERIFIED_SUCCESS"


def test_terminal_failure_is_not_eligible_for_recovery() -> None:
    """Terminal failures must never be automatically recovered."""
    state_cache.clear()

    response = TOOLS["runTerminalCommand"]({"command": "invalid_command_probe_s5"})

    assert "recovery" in response
    assert response["recovery"]["status"] == NOT_ELIGIBLE
    assert response["recovery"]["attempts"] == 0
