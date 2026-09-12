# ADR 0007: Persistent Computer Context

## Status
Accepted

## Context
As of Milestone S6, Zarya successfully performs multi-step computer tasks, validates outcomes via a domain-specific verification fabric, reasons about failure modes, and recovers from failures in a closed-loop. However, all computer observations, step results, and task contexts expire immediately upon agent or process termination.

For Zarya to acquire continuity, she must be able to remember past operations and observations. 
However, introducing persistent memory presents a severe epistemic risk: **if historical observations are treated as current truth, the agent will hallucinate the state of the computer (e.g., assuming a file is still present because it existed 3 hours ago).**

Additionally, introducing remote or complex vector databases adds unnecessary runtime dependencies, latency, and points of failure to an otherwise local, inspectable computer-use substrate.

## Decision
We implement a lightweight, local, schema-driven persistent context layer (Milestone S7) governed by the following architectural choices:

1. **Epistemic Separation (State vs. Memory)**:
   - S3 remains the source of truth for the *current session's state*.
   - S7 is the *historical context layer*. Memories are explicitly labeled as past evidence, never current truth.
   - Any query returning a memory record must expose its age and mark `current_state_established=False`.

2. **Storage Substrate (SQLite)**:
   - We utilize Python's standard library `sqlite3` driver. No external database servers (Redis, PostgreSQL, cloud databases) or vector stores are introduced.
   - Storage is local to the operating system's standard data paths (`%LOCALAPPDATA%` on Windows, standard XDG path on POSIX).

3. **Strict Schema and Type Preservation**:
   - Instead of natural language logs, S7 stores structured `MemoryRecord` envelopes.
   - S3 `StateObservation` payloads, S4 `failure` structures, and S5 `recovery` results are serialized and preserved verbatim inside the record JSON payloads, maintaining absolute provenance.

4. **Failure Isolation**:
   - The S7 persistent context store is entirely additive. 
   - If the database file is corrupted, read-only, or fails to open, S7 swallows the exception, returns an explicit `StoreStatus.UNAVAILABLE` code, and logs a warning. **It must never crash or interrupt execution in S1–S6.**

5. **Epistemic Classification Rule (UNKNOWN Gating)**:
   - State observations with an `UNKNOWN` status are strictly banned from being recorded as standard factual `observation` types. They are forced into the `uncertain_observation` memory category to prevent the promotion of uncertainty to fact.

6. **Bounded Retrieval Limits**:
   - Retrieval queries enforce mandatory bounds. Queries are clamped to a minimum of 1 and capped at a maximum of 500 records to prevent memory exhaustion from unbounded historical dumps.

## Consequences
- **Continuity**: Zarya can now report on past tasks and observations across agent and process restarts.
- **Traceability**: Every remembered fact has complete provenance including domain, timestamp, verification method, and original tool.
- **Robustness**: If local file permissions block database creation, multi-step actions and tool execution remain unaffected.
- **Safety**: Natural language personality memory and cloud synchronization are explicitly prevented, keeping the memory domain tightly bound to "Computer Context".
