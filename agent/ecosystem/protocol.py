"""EIP-1 Protocol Constants.

Defines the protocol identity and versioning for the ecosystem
boundary. External consumers must speak a supported version.
"""

PROTOCOL_NAME = "zarya-ecosystem"
PROTOCOL_VERSION = "eip-1.0"
SUPPORTED_VERSIONS = frozenset({"eip-1.0"})

# Message envelope keys (future use for non-HTTP transports)
MSG_TYPE_REQUEST = "request"
MSG_TYPE_RESPONSE = "response"
MSG_TYPE_ERROR = "error"
MSG_TYPE_EVENT = "event"

def is_version_supported(version: str) -> bool:
    """Check if a protocol version string is supported."""
    return version in SUPPORTED_VERSIONS
