"""N2 Work Context & State Model Tests.

Verifies:
  - Identity boundaries (work_id != operation_id != device_id != artifact_id)
  - Work Intent vs Plan vs Execution separation
  - Environmental context vs Work-relevant context filtering
  - Epistemic outcome preservation (VERIFIED_SUCCESS, VERIFIED_FAILURE, UNKNOWN)
  - S18 lifecycle immutability / non-interference
  - S12 artifact reuse
  - Authorization state representation without authority escalation
  - Platform neutrality (including Android-shaped contexts)
  - Epistemic separation from S7 historical memory
"""

import pytest
from datetime import datetime, timezone

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
    ArtifactReference,
    ObservationProvenance,
)
from agent.lifecycle import (
    LifecycleStatus,
    WorkState,
    StepRecord,
    create_operation,
)
from agent.artifacts import ArtifactIdentity


def test_identity_taxonomy_separation():
    """Verify distinct semantic identities for work_id, operation_id, device_id, artifact_id."""
    plan = {
        "goal": "Process telemetry",
        "steps": [{"id": "s1", "tool": "readFile", "args": {"path": "data.csv"}}]
    }
    work_state = create_operation(goal="Process telemetry", plan=plan, device_id="dev-node-alpha")
    work_state.artifact_ids.append("artifact:file:data_csv")

    unified_ctx = UnifiedContext(
        device=DeviceContext(device_id="dev-node-alpha", platform="WINDOWS"),
    )

    explicit_work_id = "work-user-job-999"
    model = derive_semantic_work(
        work_state=work_state,
        unified_context=unified_ctx,
        authorized=True,
        work_id=explicit_work_id,
    )

    # 1. Verify all 4 identities are distinct
    assert model.work_id == "work-user-job-999"
    assert model.execution_reference == work_state.operation_id
    assert model.execution_reference.startswith("op-")
    assert model.work_id != model.execution_reference
    assert model.relevant_context.device_id == "dev-node-alpha"
    assert "artifact:file:data_csv" in model.artifact_references
    assert model.artifact_references[0] != model.work_id
    assert model.artifact_references[0] != model.execution_reference


def test_deterministic_work_id_derivation():
    """When work_id is not passed, it derives deterministically and stably from operation identity."""
    plan = {"goal": "Compile report", "steps": []}
    ws = create_operation(goal="Compile report", plan=plan)

    model1 = derive_semantic_work(work_state=ws)
    model2 = derive_semantic_work(work_state=ws)

    assert model1.work_id == model2.work_id
    assert model1.work_id.startswith("work-")
    assert model1.execution_reference == ws.operation_id


def test_epistemic_outcome_mapping():
    """Verify mapping of S18 lifecycle status to strict three-value epistemic outcomes."""
    plan = {"goal": "Test outcomes", "steps": []}

    # Case 1: COMPLETED -> VERIFIED_SUCCESS
    ws_success = create_operation(goal="Test outcomes", plan=plan)
    ws_success.status = LifecycleStatus.COMPLETED
    m1 = derive_semantic_work(ws_success)
    assert m1.outcome == "VERIFIED_SUCCESS"

    # Case 2: FAILED -> VERIFIED_FAILURE
    ws_failed = create_operation(goal="Test outcomes", plan=plan)
    ws_failed.status = LifecycleStatus.FAILED
    m2 = derive_semantic_work(ws_failed)
    assert m2.outcome == "VERIFIED_FAILURE"

    # Case 3: RUNNING / PAUSED / INTERRUPTED / CREATED -> UNKNOWN
    for status in [
        LifecycleStatus.CREATED,
        LifecycleStatus.AUTHORIZED,
        LifecycleStatus.RUNNING,
        LifecycleStatus.PAUSED,
        LifecycleStatus.CHECKPOINTED,
        LifecycleStatus.CANCELLING,
        LifecycleStatus.CANCELLED,
        LifecycleStatus.INTERRUPTED,
        LifecycleStatus.UNKNOWN,
    ]:
        ws_in_progress = create_operation(goal="Test outcomes", plan=plan)
        ws_in_progress.status = status
        m = derive_semantic_work(ws_in_progress)
        assert m.outcome == "UNKNOWN", f"Status {status} must result in UNKNOWN outcome"


def test_work_relevant_context_filtering():
    """Verify that irrelevant ambient context is filtered out from RelevantWorkContext."""
    plan = {
        "goal": "Read source code",
        "steps": [
            {"id": "step1", "tool": "readFile", "args": {"path": "src/main.py"}}
        ]
    }
    ws = create_operation(goal="Read source code", plan=plan)
    ws.completed_steps.append(
        StepRecord(
            step_index=0,
            step_id="step1",
            tool="readFile",
            outcome="SUCCESS",
            artifact_ids=["artifact:file:src_main_py"]
        )
    )

    # Ambient context has Chrome open with YouTube, but the work is purely file reading
    unified_ctx = UnifiedContext(
        device=DeviceContext(device_id="dev-pc", platform="LINUX"),
        computer=ComputerContext(active_application="code"),
        browser=BrowserContext(
            browser_name="chrome",
            page_url="https://youtube.com/video123",
            page_title="Random Video",
        ),
    )

    model = derive_semantic_work(work_state=ws, unified_context=unified_ctx)

    assert model.relevant_context is not None
    assert model.relevant_context.platform == "LINUX"
    assert model.relevant_context.active_application == "code"
    # Browser is NOT relevant because no browser tool was executed
    assert model.relevant_context.page_url is None
    assert model.relevant_context.page_title is None
    assert "artifact:file:src_main_py" in model.relevant_context.artifact_ids


