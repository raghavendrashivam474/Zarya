# ADR-017: Cross-Device Identity & Local Device Fabric

## Status
Accepted

## Context
Through milestones S12–S16, Zarya established comprehensive artifact identity and unified context resolution strictly bounded to the local machine where the agent executes. S16 allows deterministic understanding of references such as *"this document"*, *"this file"*, or *"the page I'm on"*.

However, multi-device workflows require Zarya to understand target logical devices (*"my laptop"*, *"my phone"*, *"office PC"*). Treating devices as raw networking endpoints (IP addresses, ports, or transport sockets) directly inside the agent layer would violate separation of concerns and tie the semantic model to physical connectivity.

## Decision
1. **Zarya owns logical device identity and deterministic semantic resolution**:
   - DeviceIdentity: Stable, logical descriptor (device_id, display_name, device_type, platform, capabilities, 	rust_state, is_available).
   - DeviceRegistry: Local, thread-safe in-memory store representing known devices in the local fabric.
   - esolve_device_reference: Pure deterministic resolution engine (exact ID, name, taxonomy category keywords, relative references with caller exclusion).
   - esolve_compound_intent: Decomposes multi-target requests (e.g., *"send this document to my laptop"*) into artifact resolution (S16) and device resolution (S17).

2. **Explicit Separation of Identity Layers**:
Zarya Logical Identity (S17) --> DeviceId
|
| (S18 Adapter Mapping)
v
Aryntra Flux Node (S18) --> PeerId
|
+--> Path A (Local Wi-Fi)
+--> Path B (Direct TCP)
+--> Path C (Relay)

text

- DeviceId $\neq$ PeerId $\neq$ PathId.
- Zarya semantic layer never imports Flux, sockets, or transport abstractions.

3. **Core Invariants Maintained**:
- **Context $\neq$ Authorization**: Resolving an untrusted device returns RESOLVED with 	rust_state == UNTRUSTED. It does not grant execution permission.
- **Identity $\neq$ Connectivity**: Offline devices resolve to UNAVAILABLE, preserving identity without asserting network reachability.
- **Zero Guessing**: Ambiguous references (multiple matches) halt with AMBIGUOUS. Unknown references return NOT_FOUND.

## Consequences
- S17 is fully operational and testable offline with 0 network dependencies.
- S18 (Flux integration) can implement transport adapters by mapping DeviceId to PeerId without altering Zarya's semantic or intent resolution pipelines.
- S16 artifact and context resolution remain completely intact and backwards-compatible.
