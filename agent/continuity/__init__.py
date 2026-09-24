# N4 — Portable Work Continuation Bridge
# Phase: N | Sprint: N4
# Baseline: N3 v1.3.0-n3 (frozen)
#
# Responsibility:
#   Expose the primary entry point for target-side continuation of
#   safe PortableWork representations.

import logging
import json
from typing import Any, Dict, Optional, Union

log = logging.getLogger("zarya.n4")

from agent.continuity.result import ContinuationResult, ContinuationStage, ContinuationStatus
from agent.continuity.validation import validate_portable_work, ValidationVerdict
from agent.continuity.resolution import resolve_target_capabilities, resolve_target_artifacts
from agent.continuity.reconstruction import authorize_continuation, reconstruct_executable_work
from agent.continuity.execution import handoff_to_s18

__version__ = "0.1.0-n4"
__phase__ = "N4"

def continue_portable_work(
    portable_work: Union[dict, str, Any],
    *,
    authorization_token: Optional[str] = None,
    local_policy_override: bool = False,
    checkpoint_store_path: Optional[str] = None,
    checkpoint_store_instance: Optional[Any] = None,
    artifact_registry: Optional[Any] = None,
) -> ContinuationResult:
    """The formal target-side continuation contract.

    Orchestrates the N4 pipeline end-to-end:
      Validate -> Capability Check -> Resolve Artifacts -> Authorize -> Reconstruct -> Execute

    Args:
        portable_work: Deserialized dict, JSON string, or a physical N3 PortableWork instance.
        authorization_token: Optional security token (EIP-1).
        local_policy_override: Set to True to override token-validation gates.
        checkpoint_store_path: Path to target S18 Checkpoint SQLite DB.
        checkpoint_store_instance: Direct active instance of S18 CheckpointStore.
        artifact_registry: Optional direct active reference to S12 artifact registry.

    Returns:
        A ContinuationResult detailing the stage, status, and execution outcomes.
    """
    log.info("N4 Continuation Request Initiated.")

    # ── Step 1: Normalize & Validate Input (VALIDATE Stage) ──
    work_dict: Dict[str, Any] = {}
    
    if isinstance(portable_work, str):
        try:
            work_dict = json.loads(portable_work)
        except json.JSONDecodeError as e:
            log.error("N4 Validation Failed: Input string is not valid JSON. Error: %s", e)
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
        # Explicit N3 instance support
        try:
            work_dict = portable_work.to_portable_dict()
        except Exception as e:
            log.exception("N4 Validation Failed: Could not extract dict from N3 instance:")
            return ContinuationResult(
                work_id="unknown",
                operation_id="unknown",
                stage=ContinuationStage.VALIDATE,
                status=ContinuationStatus.BLOCKED,
                reason=f"Failed to serialize N3 instance: {e}",
            )
    else:
        log.error("N4 Validation Failed: Unsupported input type '%s'", type(portable_work).__name__)
        return ContinuationResult(
            work_id="unknown",
            operation_id="unknown",
            stage=ContinuationStage.VALIDATE,
            status=ContinuationStatus.BLOCKED,
            reason=f"Unsupported input type: {type(portable_work).__name__}",
        )

    # Run core validation checks
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

    # ── Step 2: Capability / Support check (SUPPORT_CHECK Stage) ──
    cap_res = resolve_target_capabilities(work_dict)
    if not cap_res.supported:
        reasons_str = "; ".join(cap_res.reasons)
        return ContinuationResult(
            work_id=work_id,
            operation_id="unknown",
            stage=ContinuationStage.SUPPORT_CHECK,
            status=ContinuationStatus.UNSUPPORTED,
            reason=reasons_str,
        )

    # ── Step 3: Resolve physical target artifact paths (RESOLVE Stage) ──
    art_refs = work_dict.get("artifact_references") or []
    art_res = resolve_target_artifacts(art_refs, artifact_registry=artifact_registry)
    if not art_res.resolved:
        reasons_str = "; ".join(art_res.reasons)
        return ContinuationResult(
            work_id=work_id,
            operation_id="unknown",
            stage=ContinuationStage.RESOLVE,
            status=ContinuationStatus.BLOCKED,
            reason=reasons_str,
        )

    # ── Step 4: Authorization Decision Gate (AUTHORIZE Stage) ──
    is_auth, auth_reason = authorize_continuation(
        work_dict,
        auth_token=authorization_token,
        local_policy_override=local_policy_override
    )
    if not is_auth:
        return ContinuationResult(
            work_id=work_id,
            operation_id="unknown",
            stage=ContinuationStage.AUTHORIZE,
            status=ContinuationStatus.UNAUTHORIZED,
            reason=auth_reason,
        )

    # ── Step 5: Work Reconstruction (RECONSTRUCT Stage) ──
    try:
        reconstructed = reconstruct_executable_work(
            portable_dict=work_dict,
            resolved_paths=art_res.resolved_paths,
            is_authorized=is_auth,
            auth_reason=auth_reason,
        )
    except Exception as e:
        log.exception("N4 Reconstruction Failed:")
        return ContinuationResult(
            work_id=work_id,
            operation_id="unknown",
            stage=ContinuationStage.RECONSTRUCT,
            status=ContinuationStatus.RECONSTRUCTION_FAILED,
            reason=f"Plan reconstruction failed: {e}",
        )

    # ── Step 6: S18 Execution Handoff & Outcome (EXECUTE & OUTCOME Stages) ──
    # Run the handoff to execution
    result = handoff_to_s18(
        reconstructed,
        checkpoint_store_path=checkpoint_store_path,
        checkpoint_store_instance=checkpoint_store_instance,
    )

    log.info(
        "N4 Continuation Executed. Logical Work ID: %s, Handoff Target Operation ID: %s, Outcome Status: %s",
        result.work_id,
        result.operation_id,
        result.status.value,
    )
    return result