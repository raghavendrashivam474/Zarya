# S3 Investigation: Computer State Model

## 1. Executive Summary
The goal of S3 was to define and implement the minimal representation of relevant computer state necessary for Zarya to reason about actions without introducing premature complexity, persistent database bloat, or continuous background observation costs.

## 2. Findings on Existing State Observations
Prior to S3, state observation was tightly coupled to verification:
- `applications.py`: tasklist process lookup checked presence, but immediately returned a verification dict and discarded the observation.
- `files.py`: checked existence and file size/content, returning verification status, but did not track modification times or timestamps.
- `terminal.py`: analyzed stdout/stderr text for common error patterns, but did not maintain environment state or command execution records.

All three domains shared a common return signature (`{status, method, detail, observation}`), which made it possible to extract and normalize state without refactoring tool execution paths.

## 3. Evaluated Candidates

### Option A: Distributed Domain-Local Observations Only
- Pros: Simple, zero central infrastructure.
- Cons: Tools cannot query state recorded by other tools; reasoning engines have no unified interface to query "what is currently believed to be true."

### Option B: Universal Centralized Daemon / Graph Database
- Pros: Complete system visibility.
- Cons: Massive CPU/memory footprint, excessive background indexing, premature complexity for multi-step tasks.

### Option C: Shared State Semantics with In-Memory Cache (Chosen)
- Implements a standardized `StateObservation` schema and `StateFreshness` calculation.
- Employs a lightweight, in-memory `StateCache` instance.
- Adds non-breaking `state` payload to tool execution outputs.
- Retains domain-specific observation logic while standardizing state queryability.

## 4. Freshness Semantics
Observations decay over time according to a deterministic tiering:
- **CURRENT** (`age <= max_age`): High confidence; can be used directly without re-verification.
- **STALE** (`max_age < age <= max_age * 3`): Medium confidence; valid for advisory purposes, but dangerous for destructive decisions.
- **REQUIRES_REFRESH** (`age > max_age * 3`): Expired; state must be explicitly re-queried before taking action.
- **UNKNOWN**: Observation missing, unparseable, or probe failed.

## 5. Backward Compatibility & Non-Breaking Evolution
All tools continue to return `"result"` and `"verification"`. The S3 changes introduce an additional `"state"` key containing the serialized `StateObservation`. All 18 existing S1/S2 regression tests passed immediately without modification.
