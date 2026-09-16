# S16 Known Limitations

## Browser Execution
- Real Playwright browser execution depends on the existing S14 runtime.
  S16 wires resolution to the browser URL but does not independently
  manage browser sessions.

## Window Identification
- Still relies on Win32 window title parsing via S13.
- UI Automation (UIA) was investigated but not adopted — existing Win32
  evidence is sufficient for current use cases.
- If title parsing proves insufficient in production, UIA adoption should
  be revisited with a new ADR.

## Multi-Window Context
- Only the foreground window is used as primary context.
- Visible-window enumeration was not implemented — AMBIGUOUS is returned
  when multiple candidates match.

## Large Workspaces
- Resolution is bounded to active artifacts and window-title matching.
- Full filesystem scanning is intentionally avoided.
- Workspaces with 10,000+ files have not been benchmarked.

## Natural Language Vocabulary
- Limited to ~25 deterministic patterns (S16 Section 12).
- Expansion requires adding patterns to `agent/context/references.py`.
- No LLM-based interpretation.

## Freshness Thresholds
- Default: CURRENT ≤ 5s, STALE ≤ 30s, beyond → UNAVAILABLE.
- These are configurable but not yet tuned from production data.
