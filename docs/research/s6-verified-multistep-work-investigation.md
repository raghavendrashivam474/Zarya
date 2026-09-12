# Zarya S6 — Verified Multi-Step Work Investigation

## 1. Architectural Decisions & Goal

S6 transitions Zarya from a single verified action with closed-loop recovery to a trustworthy orchestrator of a bounded sequence of actions. To maintain Zarya's high safety standards, S6 must not introduce unconstrained loop execution, speculation, or autonomous planning. Instead, it must follow the core invariant:

$$\text{ACTION} \neq \text{STEP SUCCESS}$$
$$\text{STEP SUCCESS} \neq \text{TASK SUCCESS}$$

### Key Design Decisions:
- **Layered Architecture:** S6 is implemented as an additive orchestration layer (`agent/work.py`). It wraps and composes existing S1–S5 components without changing their implementation.
- **Synchronous Execution:** The executor runs synchronously, executing steps sequentially. This simplifies control flow and ensures predictability.
- **Verification-First Flow:** Step-level success is evaluated directly from the tool's returning envelope. Verification or explicit permission (`unverified_ok`) is required for every step.

---

## 2. Boundedness & Safety Rules

To prevent infinite loops or runaway execution:
1. **Plan Size Limitation (`MAX_STEPS = 16`):** Plans with more than 16 steps are rejected during the validation phase.
2. **Deterministic Step Transitions:** S6 only executes forward. There is no backtracking, automatic retry, or generative path-finding.
3. **Recovery Limits:** S6 relies on S5's existing closed-loop recovery. A step may trigger exactly **one** recovery attempt (enforced inside S5). S6 does not retry steps that fail their S5 recovery.
4. **Execution Guarantees:** No step is executed after any prior step enters an unrecoverable failure state or an `UNKNOWN` state.

---

## 3. Schemas

### WorkPlan Input Schema
```json
{
  "goal": "Create a temporary file and open notepad",
  "steps": [
    {
      "id": "step-1",
      "tool": "createFile",
      "args": {
        "path": "C:\\Users\\ragha\\Documents\\test.txt",
        "content": "S6 Integration Test"
      },
      "unverified_ok": false
    },
    {
      "id": "step-2",
      "tool": "openApplication",
      "args": {
        "name": "notepad"
      },
      "unverified_ok": false
    }
  ]
}
WorkResult Output Schema
JSON

{
  "goal": "Create a temporary file and open notepad",
  "overall_status": "VERIFIED_SUCCESS | VERIFIED_FAILURE | UNKNOWN | INCOMPLETE",
  "summary": "Detailed textual summary of execution outcome.",
  "completed_steps": [
    {
      "step_id": "step-1",
      "tool": "createFile",
      "status": "VERIFIED_SUCCESS",
      "verification": { ... },
      "state": { ... },
      "failure": null,
      "recovery": { "status": "NOT_ELIGIBLE" }
    }
  ],
  "failed_step": null,
  "skipped_steps": []
}
4. Step Verification Semantics
For each step execution, the outcome status is mapped from the existing tool envelope:

VERIFIED_SUCCESS: The tool returns "verification": {"status": "VERIFIED_SUCCESS"}.
RECOVERED: The tool returns "verification": {"status": "VERIFIED_FAILURE"} but S5 executes and returns "recovery": {"status": "RECOVERED"}. Execution continues safely.
VERIFIED_FAILURE: The tool returns "verification": {"status": "VERIFIED_FAILURE"} and S5 returns "recovery": {"status": "FAILED" | "NOT_ELIGIBLE" | "NOT_ATTEMPTED"}. Execution terminates immediately.
UNKNOWN: The tool returns "verification": {"status": "UNKNOWN"} or lacks a "verification" payload when unverified_ok is false. Execution terminates immediately.
If a tool does not return a verification envelope (e.g., readFile), it is treated as UNKNOWN unless the plan creator explicitly sets "unverified_ok": true.

5. Overall Task Verification Semantics
Task success is evaluated strictly:

VERIFIED_SUCCESS: All planned steps are executed and resolve to either VERIFIED_SUCCESS or RECOVERED.
VERIFIED_FAILURE: Execution is halted because a step resolved to VERIFIED_FAILURE.
UNKNOWN: Execution is halted because a step resolved to UNKNOWN.
INCOMPLETE: The execution is aborted due to lack of authorization, validation failure, or execution-level exception.
6. S5 Integration
S6 does not duplicate failure reasoning or recovery logic. Instead, it captures S5's result payloads directly from the tool's returning dict. S5 acts as a step-level self-healing mechanism. S6 treats a successfully recovered step (RECOVERED) as a valid checkpoint, allowing the multi-step task to proceed.

7. Authorization Boundary
S6 enforces authorization at two levels:

Work Authorization: The orchestrator must be called with authorized=True. Unauthorized plans are rejected before any step runs.
Step Authorization: S6 does not bypass individual tool/S5 validation checks. If a step contains blacklisted terminal commands, the tool will throw a ToolError and halt execution.
8. Rollback Decision
Rollback is explicitly deferred. Computer actions (e.g., launching an app, starting a terminal process) are highly heterogeneous and do not support clean transactional rollbacks. Attempting automatic rollbacks would introduce speculative side effects.

Instead, S6 implements explicit partial completion preservation:

Successful steps are recorded in completed_steps.
The failed step is recorded in failed_step.
Unexecuted steps are recorded in skipped_steps.
This ensures the exact computer state is exposed to the caller, preventing silent state corruption.
