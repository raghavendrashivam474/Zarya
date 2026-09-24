# N4.5 — Continuation Result Contract
# Phase: N | Sprint: N4
# Baseline: N3 v1.3.0-n3 (frozen)
#
# Responsibility:
#   Define the structured outcome of a continuation attempt.
#
# Rule: Never guess execution status. Let S18 outcomes remain authoritative.

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ContinuationStage(str, Enum):
    VALIDATE = "validate"
    SUPPORT_CHECK = "support_check"
    RESOLVE = "resolve"
    AUTHORIZE = "authorize"
    RECONSTRUCT = "reconstruct"
    EXECUTE = "execute"
    VERIFY = "verify"
    OUTCOME = "outcome"


class ContinuationStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VERIFIED_SUCCESS = "verified_success"
    VERIFIED_FAILURE = "verified_failure"
    BLOCKED = "blocked"
    UNAUTHORIZED = "unauthorized"
    UNSUPPORTED = "unsupported"
    RECONSTRUCTION_FAILED = "reconstruction_failed"
    UNKNOWN = "unknown"


@dataclass
class ContinuationResult:
    """The formal target-side Portable Work Continuation Contract outcome."""
    work_id: str
    operation_id: str
    stage: ContinuationStage
    status: ContinuationStatus
    reason: str = ""
    target_device_id: Optional[str] = None
    outcome_details: Dict[str, Any] = field(default_factory=dict)
    observations: List[str] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return self.status == ContinuationStatus.VERIFIED_SUCCESS