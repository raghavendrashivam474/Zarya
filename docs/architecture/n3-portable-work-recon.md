# N3 Portable Work Representation — Reconnaissance Report

**Sprint:** N3
**Phase:** 0 — Reconnaissance (COMPLETE)
**Baseline:** N2 v1.2.0-n2 (frozen)
**Date:** 2026-09-23

---

## 1. Executive Summary

N3 defines what part of a SemanticWorkModel can safely leave the current
runtime. This report classifies every field from N2, N1, S18, and S12
into portability categories and identifies the gaps N3 must fill.

**Key finding:** N2's to_dict() is already free of live handles. N3's
primary additions are: schema versioning, explicit portability metadata,
runtime-local field exclusion, and loss-aware serialization boundaries.

---

## 2. Portability Taxonomy

### Category Definitions

| Category | Meaning |
|---|---|
| PORTABLE | Another runtime can interpret this without the original process |
| REFERENCE | Identity/pointer that travels, but the live object does not |
| RUNTIME-LOCAL | Must remain on the originating device/process |
| EXCLUDED | Security-sensitive; must never appear in portable output |

---

## 3. N2 SemanticWorkModel Field Classification

| N2 Field | Type | N3 Category | Notes |
|---|---|---|---|
| work_id | str | PORTABLE | Stable logical identity |
| intent | str | PORTABLE | Human-readable goal |
| plan_reference | Dict | PORTABLE | Plan structure, no live handles |
| execution_reference | Optional[str] | REFERENCE | S18 operation_id string only |
| lifecycle_status | str | PORTABLE | Semantic state string (COMPLETED, RUNNING, etc.) |
| context_reference | Optional[str] | REFERENCE | N1 context_id string only |
| relevant_context | Optional[RelevantWorkContext] | MIXED | See Section 4 |
| artifact_references | List[str] | REFERENCE | S12 artifact_id strings only |
| authorization_reference | Optional[Dict] | PORTABLE | Metadata only (authorized + policy), NO credentials |
| observations | List[Dict] | PORTABLE | Provenance-aware step observations |
| outcome | str | PORTABLE | VERIFIED_SUCCESS / VERIFIED_FAILURE / UNKNOWN |

---

## 4. RelevantWorkContext Field Classification

| Field | Type | N3 Category | Notes |
|---|---|---|---|
| device_id | Optional[str] | REFERENCE | S17 device identity string |
| platform | str | PORTABLE | WINDOWS / LINUX / MACOS / ANDROID / UNKNOWN |
| active_application | Optional[str] | PORTABLE | Application name string |
| page_url | Optional[str] | PORTABLE | URL string |
| page_title | Optional[str] | PORTABLE | Title string |
| artifact_ids | List[str] | REFERENCE | S12 artifact identity strings |

---

## 5. N1 UnifiedContext — Fields That Must NOT Travel

N3 consumes N2, not N1 directly. However, N2's derive_semantic_work()
extracts from N1, so we document what N1 contains that is runtime-local.

| N1 Field | N3 Category | Reason |
|---|---|---|
| ComputerContext.process_id | RUNTIME-LOCAL | OS PID, meaningless on another device |
| ComputerContext.process_name | RUNTIME-LOCAL | OS process name |
| ComputerContext.platform_detail | RUNTIME-LOCAL | Contains HWND, window_class, wm_class |
| ComputerContext.window_title | PORTABLE | Semantic string, safe to travel |
| ComputerContext.active_application | PORTABLE | Semantic string |
| BrowserContext (all fields) | PORTABLE | Strings only, no Playwright handles |
| DeviceContext.device_id | REFERENCE | Identity string |
| DeviceContext.platform | PORTABLE | Enum string |
| DeviceContext.device_type | PORTABLE | Enum string |
| ArtifactReference.canonical_locator | RUNTIME-LOCAL | Local filesystem path |
| ArtifactReference.artifact_id | REFERENCE | Identity string |
| ObservationProvenance (all) | PORTABLE | Metadata strings |
| WorkReference (all) | REFERENCE | Identity + status strings |

---

## 6. S18 WorkState — Runtime vs Portable

