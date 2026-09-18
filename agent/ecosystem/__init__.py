"""EIP-1: Ecosystem Integration Boundary for Zarya.

This package provides a versioned, authorized, capability-explicit
integration boundary through which external local systems can
discover and communicate with a running Zarya instance.

Core principle: Zarya remains sovereign and fully functional
without any ecosystem consumer.
"""

EIP_VERSION = "eip-1.0"

__all__ = [
    "EIP_VERSION",
    "protocol",
    "identity",
    "capabilities",
    "status",
    "authorization",
    "errors",
    "routes",
    "transport",
]
