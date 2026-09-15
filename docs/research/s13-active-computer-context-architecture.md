# S13 — Active Computer Context Architecture Specification & ADR

**Milestone:** S13 — Active Computer Context  
**Baseline:** `v0.12.1` (`84d99a2`)  
**Status:** COMPLETE & VERIFIED  

---

## 1. Problem Statement & Motivation

Prior to S13, Zarya could track logical artifact identities and mutations (S12 / S12.1) across sequential commands (e.g. *create notes.txt* -> *open it in notepad* -> *read it*). However, Zarya lacked **live situational awareness of the physical computer screen**:
- When a user switched applications or windows, Zarya had to rely on last-created or last-verified artifact assumptions.
- If the user said *"read the active document"* or *"what app am I using?"*, Zarya had no deterministic mechanism to introspect foreground windows.

**S13 solves this by providing the smallest, reliable, deterministic active computer context substrate that connects live desktop observations with known artifact identities without compromising trust or privacy.**

---

## 2. Architecture Decision Record (ADR)

### Context & Requirements
1. **Additive Design**: Must build upon S2 (Verification Fabric), S3 (State & Freshness), and S12/S12.1 (Artifact Identity & Continuity).
2. **Zero Surveillance / Privacy Boundary**: No continuous background recording, no background window hooks, no keystroke loggers. Observations are strictly **on-demand (point-in-time)** when a task or query requires it.
3. **Evidence-Based Association**: Window titles and process names are treated as empirical evidence, not absolute assumptions. If title matching is ambiguous (multiple files with same name), resolution returns `None` / `AMBIGUOUS` rather than guessing.
4. **Historical Separation**: S7 persistent memory must never be conflated with S13 current desktop state.

### Design Decisions
- **`agent/tools/desktop_observer.py`**:
  - Implements lightweight, stdlib Win32 API calls via `ctypes` (`user32.GetForegroundWindow`, `user32.GetWindowTextW`, `kernel32.QueryFullProcessImageNameW`).
  - Emits `WindowObservation` and `DesktopObservation` dataclasses capturing window title, window handle (`hwnd`), process name, PID, timestamp, S3 freshness (`CURRENT` / `UNKNOWN`), and explicit evidence string.
- **`ActiveComputerContext` Integration (`agent/artifacts.py`)**:
  - Added properties: `active_window_title`, `active_window_process`, `desktop_freshness`.
  - Added methods: `observe_desktop()`, `get_desktop_snapshot()`, `match_artifact_to_window()`.
  - Extended `PRONOUN_REFERENCES` to recognize deictic context terms: `"the active document"`, `"active document"`, `"the current document"`, `"the active file"`, `"the current file"`, `"the open file"`, `"the active window"`.
  - Enhanced `resolve_target()` to evaluate live active window title evidence against tracked artifacts with `CURRENT` freshness before falling back to sequential active artifact identity.
- **Tools & Natural Intent (`agent/tools/windows.py` & `agent/intent.py`)**:
  - Registered `getActiveWindow` and `getActiveContext` with S2 verification contracts (`VERIFIED_SUCCESS` / `UNKNOWN`).
  - Whitelisted in `PlanValidator`.
  - Extended `IntentInterpreter` to parse natural language queries (*"What is the active window?"*, *"What app am I using?"*, *"What is the active context?"*).

---

## 3. Context Lifecycle & Freshness Rules

```text
                      +-----------------------------+
                      |   Session Start / Reset     |
                      | desktop_freshness = UNKNOWN |
                      +--------------+--------------+
                                     |
                                     | On-Demand Observation
                                     v
                      +-----------------------------+
                      |      observe_desktop()      |
                      |  GetForegroundWindow Win32  |
                      +--------------+--------------+
                                     |
                  +------------------+------------------+
                  |                                     |
       [Success: Valid HWND]                 [Failure / Error]
                  |                                     |
                  v                                     v
     +-------------------------+           +-------------------------+
     | desktop_freshness:      |           | desktop_freshness:      |
     |        CURRENT          |           |        UNKNOWN          |
     | active_window_title     |           | error message recorded  |
     | active_window_process   |           +-------------------------+
     +------------+------------+
                  |
                  | match_artifact_to_window()
                  v
     +---------------------------------------------+
     | Match unique tracked artifact by filename?  |
     +--------------------+------------------------+
                          |
             +------------+------------+
             |                         |
      [Single Match]             [0 or >1 Match]
             |                         |
             v                         v
     +---------------+         +---------------+
     |   RESOLVED    |         | UNKNOWN /     |
     | with evidence |         | AMBIGUOUS     |
     +---------------+         +---------------+
```

## 4. Verification & Regression Metrics

- Baseline Tests: 219 passed
- New S13 Tests: 21 passed
- Total Suite: 240 passed (0 failures, 0 errors, 100% green)
- Live Desktop Smoke: 5/5 stages verified on real Windows desktop host
