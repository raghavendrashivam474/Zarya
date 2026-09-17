# ADR-018: Long-Running & Recoverable Work Lifecycle Architecture

## Status
Accepted

## Context
Prior to S18, Zarya's work execution model operated as an atomic synchronous pipeline: `Intent -> Plan -> Execute -> Observe -> Verify -> Outcome`. Long-running multi-step operations had no durable execution boundaries to survive interruptions (network dropouts, application crashes, process restarts, or operator pauses).

We needed a mechanism to establish durable execution checkpoints, support cooperative pause/cancellation, safely resume without blindly repeating completed work, and verify external reality before resuming.

## Decision
1. **Explicit Lifecycle State Machine (`agent/lifecycle.py`):**
   - Introduced `LifecycleStatus` enum (`CREATED`, `AUTHORIZED`, `RUNNING`, `CHECKPOINTED`, `PAUSED`, `CANCELLING`, `CANCELLED`, `INTERRUPTED`, `FAILED`, `COMPLETED`, `UNKNOWN`).
   - Illegal transitions are strictly rejected; `UNKNOWN` is treated as a terminal, non-resumable state.
   - Core principle: **A Checkpoint is NOT a success claim.**

2. **Durable Checkpoint Storage (`agent/checkpoint.py`):**
   - Uses a dedicated SQLite database (`s18_workstate.db` in `%LOCALAPPDATA%\Zarya\`) separate from S7 historical context (`s7_context.db`).
   - S7 captures historical memory; S18 manages active, transactional execution state.
   - Standard library `sqlite3` only — zero external infrastructure or broker dependencies.

3. **Reality-Checked Resume Engine (`agent/resume.py`):**
   - Before continuing remaining steps from a checkpoint, the engine performs a "Reality Check" verifying that physical files, resources, and S12 artifact locators established in preceding steps still exist on disk.
   - If external state mutated or files were deleted, execution halts safely with `VERIFIED_FAILURE` and `STALE_CHECKPOINT_STATE`.

4. **Cooperative Control (`agent/control.py`):**
   - Pausing and cancellation are non-destructive and evaluated at step boundaries, ensuring in-flight file writes are never forcefully severed.

5. **Authority Preservation:**
   - S5 remains the sole autonomous recovery authority.
   - S10 remains the bounded adaptation authority.
   - S2 verification remains the truthful judge of step and overall outcomes.
   - S12/S12.1 artifact continuity is strictly propagated across resume boundaries.

## Consequences
- Long-running work can safely pause, resume, and survive interruption.
- No blind duplication of verified steps.
- Stale checkpoint divergence is caught truthfully before executing further actions.
- 100% backward-compatible with S6 `execute_work` callers.