"""EIP-1 Authorization.

Provides token-based authorization for ecosystem boundary access.
Extends (does not replace) Zarya's existing boolean authorized flag.

Flow:
  1. Ecosystem consumer presents a token via X-Ecosystem-Token header.
  2. This module validates the token.
  3. If valid, the request proceeds to the existing Zarya auth path
     (authorized=True is passed to execute_work).
  4. If invalid, the request is rejected at the boundary.

The token can be pre-configured via ZARYA_ECOSYSTEM_TOKEN or generated
randomly once per process start.
"""

import os
import secrets
import logging

log = logging.getLogger("zarya.ecosystem.auth")

# Pre-configured via environment or generated randomly per process start
_ECOSYSTEM_TOKEN: str = os.environ.get("ZARYA_ECOSYSTEM_TOKEN") or secrets.token_urlsafe(32)

log.info("EIP-1 ecosystem token initialized")


def get_token() -> str:
    """Return the current ecosystem token.

    Used during startup to share the token with authorized local
    consumers (e.g., written to a local file or stdout).
    """
    return _ECOSYSTEM_TOKEN


def validate_token(token: str) -> bool:
    """Validate an ecosystem token.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        token: The token string to validate.

    Returns:
        True if the token is valid, False otherwise.
    """
    if not token or not isinstance(token, str):
        return False
    return secrets.compare_digest(token.strip(), _ECOSYSTEM_TOKEN)


def get_auth_instructions() -> dict:
    """Return instructions for how to authenticate.

    Useful for the /ecosystem/v1/auth-info endpoint.
    """
    return {
        "method": "header",
        "header_name": "X-Ecosystem-Token",
        "description": (
            "Include the ecosystem token in the X-Ecosystem-Token "
            "HTTP header on all requests."
        ),
    }
