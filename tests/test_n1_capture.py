"""Tests for N1 context capture orchestrator (agent/context/capture.py).

Verifies snapshot assembly from direct parameters, ActiveComputerContext,
overrides, artifact deduplication, and mobile scenarios.
"""

import pytest

from agent.context.capture import capture_unified_context
from agent.context.device import DeviceIdentity, Platform, DeviceType, TrustState
from agent.context.unified import ContextObservation, UnifiedContext
from agent.artifacts import ArtifactIdentity, ActiveComputerContext
from agent.tools.desktop_observer import WindowObservation
from agent.tools.browser_observer import BrowserObservation
from agent.lifecycle import WorkState, LifecycleStatus
from agent.state import StateFreshness


def test_empty_capture():
    """Capture with no arguments produces a clean snapshot."""
    ctx = capture_unified_context()
    assert isinstance(ctx, UnifiedContext)
    assert ctx.platform == "UNKNOWN"
    assert ctx.device is None
    assert ctx.computer is None
    assert ctx.browser is None
    assert ctx.artifacts is None
    assert ctx.work is None
    assert ctx.observations is None
    assert ctx.notes is None


def test_direct_parameter_capture():
    """Capture with explicit S17, S13, S14, S18, and S12 objects."""
    dev = DeviceIdentity(
        device_id="dev-ws-01",
        display_name="Workstation Primary",
        device_type=DeviceType.DESKTOP,
        platform=Platform.WINDOWS,
    )
    desktop = WindowObservation(
        title="Visual Studio Code",
        hwnd=0x1001,
        process_name="Code.exe",
        process_id=5000,
        observed_at="2025-01-01T12:00:00Z",
        freshness=StateFreshness.CURRENT.value,
        evidence="win32_api",
    )
    browser = BrowserObservation(
        browser_name="chrome",
        page_url="https://docs.zarya.ai",
        page_title="Zarya Docs",
        observed_at="2025-01-01T12:00:00Z",
        freshness=StateFreshness.CURRENT.value,
        evidence="cdp",
        status="VERIFIED_SUCCESS",
    )
    art = ArtifactIdentity(
        artifact_id="art-code-1",
        artifact_type="file",
        canonical_locator="capture.py",
        display_name="capture.py",
        source_operation="op-edit",
        verification_status="VERIFIED_SUCCESS",
    )
    work = WorkState(
        operation_id="op-test-capture",
        goal="Verify capture logic",
        plan={},
        status=LifecycleStatus.RUNNING,
        current_step=1,
        total_steps=2,
    )

    ctx = capture_unified_context(
        device=dev,
        desktop_observation=desktop,
        browser_observation=browser,
        artifacts=[art],
        work=work,
        notes="All parameters explicit",
    )

    assert ctx.platform == "WINDOWS"
    assert ctx.device is not None
    assert ctx.device.device_id == "dev-ws-01"
    assert ctx.computer is not None
    assert ctx.computer.active_application == "Code.exe"
    assert ctx.computer.platform_detail == {"hwnd": 0x1001}
    assert ctx.browser is not None
    assert ctx.browser.page_url == "https://docs.zarya.ai"
    assert ctx.artifacts is not None
    assert len(ctx.artifacts) == 1
    assert ctx.artifacts[0].artifact_id == "art-code-1"
    assert ctx.work is not None
    assert ctx.work.operation_id == "op-test-capture"
    assert ctx.notes == "All parameters explicit"


def test_capture_from_active_computer_context():
    """Capture automatically pulls desktop, browser, and artifacts from ACC."""
    acc = ActiveComputerContext()
    acc._active_application = "Slack"
    acc._active_window_title = "Zarya Dev Channel"
    acc._active_window_process = "slack.exe"
    acc._desktop_observed_at = "2025-01-01T12:00:00Z"
    acc._desktop_freshness = StateFreshness.CURRENT.value

    acc._browser_name = "brave"
    acc._browser_url = "https://internal.dashboard"
    acc._browser_title = "Dashboard"
    acc._browser_status = "VERIFIED_SUCCESS"

    art = ArtifactIdentity(
        artifact_id="art-slack-log",
        artifact_type="file",
        canonical_locator="slack.log",
        display_name="slack.log",
        source_operation="op-slack",
    )
    acc._artifacts[art.artifact_id] = art

    ctx = capture_unified_context(active_computer_context=acc)

    assert ctx.computer is not None
    assert ctx.computer.active_application == "Slack"
    assert ctx.computer.window_title == "Zarya Dev Channel"
    assert ctx.browser is not None
    assert ctx.browser.browser_name == "brave"
    assert ctx.artifacts is not None
    assert len(ctx.artifacts) == 1
    assert ctx.artifacts[0].artifact_id == "art-slack-log"


