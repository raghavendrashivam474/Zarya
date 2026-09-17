"""S18 - Work Lifecycle and State Management.

Provides bounded lifecycle tracking for long-running Zarya work operations.
This module does NOT replace S6 work execution, S5 recovery, or S2 verification.
It wraps existing work with checkpoint/resume/pause/cancel semantics.

Relationship to existing milestones:
  S5  remains the sole recovery authority
  S2  remains the sole verification authority
  S10 remains the bounded adaptation authority
  S12 remains the artifact identity authority
  S7  remains the historical memory store (S18 state is separate)
"""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ── Lifecycle Status ─────────────────────────────────────────────

class LifecycleStatus(str, enum.Enum):
    """Explicit states for an S18 work operation.

    UNKNOWN is terminal. Never assume UNKNOWN means resumable.
    COMPLETED, CANCELLED, FAILED are terminal.
    """
    CREATED = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    RUNNING = "RUNNING"
    CHECKPOINTED = "CHECKPOINTED"
    PAUSED = "PAUSED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    UNKNOWN = "UNKNOWN"


# Legal transitions: from_status -> allowed target statuses
_ALLOWED_TRANSITIONS: Dict[LifecycleStatus, frozenset] = {
    LifecycleStatus.CREATED: frozenset({
        LifecycleStatus.AUTHORIZED,
        LifecycleStatus.CANCELLED,
        LifecycleStatus.FAILED,
        LifecycleStatus.UNKNOWN,
    }),
    LifecycleStatus.AUTHORIZED: frozenset({
        LifecycleStatus.RUNNING,
        LifecycleStatus.CANCELLED,
        LifecycleStatus.FAILED,
        LifecycleStatus.UNKNOWN,
    }),
    LifecycleStatus.RUNNING: frozenset({
        LifecycleStatus.CHECKPOINTED,
        LifecycleStatus.PAUSED,
        LifecycleStatus.CANCELLING,
        LifecycleStatus.INTERRUPTED,
        LifecycleStatus.FAILED,
        LifecycleStatus.COMPLETED,
        LifecycleStatus.UNKNOWN,
    }),
    LifecycleStatus.CHECKPOINTED: frozenset({
        LifecycleStatus.RUNNING,
        LifecycleStatus.PAUSED,
        LifecycleStatus.CANCELLING,
        LifecycleStatus.INTERRUPTED,
        LifecycleStatus.FAILED,
        LifecycleStatus.COMPLETED,
        LifecycleStatus.UNKNOWN,
    }),
    LifecycleStatus.PAUSED: frozenset({
        LifecycleStatus.RUNNING,
        LifecycleStatus.CANCELLED,
        LifecycleStatus.FAILED,
        LifecycleStatus.UNKNOWN,
    }),
    LifecycleStatus.CANCELLING: frozenset({
        LifecycleStatus.CANCELLED,
        LifecycleStatus.FAILED,
        LifecycleStatus.UNKNOWN,
    }),
    LifecycleStatus.CANCELLED: frozenset(),
    LifecycleStatus.INTERRUPTED: frozenset({
        LifecycleStatus.RUNNING,
        LifecycleStatus.CANCELLED,
        LifecycleStatus.FAILED,
        LifecycleStatus.UNKNOWN,
    }),
    LifecycleStatus.FAILED: frozenset(),
    LifecycleStatus.COMPLETED: frozenset(),
    LifecycleStatus.UNKNOWN: frozenset(),
}

RESUMABLE_STATES = frozenset({
    LifecycleStatus.PAUSED,
    LifecycleStatus.INTERRUPTED,
    LifecycleStatus.CHECKPOINTED,
})

TERMINAL_STATES = frozenset({
    LifecycleStatus.COMPLETED,
    LifecycleStatus.CANCELLED,
    LifecycleStatus.FAILED,
    LifecycleStatus.UNKNOWN,
})


# ── Step Record ──────────────────────────────────────────────────

