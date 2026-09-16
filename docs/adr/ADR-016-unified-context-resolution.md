# ADR-016: Unified Context & Target Resolution

## Status
Accepted (S16)

## Context
S12–S15 introduced separate context systems for artifacts, desktop windows,
and browser pages. S15 demonstrated context-aware target resolution but
identified gaps: stale observations, brittle title parsing, simulated browser
execution, and no unified resolution entry point.

## Decision
Introduce `agent/context/` as a thin orchestration layer that:

1. **Classifies** natural-language references deterministically (no LLM)
2. **Checks freshness** of underlying observations (CURRENT/STALE/UNAVAILABLE)
3. **Re-observes** on-demand when stale (bounded, one attempt)
4. **Delegates** to existing S12/S13/S14 resolution systems

### Key architectural choices:
- `agent/context/resolver.py` is the single entry point (`resolve_context_reference`)
- `agent/context/references.py` maps NL phrases to `CanonicalReference` enums via regex
- `agent/context/freshness.py` reuses S3 freshness semantics
- `ActiveComputerContext` gains `update_browser_observation()` and
  `update_desktop_observation()` public methods
- `agent/work._interpolate_step_args` tries S16 resolver before S12 fallback
- Resolution results carry full evidence trails for S17 device identity

### What we did NOT do:
- Replace S12 artifact identity
- Replace S13 desktop observer
- Replace S14 browser runtime
- Add LLM-based resolution
- Add background monitoring
- Add autonomous retries

## Consequences
- Context resolution is now a reliable intermediary, not scattered behaviors
- Freshness prevents acting on stale observations
- Evidence trails enable future cross-device identity (S17)
- Backward compatible: S12 pronoun resolution still works as fallback
