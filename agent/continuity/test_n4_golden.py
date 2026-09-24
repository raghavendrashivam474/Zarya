"""N4 Golden Integration Test — run from Zarya project root.

This tests the entire end-to-end Continuation Bridge pipeline.
"""
import sys
import os
import json
from pathlib import Path

sys.path.insert(0, ".")

# Import the unified Continuation Entry Point
from agent.continuity import continue_portable_work, ContinuationStatus, ContinuationStage
import agent.continuity.execution as n4_exec

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

print("=" * 70)
print("  N4 Golden Integration Test — End-to-End")
print("=" * 70)

# Save original S18 execution engine online status, force standalone fallback for integration simulation
original_execution_state = n4_exec._S18_EXECUTION_AVAILABLE
n4_exec._S18_EXECUTION_AVAILABLE = False

# Setup physical file-path to simulate resolved S12 workspace artifact
workspace_dir = Path("workspace")
workspace_dir.mkdir(exist_ok=True)
physical_source_file = workspace_dir / "report.txt"
physical_source_file.write_text("Logical workspace report input")

target_output_file = workspace_dir / "report_final.txt"
if target_output_file.exists():
    target_output_file.unlink()

# Generate a raw JSON-safe representation simulating a transmitted PortableWork payload
portable_payload = {
    "format_version": "n3-portable-v1",
    "work_id": "work-golden-999",
    "intent": "Read input report and write final output report",
    "source_device": "laptop-01",
    "execution_reference": "op-source-1234",
    "artifact_references": [
        "artifact:file:report_txt"
    ],
    "requirements": {
        "capabilities": ["files", "system"]
    },
    "authorization_metadata": {
        "requires_token": False
    },
    "plan_reference": {
        "steps": [
            {
                "action": "write_file",
                "parameters": {
                    "path": str(target_output_file.resolve()),
                    "content": "Golden execution success!",
                }
            }
        ]
    }
}

# ── 1. Clean Path: Standard Happy Flow ──
print("\n[Flow 1] Happy Path End-to-End Continuation")
result = continue_portable_work(
    portable_work=portable_payload,
    local_policy_override=True
)

check("Pipeline reports complete success", result.status == ContinuationStatus.VERIFIED_SUCCESS)
check("Logical work_id matches input payload", result.work_id == "work-golden-999")
check("Distinct target operation_id was generated", result.operation_id != "op-source-1234")
check("Reached final outcome stage", result.stage == ContinuationStage.OUTCOME)
check("Physical file was created on target system", target_output_file.is_file())
if target_output_file.is_file():
    check("Physical file content is correct", "Golden execution" in target_output_file.read_text())

# Clean up
if target_output_file.exists():
    target_output_file.unlink()


# ── 2. Error Path: Validation Failure ──
print("\n[Flow 2] Schema Validation Fail Gate")
bad_schema_payload = dict(portable_payload)
del bad_schema_payload["intent"] # Missing required schema key

result_val = continue_portable_work(bad_schema_payload)
check("Pipeline blocks execution", result_val.status == ContinuationStatus.BLOCKED)
check("Blocks at VALIDATE stage", result_val.stage == ContinuationStage.VALIDATE)
check("Reason mentions missing field", "Required field 'intent' is absent" in result_val.reason)


# ── 3. Error Path: Unsupported Capabilities ──
print("\n[Flow 3] Capability Check Gate")
unsupported_payload = dict(portable_payload)
unsupported_payload["requirements"] = {"capabilities": ["non_existent_tool"]}

result_cap = continue_portable_work(unsupported_payload)
check("Pipeline blocks execution", result_cap.status == ContinuationStatus.UNSUPPORTED)
check("Blocks at SUPPORT_CHECK stage", result_cap.stage == ContinuationStage.SUPPORT_CHECK)
check("Reason lists the missing tool", "non_existent_tool" in result_cap.reason)


# ── 4. Error Path: Missing Artifacts ──
print("\n[Flow 4] Artifact Resolution Gate")
missing_art_payload = dict(portable_payload)
missing_art_payload["artifact_references"] = ["artifact:file:unresolved_file_csv"]

result_art = continue_portable_work(missing_art_payload)
check("Pipeline blocks execution", result_art.status == ContinuationStatus.BLOCKED)
check("Blocks at RESOLVE stage", result_art.stage == ContinuationStage.RESOLVE)
check("Reason lists the missing artifact", "unresolved_file_csv" in result_art.reason)


# ── 5. Error Path: Unauthorized Continuation ──
print("\n[Flow 5] Security Authorization Gate")
unauthorized_payload = dict(portable_payload)
unauthorized_payload["plan_reference"] = {
    "steps": [{"action": "terminal", "parameters": {"command": "rm -rf /"}}]
}

result_auth = continue_portable_work(unauthorized_payload)
check("Pipeline blocks execution", result_auth.status == ContinuationStatus.UNAUTHORIZED)
check("Blocks at AUTHORIZE stage", result_auth.stage == ContinuationStage.AUTHORIZE)
check("Reason documents tool protection block", "critical tool" in result_auth.reason)


# ── Clean up environment ──
if physical_source_file.exists():
    physical_source_file.unlink()

# Restore execution state
n4_exec._S18_EXECUTION_AVAILABLE = original_execution_state

print("\n" + "=" * 70)
total = passed + failed
print(f"  Golden Integration Results: {passed}/{total} passed, {failed} failed")
print("=" * 70)

sys.exit(1 if failed > 0 else 0)