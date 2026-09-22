"""Zarya Context Package (S7 Memory + S16 Unified Context + S17 Device Fabric + N1 Unified Work Context + N2 Semantic Work Context).

Provides unified access to:
  - S7 Persistent Memory & Episodic Store (MemoryStore, MemoryRecord, etc.)
  - S16 Unified Context Resolution (CanonicalReference, FreshnessState, resolve_context_reference, ResolutionResult)
  - S17 Logical Device Identity & Local Device Fabric (DeviceIdentity, DeviceRegistry, resolve_device_reference, CompoundResolutionResult)      
  - N1 Unified Work & Computer Context Snapshot (UnifiedContext, capture_unified_context, adapters)
  - N2 Semantic Work Context & State Model (RelevantWorkContext, SemanticWorkModel, derive_semantic_work)
"""

import importlib.util
from pathlib import Path
import sys

# ── S7 Persistent Context Re-exports (from agent/context.py) ──
_s7_file = Path(__file__).resolve().parent.parent / "context.py"
if _s7_file.exists():
    _module_name = "agent.context_s7"
    _spec = importlib.util.spec_from_file_location(_module_name, str(_s7_file))
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_module_name] = _mod
        _spec.loader.exec_module(_mod)
        # Re-export all public attributes (including helper functions like now_iso)
        for _attr in dir(_mod):
            if not _attr.startswith("__"):
                globals()[_attr] = getattr(_mod, _attr)

# ── S16 Unified Context Resolution ──
from agent.context.references import CanonicalReference, classify_reference
from agent.context.freshness import FreshnessState, check_freshness
from agent.context.resolver import (
    resolve_context_reference,
    ResolutionResult,
    CompoundResolutionResult,
    resolve_compound_intent,
)

# ── S17 Logical Device Identity & Local Fabric ──
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

# ── N1 Unified Work & Computer Context ──
from agent.context.unified import (
    UnifiedContext,
    DeviceContext,
    ComputerContext,
    BrowserContext,
    ArtifactReference,
    WorkReference,
    ContextObservation,
    ObservationProvenance,
)
from agent.context.capture import capture_unified_context
from agent.context.adapters import (
    adapt_device_identity,
    adapt_window_observation,
    adapt_browser_observation,
    adapt_artifact_identity,
    adapt_work_state,
    adapt_active_computer_context,
)

# ── N2 Semantic Work Context & State Model ──
from agent.context.work_model import (
    RelevantWorkContext,
    SemanticWorkModel,
    derive_semantic_work,
)

__all__ = [
    # S16
    "CanonicalReference",
    "classify_reference",
    "FreshnessState",
    "check_freshness",
    "resolve_context_reference",
    "ResolutionResult",
    "CompoundResolutionResult",
    "resolve_compound_intent",
    # S17
    "DeviceIdentity",
    "DeviceRegistry",
    "DeviceType",
    "Platform",
    "TrustState",
    "DeviceResolutionStatus",
    "DeviceResolutionResult",
    "resolve_device_reference",
    # N1
    "UnifiedContext",
    "DeviceContext",
    "ComputerContext",
    "BrowserContext",
    "ArtifactReference",
    "WorkReference",
    "ContextObservation",
    "ObservationProvenance",
    "capture_unified_context",
    "adapt_device_identity",
    "adapt_window_observation",
    "adapt_browser_observation",
    "adapt_artifact_identity",
    "adapt_work_state",
    "adapt_active_computer_context",
    # N2
    "RelevantWorkContext",
    "SemanticWorkModel",
    "derive_semantic_work",
]
