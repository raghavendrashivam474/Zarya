# S5 — Closed-Loop Recovery Investigation

**Status:** COMPLETE / HARDENED
**Baseline:** v0.4.0-s4 (14dff2c)
**Branch:** zarya/s5-closed-loop-recovery
**Scope boundary:** BOUNDED RECOVERY ONLY. No multi-step planning. No LLM. No persistence.

---

## 1. Hardened Failure-to-Recovery Mapping

| Failure Category | Recoverable in S5 | Recovery Action | Risk Level | Rationale |
|---|---|---|---|---|
| APPLICATION_NOT_OBSERVED | YES (Policy-Gated) | RELAUNCH via openApplication | LOW | Safe, non-destructive, verified by process image check |
| APPLICATION_VERIFICATION_UNAVAILABLE | NO | — | — | Probe verification unavailable; recovery unverifiable |
| APPLICATION_VERIFICATION_FAILED | NO | — | — | Probe exception; recovery unverifiable |
| FILE_NOT_CREATED | NO (Deferred) | — | HIGH | Deferred to avoid destructive TOCTOU overwrite race conditions |
| FILE_CONTENT_MISMATCH | NO | — | HIGH | External modification possible; overwrite could destroy data |
| FILE_VERIFICATION_UNAVAILABLE | NO | — | — | Inconclusive probe; cannot verify recovery outcome |
| TERMINAL_ERROR_DETECTED | NO | — | HIGH | Commands may have non-idempotent side effects; retry unsafe |
| INSUFFICIENT_EVIDENCE | NO | — | — | Epistemic rule: UNKNOWN != permission to act |

**Recoverable set in S5: 1 category (APPLICATION_NOT_OBSERVED).**

---

## 2. Recovery Policy & Authorization

- S5 recovery authorization is an explicit policy decision inside the recovery layer (`check_authorization`).
- Parameter validation functions (such as `_ensure_safe` or `_resolve_app`) are safety validations, not general authorization infrastructure.
- General multi-tenant/untrusted-user authorization infrastructure is deliberately deferred.

---

## 3. Filesystem Recovery Deferral

`FILE_NOT_CREATED -> createFile(overwrite=True)` was evaluated and removed during hardening.
Blindly passing `overwrite=True` introduces destructive TOCTOU risks if another process or user created the file between failure detection and recovery invocation. Safe filesystem recovery requires non-destructive atomic primitives, which are deferred.
