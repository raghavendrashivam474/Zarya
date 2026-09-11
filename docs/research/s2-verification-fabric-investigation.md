# S2 Investigation: Verification Fabric

**Date:** 2026-09-11
**Baseline:** v0.2.0-s1 (7315a63)
**Branch:** zarya/s2-verification-fabric

---

## A. Application Verification (S1 — Existing)

S1 provides `_verify_application_launched(spec)` in `agent/tools/applications.py`.

- **Method:** Polls `tasklist` for process image name (bounded: 3s timeout, 0.5s interval)
- **Returns:** Dict with `{status, method, image, observation_window_ms, detail}`
- **States:** VERIFIED_SUCCESS | VERIFIED_FAILURE | UNKNOWN
- **Integration:** Additive `"verification"` key in `open_application()` return dict
- **Style:** Plain helper function. No classes, no interfaces, no abstraction hierarchy.

## B. Filesystem Verification (S2 Target)

### Current state
`create_file()` in `agent/tools/files.py` returns:
```json
{"result": "Created file: ...", "path": "..."}
No post-write verification. Success is inferred from absence of exception.

Observable post-conditions
Check    Cost    Reliability    S2 Scope
File exists    Instant    High    ✅ YES
File size    Instant    Medium    ✅ YES (in observation)
Content matches    Instant    High    ✅ YES
Hash    Instant    High    ❌ Future
Recommendation
Add _verify_file_created(path, expected_content) helper.
Synchronous — no polling needed (unlike application verification).
Check existence + content match. Return same dict shape as S1.

C. Terminal Verification (S2 Target)
Current state
run_terminal_command() in agent/tools/terminal.py returns:

JSON

{"result": "Executed command: ...", "output": "..."}
The Windows backend run_command() returns res.stdout + res.stderr as a string.
Exit code is discarded — not available without backend modification.

Observable post-conditions
Check    Available?    S2 Scope
Exit code    ❌ Not returned by backend    ❌ Needs ADR
stdout/stderr content    ✅ Yes    ✅ YES
Error indicators in output    ✅ Parseable    ✅ YES
Filesystem side effects    ✅ Possible    ❌ Too command-specific for S2
Recommendation
Add _verify_terminal_execution(command, output) helper.
Check output for error indicators. Distinguish execution evidence from environmental evidence.
Document that exit-code verification requires a backend change (future ADR).

D. Common Semantics
All three domains CAN share:

status: VERIFIED_SUCCESS | VERIFIED_FAILURE | UNKNOWN
method: string identifying the observation technique
detail: human-readable explanation
observation: dict of raw evidence
E. Domain-Specific Semantics
Domain    Observation Mechanism    Timing
Application    Process image polling (tasklist)    Async (up to 3s)
Filesystem    Path existence + content check    Sync (instant)
Terminal    Output string analysis    Sync (instant)
These are fundamentally different observation strategies.
A shared interface would add complexity without benefit at this scale.

F. Contract Compatibility
S1 established the pattern: add "verification" key alongside "result".
S2 extends this to create_file and run_terminal_command.
Existing callers that ignore unknown keys will continue working.
No changes to server.ts, server.py, or tool dispatch.

G. Architectural Recommendation
Option A: Minimal helper-based extension ✅ SELECTED

Justification:

S1 established a dict-helper pattern — extending it is consistent
Three domains with different observation mechanisms don't benefit from a shared class hierarchy
The codebase is small (files.py ~250 lines, terminal.py ~120 lines)
Adding abstractions before evidence would violate the S2 research mandate
If S3+ adds more domains, a refactor can be justified with evidence then
Decision
Extend S1's helper-function pattern to filesystem and terminal domains.
Each tool module gets its own _verify_* helper returning the same dict shape.
No shared abstraction layer. No new files. No interface classes.
If this proves insufficient in S3, document and refactor with an ADR.
