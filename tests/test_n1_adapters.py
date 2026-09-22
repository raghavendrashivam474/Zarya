"""Tests for N1 context adapters (agent/context/adapters.py).

Verifies clean adaptation from S12, S13, S14, S17, and S18 into N1 types.
Ensures zero mutations on existing models and complete provenance tracking.
"""

import pytest

from agent.context.adapters import (
    adapt_device_identity,
    adapt_window_observation,
    adapt_browser_observation,
    adapt_artifact_identity,
    adapt_work_state,
    adapt_active_computer_context,
)
from agent.context.device import DeviceIdentity, Platform, DeviceType, TrustState
from agent.tools.desktop_observer import WindowObservation
from agent.tools.browser_observer import BrowserObservation
from agent.artifacts import ArtifactIdentity, ActiveComputerContext
from agent.lifecycle import WorkState, LifecycleStatus
from agent.state import StateFreshness


# ---------------------------------------------------------------------------
# 1. S17 Device Identity Adapter
# ---------------------------------------------------------------------------

def test_adapt_device_identity_from_object():
    """Adapt real DeviceIdentity object."""
    dev = DeviceIdentity(
        device_id="dev-win-01",
        display_name="Workstation Primary",
        device_type=DeviceType.DESKTOP,
        platform=Platform.WINDOWS,
        capabilities=frozenset(["browser", "terminal"]),
        trust_state=TrustState.TRUSTED,
    )
    res = adapt_device_identity(dev)
    assert res is not None
    assert res.device_id == "dev-win-01"
    assert res.platform == "WINDOWS"
    assert res.device_type == "DESKTOP"
    assert res.display_name == "Workstation Primary"
    assert res.provenance is not None
    assert res.provenance.source == "s17_device_identity"
    assert res.provenance.freshness == StateFreshness.CURRENT.value


def test_adapt_device_identity_from_dict():
    """Adapt device dict."""
    dev_dict = {
        "device_id": "phone-pixel-02",
        "display_name": "Pixel 8",
        "device_type": "PHONE",
        "platform": "ANDROID",
    }
    res = adapt_device_identity(dev_dict)
    assert res is not None
    assert res.device_id == "phone-pixel-02"
    assert res.platform == "ANDROID"
    assert res.device_type == "PHONE"


# ---------------------------------------------------------------------------
# 2. S13 Desktop / Window Observation Adapter
# ---------------------------------------------------------------------------

def test_adapt_window_observation_from_object():
    """Adapt real WindowObservation object."""
    obs = WindowObservation(
        title="Visual Studio Code - Zarya",
        hwnd=0x123456,
        process_name="Code.exe",
        process_id=9876,
        observed_at="2025-01-01T12:00:00Z",
        freshness=StateFreshness.CURRENT.value,
        evidence="EnumWindows",
    )
    res = adapt_window_observation(obs)
    assert res is not None
    assert res.active_application == "Code.exe"
    assert res.window_title == "Visual Studio Code - Zarya"
    assert res.process_id == 9876
    assert res.platform_detail is not None
    assert res.platform_detail["hwnd"] == 0x123456
    assert res.provenance is not None
    assert res.provenance.source == "s13_desktop_observer"
    assert res.provenance.freshness == StateFreshness.CURRENT.value
    assert res.provenance.method == "EnumWindows"


def test_adapt_window_observation_from_dict():
    """Adapt window dict without hwnd (e.g. mobile/headless)."""
    obs_dict = {
        "title": "Chrome",
        "process_name": "chrome",
        "process_id": 4321,
        "freshness": StateFreshness.STALE.value,
    }
    res = adapt_window_observation(obs_dict)
    assert res is not None
    assert res.active_application == "chrome"
    assert res.platform_detail is None  # no hwnd provided
    assert res.provenance.freshness == StateFreshness.STALE.value


# ---------------------------------------------------------------------------
# 3. S14 Browser Observation Adapter
# ---------------------------------------------------------------------------

