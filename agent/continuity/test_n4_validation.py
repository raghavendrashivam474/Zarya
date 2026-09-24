"""N4 Validation Smoke & Unit Tests."""
import sys
import os
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent.continuity.validation import (
    validate_portable_work,
    validate_portable_json,
    PORTABLE_WORK_FORMAT_VERSION,
)


def make_valid_work():
    return {
        "format_version": PORTABLE_WORK_FORMAT_VERSION,
        "work_id": "w-test-1234",
        "intent": "Generate annual report",
        "plan_reference": {"plan_id": "plan-1", "steps": []},
        "execution_reference": "exec-1",
        "artifact_references": [],
    }


def test_valid_dict_passes():
    v = validate_portable_work(make_valid_work())
    assert v.is_valid
    assert v.work_id == "w-test-1234"


def test_missing_version_fails():
    w = make_valid_work()
    del w["format_version"]
    v = validate_portable_work(w)
    assert not v.is_valid
    assert any("format_version" in issue.field_name for issue in v.issues)


def test_empty_work_id_fails():
    w = make_valid_work()
    w["work_id"] = "   "
    v = validate_portable_work(w)
    assert not v.is_valid
    assert any("work_id" in issue.field_name for issue in v.issues)


def test_non_dict_input_fails():
    v = validate_portable_work("just a string")
    assert not v.is_valid


def test_valid_json_string_passes():
    json_str = json.dumps(make_valid_work())
    v = validate_portable_json(json_str)
    assert v.is_valid
    assert v.work_id == "w-test-1234"


def test_malformed_json_fails():
    v = validate_portable_json("{not valid json: 123}")
    assert not v.is_valid
    assert any("Malformed" in issue.message for issue in v.issues)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
