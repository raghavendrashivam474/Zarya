"""
Integration tests for S3 state capture across active tool domains.
Ensures that calling existing tools correctly records state observations in the cache.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from agent.registry import TOOLS, load_all
from agent.state import cache as state_cache, StateDomain, StateFreshness

# Ensure all tools are registered and available
load_all()


def test_open_application_records_state() -> None:
    """Verify that openApplication records process state in cache."""
    state_cache.clear()

    # Dispatch openApplication directly from the TOOLS map
    # notepad launch will trigger tasklist which works on Windows or returns UNKNOWN on others
    response = TOOLS["openApplication"]({"name": "notepad"})

    assert "state" in response
    state_data = response["state"]
    assert state_data["domain"] == "application"
    assert state_data["subject"] == "notepad.exe"
    assert "running" in state_data["state"]

    # Retrieve from cache
    cached = state_cache.get("application", "notepad.exe")
    assert cached is not None
    assert cached.status == state_data["status"]
    assert cached.state["running"] == state_data["state"]["running"]
    assert cached.freshness == StateFreshness.CURRENT.value


def test_create_file_records_state(tmp_path: Path) -> None:
    """Verify that createFile records file state in cache."""
    state_cache.clear()

    test_file = tmp_path / "s3_test.txt"
    content = "Hello S3 State Model"

    response = TOOLS["createFile"]({
        "path": str(test_file),
        "content": content,
        "overwrite": True,
    })

    assert "state" in response
    state_data = response["state"]
    assert state_data["domain"] == "filesystem"
    assert state_data["subject"] == str(test_file)
    assert state_data["state"]["exists"] is True
    assert state_data["state"]["size_bytes"] == len(content)

    # Retrieve from cache
    cached = state_cache.get("filesystem", str(test_file))
    assert cached is not None
    assert cached.state["exists"] is True
    assert cached.state["size_bytes"] == len(content)


def test_run_terminal_command_records_state() -> None:
    """Verify that runTerminalCommand records execution state in cache."""
    state_cache.clear()

    command = "echo S3 Integration Test"
    response = TOOLS["runTerminalCommand"]({"command": command})

    assert "state" in response
    state_data = response["state"]
    assert state_data["domain"] == "terminal"
    assert state_data["subject"] == command
    assert state_data["state"]["executed"] is True

    # Retrieve from cache
    cached = state_cache.get("terminal", command)
    assert cached is not None
    assert cached.state["executed"] is True
    assert cached.state["has_output"] is True
