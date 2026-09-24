"""N4 Reconstruction & Authorization Smoke Test — run from Zarya project root."""
import sys
import os

sys.path.insert(0, ".")

from agent.continuity.reconstruction import (
    authorize_continuation,
    reconstruct_executable_work,
)

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
print("  N4 Reconstruction Smoke Test")
print("=" * 60)

# Dummy/Valid PortableWork payload
valid_portable = {
    "work_id": "work-99abcf",
    "format_version": "n3-portable-v1",
    "intent": "Write report.txt and process it",
    "execution_reference": "op-source-111",
    "plan_reference": {
        "steps": [
            {
                "action": "write_file",
                "parameters": {
                    "path": "artifact:file:report_txt",
                    "content": "Hello World",
                }
            },
            {
                "action": "process_file",
                "parameters": {
                    "input_file": "artifact:file:report_txt",
                }
            }
        ]
    },
    "authorization_metadata": {
        "requires_token": False
    }
}

# ── Test 1: Local Authorization (Standard Safe Plan) ──
print("\nTest 1: Standard Authorization Gate")
is_auth, reason = authorize_continuation(valid_portable)
check("safe plan is authorized", is_auth)
check("auth reason provided", len(reason) > 0)

# ── Test 2: Local Authorization Block (Unsafe Tool terminal) ──
print("\nTest 2: Block Critical Actions without Token")
unsafe_portable = dict(valid_portable)
unsafe_portable["plan_reference"] = {
    "steps": [{"action": "terminal", "parameters": {"command": "rm -rf /"}}]
}
is_auth, reason = authorize_continuation(unsafe_portable)
check("unsafe command blocked", not is_auth)
check("blocked for critical tool reason", "critical tool" in reason)

# ── Test 3: Local Override Authorization ──
print("\nTest 3: Administrative Override Auth")
is_auth, reason = authorize_continuation(unsafe_portable, local_policy_override=True)
check("override ignores blocks", is_auth)
check("override reason listed", "override" in reason)

# ── Test 4: S18 Plan Reconstruction & Path Mapping ──
print("\nTest 4: Plan Reconstruction & Path Mapping")
resolved_paths = {
    "artifact:file:report_txt": "C:\\Zarya\\workspace\\report.txt"
}

reconstructed = reconstruct_executable_work(
    portable_dict=valid_portable,
    resolved_paths=resolved_paths,
    is_authorized=True,
    auth_reason="Testing auth pass"
)

check("work_id preserved", reconstructed.work_id == "work-99abcf")
check("source operation_id preserved", reconstructed.source_operation_id == "op-source-111")
check("new unique target operation_id generated", reconstructed.target_operation_id != "op-source-111")
check("new target operation_id starts with op-", reconstructed.target_operation_id.startswith("op-"))

# Check path mappings inside the steps dictionary
steps = reconstructed.plan["steps"]
check("step 0 parameters contains substituted path", steps[0]["parameters"]["path"] == "C:\\Zarya\\workspace\\report.txt")
check("step 1 parameters contains substituted path", steps[1]["parameters"]["input_file"] == "C:\\Zarya\\workspace\\report.txt")
check("auth propagation check", reconstructed.authorized)

print("\n" + "=" * 60)
total = passed + failed
print(f"  Results: {passed}/{total} passed, {failed} failed")
print("=" * 60)

sys.exit(1 if failed > 0 else 0)