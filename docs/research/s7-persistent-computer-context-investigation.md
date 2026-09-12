# S7 Persistent Computer Context Investigation

## Objective
To analyze how Zarya can maintain contextual awareness of past computer states, workflow executions, and recovery outcomes across process sessions without violating key safety, reliability, and epistemic boundaries.

## Key Discoveries

### 1. The Epistemic Boundary (Memory vs. State)
During investigation, we analyzed the transition from current-state verification to historical recall.
```text 
┌────────────────────────┐
│ Current State │ ──► "Is notepad.exe running right now?"
│ (S3 Cache) │ Requires fresh process probe.
└────────────────────────┘
▲
│ Epistemic Barrier: Memory must not cross silently
│
┌────────────────────────┐
│ Historical Context │ ──► "Was notepad.exe observed running earlier?"
│ (S7 Store) │ Answer: "Yes, at 10:04 UTC (Verified Success)."
└────────────────────────┘
```


Treating memory as current state introduces **Time-of-Check to Time-of-Use (TOCTOU) hazards**. If a memory says a file has size 4096 bytes, and an S6 step acts on that size without re-observing, it may fail if an external process deleted or altered the file. S7 enforces time-awareness by requiring that any recalled memory evaluate its age against a freshness threshold before being presented to a reasoning loop.

### 2. Standardizing Structured Outcomes
Instead of designing a new JSON scheme for historical records, we successfully integrated the existing domain structures:
- **S3 StateObservation**: Becomes an `observation` memory.
- **S4 Failure Reason**: Stored inside the step context when an execution fails, keeping the error classification intact.
- **S5 Recovery Result**: Captured as-is inside step memory, allowing Zarya to trace whether an application was relaunched due to an initial failure.
- **S6 Work Result**: Captured as a `work_outcome` along with its sub-steps as `step_outcome` records, maintaining execution linkage.

### 3. Lightweight SQLite Selection
Our investigation confirmed that local SQLite is the optimal persistence substrate for Milestone S7:
- **No external daemon**: No background service dependencies that can fail or require administrative installation.
- **ACID Transactions**: Guard against corruption during partial or concurrent writes.
- **Zero Configuration**: Single local file with automatic table creation makes testing simple and environment-independent.