| S18 Field | N3 Category | Notes |
|---|---|---|
| operation_id | REFERENCE | String identity |
| goal | PORTABLE | Semantic |
| plan | PORTABLE | Dict structure |
| status (LifecycleStatus) | PORTABLE | Enum string value |
| current_step | PORTABLE | Integer |
| total_steps | PORTABLE | Integer |
| completed_steps | PORTABLE | List of StepRecord dicts |
| checkpoint_step | PORTABLE | Integer |
| failure_info | PORTABLE | Dict or None |
| interruption_info | PORTABLE | Dict or None |
| artifact_ids | REFERENCE | String list |
| device_id | REFERENCE | String |
| created_at / updated_at | PORTABLE | ISO timestamps |

**Finding:** S18 WorkState contains ZERO live handles. It is already
safe for serialization. N3 does not need to filter S18 data — N2
already distilled it.

**CheckpointStore** uses SQLite + json.dumps(to_dict()) for LOCAL
persistence. N3 is a different boundary (cross-device representation).
N3 must NOT duplicate or replace S18 checkpointing.

---

## 7. S12 ArtifactIdentity — Critical Boundary

| S12 Field | N3 Category | Notes |
|---|---|---|
| artifact_id | REFERENCE | The ONLY field that travels |
| artifact_type | PORTABLE | Semantic category |
| canonical_locator | RUNTIME-LOCAL | Absolute filesystem path, device-specific |
| display_name | PORTABLE | Human-readable |
| source_operation | PORTABLE | Semantic |
| verification_status | PORTABLE | Semantic |
| metadata | PORTABLE | Dict, but must be audited for secrets |

**Critical:** N3 must carry artifact_id references ONLY. Never
canonical_locator. Artifact content transfer belongs to N4/N5.

---

## 8. Security-Sensitive Information (EXCLUDED)

The following must NEVER appear in PortableWork output:

- API keys, tokens, passwords
- Session cookies, browser cookies
- Authorization credentials (authorization_reference carries metadata only)
- Private keys, local credentials
- Environment secrets
- SQLite connection strings
- Any field from ComputerContext.platform_detail (may contain handles)

---

## 9. Existing Serialization Conventions

| Pattern | Used By | Notes |
|---|---|---|
| to_dict() -> Dict | N1, N2, S18, S12 | Universal convention |
| from_dict(cls, data) | S18 WorkState, StepRecord | Deserialization |
| dataclasses.asdict() | N1 _frozen_to_dict, S12 | Deep conversion |
| json.dumps(data, default=str) | S18 CheckpointStore | Local persistence |
| format_version / schema | NONE | **N3 introduces the first** |

---

## 10. Gaps N3 Must Fill

1. **Schema versioning** — No format_version exists anywhere in the repo
2. **Portability metadata** — source_device, created_at, requirements
3. **Loss-aware serialization** — Explicit handling of excluded/local fields
4. **Runtime-local field filtering** — ComputerContext.process_id, HWND, etc.
5. **Artifact locator stripping** — canonical_locator must not leak
6. **Secret exclusion validation** — Active verification, not just omission
7. **Android/platform neutrality** — Verified by N2 tests, N3 must preserve
8. **Deterministic output** — Same input -> same serialized representation

---

## 11. What N3 Does NOT Do

- Move work between devices (N4)
- Establish connectivity (N5/Flux)
- Transfer artifact content (N4/N5)
- Resume execution (S18 + N4)
- Authorize execution on receiving device (local policy)
- Replace N2 SemanticWorkModel
- Replace S18 lifecycle or checkpoints
- Integrate with Shyam or Flux

---

## 12. Recommended N3 Architecture

```text
SemanticWorkModel (N2, frozen)
|
v
PortableWork (N3, new)
├── format_version: "n3-portable-v1"
├── work: { work_id, intent, plan_reference, outcome }
├── execution: { execution_reference, lifecycle_status }
├── context: { device_id, platform, application, browser, artifacts }
├── authorization: { metadata only, NO credentials }
├── observations: [...]
└── portability: { source_device, created_at, requirements }
|
v
to_portable_dict() -> JSON-compatible Dict
|
v
from_portable_dict(data) -> PortableWork (with validation)
```
---

## 13. Next Steps (Phase 1+)

- [x] Phase 0: Reconnaissance (this document)
- [ ] Phase 1: Portability taxonomy (this document, Section 3-7)
- [ ] Phase 2: PortableWork model (agent/context/portable_work.py)
- [ ] Phase 3: Serializer/deserializer with version validation
- [ ] Phase 4: Comprehensive test suite
- [ ] Phase 5: Full regression
