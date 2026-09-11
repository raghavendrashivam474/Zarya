"""
S3: Computer State Model — minimal shared state substrate.

Provides a common observation schema and freshness semantics that
domain-specific tools can use to represent computer state.

Design principles (from S2 lessons):
  - Shared semantics, domain-specific acquisition.
  - No centralized state manager unless evidence demands one.
  - Additive: existing tool contracts are not modified.
  - Observations are timestamped and freshness-assessed.

This module does NOT:
  - Monitor the computer continuously.
  - Persist state across sessions.
  - Replace the existing verification fabric.
  - Introduce authorization changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Freshness semantics
# ---------------------------------------------------------------------------

class StateFreshness(str, Enum):
    """How trustworthy a state observation is based on age.

    CURRENT          — Observed recently, likely still accurate.
    STALE            — Observed some time ago, may have changed.
    REQUIRES_REFRESH — Too old to trust without re-observation.
    UNKNOWN          — Never observed, or observation failed.
    """
    CURRENT = "CURRENT"
    STALE = "STALE"
    REQUIRES_REFRESH = "REQUIRES_REFRESH"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Domain identifiers
# ---------------------------------------------------------------------------

class StateDomain(str, Enum):
    APPLICATION = "application"
    FILESYSTEM = "filesystem"
    TERMINAL = "terminal"


# ---------------------------------------------------------------------------
# Core observation schema
# ---------------------------------------------------------------------------

@dataclass
class StateObservation:
    """A single point-in-time observation of computer state.

    This is the shared semantic unit across all domains.
    Each domain produces these via its own acquisition mechanism.

    Attributes:
        domain:      Which domain (application, filesystem, terminal).
        subject:     What was observed (process name, file path, command).
        observed_at: ISO 8601 UTC timestamp of when the observation occurred.
        status:      Verification status (VERIFIED_SUCCESS, VERIFIED_FAILURE, UNKNOWN).
        state:       The actual observed state data (domain-specific).
        evidence:    How the state was determined (method, raw observation data).
        freshness:   Current freshness assessment (may be recalculated).
    """
    domain: str
    subject: str
    observed_at: str
    status: str
    state: Dict[str, Any]
    evidence: Dict[str, Any]
    freshness: str = StateFreshness.CURRENT.value

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict for inclusion in tool results."""
        return {
            "domain": self.domain,
            "subject": self.subject,
            "observed_at": self.observed_at,
            "status": self.status,
            "state": self.state,
            "evidence": self.evidence,
            "freshness": self.freshness,
        }

    @classmethod
    def from_verification(
        cls,
        domain: str,
        subject: str,
        verification: Dict[str, Any],
    ) -> "StateObservation":
        """Construct a StateObservation from an existing S1/S2 verification dict.

        This is the bridge between the S2 verification fabric and S3 state.
        It wraps the existing {status, method, detail, observation} shape
        into the S3 schema without modifying the original.
        """
        status = verification.get("status", "UNKNOWN")
        method = verification.get("method", "unknown")
        detail = verification.get("detail", "")
        raw_observation = verification.get("observation", {})

        return cls(
            domain=domain,
            subject=subject,
            observed_at=now_iso(),
            status=status,
            state=_extract_state(domain, verification),
            evidence={
                "method": method,
                "detail": detail,
                "raw_observation": raw_observation,
            },
            freshness=StateFreshness.CURRENT.value,
        )


# ---------------------------------------------------------------------------
# Timestamp and freshness helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def assess_freshness(
    observed_at: str,
    max_age_seconds: float = 30.0,
) -> str:
    """Assess how fresh a state observation is based on its timestamp.

    Uses a simple age-based heuristic:
      - age <= max_age_seconds          → CURRENT
      - age <= max_age_seconds * 3      → STALE
      - age > max_age_seconds * 3       → REQUIRES_REFRESH
      - parse failure                   → UNKNOWN

    The thresholds are deliberately conservative. Different domains
    may need different thresholds (e.g., filesystem changes slower
    than process state), but this provides a safe default.

    Args:
        observed_at: ISO 8601 timestamp string from the observation.
        max_age_seconds: Maximum age in seconds to consider "current".

    Returns:
        A StateFreshness string value.
    """
    try:
        observed = datetime.fromisoformat(observed_at)
        # Ensure timezone-aware comparison
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age = (now - observed).total_seconds()

        if age < 0:
            return StateFreshness.UNKNOWN.value
        if age <= max_age_seconds:
            return StateFreshness.CURRENT.value
        if age <= max_age_seconds * 3:
            return StateFreshness.STALE.value
        return StateFreshness.REQUIRES_REFRESH.value
    except (ValueError, TypeError):
        return StateFreshness.UNKNOWN.value


