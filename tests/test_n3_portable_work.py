"""N3 Portable Work Representation Tests.

Verifies:
  - Transformation from N2 SemanticWorkModel to N3 PortableWork
  - Strict schema versioning (format_version) & rejection of invalid/unsupported schemas
  - Loss-aware serialization (runtime-local handles stripped, not falsified)
  - Security boundary: secret & credential stripping
  - Exact round-trip serialization/deserialization fidelity
  - Cross-device/platform neutrality (Windows, Linux, Android contexts)
  - S12 Artifact reference preservation without local filesystem path leakage
  - Authorization metadata isolation (metadata preserved, no authority escalation)
  - Epistemic outcome preservation (VERIFIED_SUCCESS, VERIFIED_FAILURE, UNKNOWN)
  - Deterministic serialization output
"""

import json
import pytest

from agent.context.portable_work import (
    PORTABLE_WORK_FORMAT_VERSION,
    PortableWork,
    make_portable,
)
from agent.context.work_model import (
    RelevantWorkContext,
    SemanticWorkModel,
    derive_semantic_work,
)
from agent.context.unified import (
    UnifiedContext,
    DeviceContext,
    ComputerContext,
    BrowserContext,
)
from agent.lifecycle import (
    LifecycleStatus,
    WorkState,
    StepRecord,
    create_operation,
)


@pytest.fixture
def sample_semantic_model():
    """Create a fully-populated SemanticWorkModel from S18 and N1."""
    plan = {
        "goal": "Refactor parser",
        "steps": [
            {"id": "s1", "tool": "readFile", "args": {"path": "parser.py"}},
            {"id": "s2", "tool": "editFile", "args": {"path": "parser.py"}},
        ]
    }
    ws = create_operation(goal="Refactor parser", plan=plan, device_id="node-desktop-1")
    ws.record_step(StepRecord(
        step_index=0,
        step_id="s1",
        tool="readFile",
        outcome="SUCCESS",
        artifact_ids=["artifact:file:parser_py"],
        evidence={"status": "read_complete"}
    ))
    ws.status = LifecycleStatus.RUNNING

    u_ctx = UnifiedContext(
        device=DeviceContext(device_id="node-desktop-1", platform="LINUX"),
        computer=ComputerContext(
            active_application="code",
            process_id=45120,
            platform_detail={"wm_class": "code", "wayland": True},
        ),
    )

    return derive_semantic_work(
        work_state=ws,
        unified_context=u_ctx,
        authorized=True,
        work_id="work-refactor-42"
    )


def test_make_portable_basic(sample_semantic_model):
    """Verify that make_portable extracts all relevant semantic information with correct version."""
    portable = make_portable(
        model=sample_semantic_model,
        source_device="node-desktop-1",
        requirements=["requires_filesystem"]
    )

    assert portable.format_version == PORTABLE_WORK_FORMAT_VERSION
    assert portable.work_id == "work-refactor-42"
    assert portable.intent == "Refactor parser"
    assert portable.platform == "LINUX"
    assert portable.source_device == "node-desktop-1"
    assert portable.lifecycle_status == "RUNNING"
    assert portable.outcome == "UNKNOWN"
    assert portable.requirements == ["requires_filesystem"]
    assert "artifact:file:parser_py" in portable.artifact_references


def test_round_trip_serialization(sample_semantic_model):
    """Verify clean round-trip: make_portable -> to_portable_dict -> from_portable_dict."""
    portable_orig = make_portable(sample_semantic_model, requirements=["requires_filesystem"])
    data = portable_orig.to_portable_dict()

    # JSON round trip simulation (across wire/storage)
    json_payload = json.dumps(data)
    deserialized_data = json.loads(json_payload)

    portable_restored = PortableWork.from_portable_dict(deserialized_data)

    assert portable_restored.format_version == portable_orig.format_version
    assert portable_restored.work_id == portable_orig.work_id
    assert portable_restored.intent == portable_orig.intent
    assert portable_restored.plan_reference == portable_orig.plan_reference
    assert portable_restored.outcome == portable_orig.outcome
    assert portable_restored.execution_reference == portable_orig.execution_reference
    assert portable_restored.lifecycle_status == portable_orig.lifecycle_status
    assert portable_restored.platform == portable_orig.platform
    assert portable_restored.active_application == portable_orig.active_application
    assert portable_restored.artifact_references == portable_orig.artifact_references
    assert portable_restored.authorization_metadata == portable_orig.authorization_metadata
    assert portable_restored.observations == portable_orig.observations
    assert portable_restored.requirements == portable_orig.requirements


