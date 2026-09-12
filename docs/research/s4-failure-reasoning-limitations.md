# S4 — Failure Reasoning Limitations

This document captures the physical and architectural limitations of Zarya's failure reasoning as of S4 (v0.4.0-s4). These are boundaries we explicitly refuse to bypass without concrete evidence, new metrics, or backend capabilities.

---

## 1. Domain-specific limits

### 1.1 Application Domain
* **Launcher Blind Spot:** The backend's launch mechanism does not capture the return status of the process spawn command (e.g., `subprocess.Popen`). We only know if a process is not observed during the polling window. We cannot distinguish between a missing executable, a permission error at spawn, or a crash immediately after launch.
* **Process Lifespan Blind Spot:** A process that starts, executes, and exits successfully within the 500ms polling interval will be classified as `APPLICATION_NOT_OBSERVED` and reported as a `VERIFIED_FAILURE`. S4 does not have active event tracing or process lifetime monitoring.

### 1.2 Filesystem Domain
* **Pre-empted Writes:** If `createFile` fails because of a hard write error (e.g., disk full, write permission denied), Python's I/O layer throws an exception *before* reaching verification. Therefore, the reasoner only reasons about post-write states (such as unexpected external modifications causing content mismatches or deletions).
* **Missing Error Detail:** When a content match fails, we only know that `content_matches` is False. We do not perform diffing or capture structural differences due to performance constraints.

### 1.3 Terminal Domain
* **Merged Output:** Because stdout and stderr are merged into a single string by the active terminal backend, we cannot confidently assert whether a command succeeded with warnings or produced a hard stderr failure.
* **No Return Codes:** The terminal backend contract does not expose command exit status (return code). S4 relies entirely on substring-matching error indicators. This is why terminal success is marked with `verification_strength: weak`.

---

## 2. Temporal limitations (S3 State dependence)
* **Stale Evidence Degradation:** S4 does not trigger re-observation. If an observation's freshness degrades from `CURRENT` to `STALE` or `REQUIRES_REFRESH`, the reasoner automatically caps the confidence of its explanations (e.g., capping HIGH to MEDIUM or LOW). It does not pretend old evidence is fresh.
* **No Chronological Correlation:** S4 reasons about the *most recent* observation in the session cache. It does not correlate multiple historical states to form a timeline of failure.

---

## 3. Boundary restrictions
* **No Self-Correction:** The reasoner output is strictly informative. S4 does not automatically retry, run alternative commands, rollback changes, or request human correction.
* **No Vector or Persistent Memory:** All reasoning is executed against transient, session-scoped dicts. There is no SQLite, JSON logs, or vector database keeping track of past failures across runs.
