"""Unit tests for N1 Unified Context contract (agent/context/unified.py).

Tests:
    1. Minimal snapshot construction & defaults
    2. Immutability (frozen dataclasses)
    3. Optional sub-contexts (None preserved, not fabricated)
    4. Serialization (to_dict)
    5. Provenance tracking on sub-contexts
    6. Platform neutrality (Desktop vs Mobile representation)
    7. Work reference boundary (references S18, does not embed it)
    8. Artifact reference boundary (references S12, does not embed it)
    9. Generic context observations
    10. No execution authority (pure data objects)
"""

import pytest
from dataclasses import FrozenInstanceError

from agent.context.unified import (
    UnifiedContext,
    DeviceContext,
    ComputerContext,
    BrowserContext,
    ArtifactReference,
    WorkReference,
    ContextObservation,
    ObservationProvenance,
)
from agent.state import StateFreshness


# ---------------------------------------------------------------------------
# 1. Minimal snapshot construction & defaults
# ---------------------------------------------------------------------------

def test_minimal_unified_context_defaults():
    """A bare UnifiedContext has sensible defaults and unique ID."""
    ctx = UnifiedContext()
    assert ctx.context_id.startswith("ctx-")
    assert len(ctx.context_id) > 8
    assert ctx.captured_at != ""
    assert ctx.platform == "UNKNOWN"
    assert ctx.device is None
    assert ctx.computer is None
    assert ctx.browser is None
    assert ctx.artifacts is None
    assert ctx.work is None
    assert ctx.observations is None
    assert ctx.notes is None


def test_unique_context_ids():
    """Each snapshot gets a distinct ID."""
    ctx1 = UnifiedContext()
    ctx2 = UnifiedContext()
    assert ctx1.context_id != ctx2.context_id


# ---------------------------------------------------------------------------
# 2. Immutability (frozen dataclasses)
# ---------------------------------------------------------------------------

def test_unified_context_is_immutable():
    """UnifiedContext cannot be mutated after creation."""
    ctx = UnifiedContext()
    with pytest.raises(FrozenInstanceError):
        ctx.platform = "WINDOWS"


def test_sub_contexts_are_immutable():
    """All sub-context types are frozen."""
    prov = ObservationProvenance(
        source="test", observed_at="2025-01-01T00:00:00Z", freshness=StateFreshness.CURRENT.value
    )
    dev = DeviceContext(device_id="dev-1", platform="WINDOWS", provenance=prov)
    comp = ComputerContext(active_application="chrome.exe", provenance=prov)
    browser = BrowserContext(browser_name="chrome", provenance=prov)
    art = ArtifactReference(artifact_id="art-1", provenance=prov)
    work = WorkReference(operation_id="op-1", provenance=prov)
    obs = ContextObservation(domain="fs", subject="/tmp/test", provenance=prov)

    with pytest.raises(FrozenInstanceError):
        dev.device_id = "other"
    with pytest.raises(FrozenInstanceError):
        comp.active_application = "notepad.exe"
    with pytest.raises(FrozenInstanceError):
        browser.page_url = "https://other.com"
    with pytest.raises(FrozenInstanceError):
        art.artifact_id = "other"
    with pytest.raises(FrozenInstanceError):
        work.operation_id = "other"
    with pytest.raises(FrozenInstanceError):
        obs.domain = "other"
    with pytest.raises(FrozenInstanceError):
        prov.source = "other"


# ---------------------------------------------------------------------------
# 3. Optional sub-contexts (None preserved, never faked)
# ---------------------------------------------------------------------------

def test_missing_sub_contexts_remain_none():
    """Unavailable sub-contexts are None, not empty dicts or dummy objects."""
    ctx = UnifiedContext(
        device=DeviceContext(device_id="dev-1", platform="WINDOWS"),
        # computer, browser, artifacts, work, observations all omitted
    )
    assert ctx.device is not None
    assert ctx.computer is None
    assert ctx.browser is None
    assert ctx.artifacts is None
    assert ctx.work is None
    assert ctx.observations is None


# ---------------------------------------------------------------------------
# 4. Serialization (to_dict)
# ---------------------------------------------------------------------------

def test_to_dict_full_snapshot():
    """to_dict produces clean serializable output with all fields."""
    prov = ObservationProvenance(
        source="s13_desktop_observer",
        observed_at="2025-01-01T00:00:00Z",
        freshness=StateFreshness.CURRENT.value,
        method="win32_api",
    )
    ctx = UnifiedContext(
        platform="WINDOWS",
        device=DeviceContext(
            device_id="dev-100",
            platform="WINDOWS",
            device_type="DESKTOP",
            display_name="Workstation-1",
            provenance=prov,
        ),
        computer=ComputerContext(
            active_application="chrome.exe",
            window_title="Zarya Dashboard",
            process_name="chrome.exe",
            process_id=1234,
            platform_detail={"hwnd": 65536},
            provenance=prov,
        ),
        browser=BrowserContext(
            browser_name="chrome",
            page_url="https://app.zarya.ai",
            page_title="Zarya Dashboard",
            status="VERIFIED_SUCCESS",
            provenance=prov,
        ),
        artifacts=[
            ArtifactReference(
                artifact_id="art-200",
                artifact_type="file",
                display_name="report.pdf",
                verification_status="VERIFIED_SUCCESS",
                provenance=prov,
            )
        ],
        work=WorkReference(
            operation_id="op-300",
            status="RUNNING",
            current_step=2,
            total_steps=5,
            provenance=prov,
        ),
        observations=[
            ContextObservation(
                domain="filesystem",
                subject="C:\\data\\report.pdf",
                state={"size_bytes": 1024},
                status="VERIFIED_SUCCESS",
                provenance=prov,
            )
        ],
        notes="Full desktop capture",
    )

    d = ctx.to_dict()
    assert d["platform"] == "WINDOWS"
    assert d["device"]["device_id"] == "dev-100"
    assert d["device"]["platform"] == "WINDOWS"
    assert d["computer"]["active_application"] == "chrome.exe"
    assert d["computer"]["platform_detail"]["hwnd"] == 65536
    assert d["browser"]["page_url"] == "https://app.zarya.ai"
    assert len(d["artifacts"]) == 1
    assert d["artifacts"][0]["artifact_id"] == "art-200"
    assert d["work"]["operation_id"] == "op-300"
    assert d["work"]["current_step"] == 2
    assert len(d["observations"]) == 1
    assert d["observations"][0]["domain"] == "filesystem"
    assert d["notes"] == "Full desktop capture"


