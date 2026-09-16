# S17 — Device Identity, Registry, Deterministic Resolver & S16 Coexistence Tests
# Baseline: v0.16.0 (331a91c)

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime, timezone
import pytest

from agent.artifacts import ActiveComputerContext, ArtifactIdentity
from agent.context.device import (
    DeviceIdentity,
    DeviceRegistry,
    DeviceType,
    Platform,
    TrustState,
    DeviceResolutionStatus,
    DeviceResolutionResult,
    resolve_device_reference,
)
from agent.context.resolver import (
    resolve_context_reference,
    resolve_compound_intent,
    CompoundResolutionResult,
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
        assert dev.has_capability("ARTIFACT_TRANSFER")
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


class TestDeviceResolverGoldenScenarios:
    """Golden scenarios explicitly mandated by S17 Engineering Brief Section 22."""

    def test_golden_1_device_resolution(self):
        """Golden 1: 'my laptop' resolves deterministically to the single laptop."""
        reg = DeviceRegistry()
        reg.register(DeviceIdentity("dev-laptop-01", "My Laptop", DeviceType.LAPTOP, Platform.WINDOWS))
        
        res = resolve_device_reference("my laptop", reg)
        assert res.status == DeviceResolutionStatus.RESOLVED
        assert res.is_resolved
        assert res.device is not None
        assert res.device.device_id == "dev-laptop-01"

    def test_golden_2_multiple_matching_devices_ambiguous(self):
        """Golden 2: 'the laptop' with 2 laptops produces AMBIGUOUS, never guessing."""
        reg = DeviceRegistry()
        reg.register(DeviceIdentity("dev-laptop-01", "My Laptop", DeviceType.LAPTOP, Platform.WINDOWS))
        reg.register(DeviceIdentity("dev-laptop-02", "Office Laptop", DeviceType.LAPTOP, Platform.MACOS))

        res = resolve_device_reference("the laptop", reg)
        assert res.status == DeviceResolutionStatus.AMBIGUOUS
        assert not res.is_resolved
        assert res.device is None
        assert len(res.candidate_devices) == 2
        assert {d.device_id for d in res.candidate_devices} == {"dev-laptop-01", "dev-laptop-02"}

    def test_golden_3_unknown_device_not_found(self):
        """Golden 3: 'my quantum server' returns NOT_FOUND with zero guessing."""
        reg = DeviceRegistry()
        reg.register(DeviceIdentity("dev-laptop-01", "My Laptop", DeviceType.LAPTOP, Platform.WINDOWS))

        res = resolve_device_reference("my quantum server", reg)
        assert res.status == DeviceResolutionStatus.NOT_FOUND
        assert not res.is_resolved
        assert res.device is None
        assert len(res.candidate_devices) == 0

    def test_golden_4_known_but_unavailable(self):
        """Golden 4: 'my laptop' when is_available=False returns UNAVAILABLE."""
        reg = DeviceRegistry()
        reg.register(DeviceIdentity("dev-laptop-01", "My Laptop", DeviceType.LAPTOP, Platform.WINDOWS, is_available=False))

        res = resolve_device_reference("my laptop", reg)
        assert res.status == DeviceResolutionStatus.UNAVAILABLE
        assert not res.is_resolved
        assert res.device is not None
        assert res.device.device_id == "dev-laptop-01"
        assert res.device.is_available is False

    def test_golden_5_trust_separation(self):
        """Golden 5: Untrusted device resolves, but trust_state remains UNTRUSTED. Context != Authorization."""
        reg = DeviceRegistry()
        reg.register(DeviceIdentity("dev-phone-01", "My Phone", DeviceType.MOBILE, Platform.ANDROID, trust_state=TrustState.UNTRUSTED))

        res = resolve_device_reference("my phone", reg)
        assert res.status == DeviceResolutionStatus.RESOLVED
        assert res.device is not None
        assert res.device.trust_state == TrustState.UNTRUSTED
        assert not res.device.is_trusted()

    def test_explicit_device_id_resolution(self):
        """Explicit device IDs resolve immediately."""
        reg = DeviceRegistry()
        reg.register(DeviceIdentity("dev-7e3-node", "Custom Workstation", DeviceType.DESKTOP, Platform.LINUX))

        res = resolve_device_reference("dev-7e3-node", reg)
        assert res.status == DeviceResolutionStatus.RESOLVED
        assert res.device.device_id == "dev-7e3-node"

    def test_relative_reference_with_caller_exclusion(self):
        """'that computer' resolves when exactly one other computer exists."""
        reg = DeviceRegistry()
        reg.register(DeviceIdentity("dev-this-pc", "Current Desktop", DeviceType.DESKTOP, Platform.WINDOWS))
        reg.register(DeviceIdentity("dev-remote-laptop", "Living Room Laptop", DeviceType.LAPTOP, Platform.WINDOWS))

        res = resolve_device_reference("that computer", reg, caller_device_id="dev-this-pc")
        assert res.status == DeviceResolutionStatus.RESOLVED
        assert res.device.device_id == "dev-remote-laptop"

    def test_empty_and_whitespace_reference(self):
        reg = DeviceRegistry()
        assert resolve_device_reference("", reg).status == DeviceResolutionStatus.NOT_FOUND
        assert resolve_device_reference("   ", reg).status == DeviceResolutionStatus.NOT_FOUND

    def test_action_prefix_stripping(self):
        """'send this to my laptop' correctly isolates 'my laptop'."""
        reg = DeviceRegistry()
        reg.register(DeviceIdentity("dev-lap", "Personal Laptop", DeviceType.LAPTOP, Platform.MACOS))

        res = resolve_device_reference("send this to my laptop", reg)
        assert res.status == DeviceResolutionStatus.RESOLVED
        assert res.device.device_id == "dev-lap"

    def test_golden_6_existing_artifact_plus_device(self):
        """Golden 6: 'send this document to my laptop' resolves artifact via S16 and device via S17.
        
        Zero actual transport occurs. S16 and S17 compose seamlessly.
        """
        # S16 Context Setup with an active document artifact
        ctx = ActiveComputerContext()
        doc_art = ArtifactIdentity.create_file_artifact(
            "C:\\Users\\ragha\\Documents\\report.docx",
            source_operation="createFile",
            verification_status="VERIFIED_SUCCESS",
        )
        ctx.record_artifact(doc_art)
        # Mock desktop observation as fresh so S16 resolver resolves CURRENT_DOCUMENT
        ctx._desktop_freshness = datetime.now(timezone.utc).isoformat()

        # S17 Device Registry Setup
        reg = DeviceRegistry()
        reg.register(DeviceIdentity(
            device_id="dev-laptop-01",
            display_name="My Laptop",
            device_type=DeviceType.LAPTOP,
            platform=Platform.WINDOWS,
            capabilities=frozenset(["artifact_transfer"]),
            trust_state=TrustState.TRUSTED,
        ))

        # Perform compound resolution
        compound = resolve_compound_intent(
            "send this document to my laptop",
            context=ctx,
            registry=reg,
        )

        assert compound.is_fully_resolved
        # 1. Artifact verified via S16 logic
        assert compound.artifact_result is not None
        assert compound.artifact_result.status == "RESOLVED"
        assert compound.artifact_result.target is not None
        assert "report.docx" in compound.artifact_result.target

        # 2. Device verified via S17 logic
        assert compound.device_result is not None
        assert compound.device_result.is_resolved
        assert compound.device_result.device.device_id == "dev-laptop-01"
        assert compound.device_result.device.display_name == "My Laptop"
        assert compound.device_result.device.is_trusted()
