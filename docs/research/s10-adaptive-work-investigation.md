# S10 Adaptive Work — Architecture Investigation

**Branch:** `feat/s10-adaptive-work`
**Baseline:** `main @ 7917a5a` (post `v0.9.0-s9`)
**Status:** Investigation only. No production code changed.
**Regression floor:** 171 tests passing across S0–S9.

---

## 1. Purpose

This document maps the existing S0–S9 substrate against the S10 brief and
identifies the smallest, safest seam for introducing bounded adaptive work.
No implementation begins until this map, its limitations, and its
non-goals are explicit.

---

## 2. What already exists

### 2.1 Substrate summary

| Layer | Module | Responsibility | Bounded by |
|-------|--------|----------------|------------|
| S1/S2 | `agent/tools/*` + verification payloads | Verified observation of side effects | Per-tool probe timeouts |
| S3    | `agent/state.py` | Shared observation schema + freshness + in-memory cache | 30s CURRENT / 90s STALE thresholds |
| S4    | `agent/failure.py` | Structured failure explanations | Confidence capped by freshness |
| S5    | `agent/recovery.py` | Single bounded recovery attempt per verified failure | Policy matrix (currently: 1 category), `max_attempts=1`, recursion guard |
| S6    | `agent/work.py` | Sequential validated plan execution | `MAX_STEPS=16`, halt-on-first-failure |
| S7    | `agent/context.py` | Persistent historical memory (SQLite) | `MAX_RECALL_LIMIT=500`, epistemic markers |
| S8    | `agent/intent.py` | NL → validated candidate plan | `PlanValidator` step cap = 5, tool whitelist, path safety |
| S9    | `agent/persona.py` + `ResponseTranslator` | Truth-preserving user-facing rendering | No autonomous action |

### 2.2 The exact seam where S10 must live

`agent/work.py::execute_work()` currently halts unconditionally when a step
does not return `STEP_SUCCESS` or `STEP_RECOVERED`:

 Halt immediately if step did not succeed or recover successfully
if step_status not in (STEP_SUCCESS, STEP_RECOVERED):
...
failed_step_info = recorded_step
break

This is the single insertion point for S10. Everything upstream
(intent, validation, authorization) and downstream (context capture,
response translation) can remain untouched.

### 2.3 Confirmed regression floor

Full suite: **171 passed in 12.32s** on Python 3.13.14 / pytest 8.3.5.

Test surface:
- `agent/test_intent.py`, `agent/test_persona.py`
- `tests/test_s1_verification.py`, `test_s2_verification.py`
- `tests/test_s3_integration.py`, `test_s3_state_model.py`
- `tests/test_s4_failure_reasoning.py`, `test_s4_integration.py`
- `tests/test_s5_recovery.py`, `test_s5_integration.py`
- `tests/test_s6_work.py`, `test_s6_integration.py`
- `tests/test_s7_context.py`
- `tests/test_s9_persona.py`
- `tests/test_browser_runtime.py`

---

## 3. What S10 adds (and does NOT add)

### 3.1 S10 adds
- An explicit `WorkState` view over the currently-executing plan
  (planned / running / adapting / blocked / completed / unknown).
- A deterministic `AdaptiveDecision` output: one of
  `CONTINUE | ADAPT | BLOCK | COMPLETE | FAIL | UNKNOWN`.
- An adaptation policy matrix (deterministic, no LLM) analogous to
  `RECOVERY_POLICY` but scoped to *situational reassessment* rather than
  *failure recovery*.
- A hard cap on adaptation rounds per work session.
- A recursion guard identical in spirit to `recovery.is_recovery_in_progress()`.
- A validator that any adapted candidate step must pass before it can be
  executed by S6 (mirrors `intent.PlanValidator` semantics).

### 3.2 S10 does NOT add
- No new tool implementations.
- No new verification logic (reuses S2).
- No new state cache (reuses `state.cache`).
- No new failure categories (reuses S4).
- No new recovery logic (reuses / delegates to S5).
- No new memory store (reuses `context.store`).
- No new response templates (falls through existing `ResponseTranslator`).
- No LLM in this milestone.
- No autonomous plan generation from scratch. Adaptation reshapes remaining
  steps of an existing authorized plan; it does not invent goals.

---

## 4. Distinguishing S5 from S10

Both consume S3 state and S4 failure. They differ in *when* they fire and
*what* they answer.

| Aspect | S5 Recovery | S10 Adaptation |
|--------|-------------|----------------|
| Trigger | Verified step failure with known category | Divergence between plan expectations and observed state |
| Scope | Retry / heal the failed step itself | Reshape remaining plan toward goal |
| Reasoning | Categorical policy lookup | Situational: goal + verified state + remaining steps |
| Example | `CAT_APP_NOT_OBSERVED → RELAUNCH_APPLICATION` | Expected file at path A missing → search authorized paths B, C |
| UNKNOWN | Blocks recovery | Blocks adaptation (identical epistemic rule) |
| Loops | 1 attempt max | Bounded adaptation rounds max |

S10 must call S5 when categorical recovery applies, not duplicate it.

---

## 5. Epistemic invariants inherited (unchanged)