def test_to_dict_preserves_none_fields():
    """to_dict outputs explicit None for unavailable sub-contexts."""
    ctx = UnifiedContext()
    d = ctx.to_dict()
    assert d["device"] is None
    assert d["computer"] is None
    assert d["browser"] is None
    assert d["artifacts"] is None
    assert d["work"] is None
    assert d["observations"] is None
    assert "notes" not in d  # notes is omitted from dict if None


# ---------------------------------------------------------------------------
# 5. Provenance tracking on sub-contexts
# ---------------------------------------------------------------------------

def test_provenance_reuses_s3_freshness():
    """Provenance accepts valid S3 StateFreshness values."""
    for freshness in [
        StateFreshness.CURRENT.value,
        StateFreshness.STALE.value,
        StateFreshness.REQUIRES_REFRESH.value,
        StateFreshness.UNKNOWN.value,
    ]:
        prov = ObservationProvenance(
            source="s13_desktop_observer",
            observed_at="2025-01-01T00:00:00Z",
            freshness=freshness,
        )
        assert prov.freshness == freshness


# ---------------------------------------------------------------------------
# 6. Platform Neutrality (Desktop vs Mobile)
# ---------------------------------------------------------------------------

def test_desktop_context_representation():
    """Desktop snapshot includes window and process information."""
    comp = ComputerContext(
        active_application="code.exe",
        window_title="unified.py - VS Code",
        process_name="Code.exe",
        process_id=4567,
        platform_detail={"hwnd": 131072, "window_class": "Chrome_WidgetWin_1"},
    )
    assert comp.active_application == "code.exe"
    assert comp.platform_detail["hwnd"] == 131072


def test_mobile_context_representation():
    """Mobile snapshot has device identity and app, but no desktop window."""
    ctx = UnifiedContext(
        platform="ANDROID",
        device=DeviceContext(
            device_id="phone-pixel-8",
            platform="ANDROID",
            device_type="PHONE",
            display_name="Pixel 8 Pro",
        ),
        computer=None,  # No desktop window system on mobile
        work=WorkReference(
            operation_id="op-mobile-1",
            status="RUNNING",
        ),
        notes="Android mobile context: no desktop window manager",
    )
    d = ctx.to_dict()
    assert d["platform"] == "ANDROID"
    assert d["device"]["platform"] == "ANDROID"
    assert d["device"]["device_type"] == "PHONE"
    assert d["computer"] is None
    assert d["work"]["operation_id"] == "op-mobile-1"


# ---------------------------------------------------------------------------
# 7. Work reference boundary
# ---------------------------------------------------------------------------

def test_work_reference_does_not_embed_work_state():
    """WorkReference carries only lightweight pointers, not full WorkState."""
    work = WorkReference(
        operation_id="op-s18-test",
        status="CHECKPOINTED",
        current_step=3,
        total_steps=5,
    )
    # Verify it has NO plan, checkpoint store, or step history objects
    assert not hasattr(work, "plan")
    assert not hasattr(work, "completed_steps")
    assert not hasattr(work, "checkpoint_store")
    assert work.operation_id == "op-s18-test"
    assert work.status == "CHECKPOINTED"


# ---------------------------------------------------------------------------
# 8. Artifact reference boundary
# ---------------------------------------------------------------------------

def test_artifact_reference_does_not_embed_artifact_identity():
    """ArtifactReference carries lightweight pointers, not full ArtifactIdentity."""
    art = ArtifactReference(
        artifact_id="art-doc-1",
        artifact_type="document",
        display_name="brief.md",
        verification_status="VERIFIED_SUCCESS",
    )
    # Verify it has NO source_operation, last_verified_at, etc.
    assert not hasattr(art, "canonical_locator")
    assert not hasattr(art, "source_operation")
    assert art.artifact_id == "art-doc-1"


# ---------------------------------------------------------------------------
# 9. Generic context observations
# ---------------------------------------------------------------------------

def test_context_observation_with_custom_domain():
    """ContextObservation handles non-standard domain facts cleanly."""
    obs = ContextObservation(
        domain="audio",
        subject="default_playback_device",
        state={"device_name": "Headphones (Realtek)", "volume_percent": 65},
        status="VERIFIED_SUCCESS",
    )
    assert obs.domain == "audio"
    assert obs.state["volume_percent"] == 65


# ---------------------------------------------------------------------------
# 10. No execution authority
# ---------------------------------------------------------------------------

def test_no_execution_methods_on_unified_context():
    """UnifiedContext is purely observational; has no execute/run/apply methods."""
    ctx = UnifiedContext()
    for method in ["execute", "run", "apply", "mutate", "authorize", "cancel", "resume"]:
        assert not hasattr(ctx, method), f"UnifiedContext must NOT have '{method}' method"