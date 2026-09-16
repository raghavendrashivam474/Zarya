"""
Zarya Context Management Package (S16 + S17)
"""

from agent.context.references import CanonicalReference, classify_reference
from agent.context.freshness import FreshnessState, check_freshness
from agent.context.resolver import resolve_context_reference
from agent.context.device import (
    DeviceIdentity,
    DeviceType,
    Platform,
    TrustState,
    DeviceResolutionStatus,
)

__all__ = [
    "CanonicalReference",
    "classify_reference",
    "FreshnessState",
    "check_freshness",
    "resolve_context_reference",
    "DeviceIdentity",
    "DeviceType",
    "Platform",
    "TrustState",
    "DeviceResolutionStatus",
]
