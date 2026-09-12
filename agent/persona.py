"""
Zarya Persona Layer — Shefali
Milestone S9 (v0.9.0-s9)

Architectural Boundary:
    User <-> Shefali Persona Layer <-> S8 Natural Intent <-> Zarya Trusted Runtime

Core Invariant:
    Zarya   = what the system is and what it does (computer-work runtime, S0-S8).
    Shefali = how that system presents itself and interacts (persistent persona / presence).

Persona != Runtime.
Persona changes expression, never truth.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import re

from agent.intent import process_natural_intent


@dataclass(frozen=True)
class PersonaDefinition:
    """Immutable contract defining Shefali's identity, role, and behavioral constraints."""
    name: str = "Shefali"
    role: str = "Personal computer interface persona for Zarya"
    version: str = "0.9.0"
    
    # Authoritative system identity description
    identity_summary: str = (
        "I am Shefali, the persona and interaction interface for Zarya — "
        "a verified computer-work system. I help you carry out authorized, "
        "verified tasks on your computer."
    )
    
    # Grounded capabilities derived strictly from Zarya runtime tools
    supported_capabilities: List[str] = field(default_factory=lambda: [
        "Open and verify desktop applications (e.g. Notepad, VS Code, Calculator)",
        "Create and write files with filesystem verification",
        "Read file contents safely",
        "Execute authorized terminal commands with output verification",
        "Retrieve historical computer context from verified memory",
    ])
    
    # Behavioral boundaries
    behavioral_rules: List[str] = field(default_factory=lambda: [
        "Never claim an action succeeded unless verified by Zarya runtime (VERIFIED_SUCCESS).",
        "Explicitly communicate uncertainty when runtime outcome is UNKNOWN.",
        "Never bypass or forge authorization.",
        "Never claim capabilities not supported by the underlying runtime.",
        "Treat historical memory as past observation, never as current verified truth.",
        "Maintain a concise, helpful, and transparent conversational tone.",
    ])


# Standard static persona instance
DEFAULT_SHEFALI_PERSONA = PersonaDefinition()


@dataclass
class PersonaInteractionResult:
    """Container for human-facing persona interaction output."""
    response_text: str
    persona_name: str = "Shefali"
    handled_by: str = "s8_intent"  # "persona_direct" or "s8_intent"
    status: str = "VERIFIED_SUCCESS"
    epistemic_certainty: str = "certain"  # "certain", "uncertain", "historical", "conversational"
    raw_intent_dict: Optional[Dict[str, Any]] = None
    suggested_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "persona_name": self.persona_name,
            "response_text": self.response_text,
            "handled_by": self.handled_by,
            "status": self.status,
            "epistemic_certainty": self.epistemic_certainty,
            "suggested_actions": self.suggested_actions,
            "raw_intent_dict": self.raw_intent_dict,
        }


class PersonaRenderer:
    """
    Renders S8 semantic intent outcomes into Shefali's persistent voice.
    
    Invariant: Changes presentation, NOT truth.
    - VERIFIED_SUCCESS -> Shefali confirms verified outcome.
    - VERIFIED_FAILURE -> Shefali honestly reports failure.
    - UNKNOWN -> Shefali explicitly reports uncertainty.
    - REFUSED -> Shefali explains safety refusal.
    - UNAUTHORIZED / INCOMPLETE (auth required) -> Shefali explains authorization requirement.
    - NEEDS_CLARIFICATION / CLARIFICATION_REQUIRED -> Shefali asks clarifying question.
    """

    def __init__(self, definition: PersonaDefinition = DEFAULT_SHEFALI_PERSONA):
        self.definition = definition

    def render_intent_dict(self, intent_dict: Dict[str, Any]) -> PersonaInteractionResult:
        """Render S8 process_natural_intent() dictionary result into Shefali persona response."""
        status = intent_dict.get("status", "UNKNOWN")
        base_text = intent_dict.get("response", "")

        is_auth_required = (
            status == "UNAUTHORIZED" or 
            "requires authorization" in base_text.lower() or
            "not authorized" in base_text.lower()
        )

        if is_auth_required:
            rendered = base_text
            certainty = "certain"
            actions = ["Grant authorization and retry"]

        elif status == "VERIFIED_SUCCESS":
            rendered = base_text
            certainty = "certain"
            actions = ["View system state", "What else can you do?"]

        elif status == "VERIFIED_FAILURE":
            rendered = base_text
            certainty = "certain"
            actions = ["Retry operation", "Check system logs"]

        elif status == "UNKNOWN":
            # Epistemic caution: never pretend success or guess
            rendered = base_text
            certainty = "uncertain"
            actions = ["Retry with diagnostic", "Check system manually"]

        elif status == "REFUSED":
            rendered = base_text
            certainty = "certain"
            actions = ["Review supported commands", "Ask for help"]

        elif status in ("NEEDS_CLARIFICATION", "CLARIFICATION_REQUIRED"):
            rendered = base_text
            certainty = "conversational"
            actions = ["Open Notepad", "Open VS Code"]

        else:
            rendered = base_text
            certainty = "conversational"
            actions = ["What can you do?"]

        return PersonaInteractionResult(
            response_text=rendered,
            persona_name=self.definition.name,
            handled_by="s8_intent",
            status=status,
            epistemic_certainty=certainty,
            raw_intent_dict=intent_dict,
            suggested_actions=actions,
        )


