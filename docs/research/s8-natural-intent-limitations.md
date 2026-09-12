# S8 Natural Intent — Known Limitations & Boundaries

**Date:** 2026-09-12
**Status:** DRAFT (populated during implementation)

---

## 1. Intent Understanding Boundaries
- Natural language intent translation is strictly deterministic and schema-bounded.
- Unknown/unsupported tools result in explicit rejection or clarification requests.

## 2. Authorization Boundary
- Natural intent parsing generates **Candidate Plans** only.
- Execution requires passing through the existing authorization gate.

## 3. Verification & Truth Boundary
- Natural language response cannot state an action succeeded unless verification returns VERIFIED_SUCCESS.
- UNKNOWN verification remains UNKNOWN in user responses.
