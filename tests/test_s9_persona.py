"""
S9 Milestone Test Suite — Shefali Persona & Presence Layer
Validates persona identity, communication invariants, truth preservation,
authorization enforcement, S8 pipeline integration, and S7 context semantics.
"""

import pytest
from fastapi.testclient import TestClient

from agent.persona import (
    PersonaDefinition,
    DEFAULT_SHEFALI_PERSONA,
    PersonaRenderer,
    ShefaliPersona,
    PersonaInteractionResult,
)
from agent.server import app


# ===========================================================================
# 1. Identity Contract Tests
# ===========================================================================
class TestS9PersonaIdentity:
    def test_default_persona_identity(self):
        defn = DEFAULT_SHEFALI_PERSONA
        assert defn.name == "Shefali"
        assert "Zarya" in defn.role
        assert "verified" in defn.identity_summary.lower()

    def test_identity_query_who_are_you(self):
        persona = ShefaliPersona()
        res = persona.interact("Who are you?")
        assert res.handled_by == "persona_direct"
        assert res.status == "CONVERSATIONAL"
        assert "Shefali" in res.response_text
        assert "Zarya" in res.response_text

    def test_identity_query_who_is_zarya(self):
        persona = ShefaliPersona()
        res = persona.interact("Who is Zarya?")
        assert res.handled_by == "persona_direct"
        assert "runtime" in res.response_text.lower()
        assert "Shefali" in res.response_text

    def test_identity_query_name_variations(self):
        persona = ShefaliPersona()
        for q in ["what is your name", "What's your name?", "introduce yourself", "tell me about yourself"]:
            res = persona.interact(q)
            assert res.handled_by == "persona_direct"
            assert "Shefali" in res.response_text


# ===========================================================================
# 2. Capability Grounding Tests
# ===========================================================================
class TestS9CapabilityGrounding:
    def test_capability_query_reports_grounded_tools(self):
        persona = ShefaliPersona()
        for q in ["What can you do?", "what are your capabilities", "help", "what do you support"]:
            res = persona.interact(q)
            assert res.handled_by == "persona_direct"
            assert "Notepad" in res.response_text
            assert "files" in res.response_text.lower()
            assert "terminal" in res.response_text.lower()

    def test_capabilities_do_not_claim_omnipotence(self):
        defn = DEFAULT_SHEFALI_PERSONA
        for cap in defn.supported_capabilities:
            assert "anything" not in cap.lower()
            assert "unrestricted" not in cap.lower()


# ===========================================================================
# 3. Truth-Preservation & Epistemic Boundaries
# ===========================================================================
class TestS9TruthPreservation:
    def test_verified_success_presentation(self):
        renderer = PersonaRenderer()
        raw = {
            "status": "VERIFIED_SUCCESS",
            "response": "Done — Notepad opened and verified successfully.",
            "goal": "Open Notepad",
        }
        res = renderer.render_intent_dict(raw)
        assert res.status == "VERIFIED_SUCCESS"
        assert res.epistemic_certainty == "certain"
        assert "Done" in res.response_text
        assert "verified successfully" in res.response_text

    def test_verified_failure_presentation(self):
        renderer = PersonaRenderer()
        raw = {
            "status": "VERIFIED_FAILURE",
            "response": "The operation couldn't complete. Execution stopped and confirmed a failure.",
            "goal": "Open Notepad",
        }
        res = renderer.render_intent_dict(raw)
        assert res.status == "VERIFIED_FAILURE"
        assert res.epistemic_certainty == "certain"
        assert "couldn't complete" in res.response_text

    def test_unknown_containment_never_claims_success(self):
        renderer = PersonaRenderer()
        raw = {
            "status": "UNKNOWN",
            "response": "The operation was executed, but Zarya could not verify the outcome with certainty.",
            "goal": "Open Notepad",
        }
        res = renderer.render_intent_dict(raw)
        assert res.status == "UNKNOWN"
        assert res.epistemic_certainty == "uncertain"
        assert "could not verify" in res.response_text
        assert "Done" not in res.response_text


# ===========================================================================
# 4. S8 Intent Integration & Safety Gates
# ===========================================================================
class TestS9IntentAndSafetyGates:
    def test_unauthorized_action_blocked(self):
        persona = ShefaliPersona()
        res = persona.interact("Open Notepad", authorized=False)
        assert res.handled_by == "s8_intent"
        assert "authorization" in res.response_text.lower()

    def test_dangerous_request_refused(self):
        persona = ShefaliPersona()
        res = persona.interact("delete entire drive", authorized=True)
        assert res.handled_by == "s8_intent"
        assert res.status == "REFUSED"
        assert "safety" in res.response_text.lower() or "refused" in res.response_text.lower()

    def test_ambiguous_request_clarification(self):
        persona = ShefaliPersona()
        res = persona.interact("open the editor", authorized=True)
        assert res.handled_by == "s8_intent"
        assert res.status == "NEEDS_CLARIFICATION"
        assert "VS Code or Notepad" in res.response_text


# ===========================================================================
# 5. S7 Context Semantics (Memory != Current Truth)
# ===========================================================================
class TestS9ContextSemantics:
    def test_context_passed_to_intent_layer(self):
        persona = ShefaliPersona()
        sample_context = [
            {
                "memory_id": "mem_001",
                "type": "observation",
                "content": {"domain": "application", "target": "notepad", "verified": True},
                "epistemic_status": "HISTORICAL",
            }
        ]
        # Providing historical context must not bypass authorization for new actions
        res = persona.interact("Open Notepad", authorized=False, context_memory=sample_context)
        assert res.handled_by == "s8_intent"
        assert "authorization" in res.response_text.lower()


# ===========================================================================
# 6. HTTP API Persona Endpoints
# ===========================================================================
class TestS9ServerEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_get_persona_describe(self, client):
        resp = client.get("/persona/describe")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Shefali"
        assert "capabilities" in data
        assert len(data["capabilities"]) >= 5

    def test_post_persona_interact_identity(self, client):
        resp = client.post("/persona/interact", json={"prompt": "Who are you?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["persona_name"] == "Shefali"
        assert data["handled_by"] == "persona_direct"
        assert "Shefali" in data["response_text"]

    def test_post_persona_interact_unauthorized(self, client):
        resp = client.post("/persona/interact", json={"prompt": "Open Notepad", "authorized": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["handled_by"] == "s8_intent"
        assert "authorization" in data["response_text"].lower()

    def test_post_intent_backward_compatibility(self, client):
        resp = client.post("/intent", json={"prompt": "Open Notepad", "authorized": False})
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert "authorization" in data["response"].lower()
