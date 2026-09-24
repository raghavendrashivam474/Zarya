"""N4 Resolution Smoke Test — run from Zarya project root."""
import sys
import os
from pathlib import Path

sys.path.insert(0, ".")

from agent.continuity.resolution import (
    resolve_target_capabilities,
    resolve_target_artifacts,
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
print("  N4 Resolution Smoke Test")
print("=" * 60)

# Ensure workspace/ exists for tests
workspace_dir = Path("workspace")
workspace_dir.mkdir(exist_ok=True)
test_file = workspace_dir / "report.txt"
test_file.write_text("Hello World from target resolution test")

# ── Test 1: Capability Resolution (Valid/Present) ──
print("\nTest 1: Capability Resolution (Present)")
# We request "files" or "system" which are standard files in agent/tools/
portable_pw = {
    "requirements": {
        "capabilities": ["files", "system"]
    }
}
res = resolve_target_capabilities(portable_pw)
check("capabilities supported", res.supported)
check("available listed", "files" in res.available_capabilities)
check("no missing", len(res.missing_capabilities) == 0)

# ── Test 2: Capability Resolution (Unsupported) ──
print("\nTest 2: Capability Resolution (Unsupported)")
bad_portable_pw = {
    "requirements": {
        "capabilities": ["files", "non_existent_crazy_tool_99"]
    }
}
res = resolve_target_capabilities(bad_portable_pw)
check("capabilities unsupported", not res.supported)
check("missing listed", "non_existent_crazy_tool_99" in res.missing_capabilities)
check("reasons documented", len(res.reasons) > 0)

# ── Test 3: Artifact Resolution (Valid/Found via mock filename match) ──
print("\nTest 3: Artifact Resolution (Found)")
art_refs = ["artifact:file:report_txt"]
res = resolve_target_artifacts(art_refs)
check("artifact resolved", res.resolved)
check("path mapped", "artifact:file:report_txt" in res.resolved_paths)
if res.resolved:
    resolved_path = res.resolved_paths["artifact:file:report_txt"]
    check("path exists physically", os.path.exists(resolved_path))

# ── Test 4: Artifact Resolution (S12 Mock Registry Resolution) ──
print("\nTest 4: S12 Registry Resolution Mock")
class MockArtifactIdentity:
    def __init__(self, path):
        self.path = path

class MockS12Registry:
    def get(self, art_id):
        if art_id == "artifact:file:special_pdf":
            return MockArtifactIdentity(Path("workspace/report.txt").resolve())
        return None

registry = MockS12Registry()
res = resolve_target_artifacts(["artifact:file:special_pdf"], artifact_registry=registry)
check("resolved via registry", res.resolved)
# FIX: The path maps to report.txt, so check that report.txt is in the resolved path string
resolved_path = res.resolved_paths.get("artifact:file:special_pdf", "")
check("correct path maps to report.txt", "report.txt" in resolved_path)

# ── Test 5: Artifact Resolution (Missing/Not Found) ──
print("\nTest 5: Artifact Resolution (Missing)")
bad_art_refs = ["artifact:file:missing_file_xyz"]
res = resolve_target_artifacts(bad_art_refs)
check("artifact not resolved", not res.resolved)
check("missing listed", "artifact:file:missing_file_xyz" in res.missing_artifacts)
check("reasons documented", len(res.reasons) > 0)

# Clean up
if test_file.exists():
    test_file.unlink()

print("\n" + "=" * 60)
total = passed + failed
print(f"  Results: {passed}/{total} passed, {failed} failed")
print("=" * 60)

sys.exit(1 if failed > 0 else 0)