# N1 Context Reconnaissance Report

**Sprint:** N1 — Unified Work & Computer Context
**Date:** 2026-09-22
**Status:** Phase 0 Complete — Reconnaissance
**Branch:** main

---

## 1. Executive Summary

Zarya already has substantial context infrastructure spread across S3, S12, S13, S14, S16, S17, and S18. N1 does NOT need to build from scratch. N1 needs to provide a **unified snapshot boundary** that assembles existing observations into a single, time-bounded, provenance-aware context object — without replacing any existing system.

### Critical Discovery

`ActiveComputerContext` in `agent/artifacts.py` already aggregates S12 artifacts, S13 desktop observations, and S14 browser observations into a single mutable runtime object. N1 must **wrap and project** this, not duplicate it.

---

## 2. Existing Source Inventory

| Context | Current Owner | File | Key Types | N1 Treatment |
|---------|--------------|------|-----------|--------------|
| State/Observation | S3 | `agent/state.py` | `StateFreshness`, `StateDomain`, `StateObservation`, `StateCache` | **Reuse** freshness semantics |
| Artifact Identity | S12 | `agent/artifacts.py` | `ArtifactIdentity`, `ActiveComputerContext` | **Reference** artifact_id; **wrap** ActiveComputerContext |
| Computer/Desktop | S13 | `agent/tools/desktop_observer.py` | `WindowObservation` | **Adapt** into platform-neutral projection |
| Browser | S14 | `agent/tools/browser_observer.py` | `BrowserObservation` | **Adapt** into unified context |
| Context Resolution | S16 | `agent/context/resolver.py` | `ResolutionResult`, `CanonicalReference` | **Coexist**; N1 is a snapshot, S16 is a resolver |
| Device Identity | S17 | `agent/context/device.py` | `DeviceIdentity`, `DeviceRegistry`, `Platform`, `DeviceType` | **Reference** directly; do not duplicate |
| Work State | S18 | `agent/lifecycle.py`, `agent/checkpoint.py` | `WorkState`, `LifecycleStatus`, `Checkpoint`, `CheckpointStore` | **Reference** operation_id + status only |
| Persistent Memory | S7 | `agent/context.py` (re-exported via `agent/context/__init__.py`) | `MemoryStore`, `MemoryRecord` | **Do not merge** into live context |

---

## 3. Detailed Type Inventory

### 3.1 S3 — State Model (`agent/state.py`)

```python
class StateFreshness(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    REQUIRES_REFRESH = "REQUIRES_REFRESH"
    UNKNOWN = "UNKNOWN"

class StateDomain(str, Enum):
    APPLICATION = "application"
    FILESYSTEM = "filesystem"
    TERMINAL = "terminal"

@dataclass
class StateObservation:
    domain: str
    subject: str
    observed_at: str
    status: str
    state: Dict[str, Any]
    evidence: Dict[str, Any]
    freshness: str = StateFreshness.CURRENT.value
```

**N1 Note**: This is the canonical freshness model. N1 observations MUST use these values.

### 3.2 S12 — Artifacts (agent/artifacts.py)

```Python
@dataclass
class ArtifactIdentity:
    artifact_id: str
    artifact_type: str
    canonical_locator: str
    display_name: str
    source_operation: str
    created_at: str
    last_verified_at: Optional[str]
    verification_status: str  # "UNKNOWN" | "VERIFIED_SUCCESS" | etc.
    metadata: Dict[str, Any]
```

**N1 Note**: N1 context references artifacts by artifact_id only. Full identity stays in S12.

### 3.3 S12/S13/S14 — ActiveComputerContext (agent/artifacts.py)

```Python
class ActiveComputerContext:
    # S12 Artifacts
    _artifacts: Dict[str, ArtifactIdentity]
    _active_artifact: Optional[ArtifactIdentity]
    _last_created_artifact: Optional[ArtifactIdentity]
    _last_verified_artifact: Optional[ArtifactIdentity]

    # S13 Desktop
    _active_application: Optional[str]
    _active_window_title: Optional[str]
    _active_window_process: Optional[str]
    _desktop_observed_at: Optional[str]
    _desktop_freshness: str  # "UNKNOWN" default

    # S14 Browser
    _browser_name: Optional[str]
    _browser_url: Optional[str]
    _browser_title: Optional[str]
    _browser_observed_at: Optional[str]
    _browser_freshness: str  # "UNKNOWN" default
    _browser_status: str     # "UNKNOWN" default
    _browser_evidence: Optional[str]
```

**N1 Note**: This is the closest existing analog to N1's unified context. N1 should provide a read-only snapshot projection of this mutable runtime state, not replace it.

### 3.4 S13 — Desktop Observer (agent/tools/desktop_observer.py)

```Python
@dataclass
class WindowObservation:
    title: str
    hwnd: int              # ⚠️ Windows-specific
    process_name: str
    process_id: int
    observed_at: str
    freshness: str         # Reuses S3 StateFreshness values
    evidence: str
```

**N1 Note**: hwnd is Windows-specific. N1's platform-neutral model must abstract this into a generic window_handle or similar, with platform-specific detail in an extension.

### 3.5 S14 — Browser Observer (agent/tools/browser_observer.py)

```Python
@dataclass
class BrowserObservation:
    browser_name: str
    page_url: Optional[str]
    page_title: Optional[str]
    observed_at: str
    freshness: str         # S3 StateFreshness values
    evidence: str
    status: str            # VERIFIED_SUCCESS | UNKNOWN | UNAVAILABLE
    error: Optional[str]
```

