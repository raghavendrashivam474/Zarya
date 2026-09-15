"""
S13 — Desktop Observer
======================
Provides on-demand observation of the active computer context:
  - Active window (title, handle)
  - Active application (process name, PID)

This module is OBSERVATION ONLY. It does not launch, close,
switch, or manipulate any application or window.

Uses ctypes (stdlib) for Win32 API calls. No external deps.
"""

import ctypes
import ctypes.wintypes
import datetime
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Win32 API bindings ──────────────────────────────────────
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi

# ── Data structures ─────────────────────────────────────────

@dataclass
class WindowObservation:
    """A single point-in-time observation of the active window."""
    title: str
    hwnd: int
    process_name: str
    process_id: int
    observed_at: str
    freshness: str  # Reuses S3 StateFreshness values
    evidence: str   # How this observation was obtained

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "hwnd": self.hwnd,
            "process_name": self.process_name,
            "process_id": self.process_id,
            "observed_at": self.observed_at,
            "freshness": self.freshness,
            "evidence": self.evidence,
        }


@dataclass
class DesktopObservation:
    """Complete active-computer-context snapshot."""
    active_window: Optional[WindowObservation] = None
    observed_at: str = ""
    freshness: str = "UNKNOWN"
    error: Optional[str] = None

    @property
    def is_available(self) -> bool:
        return self.active_window is not None and self.error is None

    def to_dict(self) -> dict:
        return {
            "active_window": self.active_window.to_dict() if self.active_window else None,
            "observed_at": self.observed_at,
            "freshness": self.freshness,
            "error": self.error,
        }


# ── Core observation functions ──────────────────────────────

def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _get_foreground_window_title(hwnd: int) -> str:
    """Get the title text of a window by its handle."""
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_process_name_from_pid(pid: int) -> str:
    """Get the executable name for a given process ID."""
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
    )
    if not handle:
        return "unknown"
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = ctypes.wintypes.DWORD(260)
        # Try QueryFullProcessImageNameW first (Vista+)
        if hasattr(kernel32, "QueryFullProcessImageNameW"):
            kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
            full_path = buf.value
            # Extract just the filename
            return full_path.rsplit("\\", 1)[-1] if full_path else "unknown"
        else:
            psapi.GetModuleBaseNameW(handle, None, buf, 260)
            return buf.value or "unknown"
    finally:
        kernel32.CloseHandle(handle)


def observe_active_window() -> DesktopObservation:
    """
    Observe the currently active (foreground) window and its application.

    Returns a DesktopObservation with freshness=CURRENT on success,
    or freshness=UNKNOWN with an error message on failure.

    This is a point-in-time snapshot. It does not subscribe to events
    or run in the background.
    """
    now = _now_iso()
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return DesktopObservation(
                observed_at=now,
                freshness="UNKNOWN",
                error="GetForegroundWindow returned null",
            )

        title = _get_foreground_window_title(hwnd)

        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_name = _get_process_name_from_pid(pid.value)

        window_obs = WindowObservation(
            title=title,
            hwnd=hwnd,
            process_name=process_name,
            process_id=pid.value,
            observed_at=now,
            freshness="CURRENT",
            evidence=f"Win32 GetForegroundWindow hwnd={hwnd}",
        )

        return DesktopObservation(
            active_window=window_obs,
            observed_at=now,
            freshness="CURRENT",
        )

    except Exception as e:
        logger.warning("Desktop observation failed: %s", e)
        return DesktopObservation(
            observed_at=now,
            freshness="UNKNOWN",
            error=str(e),
        )
