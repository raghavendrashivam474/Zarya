# Zarya N7 Engineering Specification: Physical Two-Node Runtime Validation

**Sprint:** N7
**Phase:** Multi-Device Work Continuity
**Target:** Physical Certification of Shyam V1 Core

## 1. Objective
Certify that the Zarya N5 + Shyam cross-device continuity + Aryntra Flux architecture executes across two real physical machines with genuine Zarya HTTP daemons, live Shyam discovery, and real Flux transport contracts.

## 2. Architecture Boundary Preservations
- **No Rewrite of Continuity Engine:** Reused existing ContinuityService, ContinuityCoordinator, and continue_portable_work.
- **No Flux Protocol Alteration:** Maintained FluxTransportProvider / FluxClient boundary.
- **Sovereign Discovery Metadata Resolution:** Solved the N6 localhost broadcast limitation by injecting _resolve_lan_url() into Shyam runtime discovery metadata publication.
- **EIP-1 Boundary Enforcement:** Mounted @router.post("/work/continue") onto Zarya EIP-1 boundary to accept PortableWork and delegate to N4 continuation.

## 3. Five-Link Correlation Contract
```text
Every continuity operation preserves uninterrupted traceability:
work_id -> continuity_id -> target_operation_id -> ContinuityState.COMPLETED -> target filesystem artifact verification
```

