# S11 Runtime Step Event Semantics & Contract

**Date**: 2026-09-14
**Milestone**: S11 — Multi-Step Visibility & Presentation Refinement
**Status**: Authoritative

---

## 1. Overview & Golden Rule

In accordance with the Zarya architecture:
> **Zarya knows. The event bridge exposes. Shefali presents.**

Step-level visibility surfaces authoritative execution and verification facts from `agent/work.py` without modifying the underlying safety, authorization, recovery, or planning semantics.

---

## 2. Event Sequence in Multi-Step Work

A multi-step workflow produces the following deterministic sequence:

```text
work_started (state: WORKING, operation_id)
  │
  ├─► work_step_started (state: WORKING, tool, payload: {step_id, step_index, total_steps})
  │     [Tool Execution + S2/S3 Observation + Verification + S5 Recovery]
  ├─► work_step_completed (state: <outcome>, tool, payload: {step_id, status, detail, ...})
  │
  ├─► work_step_started (state: WORKING, tool, payload: {step_id, step_index, total_steps})
  │     [Tool Execution + S2/S3 Observation + Verification + S5 Recovery]
  ├─► work_step_completed (state: <outcome>, tool, payload: {step_id, status, detail, ...})
  │
  └─► work_completed (state: <overall_outcome>, operation_id, payload: {completed_steps, ...})
```

## 3. Step Outcome State Mapping

Step-level outcomes determined by _evaluate_step_outcome() map authoritatively to runtime event states:

| Internal Step Status | Runtime Event State | Operational Meaning |
| :--- | :--- | :--- |
| `STEP_SUCCESS` | `VERIFIED_SUCCESS` | Step action was executed, observed, and authoritatively verified. |
| `STEP_RECOVERED` | `VERIFIED_SUCCESS` | Step failed initially, but S5 closed-loop recovery successfully resolved it. |
| `STEP_FAILURE` | `VERIFIED_FAILURE` | Step action failed, or execution verification affirmatively failed. |
| `STEP_UNKNOWN` | `UNKNOWN` | Step outcome could not be verified; epistemic safety is preserved. |

**Epistemic Rule**: An UNKNOWN step verification status must never be coerced or fabricated into VERIFIED_SUCCESS or VERIFIED_FAILURE for presentation convenience.

## 4. Failure Isolation Contract

Event emission is strictly best-effort observation and must never be an execution dependency:

1. If an event callback or HTTP post fails, times out, or throws an exception, the error is logged and discarded.
2. The core execution queue in execute_work() continues without interruption.
3. A failed event emission must never cause a step or workflow to fail.

## 5. Event Payload Specifications

### work_step_started

```JSON
{
  "type": "runtime_event",
  "version": 1,
  "event": "work_step_started",
  "operation_id": "work-1710000000-abcde",
  "timestamp": "2025-03-10T12:00:00.000Z",
  "state": "WORKING",
  "tool": "createFile",
  "payload": {
    "step_id": "step_1",
    "step_index": 0,
    "total_steps": 3,
    "args": { "path": "notes.txt" }
  }
}
```
### work_step_completed

```JSON
{
  "type": "runtime_event",
  "version": 1,
  "event": "work_step_completed",
  "operation_id": "work-1710000000-abcde",
  "timestamp": "2025-03-10T12:00:01.200Z",
  "state": "VERIFIED_SUCCESS",
  "tool": "createFile",
  "payload": {
    "step_id": "step_1",
    "status": "VERIFIED_SUCCESS",
    "detail": "File created and verified on filesystem.",
    "verification": { "status": "VERIFIED_SUCCESS", "detail": "File exists." },
    "recovery": null
  }
}
```
