"""N1 Context Capture — Point-in-time UnifiedContext snapshot assembler.

Assembles observations, active states, and device/work identities into a single
immutable `UnifiedContext` snapshot without mutating original subsystems.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agent.context.adapters import (
    adapt_active_computer_context,
    adapt_artifact_identity,
    adapt_browser_observation,
    adapt_device_identity,
    adapt_window_observation,
    adapt_work_state,
)
from agent.context.unified import (
    ArtifactReference,
    BrowserContext,
    ComputerContext,
    ContextObservation,
    DeviceContext,
    UnifiedContext,
    WorkReference,
)

logger = logging.getLogger("zarya.context.capture")


def capture_unified_context(
    device: Optional[Any] = None,
    active_computer_context: Optional[Any] = None,
    desktop_observation: Optional[Any] = None,
    browser_observation: Optional[Any] = None,
    artifacts: Optional[List[Any]] = None,
    work: Optional[Any] = None,
    custom_observations: Optional[List[ContextObservation]] = None,
    notes: Optional[str] = None,
) -> UnifiedContext:
    """Capture a time-bounded, provenance-aware snapshot of the current environment.

    Args:
        device: DeviceIdentity instance, dict, or None.
        active_computer_context: ActiveComputerContext instance (from S12) or None.
        desktop_observation: WindowObservation or dict (overrides active_computer_context desktop).
        browser_observation: BrowserObservation or dict (overrides active_computer_context browser).
        artifacts: List of ArtifactIdentity instances/dicts or None.
        work: WorkState, Checkpoint, or dict representing active work or None.
        custom_observations: Optional list of additional domain-specific ContextObservation objects.
        notes: Optional human-readable notes.

    Returns:
        An immutable UnifiedContext snapshot.
    """
    # 1. Device Context
    dev_ctx: Optional[DeviceContext] = adapt_device_identity(device)
    platform_name = dev_ctx.platform if dev_ctx else "UNKNOWN"

    # 2. Extract from ActiveComputerContext if provided
    acc_extracted = adapt_active_computer_context(active_computer_context) if active_computer_context else {}

    # 3. Desktop / Computer Context
    comp_ctx: Optional[ComputerContext] = None
    if desktop_observation is not None:
        comp_ctx = adapt_window_observation(desktop_observation)
    elif acc_extracted.get("computer") is not None:
        comp_ctx = acc_extracted["computer"]

    # 4. Browser Context
    browser_ctx: Optional[BrowserContext] = None
    if browser_observation is not None:
        browser_ctx = adapt_browser_observation(browser_observation)
    elif acc_extracted.get("browser") is not None:
        browser_ctx = acc_extracted["browser"]

    # 5. Artifacts
    artifact_refs: Optional[List[ArtifactReference]] = None
    collected_artifacts: List[ArtifactReference] = []

    if acc_extracted.get("artifacts"):
        collected_artifacts.extend(acc_extracted["artifacts"])

    if artifacts:
        for art in artifacts:
            adapted_art = adapt_artifact_identity(art)
            if adapted_art:
                # Avoid duplicates by artifact_id
                if not any(a.artifact_id == adapted_art.artifact_id for a in collected_artifacts):
                    collected_artifacts.append(adapted_art)

    if collected_artifacts:
        artifact_refs = collected_artifacts

    # 6. Work Reference
    work_ref: Optional[WorkReference] = adapt_work_state(work)

    # 7. Assemble UnifiedContext Snapshot
    return UnifiedContext(
        platform=platform_name,
        device=dev_ctx,
        computer=comp_ctx,
        browser=browser_ctx,
        artifacts=artifact_refs,
        work=work_ref,
        observations=custom_observations if custom_observations else None,
        notes=notes,
    )