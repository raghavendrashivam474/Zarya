"""EIP-1 Security and Negative Tests.

Verifies that the ecosystem boundary correctly rejects:
- Missing or invalid authentication
- Arbitrary code execution attempts
- Malformed requests
- Unsupported protocol versions
- All dangerous internal tools
"""

import pytest
from fastapi.testclient import TestClient
from agent.server import app
from agent.ecosystem.authorization import get_token

client = TestClient(app)
TOKEN = get_token()
HEADERS = {"X-Ecosystem-Token": TOKEN}


class TestAuthenticationEnforcement:
    """Every endpoint except /auth-info MUST reject unauthenticated requests."""

    ENDPOINTS_REQUIRING_AUTH = [
        ("GET", "/ecosystem/v1/identity"),
        ("GET", "/ecosystem/v1/capabilities"),
        ("GET", "/ecosystem/v1/status"),
        ("GET", "/ecosystem/v1/protocol"),
    ]

    @pytest.mark.parametrize("method,path", ENDPOINTS_REQUIRING_AUTH)
    def test_missing_token_returns_401(self, method, path):
        if method == "GET":
            resp = client.get(path)
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"]["code"] == "UNAUTHORIZED"

    @pytest.mark.parametrize("method,path", ENDPOINTS_REQUIRING_AUTH)
    def test_wrong_token_returns_401(self, method, path):
        bad_headers = {"X-Ecosystem-Token": "definitely-wrong-token"}
        if method == "GET":
            resp = client.get(path, headers=bad_headers)
        assert resp.status_code == 401

    @pytest.mark.parametrize("method,path", ENDPOINTS_REQUIRING_AUTH)
    def test_empty_token_returns_401(self, method, path):
        bad_headers = {"X-Ecosystem-Token": ""}
        if method == "GET":
            resp = client.get(path, headers=bad_headers)
        assert resp.status_code == 401

    def test_execute_without_auth_returns_401(self):
        resp = client.post(
            "/ecosystem/v1/work/execute",
            json={"tool": "getWeather", "args": {}},
        )
        assert resp.status_code == 401


class TestArbitraryExecutionPrevention:
    """The boundary MUST NOT allow arbitrary code, shell, or method execution."""

    DANGEROUS_PAYLOADS = [
        {"tool": "runTerminalCommand", "args": {"command": "whoami"}},
        {"tool": "runPythonScript", "args": {"code": "import os; os.system('dir')"}},
        {"tool": "osType", "args": {"keys": "ctrl+c"}},
        {"tool": "osPress", "args": {"key": "enter"}},
        {"tool": "osClick", "args": {"x": 100, "y": 200}},
        {"tool": "shutdownElysia", "args": {}},
        {"tool": "executePowerAction", "args": {"action": "shutdown"}},
        {"tool": "requestTerminalAction", "args": {"command": "rm -rf /"}},
        {"tool": "provideSudoPassword", "args": {"password": "root"}},
    ]

    @pytest.mark.parametrize("payload", DANGEROUS_PAYLOADS)
    def test_dangerous_tool_rejected(self, payload):
        resp = client.post(
            "/ecosystem/v1/work/execute",
            json=payload,
            headers=HEADERS,
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["error"]["code"] == "TOOL_NOT_ALLOWED"

    def test_no_python_execution_vector(self):
        """Ensure there is no generic 'python' or 'eval' endpoint."""
        for endpoint in ["/ecosystem/v1/eval", "/ecosystem/v1/exec", "/ecosystem/v1/run"]:
            resp = client.post(endpoint, json={"code": "1+1"}, headers=HEADERS)
            assert resp.status_code in (404, 405)

    def test_no_shell_execution_vector(self):
        for endpoint in ["/ecosystem/v1/shell", "/ecosystem/v1/cmd"]:
            resp = client.post(endpoint, json={"cmd": "dir"}, headers=HEADERS)
            assert resp.status_code in (404, 405)


class TestMalformedRequests:
    def test_execute_missing_tool_field(self):
        resp = client.post(
            "/ecosystem/v1/work/execute",
            json={"args": {}},
            headers=HEADERS,
        )
        assert resp.status_code == 422  # Pydantic validation

    def test_execute_empty_body(self):
        resp = client.post(
            "/ecosystem/v1/work/execute",
            json={},
            headers=HEADERS,
        )
        assert resp.status_code == 422

    def test_execute_invalid_json(self):
        resp = client.post(
            "/ecosystem/v1/work/execute",
            content=b"not json",
            headers={**HEADERS, "Content-Type": "application/json"},
        )
        assert resp.status_code == 422

