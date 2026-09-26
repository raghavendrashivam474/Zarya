import asyncio
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4
from unittest.mock import MagicMock
import pytest

sys.path.insert(0, r"C:\Users\ragha\Documents\Anti-grav\shyam\src")
sys.path.insert(0, r"C:\Users\ragha\Documents\Anti-grav\Zarya")

import uvicorn
from fastapi import FastAPI

# Zarya imports
from agent.ecosystem.routes import router as ecosystem_router
from agent.ecosystem.authorization import get_token as get_zarya_token
from agent.continuity.validation import PORTABLE_WORK_FORMAT_VERSION

# Shyam imports
from shyam.continuity.errors import DuplicateContinuityError
from shyam.continuity.service import ContinuityService
from shyam.continuity.models import (
    ContinuityOutcome,
    ContinuityRequest,
    ContinuitySession,
    ContinuityState,
    ContinuityTarget,
)
from shyam.discovery.ecosystem_registry import EcosystemRegistry
from shyam.discovery.ecosystem_models import DiscoveredNode, EcosystemNodeState
from shyam.capabilities.model import AvailabilityStatus
from shyam.trust.service import TrustService
from shyam.trust.models import TrustRecord, TrustStatus, RelationshipType
from shyam.navigation.models import NavigationResult, NavigationCandidate
from shyam.providers.zarya.client import ZaryaClient
from shyam.providers.zarya.provider import ZaryaProvider
from shyam.providers.flux.models import FluxTransferResponse, FluxTransferStatus


class LiveTargetServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8790):
        self.host = host
        self.port = port
        self.app = FastAPI(title="Zarya Target Daemon")
        self.app.include_router(ecosystem_router)
        self.server = None
        self.thread = None

    def start(self):
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="error")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        time.sleep(1.0)

    def stop(self):
        if self.server:
            self.server.should_exit = True
            if self.thread:
                self.thread.join(timeout=2.0)


def test_failure_matrix_case_a_target_offline():
    """Case A: Target offline -> truth preserved as FAILED."""
    async def _run():
        with tempfile.TemporaryDirectory() as src_dir_str, tempfile.TemporaryDirectory() as trust_dir_str:
            src_dir = Path(src_dir_str)
            trust_dir = Path(trust_dir_str)
            dead_zarya_url = "http://127.0.0.1:8799/ecosystem/v1"
            
            trust_service = TrustService(data_dir=trust_dir)
            await trust_service.grant_trust(node_id="target-offline-node", relationship=RelationshipType.PERSONAL)
            
            zarya_client = ZaryaClient(base_url=dead_zarya_url, token="token-dummy", timeout=1.0)
            zarya_provider = ZaryaProvider(client=zarya_client, base_url=dead_zarya_url)
            
            mock_flux = MagicMock()
            mock_flux.transfer.return_value = FluxTransferResponse(
                transfer_id="tx-test", peer_id="peer-test", status=FluxTransferStatus.COMPLETED
            )
            
            candidate = NavigationCandidate(
                node_id="target-offline-node",
                node_name="node-offline",
                provider_id="zarya.sovereign",
                provider_name="Zarya Offline Provider",
                capability_id="zarya.work.continue",
                is_local=False,
                node_state=EcosystemNodeState.AVAILABLE,
                provider_status=AvailabilityStatus.AVAILABLE,
                capability_availability=AvailabilityStatus.AVAILABLE,
                metadata={"flux_peer_id": "peer-1", "zarya_url": dead_zarya_url, "device_id": "target-offline-node"},
            )
            
            mock_navigator = MagicMock()
            mock_navigator.navigate.return_value = NavigationResult(
                capability="zarya.work.continue", selected=candidate, reason="Target Match", path_type="direct"
            )
            mock_eco_registry = MagicMock(spec=EcosystemRegistry)
            mock_eco_registry.create_snapshot.return_value = MagicMock()
            
            continuity_service = ContinuityService(
                navigator=mock_navigator,
                trust_service=trust_service,
                flux_provider=mock_flux,
                zarya_provider=zarya_provider,
                ecosystem_registry=mock_eco_registry,
            )
            
            pw = {
                "format_version": PORTABLE_WORK_FORMAT_VERSION,
                "work_id": "work-fail-a",
                "intent": "Test offline target",
                "plan_reference": {"id": "p1", "name": "Plan", "steps": [{"id": "s1", "tool": "listFiles", "args": {}}]},
            }
            
            req = ContinuityRequest(work_id="work-fail-a", source_device_id="dev-a", portable_work=pw)
            session = await continuity_service.request_continuity(req)
            
            assert session.state == ContinuityState.FAILED
            assert session.result is not None
            assert session.result.outcome == ContinuityOutcome.FAILED

    asyncio.run(_run())


