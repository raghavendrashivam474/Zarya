# S15 — Context-Aware Computer Work: Architecture Report

This specification details the design patterns, programmatic signatures, and safety guarantees verified at milestone **S15**.

## 1. System Intent

The objective of S15 is to translate natural language contextual queries into verified computer actions without introducing security regressions or fragile heuristics.

```text
Natural Intent -> Context Engine -> Safety Gate -> Tool Executor -> S2 Verification
```

---

## 2. Workspace File Inventory

| File Name | Size (Bytes) | Last Modified |
|---|---|---|
| $(C:\Users\ragha\Documents\Anti-grav\Zarya\S15-Block1-DesktopObserver.ps1.Name) | 2347 | 2026-09-16 09:13:38 |
| $(C:\Users\ragha\Documents\Anti-grav\Zarya\S15-Block2-ArtifactResolver.ps1.Name) | 8217 | 2026-09-16 09:14:08 |
| $(C:\Users\ragha\Documents\Anti-grav\Zarya\S15-Block3-BrowserResolver.ps1.Name) | 9872 | 2026-09-16 09:18:49 |
| $(C:\Users\ragha\Documents\Anti-grav\Zarya\S15-Block4-IntentRouter.ps1.Name) | 12394 | 2026-09-16 09:21:02 |
| $(C:\Users\ragha\Documents\Anti-grav\Zarya\S15-Block5-ExecutionAndVerification.ps1.Name) | 16992 | 2026-09-16 09:23:38 |
| $(C:\Users\ragha\Documents\Anti-grav\Zarya\S15-DocumentWorkspace.ps1.Name) | 5736 | 2026-09-16 09:36:16 |
| $(C:\Users\ragha\Documents\Anti-grav\Zarya\S15-Handoff-Suite.ps1.Name) | 16912 | 2026-09-16 09:37:08 |

---

## 3. Public API Specification

The following public APIs are exposed by S15:

### Function: `Get-ZaryaContext`

> **Synopsis**: S13/S14 active computer context observation interface.

#### Parameter Signatures:
| Parameter | Type | Mandatory |
|---|---|---|
| *None* | | |

----------------------------------------

### Function: `Resolve-ZaryaTarget`

> **Synopsis**: Translates natural language intent and current context into verified targets.

#### Parameter Signatures:
| Parameter | Type | Mandatory |
|---|---|---|
| *None* | | |

----------------------------------------

### Function: `Invoke-ZaryaAction`

> **Synopsis**: Secure work execution envelope wrapping raw tool execution & S2 verification.

#### Parameter Signatures:
| Parameter | Type | Mandatory |
|---|---|---|
| *None* | | |

----------------------------------------

### Function: `Run-S15Diagnostics`

#### Parameter Signatures:
| Parameter | Type | Mandatory |
|---|---|---|
| *None* | | |

----------------------------------------


---

## 4. Safety Guard Decoupling Contracts

### Guard A: Context Is Not Permission
- Finding a file path in an active window title does not grant authorization to execute tool pipelines against that file.
- The pipeline routes through a formal UserAuthorized gate before tool dispatch occurs.

### Guard B: Multi-Match Ambiguity Halts
- If a document reference matching multiple locations is found, the system never guesses.
- Execution halts, returns state AMBIGUOUS, and generates a clear clarification prompt for the user.

### Guard C: Mutation Safety Gate
- Any write, edit, delete, or modify actions require an explicit ExplicitMutationConfirmed parameter set to true.
- Standard execution tokens are rejected with MUTATION_BLOCKED to prevent accidental overwrites during context-aware file edits.

---

## 5. Summary of Verified Diagnostics
All 5 diagnostic suites execute successfully and are programmatically confirmed on this system:
1. **Ambiguity Halted Test**: Confirmed safety halting.
2. **Decoupled Authorization Gate**: Confirmed security blocks.
3. **Mutation Gate Block**: Safe rejection of unconfirmed writes.
4. **Verified Mutation Action**: Confirmed execution under explicit elevation.
5. **Verified Read Action**: Golden path execution and verification.
