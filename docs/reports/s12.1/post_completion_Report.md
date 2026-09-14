# Post-Implementation Report: S12.1 — Artifact Continuity Hardening

**To:** Senior Developer
**From:** Junior Developer
**Date:** 2025-07-14
**Milestone:** S12.1 — Artifact Continuity Hardening
**Parent Milestone:** S12 — Artifact Identity & Computer Context Continuity
**Baseline:** `a8f3076` (S12 signoff)
**Release Tag:** `v0.12.1`
**Branch:** Merged to `main` via `dc9864e`

---

## 1. Executive Summary

S12.1 was a hardening sprint, not a feature sprint. The goal was to fix five specific issues identified during your senior review of S12 while preserving the entire S0–S12 foundation intact.

**All five review findings have been addressed.** The full test suite (219 tests) passes with zero regressions. A live desktop golden workflow was validated against real Windows Notepad and the real filesystem. The branch has been merged to `main` and tagged `v0.12.1`.

The most critical fix was restoring S6 verification continuation semantics that S12 had accidentally relaxed. The most architecturally significant fix was replacing the fragile `"create" in tool_name` string heuristic with explicit operation category sets.

---

## 2. Investigation Findings

### 2.1 S6 Verification Semantics Drift (P0 — Critical)

**What I found:** In `agent/intent.py`, the `S8WorkPlan.to_s6_plan()` method contained a hardcoded check that automatically set `unverified_ok=True` for five observation tools:

```python
"unverified_ok": step.tool in (
    "readFile",
    "listFiles",
    "searchFiles",
    "systemInfo",
    "takeScreenshot",
),
```

This meant that any `S8WorkPlan` containing a `readFile` step would silently bypass S6's strict epistemic gate. The `readFile` tool has no S2 verification envelope (it reads content but doesn't produce a `VERIFIED_SUCCESS` / `VERIFIED_FAILURE` payload), so under correct S6 semantics it should evaluate as `UNKNOWN` unless the caller explicitly opts into `unverified_ok=True`.

**Root cause:** During S12 development, the author likely needed `readFile` steps to pass in end-to-end tests and took the shortcut of blanket-enabling `unverified_ok` for all observation tools at the plan translation layer, rather than setting it explicitly on individual steps that needed it.

**Impact:** This violated the core S8/S9 truth-preservation invariant. A `readFile` step that returned no verification data was being reported as `VERIFIED_SUCCESS` to the user, which is epistemically dishonest.

### 2.2 Fragile Artifact Creation Heuristic (P0)

**What I found:** In `agent/artifacts.py`, the `record_artifact()` method determined whether an artifact was "created" (and thus should update `_last_created_artifact`) using this check:

```python
if "create" in artifact.source_operation.lower():
    self._last_created_artifact = artifact
```

**Root cause:** Quick heuristic during S12 prototyping that was never replaced with explicit semantics.

**Impact:** Any tool whose name happened to contain the substring "create" (e.g., a hypothetical `recreateBackup` or `createThumbnail`) would incorrectly trigger the `last_created_artifact` update. Conversely, a tool that genuinely creates artifacts but doesn't have "create" in its name (e.g., `downloadFile`, `exportFile`, `saveAs`) would be silently missed.

### 2.3 Active Context Lifecycle (P0)

**What I found:** `ActiveComputerContext` was instantiated as a module-level global singleton (`active_context = ActiveComputerContext()`) and imported directly by `agent/intent.py`, `agent/work.py`, `agent/tools/files.py`, `agent/tools/applications.py`, and `agent/tools/coding.py`.

The class already had a `clear()` method and a `threading.RLock`, which was good. However:
- There was no explicit `reset()` method for standardized lifecycle boundaries.
- `execute_work()` and `_interpolate_step_args()` had no mechanism to accept a scoped context, meaning all work execution was permanently coupled to the global singleton.
- There was no documentation of the intended lifecycle (process? session? request?).

**Root cause:** S12 was designed for single-session operation, which is the current Zarya runtime model. The global singleton is architecturally correct for the current runtime but lacked the seams needed for future session isolation.

