"""N4 Validation Smoke Test — run from Zarya project root."""
import sys
import json

# Ensure project root is on path
sys.path.insert(0, ".")

from agent.continuity.validation import (
    validate_portable_work,
    validate_portable_json,
    ValidationVerdict,
    PORTABLE_WORK_FORMAT_VERSION,
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
print("  N4 Validation Smoke Test")
print("=" * 60)

# ── Test 1: Valid PortableWork dict ──
print("\nTest 1: Valid PortableWork dict")
valid_pw = {
    "format_version": PORTABLE_WORK_FORMAT_VERSION,
    "work_id": "work-abc123",
    "intent": "Create report.txt containing Hello World",
    "plan_reference": {"steps": [{"action": "write_file", "path": "report.txt"}]},
    "execution_reference": None,
    "artifact_references": ["artifact:file:report_txt"],
    "source_device": "laptop-01",
    "requirements": {"capabilities": ["file_write"]},
    "authorization_metadata": None,
    "context": {},
}
r = validate_portable_work(valid_pw)
check("verdict is PASS", r.is_valid)
check("work_id extracted", r.work_id == "work-abc123")
check("format_version extracted", r.format_version == PORTABLE_WORK_FORMAT_VERSION)
check("no issues", len(r.issues) == 0)

# ── Test 2: Missing format_version ──
print("\nTest 2: Missing format_version")
bad = dict(valid_pw)
del bad["format_version"]
r = validate_portable_work(bad)
check("verdict is FAIL", not r.is_valid)
check("has MISSING_VERSION issue", any(i.code == "MISSING_VERSION" for i in r.issues))

# ── Test 3: Wrong format version ──
print("\nTest 3: Wrong format version")
bad = dict(valid_pw, format_version="n2-old-v0")
r = validate_portable_work(bad)
check("verdict is FAIL", not r.is_valid)
check("has UNSUPPORTED_VERSION issue", any(i.code == "UNSUPPORTED_VERSION" for i in r.issues))

# ── Test 4: Missing work_id ──
print("\nTest 4: Blank work_id")
bad = dict(valid_pw, work_id="   ")
r = validate_portable_work(bad)
check("verdict is FAIL", not r.is_valid)
check("has BLANK_WORK_ID issue", any(i.code == "BLANK_WORK_ID" for i in r.issues))

# ── Test 5: Forbidden runtime field ──
print("\nTest 5: Forbidden runtime field (password)")
bad = dict(valid_pw)
bad["context"] = {"password": "hunter2"}
r = validate_portable_work(bad)
check("verdict is FAIL", not r.is_valid)
check("has FORBIDDEN_FIELD issue", any(i.code == "FORBIDDEN_FIELD" for i in r.issues))

# ── Test 6: Forbidden HWND field ──
print("\nTest 6: Forbidden runtime field (hwnd)")
bad = dict(valid_pw)
bad["hwnd"] = 12345
r = validate_portable_work(bad)
check("verdict is FAIL", not r.is_valid)

# ── Test 7: Invalid artifact_references type ──
print("\nTest 7: artifact_references not a list")
bad = dict(valid_pw, artifact_references="not-a-list")
r = validate_portable_work(bad)
check("verdict is FAIL", not r.is_valid)
check("has INVALID_TYPE issue", any(i.code == "INVALID_TYPE" for i in r.issues))

# ── Test 8: Not a dict ──
print("\nTest 8: Input is not a dict")
r = validate_portable_work("just a string")
check("verdict is FAIL", not r.is_valid)
check("has INVALID_TYPE issue", any(i.code == "INVALID_TYPE" for i in r.issues))

# ── Test 9: JSON validation ──
print("\nTest 9: JSON string validation")
r = validate_portable_json(json.dumps(valid_pw))
check("JSON PASS", r.is_valid)

# ── Test 10: Malformed JSON ──
print("\nTest 10: Malformed JSON")
r = validate_portable_json("{broken json")
check("verdict is FAIL", not r.is_valid)
check("has INVALID_JSON issue", any(i.code == "INVALID_JSON" for i in r.issues))

# ── Test 11: Unknown field warning ──
print("\nTest 11: Unknown field produces WARN")
warn_pw = dict(valid_pw, future_field_xyz="something")
r = validate_portable_work(warn_pw)
check("verdict is WARN", r.verdict == ValidationVerdict.WARN)
check("has UNKNOWN_FIELD issue", any(i.code == "UNKNOWN_FIELD" for i in r.issues))

# ── Summary ──
print("\n" + "=" * 60)
total = passed + failed
print(f"  Results: {passed}/{total} passed, {failed} failed")
print("=" * 60)

sys.exit(1 if failed > 0 else 0)