"""
S11: Step Event Emission & Failure Isolation Unit Tests.
"""

import pytest
from unittest.mock import MagicMock, patch
from agent.work import (
    execute_work,
    OUTCOME_VERIFIED_SUCCESS,
    OUTCOME_VERIFIED_FAILURE,
    OUTCOME_UNKNOWN,
)

def test_step_events_emitted_in_order():
    """Verify that work_step_started and work_step_completed are emitted sequentially with authoritative data."""
    events = []

    def callback(evt):
        events.append(evt)

    plan = {
        "goal": "Test sequential step events",
        "steps": [
            {"id": "step_1", "tool": "mock_tool_1", "args": {"val": 1}},
            {"id": "step_2", "tool": "mock_tool_2", "args": {"val": 2}},
        ]
    }

    mock_resp_1 = {
        "status": "VERIFIED_SUCCESS",
        "verification": {"status": "VERIFIED_SUCCESS", "detail": "Step 1 verified"}
    }
    mock_resp_2 = {
        "status": "VERIFIED_SUCCESS",
        "verification": {"status": "VERIFIED_SUCCESS", "detail": "Step 2 verified"}
    }

    with patch.dict("agent.work.TOOLS", {
        "mock_tool_1": lambda args: mock_resp_1,
        "mock_tool_2": lambda args: mock_resp_2,
    }):
        result = execute_work(plan, authorized=True, step_callback=callback)

    assert result["overall_status"] == OUTCOME_VERIFIED_SUCCESS
    assert len(events) == 4

    # Step 1 Started
    assert events[0]["event"] == "work_step_started"
    assert events[0]["step_id"] == "step_1"
    assert events[0]["tool"] == "mock_tool_1"
    assert events[0]["step_index"] == 0
    assert events[0]["total_steps"] == 2
    assert events[0]["state"] == "WORKING"

    # Step 1 Completed
    assert events[1]["event"] == "work_step_completed"
    assert events[1]["step_id"] == "step_1"
    assert events[1]["state"] == "VERIFIED_SUCCESS"

    # Step 2 Started
    assert events[2]["event"] == "work_step_started"
    assert events[2]["step_id"] == "step_2"
    assert events[2]["step_index"] == 1
    assert events[2]["total_steps"] == 2

    # Step 2 Completed
    assert events[3]["event"] == "work_step_completed"
    assert events[3]["step_id"] == "step_2"
    assert events[3]["state"] == "VERIFIED_SUCCESS"


def test_step_failure_event_and_halt():
    """Verify that a failing step emits VERIFIED_FAILURE and remaining steps are not executed."""
    events = []

    def callback(evt):
        events.append(evt)

    plan = {
        "goal": "Test failure step event",
        "steps": [
            {"id": "step_1", "tool": "mock_tool_1", "args": {}},
            {"id": "step_2", "tool": "mock_tool_2", "args": {}},
        ]
    }

    mock_fail_resp = {
        "status": "VERIFIED_FAILURE",
        "verification": {"status": "VERIFIED_FAILURE", "detail": "Assertion failed"}
    }

    with patch.dict("agent.work.TOOLS", {
        "mock_tool_1": lambda args: mock_fail_resp,
        "mock_tool_2": lambda args: {"status": "VERIFIED_SUCCESS"},
    }):
        result = execute_work(plan, authorized=True, step_callback=callback)

    assert result["overall_status"] == OUTCOME_VERIFIED_FAILURE
    assert len(events) == 2  # step_1 started and completed only

    assert events[0]["event"] == "work_step_started"
    assert events[0]["step_id"] == "step_1"

    assert events[1]["event"] == "work_step_completed"
    assert events[1]["step_id"] == "step_1"
    assert events[1]["state"] == "VERIFIED_FAILURE"
    assert events[1]["payload"]["detail"] == "Assertion failed"


def test_step_unknown_event_preservation():
    """Verify that UNKNOWN verification is faithfully emitted without coercion."""
    events = []

    def callback(evt):
        events.append(evt)

    plan = {
        "goal": "Test unknown step event",
        "steps": [
            {"id": "step_1", "tool": "mock_tool_1", "args": {}},
        ]
    }

    mock_unknown_resp = {
        "status": "UNKNOWN",
        "verification": {"status": "UNKNOWN", "detail": "Could not inspect external state"}
    }

    with patch.dict("agent.work.TOOLS", {
        "mock_tool_1": lambda args: mock_unknown_resp,
    }):
        result = execute_work(plan, authorized=True, step_callback=callback)

    assert result["overall_status"] == OUTCOME_UNKNOWN
    assert len(events) == 2
    assert events[1]["event"] == "work_step_completed"
    assert events[1]["state"] == "UNKNOWN"
    assert events[1]["payload"]["status"] == "UNKNOWN"


def test_callback_failure_isolation():
    """Verify that if the callback throws an exception, execution continues unaffected."""
    def broken_callback(evt):
        raise RuntimeError("Callback network timeout or crash!")

    plan = {
        "goal": "Test failure isolation",
        "steps": [
            {"id": "step_1", "tool": "mock_tool_1", "args": {}},
        ]
    }

    mock_resp = {
        "status": "VERIFIED_SUCCESS",
        "verification": {"status": "VERIFIED_SUCCESS", "detail": "OK"}
    }

    with patch.dict("agent.work.TOOLS", {"mock_tool_1": lambda args: mock_resp}):
        result = execute_work(plan, authorized=True, step_callback=broken_callback)

    # Work must succeed despite the callback throwing
    assert result["overall_status"] == OUTCOME_VERIFIED_SUCCESS
    assert len(result["completed_steps"]) == 1