**Impact:** No immediate bug in the current single-session runtime, but any future multi-session or concurrent-work architecture would silently leak artifact context across independent operations.

### 2.4 Rename/Move Identity Discontinuity (P0)

**What I found:** When `renameFile` or `moveFile` executed, `update_from_tool_response()` treated them identically to `createFile` — it generated a brand-new `ArtifactIdentity` with a new `artifact_id` derived from the new path. The original artifact (with the old path) remained in the `_artifacts` dictionary as a stale entry.

**Root cause:** The `update_from_tool_response()` method had a single code path for all file tools that always called `ArtifactIdentity.create_file_artifact()`, which generates a deterministic ID from the canonical locator. Since the locator changed after rename/move, the ID changed.

**Impact:** After renaming `A.txt` to `B.txt`, resolving "it" would return the new `B.txt` artifact (because it was set as active), but the logical connection to the original `A.txt` was lost. The `previous_locators` history was empty, and the old artifact entry was orphaned.

### 2.5 Desktop Validation Gap (P0)

**What I found:** S12's golden workflow test (`test_golden_workflow_end_to_end`) used mocked backends for `openApplication` and asserted `OUTCOME_VERIFIED_SUCCESS` for a `readFile` step (which, as noted in 2.1, was only passing because of the `unverified_ok` override). No real desktop validation had been performed.

---

## 3. Changes Implemented

### 3.1 `agent/intent.py` — S6 Verification Restoration

**Commit:** `7693f2f` — `fix(s12.1): restore existing verification continuation semantics`

**Changes:**
- Added `unverified_ok: bool = False` field to the `S8Step` dataclass.
- Replaced the hardcoded tool-name check in `S8WorkPlan.to_s6_plan()` with `step.unverified_ok`.
- All observation tools now default to `unverified_ok=False`, restoring strict S6 semantics.
- Callers that genuinely need `unverified_ok=True` (e.g., the existing S12 test for `readFile` with `$ACTIVE_ARTIFACT`) must set it explicitly on the `S8Step`.

**Lines changed:** +2, -7 (net reduction in code).

### 3.2 `agent/work.py` — Scoped Context Injection

**Commit:** `d3a97eb` — `fix(s12.1): harden active artifact context lifecycle`

**Changes:**
- Added `context: Optional[Any] = None` parameter to `execute_work()`.
- Added `context: Optional[Any] = None` parameter to `_interpolate_step_args()`.
- Inside `execute_work()`, bound `ctx = context or active_context` and passed it to both `_interpolate_step_args()` and `ctx.update_from_tool_response()`.
- All existing callers continue to work unchanged (default falls back to the global `active_context`).
- Tests and future multi-session architectures can now pass an isolated `ActiveComputerContext` instance.

**Lines changed:** +9, -5.

### 3.3 `agent/artifacts.py` — Explicit Semantics & Identity Preservation

**Commit:** `067de5e` — `refactor(s12.1): make artifact establishment explicit`

**Changes:**

**Operation Categories:**
- Defined three immutable `frozenset` constants at module level:
  - `ARTIFACT_CREATING_OPERATIONS`: `createFile`, `createPythonFile`, `writeCodeFile`, `copyFile`, `downloadFile`, `exportFile`, `saveAs`, `duplicateFile`, `extractFile`.
  - `ARTIFACT_MUTATING_OPERATIONS`: `renameFile`, `moveFile`, `appendFile`, `editFile`.
  - `ARTIFACT_READING_OPERATIONS`: `readFile`, `listFiles`, `searchFiles`, `openApplicationTarget`, `explicitReference`.
- Replaced `"create" in artifact.source_operation.lower()` with `artifact.source_operation in ARTIFACT_CREATING_OPERATIONS`.

