# N2 Work Context & State Model — Architecture Specification

## 1. Overview & Purpose
Sprint N2 defines the **Semantic Work Model** that connects work identity, intent, plan, lifecycle, environmental context, artifacts, authorization, and epistemic outcome without duplicating or modifying existing subsystem state machines.

It answers the core question:
> **"What exactly is this work, what state is it in, and which parts of the surrounding context actually belong to it?"**

---

## 2. Core Architecture & Ownership Model

```text
                           SemanticWorkModel (N2)
                                     │
       ┌─────────────────────────────┼─────────────────────────────┐
       │                             │                             │
    Identity                      Intent                         Plan
   (work_id)                     (goal)                      (S8 Plan Dict)
       │                             │                             │
       │                             │                             │
   Execution                      Context                      Artifacts
 (S18 op_id +               (N1 UnifiedContext              (S12 artifact_id
LifecycleStatus)           filtered to Relevant)                 references)
       │                             │                             │
       │                             │                             │
 Authorization                 Observations                     Outcome
  (S8/S18 Auth              (Provenance-Aware              (VERIFIED_SUCCESS |
   Reference)                 Step Outcomes)               VERIFIED_FAILURE |
                                                               UNKNOWN)
```

### Subsystem Boundaries Preserved:

- **S6 / S8**: Authoritative for plan construction, validation, and multi-step execution.
- **S12**: Authoritative for artifact identity and computer context continuity (artifact_id).
- **S17**: Authoritative for device identity (device_id).
- **S18**: Authoritative for runtime lifecycle status, checkpoint persistence, and resume reality check.
- **N1**: Authoritative for the point-in-time environmental context snapshot (UnifiedContext).
- **S7**: Authoritative for persistent memory and historical context (strictly distinct from active work context).

## 3. Structural Model Summary

#### `RelevantWorkContext`

Represents the subset of observed environmental context that is semantically tied to the work:

- `device_id`: Logical execution host.
- `platform`: Host OS platform (WINDOWS, LINUX, MACOS, ANDROID, etc.).
- `active_application`: Tool/application currently utilized in execution steps.
- `page_url & page_title`: Browser attributes only if the work execution utilized browser-based tools.
- `artifact_ids`: Filtered set of artifacts referenced or created during the work.

#### `SemanticWorkModel`

Represents the top-level immutable/serializable work object:

- `work_id`: Stable logical identity of the task.
- `intent`: User-facing high-level goal statement.
- `plan_reference`: Dict reference of the validated plan.
- `execution_reference`: S18 operation_id.
- `lifecycle_status`: Current S18 LifecycleStatus string value.
- `context_reference`: N1 context_id.
- `relevant_context`: Instance of RelevantWorkContext.
- `artifact_references`: List of stable S12 artifact_ids.
- `authorization_reference`: Explicit representation of authorization metadata without granting local authority.
- `observations`: List of provenance-aware step outcome observations.
- `outcome`: Strict three-value epistemic outcome (VERIFIED_SUCCESS, VERIFIED_FAILURE, or UNKNOWN).

## 4. N3 Portability Boundary Readiness

To prepare for N3 Portable Work Representation, `SemanticWorkModel.to_dict()` guarantees complete separation between portable semantic state and local machine resources:

| Boundary Category | Elements | Treatment in N2 / N3 |
| --- | --- | --- |
| **Portable** | `work_id`, `intent`, `plan_reference`, `artifact_references`, `observations`, `outcome` | Fully serializable to plain JSON/dict; travels across devices. |
| **Local-Only** | Windows HWND, OS PIDs, live socket descriptors, Playwright browser instances, SQLite DB connections | Excluded from the core model. Represented only as decoupled references or platform details. |

## 5. Verification & Epistemic Guarantees

- `VERIFIED_SUCCESS`: Set only when S18 lifecycle status is COMPLETED and all step verifications succeeded.
- `VERIFIED_FAILURE`: Set when S18 lifecycle status is FAILED or a fatal step failure occurs.
- `UNKNOWN`: Default for in-progress operations (CREATED, RUNNING, PAUSED, CHECKPOINTED, INTERRUPTED) 
   or when evidence is incomplete.
