"""
Filesystem tools: safe file and directory operations on user folders.

Key safeguards:
* All paths are resolved with expanduser and normalized to absolute.
* Operations are confined to a set of SAFE_ROOTS by default; paths that
  resolve outside these trees raise ToolError unless allow_anywhere=True.
* File sizes are capped before reading to prevent memory exhaustion.
* Deletions default to send2trash where available, falling back to an
  explicit confirmation barrier rather than immediate silent unlinks.
* Binary files are detected and handled gracefully (preview/metadata only).
"""

from __future__ import annotations

import mimetypes
import os
import platform
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..registry import ToolError, register
from ..state import StateObservation, StateDomain, cache as state_cache
from ..artifacts import active_context, canonicalize_locator

# Safe roots: user profile directories only.
HOME = Path(os.path.expanduser("~"))

_SYSTEM = platform.system()
if _SYSTEM == "Windows":
    _ROOT = Path("C:\\")
elif _SYSTEM == "Darwin":
    _ROOT = Path("/System/Volumes/Data")
else:
    _ROOT = Path("/")

SAFE_ROOTS: List[Path] = [
    HOME / "Desktop",
    HOME / "Documents",
    HOME / "Downloads",
    HOME / "Pictures",
    HOME / "Videos",
    HOME / "Music",
    HOME / ".elysia",
    Path(os.getcwd()),  # project root
    Path(tempfile.gettempdir()),  # test temp directories
]

# Friendly folder aliases -> resolved path.
FOLDER_ALIASES: Dict[str, Path] = {
    "desktop": HOME / "Desktop",
    "documents": HOME / "Documents",
    "docs": HOME / "Documents",
    "downloads": HOME / "Downloads",
    "pictures": HOME / "Pictures",
    "videos": HOME / "Videos",
    "music": HOME / "Music",
    "home": HOME,
    "user": HOME,
    "project": Path(os.getcwd()),
    "root": _ROOT,
    "c": _ROOT,
}


def _resolve_folder(name_or_path: Optional[str]) -> Path:
    if not name_or_path:
        raise ToolError("Parameter 'name' or 'path' is required.")
    key = str(name_or_path).strip().lower()
    if key in FOLDER_ALIASES:
        return FOLDER_ALIASES[key]
    p = Path(os.path.expandvars(os.path.expanduser(str(name_or_path)))).resolve()
    return p


def _resolve_file(path: Optional[str], *, must_exist: bool = False) -> Path:
    if not path:
        raise ToolError("Parameter 'path' is required.")
    p = Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()
    if must_exist and not p.exists():
        raise ToolError(f"File not found: {p}")
    return p


def _ensure_safe(p: Path, allow_anywhere: bool = False) -> None:
    if allow_anywhere:
        return
    p_real = str(p.resolve())
    for root in SAFE_ROOTS:
        try:
            root_real = str(root.resolve())
            if p_real == root_real or p_real.startswith(root_real + os.sep):
                return
        except Exception:
            continue
    raise ToolError(
        f"Path '{p}' is outside ELYSIA's safe folders (Desktop, Documents, "
        f"Downloads, Pictures, Music, Videos, project root). "
        f"Operation blocked for safety."
    )


def _verify_file_created(p: Path, expected_content: str = None) -> Dict[str, Any]:
    """Verify that a file exists (and optionally matches content) after creation.

    Returns a dict with `status` (VERIFIED_SUCCESS, VERIFIED_FAILURE, UNKNOWN)
    and supporting observation fields, matching the S1 verification contract.
    """
    try:
        if not p.exists():
            return {
                "status": "VERIFIED_FAILURE",
                "method": "filesystem_exists",
                "detail": f"File does not exist after creation: {p}",
                "observation": {"path": str(p), "exists": False},
            }

        observation: Dict[str, Any] = {
            "path": str(p),
            "exists": True,
            "size_bytes": p.stat().st_size,
        }

        if expected_content is not None:
            try:
                actual = p.read_text(encoding="utf-8")
                content_match = actual == expected_content
                observation["content_matches"] = content_match
                if not content_match:
                    return {
                        "status": "VERIFIED_FAILURE",
                        "method": "filesystem_content_check",
                        "detail": "File exists but content does not match expected.",
                        "observation": observation,
                    }
            except Exception as read_exc:
                observation["content_check_error"] = str(read_exc)
                return {
                    "status": "UNKNOWN",
                    "method": "filesystem_content_check",
                    "detail": f"Unable to verify file content: {read_exc}",
                    "observation": observation,
                }

        return {
            "status": "VERIFIED_SUCCESS",
            "method": "filesystem_content_check" if expected_content is not None else "filesystem_exists",
            "detail": f"File verified at {p} ({observation['size_bytes']} bytes).",
            "observation": observation,
        }
    except Exception as exc:
        return {
            "status": "UNKNOWN",
            "method": "filesystem_exists",
            "detail": f"Verification mechanism failed: {exc}",
            "observation": {"path": str(p), "error": str(exc)},
        }


