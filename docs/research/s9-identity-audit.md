# S9 Identity Taxonomy Audit: ELYSIA -> Zarya -> Shefali

**Milestone:** S9 (v0.9.0-s9)  
**Scope:** Whole-repository naming classification  
**Status:** Completed  

---

## 1. The Tripartite Identity Framework

S9 resolves all naming across three strictly bounded domains:

```text
       ┌─────────────────────────────────────────────────────────┐
       │                   SHEFALI (Persona)                     │
       │   - Conversational identity, tone, presence             │
       │   - UI assistant header, greeting, conversational replies│
       └────────────────────────────┬────────────────────────────┘
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │                    ZARYA (Runtime)                      │
       │   - Verified computer-work substrate (S0–S8)            │
       │   - Fast execution engine, state cache, verification    │
       └────────────────────────────┬────────────────────────────┘
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │                    ELYSIA (Legacy)                      │
       │   - Historical upstream origin, port variables          │
       │   - Backward-compatible env vars (ELYSIA_AGENT_PORT)    │
       └─────────────────────────────────────────────────────────┘
2. Classified Inventory of Occurrences
Layer / File    Found String    Classification    Resolution / Rule
agent/persona.py    Shefali    Persona (Active)    Authoritative identity definition
agent/persona.py    Zarya    System (Active)    Authoritative reference to underlying runtime
agent/server.py    Zarya Desktop Control Agent    System (Active)    Server OpenAPI title & description
agent/server.py    ELYSIA_AGENT_PORT    Legacy Compatibility    Preserved for non-breaking local daemon launch
server.ts / UI    Elysia / Zarya    User-Facing UI    Assistant persona labelled as Shefali (Zarya)
tests/test_s*.py    Zarya    System / Test    Standard runtime verification
start_elysia.*    elysia    Legacy Scripts    Retained for historical build script compatibility
3. Preservation Invariant
No environmental variables or daemon ports are changed arbitrarily (preventing breaks in external launch configs).
Internal tool registry namespaces remain stable.
All human-facing interaction endpoints explicitly present as Shefali, acting as the interface to Zarya.