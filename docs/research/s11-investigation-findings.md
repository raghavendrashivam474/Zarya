# S11 Investigation Findings

**Date**: 2026-09-14
**Baseline**: v0.10.6 (dd7b20e)
**Branch**: zarya/s11-multistep-visibility
**Status**: Investigation complete — implementation authorized

---

## Investigation Questions

### Q1: Where does S6 actually enter a step?

**File**: `agent/work.py`
**Line**: 187-193

```python
while execution_queue:
    if len(completed_steps) >= MAX_STEPS:
        ...
        break
    step = execution_queue.pop(0)
    step_id = step["id"]
    tool_name = step["tool"]
    args = step.get("args") or {}
```

The step boundary is the top of the while execution_queue: loop.
Each iteration pops one step, resolves its tool handler, and executes it.

### Q2: Where does a step receive its authoritative result?

File: agent/work.py
Lines: 201-225 (execution + evaluation)

```Python

# Execution (line 202-203)
tool_handler = TOOLS[tool_name]
response = tool_handler(args)

# Authoritative evaluation (line 225)
step_status, detail_msg = _evaluate_step_outcome(response, unverified_ok)
```

The authoritative result is determined by _evaluate_step_outcome()
(lines 100-133), which inspects the tool response's verification
and recovery payloads to produce one of:

- STEP_SUCCESS
- STEP_FAILURE
- STEP_RECOVERED
- STEP_UNKNOWN

This function is the single source of truth for step outcomes.

### Q3: Can the existing server event bridge observe those boundaries?

No. Not without modification.

Reason: The Node server (server/index.ts line 1766) makes a
single HTTP call to callDesktopAgent(fnName, args) which invokes
Python's /execute endpoint. The entire execute_work() loop
runs inside that single HTTP round-trip. The Node server is blocked
waiting for the response and has zero visibility into individual steps.

Evidence:

- work.py contains zero event emission (confirmed by grep)
- index.ts emits work_started at line 1763 (before the call)
  and work_completed at line 1783 (after the call)
- No events are emitted during the call

### Q4: Can step events be emitted without changing execution behavior?

Yes, via an additive callback mechanism.

Proposed approach:

1. Node injects a _callback_url into the args before forwarding
   to Python (additive — Gemini doesn't know about it)
2. execute_work() checks for _callback_url in args
3. If present, Python POSTs step events to that URL at each boundary
4. Node's internal endpoint calls broadcastRuntimeEvent()
5. If the callback fails, the step continues (event failure isolation)

What remains unchanged:

- Step execution order
- Verification logic (_evaluate_step_outcome)
- Recovery behavior (S5)
- Authorization gate
- Work halting semantics
- Adaptive work (S10)
- Final result structure

### Q5: Does the existing RuntimeEventPayload require schema modification?

No.

The existing schema (server/index.ts line 247-256 and
src/lib/audio.ts line 1-7) already includes:

```TypeScript

event: 'work_started' | 'work_completed'
     | 'work_step_started' | 'work_step_completed';
```
The state union already covers all required states:

```TypeScript

state: 'WORKING' | 'VERIFYING' | 'VERIFIED_SUCCESS'
     | 'VERIFIED_FAILURE' | 'UNKNOWN' | 'PLANNING' | 'BLOCKED';
```

The payload field (Record<string, unknown>) can carry
step-specific metadata (step_id, step description, etc.).

No schema changes required.

### Q6: Can frontend step visibility be implemented without another state machine?

Yes.

The frontend already has:

- RuntimeEventPayload type with step events
- onRuntimeEvent callback in ZaryaAudioSession
- ShefaliPresenceController that maps runtime states to presentation

The implementation will:

1. Consume work_step_started / work_step_completed events
   via the existing onRuntimeEvent handler
2. Update a simple step-progress state in App.tsx
3. Let ShefaliPresenceController derive presentation from the
   latest event — no second state machine needed

## Architecture Decision

### Chosen approach: HTTP callback from Python to Node
```text

Node (index.ts)                          Python (work.py)
─────────────                            ────────────────
broadcast('work_started')
        │
inject _callback_url into args
        │
callDesktopAgent(fn, args)  ──HTTP──►   execute_work(plan)
        │                                    │
POST /internal/step-event ◄──callback──  step 1 start
broadcast('work_step_started')               │
                                             │
POST /internal/step-event ◄──callback──  step 1 complete
broadcast('work_step_completed')             │
                                             │
POST /internal/step-event ◄──callback──  step 2 start
broadcast('work_step_started')               │
                                             │
        ...                                  ...
        │                                    │
        │◄──────────────────────────────  return result
        │
broadcast('work_completed')
```

### Why this 

1. Additive: No existing behavior changes
2. Real-time: User sees progress as it happens
3. Isolated: Callback failure cannot break execution
4. Schema-compatible: Uses existing RuntimeEventPayload
5. Minimal Python changes: Only execute_work() gains
   optional callback emission; no changes to verification,
   recovery, or adaptive logic

### What this is NOT

- Not a new event transport (reuses existing WebSocket)
- Not a new state machine (reuses existing runtime states)
- Not a change to execution semantics
- Not a change to verification authority

## Implementation Plan

1. Add POST /internal/step-event endpoint to server/index.ts
2. Inject _callback_url in the work emission block (line ~1762)
3. Add optional callback emission to execute_work() in work.py
4. Consume step events in frontend audio.ts → App.tsx
5. Refine ShefaliPresenceController for step display + UNKNOWN
6. Add tests
7. Smoke test with real multi-step workflow

## Limitations

- Callback adds minor latency per step (local HTTP, negligible)
- Step descriptions depend on plan metadata quality
- Single-operation assumption preserved (no concurrent work)
- Recovery loops remain internal (not surfaced as step events)
