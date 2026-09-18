# ADR-019: Ecosystem Integration Boundary (EIP-1)

**Status:** Accepted
**Date:** 2026-09-14
**Authors:** EIP-1 Architecture
**Context:** [Zarya S18 Baseline (frozen)]
**Supersedes:** None

---

## Context and Problem Statement

Zarya has evolved into a robust, self-verifying, long-running agent platform (S18). As we transition into the Ecosystem Integration Phase, Zarya must be capable of acting as an **independently discoverable, sovereign ecosystem participant**. 

A future local orchestrator (specifically **Shyam**) needs a way to discover Zarya, query its capabilities, monitor its status, and trigger authorized operations. 

However:
1. Zarya must remain **completely sovereign**—it must not depend on Shyam, Flux, or any external system to operate.
2. The integration boundary must be **stable and versioned** so internal Zarya refactoring does not break ecosystem peers.
3. The boundary must be **secure**—a local process connecting to Zarya must not automatically receive arbitrary shell/code execution authority.
4. We must **avoid architectural duplication**—we must reuse Zarya's existing verification, state tracking, and lifecycle systems rather than rebuilding them for the ecosystem.

---

## Decision Drivers

* **Ecosystem Isolation:** Zero imports of Zarya internals by external clients.
* **Security & Sandboxing:** Absolute rejection of raw execution vectors (shell, python eval, dangerous tools).
* **Minimal Maintenance Overhead:** Avoid launching a separate server process or managing dynamic ports.
* **Epistemic Truth:** Ecosystem outcomes must reflect Zarya's S2 reality-verification fabric, never fabricating "success."
* **Ease of Implementation:** The boundary must be readable and executable by a junior developer.

---

## Considered Alternatives

### Alternative 1: Express/TypeScript Gateway (in `server/index.ts`)
Add the ecosystem endpoints to the Express TS server, which would then proxy requests to the Python FastAPI backend.
* **Pros:** TS is already acting as the frontend proxy; contains the Gemini AI loop.
* **Cons:** Introduces an extra network hop. Separates the protocol contract from the authoritative runtime (Python). Couples ecosystem integration to the frontend presentation layer.

### Alternative 2: Separate Ecosystem Server Process
Launch a secondary FastAPI/Flask/gRPC server specifically for ecosystem traffic on a different port.
* **Pros:** Complete process-level isolation of ecosystem traffic.
* **Cons:** Increases CPU/memory overhead. Introduces port collision risks on the local machine. Requires complex cross-process communication (IPC) within the local Zarya boundary.

### Alternative 3: FastAPI Router Extension (Selected)
Extend the existing Python FastAPI runtime server (`agent/server.py`) with a dedicated `/ecosystem/v1` router.
* **Pros:** Extremely lightweight. Direct access to Zarya's authoritative runtime (`execute_work()`, `CheckpointStore`, `DeviceRegistry`). Zero port-management overhead.
* **Cons:** Sharing a port means HTTP traffic shares resource limits; mitigated by the lightweight nature of local loopback requests.

---

## Decision Outcome

We chose **Alternative 3: FastAPI Router Extension** mounted under `/ecosystem/v1`.

### Key Implementation Choices:

1. **Token-Based Authentication:**
   A cryptographically secure token (`secrets.token_urlsafe(32)`) is generated once per process start. External clients must provide this token via the `X-Ecosystem-Token` header. This prevents unauthorized local processes from hijacking Zarya.

2. **Strict Tool Allow-list Sandboxing:**
   Rather than exposing the entire `registry.TOOLS` surface (80+ tools), we enforce a strict allow-list of safe tools (`getWeather`, `getNews`, `listFiles`, `openWebsite`, `openApplication`, `getSystemInfo`). Attempting to run unlisted tools returns `403 TOOL_NOT_ALLOWED`.

3. **Compliant WorkPlan Wrapping:**
   The `POST /work/execute` endpoint takes a simple tool name and arguments, and constructs a compliant single-step `WorkPlan` internally. It invokes `execute_work(authorized=True)`, allowing us to reuse Zarya's existing S6 multi-step execution engine, S2 verification fabric, and S4 failure reasoning.

4. **Read-only Status Projection:**
   Global status is derived directly from S18 active operation counts. S18 `LifecycleStatus` values are mapped cleanly to ecosystem availability states (e.g., `RUNNING` -> `BUSY`, `COMPLETED` -> `READY`).

---

## Consequences

* **Positive:** Zarya remains 100% sovereign and fully usable if the ecosystem consumer is absent.
* **Positive:** There is no duplicate lifecycle, no duplicate executor, and no duplicate state machine.
* **Positive:** Security is guaranteed by sandboxing the tool list and requiring cryptographically secure tokens.
* **Positive:** Zero regressions were introduced to S1–S18 milestone tests.
* **Neutral:** The token must be read from Zarya's startup logs or stdout by the orchestrator. This is standard and highly appropriate for local daemon orchestration.