def test_adapt_browser_observation_from_object():
    """Adapt real BrowserObservation object."""
    obs = BrowserObservation(
        browser_name="chrome",
        page_url="https://github.com/zarya",
        page_title="GitHub - Zarya Project",
        observed_at="2025-01-01T12:00:00Z",
        freshness=StateFreshness.CURRENT.value,
        evidence="playwright_cdp_poll",
        status="VERIFIED_SUCCESS",
    )
    res = adapt_browser_observation(obs)
    assert res is not None
    assert res.browser_name == "chrome"
    assert res.page_url == "https://github.com/zarya"
    assert res.page_title == "GitHub - Zarya Project"
    assert res.status == "VERIFIED_SUCCESS"
    assert res.provenance.source == "s14_browser_observer"
    assert res.provenance.freshness == StateFreshness.CURRENT.value


# ---------------------------------------------------------------------------
# 4. S12 Artifact Identity Adapter
# ---------------------------------------------------------------------------

def test_adapt_artifact_identity_from_object():
    """Adapt real ArtifactIdentity object."""
    art = ArtifactIdentity(
        artifact_id="art-log-42",
        artifact_type="log_file",
        canonical_locator="/var/log/zarya.log",
        display_name="zarya.log",
        source_operation="op-init",
        verification_status="VERIFIED_SUCCESS",
    )
    res = adapt_artifact_identity(art)
    assert res is not None
    assert res.artifact_id == "art-log-42"
    assert res.artifact_type == "log_file"
    assert res.display_name == "zarya.log"
    assert res.verification_status == "VERIFIED_SUCCESS"
    assert res.provenance.source == "s12_artifact_store"
    assert res.provenance.freshness == StateFreshness.CURRENT.value


# ---------------------------------------------------------------------------
# 5. S18 Work State Adapter
# ---------------------------------------------------------------------------

def test_adapt_work_state_from_object():
    """Adapt real WorkState object."""
    work = WorkState(
        operation_id="op-search-99",
        goal="Find files",
        plan={"steps": [1, 2, 3]},
        status=LifecycleStatus.RUNNING,
        current_step=2,
        total_steps=3,
    )
    res = adapt_work_state(work)
    assert res is not None
    assert res.operation_id == "op-search-99"
    assert res.status == "RUNNING"
    assert res.current_step == 2
    assert res.total_steps == 3
    assert res.provenance.source == "s18_work_runtime"


# ---------------------------------------------------------------------------
# 6. ActiveComputerContext Composite Extraction
# ---------------------------------------------------------------------------

def test_adapt_active_computer_context():
    """Extract composite context directly from an ActiveComputerContext."""
    acc = ActiveComputerContext()
    acc._active_application = "Obsidian"
    acc._active_window_title = "Daily Notes - Obsidian"
    acc._active_window_process = "Obsidian.exe"
    acc._desktop_observed_at = "2025-01-01T12:00:00Z"
    acc._desktop_freshness = StateFreshness.CURRENT.value

    acc._browser_name = "firefox"
    acc._browser_url = "https://example.com"
    acc._browser_title = "Example Domain"
    acc._browser_status = "VERIFIED_SUCCESS"
    acc._browser_freshness = StateFreshness.CURRENT.value

    art = ArtifactIdentity(
        artifact_id="art-doc-1",
        artifact_type="document",
        canonical_locator="notes.md",
        display_name="notes.md",
        source_operation="op-notes",
    )
    acc._artifacts[art.artifact_id] = art

    res = adapt_active_computer_context(acc)
    assert res["computer"] is not None
    assert res["computer"].active_application == "Obsidian"
    assert res["computer"].window_title == "Daily Notes - Obsidian"

    assert res["browser"] is not None
    assert res["browser"].browser_name == "firefox"
    assert res["browser"].page_url == "https://example.com"

    assert res["artifacts"] is not None
    assert len(res["artifacts"]) == 1
    assert res["artifacts"][0].artifact_id == "art-doc-1"


# ---------------------------------------------------------------------------
# 7. Graceful None Handling & Empty inputs
# ---------------------------------------------------------------------------

def test_graceful_none_handling():
    """All adapters return None without throwing when passed None or empty inputs."""
    assert adapt_device_identity(None) is None
    assert adapt_device_identity({}) is None
    assert adapt_window_observation(None) is None
    assert adapt_browser_observation(None) is None
    assert adapt_artifact_identity(None) is None
    assert adapt_artifact_identity({}) is None
    assert adapt_work_state(None) is None
    assert adapt_work_state({}) is None

    empty_acc = adapt_active_computer_context(None)
    assert empty_acc == {"computer": None, "browser": None, "artifacts": None}