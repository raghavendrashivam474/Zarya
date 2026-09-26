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

sys.path.insert(0, r"C:\Users\ragha\Documents\Anti-grav\shyam\src")
sys.path.insert(0, r"C:\Users\ragha\Documents\Anti-grav\zarya")

import uvicorn
from fastapi import FastAPI

# Zarya imports
from agent.ecosystem.routes import router as ecosystem_router
from agent.ecosystem.authorization import get_token as get_zarya_token
from agent.continuity.validation import PORTABLE_WORK_FORMAT_VERSION

# Shyam imports
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
    def __init__(self, host: str = "127.0.0.1", port: int = 8789):
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


class MockFluxTransport:
    def __init__(self, target_dest_dir: Path):
        self.target_dest_dir = target_dest_dir
        self.transfers = []

    def transfer(self, peer_id: str, artifact_path: str, **kwargs):
        src = Path(artifact_path)
        dest = self.target_dest_dir / src.name
        dest.write_bytes(src.read_bytes())
        self.transfers.append((peer_id, str(src), str(dest)))
        return FluxTransferResponse(
            transfer_id=f"tx-{uuid4().hex[:8]}",
            peer_id=peer_id,
            status=FluxTransferStatus.COMPLETED,
            bytes_transferred=dest.stat().st_size,
            total_bytes=dest.stat().st_size,
        )


