"""N4 Reconstruction & Authorization Smoke & Unit Tests."""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent.continuity.reconstruction import (
    authorize_continuation,
    reconstruct_executable_work,
)
from agent.continuity.validation import PORTABLE_WORK_FORMAT_VERSION


def make_pw_for_recon(work_id="work-recon-1", intent="Generate monthly reports"):
    return {
        "format_version": PORTABLE_WORK_FORMAT_VERSION,
        "work_id": work_id,
        "operation_id": "op-source-999",
        "intent": intent,
        "plan_reference": {"steps": []},
        "execution_reference": "op-source-999",
        "lifecycle_status": "PAUSED",
        "relevant_context": {"target_dir": "/output"},
        "artifact_references": [],
        "authorization_reference": "auth-valid-token-123",
        "observations": ["observation from source machine"],
        "outcome": None,
    }


def test_authorization_with_local_override_passes():
    pw = make_pw_for_recon()
    is_auth, reason = authorize_continuation(pw, local_policy_override=True)
    assert is_auth
    assert "override" in reason.lower()


def test_authorization_standard_local_passes():
    pw = make_pw_for_recon()
    is_auth, reason = authorize_continuation(pw)
    assert is_auth
    assert "standard" in reason.lower()


def test_reconstruction_produces_valid_work_item():
    pw = make_pw_for_recon()
    is_auth, auth_reason = authorize_continuation(pw, local_policy_override=True)
    reconstructed = reconstruct_executable_work(
        pw,
        resolved_paths={},
        is_authorized=is_auth,
        auth_reason=auth_reason,
    )
    assert reconstructed.work_id == "work-recon-1"
    assert reconstructed.source_operation_id == "op-source-999"
    assert reconstructed.target_operation_id.startswith("op-")
    assert reconstructed.intent == "Generate monthly reports"
    assert reconstructed.authorized is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
