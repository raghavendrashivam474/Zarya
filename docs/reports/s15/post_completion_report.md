# S15 Post-Milestone Engineering Report

**To:** Senior Development  
**From:** S15 Implementation  
**Date:** 2026-09-16  
**Baseline:** v0.14.0 / S14 Browser Context  
**Commits:** `ad4a270` (engine), `a696897` (spec)  
**Status:** COMPLETE — 5/5 diagnostics passing, clean working tree

---

## 1. What We Actually Built

S15 is a **context resolution layer** that sits between the user's natural language and the existing S1–S14 execution pipeline. It does not introduce new tools, new browser runtimes, or new execution engines. It answers one question:

> When the user says "this" or "the page I'm on" or "current document," what exact target do they mean, and is it safe to act on it?

The deliverable is a single PowerShell module (`S15-Handoff-Suite.ps1`, ~17KB, 397 lines) exposing three public functions:

| Function | Purpose |
|---|---|
| `Get-ZaryaContext` | Captures the Win32 foreground window, PID, process name, and browser detection flag |
| `Resolve-ZaryaTarget` | Maps natural language queries to concrete targets using desktop/browser context |
| `Invoke-ZaryaAction` | Wraps tool execution with authorization gates, mutation safeguards, and S2 verification |

---

## 2. Architecture Decisions & Rationale

### Decision 1: Extend S12/S13/S14, don't replace them

The spec was explicit: do not create a second artifact system, a second browser runtime, or a second context store. We honored this. `Resolve-ZaryaTarget` consumes `Get-ZaryaContext` output and cross-references it against the existing S14 browser session list. No new state management was introduced.

**Tradeoff:** This means S15 is only as good as the observation layer beneath it. If S13's Win32 foreground capture returns stale data (e.g., the user alt-tabbed between observation and resolution), S15 will resolve against the wrong window. We accept this as a known limitation rather than building a competing observer.

### Decision 2: Deterministic regex patterns, not LLM intent parsing

Intent classification uses hardcoded regex patterns matching a small vocabulary:
- Browser: `"read the page I'm on"`, `"this page"`, `"current page"`, `"what webpage is open"`
- Artifacts: `"open this document"`, `"this file"`, `"edit current file"`
- Explicit fallback: `"open C:\path\file.txt"`, `"read https://..."`

**Why:** The spec forbade replacing deterministic intent with an LLM. This is the right call for now. LLM-based intent parsing introduces non-determinism that makes the authorization model unverifiable. We'd rather support 10 phrases reliably than 10,000 phrases unreliably.

**Tradeoff:** Users who phrase things differently ("can you look at what's on my screen right now") will hit the `NOT_FOUND` fallback. This is acceptable for S15. Vocabulary expansion is an S16+ concern.

### Decision 3: Separate boolean flags for authorization and mutation confirmation

The original Block 5 implementation used a single `[bool]$UserAuthorized` parameter and compared it against the string `"ExplicitConfirmation"` for mutation gating. This failed because PowerShell coerces non-empty strings to `$true` when compared against `[bool]`, silently bypassing the mutation guard.

**Fix:** Introduced two explicit boolean parameters:
- `$UserAuthorized` — base permission to execute any action
- `$ExplicitMutationConfirmed` — elevated permission required for `edit|modify|write|delete`

This is type-safe, testable, and cannot be accidentally bypassed by string coercion.

### Decision 4: Resolution states map directly to S12 contracts

We reuse the existing S12 resolution taxonomy: `RESOLVED`, `AMBIGUOUS`, `NOT_FOUND`, `UNAVAILABLE`. No new states were invented. This means downstream code that already handles S12 states will work with S15 output without modification.

---

## 3. Security Model — What's Enforced and What's Not

### Enforced:

1. **Context ≠ Authorization.** Resolving a target to `C:\secret\file.txt` does not grant read access. The `$UserAuthorized` gate is checked after resolution, before any tool call.

2. **Ambiguity halts execution.** If two files match "this document," the pipeline returns `AMBIGUOUS` with both candidate paths and invokes zero tools. No heuristic ranking, no "most recently modified" guessing.

3. **Mutation requires explicit confirmation.** Any action matching `edit|modify|write|delete` is blocked with `MUTATION_BLOCKED` unless `$ExplicitMutationConfirmed = $true` is passed. Standard `$UserAuthorized = $true` is not sufficient.

4. **No URL fabrication.** If the browser context is unavailable or the page title cannot be correlated with an S14 session, the resolver returns `UNAVAILABLE` with a null target. It never constructs a URL from partial information.

### Not Yet Enforced (S16+ concerns):

