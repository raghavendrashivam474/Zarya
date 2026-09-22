"""Integration tests for N1 context exports and end-to-end integration."""

import pytest
import agent.context as ctx
from agent.artifacts import ActiveComputerContext, ArtifactIdentity
from agent.lifecycle import WorkState, LifecycleStatus


def test_package_exports():
    """Verify that all N1 symbols are cleanly exported from agent.context."""
    assert hasattr(ctx, "UnifiedContext")
    assert hasattr(ctx, "DeviceContext")
    assert hasattr(ctx, "ComputerContext")
    assert hasattr(ctx, "BrowserContext")
    assert hasattr(ctx, "ArtifactReference")
    assert hasattr(ctx, "WorkReference")
    assert hasattr(ctx, "ContextObservation")
    assert hasattr(ctx, "ObservationProvenance")
    assert hasattr(ctx, "capture_unified_context")
    assert hasattr(ctx, "adapt_device_identity")
    assert hasattr(ctx, "adapt_window_observation")
    assert hasattr(ctx, "adapt_browser_observation")
    assert hasattr(ctx, "adapt_artifact_identity")
    assert hasattr(ctx, "adapt_work_state")
    assert hasattr(ctx, "adapt_active_computer_context")

    # Verify S16 & S17 exports are intact
    assert hasattr(ctx, "DeviceIdentity")
    assert hasattr(ctx, "DeviceRegistry")
    assert hasattr(ctx, "resolve_context_reference")
    assert hasattr(ctx, "CanonicalReference")


def test_end_to_end_context_flow():
    """Simulate a full end-to-end workflow capturing context at step execution."""
    # 1. Initialize local device identity
    dev = ctx.DeviceIdentity(
        device_id="node-dev-laptop",
        display_name="Dev Laptop",
        device_type=ctx.DeviceType.LAPTOP,
        platform=ctx.Platform.WINDOWS,
    )

    # 2. Simulate ActiveComputerContext holding S12/S13/S14 state
    acc = ActiveComputerContext()
    acc._active_application = "Terminal"
    acc._active_window_title = "PowerShell 7"
    acc._active_window_process = "pwsh.exe"

    art = ArtifactIdentity(
        artifact_id="art-output-log",
        artifact_type="log_file",
        canonical_locator="output.log",
        display_name="output.log",
        source_operation="op-build-1",
        verification_status="VERIFIED_SUCCESS",
    )
    acc._artifacts[art.artifact_id] = art

    # 3. Simulate S18 active work state
    work = WorkState(
        operation_id="op-build-1",
        goal="Build and verify project",
        plan={"steps": ["compile", "test", "package"]},
        status=LifecycleStatus.RUNNING,
        current_step=1,
        total_steps=3,
        artifact_ids=["art-output-log"],
        device_id=dev.device_id,
    )

    # 4. Capture snapshot via agent.context top-level capture function
    snapshot = ctx.capture_unified_context(
        device=dev,
        active_computer_context=acc,
        work=work,
        notes="Context captured right before step 2 execution",
    )

    # 5. Assert complete unified context invariants
    assert snapshot.platform == "WINDOWS"
    assert snapshot.device.device_id == "node-dev-laptop"
    assert snapshot.computer.active_application == "Terminal"
    assert snapshot.work.operation_id == "op-build-1"
    assert snapshot.work.status == "RUNNING"
    assert snapshot.work.current_step == 1
    assert len(snapshot.artifacts) == 1
    assert snapshot.artifacts[0].artifact_id == "art-output-log"

    # 6. Verify serialization for logging / LLM context injection
    payload = snapshot.to_dict()
    assert payload["device"]["device_id"] == "node-dev-laptop"
    assert payload["work"]["current_step"] == 1
    assert payload["artifacts"][0]["artifact_id"] == "art-output-log"