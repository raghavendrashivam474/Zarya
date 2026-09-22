"""N1 Unified Work & Computer Context — Snapshot Contract.

Provides a platform-neutral, time-bounded, provenance-aware context
snapshot that assembles existing Zarya observations into a single
coherent representation.

Architecture:
    This module defines DATA STRUCTURES ONLY.
    Adapters that populate these from S13/S14/S17/S18 live in adapters.py.
    The capture orchestration lives in capture.py (Phase 3).

Key principles:
    - References existing types; does not duplicate them.
    - All sub-contexts are Optional. None = unavailable (not {}).
    - Every observation carries provenance (source, timestamp, freshness).
    - Uses S3 StateFreshness for observation-level freshness.
    - Platform-neutral core; platform details in optional extension.
    - Immutable snapshot semantics (frozen dataclasses where practical).

Ownership boundaries preserved:
    S3  → StateFreshness (reused, not redefined)
    S12 → ArtifactIdentity (referenced by artifact_id)
    S13 → WindowObservation (adapted into ComputerContext)
    S14 → BrowserObservation (adapted into BrowserContext)
    S16 → FreshnessState (coexists; mapping documented)
    S17 → DeviceIdentity (referenced by device_id)
    S18 → WorkState (referenced by operation_id + status)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """ISO 8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _generate_context_id() -> str:
    """Generate a unique context snapshot identifier."""
    import uuid
    return f"ctx-{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Provenance — attached to every observation in the snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ObservationProvenance:
    """Where did this observation come from and how fresh is it?

    Reuses S3 StateFreshness values:
        CURRENT, STALE, REQUIRES_REFRESH, UNKNOWN

    Source identifiers (examples):
        "s13_desktop_observer"
        "s14_browser_observer"
        "s17_device_identity"
        "s18_work_runtime"
        "s12_artifact_store"
        "filesystem_scan"
    """
    source: str
    observed_at: str
    freshness: str  # S3 StateFreshness value
    method: str = ""  # How the observation was obtained


# ---------------------------------------------------------------------------
# Device Context — lightweight reference to S17 DeviceIdentity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DeviceContext:
    """Platform-neutral device reference.

    References S17 DeviceIdentity by device_id.
    Does NOT embed the full DeviceIdentity object.

    The platform field uses S17 Platform enum values:
        WINDOWS, MACOS, LINUX, ANDROID, IOS, UNKNOWN
    """
    device_id: str
    platform: str  # S17 Platform value
    device_type: str = "UNKNOWN"  # S17 DeviceType value
    display_name: str = ""
    provenance: Optional[ObservationProvenance] = None


# ---------------------------------------------------------------------------
# Computer Context — platform-neutral projection of S13
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ComputerContext:
    """Platform-neutral active computer/desktop state.

    Abstracts S13 WindowObservation into platform-neutral fields.
    Platform-specific details (e.g., Windows hwnd) go in platform_detail.

    When the desktop is not observable (e.g., Android without desktop),
    this entire object should be None in UnifiedContext, NOT an empty instance.
    """
    active_application: Optional[str] = None
    window_title: Optional[str] = None
    process_name: Optional[str] = None
    process_id: Optional[int] = None
    platform_detail: Optional[Dict[str, Any]] = None
    """Platform-specific fields. Examples:
        Windows: {"hwnd": 12345, "window_class": "Chrome_WidgetWin_1"}
        Linux:   {"wm_class": "google-chrome", "wayland": True}
        Android: None (no desktop window concept)
    """
    provenance: Optional[ObservationProvenance] = None


# ---------------------------------------------------------------------------
# Browser Context — projection of S14 BrowserObservation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BrowserContext:
    """Active browser state.

    Adapted from S14 BrowserObservation.
    Status values: VERIFIED_SUCCESS, UNKNOWN, UNAVAILABLE.
    """
    browser_name: str = ""
    page_url: Optional[str] = None
    page_title: Optional[str] = None
    status: str = "UNKNOWN"  # VERIFIED_SUCCESS | UNKNOWN | UNAVAILABLE
    error: Optional[str] = None
    provenance: Optional[ObservationProvenance] = None


# ---------------------------------------------------------------------------
# Artifact Reference — lightweight reference to S12 ArtifactIdentity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ArtifactReference:
    """Reference to an S12 artifact.

    Does NOT embed the full ArtifactIdentity.
    Carries just enough to identify and locate the artifact.
    """
    artifact_id: str
    artifact_type: str = "file"  # file | browser_tab | document | etc.
    display_name: str = ""
    verification_status: str = "UNKNOWN"
    provenance: Optional[ObservationProvenance] = None


