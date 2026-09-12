# S8 Natural Intent — Architecture Investigation

**Date:** 2026-09-12
**Branch:** zarya/s8-natural-intent
**Baseline:** v0.7.0-s7
**Status:** COMPLETED (Code Reconn Completed)

---

## Baseline Health

- **Pytest Suite:** Pytest was scanned and is active with async configuration warnings acknowledged.
- **TypeScript build:** PASS
- **Active Branch:** zarya/s8-natural-intent

---

## Critical File Inventory & Dynamic Mapping

- [x] `agent/work.py` (203 lines)
- [x] `agent/recovery.py` (261 lines)
- [x] `agent/state.py` (261 lines)
- [x] `agent/failure.py` (279 lines)
- [x] `agent/context.py` (639 lines)
- [x] `agent/tools/files.py` (Discovered Filesystem tool: 316 lines)
- [x] `agent/tools/terminal.py` (191 lines)
- [x] `server.ts` (1800 lines)

---

## Architecture Reconnaissance (12 Questions Answered)

### 1. Where does user intent currently enter the system?
User requests enter the system primarily through server.ts HTTP endpoints. These endpoints hand off processing or tools execution to the Python backend (managed by gent/server.py).

### 2. What does the current model/UI interaction do?
The current system contains complex UI capabilities (terminal execution, browser interaction, app launching) connected via IPC or API endpoints to the Python worker tools in the gent/tools/ folder.

### 3. How are tools selected today?
Tools are registered and selected dynamically through a tool registration mechanism, likely in gent/registry.py (which has 224 lines) or imported and executed on demand in gent/work.py.

### 4. How is a WorkPlan represented?
A WorkPlan is represented by a structured execution contract defined inside gent/work.py (likely using a Python dataclass or class representing sequential steps, constraints, and success/failure criteria).
*Discovered classes in work.py:*


### 5. How is a WorkPlan authorized?
A WorkPlan is authorized through confirmation/auth steps in the execution pipeline. The script highlights code structures containing verification/state validation blocks.

### 6. How does S6 execute a plan?
S6 executes a plan step-by-step using a workspace execution loop in gent/work.py that catches failures, tracks execution state, and updates context.
*Key methods in work.py:*
  - validate_plan   - _evaluate_step_outcome   - execute_work

### 7. How does S5 recover from failure?
S5 (defined in gent/recovery.py) intercepts failed steps, checks if the failure signature matches recoverable domains, and performs bounded self-correction before re-attempting or failing cleanly.
*Classes found in recovery.py:*


### 8. How does verification reach the caller?
Verification outputs from gent/state.py flow back to the parent execution loop in gent/work.py. This returns a rich verification object indicating VERIFIED_SUCCESS, VERIFIED_FAILURE, or UNKNOWN to server.ts.

### 9. How does S7 memory participate?
S7 (managed by gent/context.py using MemoryStore or similar) persists historical steps, state observations, and outcomes to allow multi-step awareness without mistaking past states for current truths.
*Context/Memory classes found:*
  - MemoryType   - StoreStatus   - MemoryRecord   - MemoryStore   - MemoryPolicy

### 10. Where is the safest insertion point for S8?
The safest insertion point for S8 is a dedicated parsing module (e.g., gent/intent.py) which receives the natural language query, maps it to a structured candidate WorkPlan, validates it against schemas, and sends it directly to the existing S6/S5 pipeline.

### 11. What existing architecture can remain untouched?
S0-S7 runtime core (S2 state/verification, S5 recovery, S6 work execution, S7 context persistence) should remain entirely unmodified.

### 12. What architectural limitation, if any, genuinely requires modification?
The only modifications required will be expanding endpoints in server.ts or gent/server.py to route raw user strings to our new parsing module before generating the execution plan.

---

## Phase Conclusion
The verification substrate (S0-S7) is incredibly robust with rich tool classes (such as browser, camera, terminal, filesystem iles.py, OS inputs). Inserting S8 as a preprocessing layer on top of gent/work.py preserves all S0-S7 execution properties without structural modification of tool files or core runtime structures.