**Identity Preservation:**
- Rewrote `update_from_tool_response()` to handle four distinct operation categories:
  1. **Mutating operations** (`renameFile`, `moveFile`): Looks up the existing artifact by the old canonical locator. If found, updates `canonical_locator`, `display_name`, `last_verified_at`, and appends the old locator to `metadata["previous_locators"]` — all in-place on the same `ArtifactIdentity` object. The `artifact_id` is preserved.
  2. **Creating operations** (`createFile`, etc.): Creates a new `ArtifactIdentity` only if verification succeeded or the operation completed without explicit failure.
  3. **Reading operations** (`readFile`): Updates `_active_artifact` to the read target but does NOT update `_last_created_artifact`. If the file is already tracked, reuses the existing identity.
  4. **Application operations** (`openApplication`): Preserves existing file target identity if the opened target is already tracked, rather than creating a duplicate.

**Lifecycle:**
- Added `reset()` method as an explicit alias for `clear()`, providing a standardized lifecycle boundary for session resets and test isolation.
- Added docstrings to `_active_artifact`, `_last_created_artifact`, and `_last_verified_artifact` defining their precise semantics.

**Lines changed:** +148, -18.

### 3.4 `tests/test_s12_artifact_identity.py` — S6 Alignment

**Commit:** `2c594cc` — `test(s12.1): cover artifact continuity edge cases`

**Changes:**
- Added `OUTCOME_UNKNOWN` to imports from `agent.work`.
- Updated `test_golden_workflow_end_to_end` to assert `OUTCOME_UNKNOWN` for the `readFile` step, reflecting the restored S6 semantics. The test still verifies that the actual disk content matches the expected edited content, so the functional correctness of the golden workflow is fully validated.

### 3.5 `tests/test_s12_1_hardening.py` — New Hardening Suite

**Commit:** `2c594cc` — `test(s12.1): cover artifact continuity edge cases`

**New file with 11 tests across 6 test classes:**

| Test Class | Tests | What They Verify |
|---|---|---|
| `TestS12_1_VerificationSemantics` | 2 | `S8WorkPlan.to_s6_plan()` does not force `unverified_ok=True`; explicit `unverified_ok=True` is preserved |
| `TestS12_1_ContextScopeAndIsolation` | 2 | Independent contexts don't leak; `reset()` clears all tracking |
| `TestS12_1_ExplicitArtifactSemantics` | 2 | `readFile` updates active but not `last_created`; `VERIFIED_FAILURE` doesn't manufacture verified artifacts |
| `TestS12_1_RenameAndMoveContinuity` | 2 | Rename preserves `artifact_id` and records `previous_locators`; Move preserves identity across directories |
| `TestS12_1_TargetResolutionContinuity` | 2 | Ambiguous references return `AMBIGUOUS`; missing references return `NOT_FOUND` |
| `TestS12_1_GoldenContinuityWorkflow` | 1 | End-to-end `CREATE → READ $ACTIVE_ARTIFACT` with target continuity verified |

### 3.6 `scripts/smoke_s12_1_desktop.py` — Live Desktop Validation

**Commit:** `35c316b` — `test(s12.1): add desktop golden workflow coverage`

**What it does:**
1. Creates `s12-test.txt` in a temp directory via `process_natural_intent("create a file called ...")`.
2. Verifies the active artifact's canonical locator matches the real filesystem path.
3. Opens the file in real Notepad via `process_natural_intent("open it in notepad")`.
4. Appends content via `process_natural_intent("add '...' in it")`.
5. Reads the file and verifies exact disk content matches expected string.
6. Cleans up the Notepad process and temp directory.

**Result:** All 6 steps passed on the live Windows development environment.

### 3.7 Documentation

**Commit:** `6f7fec4` — `docs(s12.1): document artifact continuity hardening`

- `docs/research/s12.1-artifact-continuity-hardening.md`: Investigation findings, architectural decisions, and epistemic safety verification.
- `docs/research/s12.1-artifact-continuity-limitations.md`: Current scope boundaries and intentional limitations.
- `docs/milestones/s12.1-milestone-signoff.md`: Acceptance criteria checklist with verification details.

---

## 4. Verification Results

### 4.1 Full Regression Suite

```
219 passed in 10.94s
```

Zero failures. Zero regressions. All S0–S12 tests remain green.

