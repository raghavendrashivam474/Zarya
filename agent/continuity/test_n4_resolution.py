"""N4 Resolution Smoke & Unit Tests."""
import sys
import os
import pytest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent.continuity.resolution import (
    resolve_target_capabilities,
    resolve_target_artifacts,
)


def make_pw(required_caps=None):
    return {
        "requirements": {
            "capabilities": required_caps or []
        }
    }


def test_known_capabilities_pass():
    # 'files', 'browser', 'terminal' exist in agent/tools/*.py
    pw = make_pw(required_caps=["files", "browser", "terminal"])
    res = resolve_target_capabilities(pw)
    assert res.supported
    assert len(res.missing_capabilities) == 0


def test_unknown_capability_fails():
    pw = make_pw(required_caps=["quantum_computation", "teleportation"])
    res = resolve_target_capabilities(pw)
    assert not res.supported
    assert "quantum_computation" in res.missing_capabilities
    assert "teleportation" in res.missing_capabilities


def test_empty_capabilities_passes():
    pw = make_pw(required_caps=[])
    res = resolve_target_capabilities(pw)
    assert res.supported


def test_empty_artifacts_passes():
    res = resolve_target_artifacts([])
    assert res.resolved
    assert len(res.missing_artifacts) == 0


def test_missing_file_artifact_fails():
    bogus = "workspace/nonexistent_artifact_xyz123.bin"
    res = resolve_target_artifacts([bogus])
    assert not res.resolved
    assert bogus in res.missing_artifacts


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
