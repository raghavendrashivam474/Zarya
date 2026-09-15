---

# ZARYA — S13 POST-COMPLETION REPORT

**To:** Senior Development Lead
**From:** S13 Implementation Team
**Date:** September 15, 2026
**Milestone:** S13 — Active Computer Context
**Release:** `v0.13.0` (commit `a2e5005`, tag `v0.13.0`)
**Baseline:** `v0.12.1` (commit `84d99a2`)
**Branch History:** `zarya/s13-active-computer-context` → merged to `main` → branch deleted

---

## 1. EXECUTIVE SUMMARY

Milestone S13 is complete, merged, tagged, and pushed to `origin/main`. The milestone introduces **Active Computer Context** — a deterministic, on-demand desktop observation layer that allows Zarya to answer the question: *"What is currently happening on the computer, and what application/window/artifact is currently relevant to the user's request?"*

**Key metrics:**
- **8 files** created or modified (+1,107 lines)
- **21 new tests** added (all passing)
- **240 total tests** passing (219 baseline + 21 new, 0 failures, 0 regressions)
- **5/5 live desktop smoke stages** verified on a real Windows host
- **Zero architectural breakage** to S1–S12 subsystems
- **Zero external dependencies** added (uses Python stdlib `ctypes` for Win32 API)

---

## 2. PROBLEM STATEMENT

Prior to S13, Zarya's artifact tracking (S12/S12.1) was **logically sequential but physically blind**. The system could track that `notes.txt` was created, opened, and edited across a series of commands. However, it had no mechanism to observe the actual state of the user's desktop. This created several failure modes:

1. **Stale context assumption:** If a user created `notes.txt`, then switched to VS Code to edit a different file, and then said *"save the document"*, Zarya would blindly assume `notes.txt` was still the active target.

2. **No introspection capability:** Queries like *"what app am I using?"* or *"what window is active?"* had no execution path.

3. **No evidence-based grounding:** Deictic references like *"the active document"* or *"the current file"* could not be resolved against real desktop state.

S13 solves all three by providing the **smallest reliable context substrate** connecting live desktop observation to known artifact identities.

---

## 3. ARCHITECTURE & DESIGN DECISIONS

### 3.1 Core Principle

> **S13 does not make Zarya more willing to act; it makes Zarya better informed about the computer before she acts.**

### 3.2 Desktop Observer (`agent/tools/desktop_observer.py`) — NEW FILE

A standalone, observation-only module using Python's `ctypes` stdlib to call Win32 APIs directly:

- `user32.GetForegroundWindow()` — retrieves the active window handle
- `user32.GetWindowTextW()` — retrieves the window title
- `user32.GetWindowThreadProcessId()` — retrieves the owning process ID
- `kernel32.QueryFullProcessImageNameW()` — retrieves the executable name

**Data structures:**
- `WindowObservation`: title, hwnd, process_name, process_id, observed_at, freshness, evidence
- `DesktopObservation`: active_window (optional), observed_at, freshness, error

**Key design constraints:**
- **Observation only.** No window manipulation, no process launching, no input simulation.
- **Point-in-time.** No background threads, no event hooks, no polling loops.
- **Error-safe.** Returns `freshness=UNKNOWN` with an error string instead of raising exceptions.
- **Zero dependencies.** Uses only Python stdlib (`ctypes`, `ctypes.wintypes`).

### 3.3 ActiveComputerContext Extension (`agent/artifacts.py`) — MODIFIED

Extended the existing S12 `ActiveComputerContext` class with additive fields and methods. **No existing methods were modified in their logic.**

**New fields (thread-safe via existing `RLock`):**
- `_active_window_title: Optional[str]`
- `_active_window_process: Optional[str]`
- `_desktop_observed_at: Optional[str]`
- `_desktop_freshness: str` (reuses S3 `StateFreshness` values: `CURRENT` / `UNKNOWN`)

**New read-only properties:**
- `active_window_title`
- `active_window_process`
- `desktop_freshness`

**New methods:**
- `observe_desktop() -> dict`: Calls `desktop_observer`, updates internal state, returns snapshot. This is the single entry point for live observation.
- `get_desktop_snapshot() -> dict`: Returns current state without triggering a new observation.
- `match_artifact_to_window(window_title) -> Optional[ArtifactIdentity]`: Correlates a window title against registered artifacts by checking if any tracked file's basename appears in the title. Returns `None` if zero or multiple matches (prevents guessing).

**Enhanced `resolve_target()`:**
When a deictic reference (e.g., `"the active document"`) is resolved, the method now checks if there is a `CURRENT`-freshness window observation that uniquely matches a tracked artifact. If so, it returns `RESOLVED` with explicit evidence. If not, it falls through to the existing S12.1 sequential fallback chain (active artifact → last verified → last created).

**Extended `PRONOUN_REFERENCES`:**
Added 12 new deictic context phrases:
`"the active document"`, `"active document"`, `"the current document"`, `"current document"`, `"the active file"`, `"active file"`, `"the current file"`, `"current file"`, `"the open file"`, `"open file"`, `"the active window"`, `"active window"`, `"the current window"`, `"current window"`