def test_failure_matrix_case_b_flux_transport_failure():
    """Case B: Flux transport failure -> work execution aborted, state FAILED."""
    async def _run():
        with tempfile.TemporaryDirectory() as src_dir_str, tempfile.TemporaryDirectory() as trust_dir_str:
            src_dir = Path(src_dir_str)
            trust_dir = Path(trust_dir_str)
            dummy_art = src_dir / "test.txt"
            dummy_art.write_bytes(b"data")
            
            trust_service = TrustService(data_dir=trust_dir)
            await trust_service.grant_trust(node_id="target-flux-fail", relationship=RelationshipType.PERSONAL)
            
            class FailingFluxTransport:
                def transfer(self, peer_id: str, artifact_path: str, **kwargs):
                    raise ConnectionError("Flux transport peer unreachable")
                    
            candidate = NavigationCandidate(
                node_id="target-flux-fail",
                node_name="node-flux-fail",
                provider_id="zarya.sovereign",
                provider_name="Zarya Provider",
                capability_id="zarya.work.continue",
                is_local=False,
                node_state=EcosystemNodeState.AVAILABLE,
                provider_status=AvailabilityStatus.AVAILABLE,
                capability_availability=AvailabilityStatus.AVAILABLE,
                metadata={"flux_peer_id": "peer-f", "zarya_url": "http://127.0.0.1:8790/ecosystem/v1", "device_id": "target-flux-fail"},
            )
            mock_navigator = MagicMock()
            mock_navigator.navigate.return_value = NavigationResult(
                capability="zarya.work.continue", selected=candidate, reason="Target Match", path_type="direct"
            )
            mock_eco_registry = MagicMock(spec=EcosystemRegistry)
            mock_eco_registry.create_snapshot.return_value = MagicMock()
            
            mock_zarya = MagicMock()
            
            continuity_service = ContinuityService(
                navigator=mock_navigator,
                trust_service=trust_service,
                flux_provider=FailingFluxTransport(),
                zarya_provider=mock_zarya,
                ecosystem_registry=mock_eco_registry,
            )
            
            pw = {
                "format_version": PORTABLE_WORK_FORMAT_VERSION,
                "work_id": "work-fail-b",
                "intent": "Test flux fail",
                "plan_reference": {"id": "p1", "name": "Plan", "steps": [{"id": "s1", "tool": "listFiles", "args": {}}]},
            }
            
            req = ContinuityRequest(work_id="work-fail-b", source_device_id="dev-a", portable_work=pw, artifact_paths=[str(dummy_art)])
            session = await continuity_service.request_continuity(req)
            
            assert session.state == ContinuityState.FAILED
            assert session.result is not None
            assert session.result.outcome == ContinuityOutcome.FAILED
            mock_zarya.continue_work.assert_not_called()

    asyncio.run(_run())


