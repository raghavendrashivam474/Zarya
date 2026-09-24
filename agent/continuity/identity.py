"""N5 — Continuity Identity & Operation Correlation.

This module introduces continuity_id as a FIRST-CLASS identity that
correlates a source execution with a target execution across devices.

Identity hierarchy (DO NOT COLLAPSE):
    work_id          → logical work identity       (N2 owns)
    operation_id     → specific execution instance  (S18 owns)
    continuity_id    → cross-device handoff link    (N5 owns)

A single work_id can have multiple continuity_ids over its lifetime
(e.g., laptop → tablet, then tablet → desktop).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def generate_continuity_id() -> str:
    """Generate a globally unique continuity operation identifier.

    Format: 'cont-<uuid4>'
    Example: 'cont-a3f8c1d2-7b4e-4f9a-b6d1-8e2c3f4a5b6c'

    This is intentionally prefixed to distinguish from work_id and
    operation_id in logs, traces, and debugging output.
    """
    return f"cont-{uuid.uuid4()}"


@dataclass(frozen=True)
class ContinuityOperation:
    """Immutable record of a single cross-device handoff operation.

    This is the correlation spine that links:
        - source device + source execution
        - target device + target execution
        - the PortableWork payload that moved between them

    Lifecycle:
        Created by the source Zarya when a handoff is initiated.
        Updated (via replacement, since frozen) as the operation progresses.
        Persisted by N5 persistence layer — NOT by S18 checkpoint.

    IMPORTANT:
        - source_operation_id and target_operation_id are DIFFERENT.
          They are separate S18 executions on separate devices.
        - work_id is the SAME on both sides — it's the logical work.
        - continuity_id ties the two operations together.
    """

    continuity_id: str
    work_id: str
    source_device_id: str
    source_operation_id: str
    target_device_id: Optional[str] = None
    target_operation_id: Optional[str] = None
    portable_work_reference: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: Optional[str] = None
    transport_reference: Optional[str] = None
    notes: str = ""

    def with_target(
        self,
        target_device_id: str,
        target_operation_id: str,
    ) -> ContinuityOperation:
        """Return a new ContinuityOperation with target fields populated.

        Since this dataclass is frozen (immutable), we create a copy
        with the target execution correlation filled in. This happens
        when N4 on the target side accepts and begins execution.
        """
        return ContinuityOperation(
            continuity_id=self.continuity_id,
            work_id=self.work_id,
            source_device_id=self.source_device_id,
            source_operation_id=self.source_operation_id,
            target_device_id=target_device_id,
            target_operation_id=target_operation_id,
            portable_work_reference=self.portable_work_reference,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
            transport_reference=self.transport_reference,
            notes=self.notes,
        )

    def with_transport(self, transport_reference: str) -> ContinuityOperation:
        """Return a new ContinuityOperation with Flux transport reference."""
        return ContinuityOperation(
            continuity_id=self.continuity_id,
            work_id=self.work_id,
            source_device_id=self.source_device_id,
            source_operation_id=self.source_operation_id,
            target_device_id=self.target_device_id,
            target_operation_id=self.target_operation_id,
            portable_work_reference=self.portable_work_reference,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
            transport_reference=transport_reference,
            notes=self.notes,
        )

    @property
    def is_target_assigned(self) -> bool:
        """True if a target device has been selected for this handoff."""
        return self.target_device_id is not None

    @property
    def is_target_executing(self) -> bool:
        """True if the target has an active S18 operation."""
        return self.target_operation_id is not None

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty = valid).

        Checks structural integrity without reaching into N2/N4/S18.
        """
        errors: list[str] = []
        if not self.continuity_id.startswith("cont-"):
            errors.append(
                f"continuity_id must start with 'cont-': {self.continuity_id}"
            )
        if not self.work_id:
            errors.append("work_id cannot be empty")
        if not self.source_device_id:
            errors.append("source_device_id cannot be empty")
        if not self.source_operation_id:
            errors.append("source_operation_id cannot be empty")
        return errors
