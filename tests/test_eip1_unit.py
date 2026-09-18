"""EIP-1 Unit Tests.

Tests each ecosystem module in isolation without starting the server.
"""

import pytest


class TestProtocol:
    def test_version_string(self):
        from agent.ecosystem.protocol import PROTOCOL_VERSION
        assert PROTOCOL_VERSION == "eip-1.0"

    def test_supported_versions(self):
        from agent.ecosystem.protocol import SUPPORTED_VERSIONS
        assert "eip-1.0" in SUPPORTED_VERSIONS

    def test_version_check_valid(self):
        from agent.ecosystem.protocol import is_version_supported
        assert is_version_supported("eip-1.0") is True

    def test_version_check_invalid(self):
        from agent.ecosystem.protocol import is_version_supported
        assert is_version_supported("eip-2.0") is False
        assert is_version_supported("") is False
        assert is_version_supported("garbage") is False


class TestIdentity:
    def test_instance_id_is_uuid(self):
        from agent.ecosystem.identity import get_instance_id
        import uuid
        uid = get_instance_id()
        uuid.UUID(uid)  # Raises ValueError if not a valid UUID

    def test_instance_id_stable_within_process(self):
        from agent.ecosystem.identity import get_instance_id
        assert get_instance_id() == get_instance_id()

    def test_identity_structure(self):
        from agent.ecosystem.identity import get_instance_identity
        ident = get_instance_identity()
        assert "instance_id" in ident
        assert "product" in ident
        assert ident["product"] == "zarya"
        assert "version" in ident
        assert "protocol" in ident
        assert ident["protocol"] == "eip-1.0"
        assert "platform" in ident
        assert "architecture" in ident

    def test_identity_with_no_device_registry(self):
        from agent.ecosystem.identity import get_instance_identity
        ident = get_instance_identity(device_registry=None)
        assert "device" not in ident


class TestCapabilities:
    def test_capabilities_not_empty(self):
        from agent.ecosystem.capabilities import get_capabilities
        caps = get_capabilities()
        assert len(caps) >= 3

    def test_capability_structure(self):
        from agent.ecosystem.capabilities import get_capabilities
        for cap in get_capabilities():
            assert "id" in cap
            assert "version" in cap
            assert "description" in cap
            assert "operations" in cap

    def test_allowed_tools_is_frozen(self):
        from agent.ecosystem.capabilities import ALLOWED_ECOSYSTEM_TOOLS
        assert isinstance(ALLOWED_ECOSYSTEM_TOOLS, frozenset)

    def test_allowed_tools_subset_of_all(self):
        from agent.ecosystem.capabilities import get_allowed_tools
        tools = get_allowed_tools()
        assert len(tools) > 0
        assert len(tools) < 20  # Must be a deliberate subset, not all 82

    def test_dangerous_tools_not_allowed(self):
        from agent.ecosystem.capabilities import is_tool_allowed
        dangerous = [
            "runTerminalCommand", "runPythonScript", "shutdownElysia",
            "osClick", "osPress", "osType", "requestTerminalAction",
            "executePowerAction", "provideSudoPassword",
        ]
        for tool in dangerous:
            assert is_tool_allowed(tool) is False, f"{tool} must NOT be allowed"

    def test_safe_tools_allowed(self):
        from agent.ecosystem.capabilities import is_tool_allowed
        assert is_tool_allowed("getWeather") is True
        assert is_tool_allowed("getNews") is True


class TestStatus:
    def test_all_lifecycle_states_mapped(self):
        from agent.ecosystem.status import project_lifecycle_status
        from agent.lifecycle import LifecycleStatus
        for status in LifecycleStatus:
            result = project_lifecycle_status(status)
            assert result in ("STARTING", "BUSY", "READY", "STOPPING", "UNAVAILABLE", "UNKNOWN")

    def test_running_is_busy(self):
        from agent.ecosystem.status import project_lifecycle_status
        from agent.lifecycle import LifecycleStatus
        assert project_lifecycle_status(LifecycleStatus.RUNNING) == "BUSY"

    def test_completed_is_ready(self):
        from agent.ecosystem.status import project_lifecycle_status
        from agent.lifecycle import LifecycleStatus
        assert project_lifecycle_status(LifecycleStatus.COMPLETED) == "READY"

    def test_string_input(self):
        from agent.ecosystem.status import project_lifecycle_status
        assert project_lifecycle_status("RUNNING") == "BUSY"
        assert project_lifecycle_status("INVALID_GARBAGE") == "UNKNOWN"

    def test_global_status_ready(self):
        from agent.ecosystem.status import get_global_status
        s = get_global_status(active_operation_count=0)
        assert s["status"] == "READY"
        assert s["active_operations"] == 0

    def test_global_status_busy(self):
        from agent.ecosystem.status import get_global_status
        s = get_global_status(active_operation_count=3)
        assert s["status"] == "BUSY"


class TestAuthorization:
    def test_token_generated(self):
        from agent.ecosystem.authorization import get_token
        token = get_token()
        assert isinstance(token, str)
        assert len(token) > 20

    def test_token_stable(self):
        from agent.ecosystem.authorization import get_token
        assert get_token() == get_token()

    def test_valid_token(self):
        from agent.ecosystem.authorization import get_token, validate_token
        assert validate_token(get_token()) is True

    def test_invalid_token(self):
        from agent.ecosystem.authorization import validate_token
        assert validate_token("wrong-token") is False
        assert validate_token("") is False
        assert validate_token(None) is False

    def test_timing_safe(self):
        """Token comparison uses secrets.compare_digest (constant-time)."""
        from agent.ecosystem.authorization import validate_token
        assert validate_token("a" * 100) is False


class TestErrors:
    def test_error_structure(self):
        from agent.ecosystem.errors import make_error, EcosystemErrorCode
        err = make_error(EcosystemErrorCode.UNAUTHORIZED, "test msg")
        assert "error" in err
        assert err["error"]["code"] == "UNAUTHORIZED"
        assert err["error"]["message"] == "test msg"

    def test_error_with_detail(self):
        from agent.ecosystem.errors import make_error, EcosystemErrorCode
        err = make_error(EcosystemErrorCode.TOOL_NOT_ALLOWED, "no", {"tool": "x"})
        assert err["error"]["detail"]["tool"] == "x"

    def test_http_status_mapping(self):
        from agent.ecosystem.errors import get_http_status, EcosystemErrorCode
        assert get_http_status(EcosystemErrorCode.UNAUTHORIZED) == 401
        assert get_http_status(EcosystemErrorCode.TOOL_NOT_ALLOWED) == 403
        assert get_http_status(EcosystemErrorCode.EXECUTION_FAILED) == 500

    def test_from_tool_error(self):
        from agent.ecosystem.errors import from_tool_error
        err = from_tool_error("something broke")
        assert err["error"]["code"] == "EXECUTION_FAILED"
        assert "something broke" in err["error"]["detail"]["tool_error"]
