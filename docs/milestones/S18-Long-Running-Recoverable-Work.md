# Zarya S18 — Long-Running & Recoverable Work

**Status:** Completed  
**Baseline:** S17 Complete  
**Milestone:** S18  

## 1. Overview
S18 extends Zarya with safe, durable lifecycle management for multi-step work operations across interruptions, operator pauses, and restarts.

## 2. Implemented Components
- **`agent/lifecycle.py`**: State machine, transition guards, `WorkState`, and `StepRecord` data structures.
- **`agent/checkpoint.py`**: SQLite-backed persistent checkpoint storage (`s18_workstate.db`).
- **`agent/resume.py`**: Reality verification engine and resume orchestrator.
- **`agent/control.py`**: Cooperative pause, resume, and cancellation controller.
- **`agent/work.py`**: Integrated lifecycle hooks, checkpoint triggers, and resume step-seeding.
- **`agent/server.py`**: HTTP endpoints for `/work/status`, `/work/resumable`, `/work/resume`, `/work/pause`, and `/work/cancel`.

## 3. Invariants & Guarantees
1. **Checkpoint ≠ Success:** Checkpoint records bounded progress, never hallucinating task completion.
2. **Reality Verification:** Stale or externally mutated files are detected prior to resuming, preventing corrupted runs.
3. **Artifact Continuity:** S12 artifact IDs and canonical locators survive across pause and resume.
4. **Authority Separation:** S5 recovery and S10 adaptation authorities remain untouched and authoritative.
5. **UNKNOWN Preservation:** `UNKNOWN` status is terminal and non-resumable.

## 4. Verification Suite
- Unit Tests: `tests/test_s18_lifecycle.py` (9/9 passing)
- Live Windows Desktop Smoke: `scripts/smoke_s18_desktop.py` (Positive & Negative scenarios passing 100%)