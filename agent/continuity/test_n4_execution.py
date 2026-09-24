"""N4 Execution & Handoff Smoke Test — run from Zarya project root."""
import sys
import os
from pathlib import Path

sys.path.insert(0, ".")

from agent.continuity.reconstruction import ReconstructedWork
from agent.continuity.execution import handoff_to_s18
# We import execution to dynamically control the execution mode in tests
import agent.continuity.execution as n4_exec
from agent.continuity.result import ContinuationStatus, ContinuationStage

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")

print("=" * 60)
print("  N4 S18 Handoff & Execution Smoke Test")
print("=" * 60)

# Save the original import flag state
original_execution_available = n4_exec._S18_EXECUTION_AVAILABLE

# ── Test 1: Block Handoff of Unauthorized Work ──
print("\nTest 1: Prevent Unauthorized Handoff")
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
check("handoff was refused", res.status == ContinuationStatus.UNAUTHORIZED)
check("refused at authorize stage", res.stage == ContinuationStage.AUTHORIZE)
check("reason captured", "direct block" in res.reason)

# ── Test 2: Execution & Standalone Verification (Physical File-Write Slice) ──
print("\nTest 2: Standalone Execution & Verification (Physical Slice)")
# Force standalone fallback execution path for this physical verification test
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

res = handoff_to_s18(authorized_work)
check("execution reports success", res.status == ContinuationStatus.VERIFIED_SUCCESS)
check("reached outcome stage", res.stage == ContinuationStage.OUTCOME)
check("file physically exists", target_file.is_file())
if target_file.is_file():
    content = target_file.read_text(encoding="utf-8")
    check("file content is correct", "Hello World" in content)

# Clean up
if target_file.exists():
    target_file.unlink()

# Restore original execution available flag
n4_exec._S18_EXECUTION_AVAILABLE = original_execution_available

# ── Test 3: S18 Output Dictionary Mapping ──
print("\nTest 3: Dynamic S18 Outcome Dict Mapping")
from agent.continuity.execution import _map_s18_outcome_to_n4

recon_sample = ReconstructedWork(
    work_id="work-123",
    intent="Create report.txt",
    target_operation_id="op-target-123",
    source_operation_id="op-source-123",
    plan={},
    authorized=True,
)

# Simulate a successful output from real agent.intent.execute_work
s18_success_payload = {
    "status": "VERIFIED_SUCCESS",
    "summary": "Verified: report.txt exists and contains valid calculations.",
    "observations": ["Created file report.txt", "Verified file size matches expects"],
}

mapped_res = _map_s18_outcome_to_n4(recon_sample, s18_success_payload)
check("mapped status to success", mapped_res.status == ContinuationStatus.VERIFIED_SUCCESS)
check("observations mapped", "Created file report.txt" in mapped_res.observations)

# Simulate a failed output
s18_fail_payload = {
    "status": "VERIFIED_FAILURE",
    "summary": "Verified: File report.txt is empty",
    "observations": [],
}
mapped_fail = _map_s18_outcome_to_n4(recon_sample, s18_fail_payload)
check("mapped status to failure", mapped_fail.status == ContinuationStatus.VERIFIED_FAILURE)

print("\n" + "=" * 60)
total = passed + failed
print(f"  Results: {passed}/{total} passed, {failed} failed")
print("=" * 60)

sys.exit(1 if failed > 0 else 0)