def test_failure_matrix_case_c_target_execution_failure():
    """Case C: Target execution failure -> proves Transport success != Work success."""
    async def _run():
        target_server = LiveTargetServer(port=8791)
        target_server.start()
        try:
            with tempfile.TemporaryDirectory() as trust_dir_str:
                trust_dir = Path(trust_dir_str)
                target_url = "http://127.0.0.1:8791/ecosystem/v1"
                token = get_zarya_token()
                os.environ["ZARYA_ECOSYSTEM_TOKEN"] = token
                
                trust_service = TrustService(data_dir=trust_dir)
                await trust_service.grant_trust(node_id="target-node-c", relationship=RelationshipType.PERSONAL)
                
                zarya_client = ZaryaClient(base_url=target_url, token=token)
                zarya_provider = ZaryaProvider(client=zarya_client, base_url=target_url, token=token)
                assert zarya_provider.connect()
                
                mock_flux = MagicMock()
                mock_flux.transfer.return_value = FluxTransferResponse(
                    transfer_id="tx-c", peer_id="peer-c", status=FluxTransferStatus.COMPLETED
                )
                
                candidate = NavigationCandidate(
                    node_id="target-node-c",
                    node_name="node-c",
                    provider_id="zarya.sovereign",
                    provider_name="Zarya Provider",
                    capability_id="zarya.work.continue",
                    is_local=False,
                    node_state=EcosystemNodeState.AVAILABLE,
                    provider_status=AvailabilityStatus.AVAILABLE,
                    capability_availability=AvailabilityStatus.AVAILABLE,
                    metadata={"flux_peer_id": "peer-c", "zarya_url": target_url, "device_id": "target-node-c"},
                )
                mock_navigator = MagicMock()
                mock_navigator.navigate.return_value = NavigationResult(
                    capability="zarya.work.continue", selected=candidate, reason="Target Match", path_type="direct"
                )
                mock_eco_registry = MagicMock(spec=EcosystemRegistry)
                mock_eco_registry.create_snapshot.return_value = MagicMock()
                
                continuity_service = ContinuityService(
                    navigator=mock_navigator,
                    trust_service=trust_service,
                    flux_provider=mock_flux,
                    zarya_provider=zarya_provider,
                    ecosystem_registry=mock_eco_registry,
                )
                
                pw_failing = {
                    "format_version": PORTABLE_WORK_FORMAT_VERSION,
                    "work_id": "work-fail-c",
                    "intent": "Read non existent file",
                    "plan_reference": {
                        "id": "p-fail",
                        "name": "Failing Plan",
                        "steps": [
                            {
                                "id": "step-fail",
                                "tool": "readFile",
                                "args": {"path": "C:\\non_existent_path_123456789.txt"},
                            }
                        ]
                    }
                }
                
                req = ContinuityRequest(work_id="work-fail-c", source_device_id="dev-a", portable_work=pw_failing)
                session = await continuity_service.request_continuity(req)
                
                assert session.state == ContinuityState.FAILED
                assert session.result is not None
                assert session.result.outcome == ContinuityOutcome.FAILED
                assert session.result.transfer_completed == True
                assert session.result.zarya_outcome == "VERIFIED_FAILURE"
        finally:
            target_server.stop()

    asyncio.run(_run())


def test_failure_matrix_case_d_unknown_preservation():
    """Case D: UNKNOWN indeterminate outcome preserved strictly."""
    async def _run():
        with tempfile.TemporaryDirectory() as trust_dir_str:
            trust_dir = Path(trust_dir_str)
            trust_service = TrustService(data_dir=trust_dir)
            await trust_service.grant_trust(node_id="target-node-d", relationship=RelationshipType.PERSONAL)
            
            from shyam.providers.zarya.models import ContinuationResponse, VerificationOutcome
            mock_zarya = MagicMock()
            mock_zarya.continue_work.return_value = ContinuationResponse(
                operation_id="op-unk-1",
                outcome=VerificationOutcome.UNKNOWN,
                reconstruction_completed=True,
                execution_completed=False,
                summary="Target process killed before verification completed",
            )
            
            mock_flux = MagicMock()
            mock_flux.transfer.return_value = FluxTransferResponse(
                transfer_id="tx-d", peer_id="peer-d", status=FluxTransferStatus.COMPLETED
            )
            
            candidate = NavigationCandidate(
                node_id="target-node-d",
                node_name="node-d",
                provider_id="zarya.sovereign",
                provider_name="Zarya Provider",
                capability_id="zarya.work.continue",
                is_local=False,
                node_state=EcosystemNodeState.AVAILABLE,
                provider_status=AvailabilityStatus.AVAILABLE,
                capability_availability=AvailabilityStatus.AVAILABLE,
                metadata={"flux_peer_id": "peer-d", "zarya_url": "http://127.0.0.1:8790", "device_id": "target-node-d"},
            )
            mock_navigator = MagicMock()
            mock_navigator.navigate.return_value = NavigationResult(
                capability="zarya.work.continue", selected=candidate, reason="Target Match", path_type="direct"
            )
            mock_eco_registry = MagicMock(spec=EcosystemRegistry)
            mock_eco_registry.create_snapshot.return_value = MagicMock()
            
            continuity_service = ContinuityService(
                navigator=mock_navigator,
                trust_service=trust_service,
                flux_provider=mock_flux,
                zarya_provider=mock_zarya,
                ecosystem_registry=mock_eco_registry,
            )
            
            pw = {
                "format_version": PORTABLE_WORK_FORMAT_VERSION,
                "work_id": "work-unk-d",
                "intent": "Unknown test",
                "plan_reference": {"id": "p1", "name": "Plan", "steps": [{"id": "s1", "tool": "listFiles", "args": {}}]},
            }
            
            req = ContinuityRequest(work_id="work-unk-d", source_device_id="dev-a", portable_work=pw)
            session = await continuity_service.request_continuity(req)
            
            assert session.state == ContinuityState.UNKNOWN
            assert session.result is not None
            assert session.result.outcome == ContinuityOutcome.UNKNOWN
            assert session.result.zarya_outcome == "UNKNOWN"

    asyncio.run(_run())


