# EIP-1 Reconnaissance Design Note

**Date:** 2026-09-18
**Baseline:** Zarya S18 (frozen)
**Author:** EIP-1 Implementation
**Status:** Pre-implementation reconnaissance complete

---

## 1. Existing Relevant Architecture

Zarya is a dual-process system:

- **Python runtime** (agent/): FastAPI server on 127.0.0.1:8765.
  Owns work execution, lifecycle, verification, context, device identity.
  This is the authoritative runtime.

- **TypeScript server** (server/index.ts): Express + WebSocket on port 3000.
  Serves the frontend, proxies desktop tool calls to the Python agent,
  hosts the Gemini AI conversation layer. This is NOT the runtime.

Key Python modules:

| Module | Lines | Role |
|--------|-------|------|
| agent/work.py | 486 | Work execution engine (execute_work()) |
| agent/server.py | 318 | FastAPI HTTP boundary |
| agent/lifecycle.py | 328 | S18 WorkState, LifecycleStatus enum |
| agent/checkpoint.py | 249 | SQLite checkpoint persistence |
| agent/resume.py | 199 | Reality-verified resume |
| agent/control.py | 66 | Cooperative pause/cancel |
| agent/context/device.py | 481 | S17 DeviceIdentity, DeviceRegistry |
| agent/state.py | 321 | S3 StateObservation, StateCache |
| agent/context.py | 750 | S7 MemoryStore, persistent context |
| agent/registry.py | 251 | Tool registry (TOOLS dict, @register) |

---

## 2. Existing External Communication Mechanisms

- **FastAPI HTTP** on 127.0.0.1:8765 (Python agent)
  - GET /health — liveness
  - GET /tools — lists registered tool names
  - POST /execute — single tool dispatch
  - POST /intent — natural language -> work
  - GET /work/status/{id} — S18 operation status
  - GET /work/resumable — S18 resumable list
  - POST /work/resume|pause|cancel — S18 cooperative control

- **Express HTTP + WebSocket** on 0.0.0.0:3000 (TS server)
  - Proxies desktop tool calls to Python agent
  - /internal/step-event — receives S11 step callbacks
  - /api/* — frontend data APIs
  - WebSocket /live — real-time client communication

- **HTTP callback** — make_http_step_callback() in server.py
  creates callbacks that POST step events to a URL.

---

## 3. Existing Identity Mechanisms

- **S17 DeviceIdentity** (agent/context/device.py):
  - Fields: device_id, display_name, device_type, platform,
    	rust_state, is_available, metadata
  - DeviceRegistry: register/unregister/query devices
  - 
esolve_device_reference(): fuzzy device resolution
  - Enums: DeviceType, Platform, TrustState

- **Agent version**: agent/__init__.py has __version__ = "0.9.0"

- **No instance identity** currently exists. Zarya has device identity
  but no per-instance identity for ecosystem discovery.

---

## 4. Existing Authorization Mechanisms

- **Boolean flag**: execute_work(authorized=False).
  The caller must explicitly pass authorized=True.

- **Server-level**: POST /execute requires authorized in the
  ExecuteRequest body. /intent and /persona/interact extract
  authorized from the request body.

- **No token/auth header** currently exists. Authorization is
  trust-based (localhost assumption).

- **S17 TrustState**: TRUSTED, UNTRUSTED, PENDING, REVOKED
  exists in device identity but is not wired to execution auth.

---

## 5. Existing Lifecycle/Status Sources

- **LifecycleStatus enum** (agent/lifecycle.py):
  PENDING, RUNNING, CHECKPOINTED, PAUSED,
  COMPLETED, FAILED, CANCELLED

- **WorkState class**: tracks per-operation lifecycle with
  legal transition enforcement (_ALLOWED_TRANSITIONS).

- **CheckpointStore**: SQLite-backed, can query active operations.

- **control.get_operation_status()**: returns status dict for an op.

- **No global "Zarya availability" status** exists yet.

---

## 6. Existing Work Invocation Mechanisms

- **execute_work(plan, authorized, step_callback)** in work.py:
  - Takes a validated WorkPlan (dict with steps)
  - Executes steps sequentially
  - Each step routes through 
egistry.TOOLS[tool_name](args)
  - Returns WorkResult dict with step outcomes
  - Supports step event callbacks (S11)

- **POST /execute** in server.py:
  - Accepts ExecuteRequest(tool, args, authorized)
  - Calls single tool via registry
  - Returns ExecuteResponse

- **POST /intent**: natural language -> process_natural_intent() -> work

---

## 7. Proposed Ecosystem Boundary Location

**Decision: Extend the existing Python FastAPI server (agent/server.py)
with a new /ecosystem/v1/ route prefix.**

### Why this location:

1. The Python FastAPI server IS the runtime boundary.
   All authoritative execution, lifecycle, and identity lives here.

2. Adding routes to the existing server avoids:
   - A second server process
   - Port management complexity
   - Authorization boundary fragmentation
   - A new transport layer

3. The TS server is a frontend proxy, not the runtime.
   Putting the boundary there would create an unnecessary hop
   and couple the ecosystem protocol to the frontend stack.

4. The existing /health, /execute, /work/* routes prove
   this server already handles external communication.

### Module placement:

```text
agent/
ecosystem/
init.py # Package init, version
protocol.py # Protocol constants, version
identity.py # Instance identity projection
capabilities.py # Explicit capability advertisement
status.py # Status projection from lifecycle
authorization.py # Ecosystem auth (token-based)
routes.py # FastAPI router (/ecosystem/v1/*)
errors.py # Structured error model
transport.py # Transport abstraction (future)
```

The routes.py file creates a FastAPI APIRouter that gets
mounted onto the existing pp in server.py.

---

## 8. Why This Avoids Duplication

| Ecosystem Need | Existing Source | Strategy |
|---------------|----------------|----------|
| Identity | DeviceIdentity + __version__ | Project, don't recreate |
| Capabilities | 
egistry.TOOLS + DESKTOP_TOOL_NAMES | Wrap with explicit allow-list |
| Status | LifecycleStatus + CheckpointStore | Map/aggregate, don't duplicate |
| Work execution | execute_work() | Call through existing path |
| Authorization | authorized flag + TrustState | Extend with token, reuse flag |
| Error model | ToolError + work result errors | Map to protocol errors |
| Lifecycle | WorkState transitions | Read-only projection |
| Checkpoints | CheckpointStore | Query, never replace |

No new lifecycle, no new executor, no new state machine,
no new identity system. The ecosystem boundary is a
**read-only projection + controlled invocation adapter**.

---

## Non-Goals (Reiterated)

- No Shyam-specific code
- No Flux integration
- No network discovery
- No cross-device execution
- No arbitrary code execution
- No public Internet API
- No cloud dependency
- No work migration
- No autonomous orchestration
