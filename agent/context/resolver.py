"""Unified context reference resolver.

Orchestrates: classify → freshness → delegate to existing resolution.
This is the single entry point described in S16 Section 23.

Does NOT replace ActiveComputerContext or resolve_target from artifacts.py.
Delegates INTO them and triggers on-demand re-observation if STALE.
"""
import logging
from dataclasses import dataclass
from typing import Optional, Any, Dict

from agent.context.references import CanonicalReference, classify_reference
from agent.context.freshness import FreshnessState, check_freshness

logger = logging.getLogger("zarya.context")


@dataclass
class ResolutionResult:
    """Traceable resolution outcome.

    Preserves S12 taxonomy: RESOLVED | AMBIGUOUS | NOT_FOUND | UNAVAILABLE.
    Carries evidence for debugging and future device-identity work (S17).
    """
    status: str                            # RESOLVED | AMBIGUOUS | NOT_FOUND | UNAVAILABLE
    target: Optional[str] = None           # What was resolved (path, URL, window ID)
    reference_type: Optional[str] = None   # CanonicalReference used
    evidence_source: Optional[str] = None  # Which observation supported this
    observed_at: Optional[str] = None      # When the evidence was captured
    freshness: Optional[str] = None        # CURRENT | STALE | UNAVAILABLE
    was_refreshed: bool = False            # Whether re-observation occurred
    reason: Optional[str] = None           # Human-readable explanation


def resolve_context_reference(
    reference_text: str,
    context: Any,
    freshness_policy: Optional[Dict] = None,
) -> ResolutionResult:
    """Resolve a user's contextual reference into a concrete target.

    Pipeline (S16 Section 2):
        1. Classify reference (deterministic, no LLM)
        2. Check freshness of relevant observation
        3. Re-observe if STALE (bounded, one attempt)
        4. Delegate to existing resolve_target()
        5. Return traceable result

    Args:
        reference_text: Natural language reference ("this document", etc.).
        context: ActiveComputerContext from agent.artifacts.
        freshness_policy: Optional threshold overrides.

    Returns:
        ResolutionResult with full evidence trail.
    """
    # ── Step 1: Classify ──
    ref_type = classify_reference(reference_text)

    if ref_type == CanonicalReference.UNKNOWN:
        return ResolutionResult(
            status="NOT_FOUND",
            reference_type=ref_type.value,
            reason=f"Cannot classify reference: '{reference_text}'",
        )

    if ref_type == CanonicalReference.EXPLICIT_PATH:
        return ResolutionResult(
            status="RESOLVED",
            target=reference_text.strip(),
            reference_type=ref_type.value,
            evidence_source="explicit",
            reason="Explicit path/URL — no context resolution needed",
        )

    # ── Step 2: Freshness ──
    freshness = _check_context_freshness(ref_type, context, freshness_policy)
    was_refreshed = False

    # ── Step 3: Bounded Re-observation ──
    if freshness == FreshnessState.STALE:
        logger.info(f"Context for {ref_type.value} is STALE. Re-observing...")
        try:
            was_refreshed = _trigger_reobservation(ref_type, context)
            if was_refreshed:
                freshness = _check_context_freshness(ref_type, context, freshness_policy)
        except Exception as e:
            logger.error(f"Failed to re-observe context: {e}", exc_info=True)

    if freshness == FreshnessState.UNAVAILABLE:
        return ResolutionResult(
            status="UNAVAILABLE",
            reference_type=ref_type.value,
            freshness=freshness.value,
            reason=f"No usable or fresh observation available for {ref_type.value}",
        )

    # ── Step 4: Delegate to existing resolution system ──
    return _delegate_resolution(ref_type, reference_text, context, freshness, was_refreshed)