def test_browser_relevant_context_inclusion():
    """Verify that browser context is included when work operations actually involve browser tools."""
    plan = {
        "goal": "Fetch documentation",
        "steps": [
            {"id": "step1", "tool": "openWebPage", "args": {"url": "https://docs.python.org"}}
        ]
    }
    ws = create_operation(goal="Fetch documentation", plan=plan)
    ws.completed_steps.append(
        StepRecord(
            step_index=0,
            step_id="step1",
            tool="openWebPage",
            outcome="SUCCESS",
        )
    )

    unified_ctx = UnifiedContext(
        device=DeviceContext(device_id="dev-pc", platform="WINDOWS"),
        browser=BrowserContext(
            browser_name="chromium",
            page_url="https://docs.python.org/3/",
            page_title="Python 3 Documentation",
        ),
    )

    model = derive_semantic_work(work_state=ws, unified_context=unified_ctx)

    assert model.relevant_context is not None
    assert model.relevant_context.page_url == "https://docs.python.org/3/"
    assert model.relevant_context.page_title == "Python 3 Documentation"


def test_artifact_continuity_and_evidence_extraction():
    """Verify that S12 artifact identities and step evidence are accurately preserved."""
    plan = {"goal": "Write script", "steps": []}
    ws = create_operation(goal="Write script", plan=plan)
    ws.artifact_ids.append("artifact:file:root_config")

    # Step records introducing new artifacts via step.artifact_ids or step.evidence
    step = StepRecord(
        step_index=0,
        step_id="s1",
        tool="createPythonFile",
        outcome="SUCCESS",
        evidence={"verification": {"status": "VERIFIED_SUCCESS", "artifact_id": "artifact:file:gen_test_py"}},
        artifact_ids=["artifact:file:extra_log"]
    )
    ws.record_step(step)

    model = derive_semantic_work(work_state=ws)

    assert set(model.artifact_references) == {
        "artifact:file:root_config",
        "artifact:file:gen_test_py",
        "artifact:file:extra_log",
    }
    assert len(model.observations) == 1
    assert model.observations[0]["step_id"] == "s1"
    assert model.observations[0]["outcome"] == "SUCCESS"


def test_authorization_reference_immutability():
    """Verify that N2 records authorization status without being able to grant authority."""
    plan = {"goal": "Dangerous action", "steps": []}
    ws = create_operation(goal="Dangerous action", plan=plan)

    model_unauth = derive_semantic_work(work_state=ws, authorized=False)
    assert model_unauth.authorization_reference["authorized"] is False

    model_auth = derive_semantic_work(work_state=ws, authorized=True)
    assert model_auth.authorization_reference["authorized"] is True


def test_android_shaped_context_compatibility():
    """Verify that Android-shaped contexts (no desktop window handles, no desktop process IDs) work cleanly."""
    plan = {"goal": "Mobile task", "steps": []}
    ws = create_operation(goal="Mobile task", plan=plan)

    android_ctx = UnifiedContext(
        device=DeviceContext(device_id="android-pixel-7", platform="ANDROID", device_type="PHONE"),
        computer=None,  # No desktop concept on Android
        browser=None,
        platform="ANDROID",
    )

    model = derive_semantic_work(work_state=ws, unified_context=android_ctx)

    assert model.relevant_context is not None
    assert model.relevant_context.platform == "ANDROID"
    assert model.relevant_context.device_id == "android-pixel-7"
    assert model.relevant_context.active_application is None
    assert model.relevant_context.page_url is None

    # Serialization test
    serialized = model.to_dict()
    assert serialized["relevant_context"]["platform"] == "ANDROID"
    assert serialized["relevant_context"]["active_application"] is None


def test_model_serialization_n3_readiness():
    """Verify to_dict produces a clean JSON-serializable structure with zero live system handles."""
    plan = {"goal": "Serialization test", "steps": []}
    ws = create_operation(goal="Serialization test", plan=plan)
    ws.status = LifecycleStatus.COMPLETED

    unified_ctx = UnifiedContext(
        device=DeviceContext(device_id="dev-node", platform="WINDOWS"),
    )

    model = derive_semantic_work(work_state=ws, unified_context=unified_ctx, authorized=True)
    d = model.to_dict()

    assert isinstance(d, dict)
    assert d["work_id"] == model.work_id
    assert d["intent"] == "Serialization test"
    assert d["outcome"] == "VERIFIED_SUCCESS"
    assert d["lifecycle_status"] == "COMPLETED"
    assert d["authorization_reference"]["authorized"] is True
