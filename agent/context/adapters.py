"""N1 Context Adapters — Bridge existing subsystems into unified context.

Translates domain models from S12, S13, S14, S17, and S18 into platform-neutral
unified context types defined in `agent.context.unified`.

Ownership and Boundary Rules:
    - Does NOT mutate existing models or subsystem stores.
    - Gracefully handles missing, None, or partial inputs.
    - Preserves exact timestamps, evidence, and S3 freshness ratings.
    - Extracts platform-specific details (like Win32 hwnd) into `platform_detail`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent.context.unified import (
    ArtifactReference,
    BrowserContext,
    ComputerContext,
    DeviceContext,
    ObservationProvenance,
    WorkReference,
    _now_iso,
)
from agent.state import StateFreshness


# ---------------------------------------------------------------------------
# S17 Adapter — Device Identity
# ---------------------------------------------------------------------------

def adapt_device_identity(
    device: Any,
    observed_at: Optional[str] = None,
) -> Optional[DeviceContext]:
    """Adapt an S17 DeviceIdentity into a DeviceContext.

    Args:
        device: `DeviceIdentity` instance or dict representing device info.
        observed_at: Optional timestamp override.
    """
    if device is None:
        return None

    if isinstance(device, dict):
        dev_id = device.get("device_id", "")
        platform_raw = device.get("platform", "UNKNOWN")
        dev_type_raw = device.get("device_type", "UNKNOWN")
        name = device.get("display_name", "")
    else:
        dev_id = getattr(device, "device_id", "")
        platform_attr = getattr(device, "platform", "UNKNOWN")
        platform_raw = platform_attr.value if hasattr(platform_attr, "value") else str(platform_attr)
        dev_type_attr = getattr(device, "device_type", "UNKNOWN")
        dev_type_raw = dev_type_attr.value if hasattr(dev_type_attr, "value") else str(dev_type_attr)
        name = getattr(device, "display_name", "")

    if not dev_id:
        return None

    ts = observed_at or _now_iso()
    prov = ObservationProvenance(
        source="s17_device_identity",
        observed_at=ts,
        freshness=StateFreshness.CURRENT.value,
        method="device_registry",
    )

    return DeviceContext(
        device_id=dev_id,
        platform=str(platform_raw).upper(),
        device_type=str(dev_type_raw).upper(),
        display_name=name,
        provenance=prov,
    )


# ---------------------------------------------------------------------------
# S13 Adapter — Desktop / Window Observation
# ---------------------------------------------------------------------------

def adapt_window_observation(
    obs: Any,
) -> Optional[ComputerContext]:
    """Adapt an S13 WindowObservation into a platform-neutral ComputerContext.

    Platform-specific fields like `hwnd` are placed in `platform_detail`.
    """
    if obs is None:
        return None

    if isinstance(obs, dict):
        title = obs.get("title")
        hwnd = obs.get("hwnd")
        pname = obs.get("process_name")
        pid = obs.get("process_id")
        obs_at = obs.get("observed_at") or _now_iso()
        freshness = obs.get("freshness", StateFreshness.UNKNOWN.value)
        evidence = obs.get("evidence", "")
    else:
        title = getattr(obs, "title", None)
        hwnd = getattr(obs, "hwnd", None)
        pname = getattr(obs, "process_name", None)
        pid = getattr(obs, "process_id", None)
        obs_at = getattr(obs, "observed_at", None) or _now_iso()
        freshness = getattr(obs, "freshness", StateFreshness.UNKNOWN.value)
        evidence = getattr(obs, "evidence", "")

    platform_detail: Dict[str, Any] = {}
    if hwnd is not None:
        platform_detail["hwnd"] = hwnd

    prov = ObservationProvenance(
        source="s13_desktop_observer",
        observed_at=obs_at,
        freshness=freshness,
        method=evidence or "os_window_query",
    )

    return ComputerContext(
        active_application=pname,
        window_title=title,
        process_name=pname,
        process_id=pid,
        platform_detail=platform_detail if platform_detail else None,
        provenance=prov,
    )


# ---------------------------------------------------------------------------
# S14 Adapter — Browser Observation
# ---------------------------------------------------------------------------

def adapt_browser_observation(
    obs: Any,
) -> Optional[BrowserContext]:
    """Adapt an S14 BrowserObservation into a BrowserContext."""
    if obs is None:
        return None

    if isinstance(obs, dict):
        bname = obs.get("browser_name", "")
        url = obs.get("page_url")
        title = obs.get("page_title")
        status = obs.get("status", "UNKNOWN")
        error = obs.get("error")
        obs_at = obs.get("observed_at") or _now_iso()
        freshness = obs.get("freshness", StateFreshness.UNKNOWN.value)
        evidence = obs.get("evidence", "")
    else:
        bname = getattr(obs, "browser_name", "")
        url = getattr(obs, "page_url", None)
        title = getattr(obs, "page_title", None)
        status = getattr(obs, "status", "UNKNOWN")
        error = getattr(obs, "error", None)
        obs_at = getattr(obs, "observed_at", None) or _now_iso()
        freshness = getattr(obs, "freshness", StateFreshness.UNKNOWN.value)
        evidence = getattr(obs, "evidence", "")

    prov = ObservationProvenance(
        source="s14_browser_observer",
        observed_at=obs_at,
        freshness=freshness,
        method=evidence or "playwright_cdp",
    )

    return BrowserContext(
        browser_name=bname,
        page_url=url,
        page_title=title,
        status=status,
        error=error,
        provenance=prov,
    )


# ---------------------------------------------------------------------------
# S12 Adapter — Artifact Identity
# ---------------------------------------------------------------------------

def adapt_artifact_identity(
    art: Any,
) -> Optional[ArtifactReference]:
    """Adapt an S12 ArtifactIdentity into a lightweight ArtifactReference."""
    if art is None:
        return None

    if isinstance(art, dict):
        art_id = art.get("artifact_id", "")
        art_type = art.get("artifact_type", "file")
        dname = art.get("display_name", "")
        vstatus = art.get("verification_status", "UNKNOWN")
        obs_at = art.get("last_verified_at") or art.get("created_at") or _now_iso()
    else:
        art_id = getattr(art, "artifact_id", "")
        art_type = getattr(art, "artifact_type", "file")
        dname = getattr(art, "display_name", "")
        vstatus = getattr(art, "verification_status", "UNKNOWN")
        obs_at = getattr(art, "last_verified_at", None) or getattr(art, "created_at", None) or _now_iso()

    if not art_id:
        return None

    prov = ObservationProvenance(
        source="s12_artifact_store",
        observed_at=obs_at,
        freshness=StateFreshness.CURRENT.value if vstatus == "VERIFIED_SUCCESS" else StateFreshness.UNKNOWN.value,
        method="artifact_registry",
    )

    return ArtifactReference(
        artifact_id=art_id,
        artifact_type=art_type,
        display_name=dname,
        verification_status=vstatus,
        provenance=prov,
    )


# ---------------------------------------------------------------------------
# S18 Adapter — Work State / Checkpoint
# ---------------------------------------------------------------------------

def adapt_work_state(
    work: Any,
) -> Optional[WorkReference]:
    """Adapt an S18 WorkState or Checkpoint into a lightweight WorkReference."""
    if work is None:
        return None

    if isinstance(work, dict):
        op_id = work.get("operation_id", "")
        status_raw = work.get("status", "UNKNOWN")
        c_step = work.get("current_step", 0)
        t_steps = work.get("total_steps", 0)
        obs_at = work.get("updated_at") or work.get("created_at") or _now_iso()
    else:
        op_id = getattr(work, "operation_id", "")
        status_attr = getattr(work, "status", "UNKNOWN")
        status_raw = status_attr.value if hasattr(status_attr, "value") else str(status_attr)
        c_step = getattr(work, "current_step", getattr(work, "step_index", 0))
        t_steps = getattr(work, "total_steps", 0)
        obs_at = getattr(work, "updated_at", None) or getattr(work, "created_at", None) or _now_iso()

    if not op_id:
        return None

    prov = ObservationProvenance(
        source="s18_work_runtime",
        observed_at=obs_at,
        freshness=StateFreshness.CURRENT.value,
        method="lifecycle_state",
    )

    return WorkReference(
        operation_id=op_id,
        status=str(status_raw).upper(),
        current_step=c_step,
        total_steps=t_steps,
        provenance=prov,
    )


# ---------------------------------------------------------------------------
# S12 ActiveComputerContext Composite Adapter
# ---------------------------------------------------------------------------

def adapt_active_computer_context(
    acc: Any,
) -> Dict[str, Any]:
    """Extract sub-contexts directly from an S12 ActiveComputerContext instance.

    Returns a dict containing:
        - computer: Optional[ComputerContext]
        - browser: Optional[BrowserContext]
        - artifacts: Optional[List[ArtifactReference]]
    """
    if acc is None:
        return {"computer": None, "browser": None, "artifacts": None}

    with getattr(acc, "_lock", None) or _DummyLock():
        # 1. Computer / Desktop
        comp = None
        if acc._active_window_title or acc._active_window_process or acc._active_application:
            pname = acc._active_window_process or acc._active_application
            prov = ObservationProvenance(
                source="s13_desktop_observer",
                observed_at=acc._desktop_observed_at or _now_iso(),
                freshness=acc._desktop_freshness or StateFreshness.UNKNOWN.value,
                method="active_computer_context_cache",
            )
            comp = ComputerContext(
                active_application=acc._active_application or pname,
                window_title=acc._active_window_title,
                process_name=pname,
                provenance=prov,
            )

        # 2. Browser
        browser = None
        if acc._browser_name or acc._browser_url:
            bprov = ObservationProvenance(
                source="s14_browser_observer",
                observed_at=acc._browser_observed_at or _now_iso(),
                freshness=acc._browser_freshness or StateFreshness.UNKNOWN.value,
                method=acc._browser_evidence or "active_computer_context_cache",
            )
            browser = BrowserContext(
                browser_name=acc._browser_name or "",
                page_url=acc._browser_url,
                page_title=acc._browser_title,
                status=acc._browser_status or "UNKNOWN",
                provenance=bprov,
            )

        # 3. Artifacts
        artifacts: Optional[List[ArtifactReference]] = None
        if hasattr(acc, "_artifacts") and acc._artifacts:
            art_list = []
            for art in acc._artifacts.values():
                adapted = adapt_artifact_identity(art)
                if adapted:
                    art_list.append(adapted)
            if art_list:
                artifacts = art_list

    return {
        "computer": comp,
        "browser": browser,
        "artifacts": artifacts,
    }


class _DummyLock:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass