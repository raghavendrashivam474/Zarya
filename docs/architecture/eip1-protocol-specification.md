# EIP-1 Protocol Specification

**Protocol Name:** `zarya-ecosystem`
**Version:** `eip-1.0`
**Status:** Active
**Baseline:** Zarya S18 (frozen)
**Transport:** HTTP/1.1 over localhost
**Authentication:** Bearer token via HTTP header

---

## 1. Overview

The Zarya Ecosystem Integration Protocol (EIP-1) defines how an external
local process discovers, authenticates with, and invokes operations on a
running Zarya instance.

### Design Principles

1. **Sovereignty:** Zarya remains fully functional without any ecosystem consumer.
2. **Explicit capability:** Only deliberately advertised operations are available.
3. **No arbitrary execution:** The protocol exposes declared operations, not runtime access.
4. **Versioned contract:** All communication is bound to a protocol version.
5. **Local-first:** The boundary is designed for same-machine IPC, not public APIs.

---

## 2. Transport

| Property | Value |
|----------|-------|
| Protocol | HTTP/1.1 |
| Host | `127.0.0.1` |
| Port | `8765` (default, configurable) |
| Content-Type | `application/json` |
| Base Path | `/ecosystem/v1` |

All communication occurs over localhost. The protocol is not designed
for network exposure.

---

## 3. Authentication

### Mechanism

All endpoints except `/ecosystem/v1/auth-info` require a valid
ecosystem token in the `X-Ecosystem-Token` HTTP header.
X-Ecosystem-Token: <token_string>

### Token Properties

- Generated once per Zarya process start
- Cryptographically random (`secrets.token_urlsafe(32)`)
- Logged to Zarya's startup output for local consumer discovery
- Validated using constant-time comparison (timing-attack resistant)

### Token Lifecycle

| Event | Behavior |
|-------|----------|
| Zarya starts | New token generated and logged |
| Zarya restarts | Previous token invalidated, new token generated |
| Invalid token | `401 UNAUTHORIZED` |
| Missing token | `401 UNAUTHORIZED` |
| Empty token | `401 UNAUTHORIZED` |

### Discovery

An unauthenticated client can query the auth-info endpoint to learn
the authentication mechanism:
GET /ecosystem/v1/auth-info

Response:
```json
{
    "method": "header",
    "header_name": "X-Ecosystem-Token",
    "description": "Include the ecosystem token in the X-Ecosystem-Token HTTP header on all requests."
}
```

## 4. Endpoints

### 4.1 Discovery Endpoints

#### GET /ecosystem/v1/identity

Returns the Zarya instance identity.

Auth: Required

Response 200:

```JSON
{
    "instance_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "product": "zarya",
    "version": "0.9.0",
    "protocol": "eip-1.0",
    "platform": "windows",
    "architecture": "AMD64",
    "device": {
        "device_id": "local-device-001",
        "display_name": "Raghav's Laptop",
        "device_type": "laptop",
        "platform": "windows"
    }
}
```

| Field | Type | Description |
| --- | --- | --- |
| **instance_id** | string (UUID) | Unique per process start |
| **product** | string | Always "zarya" |
| **version** | string | Zarya product version |
| **protocol** | string | Protocol version spoken |
| **platform** | string | OS platform (lowercase) |
| **architecture** | string | CPU architecture |
| **device** | object | Optional. Present if S17 device identity is registered |

#### GET /ecosystem/v1/protocol

Returns supported protocol versions.

Auth: Required

Response 200:

```JSON
{
    "current": "eip-1.0",
    "supported": ["eip-1.0"]
}
```

#### GET /ecosystem/v1/capabilities

Returns advertised capabilities and permitted tools.

Auth: Required

Response 200:

```JSON
{
    "protocol": "eip-1.0",
    "capabilities": [
        {
            "id": "system.health",
            "version": "1.0",
            "description": "Check Zarya instance liveness and basic readiness.",
            "operations": ["check"],
            "input_schema": null,
            "output_schema": {"status": "string (READY | BUSY | UNAVAILABLE)"}
        },
        {
            "id": "work.execute",
            "version": "1.0",
            "description": "Execute a single authorized tool operation through Zarya's existing work pipeline.",
            "operations": ["execute"],
            "input_schema": {"tool": "string", "args": "object"},
            "output_schema": {"result": "object", "verified": "boolean"}
        },
        {
            "id": "work.status",
            "version": "1.0",
            "description": "Query the lifecycle status of a work operation.",
            "operations": ["query"],
            "input_schema": {"operation_id": "string"},
            "output_schema": {"operation_id": "string", "status": "string"}
        }
    ],
    "allowed_tools": [
        "getNews",
        "getSystemInfo",
        "getWeather",
        "listFiles",
        "openApplication",
        "openWebsite"
    ]
}
```

**Critical**: The `allowed_tools` list is the exhaustive set of tools
that may be invoked through `POST /ecosystem/v1/work/execute`. Any
tool not in this list will be rejected with `403 TOOL_NOT_ALLOWED`.

#### GET /ecosystem/v1/status

Returns current Zarya availability.

Auth: Required

Response 200:

```JSON
{
    "status": "READY",
    "active_operations": 0
}
```

| Status | Meaning |
| --- | --- |
| **READY** | Zarya can accept work |
| **BUSY** | Zarya has active operations |
| **STARTING** | Zarya is initializing |
| **STOPPING** | Zarya is shutting down |
| **UNAVAILABLE** | Zarya cannot accept work |

## 4.2 Operational Endpoints

#### POST /ecosystem/v1/work/execute

Execute a permitted tool through Zarya's verified work runtime.

Auth: Required

Request:

```JSON
{
    "tool": "getWeather",
    "args": {"city": "Chennai"}
}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| **tool** | string | Yes | Must be in allowed_tools |
| **args** | object | No | Tool-specific arguments (default: {}) |

Response 200:

```JSON
{
    "tool": "getWeather",
    "outcome": "VERIFIED_SUCCESS",
    "verified": true,
    "result": {
        "temperature": "32C",
        "condition": "Partly cloudy"
    },
    "summary": "Step 1: getWeather completed"
}
```

| Field | Type | Description |
| --- | --- | --- |
| **tool** | string | The tool that was executed |
| **outcome** | string | S2 verification outcome (VERIFIED_SUCCESS, VERIFIED_FAILURE, UNKNOWN) |
| **verified** | boolean | true only if outcome is VERIFIED_SUCCESS |
| **result** | object | Tool-specific result data |
| **summary** | string | Human-readable execution summary |

Response 403 (tool not allowed):

```JSON
{
    "detail": {
        "error": {
            "code": "TOOL_NOT_ALLOWED",
            "message": "Tool 'runTerminalCommand' is not permitted through the ecosystem boundary.",
            "detail": {
                "allowed_tools": ["getNews", "getSystemInfo", "getWeather", "listFiles", "openApplication", "openWebsite"]
            }
        }
    }
}
```

#### GET /ecosystem/v1/work/status/{operation_id}

Query the lifecycle status of a work operation.

Auth: Required

Response 200:

```JSON
{
    "operation_id": "op-abc123",
    "ecosystem_status": "BUSY",
    "lifecycle_status": "RUNNING",
    "detail": {
        "status": "RUNNING",
        "total_steps": 3,
        "completed_steps": 1
    }
}
```

| Field | Type | Description |
| --- | --- | --- |
| **operation_id** | string | The S18 operation identifier |
| **ecosystem_status** | string | Projected availability (READY, BUSY, etc.) |
| **lifecycle_status** | string | Raw S18 LifecycleStatus value |
| **detail** | object | Full S18 operation status |

Response `404`: Operation not found.

## 5. Error Model

>All error responses follow this structure (wrapped by FastAPI's detail envelope):

```JSON
{
    "detail": {
        "error": {
            "code": "ERROR_CODE",
            "message": "Human-readable description",
            "detail": {}
        }
    }
}
```

### Error Codes

| Code | HTTP Status | Meaning |
| --- | --- | --- |
| **INVALID_REQUEST** | 400 | Malformed request body or parameters |
| **UNSUPPORTED_PROTOCOL** | 400 | Client speaks an unsupported protocol version |
| **CAPABILITY_NOT_ADVERTISED** | 404 | Requested capability is not in the advertised list |
| **OPERATION_NOT_SUPPORTED** | 404 | Requested operation does not exist |
| **UNAUTHORIZED** | 401 | Missing or invalid ecosystem token |
| **BUSY** | 503 | Zarya cannot accept work right now |
| **UNAVAILABLE** | 503 | Zarya is not available |
| **INVALID_STATE** | 409 | Operation conflicts with current state |
| **EXECUTION_FAILED** | 500 | Tool execution failed internally |
| **VERIFICATION_FAILED** | 500 | Post-execution verification failed |
| **TOOL_NOT_ALLOWED** | 403 | Tool is not in the ecosystem allow-list |
| **UNKNOWN** | 500 | Unclassified error |

## 6. Lifecycle Status Mapping

Zarya's internal S18 LifecycleStatus values are projected to
ecosystem availability states as follows:

| S18 LifecycleStatus | Ecosystem Status |
| --- | --- |
| **CREATED** | STARTING |
| **AUTHORIZED** | STARTING |
| **RUNNING** | BUSY |
| **CHECKPOINTED** | BUSY |
| **PAUSED** | READY |
| **CANCELLING** | STOPPING |
| **CANCELLED** | READY |
| **INTERRUPTED** | READY |
| **FAILED** | READY |
| **COMPLETED** | READY |
| **UNKNOWN** | UNAVAILABLE |

## 7. Versioning

The protocol version is embedded in the URL path (/ecosystem/v1/).

Future breaking changes will increment the path version (/ecosystem/v2/).

Non-breaking additions (new capabilities, new optional fields) may
occur within the same version.

Clients should check GET /ecosystem/v1/protocol to verify
compatibility before invoking operations.

## 8. Non-Goals

The following are explicitly NOT part of EIP-1:

- Network discovery (mDNS, UDP, LAN scanning)
- Cross-device execution
- Work migration between instances
- Autonomous orchestration
- Public Internet API
- Cloud dependency
- Arbitrary code execution
- Real-time streaming (WebSocket events)
- Bidirectional communication

These may be addressed in future EIP versions.

## 9. Compatibility
Backward: Zarya remains fully functional without any ecosystem consumer.
Forward: The protocol is designed to allow capability expansion within the same version.
Internal: Zarya's internal architecture may change freely as long as the external protocol contract is preserved.
