# N6 Specification: Shyam/S16 Integration & Two-Node Continuity

**Sprint:** N6  
**Phase:** Multi-Device Work Continuity  
**Baseline:** `v1.5.0-n5`  
**Status:** COMPLETE / FROZEN  

---

## 1. System Integration Architecture

N6 establishes the cross-device execution pipeline between Zarya, Shyam, and Aryntra Flux:

```text
┌───────────────────────────┐
│     ZARYA A (Source)      │
│  - HandoffRequest         │
│  - ContinuityCoordinator  │
└─────────────┬─────────────┘
              │ ContinuityTransferRequest
              ▼
┌───────────────────────────┐
│    SHYAM ORCHESTRATOR     │
│  - ContinuityTarget       │
│  - Resolution (URL/Peer)  │
└─────────────┬─────────────┘
              │ Flux Transport
              ▼
┌───────────────────────────┐
│       ARYNTRA FLUX        │
│  - TransportResult        │
└─────────────┬─────────────┘
              │ Deliver Payload
              ▼
┌───────────────────────────┐
│     ZARYA B (Target)      │
│  - continue_portable_work │
│  - N4 Reconstruction      │
│  - S18 Execution Engine   │
└─────────────┬─────────────┘
              │
              ▼
      VERIFIED_SUCCESS
```

## 2. Inviolable Boundary Contracts

1. **Subsystem Isolation**:

      - Shyam consumes Zarya over HTTP/RPC contracts; Zarya does not consume Shyam.
      - Transport is mediated by FluxTransportProvider protocol without leaking Flux internals.

2. **Correlation Spine**:

      - work_id -> continuity_id -> target_operation_id -> outcome

3. **Outcome Authority**:

      - Transport success != Work success.
      - VERIFIED_SUCCESS requires verified physical slice / S18 completion.
      - UNKNOWN is terminal and non-recoverable without manual inspection.