The only pre-existing flaky test is `test_desktop_browser_open_youtube_video_url` in `tests/test_browser_runtime.py`, which fails intermittently due to Playwright `TargetClosedError` when the browser context closes before navigation completes. This is a pre-existing S10-era issue unrelated to S12.1.

### 4.2 S12.1 Hardening Suite

```
11 passed in 0.28s
```

### 4.3 S12 Original Suite

```
14 passed in 0.37s
```

### 4.4 Live Desktop Smoke

```
✅ S12.1 REAL DESKTOP GOLDEN VALIDATION SUCCEEDED COMPLETELY
```

All 6 steps (CREATE → VERIFY CONTEXT → OPEN → EDIT → READ & VERIFY DISK → CLEANUP) passed against real Windows Notepad and real NTFS filesystem.

---

## 5. Architectural Decisions

### 5.1 No ADR Required

Per the brief's guidance ("Only create an ADR if we actually cross an architectural boundary"), no ADR was created. The changes are hardening corrections within the existing S12 architecture, not new architectural layers.

### 5.2 Global Singleton Retained

The `active_context = ActiveComputerContext()` global singleton was **not** replaced. Investigation confirmed that the current Zarya runtime is intentionally single-session and single-threaded for user-facing work execution. The global singleton is the correct pattern for this runtime model.

Instead, I added the `context` parameter injection seam to `execute_work()` and `_interpolate_step_args()`, which allows future multi-session architectures to pass isolated contexts without modifying the global default. This is the smallest safe mechanism that addresses the concern without over-engineering.

### 5.3 Operation Categories as `frozenset`

The operation category constants are `frozenset` instances at module level, not enums or classes. This was a deliberate choice:
- `frozenset` provides O(1) membership testing.
- It's immutable, preventing accidental runtime modification.
- It's the simplest mechanism that replaces the string heuristic without introducing a new type hierarchy.
- If the set of artifact-producing tools grows, adding a string to a `frozenset` is a one-line change.

### 5.4 In-Place Identity Mutation for Rename/Move

When a file is renamed or moved, the existing `ArtifactIdentity` object is mutated in-place rather than creating a new identity and linking them. This was chosen because:
- The `artifact_id` is derived from the canonical locator, so a new identity would have a different ID, breaking the "same logical artifact" invariant.
- The `_artifacts` dictionary is keyed by `artifact_id`, so a new identity would orphan the old entry.
- In-place mutation with `previous_locators` history provides both continuity and auditability.

The tradeoff is that `ArtifactIdentity` is technically mutable after creation, which slightly weakens the "identity" concept. However, the `artifact_id` itself remains stable, and the mutation is confined to locator/display metadata.

---

## 6. What Was NOT Changed

Per the brief's explicit prohibitions, the following were verified as untouched:

- **S2 verification statuses** (`VERIFIED_SUCCESS`, `VERIFIED_FAILURE`, `UNKNOWN`): Meanings unchanged.
- **S3 state model** (`StateObservation`, `StateFreshness`, `StateCache`): No modifications.
- **S4 failure taxonomy**: No new failure categories introduced.
- **S5 recovery authority**: No retry/recovery logic added to artifact context.
- **S6 `WorkPlan`/`WorkResult`**: Structure unchanged; only the `unverified_ok` default was corrected.
- **S7 `MemoryStore`**: Active context was not moved into persistent memory.
- **S8 natural intent parsing**: No LLM-based coreference introduced; deterministic resolution preserved.
- **S10 adaptive work**: Bounded adaptation behavior unchanged.
- **S10.5/S11 runtime events**: No new artifact events introduced.
- **API compatibility**: All existing `/execute` and `/intent` payloads remain compatible. No fields were removed or renamed.

---

## 7. Remaining Limitations

1. **Single active target per type:** The context tracks one `_active_artifact` and one `_active_application`. Multi-document concurrent work (e.g., editing 5 files simultaneously) resolves "it" to the most recently touched artifact. This is acceptable for the current single-session runtime but will need enhancement for multi-workspace scenarios.

2. **Ephemeral in-memory lifecycle:** Active context does not survive process restarts. Long-term provenance is S7's domain.

