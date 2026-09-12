
Playwright Browser Runtime — Limitations & Lifecycle Invariants
Status: Active Invariant Documentation

1. Thread Affinity Invariant
All Playwright async API objects (playwright, browser, context, page) are strictly bound to the dedicated background event loop thread.
Direct manipulation of Playwright objects from external threads or the FastAPI server loop is prohibited; all calls must route through _run(coro).
2. Profile Isolation Invariant
Managed Mode: Runs in dedicated persistent directory ~/.zarya_browser_data. Never targets personal Chrome directories.
CDP Mode: Strictly opt-in via ZARYA_BROWSER_MODE=cdp with explicit Chrome port 9222.
3. Tool Cleanup Invariant
Resource resets must be performed via STATE.reset_playwright() coupled with async context close dispatched on the dedicated loop.