"""
S12: Artifact Identity & Computer Context Continuity.

Defines stable runtime artifact identity and active computer context
to ensure concrete computer entities (files, applications, directories)
maintain continuity across multi-step execution and natural language references.

Key Invariants:
  1. Identity != State: Identity answers *what* thing we are talking about;
     State (S3) answers *what is observed* about it.
  2. Action != Outcome: An attempted action does NOT establish an active
     verified artifact unless S2 verification confirms VERIFIED_SUCCESS.
  3. Never Guess: Ambiguous or missing targets deterministically produce
     clarification requests rather than silent filesystem searches.
  4. Separation of Concerns: Does not replace S3 state, S4 failure reasoning,
     S5 recovery, S6 work execution, or S7 persistent memory.
"""

from __future__ import annotations

import enum
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("zarya.artifacts")

# S12.1: Explicit operation categories replace fragile string-matching heuristics.
# These sets define which tool operations establish, mutate, or read artifacts.
ARTIFACT_CREATING_OPERATIONS = frozenset({
    "createFile",
    "createPythonFile",
    "writeCodeFile",
    "copyFile",
    "downloadFile",
    "exportFile",
    "saveAs",
    "duplicateFile",
    "extractFile",
})

ARTIFACT_MUTATING_OPERATIONS = frozenset({
    "renameFile",
    "moveFile",
    "appendFile",
    "editFile",
})

