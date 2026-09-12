import pytest
from agent.intent import (
    IntentInterpreter, 
    PlanValidator, 
    ResponseTranslator, 
    process_natural_intent, 
    S8WorkPlan, 
    S8Step
)

# 1. Intent Interpreter Tests
def test_interpreter_open_notepad():
    interpreter = IntentInterpreter()
    plan = interpreter.interpret("Open Notepad")
    assert plan.status == "UNDERSTOOD"
    assert plan.steps[0].tool == "openApplication"
    assert plan.steps[0].args == {"application": "notepad"}

def test_interpreter_open_vscode():
    interpreter = IntentInterpreter()
    plan = interpreter.interpret("open vscode please")
    assert plan.status == "UNDERSTOOD"
    assert plan.steps[0].tool == "openApplication"
    assert plan.steps[0].args == {"application": "vscode"}

def test_interpreter_create_file():
    interpreter = IntentInterpreter()
    plan = interpreter.interpret("create a file called notes.txt with 'Hello Zarya'")
    assert plan.status == "UNDERSTOOD"
    assert plan.goal == "Create file notes.txt"
    assert plan.steps[0].tool == "createFile"
    assert plan.steps[0].args == {"path": "notes.txt", "content": "Hello Zarya"}

def test_interpreter_read_file():
    interpreter = IntentInterpreter()
    plan = interpreter.interpret("read the file called config.json")
    assert plan.status == "UNDERSTOOD"
    assert plan.steps[0].tool == "readFile"
    assert plan.steps[0].args == {"path": "config.json"}

def test_interpreter_clarification_on_ambiguous_editor():
    interpreter = IntentInterpreter()
    plan = interpreter.interpret("Open the editor")
    assert plan.status == "NEEDS_CLARIFICATION"
    assert "VS Code or Notepad" in plan.clarification_message

def test_interpreter_refusal_on_dangerous_command():
    interpreter = IntentInterpreter()
    plan = interpreter.interpret("delete entire drive")
    assert plan.status == "REFUSED"
    assert "violates safety constraints" in plan.clarification_message

# 2. Plan Validator Tests
def test_validator_allowed_and_disallowed():
    # Valid plan
    valid_plan = S8WorkPlan(
        intent="open notepad",
        goal="Open Notepad",
        steps=[S8Step(tool="openApplication", args={"application": "notepad"}, description="Launch")],
        status="UNDERSTOOD"
    )
    is_valid, _ = PlanValidator.validate(valid_plan)
    assert is_valid is True

    # Disallowed tool
    invalid_tool_plan = S8WorkPlan(
        intent="format disk",
        goal="Format",
        steps=[S8Step(tool="formatDisk", args={}, description="Dangerous")],
        status="UNDERSTOOD"
    )
    is_valid, reason = PlanValidator.validate(invalid_tool_plan)
    assert is_valid is False
    assert "unregistered/disallowed" in reason

    # Unsafe path extension
    unsafe_path_plan = S8WorkPlan(
        intent="create script",
        goal="Script",
        steps=[S8Step(tool="createFile", args={"path": "malicious.bat", "content": "echo bad"}, description="write")],
        status="UNDERSTOOD"
    )
    is_valid, reason = PlanValidator.validate(unsafe_path_plan)
    assert is_valid is False
    assert "unsafe path" in reason

# 3. Response Translator (Containment & Truthfulness Tests)
def test_response_translator_verified_success():
    res = {
        "overall_status": "VERIFIED_SUCCESS",
        "summary": "Application opened and PID detected.",
        "goal": "Open Notepad"
    }
    msg = ResponseTranslator.translate(res)
    assert "Done" in msg
    assert "verified successfully" in msg

def test_response_translator_verified_failure():
    res = {
        "overall_status": "VERIFIED_FAILURE",
        "summary": "Process terminated immediately.",
        "goal": "Open Notepad"
    }
    msg = ResponseTranslator.translate(res)
    assert "couldn't complete" in msg
    assert "confirmed a failure" in msg

def test_response_translator_unknown_containment():
    # Critical test: UNKNOWN must NOT claim success
    res = {
        "overall_status": "UNKNOWN",
        "summary": "No PID returned to confirm application state.",
        "goal": "Open Notepad"
    }
    msg = ResponseTranslator.translate(res)
    assert "could not verify the outcome with certainty" in msg
    assert "Done" not in msg

# 4. Full Pipeline Integration with S6
def test_full_pipeline_unauthorized_gate():
    # When authorized=False, pipeline should halt safely at authorization gate
    res = process_natural_intent("Open Notepad", authorized=False)
    assert res["status"] in ["INCOMPLETE", "UNAUTHORIZED"]
    assert "authorization" in res["response"].lower()

def test_full_pipeline_clarification():
    res = process_natural_intent("open the editor", authorized=True)
    assert res["status"] == "NEEDS_CLARIFICATION"
    assert "VS Code or Notepad" in res["response"]