def test_failure_matrix_case_e_duplicate_blocking():
    """Case E: Duplicate continuity request blocked by idempotency lock."""
    async def _run():
        with tempfile.TemporaryDirectory() as trust_dir_str:
            trust_dir = Path(trust_dir_str)
            trust_service = TrustService(data_dir=trust_dir)
            await trust_service.grant_trust(node_id="target-node-e", relationship=RelationshipType.PERSONAL)
            
            mock_zarya = MagicMock()
            mock_flux = MagicMock()
            
            candidate = NavigationCandidate(
                node_id="target-node-e",
                node_name="node-e",
                provider_id="zarya.sovereign",
                provider_name="Zarya Provider",
                capability_id="zarya.work.continue",
                is_local=False,
                node_state=EcosystemNodeState.AVAILABLE,
                provider_status=AvailabilityStatus.AVAILABLE,
                capability_availability=AvailabilityStatus.AVAILABLE,
                metadata={"flux_peer_id": "peer-e", "zarya_url": "http://127.0.0.1:8790", "device_id": "target-node-e"},
            )
            mock_navigator = MagicMock()
            mock_navigator.navigate.return_value = NavigationResult(
                capability="zarya.work.continue", selected=candidate, reason="Target Match", path_type="direct"
            )
            mock_eco_registry = MagicMock(spec=EcosystemRegistry)
            mock_eco_registry.create_snapshot.return_value = MagicMock()
            
            continuity_service = ContinuityService(
                navigator=mock_navigator,
                trust_service=trust_service,
                flux_provider=mock_flux,
                zarya_provider=mock_zarya,
                ecosystem_registry=mock_eco_registry,
            )
            
            dup_work_id = "work-dup-test"
            active_sess = ContinuitySession(
                request=ContinuityRequest(work_id=dup_work_id, source_device_id="dev-a", portable_work={"format_version": PORTABLE_WORK_FORMAT_VERSION, "work_id": dup_work_id, "intent": "dup", "plan_reference": {"id": "p", "steps": [{"id": "s", "tool": "t", "args": {}}]}}),
                state=ContinuityState.CONTINUING,
            )
            continuity_service._sessions[active_sess.continuity_id] = active_sess
            continuity_service._work_continuities[dup_work_id] = active_sess.continuity_id
            
            duplicate_caught = False
            try:
                dup_req = ContinuityRequest(work_id=dup_work_id, source_device_id="dev-a", portable_work=active_sess.request.portable_work)
                await continuity_service.request_continuity(dup_req)
            except DuplicateContinuityError:
                duplicate_caught = True
                
            assert duplicate_caught, "Duplicate continuity request was not blocked!"

    asyncio.run(_run())


def test_failure_matrix_case_f_source_disappearance_autonomy():
    """Case F: Source disappearance -> target continues autonomously."""
    target_server = LiveTargetServer(port=8792)
    target_server.start()
    try:
        with tempfile.TemporaryDirectory() as tgt_dir_str:
            tgt_dir = Path(tgt_dir_str)
            target_out = tgt_dir / "autonomous_out.txt"
            target_url = "http://127.0.0.1:8792/ecosystem/v1"
            token = get_zarya_token()
            
            zarya_client = ZaryaClient(base_url=target_url, token=token)
            
            pw_autonomous = {
                "format_version": PORTABLE_WORK_FORMAT_VERSION,
                "work_id": "work-autonomous-f",
                "intent": "Autonomous target work",
                "plan_reference": {
                    "id": "p-auton",
                    "name": "Autonomous Plan",
                    "steps": [
                        {
                            "id": "step-auton",
                            "tool": "createFile",
                            "args": {
                                "path": str(target_out.resolve()),
                                "content": "Source disconnected; target executed autonomously.",
                                "overwrite": True,
                            }
                        }
                    ]
                }
            }
            
            continuation_resp = zarya_client.continue_work(
                portable_work=pw_autonomous,
                source_device_id="source-machine-now-offline",
                continuity_id="cont-auton-999",
            )
            
            assert continuation_resp.outcome == "VERIFIED_SUCCESS"
            assert target_out.exists()
            assert "target executed autonomously" in target_out.read_text()
    finally:
        target_server.stop()