1. `UNKNOWN` state is never adapted around → `BLOCK`, never `ADAPT`.
2. `REQUIRES_REFRESH` freshness forces re-observation before any adaptation
   decision consumes the observation.
3. Historical memory (S7) may *inform* candidate adaptations but never
   *justify* them without a fresh S2 verification.
4. Authorization is not inferred. Adapted steps require explicit authorization
   before they reach `execute_work` internals for execution.
5. Verification remains the sole authority for step outcomes. S10 does not
   declare success; S2 does.

---

## 6. Proposed module boundary

**Preferred:** new module `agent/adaptive_work.py` (does not exist yet).

**Rationale:**
- `work.py` stays under 300 lines and keeps its single responsibility
  (sequential execution).
- The seam in `execute_work()` becomes a one-line hook:
  `decision = adaptive_work.reassess(...)` gated by a feature flag
  defaulting to *off* so S6 behavior is byte-identical when disabled.
- Tests for S10 live in `tests/test_s10_adaptive_work.py` and
  `tests/test_s10_integration.py`, isolating regression risk.

**Alternative considered:** inline into `work.py`. Rejected because it
would blur the S6/S10 responsibility boundary and make the feature flag
hard to reason about.

An ADR is not required for this decision because it introduces a new file
rather than modifying an existing architectural contract.

---

## 7. Proposed public surface (draft, subject to test-driven refinement)
adaptive_work.reassess(
goal: str,
remaining_steps: list[dict],
last_step_result: dict,
verified_state: StateObservation | None,
adaptation_round: int,
) -> AdaptiveDecision


Where `AdaptiveDecision` is:
{
"decision": "CONTINUE" | "ADAPT" | "BLOCK" | "COMPLETE" | "FAIL" | "UNKNOWN",
"reason": str,
"evidence": list[str],
"candidate_steps": list[dict], # empty unless decision == "ADAPT"
"adaptation_round": int,
}

Contract:
- Pure function of its inputs. No I/O.
- Never returns `ADAPT` when the driving observation has freshness
  `REQUIRES_REFRESH` or `UNKNOWN`.
- Never returns `ADAPT` when `adaptation_round >= MAX_ADAPTATION_ROUNDS`.
- `candidate_steps` must independently pass the same validator that S8
  applies to intent-derived plans.

---

## 8. Hard bounds (draft numbers, to be justified in code review)

| Bound | Draft value | Rationale |
|-------|-------------|-----------|
| `MAX_ADAPTATION_ROUNDS` per work session | 3 | Well below S6's `MAX_STEPS=16`; enough for `look-elsewhere → verify → continue` patterns without runaway. |
| `MAX_ADAPTED_STEPS_PER_ROUND` | 2 | Adaptation reshapes locally, not globally. |
| Total steps executed (planned + adapted) | ≤ `MAX_STEPS` (16) | Reuses S6's existing bound. Non-negotiable. |
| Recursion guard | 1 in-flight adaptation | Mirrors `recovery.is_recovery_in_progress()`. |

These numbers are **starting points**, not final. They will be revisited
after the initial test suite exposes real behavior.

---

## 9. Feature flag

S10 must be introduced behind an explicit runtime flag:

execute_work(plan, authorized=False, adaptive=False)

- Default `adaptive=False` → byte-identical S6 behavior.
- `adaptive=True` → S10 reassessment hook is consulted at the halt seam.

All existing S6 tests remain unmodified and continue exercising the
`adaptive=False` path.

---

## 10. Known latent issues (documented, NOT fixed in S10)

These pre-existing issues were surfaced during investigation. They are
**out of scope** for S10 per brief §26 ("Improve architecture when evidence
requires it, not because S10 gives us an excuse to refactor"):

1. `agent/work.py::validate_plan` uses `Tuple[bool, str]` return
   annotation without importing `Tuple`. `from __future__ import annotations`
   defers evaluation so no NameError is raised at runtime. Would only
   surface under `typing.get_type_hints()`.
2. `agent/intent.py::ResponseTranslator.translate` uses ambiguous operator
   precedence in its authorization branch. Works correctly today because
   `work.py` returns a summary containing "authorized" but not
   "Unauthorized". Fragile to string changes in `work.py`.

Both issues are pre-existing on `main @ 7917a5a` and were not introduced by
S10. Either can be addressed in a targeted follow-up commit, but should not
be bundled with the S10 architectural work.

---

## 11. Non-goals (mirrors brief §28)

- Unrestricted autonomous computer control.
- Infinite agent loops.
- Self-modifying Zarya.
- Unrestricted tool discovery.
- Bypassing authorization.
- Replacing S5 / S6 / verification / memory.
- Autonomous browser takeover.
- LLM integration in this milestone.

---

## 12. Definition of investigation done

- [x] All S10-relevant source files read end-to-end.
- [x] Regression floor (171 tests) confirmed green on baseline.
- [x] Seam for S10 identified as a single insertion point in `execute_work`.
- [x] Reuse contract with S3/S4/S5/S6/S7 explicit.
- [x] Non-goals restated in project terms.
- [x] Latent issues documented and *deliberately* deferred.
- [x] Feature-flag boundary defined.

Next document: `docs/research/s10-adaptive-work-limitations.md` — will be
written after the initial test suite exposes empirical limits of the
deterministic adaptation policy matrix.