"""
S8: Natural Intent Parsing & Verification Boundary.
S12: Enhanced with Artifact Identity & Deterministic Context Continuity.

Converts free-form human language into bounded, validated, deterministic
S6 WorkPlans, ensuring that pronouns ("it", "that file") bind to active artifacts,
and ambiguous instructions request clarification without guessing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    from .work import execute_work
except ImportError:
    execute_work = None

from .artifacts import active_context, resolve_target, PRONOUN_REFERENCES, ResolutionStatus

log = logging.getLogger("zarya.intent")


@dataclass
class S8Step:
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    id: str = "step-1"
    unverified_ok: bool = False


@dataclass
class S8WorkPlan:
    intent: str
    goal: str
    steps: List[S8Step]
    status: str = "UNDERSTOOD"  # UNDERSTOOD, NEEDS_CLARIFICATION, REFUSED, INVALID
    clarification_message: Optional[str] = None

    def to_s6_plan(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "steps": [
                {
                    "id": step.id,
                    "tool": step.tool,
                    "args": step.args,
                    "description": step.description,
                    "unverified_ok": step.unverified_ok,
                }
                for step in self.steps
            ],
        }


class IntentInterpreter:
    """
    S8/S12 IntentInterpreter: Converts Natural Language into structured WorkPlans.
    Preserves and resolves active computer context and artifact identity.
    """

    def __init__(
        self,
        context_memory: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Any] = None,
    ):
        self.context_memory = context_memory or []
        self.context = context or active_context

    def interpret(self, user_input: str) -> S8WorkPlan:
        raw_text = user_input.strip()
        text_lower = raw_text.lower()

        # 1. Guard against empty requests
        if not raw_text:
            return S8WorkPlan(
                intent="",
                goal="",
                steps=[],
                status="INVALID",
                clarification_message="No instruction was received. Please provide a clear command.",
            )

        # 2. Hard boundary: Refuse dangerous / destructive intents
        if any(w in text_lower for w in ["delete entire", "wipe drive", "destruct", "kill terminal", "rm -rf /"]):
            return S8WorkPlan(
                intent=user_input,
                goal="Unsafe execution prevented",
                steps=[],
                status="REFUSED",
                clarification_message="I cannot perform that operation as it violates safety constraints.",
            )

        # 3. Ambiguities requiring clarification
        if text_lower in ["open the editor", "open editor", "launch editor"]:
            return S8WorkPlan(
                intent=user_input,
                goal="Open editor application",
                steps=[],
                status="NEEDS_CLARIFICATION",
                clarification_message="Which editor would you like me to open? VS Code or Notepad?",
            )

        if text_lower in ["do something", "make something", "run a command", "open something useful"]:
            return S8WorkPlan(
                intent=user_input,
                goal="Unknown task",
                steps=[],
                status="NEEDS_CLARIFICATION",
                clarification_message="I need more information before I can safely perform that. What specific task or application did you have in mind?",
            )

                # -------------------------------------------------------------------
        # -------------------------------------------------------------------
        # S14 Pattern: Active Browser Context Queries
        # -------------------------------------------------------------------
        if re.search(r"(?:what\s+(?:webpage|website|page|browser\s+tab|tab|url)\s+(?:am\s+i\s+(?:currently\s+)?(?:on|viewing|looking\s+at)|is\s+(?:currently\s+)?(?:open|active|focused))|(?:the\s+)?current\s+(?:webpage|website|page|browser\s+context|tab|url)|what\s+page\s+am\s+i\s+(?:currently\s+)?on)", text_lower):
            return S8WorkPlan(
                intent=user_input,
                goal="Observe active browser context",
                steps=[
                    S8Step(
                        id="step-1",
                        tool="getActiveContext",
                        args={},
                        description="Observe active computer and browser context snapshot",
                    )
                ],
                status="UNDERSTOOD",
            )

        # S13 Pattern: Active Desktop Context Queries
        # -------------------------------------------------------------------
        if re.search(r"^(?:what(?:'s|\s+is)?\s+(?:the\s+)?(?:active|current|focused)\s+window|get\s+active\s+window|check\s+active\s+window)", text_lower):
            return S8WorkPlan(
                intent=user_input,
                goal="Observe active desktop window",
                steps=[
                    S8Step(
                        id="step-1",
                        tool="getActiveWindow",
                        args={},
                        description="Observe active foreground window and application",
                    )
                ],
                status="UNDERSTOOD",
            )

        if re.search(r"^(?:what(?:'s|\s+is)?\s+(?:the\s+)?(?:active|current)\s+context|what\s+app(?:\s+am\s+i|\s+is)\s+using|what\s+am\s+i\s+working\s+on|get\s+active\s+context|check\s+active\s+context)", text_lower):
            return S8WorkPlan(
                intent=user_input,
                goal="Observe active computer context",
                steps=[
                    S8Step(
                        id="step-1",
                        tool="getActiveContext",
                        args={},
                        description="Observe full active computer context snapshot",
                    )
                ],
                status="UNDERSTOOD",
            )

# -------------------------------------------------------------------
        # S12 Pattern 0: Compound CREATE -> OPEN workflow
        # e.g., "Create notes.txt with 'Hello' and open it in Notepad"
        # -------------------------------------------------------------------
        compound_match = re.search(
            r"create(?:\s+a)?\s+file\s+called\s+([^\s'\"]+)(?:\s+in\s+([^\s'\"]+))?(?:\s+with\s+['\"](.*?)['\"])?\s+and\s+open\s+(?:it|that|the file)\s+in\s+(notepad|vs\s*code|vscode|code)",
            raw_text,
            re.IGNORECASE,
        )
        if compound_match:
            filename = compound_match.group(1).strip()
            folder = compound_match.group(2).strip() if compound_match.group(2) else ""
            content = compound_match.group(3) or ""
            app_raw = compound_match.group(4).lower()
            app_name = "vscode" if "code" in app_raw else "notepad"
            target_path = f"{folder.rstrip('/')}/{filename}" if folder else filename

            return S8WorkPlan(
                intent=user_input,
                goal=f"Create {target_path} and open in {app_name.capitalize()}",
                steps=[
                    S8Step(
                        id="step-1",
                        tool="createFile",
                        args={"path": target_path, "content": content},
                        description=f"Create file {target_path}",
                    ),
                    S8Step(
                        id="step-2",
                        tool="openApplication",
                        args={"application": app_name, "target": "$ACTIVE_ARTIFACT"},
                        description=f"Open active file in {app_name.capitalize()}",
                    ),
                ],
                status="UNDERSTOOD",
            )

        # -------------------------------------------------------------------
        # S12 Pattern A: Open target in application / Open Application with target
        # e.g., "Open it in Notepad", "Open notes.txt in VS Code", "Open that file in Notepad"
        # -------------------------------------------------------------------
        open_in_match = re.search(
            r"open\s+(.+?)\s+in\s+(notepad|vs\s*code|vscode|code|chrome|edge|browser)",
            raw_text,
            re.IGNORECASE,
        )
        if open_in_match:
            target_ref = open_in_match.group(1).strip()
            app_raw = open_in_match.group(2).lower()
            app_name = "vscode" if "code" in app_raw else ("browser" if "browser" in app_raw or "chrome" in app_raw else "notepad")

            target_res = self.context.resolve_target(target_ref)
            if target_res.status == ResolutionStatus.AMBIGUOUS:
                return S8WorkPlan(
                    intent=user_input,
                    goal=f"Open {target_ref} in {app_name.capitalize()}",
                    steps=[],
                    status="NEEDS_CLARIFICATION",
                    clarification_message=f"Multiple files match '{target_ref}'. Which one do you mean?",
                )
            elif target_res.status == ResolutionStatus.NOT_FOUND and target_ref.lower() in PRONOUN_REFERENCES:
                return S8WorkPlan(
                    intent=user_input,
                    goal="Open target in application",
                    steps=[],
                    status="NEEDS_CLARIFICATION",
                    clarification_message="You referred to 'it', but no active file or artifact is currently established. What file would you like me to open?",
                )

            target_locator = target_res.canonical_locator if target_res.is_resolved else target_ref

            return S8WorkPlan(
                intent=user_input,
                goal=f"Open {target_locator} in {app_name.capitalize()}",
                steps=[
                    S8Step(
                        id="step-1",
                        tool="openApplication",
                        args={"application": app_name, "target": target_locator},
                        description=f"Launch {app_name} with target {target_locator}",
                    )
                ],
                status="UNDERSTOOD",
            )

        # -------------------------------------------------------------------
        # S8/S12 Pattern B: Open Application (plain)
        # -------------------------------------------------------------------
        app_match = re.search(r"open\s+(notepad|vs\s*code|vscode|browser|calculator|chrome|edge|paint|wordpad)", raw_text, re.IGNORECASE)
        if app_match:
            app_raw = app_match.group(1).lower()
            app_name = "notepad"
            if "code" in app_raw:
                app_name = "vscode"
            elif "browser" in app_raw or "chrome" in app_raw:
                app_name = "browser"
            elif "calculator" in app_raw:
                app_name = "calculator"

            return S8WorkPlan(
                intent=user_input,
                goal=f"Open {app_name.capitalize()}",
                steps=[
                    S8Step(
                        id="step-1",
                        tool="openApplication",
                        args={"application": app_name},
                        description=f"Launch application {app_name}",
                    )
                ],
                status="UNDERSTOOD",
            )

        # -------------------------------------------------------------------
        # S8/S12 Pattern C: Create File with content
        # e.g. "Create a file called notes.txt in Documents with 'Hello Zarya'"
        # -------------------------------------------------------------------
        file_match = re.search(
            r"create(?:\s+a)?\s+file\s+called\s+([^\s'\"]+)(?:\s+in\s+([^\s'\"]+))?(?:\s+with\s+['\"](.*?)['\"])?",
            raw_text,
            re.IGNORECASE,
        )
        if file_match:
            filename = file_match.group(1).strip()
            folder = file_match.group(2).strip() if file_match.group(2) else ""
            content = file_match.group(3) if file_match.group(3) is not None else ""
            target_path = f"{folder.rstrip('/')}/{filename}" if folder else filename

            return S8WorkPlan(
                intent=user_input,
                goal=f"Create file {target_path}",
                steps=[
                    S8Step(
                        id="step-1",
                        tool="createFile",
                        args={"path": target_path, "content": content},
                        description=f"Create file {target_path} with specified content",
                    )
                ],
                status="UNDERSTOOD",
            )

        # -------------------------------------------------------------------
        # S8/S12 Pattern D: Read File / "Read it" / "Read that file"
        # -------------------------------------------------------------------
        read_match = re.search(r"read(?:\s+the)?\s+(?:file\s+called\s+)?([^\s'\"]+|it|that\s+file|this\s+file|same\s+file)", raw_text, re.IGNORECASE)
        if read_match:
            raw_target = read_match.group(1).strip().strip("'\"")
            if raw_target.lower() in PRONOUN_REFERENCES:
                target_res = self.context.resolve_target(raw_target)
                if not target_res.is_resolved:
                    return S8WorkPlan(
                        intent=user_input,
                        goal="Read file",
                        steps=[],
                        status="NEEDS_CLARIFICATION",
                        clarification_message="You asked to read 'it', but no active file is currently established.",
                    )
                target_path = target_res.canonical_locator
            else:
                target_path = raw_target

            return S8WorkPlan(
                intent=user_input,
                goal=f"Read file {target_path}",
                steps=[
                    S8Step(
                        id="step-1",
                        tool="readFile",
                        args={"path": target_path},
                        description=f"Read contents of file {target_path}",
                    )
                ],
                status="UNDERSTOOD",
            )

        # -------------------------------------------------------------------
        # S12 Pattern E: Append / Edit / Write to same file
        # e.g., "Add 'This is a test' to it", "Append 'world' to that file"
        # -------------------------------------------------------------------
        add_match = re.search(
            r"(?:add|append|write)\s+['\"](.*?)['\"]\s+(?:in|to|into)\s+(it|that\s+file|this\s+file|same\s+file|[^\s'\"]+)",
            raw_text,
            re.IGNORECASE | re.DOTALL,
        )
        if add_match:
            new_text = add_match.group(1)
            target_ref = add_match.group(2).strip()
            target_res = self.context.resolve_target(target_ref)
            if not target_res.is_resolved:
                return S8WorkPlan(
                    intent=user_input,
                    goal=f"Append to {target_ref}",
                    steps=[],
                    status="NEEDS_CLARIFICATION",
                    clarification_message=f"Cannot determine target file for '{target_ref}'. Please specify the exact file.",
                )

            target_path = target_res.canonical_locator
            return S8WorkPlan(
                intent=user_input,
                goal=f"Append text to {target_path}",
                steps=[
                    S8Step(
                        id="step-1",
                        tool="createFile",
                        args={"path": target_path, "content": new_text, "overwrite": True},
                        description=f"Write updated content to {target_path}",
                    )
                ],
                status="UNDERSTOOD",
            )

        # -------------------------------------------------------------------
        # S8 Pattern F: Run Terminal Command
        # -------------------------------------------------------------------
        terminal_match = re.search(r"run\s+terminal\s+command\s+['\"](.*)['\"]", raw_text, re.IGNORECASE)
        if terminal_match:
            cmd_text = terminal_match.group(1)
            return S8WorkPlan(
                intent=user_input,
                goal=f"Run command: {cmd_text}",
                steps=[
                    S8Step(
                        id="step-1",
                        tool="runTerminalCommand",
                        args={"command": cmd_text},
                        description=f"Execute terminal command: {cmd_text}",
                    )
                ],
                status="UNDERSTOOD",
            )

        # -------------------------------------------------------------------
        # S8 Pattern G: Conversational Continuity / Memory lookup
        # -------------------------------------------------------------------
        if "again" in text_lower or "do the same" in text_lower:
            for memory in reversed(self.context_memory):
                if memory.get("last_goal") and memory.get("last_steps"):
                    return S8WorkPlan(
                        intent=user_input,
                        goal=f"Repeat: {memory['last_goal']}",
                        steps=[
                            S8Step(
                                id=f"step-{idx+1}",
                                tool=step.get("tool", ""),
                                args=step.get("args", {}),
                                description=step.get("description", ""),
                            )
                            for idx, step in enumerate(memory["last_steps"])
                        ],
                        status="UNDERSTOOD",
                    )
            return S8WorkPlan(
                intent=user_input,
                goal="Context resolution failed",
                steps=[],
                status="NEEDS_CLARIFICATION",
                clarification_message="You asked me to repeat an action, but I don't have a record of what to repeat. What would you like me to do?",
            )

        # Fallback to clarification
        return S8WorkPlan(
            intent=user_input,
            goal="Ambiguous intent parsing fallback",
            steps=[],
            status="NEEDS_CLARIFICATION",
            clarification_message=f"I understood your request: '{user_input}', but could not safely map it to a registered capability. Could you clarify your command?",
        )


class PlanValidator:
    """
    S8 PlanValidator: Validates that candidate plans conform to safety boundaries
    and registered tools before reaching authorization or S6 execution.
    """

    DEFAULT_ALLOWED_TOOLS = [
        "openApplication",
        "closeApplication",
        "createFile",
        "readFile",
        "deleteFile",
        "renameFile",
        "moveFile",
        "runTerminalCommand",
        "takeScreenshot",
        "systemInfo",
        "getActiveWindow",
        "getActiveContext",
    ]

    @staticmethod
    def validate(plan: S8WorkPlan, allowed_tools: Optional[List[str]] = None) -> Tuple[bool, str]:
        if plan.status != "UNDERSTOOD":
            return False, f"Plan status is {plan.status}."

        if not plan.steps:
            return False, "Plan contains no steps to execute."

        if len(plan.steps) > 5:
            return False, "Plan exceeds maximum bounded step count (limit 5)."

        tools_whitelist = allowed_tools or PlanValidator.DEFAULT_ALLOWED_TOOLS
        for idx, step in enumerate(plan.steps):
            if step.tool not in tools_whitelist:
                return False, f"Step {idx+1} requested unregistered/disallowed tool: '{step.tool}'."

            if step.tool in ["createFile", "readFile", "deleteFile", "renameFile", "moveFile"]:
                path = step.args.get("path", "")
                if not path:
                    return False, f"Step {idx+1} missing required 'path' argument."
                if ".." in path or path.endswith((".exe", ".bat", ".vbs", ".cmd")):
                    return False, f"Step {idx+1} contains unsafe path or executable extension: '{path}'."

        return True, "Plan valid."


class ResponseTranslator:
    """
    S8 ResponseTranslator: Translates S6 WorkResult outcomes into truthful,
    natural-language responses. Enforces strict containment: never hallucinating
    success when verification is UNKNOWN or INCOMPLETE.
    """

    @staticmethod
    def translate(work_result: Dict[str, Any], raw_intent: str = "") -> str:
        status = work_result.get("overall_status", "")
        summary = work_result.get("summary", "")
        goal = work_result.get("goal", raw_intent)

        # Check authorization failure
        if "Unauthorized" in summary or (status == "INCOMPLETE" and "authorized" in summary.lower()):
            return f"Action requires authorization before it can proceed: '{goal}'."

        if status == "VERIFIED_SUCCESS":
            return f"Done — '{goal}' completed and verified successfully."

        elif status == "VERIFIED_FAILURE":
            return f"I couldn't complete '{goal}'. The operation was attempted, but runtime verification confirmed a failure ({summary})."

        elif status == "UNKNOWN":
            return f"I attempted to perform '{goal}', but I could not verify the outcome with certainty ({summary})."

        elif status == "INCOMPLETE":
            return f"Work halted before completion for '{goal}': {summary}."

        elif status == "NEEDS_CLARIFICATION":
            return summary or "I need additional details to proceed safely."

        elif status == "REFUSED":
            return summary or "I cannot perform this operation under current safety rules."

        else:
            return f"Operation outcome for '{goal}': {summary or status}."


def process_natural_intent(
    user_input: str,
    authorized: bool = False,
    context_memory: Optional[List[Dict[str, Any]]] = None,
    context: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Full S8/S12 Natural Intent Pipeline:
    Natural Language -> IntentInterpreter -> Candidate Plan -> PlanValidator ->
    Authorization Check -> S6 execute_work -> ResponseTranslator -> Output Dict.
    """
    interpreter = IntentInterpreter(context_memory=context_memory, context=context)
    candidate_plan = interpreter.interpret(user_input)

    # Early-exit on non-understood states (Clarification / Refusal / Invalid)
    if candidate_plan.status in ["NEEDS_CLARIFICATION", "REFUSED", "INVALID"]:
        return {
            "status": candidate_plan.status,
            "response": candidate_plan.clarification_message,
            "goal": candidate_plan.goal,
            "work_result": None,
            "plan": candidate_plan.to_s6_plan(),
        }

    is_valid, reason = PlanValidator.validate(candidate_plan)
    if not is_valid:
        return {
            "status": "INVALID",
            "response": f"Plan validation rejected the proposed actions: {reason}",
            "goal": candidate_plan.goal,
            "work_result": None,
            "plan": candidate_plan.to_s6_plan(),
        }

    s6_plan_dict = candidate_plan.to_s6_plan()

    if execute_work is None:
        return {
            "status": "ERROR",
            "response": "S6 execute_work runtime substrate is not available.",
            "goal": candidate_plan.goal,
            "work_result": None,
            "plan": s6_plan_dict,
        }

    work_result = execute_work(s6_plan_dict, authorized=authorized)

    natural_response = ResponseTranslator.translate(work_result, raw_intent=candidate_plan.goal)

    return {
        "status": work_result.get("overall_status", "UNKNOWN"),
        "response": natural_response,
        "goal": candidate_plan.goal,
        "work_result": work_result,
        "plan": s6_plan_dict,
    }


__all__ = [
    "S8Step",
    "S8WorkPlan",
    "IntentInterpreter",
    "PlanValidator",
    "ResponseTranslator",
    "process_natural_intent",
]

