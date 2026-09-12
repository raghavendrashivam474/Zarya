# S5 — Closed-Loop Recovery Investigation

**Status:** COMPLETE (pre-implementation)
**Baseline:** v0.4.0-s4 (14dff2c)
**Branch:** zarya/s5-closed-loop-recovery
**Scope boundary:** BOUNDED RECOVERY ONLY. No multi-step planning. No LLM. No persistence.

---

## 1. Failure-to-Recovery Mapping

| Failure Category | Recoverable | Recovery Action | Risk Level | Rationale |
|---|---|---|---|---|
| APPLICATION_NOT_OBSERVED | YES (conditional) | RELAUNCH via openApplication | LOW | Re-invocation is idempotent-ish; must check for duplicate process |
| APPLICATION_VERIFICATION_UNAVAILABLE | NO | — | — | Verification itself is broken; cannot verify recovery |
| APPLICATION_VERIFICATION_FAILED | NO | — | — | Probe exception; recovery unverifiable |
| FILE_NOT_CREATED | YES (conditional) | REPEAT via createFile(overwrite=True) | MEDIUM | Safe if path is within SAFE_ROOTS; re-check existence first |
| FILE_CONTENT_MISMATCH | NO | — | HIGH | External modification possible; overwrite could destroy legitimate data |
| FILE_VERIFICATION_UNAVAILABLE | NO | — | — | Cannot verify recovery outcome |
| TERMINAL_ERROR_DETECTED | NO | — | HIGH | Commands may have partial side effects; retry could double-apply |
| INSUFFICIENT_EVIDENCE | NO | — | — | Epistemic rule: UNKNOWN != permission to act |

**Recoverable set: 2 out of 8 categories.**

---

## 2. Reusable Existing Actions

| Recovery Need | Existing Tool | Reusable? | Notes |
|---|---|---|---|
| Relaunch application | openApplication | YES | Already validates via _resolve_app, verifies via _verify_application_launched, captures state |
| Recreate file | createFile | YES (with overwrite=True) | Already validates path safety via _ensure_safe, verifies via _verify_file_created |
| Retry terminal | runTerminalCommand | NO | Side effects unknown; blacklist must not be bypassed |

**No new tools needed.** Recovery re-invokes existing tools through the TOOLS registry.

---

## 3. Unsafe Recovery Cases (Explicitly Prohibited)

1. **FILE_CONTENT_MISMATCH**: Blind overwrite could destroy external changes.
2. **TERMINAL_ERROR_DETECTED**: Command side effects are unknown; retry could double-apply (e.g., append to file, create duplicate resources).
3. **Any UNKNOWN/INSUFFICIENT_EVIDENCE**: Epistemic safety rule from S4.
4. **Stale/Expired evidence (REQUIRES_REFRESH)**: Acting on old state is unreliable.
5. **Recovery of recovery**: Recursion guard prevents infinite loops.

---

## 4. Freshness Requirements

- Recovery requires CURRENT freshness by default.
- STALE evidence: recovery NOT eligible (evidence too uncertain).
- REQUIRES_REFRESH: recovery NOT eligible.
- UNKNOWN freshness: recovery NOT eligible.

**Decision: No bounded re-observation in S5.** The brief mentioned S5 *may* extend S3 with bounded refresh, but investigation shows the current tool handlers already produce CURRENT observations at invocation time. If verification fails with CURRENT freshness, re-observing milliseconds later won't help. The failure is real, not stale.

---

## 5. Recovery Success Criteria

| Recovery Action | Success = |
|---|---|
| RELAUNCH_APPLICATION | Inner openApplication returns verification.status == VERIFIED_SUCCESS |
| REPEAT_FILE_CREATION | Inner createFile returns verification.status == VERIFIED_SUCCESS |

Recovery verification is the inner tool's own verification. No separate verification step needed.

---

## 6. UNKNOWN Recovery Verification Handling

If the inner tool returns UNKNOWN verification after recovery:
- Recovery status = UNKNOWN
- No further attempts
- Original failure preserved

---

## 7. Architecture Decision

**Selected: Option B — Shared Recovery Orchestrator**
Tool Handler
→ execute action
→ verify
→ capture state
→ reason about failure (S4)
→ attempt_recovery (S5) ← NEW
→ return {result, verification, state, failure, recovery}

text


**Rejected:**
- Option A (recovery inside tools): Spreads policy across 3 files, harder to audit.
- Option C (policy engine): Over-engineered for 2 recoverable categories.
- Option D (LLM-driven): Explicitly deferred per brief.

**Recursion guard:** Module-level threading.local flag prevents recovery-of-recovery.

---

## 8. Authorization Model

Recovery inherits the original tool's authorization:
- Application: authorized if app name resolves via _resolve_app (already validated by original call).
- Filesystem: authorized if path passes _ensure_safe (re-checked during recovery).
- Terminal: not eligible, so authorization is moot.

No new authorization infrastructure needed. Existing safety boundaries are sufficient.

---

## 9. Files to Create/Modify

**New:**
- agent/recovery.py — bounded recovery orchestrator
- tests/test_s5_recovery.py — unit tests
- tests/test_s5_integration.py — integration tests
- docs/research/s5-closed-loop-recovery-investigation.md — this document

**Modified (surgical, ~5 lines each):**
- agent/tools/applications.py — add recovery call after failure reasoning
- agent/tools/files.py — add recovery call after failure reasoning

**NOT modified:**
- agent/failure.py (S4 frozen)
- agent/state.py (S3 frozen)
- agent/registry.py
- agent/server.py
- agent/tools/terminal.py (no recovery for terminal)
- Any S1/S2/S3 tests
