"""
S4: Failure Reasoning -- evidence-grounded failure explanation.

Consumes existing S2 verification results and S3 state observations
to produce structured failure explanations. Does NOT perform recovery,
retry, or any autonomous action.

Design principles:
  - Reason from evidence, never invent causes.
  - UNKNOWN verification produces INSUFFICIENT_EVIDENCE, never fabricated failure.
  - Confidence describes the explanation, not the failure itself.
  - Additive: never replaces verification or state fields.
  - Respects S3 freshness: stale evidence weakens confidence.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_UNKNOWN = "UNKNOWN"

CAT_APP_NOT_OBSERVED = "APPLICATION_NOT_OBSERVED"
CAT_APP_VERIF_UNAVAILABLE = "APPLICATION_VERIFICATION_UNAVAILABLE"
CAT_APP_VERIF_FAILED = "APPLICATION_VERIFICATION_FAILED"
CAT_FILE_NOT_CREATED = "FILE_NOT_CREATED"
CAT_FILE_CONTENT_MISMATCH = "FILE_CONTENT_MISMATCH"
CAT_FILE_VERIF_UNAVAILABLE = "FILE_VERIFICATION_UNAVAILABLE"
CAT_TERMINAL_ERROR = "TERMINAL_ERROR_DETECTED"
CAT_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"

STRENGTH_STRONG = "strong"
STRENGTH_WEAK = "weak"
STRENGTH_NONE = "none"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cap_confidence(base: str, freshness: str) -> str:
    """Cap confidence based on S3 state freshness.

    CURRENT  -> no cap
    STALE    -> HIGH capped to MEDIUM
    REQUIRES_REFRESH / UNKNOWN -> HIGH/MEDIUM capped to LOW
    """
    if freshness == "CURRENT":
        return base
    if freshness == "STALE":
        return CONFIDENCE_MEDIUM if base == CONFIDENCE_HIGH else base
    # REQUIRES_REFRESH or UNKNOWN
    if base in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM):
        return CONFIDENCE_LOW
    return base


def _build(
    category: str,
    summary: str,
    confidence: str,
    evidence: List[str],
    uncertainty: List[str],
    verification_status: str,
    freshness: str,
    verification_strength: str = STRENGTH_STRONG,
) -> Dict[str, Any]:
    """Construct a standardized failure explanation dict."""
    return {
        "category": category,
        "summary": summary,
        "confidence": confidence,
        "evidence": evidence,
        "uncertainty": uncertainty,
        "verification_strength": verification_strength,
        "source_verification_status": verification_status,
        "source_freshness": freshness,
    }


# ---------------------------------------------------------------------------
# Domain-specific reasoners (VERIFIED_FAILURE path)
# ---------------------------------------------------------------------------

def _reason_application(
    verification: Dict[str, Any],
    state: Dict[str, Any],
    freshness: str,
) -> Dict[str, Any]:
    method = verification.get("method", "")
    detail = verification.get("detail", "")
    image = verification.get(
        "image", state.get("state", {}).get("image", "")
    )

    # Probe not applicable (non-Windows, missing image spec)
    if method == "none":
        return _build(
            CAT_APP_VERIF_UNAVAILABLE,
            f"Application verification was not available: {detail}",
            _cap_confidence(CONFIDENCE_HIGH, freshness),
            [f"Verification method: none", f"Detail: {detail}"],
            ["Application may or may not have launched successfully."],
            "VERIFIED_FAILURE",
            freshness,
        )

    # Probe itself raised an exception
    if "failed" in detail.lower() or "exception" in detail.lower():
        return _build(
            CAT_APP_VERIF_FAILED,
            f"Application verification probe failed: {detail}",
            _cap_confidence(CONFIDENCE_MEDIUM, freshness),
            [f"Verification method: {method}", f"Detail: {detail}"],
            ["The verification mechanism itself encountered an error."],
            "VERIFIED_FAILURE",
            freshness,
        )

    # Default: process image not observed within polling window
    window = verification.get("observation_window_ms", "")
    evidence_items = [f"Expected process image '{image}' not observed"]
    if window:
        evidence_items.append(f"Observation window: {window}ms")

    return _build(
        CAT_APP_NOT_OBSERVED,
        f"Expected application process '{image}' was not observed after launch.",
        _cap_confidence(CONFIDENCE_MEDIUM, freshness),
        evidence_items,
        [
            "Process may have started and exited before observation.",
            "Launch mechanism return status is not captured.",
        ],
        "VERIFIED_FAILURE",
        freshness,
    )


def _reason_filesystem(
    verification: Dict[str, Any],
    state: Dict[str, Any],
    freshness: str,
) -> Dict[str, Any]:
    method = verification.get("method", "")
    detail = verification.get("detail", "")
    obs = verification.get("observation", {})
    path = obs.get("path", state.get("state", {}).get("path", ""))

    # File simply does not exist
    if method == "filesystem_exists" and obs.get("exists") is False:
        return _build(
            CAT_FILE_NOT_CREATED,
            f"File was not present at '{path}' after creation attempt.",
            _cap_confidence(CONFIDENCE_HIGH, freshness),
            [
                "filesystem_exists probe reported exists=False",
                f"Path: {path}",
            ],
            [],
            "VERIFIED_FAILURE",
            freshness,
        )

    # File exists but content does not match
    if method == "filesystem_content_check" and obs.get("content_matches") is False:
        return _build(
            CAT_FILE_CONTENT_MISMATCH,
            f"File exists at '{path}' but content does not match expected.",
            _cap_confidence(CONFIDENCE_HIGH, freshness),
            [
                "filesystem_content_check reported content_matches=False",
                f"File size: {obs.get('size_bytes', 'unknown')} bytes",
            ],
            [
                "Content may differ due to encoding, partial write, "
                "or external modification."
            ],
            "VERIFIED_FAILURE",
            freshness,
        )

    # Fallback for other filesystem verification failures
    return _build(
        CAT_FILE_VERIF_UNAVAILABLE,
        f"Filesystem verification could not confirm expected state: {detail}",
        _cap_confidence(CONFIDENCE_MEDIUM, freshness),
        [f"Method: {method}", f"Detail: {detail}"],
        ["File may exist correctly but verification was inconclusive."],
        "VERIFIED_FAILURE",
        freshness,
    )


def _reason_terminal(
    verification: Dict[str, Any],
    state: Dict[str, Any],
    freshness: str,
) -> Dict[str, Any]:
    obs = verification.get("observation", {})
    indicators = obs.get("error_indicators", [])
    command = obs.get("command", state.get("subject", ""))

    return _build(
        CAT_TERMINAL_ERROR,
        f"Terminal command produced error indicators: {', '.join(indicators)}",
        _cap_confidence(CONFIDENCE_MEDIUM, freshness),
        [
            f"Command output contains error indicators: "
            f"{', '.join(indicators)}"
        ],
        [
            "Exit code is not available; classification is based on "
            "output substring matching.",
            "Intended side effect may or may not have occurred.",
        ],
        "VERIFIED_FAILURE",
        freshness,
        verification_strength=STRENGTH_WEAK,
    )


# ---------------------------------------------------------------------------
# UNKNOWN verification path
# ---------------------------------------------------------------------------

def _reason_insufficient(
    verification: Dict[str, Any],
    state: Dict[str, Any],
    freshness: str,
) -> Dict[str, Any]:
    detail = verification.get("detail", "")
    method = verification.get("method", "")

    evidence_items: List[str] = []
    if method:
        evidence_items.append(f"Verification method: {method}")
    if detail:
        evidence_items.append(f"Detail: {detail}")
    if not evidence_items:
        evidence_items.append("No diagnostic evidence available.")

    return _build(
        CAT_INSUFFICIENT,
        "Verification did not produce sufficient evidence to determine outcome.",
        CONFIDENCE_UNKNOWN,
        evidence_items,
        ["Operation may have succeeded, failed, or been partial."],
        "UNKNOWN",
        freshness,
        verification_strength=STRENGTH_NONE,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reason_about_failure(
    verification: Dict[str, Any],
    state: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Produce a structured failure explanation from verification and state.

    Args:
        verification: S2 verification dict (status, method, detail, observation).
        state: S3 state dict (domain, subject, state, freshness, ...).

    Returns:
        Structured failure explanation dict, or None when verification
        indicates success (no failure to reason about).
    """
    status = verification.get("status", "UNKNOWN")

    if status == "VERIFIED_SUCCESS":
        return None

    domain = state.get("domain", "")
    freshness = state.get("freshness", "UNKNOWN")

    if status == "UNKNOWN":
        return _reason_insufficient(verification, state, freshness)

    # VERIFIED_FAILURE -- dispatch by domain
    if domain == "application":
        return _reason_application(verification, state, freshness)
    if domain == "filesystem":
        return _reason_filesystem(verification, state, freshness)
    if domain == "terminal":
        return _reason_terminal(verification, state, freshness)

    # Unknown domain -- generic fallback
    detail = verification.get("detail", "")
    return _build(
        CAT_INSUFFICIENT,
        f"Unrecognized domain '{domain}'; cannot classify failure.",
        CONFIDENCE_LOW,
        [f"Domain: {domain}", f"Detail: {detail}"],
        ["Failure classification requires domain-specific reasoning."],
        status,
        freshness,
    )


__all__ = [
    "reason_about_failure",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
    "CONFIDENCE_UNKNOWN",
    "CAT_APP_NOT_OBSERVED",
    "CAT_APP_VERIF_UNAVAILABLE",
    "CAT_APP_VERIF_FAILED",
    "CAT_FILE_NOT_CREATED",
    "CAT_FILE_CONTENT_MISMATCH",
    "CAT_FILE_VERIF_UNAVAILABLE",
    "CAT_TERMINAL_ERROR",
    "CAT_INSUFFICIENT",
]
