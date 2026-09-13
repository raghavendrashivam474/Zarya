# S10 Adaptive Work — Limitations & Operational Boundaries

**Milestone:** S10 (Adaptive Verified Work)
**Baseline:** `v0.9.0-s9`
**Status:** Implemented & Verified

---

## 1. Scope and Architectural Boundary

S10 introduces **bounded, evidence-grounded situational reassessment** when observed computer state diverges from the initial WorkPlan. It operates strictly within the verification and execution substrates established in S1–S9.

The engine answers one specific question:
> *"Given the goal, the verified state of previous steps, and the remaining plan, is there a safe, authorized candidate step that can continue work toward the goal?"*

---

## 2. Hard Bounds and Constraints

| Dimension | Bound / Limit | Enforcement Mechanism |
|---|---|---|
| Max adaptation rounds | `MAX_ADAPTATION_ROUNDS = 3` | Checked on every `reassess()` entry; triggers `DECISION_BLOCK` upon exceeding |
| Max candidate steps per round | `MAX_ADAPTED_STEPS_PER_ROUND = 2` | Policy generator constraint |
| Max cumulative steps | `MAX_STEPS = 16` | S6 hard ceiling checked in `execute_work` loop |
| Tool capability whitelist | `ALLOWED_ADAPTATION_TOOLS` | Rejection of unregistered or sensitive tools |
| In-flight recursion | 1 active assessment | Thread-local recursion guard (`_adaptive_state.active`) |

---

## 3. Epistemic Safety Rules

1. **Unknown State Never Adapted**:
   If a step verification yields `UNKNOWN`, state freshness is `REQUIRES_REFRESH` or `UNKNOWN`, or failure category is `INSUFFICIENT_EVIDENCE`, S10 unconditionally produces `DECISION_BLOCK`. S10 never speculates or adapts in the absence of verified truth.

2. **S5 Priority Rule**:
   If a step failure is eligible for S5 closed-loop recovery (e.g. `APPLICATION_NOT_OBSERVED -> RELAUNCH_APPLICATION`), S5 recovery takes precedence. S10 treats `RECOVERED` as normal success and continues the existing plan.

3. **Candidate Step Safety**:
   Candidate steps proposed during adaptation must pass `validate_candidate_step()`, which forbids:
   - Directory traversal (`..` in paths)
   - Executable / script creation (`.exe`, `.bat`, `.cmd`, `.ps1`, `.sh`, `.vbs`)
   - Dangerous system commands (`rm -rf`, `format`, `del /f`, `shutdown`)

4. **Historical Memory Rule (S7)**:
   Persisted observations retrieved from S7 context memory are treated as historical hints, never current ground truth. Current truth requires current S2/S3 verified observation.

---

## 4. Current Limitations

1. **Deterministic Rule Matrix**:
   In S10, candidate adaptations are governed by deterministic rule patterns (filesystem fallbacks, browser navigation adjustments). Generalized LLM candidate generation is reserved for subsequent phases behind identical validation gates.

2. **Non-Self-Modifying**:
   S10 adjusts the remaining execution queue of an active WorkPlan. It does not modify tool definitions, agent registry, or authorization policies.

3. **Local Queue Reshaping**:
   Adaptation prepends or substitutes candidate steps at the head of the remaining queue; it does not perform global graph-based replanning.

---

## 5. Non-Goals Restated

- ❌ Unrestricted autonomous computer control
- ❌ Unbounded retry loops
- ❌ Speculative tool execution on unverified states
- ❌ Modification of S1–S9 foundational contracts