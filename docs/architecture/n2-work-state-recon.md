# N2 Work Context & State Model — Reconnaissance Document

## 1. Executive Summary & Design Goals
The goal of N2 is to establish a formal **work-context/state model** that sits semantically above the existing S18 operational lifecycle. 
It preserves S18 as the authoritative runtime lifecycle machine and N1 as the authoritative environmental context boundary, while providing a clear semantic distinction between:
- **Work Identity** vs. **Operation Identity** vs. **Device Identity** vs. **Artifact Identity**
- **Work Intent** vs. **Implementation Steps/Plan**
- **Observed Environmental Context** vs. **Work-Relevant Context**
- **Cooperative Lifecycle Status** vs. **Semantic Epistemic Outcome** (VERIFIED_SUCCESS, VERIFIED_FAILURE, UNKNOWN)

---

## 2. Existing System Ownership Boundaries

| Concern               | Existing Owner           | N2 Treatment & Relationship |
| --------------------- | ------------------------ | --------------------------- |
| Work Execution        | S6 (`execute_work`)      | Consume & wrap outcomes; do not replace execution. |
| Work Planning         | S8                       | Reference S8-validated plan; do not generate or re-validate. |
| Operational Lifecycle | S18 (`LifecycleStatus`)  | Reference; map status into structural execution views. |
| State Checkpointing   | S18 (`CheckpointStore`)  | Reference checkpoint step and active status. |
| State Resume          | S18 (`resume_work`)      | Reference; run alongside reality check outcomes. |
| Artifact Identity     | S12 (`ArtifactIdentity`)| Reference existing `artifact_id` & `canonical_locator` directly. |
| Device Identity       | S17 (`DeviceIdentity`)  | Reference existing `device_id`. |
| Environmental Context | N1 (`UnifiedContext`)    | Consume via snapshot reference; filter to active relevance. |
| Historical Memory     | S7 (`MemoryStore`)       | Remain strictly separate. |
| Authorization         | S8/S18 auth layer        | Reference authorization state (boolean or token); do not grant authority. |

---

## 3. Core Identity Mapping

To ensure absolute clarity across namespaces, we establish this strict identity taxonomy:

1. **`work_id` (Logical Work)**: Identifies the logical task or user intent (e.g., "Update README.md installation section"). This identity is durable, stable across multiple runs or resumed execution sessions, and corresponds to the top-level task definition.
2. **`operation_id` (Operational Instance)**: Managed by S18, identifying a specific runtime execution attempt of that work on a device. Multiple operations can serve a single logical `work_id` (e.g., if a task is restarted from scratch or split).
3. **`device_id` (Execution Host)**: Managed by S17, identifying the physical or logical machine where the operation is running.
4. **`artifact_id` (Product/Subject)**: Managed by S12, identifying a stable computer entity (e.g., file path, browser tab) that is read, modified, or created during work.
5. **`context_id` (Environmental Snapshot)**: Managed by N1, identifying a point-in-time snapshot of the desktop/browser environment.

---

## 4. Work Intent vs. Work Plan
- **Intent**: The high-level user objective (represented by S18's `goal` string). This remains invariant even if the underlying plan is updated, adapted (S10), or recovered (S5).
- **Plan**: S18's nested `plan` dictionary containing structural steps. The plan is the procedural route to achieve the intent.

---

## 5. Observed Context vs. Work-Relevant Context
N1 provides a complete snapshot of the surrounding environment (`UnifiedContext`). However, not all open applications, window handles, or browser tabs belong to the work.
N2 defines explicit criteria for a context element (application, file, browser URL) to be **Work-Relevant**:
- An **Artifact** is work-relevant if its `artifact_id` is registered in S18 `artifact_ids` or S12 active context history.
- An **Application** is work-relevant if it is the current active tool/process executing a step, or registered as opened by an application-related tool.
- A **Browser URL/Tab** is work-relevant if the active step explicitly references browser-based tools or URLs.

---

## 6. S18 Lifecycle Status vs. N2 Epistemic Outcome
Zarya's epistemic model maintains three core truth values:
- `VERIFIED_SUCCESS`: Verified via S2 assertions to have succeeded.
- `VERIFIED_FAILURE`: Verified via S2 assertions or catastrophic execution failure to have failed.
- `UNKNOWN`: Insufficient evidence to claim success or failure.

N2 translates S18 `LifecycleStatus` and step outcomes into this three-value outcome structure without creating competing state transition machines.

---

## 7. Portable Work Boundaries (N3 Readiness)
To support N3 portability, N2 models must strictly separate **semantic data** from **runtime system resources**.
- **Portable**: Intent string, plan structure, step outcomes, logical artifact IDs, semantic observations, and verified outcome.
- **Local (Non-Portable)**: Database handles, open sqlite3 connections, OS process IDs, Playwright/browser window handles, and live sockets.
