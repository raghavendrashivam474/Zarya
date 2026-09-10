# ADR 0001 — Adopt ELYSIA v1 as Zarya S0 baseline

Date: 2026-09-10
Status: Accepted

## Context
Zarya is a personal desktop intelligence project. An existing working
desktop-agent (ELYSIA v1) provides most of the required capabilities.

## Decision
Adopt the ELYSIA repository as the Zarya S0 baseline via fork.
Preserve upstream as a remote for reference and future sync.

## Consequences
- We inherit ~91 tools across 22 modules.
- We do NOT rewrite inherited functionality in S0.
- Zarya identity is applied at the project/documentation layer first.
- Architectural changes require ADRs before implementation.

## Rules
Keep -> Wrap -> Improve -> Replace (in that order of preference).
