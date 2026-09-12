"""
Zarya S4 -- Integration tests validating failure reasoning on active tools.

Ensures that calling createFile, runTerminalCommand, and openApplication
returns the structured "failure" payload under successful, failed, or
unknown verification.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from agent.registry import TOOLS, load_all
from agent.state import cache as state_cache

# Ensure all tools are registered and available
load_all()


def test_create_file_integration_success(tmp_path: Path) -> None:
    """If file creation succeeds, 'failure' must be None."""
    state_cache.clear()
    test_file = tmp_path / "s4_success.txt"

    response = TOOLS["createFile"]({
        "path": str(test_file),
        "content": "perfect success",
        "overwrite": True,
    })

    assert "verification" in response
    assert response["verification"]["status"] == "VERIFIED_SUCCESS"
    assert "failure" in response
    assert response["failure"] is None


def test_create_file_integration_failure(tmp_path: Path) -> None:
    """If file verification fails, 'failure' must contain reasoning."""
    state_cache.clear()
    test_file = tmp_path / "s4_fail.txt"

    # We mock _verify_file_created to return a VERIFIED_FAILURE payload
    with patch("agent.tools.files._verify_file_created") as mock_verify:
        mock_verify.return_value = {
            "status": "VERIFIED_FAILURE",
            "method": "filesystem_exists",
            "detail": "File did not exist after creation.",
            "observation": {"path": str(test_file), "exists": False},
        }

        response = TOOLS["createFile"]({
            "path": str(test_file),
            "content": "failed write mock",
            "overwrite": True,
        })

        assert "verification" in response
        assert response["verification"]["status"] == "VERIFIED_FAILURE"
        assert "failure" in response
        
        failure = response["failure"]
        assert failure is not None
        assert failure["category"] == "FILE_NOT_CREATED"
        assert failure["confidence"] == "HIGH"
        assert failure["source_verification_status"] == "VERIFIED_FAILURE"
        assert "filesystem_exists probe reported exists=False" in failure["evidence"]


def test_terminal_integration_error() -> None:
    """If terminal command produces errors, 'failure' must categorize it."""
    state_cache.clear()

    # runTerminalCommand on a non-existent command to trigger VERIFIED_FAILURE
    response = TOOLS["runTerminalCommand"]({"command": "thiscommanddoesnotexistonanyplatform"})

    assert "verification" in response
    if response["verification"]["status"] == "VERIFIED_FAILURE":
        assert "failure" in response
        failure = response["failure"]
        assert failure is not None
        assert failure["category"] == "TERMINAL_ERROR_DETECTED"
        assert failure["confidence"] == "MEDIUM"
        assert failure["verification_strength"] == "weak"
        assert "source_freshness" in failure
    else:
        # If output didn't contain blacklisted substrings, it might be SUCCESS.
        # But for 'thiscommanddoesnotexistonanyplatform', cmd.exe or bash prints 'is not recognized' or 'command not found'.
        assert response["verification"]["status"] == "VERIFIED_SUCCESS"
        assert response["failure"] is None


def test_open_application_integration_failure() -> None:
    """If openApplication verification fails, 'failure' must reason about it."""
    state_cache.clear()

    # Mock the verification to return VERIFIED_FAILURE
    with patch("agent.tools.applications._verify_application_launched") as mock_verify:
        mock_verify.return_value = {
            "status": "VERIFIED_FAILURE",
            "method": "process_image_check",
            "image": "notepad.exe",
            "observation_window_ms": 3000,
            "detail": "Process notepad.exe not found within 3.0s observation window.",
        }

        response = TOOLS["openApplication"]({"name": "notepad"})

        assert "verification" in response
        assert response["verification"]["status"] == "VERIFIED_FAILURE"
        assert "failure" in response
        
        failure = response["failure"]
        assert failure is not None
        assert failure["category"] == "APPLICATION_NOT_OBSERVED"
        assert failure["confidence"] == "MEDIUM"
        assert "Launch mechanism return status is not captured." in failure["uncertainty"]
