"""N5 — Continuity Metadata Persistence & Idempotency Store.

GOLDEN RULE (Brief Section 17):
    S18 already persists execution checkpoints.
    N5 stores CONTINUITY METADATA only.
    Do NOT create a second copy of S18 state.

This module provides:
    1. ContinuityRecord: Immutable / serializable snapshot of a continuity operation.
    2. ContinuityStore: Thread-safe persistence interface (In-Memory + JSON-backed).
    3. Idempotency enforcement: Repeated requests for the same continuity_id
       are detected and deduplicated without re-executing.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.continuity.handoff import HandoffSession
from agent.continuity.identity import ContinuityOperation
from agent.continuity.reconciliation import ContinuityReconciliationReport
from agent.continuity.state import ContinuityState, is_terminal


@dataclass
class ContinuityRecord:
    """Persistent metadata snapshot for a cross-device handoff."""
    continuity_id: str
    work_id: str
    source_device_id: str
    source_operation_id: str
    target_device_id: Optional[str] = None
    target_operation_id: Optional[str] = None
    state: str = ContinuityState.HANDOFF_REQUESTED.value
    transport_reference: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    is_terminal: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_session(cls, session: HandoffSession) -> ContinuityRecord:
        """Derive a persistable record from an active HandoffSession."""
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            continuity_id=session.operation.continuity_id,
            work_id=session.operation.work_id,
            source_device_id=session.operation.source_device_id,
            source_operation_id=session.operation.source_operation_id,
            target_device_id=session.operation.target_device_id,
            target_operation_id=session.operation.target_operation_id,
            state=session.state.value,
            transport_reference=session.operation.transport_reference,
            created_at=session.operation.created_at,
            updated_at=now,
            is_terminal=is_terminal(session.state),
            details={"history_count": len(session.history)},
        )

    @classmethod
    def from_reconciliation(cls, report: ContinuityReconciliationReport) -> ContinuityRecord:
        """Derive a final persistable record from a reconciliation report."""
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            continuity_id=report.continuity_id,
            work_id=report.work_id,
            source_device_id=report.source_device_id,
            source_operation_id=report.source_operation_id,
            target_device_id=report.target_device_id,
            target_operation_id=report.target_operation_id,
            state=report.final_state.value,
            transport_reference=report.transport_reference,
            created_at=now,
            updated_at=now,
            is_terminal=is_terminal(report.final_state),
            details={
                "is_success": report.is_success,
                "recovery_action": report.recovery_action.value,
                "target_status": report.target_status,
                **report.details,
            },
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ContinuityRecord:
        return cls(**data)


class ContinuityStore:
    """Thread-safe storage and idempotency registry for continuity records."""

    def __init__(self, storage_path: Optional[str] = None):
        self._lock = threading.RLock()
        self._records: Dict[str, ContinuityRecord] = {}
        self.storage_path = storage_path

        if self.storage_path and os.path.exists(self.storage_path):
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for cid, item in data.items():
                    self._records[cid] = ContinuityRecord.from_dict(item)
        except Exception:
            self._records = {}

    def _save_to_disk(self) -> None:
        if not self.storage_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.storage_path)), exist_ok=True)
        serializable = {cid: rec.to_dict() for cid, rec in self._records.items()}
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)

    def save(self, record: ContinuityRecord) -> None:
        """Persist or update a ContinuityRecord."""
        with self._lock:
            record.updated_at = datetime.now(timezone.utc).isoformat()
            self._records[record.continuity_id] = record
            self._save_to_disk()

    def get(self, continuity_id: str) -> Optional[ContinuityRecord]:
        """Retrieve a record by its continuity_id."""
        with self._lock:
            return self._records.get(continuity_id)

    def exists(self, continuity_id: str) -> bool:
        """Check if a continuity_id has already been registered."""
        with self._lock:
            return continuity_id in self._records

    def list_by_work_id(self, work_id: str) -> List[ContinuityRecord]:
        """List all continuity operations associated with a specific work_id."""
        with self._lock:
            return [rec for rec in self._records.values() if rec.work_id == work_id]

    def list_active(self) -> List[ContinuityRecord]:
        """List all non-terminal continuity operations."""
        with self._lock:
            return [rec for rec in self._records.values() if not rec.is_terminal]

    def count(self) -> int:
        """Return total number of tracked continuity operations."""
        with self._lock:
            return len(self._records)
