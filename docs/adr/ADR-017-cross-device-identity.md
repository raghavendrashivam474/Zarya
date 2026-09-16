# ADR-017: Cross-Device Identity & Local Device Fabric

## Status
Proposed

## Context
S16 established unified artifact/context resolution on the local machine.
S17 extends Zarya's semantic model to include logical device identity.

## Decision
Zarya owns logical device identity and semantic device resolution.
Device identity is separate from network identity (Flux PeerId/PathId).

## Explicit Separation
- DeviceId  → Which logical device does the user mean?
- PeerId    → Which Flux node represents an endpoint? (S18)
- PathId    → Which connectivity path reaches that peer? (S18)

## S17 Scope
- DeviceIdentity model
- DeviceRegistry (local, explicit)
- Deterministic device resolution
- Trust state tracking

## S18 Scope (future)
- Flux adapter
- Connectivity and transport
- Network discovery

## Non-Goals (S17)
- Network discovery (mDNS, UDP, TCP, Bluetooth)
- File transfer or chunking
- Remote execution
- Mobile runtime
- LLM-based device matching

## Consequences
- S17 is fully testable offline with no network dependencies
- S18 can plug into S17's DeviceIdentity without modifying the semantic layer