ARTIFACT_READING_OPERATIONS = frozenset({
    "readFile",
    "listFiles",
    "searchFiles",
    "openApplicationTarget",
    "explicitReference",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonicalize_locator(locator: str, artifact_type: str = "file") -> str:
    """Normalize and resolve a target locator to its canonical absolute representation."""
    if not locator:
        return ""
    s = str(locator).strip()
    if artifact_type in ("file", "folder"):
        try:
            # Expand environment variables and user home
            expanded = os.path.expandvars(os.path.expanduser(s))
            return str(Path(expanded).resolve())
        except Exception:
            return os.path.abspath(s)
    return s.strip()


class ArtifactType(str, enum.Enum):
    FILE = "file"
    FOLDER = "folder"
    APPLICATION = "application"
    WINDOW = "window"
    BROWSER_TAB = "browser_tab"


class ResolutionStatus(str, enum.Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class ArtifactIdentity:
    """Stable runtime identity of a computer entity during a session."""

    artifact_id: str
    artifact_type: str
    canonical_locator: str
    display_name: str
    source_operation: str
    created_at: str = field(default_factory=_now_iso)
    last_verified_at: Optional[str] = None
    verification_status: str = "UNKNOWN"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ArtifactIdentity:
        return cls(
            artifact_id=data.get("artifact_id", ""),
            artifact_type=data.get("artifact_type", "file"),
            canonical_locator=data.get("canonical_locator", ""),
            display_name=data.get("display_name", ""),
            source_operation=data.get("source_operation", "unknown"),
            created_at=data.get("created_at") or _now_iso(),
            last_verified_at=data.get("last_verified_at"),
            verification_status=data.get("verification_status", "UNKNOWN"),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def create_file_artifact(
        cls,
        path: str | Path,
        source_operation: str = "createFile",
        verification_status: str = "UNKNOWN",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactIdentity:
        canonical = canonicalize_locator(str(path), artifact_type="file")
        p = Path(canonical)
        name = p.name or str(canonical)
        # Stable deterministic ID derived from type and canonical locator
        safe_suffix = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", canonical).strip("_")
        artifact_id = f"artifact:file:{safe_suffix}"
        now_str = _now_iso()
        return cls(
            artifact_id=artifact_id,
            artifact_type=ArtifactType.FILE.value,
            canonical_locator=canonical,
            display_name=name,
            source_operation=source_operation,
            created_at=now_str,
            last_verified_at=now_str if verification_status == "VERIFIED_SUCCESS" else None,
            verification_status=verification_status,
            metadata=metadata or {},
        )

    @classmethod
    def create_application_artifact(
        cls,
        app_name: str,
        source_operation: str = "openApplication",
        verification_status: str = "UNKNOWN",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactIdentity:
        clean_name = app_name.strip().lower()
        artifact_id = f"artifact:app:{clean_name}"
        now_str = _now_iso()
        return cls(
            artifact_id=artifact_id,
            artifact_type=ArtifactType.APPLICATION.value,
            canonical_locator=clean_name,
            display_name=app_name.strip(),
            source_operation=source_operation,
            created_at=now_str,
            last_verified_at=now_str if verification_status == "VERIFIED_SUCCESS" else None,
            verification_status=verification_status,
            metadata=metadata or {},
        )


@dataclass
class TargetResolution:
    """Outcome of resolving a natural reference or identifier to a concrete artifact."""

    status: ResolutionStatus
    artifact: Optional[ArtifactIdentity] = None
    canonical_locator: Optional[str] = None
    reason: str = ""
    candidates: List[ArtifactIdentity] = field(default_factory=list)

    @property
    def is_resolved(self) -> bool:
        return self.status == ResolutionStatus.RESOLVED and self.artifact is not None


# Common natural language referring expressions for active artifact
PRONOUN_REFERENCES = {
    "it",
    "that",
    "this",
    "that file",
    "this file",
    "the file",
    "the file we just created",
    "the file we created",
    "the created file",
    "the document",
    "that document",
    "this document",
    "the one i just opened",
    "the one we just created",
    "same file",
    "the same file",
    "the current file",
    "current file",
    "$active_artifact",
    "$target",
    "{{last_artifact}}",
}


class ActiveComputerContext:
    """Manages active computer context and tracks runtime artifact identities."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._artifacts: Dict[str, ArtifactIdentity] = {}  # artifact_id -> identity
        # The concrete artifact most recently established as the target of an applicable operation.
        self._active_artifact: Optional[ArtifactIdentity] = None
        # The most recent artifact whose creation was actually established by the runtime.
        self._last_created_artifact: Optional[ArtifactIdentity] = None
        # The most recent artifact for which verification produced VERIFIED_SUCCESS.
        self._last_verified_artifact: Optional[ArtifactIdentity] = None
        self._active_application: Optional[str] = None

    def clear(self) -> None:
        """Reset all active context (e.g. at session start or test teardown)."""
        with self._lock:
            self._artifacts.clear()
            self._active_artifact = None
            self._last_created_artifact = None
            self._last_verified_artifact = None
            self._active_application = None

    @property
    def active_artifact(self) -> Optional[ArtifactIdentity]:
        with self._lock:
            return self._active_artifact

    @property
    def last_created_artifact(self) -> Optional[ArtifactIdentity]:
        with self._lock:
            return self._last_created_artifact

    @property
    def last_verified_artifact(self) -> Optional[ArtifactIdentity]:
        with self._lock:
            return self._last_verified_artifact

    @property
    def active_application(self) -> Optional[str]:
        with self._lock:
            return self._active_application

    def record_artifact(
        self,
        artifact: ArtifactIdentity,
        set_active: bool = True,
    ) -> None:
        """Record or update an artifact in context."""
        with self._lock:
            self._artifacts[artifact.artifact_id] = artifact
            if set_active:
                self._active_artifact = artifact
            if artifact.verification_status == "VERIFIED_SUCCESS":
                self._last_verified_artifact = artifact
            if artifact.source_operation in ARTIFACT_CREATING_OPERATIONS:
                self._last_created_artifact = artifact

    def reset(self) -> None:
        """Explicit lifecycle reset for session boundaries or test isolation."""
        self.clear()

    def update_from_tool_response(
        self,
        tool_name: str,
        args: Dict[str, Any],
        response: Dict[str, Any],
    ) -> Optional[ArtifactIdentity]:
        """Inspect a completed tool execution response and update active context.

        Respects S2 verification: UNKNOWN or failure does NOT establish
        a factual active verified artifact.
        Preserves logical identity across mutation operations (rename/move).
        """
        if not isinstance(response, dict):
            return None

        verification = response.get("verification") or {}
        v_status = verification.get("status", "UNKNOWN")
        v_is_success = v_status == "VERIFIED_SUCCESS"

        with self._lock:
            # 1. Artifact-mutating operations: renameFile, moveFile
            if tool_name in ARTIFACT_MUTATING_OPERATIONS:
                new_path_str = response.get("path")
                old_path_str = args.get("path") or args.get("filepath")
                if not new_path_str:
                    return None

                new_canonical = canonicalize_locator(str(new_path_str), artifact_type="file")
                old_canonical = canonicalize_locator(str(old_path_str), artifact_type="file") if old_path_str else ""

                # Check if we already have an artifact representing the source file
                existing_artifact: Optional[ArtifactIdentity] = None
                if old_canonical:
                    for art in self._artifacts.values():
                        if art.canonical_locator == old_canonical:
                            existing_artifact = art
                            break

                if existing_artifact is not None:
                    # PRESERVE IDENTITY: Mutate locator and display name of existing artifact
                    prev_locators = list(existing_artifact.metadata.get("previous_locators", []))
                    if existing_artifact.canonical_locator not in prev_locators:
                        prev_locators.append(existing_artifact.canonical_locator)

                    existing_artifact.canonical_locator = new_canonical
                    existing_artifact.display_name = Path(new_canonical).name or new_canonical
                    existing_artifact.source_operation = tool_name
                    existing_artifact.verification_status = v_status
                    if v_is_success:
                        existing_artifact.last_verified_at = _now_iso()
                    existing_artifact.metadata["previous_locators"] = prev_locators
                    existing_artifact.metadata["last_mutation_args"] = args

                    self._active_artifact = existing_artifact
                    if v_is_success:
                        self._last_verified_artifact = existing_artifact

                    log.info(
                        "S12.1 ActiveContext: preserved identity %s across %s -> %s",
                        existing_artifact.artifact_id,
                        tool_name,
                        new_canonical,
                    )
                    return existing_artifact
                else:
                    # New artifact if we did not have prior record
                    eff_v_status = "VERIFIED_SUCCESS" if v_is_success else "UNKNOWN"
                    artifact = ArtifactIdentity.create_file_artifact(
                        path=new_canonical,
                        source_operation=tool_name,
                        verification_status=eff_v_status,
                        metadata={"args": args, "mutated_from": old_canonical},
                    )
                    self.record_artifact(artifact, set_active=True)
                    return artifact

            # 2. Artifact-creating operations: createFile, createPythonFile, writeCodeFile, etc.
            elif tool_name in ARTIFACT_CREATING_OPERATIONS:
                path_str = response.get("path") or args.get("path") or args.get("filepath")
                if path_str:
                    canonical = canonicalize_locator(str(path_str), artifact_type="file")
                    # If verification succeeded
                    if v_is_success:
                        artifact = ArtifactIdentity.create_file_artifact(
                            path=canonical,
                            source_operation=tool_name,
                            verification_status="VERIFIED_SUCCESS",
                            metadata={"args": args},
                        )
                        self.record_artifact(artifact, set_active=True)
                        log.info(
                            "S12.1 ActiveContext: set active created artifact '%s' (VERIFIED_SUCCESS)",
                            canonical,
                        )
                        return artifact
                    elif "error" not in response and "result" in response:
                        # Operation finished without explicit verification failure (e.g. unverified execution)
                        artifact = ArtifactIdentity.create_file_artifact(
                            path=canonical,
                            source_operation=tool_name,
                            verification_status="UNKNOWN",
                            metadata={"args": args},
                        )
                        self.record_artifact(artifact, set_active=True)
                        log.info(
                            "S12.1 ActiveContext: set active created artifact '%s' (UNKNOWN)",
                            canonical,
                        )
                        return artifact

            # 3. Artifact-reading operations: readFile
            elif tool_name in ARTIFACT_READING_OPERATIONS or tool_name == "readFile":
                path_str = response.get("path") or args.get("path") or args.get("filepath")
                if path_str and "result" in response and "error" not in response:
                    canonical = canonicalize_locator(str(path_str), artifact_type="file")
                    # Check if already tracked
                    existing_artifact = None
                    for art in self._artifacts.values():
                        if art.canonical_locator == canonical:
                            existing_artifact = art
                            break

                    if existing_artifact is not None:
                        self._active_artifact = existing_artifact
                        return existing_artifact
                    else:
                        artifact = ArtifactIdentity.create_file_artifact(
                            path=canonical,
                            source_operation=tool_name,
                            verification_status="UNKNOWN",
                            metadata={"args": args},
                        )
                        self.record_artifact(artifact, set_active=True)
                        return artifact

            # 4. Application tools: openApplication
            elif tool_name == "openApplication":
                app_name = args.get("name") or args.get("application") or ""
                target_arg = args.get("target") or args.get("target_path") or args.get("path")
                if app_name:
                    self._active_application = str(app_name).strip()
                    app_artifact = ArtifactIdentity.create_application_artifact(
                        app_name=str(app_name),
                        source_operation=tool_name,
                        verification_status=v_status,
                        metadata={"target": target_arg, "args": args},
                    )
                    self.record_artifact(app_artifact, set_active=False)

                # If the app was opened with a concrete target file, preserve that file as active
                if target_arg:
                    target_canonical = canonicalize_locator(str(target_arg), artifact_type="file")
                    # Check if already tracked
                    for art in self._artifacts.values():
                        if art.canonical_locator == target_canonical:
                            self._active_artifact = art
                            log.info("S12.1 ActiveContext: existing file target preserved via app launch: '%s'", target_canonical)
                            return art

                    file_artifact = ArtifactIdentity.create_file_artifact(
                        path=target_canonical,
                        source_operation="openApplicationTarget",
                        verification_status="UNKNOWN",
                        metadata={"opened_with": app_name},
                    )
                    self.record_artifact(file_artifact, set_active=True)
                    log.info("S12.1 ActiveContext: active file target linked via app launch: '%s'", target_canonical)
                    return file_artifact

        return None

    def resolve_target(self, reference: str) -> TargetResolution:
        """Resolve a natural reference, placeholder, filename, or locator to an ArtifactIdentity."""
        if not reference:
            return TargetResolution(
                status=ResolutionStatus.NOT_FOUND,
                reason="Target reference is empty.",
            )

        ref_clean = reference.strip()
        ref_lower = ref_clean.lower()

        with self._lock:
            # 1. Direct match on artifact_id
            if ref_clean in self._artifacts:
                art = self._artifacts[ref_clean]
                return TargetResolution(
                    status=ResolutionStatus.RESOLVED,
                    artifact=art,
                    canonical_locator=art.canonical_locator,
                    reason=f"Direct match on artifact_id: {art.artifact_id}",
                )

            # 2. Pronoun / Deictic Reference ("it", "that file", "same file", etc.)
            if ref_lower in PRONOUN_REFERENCES:
                if self._active_artifact is not None:
                    return TargetResolution(
                        status=ResolutionStatus.RESOLVED,
                        artifact=self._active_artifact,
                        canonical_locator=self._active_artifact.canonical_locator,
                        reason=f"Resolved pronoun '{ref_clean}' to active artifact: {self._active_artifact.canonical_locator}",
                    )
                if self._last_verified_artifact is not None:
                    return TargetResolution(
                        status=ResolutionStatus.RESOLVED,
                        artifact=self._last_verified_artifact,
                        canonical_locator=self._last_verified_artifact.canonical_locator,
                        reason=f"Resolved pronoun '{ref_clean}' to last verified artifact: {self._last_verified_artifact.canonical_locator}",
                    )
                if self._last_created_artifact is not None:
                    return TargetResolution(
                        status=ResolutionStatus.RESOLVED,
                        artifact=self._last_created_artifact,
                        canonical_locator=self._last_created_artifact.canonical_locator,
                        reason=f"Resolved pronoun '{ref_clean}' to last created artifact: {self._last_created_artifact.canonical_locator}",
                    )
                return TargetResolution(
                    status=ResolutionStatus.NOT_FOUND,
                    reason=f"Cannot resolve '{ref_clean}': No active or previously referenced artifact exists in context.",
                )

            # 3. Canonical locator direct match in known artifacts
            canonical_query = canonicalize_locator(ref_clean)
            for art in self._artifacts.values():
                if art.canonical_locator == canonical_query:
                    return TargetResolution(
                        status=ResolutionStatus.RESOLVED,
                        artifact=art,
                        canonical_locator=art.canonical_locator,
                        reason=f"Direct match on canonical locator: {art.canonical_locator}",
                    )

            # 4. Display name or basename match in known artifacts
            matching_artifacts = [
                art
                for art in self._artifacts.values()
                if art.display_name.lower() == ref_lower
                or Path(art.canonical_locator).name.lower() == ref_lower
            ]
            if len(matching_artifacts) == 1:
                art = matching_artifacts[0]
                return TargetResolution(
                    status=ResolutionStatus.RESOLVED,
                    artifact=art,
                    canonical_locator=art.canonical_locator,
                    reason=f"Unique match on artifact display name: {art.display_name}",
                )
            elif len(matching_artifacts) > 1:
                return TargetResolution(
                    status=ResolutionStatus.AMBIGUOUS,
                    candidates=matching_artifacts,
                    reason=f"Multiple artifacts match '{ref_clean}'. Clarification required.",
                )

            # 5. Check if reference itself looks like a direct explicit path
            if (
                os.path.isabs(ref_clean)
                or "/" in ref_clean
                or "\\" in ref_clean
                or ref_clean.endswith((".txt", ".md", ".json", ".py", ".log", ".csv", ".html", ".js", ".ts"))
            ):
                canonical_direct = canonicalize_locator(ref_clean)
                # Create an ad-hoc unverified artifact representation for explicit path
                ad_hoc = ArtifactIdentity.create_file_artifact(
                    path=canonical_direct,
                    source_operation="explicitReference",
                    verification_status="UNKNOWN",
                )
                return TargetResolution(
                    status=ResolutionStatus.RESOLVED,
                    artifact=ad_hoc,
                    canonical_locator=canonical_direct,
                    reason=f"Resolved explicit path target: {canonical_direct}",
                )

            return TargetResolution(
                status=ResolutionStatus.NOT_FOUND,
                reason=f"Target '{ref_clean}' could not be resolved from active context.",
            )


# Global singleton for active computer context
active_context = ActiveComputerContext()


def resolve_target(reference: str, context: Optional[ActiveComputerContext] = None) -> TargetResolution:
    """Convenience helper to resolve a target reference against provided or global active context."""
    ctx = context or active_context
    return ctx.resolve_target(reference)


__all__ = [
    "ArtifactType",
    "ArtifactIdentity",
    "ResolutionStatus",
    "TargetResolution",
    "ActiveComputerContext",
    "active_context",
    "resolve_target",
    "canonicalize_locator",
    "PRONOUN_REFERENCES",
]
