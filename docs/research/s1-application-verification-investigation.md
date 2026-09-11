# S1 Investigation: Application Launch Verification

**Date:** 2026-09-11
**Baseline:** v0.1.0-s0 (ad68738)
**Branch:** zarya/s1-state-verification

---

## A. Current Execution Path
User Intent ("Open VS Code")
|
server.ts (Node.js WebSocket gateway)
|
HTTP POST http://127.0.0.1:8765/execute
body: { tool: "openApplication", args: { name: "vscode" } }
|
agent/server.py (FastAPI)
-> TOOLS["openApplication"] lookup
-> asyncio.to_thread(handler, args)
|
agent/tools/applications.py :: open_application(args)
-> _resolve_app("vscode")
-> APP_COMMANDS["vscode"] = {
"exe": "code.cmd",
"image": "Code.exe",
"label": "Visual Studio Code"
}
-> get_backend().launcher.launch(spec)
|
agent/backends/windows.py :: WindowsApplicationLauncher.launch(spec)
-> subprocess.Popen(
["code.cmd"],
shell=False,
close_fds=True,
creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
)
-> RETURNS None (Popen object discarded)
|
open_application() returns {"result": "Visual Studio Code opened."}
|
server.py wraps: ExecuteResponse(ok=True, result={...}, tool="openApplication")
|
server.ts receives HTTP 200 -> model sees success

text


## B. Current Result Contract

### Tool handler return (applications.py):
```json
{ "result": "Visual Studio Code opened." }
Server response (server.py ExecuteResponse):
JSON

{
  "ok": true,
  "result": { "result": "Visual Studio Code opened." },
  "error": null,
  "tool": "openApplication"
}
Key observation:
ApplicationLauncher.launch() returns None (void)
No PID is captured or returned
No process handle is retained
Success is inferred from absence of exception
C. Current Failure Handling
Scenario    Current Behavior
App not in APP_COMMANDS    ToolError raised -> ok=false
Popen throws (e.g., file not found)    Exception propagates -> ok=false
Process spawns then crashes immediately    Silently reported as success
Process spawns wrong application    Silently reported as success
Permission denied    Exception propagates -> ok=false
Timeout    No timeout mechanism exists
D. Existing Observability
Capability    Location    Mechanism
Process image name    APP_COMMANDS[app]["image"]    Static dict, e.g., "Code.exe"
Window title search    WindowsWindowManager.find_window_by_title()    win32gui.EnumWindows
Process kill by image    WindowsApplicationLauncher.close()    taskkill /IM "{image}"
Foreground window    WindowsWindowManager.get_foreground_window()    win32gui.GetForegroundWindow
Window visibility    find_window_by_title callback    win32gui.IsWindowVisible
No new dependencies required for S1 verification.

E. Verification Insertion Point
File: agent/tools/applications.py
Function: open_application()
Location: Between get_backend().launcher.launch(spec) and return

Python

# CURRENT:
    get_backend().launcher.launch(spec)
    return {"result": f"{spec['label']} opened."}

# S1 TARGET:
    get_backend().launcher.launch(spec)
    verification = _verify_application_launched(spec)
    return {
        "result": f"{spec['label']} opened.",
        "verification": verification
    }
This is additive. The existing "result" key is unchanged.
A new "verification" key is added alongside it.

F. Proposed Minimal Contract
JSON

{
  "result": "Visual Studio Code opened.",
  "verification": {
    "status": "VERIFIED_SUCCESS",
    "method": "process_image_check",
    "image": "Code.exe",
    "observation_window_ms": 2500,
    "detail": "Process Code.exe found within observation window."
  }
}
Status values:
VERIFIED_SUCCESS: Process image found within observation window
VERIFIED_FAILURE: Process image not found after observation window
UNKNOWN: Observation mechanism itself failed (e.g., tasklist error)
UNEXPECTED: Reserved for future use (e.g., wrong process detected)
G. Risks
Risk    Mitigation
Process name ambiguity (multiple instances)    S1 only checks existence, not count
Launch latency (app takes >3s to appear)    Configurable timeout, default 3s
Helper processes (e.g., code.cmd spawns Code.exe)    We check "image" field which is the final process name
UWP apps (Calculator, Settings)    tasklist may not show UWP; mark as UNKNOWN if check fails
Race condition (process appears then vanishes)    Bounded poll, not single check
Platform differences    S1 targets Windows only; Linux/macOS return UNKNOWN
H. Alternatives Considered
Approach    Pros    Cons    S1 Decision
Process existence (tasklist)    Simple, deterministic, no deps    UWP apps may not appear    PRIMARY for S1
Window title detection    Reuses existing win32gui code    Titles vary, fragile    Secondary signal
PID tracking from Popen    Most precise    Popen object currently discarded; launcher returns None    Future improvement
Screenshot + vision    Most general    Heavy, slow, needs model    Out of scope
psutil library    Rich process info    New dependency    Not needed for S1
I. Recommendation
Add _verify_application_launched(spec) helper in applications.py
Use tasklist /FI "IMAGENAME eq {image}" with bounded polling (3s max, 0.5s interval)
Return verification dict alongside existing result (additive, non-breaking)
Handle UWP/edge cases by returning UNKNOWN when tasklist cannot confirm
No changes to launcher interface, backend, or server.py
No new dependencies
Add regression tests for VERIFIED_SUCCESS, VERIFIED_FAILURE, UNKNOWN
Limitations (S1)
Only covers application launching, not other tool actions
Windows-only verification (Linux/macOS return UNKNOWN)
Does not track PIDs or process lifetimes
Does not verify application readiness, only process existence
UWP applications may report UNKNOWN
Future Work (Post-S1)
PID capture from launcher (requires changing ApplicationLauncher interface)
Multi-step action verification (browser, filesystem, terminal)
Process readiness detection (window visible + responsive)
Cross-platform verification (Linux/macOS backends)
Verification for closeApplication (confirm process terminated)
