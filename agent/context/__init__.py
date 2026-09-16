"""
Zarya Context Management Package (S16 + S17)
"""

from agent.context.references import CanonicalReference, classify_reference
from agent.context.freshness import FreshnessState, check_freshness
from agent.context.resolver import (
    ContextResolutionResult,
    CompoundResolutionResult,
    resolve_context_reference,
    resolve_compound_intent,
)
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

__all__ = [
    "CanonicalReference",
    "classify_reference",
    "FreshnessState",
    "check_freshness",
    "ContextResolutionResult",
    "CompoundResolutionResult",
    "resolve_context_reference",
    "resolve_compound_intent",
    "DeviceIdentity",
    "DeviceRegistry",
    "DeviceType",
    "Platform",
    "TrustState",
    "DeviceResolutionStatus",
    "DeviceResolutionResult",
    "resolve_device_reference",
]