3. **No out-of-band change detection:** If an external process modifies or moves a tracked file outside Zarya's tool envelope, the active context will not detect the change until the next Zarya tool operation touches that file.

4. **No deep GUI window tracking:** Application launching validates process spawn and arguments. Window handle state and UI tree inspection remain out of scope.

5. **`readFile` verification gap:** `readFile` does not produce an S2 verification envelope. This is architecturally correct (reading is observation, not action), but it means `readFile` steps will always evaluate as `UNKNOWN` under strict S6 semantics unless `unverified_ok=True` is explicitly set. This is the truthful behavior, but it may surprise users who expect "I read the file successfully" to count as verified success. This is a design discussion for S13, not a bug.

---

## 8. Recommendations for S13

Based on the S12.1 investigation, the following areas are ready for S13 consideration:

1. **Active Computer Context as a first-class S13 module:** S12 established artifact identity; S13 can now build the broader "active computer context" layer (active windows, active browser tabs, active terminal sessions) on top of the hardened S12.1 foundation without inheriting unfinished S12 work.

2. **`readFile` verification envelope:** Consider whether `readFile` should produce a lightweight S2 verification payload (e.g., `VERIFIED_SUCCESS` if the file was successfully read and content returned). This would eliminate the need for `unverified_ok=True` on read steps and make the golden workflow fully `VERIFIED_SUCCESS` end-to-end.

3. **Multi-target context:** If S13 introduces multi-workspace or multi-session support, the `context` parameter injection seam added in S12.1 is ready to be used for session-scoped `ActiveComputerContext` instances.

4. **Out-of-band change detection:** Consider a lightweight filesystem watcher or periodic staleness check for active artifacts, building on S3's `StateFreshness` model.

---

## 9. Commit Timeline

```
dc9864e (HEAD -> main, tag: v0.12.1) Merge milestone S12.1: Artifact Continuity Hardening
6f7fec4 docs(s12.1): document artifact continuity hardening
35c316b test(s12.1): add desktop golden workflow coverage
2c594cc test(s12.1): cover artifact continuity edge cases
067de5e refactor(s12.1): make artifact establishment explicit
d3a97eb fix(s12.1): harden active artifact context lifecycle
7693f2f fix(s12.1): restore existing verification continuation semantics
fc1346b (tag: v0.12.0) Merge milestone S12: Artifact Identity & Computer Context Continuity
```

---

## 10. Definition of Done Checklist

| Requirement | Status |
|---|---|
| Artifact identity separate from state | ✅ |
| Artifact identity separate from historical memory | ✅ |
| Concrete target survives multi-step work | ✅ |
| Rename preserves logical identity | ✅ |
| Move preserves logical identity | ✅ |
| Active context lifetime explicitly defined | ✅ |
| Context cannot leak across isolated boundaries | ✅ |
| Context can be safely reset | ✅ |
| S6 verification semantics unchanged | ✅ |
| `unverified_ok` not silently broadened | ✅ |
| FAILED operations cannot create false verified artifacts | ✅ |
| UNKNOWN remains UNKNOWN | ✅ |
| Known target resolves deterministically | ✅ |
| Ambiguous target requests clarification | ✅ |
| Missing target requests clarification | ✅ |
| No filesystem guessing/scanning | ✅ |
| Golden workflow CREATE→OPEN→EDIT→SAVE→VERIFY | ✅ |
| Full pytest suite passes (219/219) | ✅ |
| S0–S11 tests remain green | ✅ |
| No API compatibility break | ✅ |
| No S5/S6/S7 semantic regression | ✅ |
| Investigation documented | ✅ |
| Limitations documented | ✅ |
| Signoff documented | ✅ |
| Real desktop golden workflow passes | ✅ |
| Actual canonical path confirmed | ✅ |
| Actual saved artifact verified from disk | ✅ |
| Working tree clean | ✅ |
| Branch merged and tagged | ✅ |

---

**S12.1 is complete. S13 can cleanly begin as Active Computer Context without inheriting unfinished S12 work.**