"""N3 Portable Work Representation.

Defines the portable serialization boundary for Zarya work.
Consumes N2 SemanticWorkModel and produces a versioned, platform-neutral,
JSON-compatible representation that can safely cross process/device boundaries.

Architecture:
    N2 SemanticWorkModel  -->  N3 PortableWork  -->  JSON-compatible dict
                                  (this module)

Key principles:
    - Representation boundary, NOT transport/execution/orchestration.
    - Schema-versioned from day one (first versioned format in Zarya).
    - Loss-aware: runtime-local fields are explicitly excluded, not silently nulled.
    - Artifact references only; never artifact content or local paths.
    - Authorization metadata only; never credentials or secrets.
    - Platform-neutral: desktop, Android, and future form factors.
    - Portable != Resumable != Executable.

Ownership boundaries preserved:
    N2  -> SemanticWorkModel (consumed, not replaced)
    N1  -> UnifiedContext (not imported; N2 already distilled it)
    S18 -> WorkState / LifecycleStatus (not imported; N2 already distilled it)
    S12 -> ArtifactIdentity (referenced by artifact_id only)
    S17 -> DeviceIdentity (referenced by device_id only)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.context.work_model import SemanticWorkModel


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PORTABLE_WORK_FORMAT_VERSION = "n3-portable-v1"

SUPPORTED_FORMAT_VERSIONS = frozenset({
    PORTABLE_WORK_FORMAT_VERSION,
})

# Fields from N1 ComputerContext that are runtime-local and must NEVER
# appear in portable output. Documented here for explicit enforcement.
RUNTIME_LOCAL_FIELDS = frozenset({
    "process_id",
    "process_name",
    "hwnd",
    "window_class",
    "wm_class",
    "wayland",
    "canonical_locator",
    "pid",
})

# Patterns that indicate secret/credential data. Any dict key matching
# these patterns is stripped during serialization.
SECRET_KEY_PATTERNS = frozenset({
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "credential",
    "private_key",
    "session_cookie",
    "cookie",
    "auth_token",
    "access_token",
    "refresh_token",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """ISO 8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _is_secret_key(key: str) -> bool:
    """Check whether a dict key matches known secret/credential patterns."""
    lower = key.lower().replace("-", "_")
    return any(pattern in lower for pattern in SECRET_KEY_PATTERNS)


def _strip_secrets(data: Any) -> Any:
    """Recursively strip keys that match secret patterns from dicts.

    Returns a deep copy with secrets removed. Does not mutate the original.
    """
    if isinstance(data, dict):
        return {
            k: _strip_secrets(v)
            for k, v in data.items()
            if not _is_secret_key(k)
        }
    if isinstance(data, list):
        return [_strip_secrets(item) for item in data]
    return data


def _strip_runtime_locals(data: Any) -> Any:
    """Recursively strip keys that are runtime-local from dicts.

    Returns a deep copy. Does not mutate the original.
    """
    if isinstance(data, dict):
        return {
            k: _strip_runtime_locals(v)
            for k, v in data.items()
            if k.lower() not in RUNTIME_LOCAL_FIELDS
        }
    if isinstance(data, list):
        return [_strip_runtime_locals(item) for item in data]
    return data


