"""
S17 — Cross-Device Identity & Local Device Fabric
Baseline: v0.16.0 (331a91c)

Owns:
  - DeviceType, Platform, TrustState, DeviceResolutionStatus enums
  - DeviceIdentity dataclass
  - DeviceRegistry (local, thread-safe in-memory device store)
  - DeviceResolutionResult dataclass
  - resolve_device_reference() deterministic resolution engine

Does NOT own:
  - Flux integration / PeerId / PathId (S18)
  - Network discovery / transport
  - Authorization enforcement
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple, Union


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

        if isinstance(self.device_type, str) and not isinstance(self.device_type, DeviceType):
            object.__setattr__(self, "device_type", DeviceType.from_string(self.device_type))
        if isinstance(self.platform, str) and not isinstance(self.platform, Platform):
            object.__setattr__(self, "platform", Platform.from_string(self.platform))
        if isinstance(self.trust_state, str) and not isinstance(self.trust_state, TrustState):
            object.__setattr__(self, "trust_state", TrustState.from_string(self.trust_state))
        if not isinstance(self.capabilities, frozenset):
            object.__setattr__(self, "capabilities", frozenset(self.capabilities))

    def has_capability(self, cap: str) -> bool:
        return cap.strip().lower() in {c.lower() for c in self.capabilities}

    def is_trusted(self) -> bool:
        return self.trust_state == TrustState.TRUSTED

    def to_dict(self) -> Dict[str, Any]:
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
    """Thread-safe in-memory registry of logical devices."""

    def __init__(self) -> None:
        self._devices: Dict[str, DeviceIdentity] = {}
        self._lock = threading.RLock()

    def register(self, device: DeviceIdentity) -> None:
        if not isinstance(device, DeviceIdentity):
            raise TypeError("Expected DeviceIdentity instance")
        with self._lock:
            self._devices[device.device_id] = device

    def unregister(self, device_id: str) -> Optional[DeviceIdentity]:
        if not device_id:
            return None
        with self._lock:
            return self._devices.pop(device_id, None)

    def get(self, device_id: str) -> Optional[DeviceIdentity]:
        if not device_id:
            return None
        with self._lock:
            return self._devices.get(device_id)

    def get_by_name(self, display_name: str, case_sensitive: bool = False) -> List[DeviceIdentity]:
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
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return None
            updated = replace(dev, is_available=bool(is_available))
            self._devices[device_id] = updated
            return updated

    def set_trust_state(self, device_id: str, trust_state: Union[TrustState, str]) -> Optional[DeviceIdentity]:
        state = TrustState.from_string(trust_state) if isinstance(trust_state, str) else trust_state
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return None
            updated = replace(dev, trust_state=state)
            self._devices[device_id] = updated
            return updated

    def clear(self) -> None:
        with self._lock:
            self._devices.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._devices)

    def __len__(self) -> int:
        return self.count()

    def __contains__(self, device_id: str) -> bool:
        with self._lock:
            return device_id in self._devices

    def to_list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [d.to_dict() for d in sorted(self._devices.values(), key=lambda d: d.device_id)]

    @classmethod
    def from_list(cls, data: List[Dict[str, Any]]) -> DeviceRegistry:
        reg = cls()
        for item in data:
            reg.register(DeviceIdentity.from_dict(item))
        return reg


@dataclass(frozen=True)
class DeviceResolutionResult:
    """Outcome of resolving a device reference against the DeviceRegistry."""
    status: DeviceResolutionStatus
    device: Optional[DeviceIdentity] = None
    candidate_devices: List[DeviceIdentity] = field(default_factory=list)
    reference_raw: str = ""
    reason: Optional[str] = None

    @property
    def is_resolved(self) -> bool:
        return self.status == DeviceResolutionStatus.RESOLVED and self.device is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "device": self.device.to_dict() if self.device else None,
            "candidate_devices": [d.to_dict() for d in self.candidate_devices],
            "reference_raw": self.reference_raw,
            "reason": self.reason,
        }


# Bounded deterministic reference tokens and category matchers
_CATEGORY_KEYWORDS: Dict[DeviceType, Tuple[str, ...]] = {
    DeviceType.LAPTOP: ("laptop", "notebook", "macbook", "thinkpad"),
    DeviceType.MOBILE: ("phone", "mobile", "iphone", "android", "smartphone"),
    DeviceType.DESKTOP: ("desktop", "workstation", "tower", "office pc", "home pc", "pc"),
    DeviceType.TABLET: ("tablet", "ipad"),
    DeviceType.SERVER: ("server", "quantum server", "host"),
}

_RELATIVE_PATTERNS = (
    r"^(?:that|the other|other)\s+(?:computer|device|machine|pc)$",
    r"^(?:that|other)\s+one$",
)


def _clean_reference(raw: str) -> str:
    """Normalize input reference text for matching."""
    text = raw.strip().lower()
    # Strip common leading verbs / prepositions
    text = re.sub(r"^(?:send\s+(?:this\s+)?to|to|on|for|transfer\s+to)\s+", "", text).strip()
    return text


def resolve_device_reference(
    reference: str,
    registry: DeviceRegistry,
    caller_device_id: Optional[str] = None,
) -> DeviceResolutionResult:
    """Deterministically resolve a natural-language or explicit device reference.
    
    Rules:
      1. Exact device_id match takes highest priority.
      2. Exact display_name match (case-insensitive) comes second.
      3. Category keywords ("laptop", "phone", "desktop") filter by DeviceType.
      4. Contextual relative references ("that computer", "the other computer") filter out caller_device_id.
      5. Substring match across display names.
      6. If > 1 candidate matches -> AMBIGUOUS (no arbitrary guessing).
      7. If 0 candidates match -> NOT_FOUND.
      8. If 1 candidate matches but is_available is False -> UNAVAILABLE.
      9. If 1 candidate matches and is_available is True -> RESOLVED.
    """
    if not reference or not reference.strip():
        return DeviceResolutionResult(
            status=DeviceResolutionStatus.NOT_FOUND,
            reference_raw=reference or "",
            reason="Empty or blank device reference",
        )

    raw_clean = reference.strip()
    cleaned = _clean_reference(raw_clean)

    # 1. Exact device_id match
    exact_id_match = registry.get(raw_clean) or registry.get(cleaned)
    if exact_id_match is not None:
        if not exact_id_match.is_available:
            return DeviceResolutionResult(
                status=DeviceResolutionStatus.UNAVAILABLE,
                device=exact_id_match,
                candidate_devices=[exact_id_match],
                reference_raw=raw_clean,
                reason=f"Device '{exact_id_match.display_name}' ({exact_id_match.device_id}) is currently unavailable",
            )
        return DeviceResolutionResult(
            status=DeviceResolutionStatus.RESOLVED,
            device=exact_id_match,
            candidate_devices=[exact_id_match],
            reference_raw=raw_clean,
        )

    # 2. Exact display_name match
    name_matches = registry.get_by_name(cleaned, case_sensitive=False)
    if not name_matches and cleaned != raw_clean:
        name_matches = registry.get_by_name(raw_clean, case_sensitive=False)

    if len(name_matches) == 1:
        target = name_matches[0]
        if not target.is_available:
            return DeviceResolutionResult(
                status=DeviceResolutionStatus.UNAVAILABLE,
                device=target,
                candidate_devices=[target],
                reference_raw=raw_clean,
                reason=f"Device '{target.display_name}' ({target.device_id}) is currently unavailable",
            )
        return DeviceResolutionResult(
            status=DeviceResolutionStatus.RESOLVED,
            device=target,
            candidate_devices=[target],
            reference_raw=raw_clean,
        )
    elif len(name_matches) > 1:
        return DeviceResolutionResult(
            status=DeviceResolutionStatus.AMBIGUOUS,
            candidate_devices=name_matches,
            reference_raw=raw_clean,
            reason=f"Multiple devices found with display name '{raw_clean}'",
        )

    # 3. Relative reference check: "that computer", "the other computer"
    is_relative = any(re.search(pat, cleaned) for pat in _RELATIVE_PATTERNS)
    if is_relative:
        all_devs = registry.list_devices()
        candidates = [d for d in all_devs if d.device_id != caller_device_id] if caller_device_id else all_devs
        if len(candidates) == 1:
            target = candidates[0]
            if not target.is_available:
                return DeviceResolutionResult(
                    status=DeviceResolutionStatus.UNAVAILABLE,
                    device=target,
                    candidate_devices=[target],
                    reference_raw=raw_clean,
                    reason=f"Device '{target.display_name}' is currently unavailable",
                )
            return DeviceResolutionResult(
                status=DeviceResolutionStatus.RESOLVED,
                device=target,
                candidate_devices=[target],
                reference_raw=raw_clean,
            )
        elif len(candidates) > 1:
            return DeviceResolutionResult(
                status=DeviceResolutionStatus.AMBIGUOUS,
                candidate_devices=candidates,
                reference_raw=raw_clean,
                reason="Multiple other devices exist; cannot determine target unambiguously",
            )
        else:
            return DeviceResolutionResult(
                status=DeviceResolutionStatus.NOT_FOUND,
                reference_raw=raw_clean,
                reason="No other devices registered in the local fabric",
            )

    # 4. Category keywords check
    matched_type: Optional[DeviceType] = None
    for dtype, kws in _CATEGORY_KEYWORDS.items():
        for kw in kws:
            # Match whole words or boundary
            if re.search(r"\b" + re.escape(kw) + r"\b", cleaned):
                matched_type = dtype
                break
        if matched_type is not None:
            break

    candidates: List[DeviceIdentity] = []
    if matched_type is not None:
        candidates = registry.list_devices(device_type=matched_type)
        # Also check display names containing the keyword
        name_submatches = [
            d for d in registry.list_devices()
            if any(re.search(r"\b" + re.escape(kw) + r"\b", d.display_name.lower()) for kw in _CATEGORY_KEYWORDS[matched_type])
            and d not in candidates
        ]
        candidates.extend(name_submatches)

    # 5. Substring / partial match fallback if no category matched
    if not candidates:
        tokens = [t for t in re.split(r"\s+", cleaned) if t and t not in ("my", "the", "a", "an", "that", "this")]
        if tokens:
            for dev in registry.list_devices():
                dev_lower = dev.display_name.lower()
                if any(tok in dev_lower for tok in tokens):
                    if dev not in candidates:
                        candidates.append(dev)

    # Deduplicate deterministically
    unique_candidates = sorted(list(set(candidates)), key=lambda d: d.device_id)

    if len(unique_candidates) == 1:
        target = unique_candidates[0]
        if not target.is_available:
            return DeviceResolutionResult(
                status=DeviceResolutionStatus.UNAVAILABLE,
                device=target,
                candidate_devices=[target],
                reference_raw=raw_clean,
                reason=f"Device '{target.display_name}' ({target.device_id}) is currently unavailable",
            )
        return DeviceResolutionResult(
            status=DeviceResolutionStatus.RESOLVED,
            device=target,
            candidate_devices=[target],
            reference_raw=raw_clean,
        )
    elif len(unique_candidates) > 1:
        return DeviceResolutionResult(
            status=DeviceResolutionStatus.AMBIGUOUS,
            candidate_devices=unique_candidates,
            reference_raw=raw_clean,
            reason=f"Reference '{raw_clean}' matched {len(unique_candidates)} devices",
        )

    return DeviceResolutionResult(
        status=DeviceResolutionStatus.NOT_FOUND,
        reference_raw=raw_clean,
        reason=f"No device found matching reference '{raw_clean}'",
    )
