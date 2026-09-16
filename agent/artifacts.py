"""
S12 / S16 / S17 — Artifact Identity & Active Computer Context
"""

from __future__ import annotations

import os
import uuid
import hashlib
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union


class ArtifactKind(str, Enum):
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"
    URL = "URL"
    PROCESS = "PROCESS"
    WINDOW = "WINDOW"
    UNKNOWN = "UNKNOWN"


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    STALE = "STALE"
    RE_OBSERVED = "RE_OBSERVED"


@dataclass(frozen=True)
class ArtifactIdentity:
    """Stable, unique identifier for an artifact across context turns."""
    artifact_id: str
    kind: ArtifactKind
    canonical_uri: str
    display_name: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_operation: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    @classmethod
    def create_file_artifact(cls, file_path: str, source_operation: Optional[str] = None) -> ArtifactIdentity:
        norm_path = os.path.normpath(os.path.abspath(file_path))
        display = os.path.basename(norm_path) or norm_path
        uri = f"file://{norm_path.replace(os.sep, '/')}"
        id_str = f"art-file-{hashlib.sha256(uri.encode('utf-8')).hexdigest()[:12]}"
        return cls(
            artifact_id=id_str,
            kind=ArtifactKind.FILE,
            canonical_uri=uri,
            display_name=display,
            source_operation=source_operation,
            metadata={"raw_path": norm_path},
        )

    @classmethod
    def create_url_artifact(cls, url: str, title: Optional[str] = None, source_operation: Optional[str] = None) -> ArtifactIdentity:
        clean_url = url.strip()
        display = title or clean_url
        id_str = f"art-url-{hashlib.sha256(clean_url.encode('utf-8')).hexdigest()[:12]}"
        return cls(
            artifact_id=id_str,
            kind=ArtifactKind.URL,
            canonical_uri=clean_url,
            display_name=display,
            source_operation=source_operation,
            metadata={"title": title},
        )

    @classmethod
    def create_window_artifact(cls, handle: int, title: str, process_name: Optional[str] = None) -> ArtifactIdentity:
        uri = f"win://handle/{handle}"
        id_str = f"art-win-{handle}"
        return cls(
            artifact_id=id_str,
            kind=ArtifactKind.WINDOW,
            canonical_uri=uri,
            display_name=title,
            metadata={"handle": handle, "process_name": process_name},
        )


@dataclass
class ActiveComputerContext:
    """The local computer context holding active desktop, browser, artifacts, and known devices."""
    active_window: Optional[Dict[str, Any]] = None
    active_browser_tab: Optional[Dict[str, Any]] = None
    recent_artifacts: List[ArtifactIdentity] = field(default_factory=list)
    last_observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    # S17 addition: optional device registry attached to the computer context
    device_registry: Optional[Any] = None

    def record_artifact(self, artifact: ArtifactIdentity) -> None:
        self.recent_artifacts = [a for a in self.recent_artifacts if a.artifact_id != artifact.artifact_id]
        self.recent_artifacts.insert(0, artifact)
        if len(self.recent_artifacts) > 20:
            self.recent_artifacts = self.recent_artifacts[:20]

    def get_latest_artifact(self, kind: Optional[ArtifactKind] = None) -> Optional[ArtifactIdentity]:
        for a in self.recent_artifacts:
            if kind is None or a.kind == kind:
                return a
        return None
