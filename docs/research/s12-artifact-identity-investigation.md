# S12 Research: Artifact Identity & Computer Context Continuity Investigation

**Milestone:** S12  
**Baseline:** v0.11.0 (`2f89975`)  
**Status:** In Progress / Designed  

---

## 1. Executive Summary

During real-world dogfooding and multi-step interactions, Zarya exhibited target-continuity degradation: operations executed individually in isolation, but the concrete identity of computer artifacts (such as files created or inspected in step $N$) was not preserved into step $N+1$ or across subsequent natural-language instructions referring to "it", "that file", or "the document".

This investigation establishes the root causes, boundaries, and minimal architectural design for **Artifact Identity** and **Computer Context Continuity** in S12.

---

## 2. Root Cause Analysis: Where Target Knowledge Disappears

Tracing the baseline codebase revealed three distinct points of loss:

1. **Tool Invocation Argument Freezing (`agent/work.py`)**:
   - In `execute_work()`, step arguments (`args = step.get("args") or {}`) were extracted directly and immutably from the static `WorkPlan`.
   - Tool execution returns responses (containing canonical file paths in `files.py`), but these results were merely appended to `completed_steps` for reporting and never fed forward as dynamic target context for subsequent steps in the same plan.

2. **Application Launcher Target Disconnect (`agent/tools/applications.py` & `agent/backends/`)**:
   - `open_application` only accepted `name`/`application` parameters.
   - `ApplicationLauncher.launch(spec)` did not accept target file paths, preventing an application like Notepad or VS Code from being launched directly with a canonical artifact path.

3. **Stateless Intent Interpretation (`agent/intent.py`)**:
   - `IntentInterpreter.interpret()` only received historical `context_memory` (S7 historical records), lacking a live `ActiveComputerContext`.
   - Pronouns ("it", "that file", "the file we created") had no deterministic target resolver and either fell back to `NEEDS_CLARIFICATION` or failed to bind to the active artifact.

---

## 3. Boundary Definitions: Identity vs State vs Historical Memory

To avoid architectural corruption, S12 strictly separates three distinct concepts:

| Dimension | System Owner | Core Question | Example |
| :--- | :--- | :--- | :--- |
| **Artifact Identity** | **S12 (`artifacts.py`)** | *Which concrete object are we talking about?* | `C:\Users\user\Documents\notes.txt` |
| **Computer State** | **S3 (`state.py`)** | *What is currently observed about that object?* | `CURRENT`, `STALE`, size, hash |
| **Historical Memory**| **S7 (`context.py`)** | *What happened in previous sessions/work?* | SQLite persistent records |
| **Verification** | **S2 (`verification`)** | *Did the attempted operation truly succeed?* | `VERIFIED_SUCCESS`, `VERIFIED_FAILURE` |
| **Work Execution** | **S6 (`work.py`)** | *How does a multi-step bounded plan execute?* | `execute_work`, step dispatch |
| **Intent Translation** | **S8 (`intent.py`)** | *How does natural language map to a plan?* | `process_natural_intent` |

### Critical Invariants
- **Identity $\neq$ State**: An artifact identity may remain known even if its live state requires refresh or is unknown.
- **Action $\neq$ Outcome**: An attempted operation (e.g. `createFile`) does **not** create a verified active artifact unless the verification status is `VERIFIED_SUCCESS`.
- **Never Guess**: If natural language refers to an ambiguous target and no active artifact is uniquely bound, Zarya must clarify rather than guessing.

---

## 4. Minimal Architectural Model

### 4.1 ArtifactIdentity Structure
```python
@dataclass
class ArtifactIdentity:
    artifact_id: str             # e.g. "artifact:file:c_users_..._notes_txt"
    artifact_type: str           # "file", "folder", "application"
    canonical_locator: str       # Normalized absolute path or unique identifier
    display_name: str           # "notes.txt"
    source_operation: str       # "createFile", "readFile", etc.
    created_at: str             # ISO timestamp
    last_verified_at: Optional[str]
    verification_status: str     # VERIFIED_SUCCESS, etc.
    metadata: Dict[str, Any]
```

### 4.2 ActiveComputerContext Structure
```Python
class ActiveComputerContext:
    active_artifact: Optional[ArtifactIdentity]
    last_created_artifact: Optional[ArtifactIdentity]
    last_verified_artifact: Optional[ArtifactIdentity]
    active_application: Optional[str]
    artifacts: Dict[str, ArtifactIdentity]
```

### 4.3 Target Resolution Hierarchy

When resolving a reference R (e.g. "it", "notes.txt", "$ACTIVE_ARTIFACT"):

1. **Explicit Target in Instruction**: Specific canonical path provided.
2. **Explicit Artifact ID**: Matches a known tracked artifact.
3. **Pronominal Reference ("it", "that file", "the document", "same file")**:
     - Resolves to active_artifact if present and verified.
     -  If no active artifact exists, returns AMBIGUOUS / NOT_FOUND → Clarification requested.
4. **Name match in tracked artifacts**: Unique match in session artifacts.
5. **No Guessing**: Never silently fall back to scanning the entire disk to manufacture certainty.

## 5. Security & Safety Analysis

Canonical locator resolution strictly maintains path traversal protections (.. normalization) and existing SAFE_ROOTS enforcement.
Artifact identity tracking does not confer authorization; S6/S8 authorization boundaries remain strictly enforced before any tool execution.
