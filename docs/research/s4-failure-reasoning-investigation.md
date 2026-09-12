# S4 - Failure Reasoning Investigation

**Status:** DRAFT (pre-implementation)
**Baseline:** v0.4.0-s3 (b3facb8)
**Branch:** zarya/s4-failure-reasoning
**Scope boundary:** REASONING ONLY. No recovery. No autonomous behavior. No persistence.

---

## 1. Purpose

Map the concrete failure evidence produced by S1/S2/S3 in each of the three active
tool domains (application, filesystem, terminal) so that S4 reasoning is grounded
in real evidence, not invented ontology.

This document must be complete and reviewed before any S4 implementation code
is written.

---

## 2. Evidence inventory per domain

### 2.1 Application domain

**Location:** agent/tools/applications.py, function _verify_application_launched()

**Evidence produced on each outcome:**

| Outcome            | method                | Evidence fields                                          |
|--------------------|-----------------------|----------------------------------------------------------|
| VERIFIED_SUCCESS   | process_image_check   | image, observation_window_ms, detail                     |
| VERIFIED_FAILURE   | process_image_check   | image, observation_window_ms, detail                     |
| UNKNOWN (no image) | none                  | detail only                                              |
| UNKNOWN (non-Win)  | none                  | detail (platform name)                                   |
| UNKNOWN (probe ex) | process_image_check   | image, detail (exception message)                        |

**S3 state captured:** domain=application, subject=image, state.running=bool

**What S4 CAN reason about:**
- Whether the expected process image was observed within the polling window
- Whether the verification mechanism itself was applicable/available

**What S4 CANNOT reason about (missing evidence):**
- Whether the launcher subprocess.Popen actually succeeded (return code not captured)
- Whether the process started and exited before observation window began
- Whether the process was blocked (UAC, antivirus, group policy)
- Whether the binary path resolution failed
- stderr from the launcher (not captured)

**S4 failure classes justified:**
- APPLICATION_NOT_OBSERVED
- APPLICATION_VERIFICATION_UNAVAILABLE
- APPLICATION_VERIFICATION_FAILED

**Confidence ceiling:** MEDIUM. We only know the process was not observed.

---

### 2.2 Filesystem domain

**Location:** agent/tools/files.py, function _verify_file_created()

**Evidence produced on each outcome:**

| Outcome                     | method                       | Evidence fields                                              |
|-----------------------------|------------------------------|--------------------------------------------------------------|
| VERIFIED_SUCCESS (exists)   | filesystem_exists            | observation.path, exists, size_bytes                         |
| VERIFIED_SUCCESS (content)  | filesystem_content_check     | observation.path, exists, size_bytes, content_matches=True   |
| VERIFIED_FAILURE (missing)  | filesystem_exists            | observation.path, exists=False                               |
| VERIFIED_FAILURE (mismatch) | filesystem_content_check     | observation.path, exists=True, size_bytes, content_matches=F |
| UNKNOWN (read exception)    | filesystem_content_check     | observation.path, exists=True, size_bytes, content_check_err |
| UNKNOWN (exists() throws)   | filesystem_exists            | observation.path, error                                      |

**S3 state captured:** domain=filesystem, subject=path, state.exists, state.size_bytes

**What S4 CAN reason about:**
- Whether the file exists at the expected path
- Whether the file content matches expected content
- Whether the verification probe itself failed
- Distinction between not-created vs created-but-wrong-contents

**What S4 CANNOT reason about:**
- Why the write did not persist (disk full, permission, antivirus rollback)
- Why content differs (encoding, partial write, external modification)

**S4 failure classes justified:**
- FILE_NOT_CREATED
- FILE_CONTENT_MISMATCH
- FILE_VERIFICATION_UNAVAILABLE

**Confidence ceiling:** HIGH for FILE_NOT_CREATED and FILE_CONTENT_MISMATCH.

---

### 2.3 Terminal domain

**Location:** agent/tools/terminal.py, function _verify_terminal_execution()

**Evidence produced on each outcome:**

| Outcome             | method                 | Evidence fields                                                |
|---------------------|------------------------|----------------------------------------------------------------|
| VERIFIED_SUCCESS    | terminal_output_check  | observation.command, output_length, has_output                 |
| VERIFIED_FAILURE    | terminal_output_check  | observation.command, output_length, has_output, error_indicators |
| UNKNOWN (verify ex) | terminal_output_check  | observation.command, error                                     |

