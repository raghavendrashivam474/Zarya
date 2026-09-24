"""N4 Execution & S18 Handoff Smoke & Unit Tests."""
import sys
import os
from pathlib import Path
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent.continuity.reconstruction import ReconstructedWork
from agent.continuity.execution import handoff_to_s18, _map_s18_outcome_to_n4
import agent.continuity.execution as n4_exec
from agent.continuity.result import ContinuationStatus, ContinuationStage


def test_prevent_unauthorized_handoff():
    unauthorized_work = ReconstructedWork(
        work_id="work-000",
        intent="Testing unauthorized handoff block",
        target_operation_id="op-target-000",
        source_operation_id="op-source-000",
        plan={"steps": []},
        authorized=False,
        auth_reason="Testing direct block",
    )
    res = handoff_to_s18(unauthorized_work)
    assert res.status == ContinuationStatus.UNAUTHORIZED
    assert res.stage == ContinuationStage.AUTHORIZE
    assert "direct block" in res.reason


def test_standalone_execution_physical_slice():
    original_flag = n4_exec._S18_EXECUTION_AVAILABLE
    n4_exec._S18_EXECUTION_AVAILABLE = False

    target_file = Path("workspace/output_test.txt")
    if target_file.exists():
        target_file.unlink()

    authorized_work = ReconstructedWork(
        work_id="work-777",
        intent="Create a physical test output file",
        target_operation_id="op-target-777",
        source_operation_id="op-source-777",
        plan={
            "steps": [
                {
                    "action": "write_file",
                    "parameters": {
                        "path": str(target_file.resolve()),
                        "content": "Hello World from real handoff physical slice",
                    }
                }
            ]
        },
        authorized=True,
        auth_reason="Locally verified",
    )

    try:
        res = handoff_to_s18(authorized_work)
        assert res.status == ContinuationStatus.VERIFIED_SUCCESS
        assert res.stage == ContinuationStage.OUTCOME
        assert target_file.is_file()
        content = target_file.read_text(encoding="utf-8")
        assert "Hello World" in content
    finally:
        if target_file.exists():
            target_file.unlink()
        n4_exec._S18_EXECUTION_AVAILABLE = original_flag


def test_dynamic_s18_outcome_mapping():
    recon_sample = ReconstructedWork(
        work_id="work-123",
        intent="Create report.txt",
        target_operation_id="op-target-123",
        source_operation_id="op-source-123",
        plan={},
        authorized=True,
    )

    s18_success_payload = {
        "status": "VERIFIED_SUCCESS",
        "summary": "Verified: report.txt exists and contains valid calculations.",
        "observations": ["Created file report.txt", "Verified file size matches expects"],
    }
    mapped_res = _map_s18_outcome_to_n4(recon_sample, s18_success_payload)
    assert mapped_res.status == ContinuationStatus.VERIFIED_SUCCESS
    assert "Created file report.txt" in mapped_res.observations

    s18_fail_payload = {
        "status": "VERIFIED_FAILURE",
        "summary": "Verified: File report.txt is empty",
        "observations": [],
    }
    mapped_fail = _map_s18_outcome_to_n4(recon_sample, s18_fail_payload)
    assert mapped_fail.status == ContinuationStatus.VERIFIED_FAILURE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
