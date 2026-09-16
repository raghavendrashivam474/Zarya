# S17 — Device Identity & Registry Tests
# Baseline: v0.16.0 (331a91c)

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from agent.context.device import (
    DeviceIdentity,
    DeviceRegistry,
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
            dev.display_name = "Changed"


class TestDeviceRegistry:
    """Validates local thread-safe device registry operations."""

    @pytest.fixture
    def registry(self):
        reg = DeviceRegistry()
        reg.register(DeviceIdentity("dev-laptop", "My Laptop", DeviceType.LAPTOP, Platform.WINDOWS, trust_state=TrustState.TRUSTED))
        reg.register(DeviceIdentity("dev-phone", "My Phone", DeviceType.MOBILE, Platform.ANDROID, trust_state=TrustState.UNTRUSTED))
        reg.register(DeviceIdentity("dev-office-pc", "Office PC", DeviceType.DESKTOP, Platform.WINDOWS, trust_state=TrustState.TRUSTED, is_available=False))
        return reg

    def test_register_and_get(self, registry):
        assert len(registry) == 3
        assert "dev-laptop" in registry
        dev = registry.get("dev-laptop")
        assert dev is not None
        assert dev.display_name == "My Laptop"

    def test_unregister(self, registry):
        removed = registry.unregister("dev-phone")
        assert removed is not None
        assert removed.device_id == "dev-phone"
        assert len(registry) == 2
        assert registry.get("dev-phone") is None
        assert registry.unregister("non-existent") is None

    def test_get_by_name(self, registry):
        matches = registry.get_by_name("my laptop")
        assert len(matches) == 1
        assert matches[0].device_id == "dev-laptop"

        # Case sensitivity
        assert len(registry.get_by_name("my laptop", case_sensitive=True)) == 0
        assert len(registry.get_by_name("My Laptop", case_sensitive=True)) == 1

    def test_list_with_filters(self, registry):
        laptops = registry.list_devices(device_type=DeviceType.LAPTOP)
        assert len(laptops) == 1
        assert laptops[0].device_id == "dev-laptop"

        windows_devs = registry.list_devices(platform=Platform.WINDOWS)
        assert len(windows_devs) == 2

        available = registry.list_devices(only_available=True)
        assert len(available) == 2
        assert "dev-office-pc" not in [d.device_id for d in available]

        trusted = registry.list_devices(only_trusted=True)
        assert len(trusted) == 2
        assert "dev-phone" not in [d.device_id for d in trusted]

    def test_set_availability_and_trust(self, registry):
        updated = registry.set_availability("dev-office-pc", True)
        assert updated is not None
        assert updated.is_available is True
        assert registry.get("dev-office-pc").is_available is True

        updated_trust = registry.set_trust_state("dev-phone", TrustState.TRUSTED)
        assert updated_trust is not None
        assert updated_trust.is_trusted()

    def test_serialization_roundtrip(self, registry):
        data = registry.to_list()
        assert len(data) == 3
        restored = DeviceRegistry.from_list(data)
        assert len(restored) == 3
        assert restored.get("dev-laptop").display_name == "My Laptop"
