"""Deterministic natural-language reference classifier.

Maps user phrases to canonical semantic references using regex patterns.
No LLM involved — all classification is rule-based and testable.

Architecture (S16 Section 12):
    Reference pattern
          ↓
    Canonical semantic reference
          ↓
    Unified resolver
"""
import re
from enum import Enum


class CanonicalReference(Enum):
    """Canonical semantic reference types."""
    EXPLICIT_PATH = "EXPLICIT_PATH"
    CURRENT_DOCUMENT = "CURRENT_DOCUMENT"
    CURRENT_PAGE = "CURRENT_PAGE"
    CURRENT_WINDOW = "CURRENT_WINDOW"
    CURRENT_APPLICATION = "CURRENT_APPLICATION"
    UNKNOWN = "UNKNOWN"


# Ordered: first match wins. More specific patterns before general ones.
_REFERENCE_PATTERNS = [
    # ── Explicit paths and URLs (highest priority) ──
    (r'^[A-Za-z]:\\',                          CanonicalReference.EXPLICIT_PATH),
    (r'^https?://',                             CanonicalReference.EXPLICIT_PATH),
    (r'^~/|^/\w',                               CanonicalReference.EXPLICIT_PATH),
    (r'^\\\\',                                  CanonicalReference.EXPLICIT_PATH),  # UNC

    # ── Browser / page references ──
    (r'\bpage\s+i(?:\'m|\s+am)\s+on\b',        CanonicalReference.CURRENT_PAGE),
    (r'\bthe\s+page\b',                         CanonicalReference.CURRENT_PAGE),
    (r'\bthis\s+page\b',                        CanonicalReference.CURRENT_PAGE),
    (r'\bcurrent\s+page\b',                     CanonicalReference.CURRENT_PAGE),
    (r'\bactive\s+tab\b',                       CanonicalReference.CURRENT_PAGE),
    (r'\bcurrent\s+tab\b',                      CanonicalReference.CURRENT_PAGE),
    (r'\bthis\s+tab\b',                         CanonicalReference.CURRENT_PAGE),

    # ── Document / file references ──
    (r'\bdocument\s+i(?:\'m|\s+am)\s+(?:working\s+on|editing|reading)\b',
                                                CanonicalReference.CURRENT_DOCUMENT),
    (r'\bthe\s+document\b',                     CanonicalReference.CURRENT_DOCUMENT),
    (r'\bthis\s+document\b',                    CanonicalReference.CURRENT_DOCUMENT),
    (r'\bcurrent\s+document\b',                 CanonicalReference.CURRENT_DOCUMENT),
    (r'\bthis\s+file\b',                        CanonicalReference.CURRENT_DOCUMENT),
    (r'\bcurrent\s+file\b',                     CanonicalReference.CURRENT_DOCUMENT),
    (r'\bthe\s+file\b',                         CanonicalReference.CURRENT_DOCUMENT),
    (r'\bactive\s+file\b',                      CanonicalReference.CURRENT_DOCUMENT),

    # ── Window references ──
    (r'\bthis\s+window\b',                      CanonicalReference.CURRENT_WINDOW),
    (r'\bcurrent\s+window\b',                   CanonicalReference.CURRENT_WINDOW),
    (r'\bactive\s+window\b',                    CanonicalReference.CURRENT_WINDOW),

    # ── Application references ──
    (r'\bthis\s+(?:app|application)\b',         CanonicalReference.CURRENT_APPLICATION),
    (r'\bcurrent\s+(?:app|application)\b',      CanonicalReference.CURRENT_APPLICATION),
    (r'\bactive\s+(?:app|application)\b',       CanonicalReference.CURRENT_APPLICATION),
]

# Pre-compile for performance
_COMPILED = [
    (re.compile(pattern, re.IGNORECASE), ref)
    for pattern, ref in _REFERENCE_PATTERNS
]


def classify_reference(text: str) -> CanonicalReference:
    """Classify a natural-language reference deterministically.

    First matching pattern wins. No LLM. No guessing.

    Args:
        text: User reference phrase (e.g. "this document").

    Returns:
        CanonicalReference enum value.
    """
    if not text or not text.strip():
        return CanonicalReference.UNKNOWN

    normalized = text.strip().lower()

    for pattern, ref in _COMPILED:
        if pattern.search(normalized):
            return ref

    return CanonicalReference.UNKNOWN
