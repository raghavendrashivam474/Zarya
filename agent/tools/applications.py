"""
Application control: launch and close common applications.

Uses the OS backend for platform-independent app launching and closing.

S1: Added post-launch verification to distinguish execution success
from actual application state confirmation.
S12: Added target artifact continuity parameter to launch target files.
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from typing import Any, Dict, Optional

from ..registry import ToolError, register
from ..backends import get_backend
from ..state import StateObservation, StateDomain, cache as state_cache
from ..artifacts import active_context, canonicalize_locator

APP_COMMANDS: Dict[str, Dict[str, str]] = {
    "notepad": {"exe": "notepad.exe", "image": "notepad.exe", "label": "Notepad", "linux_cmd": "gedit", "linux_image": "gedit"},
    "chrome": {"exe": "chrome.exe", "image": "chrome.exe", "label": "Google Chrome", "linux_cmd": "google-chrome-stable", "linux_image": "chrome"},
    "edge": {"exe": "msedge.exe", "image": "msedge.exe", "label": "Microsoft Edge", "linux_cmd": "microsoft-edge-stable", "linux_image": "msedge"},
    "vscode": {"exe": "code.cmd", "image": "Code.exe", "label": "Visual Studio Code", "linux_cmd": "code", "linux_image": "code"},
    "calculator": {"shell": "calc", "image": "CalculatorApp.exe", "label": "Calculator", "linux_cmd": "gnome-calculator", "linux_image": "gnome-calculator"},
    "calc": {"shell": "calc", "image": "CalculatorApp.exe", "label": "Calculator", "linux_cmd": "gnome-calculator", "linux_image": "gnome-calculator"},
    "file explorer": {"shell": "explorer", "image": "explorer.exe", "label": "File Explorer", "linux_cmd": "nautilus", "linux_image": "nautilus"},
    "explorer": {"shell": "explorer", "image": "explorer.exe", "label": "File Explorer", "linux_cmd": "nautilus", "linux_image": "nautilus"},
    "task manager": {"shell": "taskmgr", "image": "Taskmgr.exe", "label": "Task Manager", "linux_cmd": "gnome-system-monitor", "linux_image": "gnome-system-monitor"},
    "taskmanager": {"shell": "taskmgr", "image": "Taskmgr.exe", "label": "Task Manager", "linux_cmd": "gnome-system-monitor", "linux_image": "gnome-system-monitor"},
    "settings": {"uwp": "ms-settings:", "image": "SystemSettings.exe", "label": "Settings", "linux_cmd": "gnome-control-center", "linux_image": "gnome-control-center"},
    "command prompt": {"exe": "cmd.exe", "image": "cmd.exe", "label": "Command Prompt", "linux_cmd": "gnome-terminal", "linux_image": "gnome-terminal-server"},
    "cmd": {"exe": "cmd.exe", "image": "cmd.exe", "label": "Command Prompt", "linux_cmd": "gnome-terminal", "linux_image": "gnome-terminal-server"},
    "powershell": {"exe": "powershell.exe", "image": "powershell.exe", "label": "PowerShell", "linux_cmd": "pwsh", "linux_image": "pwsh"},
    "wordpad": {"shell": "write", "image": "wordpad.exe", "label": "WordPad", "linux_cmd": "abiword", "linux_image": "abiword"},
    "paint": {"shell": "mspaint", "image": "mspaint.exe", "label": "Paint", "linux_cmd": "gimp", "linux_image": "gimp"},
    "snipping tool": {"uwp": "ms-screenclip:", "image": "ScreenClippingHost.exe", "label": "Snipping Tool", "linux_cmd": "gnome-screenshot", "linux_image": "gnome-screenshot"},
}


def _resolve_app(key: str) -> Dict[str, str]:
    norm = (key or "").strip().lower()
    if norm in APP_COMMANDS:
        return APP_COMMANDS[norm]
    # Allow loose aliases
    aliases = {
        "code": "vscode",
        "visual studio code": "vscode",
        "vs code": "vscode",
        "google chrome": "chrome",
        "microsoft edge": "edge",
        "calc": "calculator",
        "settings app": "settings",
        "file explorer": "file explorer",
        "windows explorer": "file explorer",
    }
    if norm in aliases and aliases[norm] in APP_COMMANDS:
        return APP_COMMANDS[aliases[norm]]
    raise ToolError(
        f"Unrecognized application '{key}'. Supported: "
        f"{', '.join(sorted({v['label'] for v in APP_COMMANDS.values()}))}."
    )


def _is_hyprland() -> bool:
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "hyprland"


def _launch_hyprland(cmd: str, floating: bool, size: str = "60% 60%", target: Optional[str] = None) -> None:
    prefix = f"[float size {size} center]" if floating else ""
    target_part = f' "{target}"' if target else ""
    subprocess.Popen(
        f"hyprctl dispatch exec -- {prefix} {cmd}{target_part}",
        shell=True,
        close_fds=True,
        start_new_session=True,
    )


# ---------------------------------------------------------------------------
# S1: Post-launch state verification
# ---------------------------------------------------------------------------

def _verify_application_launched(
    spec: Dict[str, str],
    timeout_s: float = 3.0,
    interval_s: float = 0.5,
) -> Dict[str, Any]:
    """Check whether the expected process is running after launch.

    Uses ``tasklist`` on Windows to look for the process image name
    recorded in *spec*.  Polls at *interval_s* for up to *timeout_s*.

    Returns a dict with at least ``status`` (one of VERIFIED_SUCCESS,
    VERIFIED_FAILURE, UNKNOWN) and supporting detail fields.
    """
    image = spec.get("image")
    if not image:
        return {
            "status": "UNKNOWN",
            "method": "none",
            "detail": "No process image specified in app spec.",
        }

    if platform.system() != "Windows":
        return {
            "status": "UNKNOWN",
            "method": "none",
            "detail": f"Verification not yet implemented for {platform.system()}.",
        }

    deadline = time.time() + timeout_s
    start = time.time()

    while time.time() < deadline:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = result.stdout.strip()
            # tasklist prints "INFO: No tasks are running..." when empty
            if output and "INFO:" not in output and image.lower() in output.lower():
                elapsed_ms = int((time.time() - start) * 1000)
                return {
                    "status": "VERIFIED_SUCCESS",
                    "method": "process_image_check",
                    "image": image,
                    "observation_window_ms": elapsed_ms,
                    "detail": f"Process {image} found within observation window.",
                }
        except Exception as exc:
            return {
                "status": "UNKNOWN",
                "method": "process_image_check",
                "image": image,
                "detail": f"Observation mechanism failed: {exc}",
            }
        time.sleep(interval_s)

    return {
        "status": "VERIFIED_FAILURE",
        "method": "process_image_check",
        "image": image,
        "observation_window_ms": int(timeout_s * 1000),
        "detail": f"Process {image} not found within {timeout_s}s observation window.",
    }


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

@register("openApplication")
def open_application(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args.get("name") or args.get("application")
    if not name:
        raise ToolError("Parameter 'name' (application name) is required.")
    spec = _resolve_app(str(name))
    floating = bool(args.get("floating", False))
    size = args.get("size", "60% 60%")
    target_raw = args.get("target") or args.get("target_path") or args.get("path") or args.get("file_path")
    target_str = str(target_raw).strip() if target_raw else None

    linux_cmd = spec.get("linux_cmd")
    if floating and _is_hyprland() and linux_cmd:
        _launch_hyprland(linux_cmd, floating=True, size=size, target=target_str)
    else:
        get_backend().launcher.launch(spec, target=target_str)

    # S1: verify the application actually appeared
    verification = _verify_application_launched(spec)

    # S3: capture state observation from verification
    state_obs = StateObservation.from_verification(
        domain=StateDomain.APPLICATION.value,
        subject=spec.get("image", spec["label"]),
        verification=verification,
    )
    state_cache.record(state_obs)

    from ..failure import reason_about_failure
    from ..recovery import attempt_recovery

    failure_reasoning = reason_about_failure(verification, state_obs.to_dict())
    recovery_result = attempt_recovery(
        failure=failure_reasoning,
        verification=verification,
        state=state_obs.to_dict(),
        original_tool_name="openApplication",
        original_args=args,
    )

    msg = f"{spec['label']} opened."
    if target_str:
        msg = f"{spec['label']} opened with target: {target_str}."

    resp = {
        "result": msg,
        "verification": verification,
        "state": state_obs.to_dict(),
        "failure": failure_reasoning,
        "recovery": recovery_result,
    }
    if target_str:
        resp["target"] = target_str

    # S12: Update Active Context
    active_context.update_from_tool_response("openApplication", args, resp)

    return resp


@register("closeApplication")
def close_application(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args.get("name") or args.get("application")
    if not name:
        raise ToolError("Parameter 'name' (application name) is required.")
    spec = _resolve_app(str(name))
    force = bool(args.get("force", False))
    get_backend().launcher.close(spec, force=force)
    return {"result": f"Closed {spec['label']}."}


__all__ = ["open_application", "close_application"]
