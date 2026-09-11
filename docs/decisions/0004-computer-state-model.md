# ADR 0004: Computer State Model Pattern

## Status
Accepted (S3 milestone)

## Context
In milestones S0–S2, Zarya established the ability to verify actions across multiple domains (Applications, Filesystem, Terminal). However, these verification outcomes were strictly "action-local" and transient—they occurred as part of a tool call and were immediately discarded. Zarya lacked an internal representation of what was currently believed to be true about the system or how fresh that belief was. To enable future milestones (failure reasoning, recovery, multi-step execution), Zarya requires a persistent but minimal model of the computer's state.

## Decision
We implement a **decentralized state-model substrate** rather than a heavy, centralized state monitor or background daemon. 

Key architectural components:
1. **Normalized State Representation (`StateObservation`)**: A common schema containing domain, subject, timestamp, verification status, structured state payload, raw evidence, and freshness category.
2. **Age-Based Freshness Semantics (`StateFreshness`)**: Every observation is classified as `CURRENT`, `STALE`, `REQUIRES_REFRESH`, or `UNKNOWN` based on a configurable age heuristic.
3. **Session-Scoped Memory Cache (`StateCache`)**: A simple, in-memory, process-wide single-point cache keyed by `(domain, subject)` that preserves the most recent point-in-time observation.
4. **Additive Tool Integration**: Existing tool handlers for `openApplication`, `createFile`, and `runTerminalCommand` are extended to capture state observations inside the cache and append a `"state"` field to their existing returns, ensuring complete backward compatibility.

## Consequences
- **Zero performance overhead**: State acquisition remains strictly on-demand as a post-action side effect. No continuous background polling is introduced.
- **Improved semantic queryability**: High-level orchestrators can now inspect the cache to understand what has changed, when it was last observed, and whether those assumptions are still current.
- **Complete safety preservation**: The cache is purely passive. Knowing a file's state does not alter user permission boundaries or bypass agent authorization.