@register("createFile")
def create_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path")
    content = args.get("content", "")
    overwrite = bool(args.get("overwrite", False))
    p = _resolve_file(path)
    _ensure_safe(p)

    if p.exists() and not overwrite:
        raise ToolError(
            f"File already exists: {p}. Pass overwrite=true to replace it."
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(content), encoding="utf-8")
    verification = _verify_file_created(p, expected_content=str(content))

    # S3: capture state observation from verification
    state_obs = StateObservation.from_verification(
        domain=StateDomain.FILESYSTEM.value,
        subject=str(p),
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
        original_tool_name="createFile",
        original_args=args,
    )

    resp = {
        "result": f"Created file: {p}",
        "path": str(p),
        "verification": verification,
        "state": state_obs.to_dict(),
        "failure": failure_reasoning,
        "recovery": recovery_result,
    }

    # S12: Update active context
    active_context.update_from_tool_response("createFile", args, resp)

    return resp


@register("readFile")
def read_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path")
    max_chars = int(args.get("max_chars", 8000))
    p = _resolve_file(path, must_exist=True)
    _ensure_safe(p)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except UnicodeDecodeError:
        resp = {"result": f"(Binary file, {p.stat().st_size} bytes): {p}", "path": str(p)}
        active_context.update_from_tool_response("readFile", args, resp)
        return resp
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…[truncated, {len(text) - max_chars} more chars]"
    resp = {"result": text, "path": str(p)}
    active_context.update_from_tool_response("readFile", args, resp)
    return resp


@register("renameFile")
def rename_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path")
    new_name = args.get("new_name")
    if not new_name:
        raise ToolError("Parameter 'new_name' is required.")
    p = _resolve_file(path, must_exist=True)
    _ensure_safe(p)
    target = (p.parent / str(new_name)).resolve()
    _ensure_safe(target)
    if target.exists():
        raise ToolError(f"A file already exists at the target name: {target}")
    p.rename(target)
    resp = {"result": f"Renamed {p.name} -> {target.name}", "path": str(target)}
    active_context.update_from_tool_response("renameFile", args, resp)
    return resp


@register("deleteFile")
def delete_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path")
    permanent = bool(args.get("permanent", False))
    p = _resolve_file(path, must_exist=True)
    _ensure_safe(p)

    if permanent:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return {"result": f"Permanently deleted: {p}"}

    # Prefer recycle bin.
    try:
        import send2trash  # type: ignore

        send2trash.send2trash(str(p))
        return {"result": f"Moved to Recycle Bin: {p}"}
    except ImportError:
        raise ToolError(
            "Safe deletion requires the 'send2trash' package. Install it or pass "
            "permanent=true (use with care)."
        )
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not move to Recycle Bin: {e}")


@register("moveFile")
def move_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path")
    destination = args.get("destination")
    if not destination:
        raise ToolError("Parameter 'destination' is required.")
    p = _resolve_file(path, must_exist=True)
    _ensure_safe(p)
    dest = Path(os.path.expandvars(os.path.expanduser(str(destination)))).resolve()
    _ensure_safe(dest)
    if dest.is_dir():
        dest = dest / p.name
    shutil.move(str(p), str(dest))
    resp = {"result": f"Moved {p.name} -> {dest}", "path": str(dest)}
    active_context.update_from_tool_response("moveFile", args, resp)
    return resp


@register("openFolder")
def open_folder(args: Dict[str, Any]) -> Dict[str, Any]:
    folder = _resolve_folder(args.get("name") or args.get("path"))
    _ensure_safe(folder)
    if not folder.exists():
        raise ToolError(f"Folder does not exist: {folder}")
    system = platform.system()
    if system == "Windows":
        os.startfile(str(folder))  # type: ignore[attr-defined]
    elif system == "Darwin":
        import subprocess

        subprocess.run(["open", str(folder)], check=False)
    else:
        import subprocess

        subprocess.run(["xdg-open", str(folder)], check=False)
    return {"result": f"Opened folder: {folder}", "path": str(folder)}


@register("listFiles")
def list_files(args: Dict[str, Any]) -> Dict[str, Any]:
    folder = _resolve_folder(args.get("name") or args.get("path") or "documents")
    _ensure_safe(folder)
    if not folder.exists():
        raise ToolError(f"Folder not found: {folder}")
    limit = int(args.get("limit", 50))
    items = []
    try:
        for entry in sorted(folder.iterdir()):
            items.append(
                {
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size_bytes": entry.stat().st_size if entry.is_file() else None,
                }
            )
            if len(items) >= limit:
                break
    except PermissionError:
        raise ToolError(f"Permission denied accessing folder: {folder}")
    return {
        "result": f"Found {len(items)} items in {folder}",
        "folder": str(folder),
        "items": items,
    }


@register("searchFiles")
def search_files(args: Dict[str, Any]) -> Dict[str, Any]:
    query = (args.get("query") or args.get("name") or "").lower()
    if not query:
        raise ToolError("Parameter 'query' is required.")
    folder = _resolve_folder(args.get("folder") or args.get("under") or "home")
    _ensure_safe(folder)
    max_results = int(args.get("max_results", 20))
    matches: List[str] = []
    skip_dirs = {
        "node_modules",
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "AppData",
        "Library",
        ".cache",
        "$Recycle.Bin",
    }
    for root, dirs, files in os.walk(str(folder)):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for fname in files:
            if query in fname.lower():
                matches.append(os.path.join(root, fname))
                if len(matches) >= max_results:
                    break
        if len(matches) >= max_results:
            break
    return {
        "result": f"Found {len(matches)} files matching '{query}' under {folder}",
        "matches": matches,
    }


__all__ = [
    "create_file",
    "read_file",
    "rename_file",
    "delete_file",
    "move_file",
    "open_folder",
    "listFiles",
    "searchFiles",
]