# ---------------------------------------------------------------------------
# Work Reference — lightweight reference to S18 WorkState
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkReference:
    """Reference to an active S18 work operation.

    Does NOT embed the full WorkState or Checkpoint.
    Carries only the identity and current lifecycle status.

    LifecycleStatus values from S18:
        CREATED, AUTHORIZED, RUNNING, CHECKPOINTED, PAUSED,
        CANCELLING, CANCELLED, INTERRUPTED, FAILED, COMPLETED, UNKNOWN
    """
    operation_id: str
    status: str = "UNKNOWN"  # S18 LifecycleStatus value
    current_step: int = 0
    total_steps: int = 0
    provenance: Optional[ObservationProvenance] = None


# ---------------------------------------------------------------------------
# Context Observation — provenance-aware generic observation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ContextObservation:
    """A single provenance-aware observation within the unified context.

    Wraps the concept of S3 StateObservation with explicit source tracking.
    Can represent any domain-specific fact that doesn't fit neatly into
    the structured sub-contexts above.
    """
    domain: str  # application | filesystem | terminal | network | etc.
    subject: str
    state: Dict[str, Any] = field(default_factory=dict)
    status: str = "UNKNOWN"
    provenance: Optional[ObservationProvenance] = None


# ---------------------------------------------------------------------------
# Unified Context — the top-level snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UnifiedContext:
    """Time-bounded, provenance-aware context snapshot.

    This is the primary N1 output type. It answers:
        "What is the relevant environment around this work right now?"

    Design rules:
        1. All sub-contexts are Optional. None = genuinely unavailable.
        2. Never fabricate a value to fill a field.
        3. The snapshot is frozen (immutable) after creation.
        4. captured_at records when the snapshot was assembled.
        5. Each sub-context carries its own provenance and freshness.
        6. Platform-specific details live in platform_detail dicts,
           not in top-level fields.

    Example (desktop with browser):
        UnifiedContext(
            device=DeviceContext(device_id="...", platform="WINDOWS"),
            computer=ComputerContext(active_application="chrome.exe"),
            browser=BrowserContext(browser_name="chrome", page_url="..."),
            work=WorkReference(operation_id="op-123", status="RUNNING"),
        )

    Example (Android, no desktop):
        UnifiedContext(
            device=DeviceContext(device_id="...", platform="ANDROID"),
            computer=None,  # No desktop window concept
            browser=None,   # May or may not be available
            work=WorkReference(operation_id="op-456", status="RUNNING"),
        )
    """
    context_id: str = field(default_factory=_generate_context_id)
    captured_at: str = field(default_factory=_now_iso)

    # --- Sub-contexts (all optional) ---
    device: Optional[DeviceContext] = None
    computer: Optional[ComputerContext] = None
    browser: Optional[BrowserContext] = None
    artifacts: Optional[List[ArtifactReference]] = None
    work: Optional[WorkReference] = None
    observations: Optional[List[ContextObservation]] = None

    # --- Metadata ---
    platform: str = "UNKNOWN"
    """Top-level platform hint for quick filtering.
    Mirrors device.platform when device is available."""

    notes: Optional[str] = None
    """Human-readable annotation (e.g., 'browser unavailable: no Playwright')."""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict for JSON/logging/LLM context."""
        result: Dict[str, Any] = {
            "context_id": self.context_id,
            "captured_at": self.captured_at,
            "platform": self.platform,
        }

        if self.device is not None:
            result["device"] = _frozen_to_dict(self.device)
        else:
            result["device"] = None

        if self.computer is not None:
            result["computer"] = _frozen_to_dict(self.computer)
        else:
            result["computer"] = None

        if self.browser is not None:
            result["browser"] = _frozen_to_dict(self.browser)
        else:
            result["browser"] = None

        if self.artifacts is not None:
            result["artifacts"] = [_frozen_to_dict(a) for a in self.artifacts]
        else:
            result["artifacts"] = None

        if self.work is not None:
            result["work"] = _frozen_to_dict(self.work)
        else:
            result["work"] = None

        if self.observations is not None:
            result["observations"] = [_frozen_to_dict(o) for o in self.observations]
        else:
            result["observations"] = None

        if self.notes is not None:
            result["notes"] = self.notes

        return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _frozen_to_dict(obj: Any) -> Dict[str, Any]:
    """Convert a frozen dataclass to dict, handling nested provenance."""
    from dataclasses import asdict
    return asdict(obj)
