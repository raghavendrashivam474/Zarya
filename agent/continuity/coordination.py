"""N5 — Cross-Device Coordination Layer & Flux Transport Boundary.

This module coordinates the cross-device continuity pipeline:
    1. Packages a clean ContinuityTransferRequest for Flux transport.
    2. Provides a protocol for the Flux transport adapter without leaking transport internals.
    3. Triggers target-side N4 continuation upon payload delivery.
    4. Correlates target execution operation_id back to continuity_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol

from agent.continuity.handoff import HandoffSession
from agent.continuity.identity import ContinuityOperation
from agent.continuity.result import ContinuationResult, ContinuationStatus, ContinuationStage
from agent.continuity.state import ContinuityState


@dataclass(frozen=True)
class ContinuityTransferRequest:
    """The clean transport boundary payload passed to Flux.

    Contains everything the target device needs to execute continuation:
        - continuity_id and work_id
        - source and target device identities
        - serialized PortableWork dictionary/payload
        - artifact manifest / requirements
    """
    continuity_id: str
    work_id: str
    source_device_id: str
    target_device_id: str
    portable_work_payload: Dict[str, Any]
    artifact_requirements: List[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.continuity_id.startswith("cont-"):
            errors.append(f"Invalid continuity_id: {self.continuity_id}")
        if not self.work_id:
            errors.append("work_id is required")
        if not self.source_device_id:
            errors.append("source_device_id is required")
        if not self.target_device_id:
            errors.append("target_device_id is required")
        if not self.portable_work_payload:
            errors.append("portable_work_payload cannot be empty")
        return errors


@dataclass(frozen=True)
class TransportResult:
    """Outcome of the Flux transport operation."""
    continuity_id: str
    success: bool
    transport_reference: str
    error_message: Optional[str] = None


class FluxTransportProvider(Protocol):
    """Protocol defining the required Flux interface for N5 continuity."""
    def transfer(self, request: ContinuityTransferRequest) -> TransportResult:
        ...


class DefaultTransportAdapter:
    """In-memory reference transport adapter for local testing and integration."""

    def __init__(self, should_succeed: bool = True, error_msg: Optional[str] = None):
        self.should_succeed = should_succeed
        self.error_msg = error_msg
        self.transferred_requests: List[ContinuityTransferRequest] = []

    def transfer(self, request: ContinuityTransferRequest) -> TransportResult:
        self.transferred_requests.append(request)
        if not self.should_succeed:
            return TransportResult(
                continuity_id=request.continuity_id,
                success=False,
                transport_reference=f"flux-err-{request.continuity_id}",
                error_message=self.error_msg or "Transport connection dropped",
            )
        return TransportResult(
            continuity_id=request.continuity_id,
            success=True,
            transport_reference=f"flux-xfer-{request.continuity_id}",
        )


class ContinuityCoordinator:
    """Orchestrates source handoff packaging, transport, and target continuation."""

    def __init__(
        self,
        transport: Optional[FluxTransportProvider] = None,
        target_executor: Optional[Callable[[Dict[str, Any]], ContinuationResult]] = None,
    ):
        self.transport = transport or DefaultTransportAdapter()
        self.target_executor = target_executor

    def prepare_transfer_request(
        self,
        session: HandoffSession,
        target_device_id: str,
        portable_work_payload: Dict[str, Any],
        artifact_requirements: Optional[List[str]] = None,
    ) -> ContinuityTransferRequest:
        """Construct and validate a ContinuityTransferRequest from an active session."""
        session.transition_to(ContinuityState.HANDOFF_PREPARING, "Constructing transport payload")

        req = ContinuityTransferRequest(
            continuity_id=session.operation.continuity_id,
            work_id=session.operation.work_id,
            source_device_id=session.operation.source_device_id,
            target_device_id=target_device_id,
            portable_work_payload=portable_work_payload,
            artifact_requirements=artifact_requirements or [],
        )

        errors = req.validate()
        if errors:
            raise ValueError(f"Invalid ContinuityTransferRequest: {', '.join(errors)}")

        return req

    def dispatch_transfer(
        self,
        session: HandoffSession,
        request: ContinuityTransferRequest,
    ) -> TransportResult:
        """Send the payload via Flux and update session state accordingly."""
        session.transition_to(ContinuityState.TRANSFERRING, "Dispatching to Flux transport")

        result = self.transport.transfer(request)
        if not result.success:
            session.transition_to(
                ContinuityState.TRANSFER_FAILED,
                reason=result.error_message or "Flux transport failed",
            )
        return result

    def deliver_and_execute_target(
        self,
        session: HandoffSession,
        request: ContinuityTransferRequest,
    ) -> ContinuationResult:
        """Deliver to target Zarya and execute via N4 target continuation engine."""
        if not self.target_executor:
            raise RuntimeError("No target executor configured for ContinuityCoordinator")

        session.transition_to(ContinuityState.TARGET_ACCEPTED, "Target Zarya accepted payload")
        session.transition_to(ContinuityState.TARGET_RUNNING, "Target execution started")

        result = self.target_executor(request.portable_work_payload)

        # Correlate target execution operation_id back to session operation
        if result.operation_id:
            updated_op = session.operation.with_target(
                target_device_id=request.target_device_id,
                target_operation_id=result.operation_id,
            )
            session.operation = updated_op

        return result