def test_direct_observation_overrides_acc():
    """Explicit desktop/browser observation takes precedence over ACC cache."""
    acc = ActiveComputerContext()
    acc._active_application = "OldApp"
    acc._active_window_title = "Old Window"

    fresh_desktop = WindowObservation(
        title="Fresh Window",
        hwnd=0x9999,
        process_name="FreshApp.exe",
        process_id=7777,
        observed_at="2025-01-01T12:05:00Z",
        freshness=StateFreshness.CURRENT.value,
        evidence="direct_hook",
    )

    ctx = capture_unified_context(
        active_computer_context=acc,
        desktop_observation=fresh_desktop,
    )

    assert ctx.computer is not None
    assert ctx.computer.active_application == "FreshApp.exe"
    assert ctx.computer.window_title == "Fresh Window"
    assert ctx.computer.provenance.method == "direct_hook"


def test_artifact_deduplication():
    """Artifacts present in both ACC and explicit list are deduplicated by artifact_id."""
    acc = ActiveComputerContext()
    art1 = ArtifactIdentity(
        artifact_id="art-shared-1",
        artifact_type="file",
        canonical_locator="shared.txt",
        display_name="shared.txt",
        source_operation="op-1",
    )
    acc._artifacts[art1.artifact_id] = art1

    art2 = ArtifactIdentity(
        artifact_id="art-shared-1",  # duplicate ID
        artifact_type="file",
        canonical_locator="shared_v2.txt",
        display_name="shared_v2.txt",
        source_operation="op-2",
    )
    art3 = ArtifactIdentity(
        artifact_id="art-unique-3",
        artifact_type="file",
        canonical_locator="unique.txt",
        display_name="unique.txt",
        source_operation="op-3",
    )

    ctx = capture_unified_context(
        active_computer_context=acc,
        artifacts=[art2, art3],
    )

    assert ctx.artifacts is not None
    assert len(ctx.artifacts) == 2
    art_ids = [a.artifact_id for a in ctx.artifacts]
    assert "art-shared-1" in art_ids
    assert "art-unique-3" in art_ids


def test_android_mobile_capture_scenario():
    """Simulate Android environment: phone device, work, no desktop window."""
    dev = {
        "device_id": "android-pixel-8",
        "display_name": "Pixel 8 Pro",
        "device_type": "PHONE",
        "platform": "ANDROID",
    }
    work = {
        "operation_id": "op-android-sync",
        "status": "RUNNING",
        "current_step": 3,
        "total_steps": 4,
    }
    mobile_obs = ContextObservation(
        domain="mobile_telephony",
        subject="network_carrier",
        state={"carrier": "Jio 5G", "signal_strength": -85},
        status="VERIFIED_SUCCESS",
    )

    ctx = capture_unified_context(
        device=dev,
        work=work,
        custom_observations=[mobile_obs],
        notes="Android field test",
    )

    assert ctx.platform == "ANDROID"
    assert ctx.device is not None
    assert ctx.device.device_type == "PHONE"
    assert ctx.computer is None  # no desktop window on mobile
    assert ctx.browser is None
    assert ctx.work is not None
    assert ctx.work.operation_id == "op-android-sync"
    assert ctx.observations is not None
    assert len(ctx.observations) == 1
    assert ctx.observations[0].domain == "mobile_telephony"

    # Verify serialization
    d = ctx.to_dict()
    assert d["platform"] == "ANDROID"
    assert d["computer"] is None
    assert d["work"]["status"] == "RUNNING"