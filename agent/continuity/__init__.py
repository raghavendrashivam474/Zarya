# N5 — Cross-Device Work Continuity & Handoff Lifecycle Bridge
# Phase: N | Sprint: N5
# Baseline: v1.4.0-n4

import json
import logging
from typing import Any, Dict, Optional, Union

log = logging.getLogger("zarya.continuity")

# ── N4 Target Continuation Layer ──
from agent.continuity.result import ContinuationResult, ContinuationStage, ContinuationStatus
from agent.continuity.validation import validate_portable_work, validate_portable_json, ValidationVerdict
from agent.continuity.resolution import resolve_target_capabilities, resolve_target_artifacts
from agent.continuity.reconstruction import authorize_continuation, reconstruct_executable_work, ReconstructedWork
from agent.continuity.execution import handoff_to_s18

# ── N5 Cross-Device Continuity & Handoff Layer ──
from agent.continuity.identity import (
    generate_continuity_id,
    ContinuityOperation,
)
from agent.continuity.state import (
    ContinuityState,
    is_terminal,
    is_recoverable,
    is_success,
    derive_from_n4_status,
    derive_from_s18_status,
)
from agent.continuity.handoff import (
    HandoffRequest,
    HandoffSession,
    RecoveryPolicy,
    RecoveryAction,
)
from agent.continuity.coordination import (
    ContinuityTransferRequest,
    TransportResult,
    FluxTransportProvider,
    DefaultTransportAdapter,
    ContinuityCoordinator,
)
from agent.continuity.reconciliation import (
    ContinuityReconciler,
    ContinuityReconciliationReport,
)
from agent.continuity.persistence import (
    ContinuityRecord,
    ContinuityStore,
)

__version__ = "0.2.0-n5"
__phase__ = "N5"


def continue_portable_work(
    portable_work: Union[dict, str, Any],
    *,
    authorization_token: Optional[str] = None,
    local_policy_override: bool = False,
    checkpoint_store_path: Optional[str] = None,
    checkpoint_store_instance: Optional[Any] = None,
    artifact_registry: Optional[Any] = None,
) -> ContinuationResult:
    """The formal target-side continuation contract."""
    log.info("N4 Continuation Request Initiated.")

    # Step 1: Normalize & Validate Input
    work_dict: Dict[str, Any] = {}
    if isinstance(portable_work, str):
        try:
            work_dict = json.loads(portable_work)
        except json.JSONDecodeError as e:
            return ContinuationResult(
                work_id="unknown",
                operation_id="unknown",
                stage=ContinuationStage.VALIDATE,
                status=ContinuationStatus.BLOCKED,
                reason=f"Input string is not valid JSON: {e}",
            )
    elif isinstance(portable_work, dict):
        work_dict = portable_work
    elif hasattr(portable_work, "to_portable_dict"):
        try:
            work_dict = portable_work.to_portable_dict()
        except Exception as e:
            return ContinuationResult(
                work_id="unknown",
                operation_id="unknown",
                stage=ContinuationStage.VALIDATE,
                status=ContinuationStatus.BLOCKED,
                reason=f"Failed to serialize N3 instance: {e}",
            )
    else:
        return ContinuationResult(
            work_id="unknown",
            operation_id="unknown",
            stage=ContinuationStage.VALIDATE,
            status=ContinuationStatus.BLOCKED,
            reason=f"Unsupported input type: {type(portable_work).__name__}",
        )

    val_res = validate_portable_work(work_dict)
    if not val_res.is_valid:
        primary_issue = val_res.issues[0].message if val_res.issues else "Unknown schema validation failure"
        return ContinuationResult(
            work_id=val_res.work_id or "unknown",
            operation_id="unknown",
            stage=ContinuationStage.VALIDATE,
            status=ContinuationStatus.BLOCKED,
            reason=f"PortableWork validation failed: {primary_issue}",
        )

    work_id = val_res.work_id

    # Step 2: Capability / Support check
    cap_res = resolve_target_capabilities(work_dict)
    if not cap_res.supported:
        return ContinuationResult(
            work_id=work_id,
            operation_id="unknown",
            stage=ContinuationStage.SUPPORT_CHECK,
            status=ContinuationStatus.UNSUPPORTED,
            reason="; ".join(cap_res.reasons),
        )

    # Step 3: Resolve artifacts
    art_refs = work_dict.get("artifact_references") or []
    art_res = resolve_target_artifacts(art_refs, artifact_registry=artifact_registry)
    if not art_res.resolved:
        return ContinuationResult(
            work_id=work_id,
            operation_id="unknown",
            stage=ContinuationStage.RESOLVE,
            status=ContinuationStatus.BLOCKED,
            reason="; ".join(art_res.reasons),
        )

    # Step 4: Authorize
    is_auth, auth_reason = authorize_continuation(
        work_dict,
        auth_token=authorization_token,
        local_policy_override=local_policy_override,
    )
    if not is_auth:
        return ContinuationResult(
            work_id=work_id,
            operation_id="unknown",
            stage=ContinuationStage.AUTHORIZE,
            status=ContinuationStatus.UNAUTHORIZED,
            reason=auth_reason,
        )

    # Step 5: Reconstruct
    reconstructed = reconstruct_executable_work(
        work_dict,
        resolved_paths=art_res.resolved_paths,
        is_authorized=is_auth,
        auth_reason=auth_reason,
    )

    # Step 6 & 7: Execute & Verify via S18
    return handoff_to_s18(
        reconstructed,
        checkpoint_store_path=checkpoint_store_path,
        checkpoint_store_instance=checkpoint_store_instance,
    )


__all__ = [
    # N4 Target Continuation
    "continue_portable_work",
    "ContinuationResult",
    "ContinuationStage",
    "ContinuationStatus",
    "validate_portable_work",
    "validate_portable_json",
    "ValidationVerdict",
    "resolve_target_capabilities",
    "resolve_target_artifacts",
    "authorize_continuation",
    "reconstruct_executable_work",
    "ReconstructedWork",
    "handoff_to_s18",
    # N5 Cross-Device Continuity
    "generate_continuity_id",
    "ContinuityOperation",
    "ContinuityState",
    "is_terminal",
    "is_recoverable",
    "is_success",
    "derive_from_n4_status",
    "derive_from_s18_status",
    "HandoffRequest",
    "HandoffSession",
    "RecoveryPolicy",
    "RecoveryAction",
    "ContinuityTransferRequest",
    "TransportResult",
    "FluxTransportProvider",
    "DefaultTransportAdapter",
    "ContinuityCoordinator",
    "ContinuityReconciler",
    "ContinuityReconciliationReport",
    "ContinuityRecord",
    "ContinuityStore",
]