class ShefaliPersona:
    """
    Persistent Persona & Presence layer over Zarya.
    
    Responsibilities:
    1. Direct identity & capability conversations ("Who are you?", "What can you do?")
    2. Input framing & routing to S8 Intent Layer
    3. Output rendering via PersonaRenderer (truth-preserving)
    4. Guarding the boundary: Persona never executes tools directly, never bypasses authorization.
    """

    def __init__(self, definition: PersonaDefinition = DEFAULT_SHEFALI_PERSONA):
        self.definition = definition
        self.renderer = PersonaRenderer(definition)

    def describe(self) -> Dict[str, Any]:
        """Return full persona contract definition."""
        return {
            "name": self.definition.name,
            "role": self.definition.role,
            "version": self.definition.version,
            "identity_summary": self.definition.identity_summary,
            "capabilities": list(self.definition.supported_capabilities),
            "behavioral_rules": list(self.definition.behavioral_rules),
        }

    def _is_identity_query(self, text: str) -> bool:
        """Check if user is asking about Shefali's or Zarya's identity."""
        cleaned = text.strip().lower()
        patterns = [
            r"^(who|what) are you\b",
            r"^what('s| is) your name\b",
            r"^introduce yourself\b",
            r"^tell me about yourself\b",
            r"^who is shefali\b",
            r"^who is zarya\b",
        ]
        return any(re.search(p, cleaned) for p in patterns)

    def _is_capability_query(self, text: str) -> bool:
        """Check if user is asking about what Shefali/Zarya can do."""
        cleaned = text.strip().lower()
        patterns = [
            r"^(what|which) (can you|tools do you|capabilities do you|tasks can you)\b",
            r"^what can you do\b",
            r"^what are your capabilities\b",
            r"^help\b",
            r"^what do you support\b",
        ]
        return any(re.search(p, cleaned) for p in patterns)

    def _handle_identity_query(self, text: str) -> PersonaInteractionResult:
        """Generate authoritative identity response."""
        cleaned = text.strip().lower()
        if "who is zarya" in cleaned:
            resp_text = (
                "Zarya is the underlying verified computer-work runtime that executes and "
                "verifies operations on your system. I am Shefali, the conversational persona "
                "and interface through which you interact with Zarya."
            )
        else:
            resp_text = (
                f"I'm {self.definition.name} — the persona and human interface for Zarya, "
                f"a verified computer-work system. I help you carry out authorized desktop tasks "
                f"with guaranteed state verification."
            )
        return PersonaInteractionResult(
            response_text=resp_text,
            persona_name=self.definition.name,
            handled_by="persona_direct",
            status="CONVERSATIONAL",
            epistemic_certainty="conversational",
            suggested_actions=["What can you do?", "Open Notepad", "Create a file named notes.txt"],
        )

    def _handle_capability_query(self) -> PersonaInteractionResult:
        """Generate grounded capability response based on real runtime capabilities."""
        caps_list = "\n".join(f"• {c}" for c in self.definition.supported_capabilities)
        resp_text = (
            f"Here are the computer tasks I can currently perform through Zarya's verified runtime:\n\n"
            f"{caps_list}\n\n"
            f"Every operation is verified before I report completion, and dangerous actions require explicit authorization."
        )
        return PersonaInteractionResult(
            response_text=resp_text,
            persona_name=self.definition.name,
            handled_by="persona_direct",
            status="CONVERSATIONAL",
            epistemic_certainty="conversational",
            suggested_actions=["Open Notepad", "Open VS Code", "Create a file named test.txt"],
        )

    def interact(
        self,
        user_input: str,
        authorized: bool = False,
        context_memory: Optional[List[Dict[str, Any]]] = None,
    ) -> PersonaInteractionResult:
        """
        Main persona interaction pipeline:
        1. Handle direct conversational queries (identity, capabilities).
        2. Otherwise, route to S8 Intent Layer -> Zarya Runtime.
        3. Render result through PersonaRenderer (truth-preserving).
        """
        if not user_input or not user_input.strip():
            return PersonaInteractionResult(
                response_text="Hello! How can I help you today?",
                persona_name=self.definition.name,
                handled_by="persona_direct",
                status="CONVERSATIONAL",
                epistemic_certainty="conversational",
                suggested_actions=["Open Notepad", "What can you do?"],
            )

        stripped = user_input.strip()

        # 1. Direct persona identity queries
        if self._is_identity_query(stripped):
            return self._handle_identity_query(stripped)

        # 2. Direct capability queries
        if self._is_capability_query(stripped):
            return self._handle_capability_query()

        # 3. Route to S8 Intent Layer (trusted computer-work pipeline)
        intent_dict = process_natural_intent(
            user_input=stripped,
            authorized=authorized,
            context_memory=context_memory,
        )

        # 4. Render outcome with persona presentation
        return self.renderer.render_intent_dict(intent_dict)
