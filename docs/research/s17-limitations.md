# S17 Limitations & Architectural Boundaries

## Purpose
This document specifies the deliberate limitations and architectural non-goals of milestone S17 (*Cross-Device Identity & Local Device Fabric*).

---

## Deliberate Non-Goals in S17

1. **No Aryntra Flux Integration (Owned by S18)**
- S17 does not import Flux crates or Python bindings.
- S17 contains no concept of PeerId, PathId, SessionId, or Chunk.

2. **No Network Discovery or Protocol Listeners**
- S17 does not run mDNS, UDP broadcast/multicast, Bluetooth scanning, or TCP discovery.
- Devices are explicitly registered via DeviceRegistry or configuration providers.

3. **No Network Transport or File Transfer**
- S17 resolves intent targets (*"send this document to my laptop"* $\rightarrow$ Artifact: 
eport.docx, Device: dev-laptop-01).
- Execution stops before transport. Actual payload chunking and transmission belong to S18.

4. **No Remote Execution (Owned by S19)**
- S17 does not execute commands, processes, or agents on remote endpoints.

5. **No Probabilistic Matching / LLMs**
- Device resolution is strictly deterministic via exact IDs, display names, bounded category keywords, and relative spatial/context filters.
- No vector embeddings, fuzzy heuristics, or LLM agentic guessing are used.

---

## Supported Taxonomy Boundaries

- **DeviceType**: DESKTOP, LAPTOP, MOBILE, TABLET, SERVER, UNKNOWN
- **Platform**: WINDOWS, LINUX, MACOS, ANDROID, IOS, UNKNOWN
- **TrustState**: UNKNOWN, TRUSTED, UNTRUSTED, REVOKED
- **DeviceResolutionStatus**: RESOLVED, AMBIGUOUS, NOT_FOUND, UNAVAILABLE

