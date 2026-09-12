# S8 Natural Intent — Known Limitations & Boundaries

**Date:** 2026-09-12
**Branch:** zarya/s8-natural-intent
**Baseline:** v0.7.0-s7
**Status:** COMPLETED

---

## 1. Intent Understanding Boundaries

The current S8 IntentInterpreter is **deterministic and regex-based**. It supports:

- Opening applications (Notepad, VS Code, Browser, Calculator, Chrome)
- Creating files with optional content
- Reading files
- Running quoted terminal commands
- Conversational continuity via S7 context memory ("do the same again")

**Not yet supported:**

- Free-form multi-step task decomposition
- Complex conditional logic ("if X then Y")
- Fuzzy synonyms outside deterministic patterns
- Any tool outside the whitelist (see PlanValidator.DEFAULT_ALLOWED_TOOLS)

## 2. Authorization Boundary

- Every candidate plan requires `authorized=True` before reaching S6 execution.
- Natural language interpretation **never** implies authorization.
- The `/intent` endpoint accepts an explicit `authorized` boolean flag from the caller.

## 3. Verification & Truth Boundary

The ResponseTranslator strictly enforces:

- `VERIFIED_SUCCESS` -> "Done — X completed and verified successfully."
- `VERIFIED_FAILURE` -> "I couldn't complete X. Runtime confirmed failure."
- `UNKNOWN` -> "I attempted X, but could not verify the outcome with certainty."
- `INCOMPLETE` -> "Work halted before completion."

**Critical:** UNKNOWN can never be presented as success. This is hallucination containment.

## 4. Plan Validator Constraints

- Maximum 5 steps per plan (bounded execution)
- File paths cannot contain `..` (directory traversal blocked)
- File extensions `.exe`, `.bat`, `.vbs`, `.cmd` blocked
- Only registered tools accepted (whitelist-based)

## 5. S7 Context Participation

- Historical context can inform intent (e.g., "do it again")
- Historical context is NEVER treated as current truth
- Current state must always come from fresh S2/S3 observation

## 6. LLM Boundary

- No LLM is currently integrated in S8.
- The architecture is prepared: IntentInterpreter can be swapped/extended with an LLM behind the same interface.
- If LLM is added later, it will produce candidate plans only — validation, authorization, execution, and verification remain owned by S2-S7.

## 7. Identity Transition Status

- User-facing server startup strings transitioned from ELYSIA -> Zarya.
- Internal tool names, dependency references, and repository history preserved intentionally.
- Full ELYSIA -> Zarya migration is a separate task (not part of S8 scope).

## 8. Server Integration

- New endpoint: `POST /intent` on `agent/server.py`
- Accepts: `{ "prompt": str, "authorized": bool }`
- Returns: `{ status, response, goal, work_result, plan }`
- Backward compatible: existing `/execute` endpoint untouched.

## 9. Test Coverage

- 12 unit + integration tests in `agent/test_intent.py`
- Covers: interpreter, validator, response translator, full pipeline
- All tests pass with zero S0-S7 regressions.
