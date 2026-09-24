# N4.1 — PortableWork Validation
# Phase: N | Sprint: N4
# Baseline: N3 v1.3.0-n3 (frozen)
#
# Responsibility:
#   Validate incoming PortableWork BEFORE any resolution or execution.
#
# This module imports from the FROZEN N3 boundary to validate against
# the actual PortableWork schema. It does NOT modify N3.
#
# Rule: Invalid PortableWork must NEVER reach reconstruction or S18.

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

log = logging.getLogger("zarya.n4.validation")

# ── Import frozen N3 constants ──────────────────────────────────────
# We import the format version directly from N3 to stay in sync.
# If N3 is truly frozen, this will never change.
try:
    from agent.context.portable_work import (
        PORTABLE_WORK_FORMAT_VERSION,
        PortableWork,
    )
    _N3_AVAILABLE = True
except ImportError:
    _N3_AVAILABLE = False
    PORTABLE_WORK_FORMAT_VERSION = "n3-portable-v1"
    log.warning("N3 portable_work module not importable; using fallback constant")


# ── Validation result types ─────────────────────────────────────────

class ValidationVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


@dataclass
class ValidationIssue:
    """A single validation finding."""
    field_name: str
    severity: ValidationVerdict
    code: str
    message: str


@dataclass
class ValidationResult:
    """Aggregate result of PortableWork validation."""
    verdict: ValidationVerdict = ValidationVerdict.PASS
    format_version: str = ""
    work_id: str = ""
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.verdict in (ValidationVerdict.PASS, ValidationVerdict.WARN)

    def fail(self, field_name: str, code: str, message: str) -> None:
        self.verdict = ValidationVerdict.FAIL
        self.issues.append(ValidationIssue(
            field_name=field_name,
            severity=ValidationVerdict.FAIL,
            code=code,
            message=message,
        ))
        log.warning("N4 validation FAIL [%s] %s: %s", code, field_name, message)

    def warn(self, field_name: str, code: str, message: str) -> None:
        if self.verdict == ValidationVerdict.PASS:
            self.verdict = ValidationVerdict.WARN
        self.issues.append(ValidationIssue(
            field_name=field_name,
            severity=ValidationVerdict.WARN,
            code=code,
            message=message,
        ))
        log.info("N4 validation WARN [%s] %s: %s", code, field_name, message)


# ── Known N3 PortableWork fields (from recon: portable_work.py) ─────
# These are the fields that to_portable_dict() serializes.
# We validate against this known schema.

REQUIRED_FIELDS = frozenset({
    "format_version",
    "work_id",
    "intent",
    "plan_reference",
})

OPTIONAL_FIELDS = frozenset({
    "source_device",
    "execution_reference",
    "artifact_references",
    "requirements",
    "authorization_metadata",
    "context",
})

KNOWN_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

# Fields that must NEVER appear in a safe portable representation.
# N3 strips these, but we validate defensively on the target side.
FORBIDDEN_RUNTIME_FIELDS = frozenset({
    "hwnd",
    "pid",
    "process_id",
    "thread_id",
    "window_handle",
    "password",
    "token",
    "secret",
    "credential",
    "session_cookie",
    "api_key",
    "access_token",
    "refresh_token",
    "private_key",
})


# ── Core validation function ────────────────────────────────────────

