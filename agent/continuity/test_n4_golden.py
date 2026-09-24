"""N4 Golden Integration Unit Tests."""
import sys
import os
from pathlib import Path
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent.continuity import continue_portable_work, ContinuationStatus, ContinuationStage
from agent.continuity.validation import PORTABLE_WORK_FORMAT_VERSION
import agent.continuity.execution as n4_exec


def make_golden_portable_work():
    target_output = Path("workspace/golden_handoff_output.txt")
    if target_output.exists():
        target_output.unlink()

    return {
        "format_version": PORTABLE_WORK_FORMAT_VERSION,
        "work_id": "work-golden-handoff-001",
        "operation_id": "op-source-master-001",
        "intent": "Generate final financial summary on target device",
        "plan_reference": {
            "steps": [
                {
                    "action": "write_file",
                    "parameters": {
                        "path": str(target_output.resolve()),
                        "content": "Golden N4 handoff output successfully written.",
                    }
                }
            ]
        },
        "execution_reference": "exec-financial-001",
        "lifecycle_status": "PAUSED",
        "relevant_context": {},
        "artifact_references": [],
        "authorization_reference": "auth-cross-device-approved",
        "observations": ["Source completed phase 1"],
        "outcome": None,
    }


def test_golden_continuation_pipeline():
    original_flag = n4_exec._S18_EXECUTION_AVAILABLE
    n4_exec._S18_EXECUTION_AVAILABLE = False

    target_output = Path("workspace/golden_handoff_output.txt")
    if target_output.exists():
        target_output.unlink()

    try:
        pw_dict = make_golden_portable_work()
        result = continue_portable_work(pw_dict, local_policy_override=True)

        assert result.status == ContinuationStatus.VERIFIED_SUCCESS
        assert result.stage == ContinuationStage.OUTCOME
        assert result.work_id == "work-golden-handoff-001"
        assert result.operation_id.startswith("op-")
        assert target_output.is_file()
        content = target_output.read_text(encoding="utf-8")
        assert len(content) > 0
    finally:
        if target_output.exists():
            target_output.unlink()
        n4_exec._S18_EXECUTION_AVAILABLE = original_flag


def test_golden_rejection_on_invalid_payload():
    bad_pw = {"format_version": "0.0.1", "corrupt": True}
    res = continue_portable_work(bad_pw)
    assert not res.is_success
    assert res.stage == ContinuationStage.VALIDATE
    assert res.status == ContinuationStatus.BLOCKED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