**S3 state captured:** domain=terminal, subject=command, state.executed, state.has_output

**Documented backend limitation (from terminal.py source):**
This checks execution evidence, not environmental outcome. A command may
produce no errors but still fail to achieve its intended side effect.
Exit-code verification requires a backend change.

**What S4 CAN reason about:**
- Whether known error indicator substrings appeared in combined stdout+stderr
- Which specific error indicators were detected

**What S4 CANNOT reason about:**
- Whether the process exited with non-zero status (no exit code captured)
- Whether stderr contained an error (stdout and stderr are merged)
- Whether the intended side effect occurred
- Cause categorization beyond substring matching

**S4 failure classes justified:**
- TERMINAL_ERROR_DETECTED (with sub-classification by indicator)

**Confidence rules for terminal:**
- VERIFIED_SUCCESS from this probe is a WEAK signal (no known error strings
  does not mean the intended effect occurred).
- S4 must mark terminal success reasoning with verification_strength=weak.

---

## 3. Cross-domain S3 evidence

Every tool records a StateObservation via StateCache with:
- domain (application | filesystem | terminal)
- subject (image name | path | command)
- state (domain-specific dict)
- status (mirrored from verification)
- freshness (CURRENT | STALE | REQUIRES_REFRESH | UNKNOWN)
- timestamp

S4 reasoning must consult freshness. A VERIFIED_FAILURE with STALE freshness
carries less weight than one with CURRENT freshness.

---

## 4. Failure classes S4 will support (minimum viable set)

Grounded strictly in the evidence inventory above:

    APPLICATION_NOT_OBSERVED
    APPLICATION_VERIFICATION_UNAVAILABLE
    APPLICATION_VERIFICATION_FAILED
    FILE_NOT_CREATED
    FILE_CONTENT_MISMATCH
    FILE_VERIFICATION_UNAVAILABLE
    TERMINAL_ERROR_DETECTED
    INSUFFICIENT_EVIDENCE
    NO_FAILURE

---

## 5. Confidence model

    HIGH     - direct observation supports the classification
    MEDIUM   - indirect observation; alternatives remain plausible
    LOW      - evidence weakly supports classification
    UNKNOWN  - evidence is insufficient to classify

Confidence describes the explanation, not the failure itself.

---

## 6. Architecture decision (proposed, minimal)

Chosen: shared reasoner module consuming existing verification and state
payloads. No changes to tool contracts. Additive failure field.

Rejected:
- Domain-local reasoners (duplicates logic, mixes reasoning with execution)
- Centralized failure engine with event bus (over-engineered)
- Rule-based DSL / probabilistic scoring (premature)
- LLM diagnosis (crosses S5/S6/S10 boundaries)

---

## 7. Output contract (proposed)

Added to tool results as additive failure key. Never replaces verification or state.

For failures:
    failure.category, failure.summary, failure.confidence,
    failure.evidence[], failure.uncertainty[],
    failure.verification_strength, failure.source_verification_status,
    failure.source_freshness

For success: failure = null
For unknown: failure.category = INSUFFICIENT_EVIDENCE, confidence = UNKNOWN

---

## 8. Non-goals (hard boundary)

S4 will NOT: retry, restart, recover, select fallbacks, modify authorization,
persist history, run monitors, invoke LLM, alter S1/S2/S3 contracts,
fabricate evidence, or upgrade UNKNOWN into SUCCESS/FAILURE.

---

## 9. Test plan

- Classification tests for each failure class
- Confidence tests (strong -> HIGH, weak -> LOW, missing -> UNKNOWN)
- Freshness tests (CURRENT vs STALE)
- UNKNOWN preservation
- SUCCESS tests (failure = null)
- Cross-domain integration
- Contract preservation (27 existing tests green)

---

## 10. Open questions (resolve after reading state.py)

1. Does state.py expose freshness consumably without duplicating S3 logic?
2. Should reasoner accept StateObservation object or serialized dict?
3. How does the failure field interact with S2 contract integrity tests?

Sign-off gate: implementation begins only after Section 10 is resolved.
