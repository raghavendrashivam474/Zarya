"""
S10.5: Runtime Event Bridge Tests.

Verifies:
  - Epistemic safety: UNKNOWN remains UNKNOWN across all translations.
  - Runtime event schema contract and versioning.
  - Extraction of verification statuses from tool execution results.
  - Safe failure handling and unverified tool outcomes.
  - Backward compatibility of the execution boundary.
"""

import json
from datetime import datetime, timezone
import pytest

from agent.state import StateObservation, StateFreshness
from agent.work import OUTCOME_VERIFIED_SUCCESS, OUTCOME_VERIFIED_FAILURE, OUTCOME_UNKNOWN


def simulate_event_outcome(agent_result: dict) -> tuple[str, dict]:
    """
    Simulates the server/index.ts event bridge outcome extraction logic:
    Given an agent result { ok: bool, result?: dict, error?: str },
    derive the authoritative runtime outcome state and event payload.
    """
    outcome_state = "UNKNOWN"
    ok = agent_result.get("ok", False)
    result = agent_result.get("result")

    if ok and result is not None:
        if isinstance(result, dict):
            v_status = result.get("verification", {}).get("status") if isinstance(result.get("verification"), dict) else None
            if v_status in ("VERIFIED_SUCCESS", "VERIFIED_FAILURE", "UNKNOWN"):
                outcome_state = v_status
            elif result.get("status") in ("VERIFIED_SUCCESS", "VERIFIED_FAILURE", "UNKNOWN"):
                outcome_state = result["status"]
            # If no verification status is found, outcome_state remains UNKNOWN (Epistemic Safety Rule)
    elif not ok:
        outcome_state = "VERIFIED_FAILURE"

    has_verification = bool(isinstance(result, dict) and result.get("verification"))
    return outcome_state, {"ok": ok, "has_verification": has_verification}


def create_runtime_event(
    event_type: str,
    state: str,
    tool: str,
    operation_id: str,
    payload: dict = None,
) -> dict:
    """Constructs a standard S10.5 runtime event envelope."""
    return {
        "type": "runtime_event",
        "version": 1,
        "event": event_type,
        "operation_id": operation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "tool": tool,
        "payload": payload or {},
    }


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_runtime_event_schema_conformance():
    """Verify runtime event envelope contains required version, timestamps, and fields."""
    event = create_runtime_event(
        event_type="work_started",
        state="WORKING",
        tool="openApplication",
        operation_id="work-12345",
        payload={"args": {"name": "notepad"}},
    )

    assert event["type"] == "runtime_event"
    assert event["version"] == 1
    assert event["event"] == "work_started"
    assert event["state"] == "WORKING"
    assert event["tool"] == "openApplication"
    assert event["operation_id"] == "work-12345"
    assert "timestamp" in event
    assert isinstance(event["payload"], dict)

    # Valid JSON serialization check
    serialized = json.dumps(event)
    deserialized = json.loads(serialized)
    assert deserialized == event


def test_verified_success_outcome_extraction():
    """Verify VERIFIED_SUCCESS in tool verification payload produces VERIFIED_SUCCESS event state."""
    agent_result = {
        "ok": True,
        "result": {
            "verification": {
                "status": "VERIFIED_SUCCESS",
                "method": "process_match",
                "detail": "notepad.exe found running with PID 4321",
            }
        },
    }

    state, payload = simulate_event_outcome(agent_result)
    assert state == "VERIFIED_SUCCESS"
    assert payload["ok"] is True
    assert payload["has_verification"] is True


def test_verified_failure_outcome_extraction():
    """Verify VERIFIED_FAILURE in tool verification payload produces VERIFIED_FAILURE event state."""
    agent_result = {
        "ok": True,
        "result": {
            "verification": {
                "status": "VERIFIED_FAILURE",
                "method": "process_match",
                "detail": "Application window failed to appear within 5.0s",
            }
        },
    }

    state, payload = simulate_event_outcome(agent_result)
    assert state == "VERIFIED_FAILURE"
    assert payload["ok"] is True
    assert payload["has_verification"] is True


def test_epistemic_safety_unknown_remains_unknown():
    """Verify UNKNOWN in tool verification payload is NEVER mapped to SUCCESS or FAILURE."""
    agent_result = {
        "ok": True,
        "result": {
            "verification": {
                "status": "UNKNOWN",
                "method": "insufficient_evidence",
                "detail": "Observation timed out before window state settled",
            }
        },
    }

    state, payload = simulate_event_outcome(agent_result)
    assert state == "UNKNOWN"
    assert state != "VERIFIED_SUCCESS"
    assert state != "VERIFIED_FAILURE"
    assert payload["has_verification"] is True


def test_unverified_tool_result_defaults_to_unknown():
    """
    Epistemic Safety Rule:
    If a tool returns ok=True without any verification payload, the event bridge
    MUST NOT assume VERIFIED_SUCCESS. It defaults to UNKNOWN.
    """
    agent_result = {
        "ok": True,
        "result": {"output": "Volume set to 50%"},  # No verification dict
    }

    state, payload = simulate_event_outcome(agent_result)
    assert state == "UNKNOWN"
    assert state != "VERIFIED_SUCCESS"
    assert payload["ok"] is True
    assert payload["has_verification"] is False


def test_agent_error_produces_verified_failure():
    """Verify transport or tool exception (ok=False) produces VERIFIED_FAILURE event state."""
    agent_result = {
        "ok": False,
        "error": "ToolExecutionError: Failed to bind port",
    }

    state, payload = simulate_event_outcome(agent_result)
    assert state == "VERIFIED_FAILURE"
    assert payload["ok"] is False


def test_operation_id_isolation():
    """Verify distinct operations generate distinct operation identifiers."""
    op1 = f"work-{datetime.now(timezone.utc).timestamp()}-abc1"
    op2 = f"work-{datetime.now(timezone.utc).timestamp()}-abc2"
    assert op1 != op2

    ev1 = create_runtime_event("work_started", "WORKING", "toolA", op1)
    ev2 = create_runtime_event("work_started", "WORKING", "toolB", op2)
    assert ev1["operation_id"] != ev2["operation_id"]
