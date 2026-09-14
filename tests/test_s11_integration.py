"""
S11 Integration Tests:
Verifies live HTTP dispatch of step events from Python agent to local listener,
validating payload structure, ordering, and resilience.
"""

import http.server
import json
import threading
from unittest.mock import patch

import pytest

from agent.server import make_http_step_callback
from agent.work import execute_work, OUTCOME_VERIFIED_SUCCESS


class MockTelemetryHandler(http.server.BaseHTTPRequestHandler):
    received_events = []

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body.decode("utf-8"))
        MockTelemetryHandler.received_events.append(data)
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, format, *args):
        pass  # Quiet logging


@pytest.fixture
def mock_server():
    MockTelemetryHandler.received_events = []
    server = http.server.HTTPServer(("127.0.0.1", 0), MockTelemetryHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/internal/step-event"
    server.shutdown()
    server.server_close()


def test_live_http_step_event_stream(mock_server):
    """Verify that execute_work streams events over real HTTP callbacks to a listener."""
    callback = make_http_step_callback(mock_server, operation_id="test-op-123")

    plan = {
        "goal": "Integration test multi-step streaming",
        "steps": [
            {"id": "step_a", "tool": "mock_tool_a", "args": {"key": "val1"}},
            {"id": "step_b", "tool": "mock_tool_b", "args": {"key": "val2"}},
        ]
    }

    mock_resp_a = {
        "status": "VERIFIED_SUCCESS",
        "verification": {"status": "VERIFIED_SUCCESS", "detail": "Step A verified"}
    }
    mock_resp_b = {
        "status": "VERIFIED_SUCCESS",
        "verification": {"status": "VERIFIED_SUCCESS", "detail": "Step B verified"}
    }

    with patch.dict("agent.work.TOOLS", {
        "mock_tool_a": lambda args: mock_resp_a,
        "mock_tool_b": lambda args: mock_resp_b,
    }):
        result = execute_work(plan, authorized=True, step_callback=callback)

    assert result["overall_status"] == OUTCOME_VERIFIED_SUCCESS
    
    events = MockTelemetryHandler.received_events
    assert len(events) == 4

    # 1. Step A Started
    assert events[0]["event"] == "work_step_started"
    assert events[0]["operation_id"] == "test-op-123"
    assert events[0]["tool"] == "mock_tool_a"
    assert events[0]["payload"]["step_id"] == "step_a"
    assert events[0]["payload"]["step_index"] == 0
    assert events[0]["payload"]["total_steps"] == 2

    # 2. Step A Completed
    assert events[1]["event"] == "work_step_completed"
    assert events[1]["state"] == "VERIFIED_SUCCESS"
    assert events[1]["payload"]["step_id"] == "step_a"

    # 3. Step B Started
    assert events[2]["event"] == "work_step_started"
    assert events[2]["payload"]["step_index"] == 1

    # 4. Step B Completed
    assert events[3]["event"] == "work_step_completed"
    assert events[3]["state"] == "VERIFIED_SUCCESS"


def test_live_http_step_event_unreachable_endpoint_does_not_fail_work():
    """Verify that if the HTTP telemetry server is down/unreachable, work continues safely."""
    dead_url = "http://127.0.0.1:59999/internal/step-event"
    callback = make_http_step_callback(dead_url, operation_id="dead-test-op")

    plan = {
        "goal": "Test dead endpoint isolation",
        "steps": [
            {"id": "step_isolated", "tool": "mock_tool", "args": {}},
        ]
    }

    mock_resp = {
        "status": "VERIFIED_SUCCESS",
        "verification": {"status": "VERIFIED_SUCCESS", "detail": "Step OK"}
    }

    with patch.dict("agent.work.TOOLS", {"mock_tool": lambda args: mock_resp}):
        result = execute_work(plan, authorized=True, step_callback=callback)

    # Must complete with success despite network failure
    assert result["overall_status"] == OUTCOME_VERIFIED_SUCCESS
    assert len(result["completed_steps"]) == 1
