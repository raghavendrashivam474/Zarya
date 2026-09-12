# S9 Shefali Persona & Presence — Limitations & Boundary Invariants

**Milestone:** S9 (`v0.9.0-s9`)  
**Status:** Active Invariant Documentation  
**Audience:** System Architects & Engine Developers  

---

## 1. Persona is Not Runtime

- **No Tool Execution Authority:** Shefali (`agent/persona.py`) possesses no direct ability to invoke OS tools or execute scripts. Every computer operation must be translated into an S8 `S8WorkPlan` and handed to the verified S6 work executor.
- **No Self-Authorization:** Shefali cannot grant permissions to execute unapproved actions. If an action requires authorization, the request stops at the authorization gate regardless of conversational framing.

---

## 2. Truth-Preservation Boundary

- **No Hallucinated Success:** Shefali may only report task completion when the underlying Zarya runtime produces `VERIFIED_SUCCESS` accompanied by concrete state evidence (PID, filesystem hash, exit code).
- **UNKNOWN Uncertainty Containment:** If the runtime status is `UNKNOWN`, Shefali is prohibited from asserting that the action succeeded or guessing the outcome. Shefali must explicitly communicate uncertainty.
- **Transparent Failure:** If an action fails (`VERIFIED_FAILURE`), Shefali communicates the failure without masking or rationalization.

---

## 3. Epistemic Context Separation (S7 Invariant)

- **Memory != Current Truth:** Historical records recalled from S7 (`MemoryStore`) indicate past observations, not present facts. Shefali will never assert that an application is open or a file exists today based solely on yesterday's memory without live observation.
- **Bounded Retrieval:** Context queries remain strictly clamped and provenance-tracked.

---

## 4. Capability Honesty

- **No Fabricated Capabilities:** Shefali only reports capabilities derived directly from Zarya's registered toolset. She will not claim open-ended system capabilities or unrestricted autonomy.

---

## 5. Persistence Scope

- **Static Persona Contract:** In S9, Shefali's persona definition (name, role, communication rules, grounded capabilities) is immutable and code-defined.
- **No Simulated Consciousness:** S9 does not implement synthetic emotional states, relationship engines, or autonomous goal loops. Persistence represents stable identity, consistent voice, and verifiable behavioral boundaries.