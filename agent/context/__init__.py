"""S16 — Unified Context & Target Resolution.

Thin orchestration layer over existing S12/S13/S14 systems.
Not a second context store — coordinates the existing ones.
"""
from agent.context.references import CanonicalReference, classify_reference
from agent.context.freshness import FreshnessState, check_freshness
from agent.context.resolver import resolve_context_reference, ResolutionResult

__all__ = [
    "CanonicalReference",
    "classify_reference",
    "FreshnessState",
    "check_freshness",
    "resolve_context_reference",
    "ResolutionResult",
]
