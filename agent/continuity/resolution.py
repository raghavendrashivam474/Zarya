# N4.2 — Target-Local Resolution
# Phase: N | Sprint: N4
# Baseline: N3 v1.3.0-n3 (frozen)
#
# Responsibility:
#   Resolve target-local capabilities and artifacts from PortableWork references.
#
# Rule: Never fake missing info. Return structured BLOCKED / UNAVAILABLE.
# Rule: Use S12 (artifacts.py) and Zarya registry (registry.py) directly.

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

log = logging.getLogger("zarya.n4.resolution")

# ── Dynamic S12 / Registry Imports ──────────────────────────────────
try:
    from agent.artifacts import ArtifactIdentity
    _S12_AVAILABLE = True
except ImportError:
    _S12_AVAILABLE = False
    log.warning("S12 artifacts.py not available; falling back to mock resolution")

try:
    # Try importing Zarya's existing tool registry
    from agent.registry import registry as zarya_tool_registry
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False
    zarya_tool_registry = None
    log.warning("Zarya tool registry not available; falling back to module scans")


# ── Resolution Result Models ────────────────────────────────────────

@dataclass
class CapabilityResult:
    """Outcome of checking target execution capability support."""
    supported: bool = True
    available_capabilities: List[str] = field(default_factory=list)
    missing_capabilities: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


@dataclass
class ArtifactResolutionResult:
    """Outcome of checking and mapping N3 artifact references to local resources."""
    resolved: bool = True
    resolved_paths: Dict[str, str] = field(default_factory=dict)  # artifact_id -> local_absolute_path
    missing_artifacts: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


# ── Core Capability Resolution ──────────────────────────────────────

def resolve_target_capabilities(portable_dict: Dict[str, Any]) -> CapabilityResult:
    """Check whether this target device can support the work requirements.

    Looks up required tools/capabilities in:
      1. Zarya's active tool registry
      2. Or scans agent/tools/ directories if registry is empty.
    """
    result = CapabilityResult()
    requirements = portable_dict.get("requirements") or {}
    required_tools = requirements.get("capabilities") or []

    if not required_tools:
        log.info("No capability requirements specified in PortableWork; passing support check.")
        return result

    # Identify what is actually available on this target
    registered_tools: Set[str] = set()

    if _REGISTRY_AVAILABLE and zarya_tool_registry:
        # Pull tools registered in S8/S18 runtime registry
        try:
            # Handle list or dict registries
            if hasattr(zarya_tool_registry, "get_all_tools"):
                registered_tools = {t.name for t in zarya_tool_registry.get_all_tools()}
            elif hasattr(zarya_tool_registry, "keys"):
                registered_tools = set(zarya_tool_registry.keys())
            elif hasattr(zarya_tool_registry, "tools"):
                registered_tools = set(getattr(zarya_tool_registry, "tools", {}).keys())
        except Exception as e:
            log.error("Failed to read Zarya tool registry: %s", e)

    # Fallback/Supplemental: Scan agent/tools directory
    tools_dir = Path("agent/tools")
    if tools_dir.is_dir():
        for f in tools_dir.glob("*.py"):
            if f.name != "__init__.py":
                registered_tools.add(f.stem)

    # Match requirements
    for tool in required_tools:
        if tool in registered_tools:
            result.available_capabilities.append(tool)
        else:
            result.supported = False
            result.missing_capabilities.append(tool)
            msg = f"Required capability '{tool}' is not available on this target device."
            result.reasons.append(msg)
            log.warning("N4 Capability Blocked: %s", msg)

    if result.supported:
        log.info("N4 Capability Check: PASS. Available: %s", result.available_capabilities)

    return result


# ── Core Artifact Resolution ────────────────────────────────────────

def resolve_target_artifacts(
    artifact_references: List[str], 
    artifact_registry: Optional[Any] = None
) -> ArtifactResolutionResult:
    """Map N3 artifact references to target-local physical paths.

    This acts as the bridge with S12. It does NOT transfer files;
    it only verifies if they are locally present and resolved in S12 terms.

    Args:
        artifact_references: List of artifact_id strings from PortableWork.
        artifact_registry: Optional direct reference to S12 context/registry.
    """
    result = ArtifactResolutionResult()

    if not artifact_references:
        log.info("No artifact references to resolve.")
        return result

    for art_id in artifact_references:
        # Rule: Never guess or assume paths. Try to resolve rigorously.
        resolved_path: Optional[str] = None

        # 1. Attempt S12 resolution if registry is passed or globally available
        if _S12_AVAILABLE and artifact_registry:
            try:
                # Inspect registry for standard S12 lookup protocols
                if hasattr(artifact_registry, "get"):
                    identity = artifact_registry.get(art_id)
                    if identity and hasattr(identity, "path") and identity.path:
                        resolved_path = str(identity.path)
                elif hasattr(artifact_registry, "resolve"):
                    resolved_path = artifact_registry.resolve(art_id)
            except Exception as e:
                log.warning("Error resolving artifact '%s' via S12 registry: %s", art_id, e)

        # 2. Fallback: Parse artifact prefix for direct safe path mapping
        # E.g., "artifact:file:report_txt" -> look for report.txt locally
        # We only do this if it maps cleanly to a verifiable local path.
        if not resolved_path and art_id.startswith("artifact:file:"):
            # Translate safe suffix back to a standard workspace/local path
            raw_suffix = art_id.replace("artifact:file:", "")
            # Example heuristic: report_txt -> report.txt
            possible_filename = raw_suffix.replace("_", ".")
            
            # Look inside local workspace/downloads directory
            candidate_paths = [
                Path(possible_filename),
                Path("downloads") / possible_filename,
                Path("workspace") / possible_filename,
            ]
            
            for p in candidate_paths:
                if p.is_file():
                    resolved_path = str(p.resolve())
                    break

        # Record resolution verdict
        if resolved_path and os.path.exists(resolved_path):
            result.resolved_paths[art_id] = resolved_path
            log.info("N4 Resolved Artifact: '%s' -> '%s'", art_id, resolved_path)
        else:
            result.resolved = False
            result.missing_artifacts.append(art_id)
            msg = f"Artifact reference '{art_id}' could not be resolved locally."
            result.reasons.append(msg)
            log.warning("N4 Artifact Blocked: %s", msg)

    return result