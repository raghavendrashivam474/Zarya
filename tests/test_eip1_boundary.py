"""EIP-1 Boundary Tests.

Tests the HTTP endpoints using FastAPI's TestClient.
Verifies the full request/response cycle through the ecosystem boundary.
"""

import pytest
from fastapi.testclient import TestClient
from agent.server import app
from agent.ecosystem.authorization import get_token

client = TestClient(app)
TOKEN = get_token()
HEADERS = {"X-Ecosystem-Token": TOKEN}


class TestDiscoveryEndpoints:
    def test_auth_info_no_token_required(self):
        resp = client.get("/ecosystem/v1/auth-info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "header"
        assert "X-Ecosystem-Token" in data["header_name"]

    def test_identity_with_token(self):
        resp = client.get("/ecosystem/v1/identity", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["product"] == "zarya"
        assert "instance_id" in data
        assert data["protocol"] == "eip-1.0"

    def test_capabilities_with_token(self):
        resp = client.get("/ecosystem/v1/capabilities", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "capabilities" in data
        assert "allowed_tools" in data
        assert len(data["capabilities"]) >= 3

    def test_status_with_token(self):
        resp = client.get("/ecosystem/v1/status", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("READY", "BUSY")

    def test_protocol_with_token(self):
        resp = client.get("/ecosystem/v1/protocol", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == "eip-1.0"
        assert "eip-1.0" in data["supported"]


class TestWorkExecution:
    def test_execute_allowed_tool(self):
        """Execute a safe tool through the ecosystem boundary."""
        resp = client.post(
            "/ecosystem/v1/work/execute",
            json={"tool": "getWeather", "args": {"city": "Chennai"}},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool"] == "getWeather"
        assert "outcome" in data
        assert "verified" in data

    def test_execute_disallowed_tool_rejected(self):
        """Dangerous tools must be rejected at the boundary."""
        resp = client.post(
            "/ecosystem/v1/work/execute",
            json={"tool": "runTerminalCommand", "args": {"command": "dir"}},
            headers=HEADERS,
        )
        assert resp.status_code == 403
        data = resp.json()
        assert data["detail"]["error"]["code"] == "TOOL_NOT_ALLOWED"

    def test_execute_unknown_tool_rejected(self):
        resp = client.post(
            "/ecosystem/v1/work/execute",
            json={"tool": "nonExistentTool", "args": {}},
            headers=HEADERS,
        )
        assert resp.status_code == 403


class TestWorkStatus:
    def test_status_unknown_operation(self):
        resp = client.get(
            "/ecosystem/v1/work/status/nonexistent-op-id",
            headers=HEADERS,
        )
        assert resp.status_code == 404