### 3.4 Registered Tools (`agent/tools/windows.py`) — MODIFIED

Two new tools registered via the existing `@register("toolName")` decorator:

- **`getActiveWindow`**: Observes the foreground window, synchronizes `active_context`, checks for artifact matches, returns a dict with S2 verification payload (`VERIFIED_SUCCESS` or `UNKNOWN`).
- **`getActiveContext`**: Full context snapshot including active application, active window, matched artifact, working directory, freshness, and evidence.

Both tools follow the existing `(args: Dict[str, Any]) -> Dict[str, Any]` signature and include `verification` blocks compatible with S2's verification fabric.

### 3.5 Intent & Validation (`agent/intent.py`) — MODIFIED

**`IntentInterpreter` additions:**
- Two new regex-based pattern blocks at the top of `interpret()` that match natural language queries like:
  - *"What is the active window?"*, *"Get active window"*, *"Check active window"*
  - *"What is the active context?"*, *"What app am I using?"*, *"What am I working on?"*
- These produce single-step `S8WorkPlan` objects targeting `getActiveWindow` or `getActiveContext`.

**`PlanValidator` update:**
- Added `"getActiveWindow"` and `"getActiveContext"` to `DEFAULT_ALLOWED_TOOLS` whitelist. Without this, the validator would reject plans containing these tools as "unregistered/disallowed."

### 3.6 What Was NOT Changed

Per the engineering brief's guardrails, the following were deliberately left untouched:

- `agent/recovery.py` (S5) — No new recovery loops
- `agent/failure.py` (S4) — No new failure taxonomy
- `agent/work.py` (S6) — No new work executor
- `agent/state.py` (S3) — Reused existing freshness enum, no modifications
- `agent/context.py` (S7) — Historical memory remains separate
- `agent/server.py` — No new API endpoints or event bridges
- `server/index.ts` — No WebSocket/SSE changes
- `src/App.tsx`, `src/lib/audio.ts` — No frontend changes
- No LLM-based context interpretation or guessing
- No background monitoring, polling, or surveillance

---

## 4. FILES CHANGED

| File | Status | Lines | Description |
|---|---|---|---|
| `agent/tools/desktop_observer.py` | **NEW** | +163 | Win32 ctypes desktop introspection |
| `agent/artifacts.py` | Modified | +105 | Context state, properties, methods, pronoun extension, window matching |
| `agent/tools/windows.py` | Modified | +108 | `getActiveWindow` and `getActiveContext` tool handlers |
| `agent/intent.py` | Modified | +35 | Desktop query patterns, PlanValidator whitelist |
| `tests/test_s13_active_computer_context.py` | **NEW** | +465 | 21 unit and integration tests |
| `docs/research/s13-active-computer-context-architecture.md` | **NEW** | +92 | ADR and architecture spec |
| `docs/milestones/s13-milestone-signoff.md` | **NEW** | +76 | Formal milestone signoff |
| `docs/research/s13-active-computer-context-post-completion-report.md` | **NEW** | +63 | Post-completion summary |
| **Total** | **8 files** | **+1,107** | |

---

## 5. TEST RESULTS

### 5.1 Quantitative Summary

| Metric | Before S13 | After S13 | Delta |
|---|---|---|---|
| Total tests | 219 | 240 | +21 |
| Passed | 219 | 240 | +21 |
| Failed | 0 | 0 | 0 |
| Errors | 0 | 0 | 0 |

### 5.2 New Test Coverage (`tests/test_s13_active_computer_context.py`)

**Desktop Observer (4 tests):**
1. `test_window_observation_to_dict` — Serialization correctness
2. `test_desktop_observation_available` — Success path data structure
3. `test_desktop_observation_unavailable` — Error path data structure
4. `test_live_observe_active_window` — Real Win32 call on host machine

**ActiveComputerContext State (4 tests):**
5. `test_initial_state` — Freshness starts `UNKNOWN`, all fields `None`
6. `test_observe_desktop_updates_state` — Mocked observation updates all fields
7. `test_clear_resets_s13_state` — `clear()` resets S13 fields
8. `test_get_desktop_snapshot` — Snapshot dict structure and content

**Window-Artifact Association (3 tests):**
9. `test_exact_filename_in_window_title_matches` — `"notes.txt - Notepad"` matches tracked `notes.txt`
10. `test_unrelated_window_title_returns_none` — `"Inbox - Outlook"` returns `None`
11. `test_ambiguous_window_title_returns_none_safely` — Two files with same name returns `None`

**Context Resolution (3 tests):**
12. `test_resolve_active_document_via_window_matching` — `"the active document"` resolves via window evidence
13. `test_resolve_active_window_phrase` — `"the active window"` resolves via window evidence
14. `test_fallback_to_active_artifact_when_no_window_evidence` — `"it"` falls back to S12.1 chain

**Registered Tools (2 tests):**
15. `test_get_active_window_tool_execution` — Tool output structure, S2 verification, context sync
16. `test_get_active_context_tool_execution` — Full snapshot output, working directory, verification

