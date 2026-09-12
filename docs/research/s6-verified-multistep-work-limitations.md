# Zarya S6: Verified Multi-Step Work — Limitations & Deferred Boundaries

## Summary
Milestone S6 introduces deterministic, bounded multi-step plan execution with verification and closed-loop recovery integration. The system intentionally defers several autonomous and long-running capabilities to maintain strict epistemic safety.

---

## 1. No Autonomous Planning / LLM Goal Decomposition
- S6 executes strictly pre-structured, validated WorkPlans (`execute_work(plan)`).
- S6 does **not** dynamically generate plans or adapt step sequences via LLM reasoning mid-execution.
- Generative planning from high-level natural language requests is deferred to milestone S8+.

## 2. No Rollback / Transactional Reversion
- Desktop actions across processes, filesystem, and terminal environments cannot be universally or safely rolled back without introducing unpredictable state mutations.
- Instead of speculative rollback, S6 enforces **partial completion state preservation** (`completed_steps`, `failed_step`, `skipped_steps`), giving the caller exact ground truth on what was executed and what was skipped.

## 3. Fixed Step Bound (`MAX_STEPS = 16`)
- Plan execution is capped at 16 steps to prevent runaway loops or infinite executions.
- Step execution is strictly forward-only: no backtracking or loop constructs.

## 4. Single Step-Level Recovery Bound
- S6 relies entirely on S5's single-attempt closed-loop recovery mechanism.
- If S5 recovery fails for a step, S6 immediately halts execution. It does not attempt alternative recovery strategies or multiple retries.

## 5. Non-Verified Tool Gating
- Tools that do not return a standardized S2 verification envelope (e.g. `readFile`, `renameFile`) are treated as `UNKNOWN` unless the step explicitly sets `"unverified_ok": true`.
- Future milestones will progressively bring all remaining desktop tools under the verification fabric.

## 6. No Execution-Level Timeout
- S6 does not enforce a global wall-clock deadline across all steps in the plan. Individual tool-level timeouts apply.
