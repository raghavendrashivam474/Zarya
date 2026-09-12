# Browser Runtime & Event Loop Architecture Investigation

**Status:** Resolved  
**Baseline:** `v0.9.0-s9` (`8247de5`)  
**Scope:** Playwright Event Loop Thread-Affinity, CDP Boundaries & Lifecycle  

---

## 1. Observed Defect

When executing browser operations (`desktopBrowserOpen`, `desktopBrowserOpenYoutubeVideo`), the engine raised:
```text
AttributeError: Page.goto: 'NoneType' object has no attribute 'send'
or reported:

text

Opening in existing browser session. This usually means that the profile is already in use by another instance of Chromium.
2. Root Cause Analysis
Event Loop Destruction Across Tool Invocations:
In recent changes, _run(coro) was modified to use concurrent.futures.ThreadPoolExecutor with asyncio.run(coro). Because asyncio.run() creates and destroys an event loop on each call, the Playwright connection objects (STATE.playwright, STATE.context, STATE.page) remained attached to a destroyed loop. Subsequent calls on existing page instances tried to execute _channel.send(...) with _connection = None, triggering NoneType has no attribute 'send'.
Process Orphanage & Profile Locking:
When unhandled exceptions occurred on destroyed loops, background Chromium worker processes remained running without clean teardown, retaining exclusive SQLite locks on the user data directory.
Cross-Thread Deadlock on Cleanup:
Attempting to call STATE.context.close() from a different thread or loop than the one that created the Playwright objects resulted in asynchronous deadlocks.
3. Surgical Fix Applied
Dedicated Background Event Loop:
Restored the dedicated daemon thread and event loop (_LOOP, _LOOP_THREAD, _run_loop()). All Playwright async coroutines are marshalled through asyncio.run_coroutine_threadsafe(coro, loop), ensuring long-lived connection stability across sequential tool invocations.
Thread-Safe Cleanup:
All browser lifecycle operations (open, navigate, read, close) are executed strictly within the dedicated loop.
Preserved Managed/CDP Boundaries:
managed: Isolated profile in ~/.zarya_browser_data (default).
cdp: Connects strictly to port 9222 and raises a clean ToolError on failure (no phantom processes).