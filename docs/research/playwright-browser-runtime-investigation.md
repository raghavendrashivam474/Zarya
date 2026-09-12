# Browser Runtime & Chrome Profile Architecture Investigation

**Status:** Resolved  
**Scope:** Browser Execution, CDP, and Profile Isolation  

---

## 1. Observed Issue

During execution of browser tools, Playwright reported launch failures when attempting to launch Chromium. Additionally, when CDP connection failed, the engine silently fell back to spawning Chrome with a generated UUID temporary directory:
```text
_tmpdir = os.path.join(_tempfile.gettempdir(), f"elysia-cdp-{_uuid.uuid4().hex[:8]}")
This behavior generated confusing, profile-less, non-deterministic browser windows for the user with zero logins or active profiles.

2. Root Cause Analysis
Environment Binaries: The local Playwright package (1.62.0) expects its standard Chromium build v1234 inside %LOCALAPPDATA%\ms-playwright\chromium-1234. The folder existed but required validation. Standalone launch verification showed the binary was intact and accessible.
Silent Fallback Trap: If Zarya was configured for CDP mode (ELYSIA_BROWSER_MODE=cdp / ZARYA_BROWSER_MODE=cdp) but Chrome was not started on port 9222, the connection caught a connect ECONNREFUSED error. Instead of raising a clear failure, the legacy code executed a shell launch with a random temporary user data directory, bypassing normal profile semantics.
Profile File-Locking: Google Chrome places exclusive SQLite file-locks on active profile directories (Cookies, History, Web Data). If two distinct Chrome processes (regular everyday browsing and Playwright automation) attempt to access the same profile directory simultaneously, database corruption or crash occurs.
3. Structural Repair Action
Removed Ghost Fallback: Eliminated the silent fallback process invocation in _ensure_browser_cdp_async.
Transparent Error Propagation: CDP connection failure now throws a descriptive ToolError instructing the developer/user to either:
Start their normal Chrome process with --remote-debugging-port=9222.
Switch back to managed mode via desktopBrowserSetMode.
Standardized Storage: Standardized the managed browser context to use ~/.zarya_browser_data, ensuring logins, cookies, and local sessions persist across browser actions safely without overlapping with daily browsing profiles.