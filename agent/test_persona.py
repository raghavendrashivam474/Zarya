"""
Unit and Integration Tests for S9 Shefali Persona Layer
Validates persona identity stability, capability grounding, truth-preservation,
authorization enforcement, and S8 pipeline handoff.
"""

import pytest
from agent.persona import (
    PersonaDefinition,
    DEFAULT_SHEFALI_PERSONA,
    PersonaRenderer,
    ShefaliPersona,
    PersonaInteractionResult,
)


def test_persona_definition_immutability():
    """Verify PersonaDefinition is frozen and stable."""
    defn = DEFAULT_SHEFALI_PERSONA
    assert defn.name == "Shefali"
    assert "Zarya" in defn.role
    assert len(defn.supported_capabilities) >= 5
    assert len(defn.behavioral_rules) >= 5
    
    with pytest.raises(Exception):
        defn.name = "DifferentName"  # dataclass is frozen


def test_persona_identity_queries():
    """Shefali must consistently identify herself and explain Zarya."""
    persona = ShefaliPersona()
    
    # 1. Who are you?
    r1 = persona.interact("Who are you?")
    assert r1.handled_by == "persona_direct"
    assert "Shefali" in r1.response_text
    assert "Zarya" in r1.response_text
    assert r1.status == "CONVERSATIONAL"
    assert r1.epistemic_certainty == "conversational"
    
    # 2. What is your name?
    r2 = persona.interact("What's your name?")
    assert r2.handled_by == "persona_direct"
    assert "Shefali" in r2.response_text
    
    # 3. Who is Zarya?
    r3 = persona.interact("Who is Zarya?")
    assert r3.handled_by == "persona_direct"
    assert "runtime" in r3.response_text.lower()
    assert "Shefali" in r3.response_text


def test_persona_capability_queries():
    """Shefali must only report grounded capabilities and not fabricate fictional ones."""
    persona = ShefaliPersona()
    r = persona.interact("What can you do?")
    assert r.handled_by == "persona_direct"
    assert "Notepad" in r.response_text
    assert "files" in r.response_text.lower()
    assert "terminal" in r.response_text.lower()
    assert "verified" in r.response_text.lower()


def test_persona_truth_preservation_success():
    """VERIFIED_SUCCESS produces a truthful completion message."""
    renderer = PersonaRenderer()
    intent_res = {
        "status": "VERIFIED_SUCCESS",
        "response": "Done — Notepad opened and verified successfully.",
        "goal": "Open Notepad",
    }
    rendered = renderer.render_intent_dict(intent_res)
    assert rendered.status == "VERIFIED_SUCCESS"
    assert rendered.epistemic_certainty == "certain"
    assert "Done" in rendered.response_text
    assert "verified successfully" in rendered.response_text


def test_persona_truth_preservation_failure():
    """VERIFIED_FAILURE produces an honest failure message."""
    renderer = PersonaRenderer()
    intent_res = {
        "status": "VERIFIED_FAILURE",
        "response": "The operation couldn't complete. Execution stopped and confirmed a failure.",
        "goal": "Open Notepad",
    }
    rendered = renderer.render_intent_dict(intent_res)
    assert rendered.status == "VERIFIED_FAILURE"
    assert rendered.epistemic_certainty == "certain"
    assert "couldn't complete" in rendered.response_text
    assert "failure" in rendered.response_text


def test_persona_truth_preservation_unknown():
    """CRITICAL: UNKNOWN outcome must NEVER claim success and must indicate uncertainty."""
    renderer = PersonaRenderer()
    intent_res = {
        "status": "UNKNOWN",
        "response": "The operation was executed, but Zarya could not verify the outcome with certainty.",
        "goal": "Open Notepad",
    }
    rendered = renderer.render_intent_dict(intent_res)
    assert rendered.status == "UNKNOWN"
    assert rendered.epistemic_certainty == "uncertain"
    assert "could not verify" in rendered.response_text
    assert "Done" not in rendered.response_text


def test_persona_authorization_enforcement():
    """Shefali cannot bypass authorization; unauthorized requests halt."""
    persona = ShefaliPersona()
    r = persona.interact("Open Notepad", authorized=False)
    assert r.handled_by == "s8_intent"
    assert "authorization" in r.response_text.lower()


def test_persona_dangerous_command_refusal():
    """Dangerous requests are refused with safety explanations."""
    persona = ShefaliPersona()
    r = persona.interact("delete entire drive", authorized=True)
    assert r.handled_by == "s8_intent"
    assert r.status == "REFUSED"
    assert "safety" in r.response_text.lower() or "refused" in r.response_text.lower()


def test_persona_ambiguity_clarification():
    """Ambiguous requests trigger clarification rather than hallucinating actions."""
    persona = ShefaliPersona()
    r = persona.interact("open the editor", authorized=True)
    assert r.handled_by == "s8_intent"
    assert r.status == "NEEDS_CLARIFICATION"
    assert "VS Code or Notepad" in r.response_text
