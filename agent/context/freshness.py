"""Bounded freshness validation for context observations.

Reuses S3 freshness semantics. Does NOT create a background monitor.
Model: on-demand check immediately before resolution when evidence
is too old (S16 Section 8).

States (S16 Section 9):
    CURRENT     → safe to resolve
    STALE       → refresh before resolution
    UNAVAILABLE → do not guess
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class FreshnessState(Enum):
    """Observation freshness states."""
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


# Default thresholds in seconds.
# Derived from S3/S13/S14 observation cadence — tune after testing.
DEFAULT_FRESH_SECONDS = 5.0
DEFAULT_STALE_SECONDS = 30.0


def check_freshness(
    observed_at: Optional[str],
    current_time: Optional[datetime] = None,
    fresh_threshold: float = DEFAULT_FRESH_SECONDS,
    stale_threshold: float = DEFAULT_STALE_SECONDS,
) -> FreshnessState:
    """Check whether an observation timestamp is fresh enough to use.

    Args:
        observed_at: ISO 8601 timestamp string from the observation.
        current_time: Override for "now" (for deterministic tests).
        fresh_threshold: Seconds within which → CURRENT.
        stale_threshold: Seconds within which → STALE. Beyond → UNAVAILABLE.

    Returns:
        FreshnessState.
    """
    if not observed_at:
        return FreshnessState.UNAVAILABLE

    # Handle case where caller passes a state string instead of timestamp
    if isinstance(observed_at, str) and observed_at.upper() in (
        "CURRENT", "STALE", "UNAVAILABLE"
    ):
        return FreshnessState(observed_at.upper())

    try:
        observed = datetime.fromisoformat(observed_at)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return FreshnessState.UNAVAILABLE

    now = current_time or datetime.now(timezone.utc)
    age = (now - observed).total_seconds()

    if age < 0:
        return FreshnessState.UNAVAILABLE  # clock skew
    elif age <= fresh_threshold:
        return FreshnessState.CURRENT
    elif age <= stale_threshold:
        return FreshnessState.STALE
    else:
        return FreshnessState.UNAVAILABLE
