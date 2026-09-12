# ADR 0005: Bounded Closed-Loop Recovery Pattern

## Status
Accepted (S5 milestone)

## Context
In S0-S4, Zarya established execution, multi-domain post-condition verification, computer state tracking, and evidence-grounded failure reasoning. When an action produced a verified failure, Zarya could explain what went wrong with structured evidence and confidence metrics. However, Zarya had no mechanism to perform controlled, bounded remediation.

Recovery without boundaries risks runaway autonomous loops, destructive side effects (e.g., blind overwrites), and safety bypasses. S5 introduces a tightly bounded recovery layer.

## Decision
We implement a **Synchronous, Policy-Gated, Single-Attempt Recovery Orchestrator** (agent/recovery.py).

Key architectural components:
1. **Separation of Concerns**:
   - Tools (applications, files, terminal) -> Act & Observe.
   - S3 (state.py) -> Represent state & freshness.
   - S4 (failure.py) -> Explain failure from evidence.
   - S5 (recovery.py) -> Check eligibility, check authorization, orchestrate ONE bounded recovery action, and verify outcome.
2. **Strict Eligibility & Policy Matrix**:
   - Only failure categories with unambiguous, non-destructive remediation policies are eligible (APPLICATION_NOT_OBSERVED -> relaunch, FILE_NOT_CREATED -> repeat with overwrite).
   - FILE_CONTENT_MISMATCH, TERMINAL_ERROR_DETECTED, and INSUFFICIENT_EVIDENCE are explicitly **NOT eligible** for automatic recovery.
   - State freshness must be CURRENT. Stale, expired, or unknown freshness immediately disqualifies recovery.
3. **Finite Bound & Recursion Guard**:
   - Maximum automatic recovery attempts: exactly **1**.
   - Thread-local recursion guard (is_recovery_in_progress) prevents recovery actions from triggering nested recoveries.
4. **Outcome Verification**:
   - A recovery attempt is only marked RECOVERED if post-recovery state verification returns VERIFIED_SUCCESS.
   - Action completion is not treated as recovery success.
5. **Additive Result Shape**:
   - Recovery status and metadata are returned under an additive recovery key. The original verification and failure fields are preserved without mutation.

## Consequences
- **Positive**: Controlled self-healing for transient launch/creation failures without introducing unconstrained agent loops or LLM hallucination risks.
- **Negative**: Complex multi-step recovery chains or alternative tool fallbacks are not supported in S5 (deferred to future milestones).
