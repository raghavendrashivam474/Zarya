"""
S17 — Cross-Device Identity & Local Device Fabric
Baseline: v0.16.0 (331a91c)

Owns:
  - DeviceType, Platform, TrustState, DeviceResolutionStatus enums
  - DeviceIdentity dataclass
  - Model serialization and validation

Does NOT own:
  - Flux integration / PeerId / PathId (S18)
  - Network discovery / transport
  - Authorization enforcement
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, Optional, Set, Union


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
