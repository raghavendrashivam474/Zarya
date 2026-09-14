# S12 Research: Artifact Identity & Computer Context Continuity — Limitations & Future Scope

**Milestone:** S12  
**Status:** Complete  
**Scope:** Runtime target identity tracking and deterministic reference continuity.

---

## 1. Scope & Capabilities Achieved in S12

1. **Deterministic Target Continuity**:
   - Files created, read, modified, or targeted in step $N$ maintain an immutable canonical locator (`ArtifactIdentity`).
   - Subsequent steps in a `WorkPlan` or follow-up natural commands referring to "it", "that file", "the document", or "$ACTIVE_ARTIFACT" resolve strictly to the active verified artifact without guessing.

2. **Strict Verification Authority**:
   - UNKNOWN outcomes and failed operations (`VERIFIED_FAILURE`) never establish factual active artifacts.
   - S2 verification remains the sole authority for confirming existence on disk.

3. **Ambiguity Containment**:
   - When multiple candidates match a name query and no active artifact is uniquely selected, the system halts with `NEEDS_CLARIFICATION` rather than scanning disk or guessing.

4. **Multi-Domain Launcher Support**:
   - `openApplication` passes concrete target locators across Windows, macOS, and Linux backends to launch applications directly with their targeted files.

---

## 2. Documented Limitations in S12

1. **Primary Artifact Domain (Filesystem)**:
   - S12 prioritizes `FILE` artifacts (P0).
   - `APPLICATION` artifacts record active process states, but advanced sub-entities (individual browser tabs within a multi-tab session, specific terminal window handles across multiple workspaces) remain candidate extensions for future milestones.

2. **In-Memory Active Session Context**:
   - `ActiveComputerContext` maintains active targets during the live runtime session.
   - Cross-restart persistent context is preserved as historical evidence in S7 (`MemoryStore`), but historical records do not automatically overwrite live active session context unless explicitly recalled.

3. **Deterministic Reference Resolution (No Unbounded LLM Coreference)**:
   - Reference resolution uses deterministic pronoun binding and canonical path resolution.
   - Ambiguous queries outside established lexical patterns request user clarification rather than invoking non-deterministic LLM hallucinations.

4. **GUI Editor In-App Buffer Edits**:
   - In S12, file edits are verified on the filesystem substrate.
   - Direct automation of uncommitted in-memory GUI editor buffers (e.g. typing directly into a Notepad window without saving) relies on OS input tools + verified disk save, preserving the invariant that only verified disk changes constitute state transitions.

---

## 3. Future Roadmap

- **S13+ Extended Entities**: Expanding first-class `ArtifactIdentity` to cover dynamic browser DOM elements, persistent remote SSH sessions, and specific Hyprland window workspaces.
