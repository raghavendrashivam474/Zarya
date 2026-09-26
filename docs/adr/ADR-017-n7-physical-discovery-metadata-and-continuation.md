# ADR-017: LAN IP Discovery Metadata Resolution and EIP-1 Work Continuation Boundary

## Status
Accepted

## Context
N6 established contract verification but exposed that default discovery metadata broadcasted loopback addresses (127.0.0.1), preventing cross-device routing. Additionally, Zarya required a formal HTTP adapter on its EIP-1 boundary for incoming PortableWork packages.

## Decision
1. In Shyam runtime discovery, dynamically resolve 127.0.0.1 / localhost to the active physical LAN interface IP at broadcast time.
2. Mount @router.post("/work/continue") in Zarya gent/ecosystem/routes.py, delegating to continue_portable_work.
3. In gent/continuity/execution.py, inspect overall_status from S18 execution to map verified verdicts accurately.

## Consequences
- Physical two-machine work continuity operates seamlessly without manual IP configuration.
- Existing unit tests across Zarya, Shyam, and Flux remain 100% green.