def _check_context_freshness(
    ref_type: CanonicalReference,
    context: Any,
    policy: Optional[Dict] = None,
) -> FreshnessState:
    """Check freshness of the observation relevant to this reference type."""
    fresh_s = (policy or {}).get("fresh_seconds", 5.0)
    stale_s = (policy or {}).get("stale_seconds", 30.0)

    if ref_type == CanonicalReference.CURRENT_PAGE:
        ts = getattr(context, "browser_freshness", None)
        return check_freshness(ts, fresh_threshold=fresh_s, stale_threshold=stale_s)

    if ref_type in (
        CanonicalReference.CURRENT_DOCUMENT,
        CanonicalReference.CURRENT_WINDOW,
        CanonicalReference.CURRENT_APPLICATION,
    ):
        ts = getattr(context, "desktop_freshness", None)
        return check_freshness(ts, fresh_threshold=fresh_s, stale_threshold=stale_s)

    return FreshnessState.UNAVAILABLE


def _trigger_reobservation(ref_type: CanonicalReference, context: Any) -> bool:
    """Trigger the real underlying observer tools on-demand (one bounded refresh)."""
    if ref_type == CanonicalReference.CURRENT_PAGE:
        from agent.tools.browser_observer import observe_browser_context
        observation = observe_browser_context()
        if observation:
            obs_dict = observation.to_dict() if hasattr(observation, "to_dict") else observation
            if hasattr(context, "update_from_tool_response"):
                context.update_from_tool_response("desktopBrowserObserve", {}, {"observation": obs_dict, "browser_observation": obs_dict})
            return True

    elif ref_type in (
        CanonicalReference.CURRENT_DOCUMENT,
        CanonicalReference.CURRENT_WINDOW,
        CanonicalReference.CURRENT_APPLICATION,
    ):
        from agent.tools.desktop_observer import observe_active_window
        observation = observe_active_window()
        if observation:
            obs_dict = observation.to_dict() if hasattr(observation, "to_dict") else observation
            if hasattr(context, "update_from_tool_response"):
                context.update_from_tool_response("desktopObserve", {}, {"observation": obs_dict, "desktop_observation": obs_dict})
            return True

    return False


def _delegate_resolution(
    ref_type: CanonicalReference,
    reference_text: str,
    context: Any,
    freshness: FreshnessState,
    was_refreshed: bool = False,
) -> ResolutionResult:
    """Delegate to existing resolution systems inside artifacts.py."""
    import agent.artifacts as art

    if ref_type == CanonicalReference.CURRENT_PAGE:
        url = getattr(context, "browser_url", None)
        if url:
            return ResolutionResult(
                status="RESOLVED",
                target=url,
                reference_type=ref_type.value,
                evidence_source="browser_context",
                observed_at=getattr(context, "browser_freshness", None),
                freshness=freshness.value,
                was_refreshed=was_refreshed,
                reason="Resolved via browser_context (RESOLVED)",
            )
        else:
            return ResolutionResult(
                status="NOT_FOUND",
                reference_type=ref_type.value,
                evidence_source="browser_context",
                observed_at=getattr(context, "browser_freshness", None),
                freshness=freshness.value,
                was_refreshed=was_refreshed,
                reason="No active browser page URL found",
            )

    # For documents, windows, applications: delegate to context.resolve_target
    target_res = context.resolve_target(reference_text)

    # Extract status
    status_val = target_res.status.value if hasattr(target_res.status, "value") else str(target_res.status)
    target_val = None

    if hasattr(target_res, "canonical_locator") and target_res.canonical_locator:
        target_val = target_res.canonical_locator
    elif hasattr(target_res, "artifact") and target_res.artifact:
        target_val = getattr(target_res.artifact, "locator", None) or getattr(target_res.artifact, "name", None)

    return ResolutionResult(
        status=status_val,
        target=target_val,
        reference_type=ref_type.value,
        evidence_source="artifacts_resolver",
        observed_at=getattr(context, "desktop_freshness", None),
        freshness=freshness.value,
        was_refreshed=was_refreshed,
        reason=getattr(target_res, "reason", f"Resolved via artifact context ({status_val})"),
    )