def validate_portable_work(portable_dict: Dict[str, Any]) -> ValidationResult:
    """Validate a deserialized PortableWork dict.

    This is the N4 input gate. Nothing passes this without validation.

    Args:
        portable_dict: A dict produced by PortableWork.to_portable_dict()
                       or deserialized from PortableWork.from_json().

    Returns:
        ValidationResult with PASS/FAIL/WARN and detailed issues.
    """
    result = ValidationResult()

    if not isinstance(portable_dict, dict):
        result.fail("root", "INVALID_TYPE", f"Expected dict, got {type(portable_dict).__name__}")
        return result

    # ── 1. Format version ───────────────────────────────────────
    fmt = portable_dict.get("format_version", "")
    result.format_version = str(fmt)

    if not fmt:
        result.fail("format_version", "MISSING_VERSION", "format_version is required")
    elif fmt != PORTABLE_WORK_FORMAT_VERSION:
        result.fail(
            "format_version",
            "UNSUPPORTED_VERSION",
            f"Expected '{PORTABLE_WORK_FORMAT_VERSION}', got '{fmt}'",
        )

    # ── 2. Required fields ──────────────────────────────────────
    for req in REQUIRED_FIELDS:
        if req not in portable_dict:
            result.fail(req, "MISSING_FIELD", f"Required field '{req}' is absent")

    # ── 3. work_id integrity ────────────────────────────────────
    work_id = portable_dict.get("work_id", "")
    result.work_id = str(work_id)

    if not work_id or not isinstance(work_id, str):
        result.fail("work_id", "INVALID_WORK_ID", "work_id must be a non-empty string")
    elif len(work_id.strip()) == 0:
        result.fail("work_id", "BLANK_WORK_ID", "work_id must not be blank")

    # ── 4. plan_reference structure ─────────────────────────────
    plan_ref = portable_dict.get("plan_reference")
    if plan_ref is not None and not isinstance(plan_ref, dict):
        result.fail(
            "plan_reference",
            "INVALID_TYPE",
            f"plan_reference must be a dict, got {type(plan_ref).__name__}",
        )

    # ── 5. artifact_references structure ────────────────────────
    art_refs = portable_dict.get("artifact_references")
    if art_refs is not None:
        if not isinstance(art_refs, list):
            result.fail(
                "artifact_references",
                "INVALID_TYPE",
                f"artifact_references must be a list, got {type(art_refs).__name__}",
            )
        else:
            for i, ref in enumerate(art_refs):
                if not isinstance(ref, str) or not ref.strip():
                    result.fail(
                        f"artifact_references[{i}]",
                        "INVALID_ARTIFACT_REF",
                        "Each artifact reference must be a non-empty string",
                    )

    # ── 6. execution_reference type ─────────────────────────────
    exec_ref = portable_dict.get("execution_reference")
    if exec_ref is not None and not isinstance(exec_ref, str):
        result.fail(
            "execution_reference",
            "INVALID_TYPE",
            f"execution_reference must be str or None, got {type(exec_ref).__name__}",
        )

    # ── 7. Forbidden runtime fields (security gate) ─────────────
    _check_forbidden_fields(portable_dict, result)

    # ── 8. Unknown fields warning ───────────────────────────────
    for key in portable_dict:
        if key not in KNOWN_FIELDS:
            result.warn(
                key,
                "UNKNOWN_FIELD",
                f"Field '{key}' is not in the known N3 schema",
            )

    # ── 9. Intent must be non-empty ─────────────────────────────
    intent = portable_dict.get("intent", "")
    if isinstance(intent, str) and len(intent.strip()) == 0:
        result.fail("intent", "BLANK_INTENT", "intent must not be blank")

    if result.is_valid:
        log.info(
            "N4 validation PASS: work_id=%s, format=%s",
            result.work_id,
            result.format_version,
        )

    return result


def _check_forbidden_fields(data: Dict[str, Any], result: ValidationResult, prefix: str = "") -> None:
    """Recursively check for forbidden runtime-local fields."""
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        lower_key = key.lower()

        if lower_key in FORBIDDEN_RUNTIME_FIELDS:
            result.fail(
                full_key,
                "FORBIDDEN_FIELD",
                f"Runtime-local field '{full_key}' must not appear in PortableWork",
            )

        # Recurse into nested dicts
        if isinstance(value, dict):
            _check_forbidden_fields(value, result, prefix=full_key)


# ── Convenience: validate from JSON string ──────────────────────────

def validate_portable_json(json_str: str) -> ValidationResult:
    """Validate a PortableWork JSON string without fully deserializing.

    Parses JSON, then runs dict-level validation.
    """
    import json

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        r = ValidationResult()
        r.fail("root", "INVALID_JSON", f"Malformed JSON: {e}")
        return r

    return validate_portable_work(data)


# ── Convenience: validate a PortableWork instance ───────────────────

def validate_portable_instance(pw: "PortableWork") -> ValidationResult:
    """Validate an already-deserialized PortableWork object.

    Converts to dict via the frozen N3 method, then validates.
    """
    if not _N3_AVAILABLE:
        r = ValidationResult()
        r.fail("root", "N3_UNAVAILABLE", "Cannot validate instance without N3 module")
        return r

    if not isinstance(pw, PortableWork):
        r = ValidationResult()
        r.fail("root", "INVALID_TYPE", f"Expected PortableWork, got {type(pw).__name__}")
        return r

    return validate_portable_work(pw.to_portable_dict())