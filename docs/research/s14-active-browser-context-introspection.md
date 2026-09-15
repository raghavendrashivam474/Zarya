# S14 — Active Browser Context Introspection Architecture

## 1. Architectural Overview

Zarya’s Active Computer Context (`ActiveComputerContext` in `agent/artifacts.py`) models the operating state of the host. Prior milestones mapped the foreground application process name and window title (S13) and tracked workspace file artifact logic (S12/S12.1). 

**S14 extends this hierarchy dynamically:** when the active window corresponds to a recognized web browser, Zarya introspects the internal state of the **existing** Playwright browser runtime. She identifies the active tab, captures the active webpage’s URL and title, and exposes this context cleanly through `getActiveContext`.
```text

                +------------------------------------+
                |        S13 OS FOREGROUND           |
                |       WindowObservation            |
                +-----------------+------------------+
                                  |
                       Is active app a browser?
                                  |
                 +----------------v------------------+
                 |       S14 BROWSER OBSERVER        |
                 +----------------+------------------+
                                  |
                  Inspects STATE in browser.py
                                  |
          +-----------------------+-----------------------+
          |                                               |
    Single Page?                                     Multi-Tab?
          |                                               |
 [VERIFIED_SUCCESS]                            Match OS Window Title?
 Return URL/Title                                         |
                                        +-----------------+-----------------+
                                        |                                   |
                                   Unique Match?                     Ambiguous/No Match?
                                        |                                   |
                               [VERIFIED_SUCCESS]                       [UNKNOWN]
                               Return URL/Title                   "ambiguous_multi_tab"
```


---

## 2. Core Integration Rules & System Boundaries

### Rule 2.1: Observation-Only / Read-Only Lifecycle
S14 browser context extraction is strictly **passive and synchronous**. 
* It **never** invokes `_ensure_browser_async()` or launches/starts a browser process on-demand solely to satisfy a context query.
* It **never** automatically navigates, clicks, extracts cookie/storage/credential structures, or modifies page structures.
* It performs a simple point-in-time state read of existing memory, remaining completely silent in the background.

### Rule 2.2: Event Loop Thread-Safety
The Playwright runtime inside Zarya runs on a dedicated background thread-loop managed by `browser.py` to prevent event-loop deadlocks caused by concurrent calls or blockages in asynchronous coroutines. 
S14 uses the identical `_run()` bridge to dispatch thread-safe metadata coroutines (`_inspect_pages()`) into the background loop, maintaining robust execution boundaries.

---

## 3. The Active Tab Problem & Multi-Tab Disambiguation

Determining which tab is active within a browser process is notoriously unreliable using Playwright primitives alone because:
1. Playwright maintains an array of `pages` representing open tabs, but **does not** expose an OS-level "is_visible_tab" property.
2. The last-created page or last-navigated page (`pages[-1]`) is often not the tab currently focused by the user.

### 3.1 Resolving Tab Ambiguity Deterministically
S14 implements an **evidence-based window correlation algorithm** to determine active page state safely:

1. **Window Title Extraction (S13):** The OS foreground tracker records the exact window title of the browser (e.g. `Angular - Google Chrome`).
2. **Tab Title Gathering (S14):** S14 gathers the page title and URL of every open page concurrently in the Playwright context.
3. **Correlation Match:**
   * **Case A: Single Page:** If exactly one page/tab exists in the runtime, it is assumed active. Status: `VERIFIED_SUCCESS`, Evidence: `single_live_page`.
   * **Case B: Unique Title Match:** If multiple tabs are open, Zarya compares the clean titles of each tab with the OS foreground window title. If exactly one tab's title is a substring or start of the OS window title, that tab is uniquely identified. Status: `VERIFIED_SUCCESS`, Evidence: `playwright_window_title_match`.
   * **Case C: Duplicates / Ambiguity:** If multiple tabs share identical titles, or if no tabs match the OS foreground window title, Zarya declines to guess. Status: `UNKNOWN`, Evidence: `ambiguous_duplicate_page_titles` or `ambiguous_multi_tab`.

This deterministic strategy guarantees Zarya **never operates on a stale or wrong tab** during contextual execution.

---

## 4. Security & Privacy Boundaries

To preserve user privacy and maintain system trust, S14 enforces strict boundaries:
* **No continuous background monitoring:** Browser context is only collected on-demand when `getActiveContext` is executed or naturally queried.
* **No logging of URL histories:** No database persists user surfing actions over time. S7's historical storage only tracks execution outcomes, never background browser activity.
* **Sensitive Page Exclusions:** All credentials, cookies, browser vaults, local storage, clipboard state, and iframe contexts remain entirely inaccessible to the observation module.

---

## 5. Contract Conformance (S14 JSON Schema)

When querying `getActiveContext` while Chrome is the focused foreground application with `angular.dev` open:

```json
{
  "active_application": "chrome.exe",
  "active_window": "Angular - Google Chrome",
  "active_artifact": null,
  "working_directory": "C:\\Users\\ragha\\Documents\\Anti-grav\\Zarya",
  "browser": {
    "browser_name": "Chrome",
    "page_url": "https://angular.dev/",
    "page_title": "Angular",
    "observed_at": "2026-09-15T04:31:01.294541+00:00",
    "freshness": "CURRENT",
    "evidence": "playwright_window_title_match",
    "status": "VERIFIED_SUCCESS"
  },
  "freshness": "CURRENT",
  "observed_at": "2026-09-15T04:31:01.294541+00:00",
  "evidence": "win32_ctypes",
  "verification": {
    "status": "VERIFIED_SUCCESS",
    "method": "active_context_snapshot",
    "detail": "Active app: chrome.exe, Window: Angular - Google Chrome"
  }
}

If Notepad is the active foreground application:

```JSON

{
  "active_application": "notepad.exe",
  "active_window": "notes.txt - Notepad",
  "active_artifact": "notes.txt",
  "working_directory": "C:\\Users\\ragha\\Documents\\Anti-grav\\Zarya",
  "browser": null,
  "freshness": "CURRENT",
  "observed_at": "2026-09-15T04:31:01.294541+00:00",
  "evidence": "win32_ctypes",
  "verification": {
    "status": "VERIFIED_SUCCESS",
    "method": "active_context_snapshot",
    "detail": "Active app: notepad.exe, Window: notes.txt - Notepad"
  }
}
```
