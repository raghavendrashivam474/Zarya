# S17 — Device Identity Tests
# Baseline: v0.16.0 (331a91c)

import pytest
from agent.context.device import (
    DeviceIdentity,
    DeviceType,
    Platform,
    TrustState,
    DeviceResolutionStatus,
)


class TestDeviceModel:
    """Validates S17 DeviceIdentity model, enums, and invariants."""

    def test_minimal_device_creation(self):
        dev = DeviceIdentity(
            device_id="device-laptop-01",
            display_name="My Laptop",
        )
        assert dev.device_id == "device-laptop-01"
        assert dev.display_name == "My Laptop"
        assert dev.device_type == DeviceType.UNKNOWN
        assert dev.platform == Platform.UNKNOWN
        assert dev.trust_state == TrustState.UNKNOWN
        assert dev.capabilities == frozenset()
        assert dev.is_available is True
        assert not dev.is_trusted()

    def test_full_device_creation(self):
        dev = DeviceIdentity(
            device_id="device-pc-02",
            display_name="Office PC",
            device_type=DeviceType.DESKTOP,
            platform=Platform.WINDOWS,
            capabilities=frozenset(["artifact_transfer", "screen_share"]),
            trust_state=TrustState.TRUSTED,
            is_available=True,
            metadata={"location": "building-a"},
        )
        assert dev.device_type == DeviceType.DESKTOP
        assert dev.platform == Platform.WINDOWS
        assert dev.is_trusted()
        assert dev.has_capability("artifact_transfer")
        assert dev.has_capability("ARTIFACT_TRANSFER")  # case-insensitive
        assert not dev.has_capability("remote_exec")

    def test_string_coercion_for_enums(self):
        dev = DeviceIdentity(
            device_id="dev-03",
            display_name="Phone",
            device_type="mobile",
            platform="android",
            trust_state="trusted",
            capabilities=["artifact_transfer"],
        )
        assert dev.device_type == DeviceType.MOBILE
        assert dev.platform == Platform.ANDROID
        assert dev.trust_state == TrustState.TRUSTED
        assert "artifact_transfer" in dev.capabilities

    def test_unknown_enum_fallbacks(self):
        assert DeviceType.from_string("quantum_rig") == DeviceType.UNKNOWN
        assert Platform.from_string("freebsd") == Platform.UNKNOWN
        assert TrustState.from_string("super_trusted") == TrustState.UNKNOWN

    def test_empty_or_invalid_id_raises(self):
        with pytest.raises(ValueError):
            DeviceIdentity(device_id="", display_name="Laptop")
        with pytest.raises(ValueError):
            DeviceIdentity(device_id="   ", display_name="Laptop")

    def test_empty_or_invalid_name_raises(self):
        with pytest.raises(ValueError):
            DeviceIdentity(device_id="dev-1", display_name="")
        with pytest.raises(ValueError):
            DeviceIdentity(device_id="dev-1", display_name="  ")

    def test_serialization_roundtrip(self):
        dev = DeviceIdentity(
            device_id="device-mac-01",
            display_name="Work MacBook",
            device_type=DeviceType.LAPTOP,
            platform=Platform.MACOS,
            capabilities=frozenset(["artifact_transfer"]),
            trust_state=TrustState.TRUSTED,
            is_available=False,
            metadata={"env": "prod"},
        )
        d = dev.to_dict()
        assert d["device_id"] == "device-mac-01"
        assert d["device_type"] == "LAPTOP"
        assert d["platform"] == "MACOS"
        assert d["trust_state"] == "TRUSTED"
        assert d["is_available"] is False
        assert d["capabilities"] == ["artifact_transfer"]

        restored = DeviceIdentity.from_dict(d)
        assert restored == dev
        assert restored.is_available is False
        assert restored.is_trusted()

    def test_device_immutability(self):
        dev = DeviceIdentity(device_id="dev-1", display_name="Static")
        with pytest.raises(AttributeError):
            dev.display_name = "Changed"  # dataclass is frozen
