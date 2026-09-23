# N3 Portable Work Representation — Specification

**Sprint:** N3
**Track:** Work Engine Evolution / Cross-Device Continuity
**Version:** v1.3.0-n3
**Schema Version:** `n3-portable-v1`
**Baseline:** N2 `v1.2.0-n2` (frozen)

---

## 1. Architectural Mission

N3 establishes the **portable representation boundary** for Zarya work. It defines what part of a piece of semantic work can safely leave the current runtime process so that another device or runtime can understand and potentially continue it, without violating process boundaries or leaking sensitive credentials.

```text
N1 UnifiedContext (Environmental Context Snapshot)
│
▼
N2 SemanticWorkModel (Distilled Task Intent, Lifecycle & Outcome)
│
▼
N3 PortableWork (Versioned, Loss-Aware, Platform-Neutral Serialized Package)
│
▼
N4 Cross-Device Work Handoff (Transfer & Negotiation)
│
▼
N5 Flux Connectivity (Wire Transport & Synchronization)
```
---

## 2. Core Invariants & Boundaries

1. **Representation ≠ Transfer:** N3 defines the serialized structure. It does not perform network handoff (N4) or manage wire sockets (N5).
2. **Portable ≠ Resumable:** A serialized `PortableWork` does not guarantee immediate continuation on another node. Resumption is subject to local capability validation and policy.
3. **Portable ≠ Executable:** A receiving device must validate, adapt, and locally authorize the task before executing any tool.
4. **Artifact Reference ≠ Artifact Transfer:** Only stable identity strings (`artifact:file:...`) cross the boundary. Canonical local filesystem paths and binary payloads are stripped.
5. **Authorization Metadata ≠ Authorization Credential:** Policy descriptors and boolean authorization state are preserved; private tokens, session cookies, and API keys are scrubbed.
6. **No Live Runtime Handles:** OS PIDs, HWNDs, window pointers, Playwright objects, and database connections are strictly excluded.

---

## 3. Schema Structure (`n3-portable-v1`)

A serialized `PortableWork` dictionary adheres to the following deterministic JSON-compatible structure:

```json
{
  "format_version": "n3-portable-v1",
  "work": {
    "work_id": "work-abc12345",
    "intent": "Refactor parser module",
    "plan_reference": { ... },
    "outcome": "VERIFIED_SUCCESS | VERIFIED_FAILURE | UNKNOWN"
  },
  "execution": {
    "execution_reference": "op-98765432",
    "lifecycle_status": "RUNNING | COMPLETED | PAUSED | ..."
  },
  "context": {
    "device_reference": "dev-desktop-alpha",
    "platform": "WINDOWS | LINUX | MACOS | ANDROID | UNKNOWN",
    "active_application": "code",
    "page_url": null,
    "page_title": null,
    "artifact_references": [
      "artifact:file:parser_py"
    ],
    "context_reference": "ctx-fedcba98"
  },
  "authorization": {
    "authorized": true,
    "policy": "POLICY_EXPLICIT_STEP"
  },
  "observations": [
    {
      "step_id": "s1",
      "tool": "readFile",
      "outcome": "SUCCESS",
      "timestamp": "2025-05-18T10:00:00Z"
    }
  ],
  "portability": {
    "source_device": "dev-desktop-alpha",
    "created_at": "2025-05-18T10:00:01Z",
    "requirements": [
      "requires_filesystem"
    ]
  }
}
```

## 4. Portability Taxonomy & Field Treatments

| Field Path | Source System | Treatment | Enforcement |
| --- | --- | --- | --- |
| `format_version` | N3 | Required | Must be in SUPPORTED_FORMAT_VERSIONS |
| `work.work_id` | N2 | Preserved | Stable logical work identifier |
| `work.intent` | N2 | Preserved | Goal statement |
| `work.plan_reference` | N2 | Scrubbed | Dict structure preserved; secrets stripped |
| `work.outcome` | N2 | Preserved | 3-valued epistemic state |
| `execution.execution_reference` | S18 via N2 | Preserved | Operation ID string reference |
| `execution.lifecycle_status` | S18 via N2 | Preserved | S18 LifecycleStatus string |
| `context.device_reference` | S17 via N2 | Preserved | Device ID string reference |
| `context.platform` | S17 / N1 | Preserved | Platform string (supports Android) |
| `context.active_application` | S13 / N1 | Preserved | Application name string |
| `context.artifact_references` | S12 via N2 | Preserved | ID list only (canonical_locator scrubbed) |
| `authorization` | S8 / N2 | Scrubbed | Metadata preserved; auth tokens scrubbed |
| `observations` | S18 / N2 | Scrubbed | Runtime PIDs/HWNDs removed from evidence |
| `portability.requirements` | N3 | Preserved | Capability strings for downstream validation |

## 5. Security & Handle Scrubbing Pipeline

The serialization process applies two recursive scrubbing passes:

1. `_strip_secrets(data)`: Traverses all dictionaries and lists, stripping keys containing patterns 
   such as `api_key`, `secret`, `password`, `token`, `credential`, `cookie`.
2. _strip_runtime_locals(data): Striverses all structures, stripping runtime-local keys such as 
   `process_id`, `pid`, `hwnd`, `window_class`, `wm_class`, `wayland`, and `canonical_locator`.