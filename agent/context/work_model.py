"""N2 Semantic Work Model.

Establishes a high-level representation of work identity, intent, plan,
context, and outcome, connecting S18 lifecycle state and N1 environmental
context without replacing them or violating architectural boundaries.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from agent.context.unified import UnifiedContext
from agent.lifecycle import LifecycleStatus, WorkState


@dataclass(frozen=True)
class RelevantWorkContext:
    """Subset of UnifiedContext that is semantically associated with this work.

    Filters out background noise, non-task applications, and unrelated tabs.
    """
    device_id: Optional[str] = None
    platform: str = "UNKNOWN"
    active_application: Optional[str] = None
    page_url: Optional[str] = None
    page_title: Optional[str] = None
    artifact_ids: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticWorkModel:
    """Semantic representation of work.

    This class decouples logical/semantic tasks from platform-specific
    runtime handles, making it a foundation for portable state models (N3).
    """
    work_id: str
    intent: str
    plan_reference: Dict[str, Any]
    execution_reference: Optional[str] = None  # S18 operation_id
    lifecycle_status: str = "UNKNOWN"          # S18 LifecycleStatus string representation
    context_reference: Optional[str] = None   # N1 context_id reference
    relevant_context: Optional[RelevantWorkContext] = None
    artifact_references: List[str] = field(default_factory=list)  # S12 artifact_ids
    authorization_reference: Optional[Dict[str, Any]] = None      # Auth metadata
    observations: List[Dict[str, Any]] = field(default_factory=list)  # Provenance-aware task observations
    outcome: str = "UNKNOWN"                   # VERIFIED_SUCCESS | VERIFIED_FAILURE | UNKNOWN

    def to_dict(self) -> Dict[str, Any]:
        """Convert the model to a plain dict for serialization or context building."""
        return {
            "work_id": self.work_id,
            "intent": self.intent,
            "plan_reference": self.plan_reference,
            "execution_reference": self.execution_reference,
            "lifecycle_status": self.lifecycle_status,
            "context_reference": self.context_reference,
            "relevant_context": {
                "device_id": self.relevant_context.device_id if self.relevant_context else None,
                "platform": self.relevant_context.platform if self.relevant_context else "UNKNOWN",
                "active_application": self.relevant_context.active_application if self.relevant_context else None,
                "page_url": self.relevant_context.page_url if self.relevant_context else None,
                "page_title": self.relevant_context.page_title if self.relevant_context else None,
                "artifact_ids": list(self.relevant_context.artifact_ids) if self.relevant_context else [],
            } if self.relevant_context else None,
            "artifact_references": list(self.artifact_references),
            "authorization_reference": self.authorization_reference,
            "observations": list(self.observations),
            "outcome": self.outcome,
        }


def derive_semantic_work(
    work_state: WorkState,
    unified_context: Optional[UnifiedContext] = None,
    authorized: bool = False,
    work_id: Optional[str] = None,
) -> SemanticWorkModel:
    """Adapt S18 WorkState and N1 UnifiedContext into a SemanticWorkModel.

    Guarantees:
      - Logical work_id is distinct from operation_id (uses provided or stable UUID seed)
      - Translates S18 LifecycleStatus cleanly to Epistemic Outcomes:
        * COMPLETED -> VERIFIED_SUCCESS
        * FAILED -> VERIFIED_FAILURE
        * UNKNOWN -> UNKNOWN
        * Any other state -> UNKNOWN
      - Extracts only relevant context from UnifiedContext based on step records.
    """
    # 1. Determine stable logical work_id (derived deterministically or uniquely)
    effective_work_id = work_id or f"work-{uuid.uuid5(uuid.NAMESPACE_DNS, work_state.operation_id).hex[:16]}"

    # 2. Extract artifact references from S18 state
    artifact_ids: Set[str] = set(work_state.artifact_ids)
    for step in work_state.completed_steps:
        if step.artifact_ids:
            artifact_ids.update(step.artifact_ids)
        # Check evidence for artifact paths/ids
        evidence = step.evidence or {}
        verification = evidence.get("verification") or {}
        art_id = verification.get("artifact_id")
        if art_id:
            artifact_ids.add(art_id)

    # 3. Determine semantic outcome
    outcome = "UNKNOWN"
    if work_state.status == LifecycleStatus.COMPLETED:
        outcome = "VERIFIED_SUCCESS"
    elif work_state.status == LifecycleStatus.FAILED:
        outcome = "VERIFIED_FAILURE"

    # 4. Generate observations list from completed steps
    observations: List[Dict[str, Any]] = []
    for step in work_state.completed_steps:
        observations.append({
            "step_id": step.step_id,
            "tool": step.tool,
            "outcome": step.outcome,
            "timestamp": step.timestamp,
            "evidence_keys": list(step.evidence.keys()) if step.evidence else [],
        })

    # 5. Extract work-relevant context from environmental UnifiedContext snapshot
    relevant_context = None
    if unified_context:
        # Determine platform: mirror device platform if top-level is UNKNOWN
        plat = unified_context.platform
        if plat == "UNKNOWN" and unified_context.device and unified_context.device.platform:
            plat = unified_context.device.platform

        active_app = None
        page_url = None
        page_title = None

        used_tools = {step.tool for step in work_state.completed_steps}
        browser_active = any("browser" in t.lower() or t == "openWebPage" for t in used_tools)

        if unified_context.computer:
            active_app = unified_context.computer.active_application

        if browser_active and unified_context.browser:
            page_url = unified_context.browser.page_url
            page_title = unified_context.browser.page_title

        relevant_context = RelevantWorkContext(
            device_id=unified_context.device.device_id if unified_context.device else None,
            platform=plat,
            active_application=active_app,
            page_url=page_url,
            page_title=page_title,
            artifact_ids=list(sorted(artifact_ids)),
        )

    # 6. Build the authorization reference without bypassing the auth layer
    auth_ref = {
        "authorized": authorized,
        "policy": "S8_EXPLICIT_PLAN_AUTHORIZATION",
    }

    return SemanticWorkModel(
        work_id=effective_work_id,
        intent=work_state.goal,
        plan_reference=work_state.plan,
        execution_reference=work_state.operation_id,
        lifecycle_status=work_state.status.value,
        context_reference=unified_context.context_id if unified_context else None,
        relevant_context=relevant_context,
        artifact_references=list(sorted(artifact_ids)),
        authorization_reference=auth_ref,
        observations=observations,
        outcome=outcome,
    )