**Intent Interpretation (2 tests):**
17. `test_intent_active_window_queries` — 5 query variants all produce `getActiveWindow` plans
18. `test_intent_active_context_queries` — 5 query variants all produce `getActiveContext` plans

**Work Execution Integration (1 test):**
19. `test_execute_work_get_active_context` — End-to-end S6 work execution with S2 verification

**Disruption & Safety (2 tests):**
20. `test_window_observation_failure_preserves_unknown` — Failed observation keeps `UNKNOWN`
21. `test_historical_memory_does_not_alter_desktop_freshness` — S7 memory does not contaminate S13 state

### 5.3 Live Desktop Smoke Test (5 stages, all passed)

1. **Live Foreground Introspection:** Observed `Antigravity IDE.exe` (PID 17316, hwnd 67014) with `CURRENT` freshness.
2. **Context Synchronization:** `observe_desktop()` updated `ActiveComputerContext` state correctly.
3. **Artifact Association:** Created real temp file, matched against simulated window title, resolved `"the active document"` to the correct canonical locator.
4. **Disruption Protection:** Switched simulated window to `"Terminal - PowerShell"`, confirmed `match_artifact_to_window()` returned `None`.
5. **End-to-End Intent:** `process_natural_intent("What is the active context?", authorized=True)` returned `VERIFIED_SUCCESS`.

---

## 6. GUARDRAIL & SAFETY COMPLIANCE

| Guardrail | Status | Evidence |
|---|---|---|
| No background surveillance | ✅ PASS | No threads, no hooks, no polling. All observation is on-demand via explicit `observe_desktop()` call. |
| No LLM guessing | ✅ PASS | All matching is deterministic string comparison. No LLM calls in the observation or resolution path. |
| S3 freshness reuse | ✅ PASS | Uses `CURRENT` and `UNKNOWN` strings matching `StateFreshness` enum. No competing taxonomy. |
| S2 verification compliance | ✅ PASS | Both tools emit `{"status": "VERIFIED_SUCCESS"|"UNKNOWN", "method": "...", "detail": "..."}` |
| S5 recovery untouched | ✅ PASS | `agent/recovery.py` not modified. No new recovery loops. |
| S7 memory separation | ✅ PASS | Test `test_historical_memory_does_not_alter_desktop_freshness` explicitly verifies this. |
| S12/S12.1 continuity | ✅ PASS | All 219 baseline tests pass. `resolve_target()` falls through to S12.1 chain when no window evidence exists. |
| Privacy boundary | ✅ PASS | No screenshots, no keystrokes, no clipboard, no URL history, no continuous window logging. |
| Ambiguity preservation | ✅ PASS | `match_artifact_to_window()` returns `None` for 0 or >1 matches. Never guesses. |
| Uncertainty preservation | ✅ PASS | Failed observations produce `UNKNOWN`. No fabricated confidence. |

---

## 7. KNOWN LIMITATIONS & FUTURE WORK

1. **Windows-only:** The `desktop_observer.py` module uses Win32 `ctypes` bindings. It will return `UNKNOWN` on Linux/macOS. A future milestone could add `xdotool`/`xprop` (Linux) or `NSWorkspace` (macOS) backends.

2. **Window title parsing is heuristic:** Matching relies on the tracked file's basename appearing in the window title string (e.g., `"notes.txt - Notepad"`). Applications that don't include filenames in their titles will not produce matches. This is by design — we prefer `UNKNOWN` over false positives.

3. **No browser tab introspection:** The brief listed browser context as P1. The current implementation captures the browser process name and window title but does not introspect individual tabs or URLs. This can be layered on in a future milestone using the existing Playwright runtime.

4. **No terminal session context:** Similarly, terminal working directory and session identity are listed as P1 but not yet implemented. The `getActiveContext` tool returns `os.getcwd()` as a basic working directory proxy.

5. **Single-monitor foreground:** `GetForegroundWindow()` returns the single system-wide foreground window. Multi-monitor or virtual desktop awareness is not yet implemented.

---

## 8. RECOMMENDATIONS FOR NEXT MILESTONES

1. **S14 candidate — Browser Context Introspection:** Extend `getActiveContext` to extract active tab URL and title from the existing Playwright browser runtime when the active application is a browser.

2. **S15 candidate — Terminal Session Awareness:** Integrate with `agent/tools/terminal.py` to capture shell working directory and session identity when the active window is a terminal emulator.

3. **Cross-platform observer:** Abstract `desktop_observer.py` behind a backend interface (similar to the existing `get_backend()` pattern in `agent/tools/windows.py`) to support Linux and macOS.

4. **Context freshness decay:** Implement automatic `CURRENT` → `STALE` → `REQUIRES_REFRESH` transitions based on elapsed time since last observation, reusing S3's full freshness lifecycle.

---

## 9. SIGNOFF

**Milestone S13 is complete.** All definition-of-done criteria from the S13 Engineering Brief have been met. The code is merged to `main`, tagged as `v0.13.0`, and pushed to `origin`. The test suite is 100% green with zero regressions. The implementation is additive, safe, and fully backward-compatible with S1–S12.

**Status: APPROVED FOR RELEASE**

---