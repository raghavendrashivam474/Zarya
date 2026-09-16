"""
S16 / S17 — Unified Context & Target Resolver
Baseline: v0.16.0 (331a91c)

Pipeline:
  Intent / Reference -> classify -> freshness -> re-observe -> delegate -> ResolutionResult
  + S17 Compound Device Target Resolution
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from agent.artifacts import ActiveComputerContext, ArtifactIdentity, ArtifactKind, ResolutionStatus
from agent.context.references import CanonicalReference, classify_reference
from agent.context.freshness import FreshnessState, check_freshness
from agent.context.device import (
    DeviceIdentity,
    DeviceRegistry,
    DeviceResolutionResult,
    DeviceResolutionStatus,
    resolve_device_reference,
)


@dataclass(frozen=True)
class ContextResolutionResult:
    """Unified context resolution result."""
    status: ResolutionStatus
    artifact: Optional[ArtifactIdentity] = None
    canonical_reference: Optional[CanonicalReference] = None
    freshness: FreshnessState = FreshnessState.FRESH
    candidate_artifacts: List[ArtifactIdentity] = field(default_factory=list)
    reference_raw: str = ""
    reobserved: bool = False
    reason: Optional[str] = None

    @property
    def is_resolved(self) -> bool:
        return self.status in (ResolutionStatus.RESOLVED, ResolutionStatus.RE_OBSERVED) and self.artifact is not None


@dataclass(frozen=True)
class CompoundResolutionResult:
    """Unified resolution result containing both resolved artifact and resolved target device.
    
    Proves S16 (artifact) and S17 (device) compose seamlessly.
    """
    artifact_result: Optional[ContextResolutionResult] = None
    device_result: Optional[DeviceResolutionResult] = None
    raw_input: str = ""

    @property
    def is_fully_resolved(self) -> bool:
        art_ok = self.artifact_result is not None and self.artifact_result.is_resolved
        dev_ok = self.device_result is not None and self.device_result.is_resolved
        return art_ok and dev_ok


def resolve_context_reference(
    reference: str,
    context: ActiveComputerContext,
    reobserve_fn: Optional[Callable[[], Optional[ActiveComputerContext]]] = None,
    max_age_seconds: float = 30.0,
) -> ContextResolutionResult:
    """Resolve a natural-language or canonical reference against the current context."""
    if not reference or not reference.strip():
        return ContextResolutionResult(
            status=ResolutionStatus.NOT_FOUND,
            reference_raw=reference or "",
            reason="Empty reference",
        )

    canonical = classify_reference(reference)
    freshness = check_freshness(context, max_age_seconds=max_age_seconds)
    reobserved = False

    # Stale context handling with re-observation hook
    active_ctx = context
    if freshness == FreshnessState.STALE and reobserve_fn is not None:
        new_ctx = reobserve_fn()
        if new_ctx is not None:
            active_ctx = new_ctx
            freshness = FreshnessState.FRESH
            reobserved = True

    # 1. Desktop / Active Window References
    if canonical == CanonicalReference.ACTIVE_WINDOW:
        if active_ctx.active_window:
            handle = active_ctx.active_window.get("handle", 0)
            title = active_ctx.active_window.get("title", "Active Window")
            proc = active_ctx.active_window.get("process_name")
            art = ArtifactIdentity.create_window_artifact(handle=handle, title=title, process_name=proc)
            return ContextResolutionResult(
                status=ResolutionStatus.RE_OBSERVED if reobserved else ResolutionStatus.RESOLVED,
                artifact=art,
                canonical_reference=canonical,
                freshness=freshness,
                reference_raw=reference,
                reobserved=reobserved,
            )
        return ContextResolutionResult(
            status=ResolutionStatus.NOT_FOUND,
            canonical_reference=canonical,
            freshness=freshness,
            reference_raw=reference,
            reason="No active window observed in context",
        )

    # 2. Browser Tab References
    if canonical in (CanonicalReference.ACTIVE_TAB, CanonicalReference.CURRENT_PAGE):
        if active_ctx.active_browser_tab:
            url = active_ctx.active_browser_tab.get("url", "")
            title = active_ctx.active_browser_tab.get("title")
            art = ArtifactIdentity.create_url_artifact(url=url, title=title)
            return ContextResolutionResult(
                status=ResolutionStatus.RE_OBSERVED if reobserved else ResolutionStatus.RESOLVED,
                artifact=art,
                canonical_reference=canonical,
                freshness=freshness,
                reference_raw=reference,
                reobserved=reobserved,
            )
        return ContextResolutionResult(
            status=ResolutionStatus.NOT_FOUND,
            canonical_reference=canonical,
            freshness=freshness,
            reference_raw=reference,
            reason="No active browser tab observed in context",
        )

    # 3. File / Document Artifact References
    if canonical in (CanonicalReference.ACTIVE_FILE, CanonicalReference.CURRENT_DOCUMENT, CanonicalReference.LAST_ARTIFACT):
        latest = active_ctx.get_latest_artifact()
        if latest:
            return ContextResolutionResult(
                status=ResolutionStatus.RE_OBSERVED if reobserved else ResolutionStatus.RESOLVED,
                artifact=latest,
                canonical_reference=canonical,
                freshness=freshness,
                reference_raw=reference,
                reobserved=reobserved,
            )
        return ContextResolutionResult(
            status=ResolutionStatus.NOT_FOUND,
            canonical_reference=canonical,
            freshness=freshness,
            reference_raw=reference,
            reason="No recent artifact found in context",
        )

    # Fallback to direct lookup in recent artifacts
    for art in active_ctx.recent_artifacts:
        if reference.strip().lower() in art.display_name.lower():
            return ContextResolutionResult(
                status=ResolutionStatus.RESOLVED,
                artifact=art,
                canonical_reference=canonical,
                freshness=freshness,
                reference_raw=reference,
            )

    return ContextResolutionResult(
        status=ResolutionStatus.NOT_FOUND,
        canonical_reference=canonical,
        freshness=freshness,
        reference_raw=reference,
        reason=f"Could not resolve reference '{reference}' in active context",
    )


def resolve_compound_intent(
    text: str,
    context: ActiveComputerContext,
    registry: Optional[DeviceRegistry] = None,
) -> CompoundResolutionResult:
    """Deterministically resolves compound cross-device requests such as:
    
      "send this document to my laptop"
      "transfer this file to office pc"
      "send current page to the phone"
    
    Decomposes the intent into:
      1. Artifact reference -> S16 resolve_context_reference
      2. Device reference   -> S17 resolve_device_reference
    
    Does NOT initiate transport (S18 boundary).
    """
    dev_reg = registry or getattr(context, "device_registry", None) or DeviceRegistry()

    # Pattern: send/transfer <artifact> to <device>
    match = re.search(r"^(?:send|transfer|share|copy)\s+(.+?)\s+to\s+(.+)$", text.strip(), re.IGNORECASE)
    if match:
        art_ref_raw = match.group(1).strip()
        dev_ref_raw = match.group(2).strip()

        art_res = resolve_context_reference(art_ref_raw, context)
        dev_res = resolve_device_reference(dev_ref_raw, dev_reg)

        return CompoundResolutionResult(
            artifact_result=art_res,
            device_result=dev_res,
            raw_input=text,
        )

    # Fallback: attempt artifact resolution on whole string
    art_res = resolve_context_reference(text, context)
    dev_res = resolve_device_reference(text, dev_reg)

    return CompoundResolutionResult(
        artifact_result=art_res,
        device_result=dev_res,
        raw_input=text,
    )
