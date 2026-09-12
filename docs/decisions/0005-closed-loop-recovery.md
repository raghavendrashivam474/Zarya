# ADR 0005: Bounded Closed-Loop Recovery Pattern

## Status
Accepted (S5 milestone - Hardened)

## Context
In S0–S4, Zarya established execution, multi-domain post-condition verification, computer state tracking, and evidence-grounded failure reasoning. When an action produced a verified failure, Zarya could explain what went wrong with structured evidence and confidence metrics. However, Zarya had no mechanism to perform controlled, bounded remediation.

Recovery without boundaries risks runaway autonomous loops, destructive side effects (e.g., blind overwrites), and safety bypasses. S5 introduces a tightly bounded recovery layer.

## Decision
We implement a **Synchronous, Policy-Gated, Single-Attempt Recovery Orchestrator** (`agent/recovery.py`).

Key architectural components:
1. **Explicit Policy Authorization**:
   - Recovery authorization is an explicit policy rule inside `agent/recovery.py`, not inferred from tool-level parameter validation.
   - General authorization infrastructure is deliberately deferred.
2. **Narrowed Recovery Surface**:
   - Only `APPLICATION_NOT_OBSERVED` is eligible for automatic recovery (`RELAUNCH_APPLICATION`).
   - `FILE_NOT_CREATED` recovery is deferred to prevent destructive TOCTOU overwrite races.
   - `FILE_CONTENT_MISMATCH`, `TERMINAL_ERROR_DETECTED`, and `INSUFFICIENT_EVIDENCE` are strictly non-recoverable.
3. **Finite Bound & Recursion Guard**:
   - Maximum automatic recovery attempts: exactly **1**.
   - Thread-local recursion guard (`is_recovery_in_progress`) prevents recovery actions from triggering nested recoveries.
4. **Outcome Verification**:
   - A recovery attempt is only marked `RECOVERED` if post-recovery state verification returns `VERIFIED_SUCCESS`.
   - Action completion is not treated as recovery success.
5. **Additive Result Shape**:
   - Recovery status and metadata are returned under an additive `"recovery"` key. The original `"verification"` and `"failure"` fields are preserved without mutation.

## Consequences
- **Positive**: Controlled self-healing for transient application launch failures without introducing unconstrained agent loops, destructive file overwrites, or LLM hallucination risks.
- **Negative**: Filesystem remediation is deferred until safer atomic primitives exist.
