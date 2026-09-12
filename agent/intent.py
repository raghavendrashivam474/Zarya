import json
import re
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict

# Import S6 Work Executor contracts
try:
    from agent.work import execute_work, validate_plan
except ImportError:
    execute_work = None
    validate_plan = None

logger = logging.getLogger("zarya.intent")

@dataclass
class S8Step:
    tool: str
    args: Dict[str, Any]
    description: str
    id: Optional[str] = None

@dataclass
class S8WorkPlan:
    intent: str
    goal: str
    steps: List[S8Step]
    status: str  # UNDERSTOOD, NEEDS_CLARIFICATION, REFUSED, INVALID
    clarification_message: Optional[str] = None

    def to_s6_plan(self) -> Dict[str, Any]:
        """Convert S8 representation to standard S6 WorkPlan dictionary format."""
        return {
            "intent": self.intent,
            "goal": self.goal,
            "steps": [
                {
                    "id": s.id if s.id else f"step-{idx + 1}",
                    "tool": s.tool,
                    "args": s.args,
                    "description": s.description
                }
                for idx, s in enumerate(self.steps)
            ]
        }

class IntentInterpreter:
    """
    S8 IntentInterpreter: Converts Natural Language into structured WorkPlans.
    Uses exact registered tool signatures: 'openApplication', 'createFile', etc.
    """
    def __init__(self, context_memory: Optional[List[Dict[str, Any]]] = None):
        self.context_memory = context_memory or []

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
                clarification_message="No instruction was received. Please provide a clear command."
            )
            
        # 2. Hard boundary: Refuse dangerous / destructive intents
        if any(w in text_lower for w in ["delete entire", "wipe drive", "destruct", "kill terminal", "rm -rf /"]):
            return S8WorkPlan(
                intent=user_input,
                goal="Unsafe execution prevented",
                steps=[],
                status="REFUSED",
                clarification_message="I cannot perform that operation as it violates safety constraints."
            )

        # 3. Ambiguities requiring clarification
        if text_lower in ["open the editor", "open editor", "launch editor"]:
            return S8WorkPlan(
                intent=user_input,
                goal="Open editor application",
                steps=[],
                status="NEEDS_CLARIFICATION",
                clarification_message="Which editor would you like me to open? VS Code or Notepad?"
            )
            
        if text_lower in ["do something", "make something", "run a command", "open something useful"]:
            return S8WorkPlan(
                intent=user_input,
                goal="Unknown task",
                steps=[],
                status="NEEDS_CLARIFICATION",
                clarification_message="I need more information before I can safely perform that. What specific task or application did you have in mind?"
            )

        # 4. Deterministic Tool Translation
        
        # Pattern A: Open Application
        app_match = re.search(r"open\s+(notepad|vs\s*code|vscode|browser|calculator|chrome)", raw_text, re.IGNORECASE)
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
                        description=f"Launch application {app_name}"
                    )
                ],
                status="UNDERSTOOD"
            )

        # Pattern B: Create File with content
        file_match = re.search(
            r"create(?:\s+a)?\s+file\s+called\s+([\w\.\-]+)(?:\s+with\s+['\"](.*)['\"])?", 
            raw_text,
            re.IGNORECASE
        )
        if file_match:
            filename = file_match.group(1)
            content = file_match.group(2) if file_match.group(2) is not None else ""
            
            return S8WorkPlan(
                intent=user_input,
                goal=f"Create file {filename}",
                steps=[
                    S8Step(
                        id="step-1",
                        tool="createFile",
                        args={"path": filename, "content": content},
                        description=f"Create file {filename} with specified content"
                    )
                ],
                status="UNDERSTOOD"
            )

        # Pattern C: Read File
        read_match = re.search(r"read(?:\s+the)?\s+file\s+called\s+([\w\.\-]+)", raw_text, re.IGNORECASE)
        if read_match:
            filename = read_match.group(1)
            return S8WorkPlan(
                intent=user_input,
                goal=f"Read file {filename}",
                steps=[
                    S8Step(
                        id="step-1",
                        tool="readFile",
                        args={"path": filename},
                        description=f"Read contents of file {filename}"
                    )
                ],
                status="UNDERSTOOD"
            )

        # Pattern D: Run Terminal Command
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
                        description=f"Execute terminal command: {cmd_text}"
                    )
                ],
                status="UNDERSTOOD"
            )

        # Pattern E: Conversational Continuity / Memory lookup
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
                                description=step.get("description", "")
                            )
                            for idx, step in enumerate(memory["last_steps"])
                        ],
                        status="UNDERSTOOD"
                    )
            return S8WorkPlan(
                intent=user_input,
                goal="Context resolution failed",
                steps=[],
                status="NEEDS_CLARIFICATION",
                clarification_message="You asked me to repeat an action, but I don't have a record of what to repeat. What would you like me to do?"
            )

        # Fallback to clarification
        return S8WorkPlan(
            intent=user_input,
            goal="Ambiguous intent parsing fallback",
            steps=[],
            status="NEEDS_CLARIFICATION",
            clarification_message=f"I understood your request: '{user_input}', but could not safely map it to a registered capability. Could you clarify your command?"
        )