**N1 Note**: Already platform-neutral. Can be referenced directly.

### 3.6 S16 — Context Resolution (agent/context/)

```Python
# freshness.py
class FreshnessState(Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"  # ⚠️ Different from S3's REQUIRES_REFRESH/UNKNOWN

# references.py
class CanonicalReference(Enum):
    EXPLICIT_PATH, CURRENT_DOCUMENT, CURRENT_PAGE,
    CURRENT_WINDOW, CURRENT_APPLICATION, UNKNOWN

# resolver.py
@dataclass
class ResolutionResult:
    status: str            # RESOLVED | AMBIGUOUS | NOT_FOUND | UNAVAILABLE
    target: Optional[str]
    reference_type: Optional[str]
    evidence_source: Optional[str]
    observed_at: Optional[str]
    freshness: Optional[str]
    was_refreshed: bool
    reason: Optional[str]
```

**N1 Note**: S16 resolves references ("the page I'm on"). N1 captures snapshots ("what is the environment right now"). These are complementary, not competing. N1 must be aware that S16's FreshnessState has 3 states while S3's StateFreshness has 4. N1 should use S3's model for observation-level freshness and document the mapping.

### 3.7 S17 — Device Identity (agent/context/device.py)

```Python
@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    display_name: str
    device_type: DeviceType      # DESKTOP | LAPTOP | PHONE | TABLET | SERVER | UNKNOWN
    platform: Platform           # WINDOWS | MACOS | LINUX | ANDROID | IOS | UNKNOWN
    capabilities: FrozenSet[str]
    trust_state: TrustState
    is_available: bool
    metadata: Dict[str, Any]
N1 Note: Already has Platform.ANDROID. N1 references DeviceIdentity directly. No duplication needed.

3.8 S18 — Work State (agent/lifecycle.py, agent/checkpoint.py)
Python

class LifecycleStatus(str, enum.Enum):
    CREATED, AUTHORIZED, RUNNING, CHECKPOINTED, PAUSED,
    CANCELLING, CANCELLED, INTERRUPTED, FAILED, COMPLETED, UNKNOWN

@dataclass
class WorkState:
    operation_id: str
    goal: str
    plan: Dict[str, Any]
    status: LifecycleStatus
    current_step: int
    total_steps: int
    completed_steps: List[StepRecord]
    checkpoint_step: int
    failure_info: Optional[Dict[str, Any]]
    interruption_info: Optional[Dict[str, Any]]
    artifact_ids: List[str]
    device_id: Optional[str]
    created_at: str
    updated_at: str
```

**N1 Note**: N1 references operation_id and status only. Does NOT embed full WorkState.

## 4. Architectural Tensions Identified

### 4.1 Two Freshness Models

| Model | Location | States Used | By State | Freshness |
| --- | --- | --- | --- | --- |
| `agent/state.py` (S3) | Local State | `CURRENT`, `STALE`, `REQUIRES_REFRESH`, `UNKNOWN` | S3, S13, S14 | observations |
| `agent/context/freshness.py` (S16) | Context Resolution | `CURRENT`, `STALE`, `UNAVAILABLE` | S16 | `FreshnessState` |

**N1 Decision*: Use S3 `StateFreshness` for observation-level provenance (it's more granular). Map to S16 `FreshnessState` only when interacting with S16 resolver. Document the mapping explicitly.

### 4.2 ActiveComputerContext Overlap

`ActiveComputerContext` already aggregates S12+S13+S14. N1 must not duplicate this. Instead, N1 provides:

- A read-only, immutable snapshot projection
- Provenance metadata per observation
- Device identity integration (S17)
- Work reference integration (S18)
- Platform-neutral abstraction layer

### 4.3 Platform-Specific Fields

`WindowObservation.hwnd` is Windows-specific. N1 core model must not expose `hwnd` at the top level. Platform-specific details go into an optional platform extension.

## 5. N1 Placement Decision

N1 will add a new module inside the existing `agent/context/` package:

```text
agent/context/
    __init__.py          # Update to export N1 types
    device.py            # S17 (unchanged)
    freshness.py         # S16 (unchanged)
    references.py        # S16 (unchanged)
    resolver.py          # S16 (unchanged)
    unified.py           # ← N1 NEW: Unified context snapshot
    adapters.py          # ← N1 NEW: Adapters from S13/S14/S17/S18
```

This keeps N1 inside the existing context boundary rather than creating a parallel structure.

## 6. What N1 Will NOT Touch

- `agent/artifacts.py` — ActiveComputerContext stays as-is
- `agent/state.py` — StateFreshness/StateObservation stay as-is
- `agent/tools/desktop_observer.py` — WindowObservation stays as-is
- `agent/tools/browser_observer.py` — BrowserObservation stays as-is
- `agent/context/device.py` — DeviceIdentity stays as-is
- `agent/lifecycle.py` — WorkState/LifecycleStatus stay as-is
- `agent/checkpoint.py` — Checkpoint/CheckpointStore stay as-is
- `agent/context/freshness.py` — FreshnessState stays as-is
- `agent/context/resolver.py` — ResolutionResult stays as-is
- `agent/context/references.py` — CanonicalReference stays as-is

## 7. Next Steps

1. **Phase 1**: Define the N1 unified context contract (agent/context/unified.py)
2. **Phase 2**: Build adapters (agent/context/adapters.py)
3. **Phase 3**: Implement capture mechanism
4. **Phase 4**: Minimal integration
5. **Phase 5*: Tests + validation
