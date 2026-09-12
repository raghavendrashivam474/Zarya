# S5 — Closed-Loop Recovery Limitations

This document captures the physical, algorithmic, and safety boundaries of Zarya's closed-loop recovery capabilities as of S5 (v0.5.1-s5).

---

## 1. Safety & Autonomy Limits
* **Strict Single-Attempt Limit:** S5 executes at most ONE recovery action per failed operation. There are no retry loops, exponential backoffs, or iterative trial-and-error behaviors.
* **Narrow Recovery Surface:** Only `APPLICATION_NOT_OBSERVED` is eligible for automatic recovery.
* **No Filesystem Recovery in S5:** `FILE_NOT_CREATED` is not automatically recovered in S5 because `overwrite=True` carries destructive TOCTOU race condition risks.
* **No Terminal Recovery:** Terminal command errors (`TERMINAL_ERROR_DETECTED`) are never automatically retried because arbitrary shell commands may have non-idempotent or unknown side effects.
* **No Content Mismatch Overwrites:** If a file exists with unexpected content (`FILE_CONTENT_MISMATCH`), automatic recovery is refused.
* **No Speculative or LLM-Driven Recovery:** Recovery policies are hardcoded deterministic rules. Zarya never uses an LLM to invent recovery actions dynamically.

---

## 2. Epistemic & Freshness Boundaries
* **UNKNOWN Is Never Recoverable:** In accordance with S4 epistemic safety rules, `INSUFFICIENT_EVIDENCE` or `UNKNOWN` verification never grants permission to act.
* **Freshness Decay:** Recovery requires `CURRENT` state freshness. If evidence is `STALE`, `REQUIRES_REFRESH`, or `UNKNOWN`, recovery is rejected immediately.

---

## 3. Persistence & Memory Limits
* **Zero Recovery History Across Sessions:** Recovery outcomes are transiently appended to the immediate tool response payload. No database, event log, or vector store persists recovery history across invocations.