# ---------------------------------------------------------------------------
# Portable Work Model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PortableWork:
    """Versioned, platform-neutral, portable representation of Zarya work.

    This is the first representation in Zarya designed to cross process
    and device boundaries. It carries semantic work information, references,
    and portability metadata — but never live runtime handles, credentials,
    or device-local state.

    Portable != Resumable: The presence of a PortableWork does not guarantee
    that execution can continue on another device. That determination belongs
    to N4 (work handoff) and the receiving runtime's local policy.

    Portable != Executable: A PortableWork must be validated, authorized,
    and adapted by the receiving runtime before any execution.
    """

    # -- Schema --
    format_version: str = PORTABLE_WORK_FORMAT_VERSION

    # -- Work identity and semantics (from N2) --
    work_id: str = ""
    intent: str = ""
    plan_reference: Dict[str, Any] = field(default_factory=dict)
    outcome: str = "UNKNOWN"

    # -- Execution (references only, from N2/S18) --
    execution_reference: Optional[str] = None
    lifecycle_status: str = "UNKNOWN"

    # -- Context (distilled from N2 RelevantWorkContext) --
    device_reference: Optional[str] = None
    platform: str = "UNKNOWN"
    active_application: Optional[str] = None
    page_url: Optional[str] = None
    page_title: Optional[str] = None
    artifact_references: List[str] = field(default_factory=list)
    context_reference: Optional[str] = None

    # -- Authorization (metadata only, NEVER credentials) --
    authorization_metadata: Optional[Dict[str, Any]] = None

    # -- Observations (provenance-aware, from N2) --
    observations: List[Dict[str, Any]] = field(default_factory=list)

    # -- Portability metadata (N3-specific) --
    source_device: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    requirements: List[str] = field(default_factory=list)
    """Capability requirements for continuation. Examples:
        "requires_browser", "requires_filesystem", "requires_android_camera"
        Keep minimal; do not build a capability negotiation system here.
    """

    def to_portable_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict safe for cross-device transfer.

        Guarantees:
            - Deterministic structure
            - No live runtime handles
            - No secrets or credentials
            - No device-local paths (canonical_locator)
            - Explicit format_version for forward compatibility
        """
        raw = {
            "format_version": self.format_version,
            "work": {
                "work_id": self.work_id,
                "intent": self.intent,
                "plan_reference": self.plan_reference,
                "outcome": self.outcome,
            },
            "execution": {
                "execution_reference": self.execution_reference,
                "lifecycle_status": self.lifecycle_status,
            },
            "context": {
                "device_reference": self.device_reference,
                "platform": self.platform,
                "active_application": self.active_application,
                "page_url": self.page_url,
                "page_title": self.page_title,
                "artifact_references": list(self.artifact_references),
                "context_reference": self.context_reference,
            },
            "authorization": self.authorization_metadata,
            "observations": list(self.observations),
            "portability": {
                "source_device": self.source_device,
                "created_at": self.created_at,
                "requirements": list(self.requirements),
            },
        }

        # Apply safety filters
        safe = _strip_secrets(raw)
        safe = _strip_runtime_locals(safe)
        return safe

    def to_json(self, indent: Optional[int] = None) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_portable_dict(), indent=indent, default=str)

    @classmethod
    def from_portable_dict(cls, data: Dict[str, Any]) -> "PortableWork":
        """Deserialize from a portable dict with schema validation.

        Raises:
            ValueError: If format_version is missing or unsupported.
            TypeError: If data is not a dict.
        """
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict, got {type(data).__name__}")

        version = data.get("format_version")
        if not version:
            raise ValueError("PortableWork missing format_version")
        if version not in SUPPORTED_FORMAT_VERSIONS:
            raise ValueError(
                f"Unsupported PortableWork format_version: {version!r}. "
                f"Supported: {sorted(SUPPORTED_FORMAT_VERSIONS)}"
            )

        work = data.get("work", {})
        execution = data.get("execution", {})
        context = data.get("context", {})
        portability = data.get("portability", {})

        return cls(
            format_version=version,
            work_id=work.get("work_id", ""),
            intent=work.get("intent", ""),
            plan_reference=work.get("plan_reference", {}),
            outcome=work.get("outcome", "UNKNOWN"),
            execution_reference=execution.get("execution_reference"),
            lifecycle_status=execution.get("lifecycle_status", "UNKNOWN"),
            device_reference=context.get("device_reference"),
            platform=context.get("platform", "UNKNOWN"),
            active_application=context.get("active_application"),
            page_url=context.get("page_url"),
            page_title=context.get("page_title"),
            artifact_references=context.get("artifact_references", []),
            context_reference=context.get("context_reference"),
            authorization_metadata=data.get("authorization"),
            observations=data.get("observations", []),
            source_device=portability.get("source_device"),
            created_at=portability.get("created_at", _now_iso()),
            requirements=portability.get("requirements", []),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "PortableWork":
        """Deserialize from a JSON string."""
        data = json.loads(json_str)
        return cls.from_portable_dict(data)


# ---------------------------------------------------------------------------
# Factory: SemanticWorkModel -> PortableWork
# ---------------------------------------------------------------------------

def make_portable(
    model: SemanticWorkModel,
    source_device: Optional[str] = None,
    requirements: Optional[List[str]] = None,
) -> PortableWork:
    """Create a PortableWork from an N2 SemanticWorkModel.

    This is the primary entry point for N3. It consumes the semantic model
    and produces a versioned portable representation.

    Args:
        model: N2 SemanticWorkModel (frozen, authoritative).
        source_device: Optional device identifier for portability metadata.
            Falls back to model.relevant_context.device_id if available.
        requirements: Optional list of capability requirements.

    Returns:
        A frozen PortableWork instance.
    """
    ctx = model.relevant_context

    effective_source = source_device
    if not effective_source and ctx:
        effective_source = ctx.device_id

    effective_platform = "UNKNOWN"
    if ctx:
        effective_platform = ctx.platform

    return PortableWork(
        format_version=PORTABLE_WORK_FORMAT_VERSION,
        work_id=model.work_id,
        intent=model.intent,
        plan_reference=dict(model.plan_reference),
        outcome=model.outcome,
        execution_reference=model.execution_reference,
        lifecycle_status=model.lifecycle_status,
        device_reference=ctx.device_id if ctx else None,
        platform=effective_platform,
        active_application=ctx.active_application if ctx else None,
        page_url=ctx.page_url if ctx else None,
        page_title=ctx.page_title if ctx else None,
        artifact_references=list(model.artifact_references),
        context_reference=model.context_reference,
        authorization_metadata=dict(model.authorization_reference) if model.authorization_reference else None,
        observations=[dict(obs) for obs in model.observations],
        source_device=effective_source,
        created_at=_now_iso(),
        requirements=list(requirements) if requirements else [],
    )