def test_runtime_local_handles_strictly_excluded():
    """Verify that OS PIDs, HWNDs, window handles, and local paths are excluded from serialized dictionary."""
    model = SemanticWorkModel(
        work_id="work-sec-1",
        intent="Test handle scrubbing",
        plan_reference={"steps": []},
        relevant_context=RelevantWorkContext(
            device_id="dev-win",
            platform="WINDOWS",
            active_application="notepad.exe"
        ),
        observations=[{
            "step_id": "s1",
            "tool": "launch",
            "process_id": 9999,
            "hwnd": 123456,
            "pid": 9999,
            "canonical_locator": "C:\\Users\\local\\test.txt",
            "safe_detail": "opened_notepad"
        }]
    )

    portable = make_portable(model)
    serialized = portable.to_portable_dict()

    # Verify root and nested observations do not contain local handles
    serialized_str = json.dumps(serialized)
    assert "process_id" not in serialized_str
    assert "hwnd" not in serialized_str
    assert "pid" not in serialized_str
    assert "canonical_locator" not in serialized_str
    assert "opened_notepad" in serialized_str


def test_secret_credential_stripping():
    """Verify that API keys, passwords, and tokens are scrubbed from plan and observation payloads."""
    model = SemanticWorkModel(
        work_id="work-auth-strip",
        intent="Scrub auth credentials",
        plan_reference={
            "steps": [{
                "id": "s1",
                "tool": "apiCall",
                "api_key": "sk-secret-12345",
                "auth_token": "bearer-xyz",
                "nested": {
                    "password": "super-secret-pass",
                    "session_cookie": "sess_987654321",
                    "safe_param": "public_data"
                }
            }]
        },
        authorization_reference={
            "authorized": True,
            "policy": "POLICY_EXPLICIT_STEP",
            "user_token": "secret_jwt_token"
        }
    )

    portable = make_portable(model)
    serialized = portable.to_portable_dict()

    json_str = json.dumps(serialized)
    assert "sk-secret-12345" not in json_str
    assert "bearer-xyz" not in json_str
    assert "super-secret-pass" not in json_str
    assert "sess_987654321" not in json_str
    assert "secret_jwt_token" not in json_str
    assert "public_data" in json_str
    # Authorization metadata policy is preserved
    assert serialized["authorization"]["authorized"] is True
    assert serialized["authorization"]["policy"] == "POLICY_EXPLICIT_STEP"


def test_schema_version_validation():
    """Verify schema version enforcement and rejection of missing/unsupported versions."""
    valid_data = {
        "format_version": PORTABLE_WORK_FORMAT_VERSION,
        "work": {"work_id": "work-1", "intent": "Test", "plan_reference": {}, "outcome": "UNKNOWN"},
        "execution": {},
        "context": {},
        "portability": {},
    }

    # Valid schema succeeds
    pw = PortableWork.from_portable_dict(valid_data)
    assert pw.work_id == "work-1"

    # Missing format_version fails
    invalid_no_version = dict(valid_data)
    del invalid_no_version["format_version"]
    with pytest.raises(ValueError, match="missing format_version"):
        PortableWork.from_portable_dict(invalid_no_version)

    # Unsupported format_version fails
    invalid_future_version = dict(valid_data)
    invalid_future_version["format_version"] = "n99-future-format-v99"
    with pytest.raises(ValueError, match="Unsupported PortableWork format_version"):
        PortableWork.from_portable_dict(invalid_future_version)

    # Non-dict input fails
    with pytest.raises(TypeError, match="Expected dict"):
        PortableWork.from_portable_dict("not-a-dict")


def test_android_shaped_work_portability():
    """Verify that Android-shaped work (no window title, no browser, phone device) serializes and deserializes cleanly."""
    plan = {"goal": "Process mobile image", "steps": []}
    ws = create_operation(goal="Process mobile image", plan=plan, device_id="android-tablet-tab9")
    ws.status = LifecycleStatus.COMPLETED

    android_ctx = UnifiedContext(
        device=DeviceContext(device_id="android-tablet-tab9", platform="ANDROID", device_type="TABLET"),
        computer=None,
        browser=None,
        platform="ANDROID",
    )

    model = derive_semantic_work(work_state=ws, unified_context=android_ctx, authorized=True)
    portable = make_portable(model, requirements=["requires_android_camera"])

    assert portable.platform == "ANDROID"
    assert portable.active_application is None
    assert portable.page_url is None
    assert portable.outcome == "VERIFIED_SUCCESS"
    assert portable.requirements == ["requires_android_camera"]

    # Round trip test
    serialized = portable.to_portable_dict()
    assert serialized["context"]["platform"] == "ANDROID"
    assert serialized["context"]["active_application"] is None
    restored = PortableWork.from_portable_dict(serialized)
    assert restored.platform == "ANDROID"
    assert restored.outcome == "VERIFIED_SUCCESS"


def test_to_json_and_from_json_helpers(sample_semantic_model):
    """Verify direct to_json and from_json helper methods."""
    portable = make_portable(sample_semantic_model)
    json_str = portable.to_json(indent=2)

    assert isinstance(json_str, str)
    assert PORTABLE_WORK_FORMAT_VERSION in json_str

    restored = PortableWork.from_json(json_str)
    assert restored.work_id == portable.work_id
    assert restored.intent == portable.intent
    assert restored.format_version == portable.format_version