def refresh_observation_freshness(
    observation: StateObservation,
    max_age_seconds: float = 30.0,
) -> StateObservation:
    """Recalculate the freshness of an existing observation in-place.

    Returns the same observation object with updated freshness.
    """
    observation.freshness = assess_freshness(
        observation.observed_at, max_age_seconds
    )
    return observation


# ---------------------------------------------------------------------------
# Domain-specific state extraction
# ---------------------------------------------------------------------------

def _extract_state(domain: str, verification: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a normalized state dict from a verification result.

    Each domain has different "what is the state" semantics:
      - application: is the process running?
      - filesystem: does the path exist? what are its properties?
      - terminal: did the command succeed? what was the output shape?
    """
    status = verification.get("status", "UNKNOWN")
    raw = verification.get("observation", {})

    if domain == StateDomain.APPLICATION.value or domain == "application":
        return {
            "running": status == "VERIFIED_SUCCESS",
            "image": verification.get("image", raw.get("image", "")),
        }

    if domain == StateDomain.FILESYSTEM.value or domain == "filesystem":
        return {
            "exists": raw.get("exists", status == "VERIFIED_SUCCESS"),
            "size_bytes": raw.get("size_bytes"),
            "content_matches": raw.get("content_matches"),
            "path": raw.get("path", ""),
        }

    if domain == StateDomain.TERMINAL.value or domain == "terminal":
        return {
            "executed": status == "VERIFIED_SUCCESS",
            "has_output": raw.get("has_output", False),
            "output_length": raw.get("output_length", 0),
            "error_indicators": raw.get("error_indicators", []),
        }

    # Fallback for unknown domains
    return {"status": status, "raw": raw}


# ---------------------------------------------------------------------------
# Minimal in-memory state cache (optional, per-session)
# ---------------------------------------------------------------------------

class StateCache:
    """A tiny in-memory cache of recent state observations.

    This is NOT a persistent store. It exists only for the lifetime
    of the current agent session and provides a way to answer
    "what did we last observe about X?" without re-querying.

    The cache is keyed by (domain, subject) and stores only the
    most recent observation per key.
    """

    def __init__(self) -> None:
        self._observations: Dict[str, StateObservation] = {}

    def _key(self, domain: str, subject: str) -> str:
        return f"{domain}:{subject}"

    def record(self, observation: StateObservation) -> None:
        """Store or update an observation in the cache."""
        key = self._key(observation.domain, observation.subject)
        self._observations[key] = observation

    def get(
        self,
        domain: str,
        subject: str,
        max_age_seconds: float = 30.0,
    ) -> Optional[StateObservation]:
        """Retrieve the last observation for a (domain, subject) pair.

        Automatically refreshes the freshness assessment before returning.
        Returns None if no observation exists for this key.
        """
        key = self._key(domain, subject)
        obs = self._observations.get(key)
        if obs is None:
            return None
        refresh_observation_freshness(obs, max_age_seconds)
        return obs

    def get_all(
        self,
        domain: Optional[str] = None,
        max_age_seconds: float = 30.0,
    ) -> List[StateObservation]:
        """Retrieve all cached observations, optionally filtered by domain.

        Refreshes freshness on all returned observations.
        """
        results = []
        for obs in self._observations.values():
            if domain and obs.domain != domain:
                continue
            refresh_observation_freshness(obs, max_age_seconds)
            results.append(obs)
        return results

    def clear(self) -> None:
        """Clear all cached observations."""
        self._observations.clear()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the entire cache to a plain dict."""
        return {
            key: obs.to_dict()
            for key, obs in self._observations.items()
        }


# Module-level cache instance (session-scoped, in-memory only)
cache = StateCache()


__all__ = [
    "StateFreshness",
    "StateDomain",
    "StateObservation",
    "StateCache",
    "now_iso",
    "assess_freshness",
    "refresh_observation_freshness",
    "cache",
]
