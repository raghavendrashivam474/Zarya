"""
S17 — Cross-Device Identity & Local Device Fabric
Baseline: v0.16.0 (331a91c)

Owns:
  - DeviceType, Platform, TrustState, DeviceResolutionStatus enums
  - DeviceIdentity dataclass
  - DeviceRegistry (local, thread-safe in-memory device store)
  - Model serialization and validation

Does NOT own:
  - Flux integration / PeerId / PathId (S18)
  - Network discovery / transport
  - Authorization enforcement
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Set, Union


class DeviceType(str, Enum):
    """Bounded device taxonomy."""
    DESKTOP = "DESKTOP"
    LAPTOP = "LAPTOP"
    MOBILE = "MOBILE"
    TABLET = "TABLET"
    SERVER = "SERVER"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_string(cls, val: Optional[str]) -> DeviceType:
        if not val:
            return cls.UNKNOWN
        clean = val.strip().upper()
        for member in cls:
            if member.value == clean:
                return member
        return cls.UNKNOWN


class Platform(str, Enum):
    """Bounded operating system / platform taxonomy."""
    WINDOWS = "WINDOWS"
    LINUX = "LINUX"
    MACOS = "MACOS"
    ANDROID = "ANDROID"
    IOS = "IOS"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_string(cls, val: Optional[str]) -> Platform:
        if not val:
            return cls.UNKNOWN
        clean = val.strip().upper()
        for member in cls:
            if member.value == clean:
                return member
        return cls.UNKNOWN


class TrustState(str, Enum):
    """Explicit trust boundary for logical devices."""
    UNKNOWN = "UNKNOWN"
    TRUSTED = "TRUSTED"
    UNTRUSTED = "UNTRUSTED"
    REVOKED = "REVOKED"

    @classmethod
    def from_string(cls, val: Optional[str]) -> TrustState:
        if not val:
            return cls.UNKNOWN
        clean = val.strip().upper()
        for member in cls:
            if member.value == clean:
                return member
        return cls.UNKNOWN


class DeviceResolutionStatus(str, Enum):
    """Outcome of deterministic device resolution."""
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class DeviceIdentity:
    """Logical device identity owned by Zarya.
    
    Explicitly independent of Flux PeerId and transport paths.
    """
    device_id: str
    display_name: str
    device_type: DeviceType = DeviceType.UNKNOWN
    platform: Platform = Platform.UNKNOWN
    capabilities: FrozenSet[str] = field(default_factory=frozenset)
    trust_state: TrustState = TrustState.UNKNOWN
    is_available: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    def __post_init__(self) -> None:
        if not self.device_id or not isinstance(self.device_id, str) or not self.device_id.strip():
            raise ValueError("device_id must be a non-empty string")
        if not self.display_name or not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("display_name must be a non-empty string")

        # Coerce strings to enums if passed directly
        if isinstance(self.device_type, str) and not isinstance(self.device_type, DeviceType):
            object.__setattr__(self, "device_type", DeviceType.from_string(self.device_type))
        if isinstance(self.platform, str) and not isinstance(self.platform, Platform):
            object.__setattr__(self, "platform", Platform.from_string(self.platform))
        if isinstance(self.trust_state, str) and not isinstance(self.trust_state, TrustState):
            object.__setattr__(self, "trust_state", TrustState.from_string(self.trust_state))
        if not isinstance(self.capabilities, frozenset):
            object.__setattr__(self, "capabilities", frozenset(self.capabilities))

    def has_capability(self, cap: str) -> bool:
        """Check if device advertises a specific capability."""
        return cap.strip().lower() in {c.lower() for c in self.capabilities}

    def is_trusted(self) -> bool:
        """Convenience check for explicit trust."""
        return self.trust_state == TrustState.TRUSTED

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic dictionary serialization."""
        return {
            "device_id": self.device_id,
            "display_name": self.display_name,
            "device_type": self.device_type.value,
            "platform": self.platform.value,
            "capabilities": sorted(list(self.capabilities)),
            "trust_state": self.trust_state.value,
            "is_available": self.is_available,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DeviceIdentity:
        """Construct DeviceIdentity from serialized data."""
        return cls(
            device_id=data["device_id"],
            display_name=data["display_name"],
            device_type=DeviceType.from_string(data.get("device_type")),
            platform=Platform.from_string(data.get("platform")),
            capabilities=frozenset(data.get("capabilities", [])),
            trust_state=TrustState.from_string(data.get("trust_state")),
            is_available=bool(data.get("is_available", True)),
            metadata=dict(data.get("metadata", {})),
        )


class DeviceRegistry:
    """Thread-safe in-memory registry of logical devices.
    
    Acts as the authoritative local source of known devices for Zarya.
    Does NOT perform network discovery.
    """

    def __init__(self) -> None:
        self._devices: Dict[str, DeviceIdentity] = {}
        self._lock = threading.RLock()

    def register(self, device: DeviceIdentity) -> None:
        """Register or update a device identity in the local registry."""
        if not isinstance(device, DeviceIdentity):
            raise TypeError("Expected DeviceIdentity instance")
        with self._lock:
            self._devices[device.device_id] = device

    def unregister(self, device_id: str) -> Optional[DeviceIdentity]:
        """Remove a device by its device_id. Returns the removed device or None."""
        if not device_id:
            return None
        with self._lock:
            return self._devices.pop(device_id, None)

    def get(self, device_id: str) -> Optional[DeviceIdentity]:
        """Lookup a device by device_id."""
        if not device_id:
            return None
        with self._lock:
            return self._devices.get(device_id)

    def get_by_name(self, display_name: str, case_sensitive: bool = False) -> List[DeviceIdentity]:
        """Find devices by display_name."""
        if not display_name or not display_name.strip():
            return []
        target = display_name if case_sensitive else display_name.strip().lower()
        with self._lock:
            matches = []
            for dev in self._devices.values():
                name = dev.display_name if case_sensitive else dev.display_name.strip().lower()
                if name == target:
                    matches.append(dev)
            return sorted(matches, key=lambda d: d.device_id)

    def list_devices(
        self,
        device_type: Optional[Union[DeviceType, str]] = None,
        platform: Optional[Union[Platform, str]] = None,
        only_available: bool = False,
        only_trusted: bool = False,
    ) -> List[DeviceIdentity]:
        """List devices matching optional filters, sorted deterministically by device_id."""
        target_type = DeviceType.from_string(device_type) if isinstance(device_type, str) else device_type
        target_plat = Platform.from_string(platform) if isinstance(platform, str) else platform

        with self._lock:
            results = []
            for dev in self._devices.values():
                if target_type is not None and dev.device_type != target_type:
                    continue
                if target_plat is not None and dev.platform != target_plat:
                    continue
                if only_available and not dev.is_available:
                    continue
                if only_trusted and not dev.is_trusted():
                    continue
                results.append(dev)
            return sorted(results, key=lambda d: d.device_id)

    def set_availability(self, device_id: str, is_available: bool) -> Optional[DeviceIdentity]:
        """Update a device's availability flag atomically."""
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return None
            updated = replace(dev, is_available=bool(is_available))
            self._devices[device_id] = updated
            return updated

    def set_trust_state(self, device_id: str, trust_state: Union[TrustState, str]) -> Optional[DeviceIdentity]:
        """Update a device's trust state atomically."""
        state = TrustState.from_string(trust_state) if isinstance(trust_state, str) else trust_state
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return None
            updated = replace(dev, trust_state=state)
            self._devices[device_id] = updated
            return updated

    def clear(self) -> None:
        """Clear all registered devices."""
        with self._lock:
            self._devices.clear()

    def count(self) -> int:
        """Return total number of registered devices."""
        with self._lock:
            return len(self._devices)

    def __len__(self) -> int:
        return self.count()

    def __contains__(self, device_id: str) -> bool:
        with self._lock:
            return device_id in self._devices

    def to_list(self) -> List[Dict[str, Any]]:
        """Serialize all devices in the registry to a sorted list of dicts."""
        with self._lock:
            return [d.to_dict() for d in sorted(self._devices.values(), key=lambda d: d.device_id)]

    @classmethod
    def from_list(cls, data: List[Dict[str, Any]]) -> DeviceRegistry:
        """Construct a DeviceRegistry from serialized list."""
        reg = cls()
        for item in data:
            reg.register(DeviceIdentity.from_dict(item))
        return reg
