"""
Window management: minimize / maximize / close the active window or switch apps.

Uses the backend abstraction to handle OS-specific window management.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from ..registry import ToolError, register
from ..backends import get_backend

SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9
SW_HIDE = 0

def _resolve_target(args: Dict[str, Any]):
    """Pick the hwnd to operate on: explicit title, or the foreground window."""
    wm = get_backend().window_manager
    title: Optional[str] = args.get("title") or args.get("application")
    if title:
        hwnd = wm.find_window_by_title(str(title))
        if not hwnd:
            raise ToolError(f"No visible window with title containing '{title}'.")
        return hwnd, str(title)
    hwnd = wm.get_foreground_window()
    if not hwnd:
        raise ToolError("No active window found.")
    return hwnd, wm.get_window_title(hwnd)


@register("minimizeWindow")
def minimize_window(args: Dict[str, Any]) -> Dict[str, Any]:
    hwnd, title = _resolve_target(args)
    get_backend().window_manager.show_window(hwnd, SW_MINIMIZE)
    return {"result": f"Minimized window: {title or 'active window'}."}


@register("maximizeWindow")
def maximize_window(args: Dict[str, Any]) -> Dict[str, Any]:
    hwnd, title = _resolve_target(args)
    get_backend().window_manager.show_window(hwnd, SW_MAXIMIZE)
    return {"result": f"Maximized window: {title or 'active window'}."}


@register("closeWindow")
def close_window(args: Dict[str, Any]) -> Dict[str, Any]:
    hwnd, title = _resolve_target(args)
    get_backend().window_manager.close_window(hwnd)
    return {"result": f"Closed window: {title or 'active window'}."}


@register("switchApplication")
def switch_application(args: Dict[str, Any]) -> Dict[str, Any]:
    """Focus a window by title."""
    wm = get_backend().window_manager
    title = args.get("title") or args.get("application")
    if title:
        hwnd = wm.find_window_by_title(str(title))
        if not hwnd:
            raise ToolError(f"No visible window matching '{title}'.")
        wm.show_window(hwnd, SW_RESTORE)
        wm.focus(hwnd)
        return {"result": f"Switched to: {str(title)}."}

    # Alt+Tab cycle could be implemented via backend.clipboard / keys
    # or just enumerating windows, but for simplicity we require title.
    raise ToolError("Please specify an application title to switch to.")


__all__ = [
    "minimize_window",
    "maximize_window",
    "close_window",
    "switch_application",
]



# ── S13: Active Desktop Context Observation Tools ───────────────────────────

@register("getActiveWindow")
def get_active_window(args: Dict[str, Any]) -> Dict[str, Any]:
    """Observe the currently active (foreground) window on the desktop.

    Returns title, process name, PID, evidence, and S3 freshness.
    """
    from ..artifacts import active_context
    from .desktop_observer import observe_active_window

    obs = observe_active_window()
    if obs.is_available and obs.active_window:
        active_context._active_window_title = obs.active_window.title
        active_context._active_window_process = obs.active_window.process_name
        active_context._active_application = obs.active_window.process_name
        active_context._desktop_observed_at = obs.observed_at
        active_context._desktop_freshness = "CURRENT"

        matched = active_context.match_artifact_to_window(obs.active_window.title)
        matched_locator = matched.canonical_locator if matched else None

        return {
            "title": obs.active_window.title,
            "process_name": obs.active_window.process_name,
            "process_id": obs.active_window.process_id,
            "matched_artifact": matched_locator,
            "freshness": "CURRENT",
            "evidence": obs.active_window.evidence,
            "observed_at": obs.observed_at,
            "verification": {
                "status": "VERIFIED_SUCCESS",
                "method": "desktop_observation",
                "detail": f"Observed active window '{obs.active_window.title}' ({obs.active_window.process_name})",
            },
        }

    return {
        "title": None,
        "process_name": None,
        "process_id": None,
        "matched_artifact": None,
        "freshness": "UNKNOWN",
        "error": obs.error or "Window observation unavailable",
        "observed_at": obs.observed_at,
        "verification": {
            "status": "UNKNOWN",
            "method": "desktop_observation",
            "detail": obs.error or "Could not observe active window",
        },
    }


@register("getActiveContext")
def get_active_context(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get the full active computer context snapshot including active window, application, browser context (S14), matched artifact, working directory, and freshness."""
    import os
    from ..artifacts import active_context
    from .desktop_observer import observe_active_window
    from .browser_observer import observe_browser_context

    obs = observe_active_window()
    cwd = os.getcwd()

    if obs.is_available and obs.active_window:
        active_context._active_window_title = obs.active_window.title
        active_context._active_window_process = obs.active_window.process_name
        active_context._active_application = obs.active_window.process_name
        active_context._desktop_observed_at = obs.observed_at
        active_context._desktop_freshness = "CURRENT"

        matched = active_context.match_artifact_to_window(obs.active_window.title)
        matched_locator = matched.canonical_locator if matched else None

        # S14 — Observe browser context when active application is a browser
        browser_obs = observe_browser_context(obs.active_window.process_name, window_title=obs.active_window.title)
        browser_dict = None
        if browser_obs is not None:
            browser_dict = browser_obs.to_dict()
            active_context._browser_name = browser_obs.browser_name
            active_context._browser_url = browser_obs.page_url
            active_context._browser_title = browser_obs.page_title
            active_context._browser_observed_at = browser_obs.observed_at
            active_context._browser_freshness = browser_obs.freshness
            active_context._browser_status = browser_obs.status
            active_context._browser_evidence = browser_obs.evidence
        else:
            active_context._browser_name = None
            active_context._browser_url = None
            active_context._browser_title = None
            active_context._browser_observed_at = None
            active_context._browser_freshness = "UNKNOWN"
            active_context._browser_status = "UNKNOWN"
            active_context._browser_evidence = None

        return {
            "active_application": obs.active_window.process_name,
            "active_window": obs.active_window.title,
            "active_artifact": matched_locator,
            "working_directory": cwd,
            "browser": browser_dict,
            "freshness": "CURRENT",
            "observed_at": obs.observed_at,
            "evidence": obs.active_window.evidence,
            "verification": {
                "status": "VERIFIED_SUCCESS",
                "method": "active_context_snapshot",
                "detail": f"Active app: {obs.active_window.process_name}, Window: {obs.active_window.title}",
            },
        }

    return {
        "active_application": active_context.active_application,
        "active_window": None,
        "active_artifact": (
            active_context.active_artifact.canonical_locator
            if active_context.active_artifact else None
        ),
        "working_directory": cwd,
        "browser": active_context.get_browser_snapshot(),
        "freshness": "UNKNOWN",
        "observed_at": None,
        "evidence": "no_active_window_detected",
        "verification": {
            "status": "UNKNOWN",
            "method": "active_context_snapshot",
            "detail": obs.error or "Active window could not be observed",
        },
    }

    obs = observe_active_window()
    cwd = os.getcwd()

    if obs.is_available and obs.active_window:
        active_context._active_window_title = obs.active_window.title
        active_context._active_window_process = obs.active_window.process_name
        active_context._active_application = obs.active_window.process_name
        active_context._desktop_observed_at = obs.observed_at
        active_context._desktop_freshness = "CURRENT"

        matched = active_context.match_artifact_to_window(obs.active_window.title)
        matched_locator = matched.canonical_locator if matched else None

        return {
            "active_application": obs.active_window.process_name,
            "active_window": obs.active_window.title,
            "active_artifact": matched_locator,
            "working_directory": cwd,
            "freshness": "CURRENT",
            "observed_at": obs.observed_at,
            "evidence": obs.active_window.evidence,
            "verification": {
                "status": "VERIFIED_SUCCESS",
                "method": "active_context_snapshot",
                "detail": f"Active app: {obs.active_window.process_name}, Window: {obs.active_window.title}",
            },
        }

    return {
        "active_application": active_context.active_application,
        "active_window": None,
        "active_artifact": (
            active_context.active_artifact.canonical_locator
            if active_context.active_artifact else None
        ),
        "working_directory": cwd,
        "freshness": "UNKNOWN",
        "error": obs.error or "Context observation unavailable",
        "observed_at": obs.observed_at,
        "verification": {
            "status": "UNKNOWN",
            "method": "active_context_snapshot",
            "detail": obs.error or "Could not observe active desktop context",
        },
    }
