"""
Unit tests for S3 core computer state model.
Verifies state representation, freshness calculations, serialization, and cache behavior.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
import pytest

from agent.state import (
    StateDomain,
    StateFreshness,
    StateObservation,
    StateCache,
    assess_freshness,
    now_iso,
    refresh_observation_freshness,
)


def test_observation_creation_and_serialization() -> None:
    """Verify that a StateObservation can be constructed and serialized correctly."""
    timestamp = now_iso()
    obs = StateObservation(
        domain=StateDomain.APPLICATION.value,
        subject="notepad.exe",
        observed_at=timestamp,
        status="VERIFIED_SUCCESS",
        state={"running": True, "image": "notepad.exe"},
        evidence={"method": "process_image_check", "detail": "Process found."},
    )

    assert obs.domain == "application"
    assert obs.subject == "notepad.exe"
    assert obs.observed_at == timestamp
    assert obs.status == "VERIFIED_SUCCESS"
    assert obs.state["running"] is True
    assert obs.freshness == "CURRENT"

    d = obs.to_dict()
    assert d["domain"] == "application"
    assert d["subject"] == "notepad.exe"
    assert d["observed_at"] == timestamp
    assert d["status"] == "VERIFIED_SUCCESS"
    assert d["state"]["running"] is True
    assert d["evidence"]["method"] == "process_image_check"
    assert d["freshness"] == "CURRENT"


def test_from_verification_application() -> None:
    """Verify conversion from an S1 application verification payload."""
    verification = {
        "status": "VERIFIED_SUCCESS",
        "method": "process_image_check",
        "image": "Code.exe",
        "observation_window_ms": 120,
        "detail": "Process Code.exe found within observation window.",
        "observation": {"running": True},
    }

    obs = StateObservation.from_verification(
        domain=StateDomain.APPLICATION.value,
        subject="Code.exe",
        verification=verification,
    )

    assert obs.domain == "application"
    assert obs.subject == "Code.exe"
    assert obs.status == "VERIFIED_SUCCESS"
    assert obs.state["running"] is True
    assert obs.state["image"] == "Code.exe"
    assert obs.evidence["method"] == "process_image_check"
    assert "detail" in obs.evidence


def test_from_verification_filesystem() -> None:
    """Verify conversion from an S2 filesystem verification payload."""
    verification = {
        "status": "VERIFIED_SUCCESS",
        "method": "filesystem_content_check",
        "detail": "File verified at test.txt",
        "observation": {
            "path": "test.txt",
            "exists": True,
            "size_bytes": 42,
            "content_matches": True,
        },
    }

    obs = StateObservation.from_verification(
        domain=StateDomain.FILESYSTEM.value,
        subject="test.txt",
        verification=verification,
    )

    assert obs.domain == "filesystem"
    assert obs.subject == "test.txt"
    assert obs.status == "VERIFIED_SUCCESS"
    assert obs.state["exists"] is True
    assert obs.state["size_bytes"] == 42
    assert obs.state["content_matches"] is True


def test_assess_freshness() -> None:
    """Test the age-based freshness heuristic."""
    now = datetime.now(timezone.utc)

    # Current: freshly made (0s)
    t_current = now.isoformat()
    assert assess_freshness(t_current, max_age_seconds=10.0) == StateFreshness.CURRENT.value

    # Stale: older than max_age but within 3x
    t_stale = (now - timedelta(seconds=15)).isoformat()
    assert assess_freshness(t_stale, max_age_seconds=10.0) == StateFreshness.STALE.value

    # Requires Refresh: older than 3x max_age
    t_refresh = (now - timedelta(seconds=35)).isoformat()
    assert assess_freshness(t_refresh, max_age_seconds=10.0) == StateFreshness.REQUIRES_REFRESH.value

    # Invalid timestamp
    assert assess_freshness("invalid-timestamp", max_age_seconds=10.0) == StateFreshness.UNKNOWN.value

    # Future timestamps are unknown/invalid
    t_future = (now + timedelta(seconds=100)).isoformat()
    assert assess_freshness(t_future, max_age_seconds=10.0) == StateFreshness.UNKNOWN.value


def test_refresh_observation_freshness() -> None:
    """Test updating freshness in-place on an observation object."""
    past_time = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
    obs = StateObservation(
        domain="filesystem",
        subject="test.txt",
        observed_at=past_time,
        status="VERIFIED_SUCCESS",
        state={},
        evidence={},
        freshness="CURRENT",
    )

    # Re-assessing with max_age of 5s should update freshness to STALE or REQUIRES_REFRESH
    refresh_observation_freshness(obs, max_age_seconds=5.0)
    assert obs.freshness == StateFreshness.REQUIRES_REFRESH.value


def test_state_cache_operations() -> None:
    """Test record, get, filtering, and clear operations of StateCache."""
    cache = StateCache()
    timestamp = now_iso()

    obs_app = StateObservation(
        domain="application",
        subject="notepad.exe",
        observed_at=timestamp,
        status="VERIFIED_SUCCESS",
        state={"running": True},
        evidence={},
    )
    obs_file = StateObservation(
        domain="filesystem",
        subject="C:/temp.txt",
        observed_at=timestamp,
        status="VERIFIED_SUCCESS",
        state={"exists": True},
        evidence={},
    )

    # Assert cache starts empty
    assert len(cache.get_all()) == 0
    assert cache.get("application", "notepad.exe") is None

    # Record and get
    cache.record(obs_app)
    cache.record(obs_file)

    cached_app = cache.get("application", "notepad.exe")
    assert cached_app is not None
    assert cached_app.subject == "notepad.exe"
    assert cached_app.state["running"] is True

    # Filtered get_all
    apps = cache.get_all(domain="application")
    assert len(apps) == 1
    assert apps[0].subject == "notepad.exe"

    files = cache.get_all(domain="filesystem")
    assert len(files) == 1
    assert files[0].subject == "C:/temp.txt"

    # Total cache dictionary format
    as_dict = cache.to_dict()
    assert "application:notepad.exe" in as_dict
    assert "filesystem:C:/temp.txt" in as_dict

    # Clear
    cache.clear()
    assert len(cache.get_all()) == 0
    assert cache.get("application", "notepad.exe") is None