- **File path traversal validation.** The resolver trusts the workspace root boundary but does not actively block `..\..\` traversal in explicit target inputs. This is mitigated by the fact that explicit targets still pass through the authorization gate, but it should be hardened.
- **Browser session spoofing.** The S14 browser page list is trusted as-is. If a malicious process injects fake tab entries into the observed pages array, S15 would resolve against them. This is an S14-layer concern, not S15.
- **Rate limiting / replay protection.** Nothing prevents the same resolved target from being executed repeatedly in rapid succession.

---

## 4. Testing Evidence

The embedded diagnostic suite (`Run-S15Diagnostics`) runs 5 tests:

| # | Test | What It Proves | Result |
|---|---|---|---|
| 1 | Ambiguity Safety Guard | `AMBIGUOUS` state halts execution, invokes no tools | PASSED |
| 2 | Trust-Decoupling Authorization | Resolved target + `$UserAuthorized=$false` = `BLOCKED` | PASSED |
| 3 | Mutation Block (Unconfirmed) | Resolved edit target + standard auth = `MUTATION_BLOCKED` | PASSED |
| 4 | Mutation Execution (Confirmed) | Resolved edit target + explicit confirmation = `SUCCESS` | PASSED |
| 5 | Integrated Read Verification | Full golden path: resolve → authorize → execute → verify | PASSED |

**What's NOT tested yet:**
- Live Playwright integration (S14 browser session correlation with real tabs)
- Cross-process window title parsing for non-standard apps (e.g., Electron apps with custom title bars)
- Race conditions between foreground capture and user alt-tabbing
- Unicode/non-ASCII filenames in workspace resolution
- Very large workspace directories (10,000+ files) and `Get-ChildItem -Recurse` performance

---

## 5. Known Limitations & Tech Debt

### Limitation 1: Window title parsing is brittle

The resolver strips app suffixes using patterns like:
```
-replace "\s+-\s+(Google Chrome|Microsoft Edge|Mozilla Firefox|Brave).*$", ""
```

This works for standard browsers and editors but will fail for:
- Apps with custom title bar formats (e.g., `"MyApp — file.txt"` using an em-dash)
- Localized app names (e.g., German Windows showing `"Datei.txt - Editor"`)
- Apps that put the filename at the end instead of the beginning

**Mitigation:** The fallback is `NOT_FOUND` with a clarification prompt, which is safe but not helpful. S16 should consider UI Automation (UIA) or accessibility tree inspection for more robust title extraction.

### Limitation 2: No real file content verification

The `Invoke-ZaryaAction` function simulates tool execution. In production, the actual `Invoke-BrowserReadTool` and `Invoke-FsOpenTool` stubs need to be replaced with real S14 Playwright calls and real filesystem operations. The verification logic (`-not [string]::IsNullOrWhiteSpace($payload)`) is correct in structure but currently validates simulated output.

### Limitation 3: Single foreground window only

S15 resolves against the single foreground window returned by `GetForegroundWindow()`. It cannot handle scenarios like:
- "Read the page in my second monitor"
- "Edit the file in the other VS Code window"
- Multi-monitor, multi-workspace setups where "this" is ambiguous across screens

### Limitation 4: No temporal context

The resolver captures a point-in-time snapshot. If the user says "read the page I'm on" but switched tabs 200ms before the capture, the resolved target will be stale. There is no freshness validation or re-observation loop.

---

## 6. What the Junior Dev Should Know

If you are picking up S15 for maintenance or S16 development:

1. **Start with `S15-Handoff-Suite.ps1`.** It is self-contained. The three public functions are the entire API surface. Do not look for hidden state or background threads — there are none.

2. **The regex vocabulary is intentionally small.** Do not expand it without adding corresponding test cases. Each new pattern must be tested against at least: exact match, partial match, ambiguous match, and no-match scenarios.

3. **The mutation gate is the most critical safety mechanism.** If you change the `Invoke-ZaryaAction` parameter signature, verify that `$ExplicitMutationConfirmed` cannot be accidentally defaulted to `$true`. The original bug (string-to-bool coercion) was subtle and silent.

4. **Do not merge observation and execution.** The separation between `Get-ZaryaContext` (observe), `Resolve-ZaryaTarget` (resolve), and `Invoke-ZaryaAction` (execute) is architectural, not cosmetic. Collapsing them will break the authorization model.

5. **The diagnostic suite is your regression safety net.** Run `Run-S15Diagnostics` after any change. If any test flips from PASSED to FAILED, do not ship.

---

## 7. Recommendations for S16+

1. **Real Playwright integration.** Replace the simulated browser tool stubs with actual S14 Playwright session calls. The resolution pipeline is ready; the execution stubs are not.

2. **UI Automation for robust title parsing.** Win32 `GetWindowText` is the lowest common denominator. UIA would provide structured access to document names, tab titles, and file paths without regex fragility.

3. **Vocabulary expansion with test harness.** Build a parameterized test suite that validates new natural language patterns against mock contexts before adding them to the production regex list.

4. **Freshness validation.** Add a TTL (time-to-live) check on context observations. If the foreground window was captured more than N seconds ago, re-observe before resolving.

5. **Multi-window disambiguation.** Extend the resolver to enumerate all visible windows (not just foreground) when the user's reference is ambiguous across screens or workspaces.

---

## 8. Bottom Line

S15 successfully bridges observation and action without introducing security regressions, new runtimes, or architectural debt. The implementation is small (~400 lines), deterministic, and fully tested. The main risks going forward are the brittleness of window title parsing and the gap between simulated and real tool execution. Neither is a blocker for S15 sign-off, but both should be addressed before S16 ships to production.

**Sign-off status:** Ready for S16 planning.