# ADR 0002 — Fix ESM/CommonJS require() bug in desktop agent spawner

Date: 2026-09-10
Status: Accepted

## Context
server.ts is executed via `tsx server.ts` under Node 24 in ESM mode.
The inherited function `spawnDesktopAgent()` (server.ts line 142)
uses `const { spawn } = require('child_process')`.

`require` is not defined in ESM, so the call throws:
`[Desktop Agent] Boot probe failed: require is not defined`

Result: the Python desktop agent never auto-spawns.
All ~40 desktop tools silently fail.

## Current behavior
- Node server boots successfully on :3000.
- Voice/chat/Gemini interaction works.
- Any tool routed to Python agent returns 'Desktop agent is not running'.

## Proposal
Replace the inline `require('child_process')` with a top-level ESM
`import { spawn } from 'child_process'`.

This is a **minimal, reversible, single-line-region change**.
No refactor. No API change. No behavior change beyond fixing the bug.

## Alternatives considered
1. Add `createRequire` shim -> works but leaves inconsistent style.
2. Switch project to CommonJS -> huge, out of S0 scope.
3. Leave broken and run Python agent manually -> unacceptable UX.

## Impact
- Fixes silent failure of all desktop tools.
- No existing working feature changes.
- Change is <5 lines.

## Verification
- `npm run dev` should log `[Desktop Agent] Auto-spawned via Python`.
- Health probe at http://127.0.0.1:8765/health should return 200.
- Zarya should be able to execute `openApplication('notepad')`.