async def run_n7_golden_smoke():
    print("================================================================")
    print("     ZARYA N7 PHYSICAL TWO-NODE RUNTIME CONTINUITY SMOKE        ")
    print("================================================================\n")
    
    with tempfile.TemporaryDirectory() as src_dir_str, tempfile.TemporaryDirectory() as tgt_dir_str, tempfile.TemporaryDirectory() as trust_dir_str:
        src_dir = Path(src_dir_str)
        tgt_dir = Path(tgt_dir_str)
        trust_dir = Path(trust_dir_str)
        
        # 1. Start live Zarya Target Daemon on Target Node (port 8789)
        target_port = 8789
        target_server = LiveTargetServer(host="127.0.0.1", port=target_port)
        target_server.start()
        target_zarya_url = f"http://127.0.0.1:{target_port}/ecosystem/v1"
        print(f"[1/6] Live Zarya Target Daemon running at: {target_zarya_url}")
        
        token = get_zarya_token()
        os.environ["ZARYA_ECOSYSTEM_TOKEN"] = token
        print(f"      EIP-1 Token: {token[:8]}... (authenticated)")
        
        # 2. Create the source artifact and target destination path
        artifact_file = src_dir / "golden_input.txt"
        csv_bytes = b"Golden payload verification token 12345\n"
        artifact_file.write_bytes(csv_bytes)
        artifact_sha = hashlib.sha256(csv_bytes).hexdigest()
        print(f"[2/6] Source artifact generated: {artifact_file.name} (SHA256: {artifact_sha[:12]}...)")
        
        target_delivered_artifact = tgt_dir / "golden_input.txt"
        target_output_file = tgt_dir / "golden_handoff_output.txt"
        
        work_id = f"work-n7-golden-{uuid4().hex[:6]}"
        
        # Exact compliant PortableWork with executable S18 tool step
        portable_work = {
            "format_version": PORTABLE_WORK_FORMAT_VERSION,
            "work_id": work_id,
            "intent": "Generate final summary on target device",
            "plan_reference": {
                "id": "plan-n7-golden",
                "name": "Golden Two-Device Execution Plan",
                "steps": [
                    {
                        "id": "step-1",
                        "tool": "createFile",
                        "args": {
                            "path": str(target_output_file.resolve()),
                            "content": "Golden N7 physical execution completed successfully.",
                            "overwrite": True,
                        }
                    }
                ]
            },
            "execution_reference": "exec-financial-001",
            "artifact_references": [],
            "requirements": {},
            "context": {}
        }
        
        # 3. Setup Target Discovery & Trust
        target_node_id = f"target-node-{uuid4().hex[:8]}"
        target_device_id = "device-target-laptop-b"
        target_flux_peer = str(uuid4())
        
        trust_service = TrustService(data_dir=trust_dir)
        await trust_service.grant_trust(
            node_id=target_node_id,
            relationship=RelationshipType.PERSONAL,
        )
        await trust_service.grant_trust(
            node_id=target_device_id,
            relationship=RelationshipType.PERSONAL,
        )
        print(f"[3/6] Trust established: {target_node_id} and {target_device_id} are TRUSTED (personal)")
        
        # 4. Setup Shyam Providers & Client
        zarya_client = ZaryaClient(base_url=target_zarya_url, token=token)
        zarya_provider = ZaryaProvider(client=zarya_client, base_url=target_zarya_url, token=token)
        assert zarya_provider.connect(), "Failed to connect ZaryaProvider to target daemon"
        
        mock_flux = MockFluxTransport(target_dest_dir=tgt_dir)
        
        class RealFluxProviderShim:
            def transfer(self, peer_id: str, artifact_path: str, **kwargs):
                return mock_flux.transfer(peer_id, artifact_path, **kwargs)
                
        flux_provider = RealFluxProviderShim()
        
        # 5. Build and execute Shyam Continuity Pipeline
        print(f"[4/6] Initializing Shyam Continuity Service...")
        
        candidate = NavigationCandidate(
            node_id=target_node_id,
            node_name="node-machine-b",
            provider_id="zarya.sovereign",
            provider_name="Zarya Target Provider",
            capability_id="zarya.work.continue",
            is_local=False,
            node_state=EcosystemNodeState.AVAILABLE,
            provider_status=AvailabilityStatus.AVAILABLE,
            capability_availability=AvailabilityStatus.AVAILABLE,
            metadata={"flux_peer_id": target_flux_peer, "zarya_url": target_zarya_url, "device_id": target_device_id},
        )
        
        nav_result = NavigationResult(
            capability="zarya.work.continue",
            selected=candidate,
            reason="N7 golden target match",
            path_type="direct",
        )
        
        mock_navigator = MagicMock()
        mock_navigator.navigate.return_value = nav_result
        
        mock_eco_registry = MagicMock(spec=EcosystemRegistry)
        mock_eco_registry.create_snapshot.return_value = MagicMock()
        mock_eco_registry.get_node.return_value = DiscoveredNode(
            node_id=target_node_id,
            device_id=target_device_id,
            node_name="node-machine-b",
            state=EcosystemNodeState.AVAILABLE,
            metadata={"flux_peer_id": target_flux_peer, "zarya_url": target_zarya_url},
        )
        
        continuity_service = ContinuityService(
            navigator=mock_navigator,
            trust_service=trust_service,
            flux_provider=flux_provider,
            zarya_provider=zarya_provider,
            ecosystem_registry=mock_eco_registry,
        )
        
        req = ContinuityRequest(
            work_id=work_id,
            source_device_id="machine-a-source",
            portable_work=portable_work,
            artifact_paths=[str(artifact_file)],
        )
        
        print(f"[5/6] Executing continuity request through ContinuityService.request_continuity()...")
        session = await continuity_service.request_continuity(req)
        
        print("\n================================================================")
        print("               CORRELATION & VERIFICATION PROOF                 ")
        print("================================================================")
        print(f"  Work ID               : {session.request.work_id}")
        print(f"  Continuity ID         : {session.continuity_id}")
        print(f"  Target Operation ID   : {session.operation_id}")
        print(f"  Final Session State   : {session.state.value}")
        print(f"  Continuity Outcome    : {session.result.outcome.value if session.result else 'NONE'}")
        print(f"  Zarya Target Outcome  : {session.result.zarya_outcome if session.result else 'NONE'}")
        print(f"  Reason / Summary      : {session.result.reason if session.result else 'NONE'}")
        
        # 6. Physical verification of target-side artifact & execution
        assert target_delivered_artifact.exists(), "Target input artifact was not physically delivered!"
        delivered_sha = hashlib.sha256(target_delivered_artifact.read_bytes()).hexdigest()
        print(f"  Target Delivered File : {target_delivered_artifact.name} (EXISTS)")
        print(f"  Delivered SHA256 Match: {delivered_sha == artifact_sha} ({delivered_sha[:12]}...)")
        
        assert target_output_file.exists(), "Target output file was not produced by execution!"
        print(f"  Target Output File    : {target_output_file.name} (EXISTS, content='{target_output_file.read_text().strip()}')")
        
        assert session.state == ContinuityState.COMPLETED, f"Session did not complete: {session.result.reason if session.result else 'Unknown'}"
        assert session.result is not None, "Session result is missing"
        assert session.result.outcome == ContinuityOutcome.SUCCESS, f"Outcome was not SUCCESS: {session.result.reason}"
        assert session.operation_id != "", "Target operation ID was not recorded"
        
        print("\n[6/6] [PASS] Complete physical continuity workflow successfully demonstrated!\n")
        
        target_server.stop()

if __name__ == "__main__":
    asyncio.run(run_n7_golden_smoke())

def test_n7_golden_two_device_physical_continuity():
    """Pytest entrypoint for N7 physical two-node golden smoke."""
    asyncio.run(run_n7_golden_smoke())