class PlanValidator:
    """
    S8 PlanValidator: Validates that candidate plans conform to safety boundaries
    and registered tools before reaching authorization or S6 execution.
    """
    DEFAULT_ALLOWED_TOOLS = [
        "openApplication", "closeApplication", "createFile", "readFile",
        "deleteFile", "runTerminalCommand", "takeScreenshot", "systemInfo"
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
                
            # Path traversal / script security check
            if step.tool in ["createFile", "readFile", "deleteFile"]:
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
        if "Unauthorized" in summary or status == "INCOMPLETE" and "authorized" in summary.lower():
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
    context_memory: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Full S8 Natural Intent Pipeline:
    Natural Language -> IntentInterpreter -> Candidate Plan -> PlanValidator ->
    Authorization Check -> S6 execute_work -> ResponseTranslator -> Output Dict.
    """
    # 1. Natural Language Interpretation
    interpreter = IntentInterpreter(context_memory=context_memory)
    candidate_plan = interpreter.interpret(user_input)
    
    # 2. Early-exit on non-understood states (Clarification / Refusal / Invalid)
    if candidate_plan.status in ["NEEDS_CLARIFICATION", "REFUSED", "INVALID"]:
        return {
            "status": candidate_plan.status,
            "response": candidate_plan.clarification_message,
            "goal": candidate_plan.goal,
            "work_result": None,
            "plan": candidate_plan.to_s6_plan()
        }
        
    # 3. Plan Validation
    is_valid, reason = PlanValidator.validate(candidate_plan)
    if not is_valid:
        return {
            "status": "INVALID",
            "response": f"Plan validation rejected the proposed actions: {reason}",
            "goal": candidate_plan.goal,
            "work_result": None,
            "plan": candidate_plan.to_s6_plan()
        }
        
    # 4. Prepare S6 WorkPlan Dict
    s6_plan_dict = candidate_plan.to_s6_plan()
    
    # 5. Hand off to S6 Work Executor
    if execute_work is None:
        return {
            "status": "ERROR",
            "response": "S6 execute_work runtime substrate is not available.",
            "goal": candidate_plan.goal,
            "work_result": None,
            "plan": s6_plan_dict
        }
        
    work_result = execute_work(s6_plan_dict, authorized=authorized)
    
    # 6. Response Translation (Truthful, non-hallucinated natural output)
    natural_response = ResponseTranslator.translate(work_result, raw_intent=candidate_plan.goal)
    
    return {
        "status": work_result.get("overall_status", "UNKNOWN"),
        "response": natural_response,
        "goal": candidate_plan.goal,
        "work_result": work_result,
        "plan": s6_plan_dict
    }