@dataclass
class StepRecord:
    """Outcome of a single executed step within a work operation."""
    step_index: int
    step_id: str
    tool: str
    outcome: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    artifact_ids: List[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = _now_iso()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "step_id": self.step_id,
            "tool": self.tool,
            "outcome": self.outcome,
            "evidence": self.evidence,
            "artifact_ids": list(self.artifact_ids),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepRecord":
        return cls(
            step_index=data["step_index"],
            step_id=data["step_id"],
            tool=data["tool"],
            outcome=data["outcome"],
            evidence=data.get("evidence", {}),
            artifact_ids=data.get("artifact_ids", []),
            timestamp=data.get("timestamp", ""),
        )


# ── Work State ───────────────────────────────────────────────────

@dataclass
class WorkState:
    """Durable representation of an S18 work operation.

    IMPORTANT: This is NOT a success claim. It records what has happened,
    what remains, and the current lifecycle status. Final success still
    requires S2 verification of the overall outcome.
    """
    operation_id: str
    goal: str
    plan: Dict[str, Any]
    status: LifecycleStatus = LifecycleStatus.CREATED
    current_step: int = 0
    total_steps: int = 0
    completed_steps: List[StepRecord] = field(default_factory=list)
    checkpoint_step: int = 0
    failure_info: Optional[Dict[str, Any]] = None
    interruption_info: Optional[Dict[str, Any]] = None
    artifact_ids: List[str] = field(default_factory=list)
    device_id: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now_iso()
        if not self.updated_at:
            self.updated_at = self.created_at
        if isinstance(self.status, str):
            self.status = LifecycleStatus(self.status)

    # ── State transitions ────────────────────────────────────────

    def can_transition_to(self, target: LifecycleStatus) -> bool:
        """Check whether a transition from current status is legal."""
        if isinstance(target, str):
            target = LifecycleStatus(target)
        allowed = _ALLOWED_TRANSITIONS.get(self.status, frozenset())
        return target in allowed

    def transition_to(self, target: LifecycleStatus, reason: str = "") -> bool:
        """Attempt a state transition.

        Returns True if legal and applied, False if illegal.
        Never silently forces illegal transitions.
        """
        if isinstance(target, str):
            target = LifecycleStatus(target)

        if not self.can_transition_to(target):
            log.warning(
                "S18 illegal transition: %s -> %s (op=%s, reason=%s)",
                self.status.value, target.value, self.operation_id, reason,
            )
            return False

        old = self.status
        self.status = target
        self.updated_at = _now_iso()
        log.info(
            "S18 transition: %s -> %s (op=%s, reason=%s)",
            old.value, target.value, self.operation_id, reason,
        )
        return True

    # ── Checkpoint ───────────────────────────────────────────────

    def record_checkpoint(self) -> bool:
        """Mark current completed_steps boundary as a checkpoint.

        A checkpoint is NOT a success claim. It means the runtime has
        recorded state up to this point. Final success still requires
        S2 verification.
        """
        if not self.can_transition_to(LifecycleStatus.CHECKPOINTED):
            log.warning(
                "S18 cannot checkpoint from %s (op=%s)",
                self.status.value, self.operation_id,
            )
            return False

        self.checkpoint_step = len(self.completed_steps)
        self.transition_to(LifecycleStatus.CHECKPOINTED, "checkpoint recorded")
        return True

    # ── Step recording ───────────────────────────────────────────

    def record_step(self, step: StepRecord) -> None:
        """Record a completed step outcome."""
        self.completed_steps.append(step)
        self.current_step = step.step_index + 1
        self.updated_at = _now_iso()

    @property
    def remaining_steps(self) -> int:
        return max(0, self.total_steps - len(self.completed_steps))

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    @property
    def is_resumable(self) -> bool:
        return self.status in RESUMABLE_STATES and self.checkpoint_step > 0

    # ── Serialization ────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "goal": self.goal,
            "plan": self.plan,
            "status": self.status.value,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "completed_steps": [s.to_dict() for s in self.completed_steps],
            "checkpoint_step": self.checkpoint_step,
            "failure_info": self.failure_info,
            "interruption_info": self.interruption_info,
            "artifact_ids": list(self.artifact_ids),
            "device_id": self.device_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkState":
        return cls(
            operation_id=data["operation_id"],
            goal=data["goal"],
            plan=data["plan"],
            status=LifecycleStatus(data["status"]),
            current_step=data.get("current_step", 0),
            total_steps=data.get("total_steps", 0),
            completed_steps=[
                StepRecord.from_dict(s) for s in data.get("completed_steps", [])
            ],
            checkpoint_step=data.get("checkpoint_step", 0),
            failure_info=data.get("failure_info"),
            interruption_info=data.get("interruption_info"),
            artifact_ids=data.get("artifact_ids", []),
            device_id=data.get("device_id"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


# ── Factory ──────────────────────────────────────────────────────

def create_operation(
    goal: str,
    plan: Dict[str, Any],
    device_id: Optional[str] = None,
) -> WorkState:
    """Create a new S18 work operation in CREATED state."""
    steps = plan.get("steps", [])
    return WorkState(
        operation_id=f"op-{uuid.uuid4().hex[:12]}",
        goal=goal,
        plan=plan,
        total_steps=len(steps),
        device_id=device_id,
    )


# ── Helpers ──────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
