"""EIP-1 Instance Identity.

Projects an externally visible instance identity from existing
Zarya identity sources:
  - agent.__version__ (product version)
  - agent.context.device.DeviceIdentity (device identity, S17)
  - Process-level UUID (instance identity, generated once per start)

This does NOT create a new identity system. It wraps existing ones.
"""

import uuid
import platform
import logging

from agent import __version__
from agent.ecosystem.protocol import PROTOCOL_VERSION

log = logging.getLogger("zarya.ecosystem.identity")

# Generated once per process lifetime.
# This identifies THIS running instance, not the device.
_INSTANCE_ID = str(uuid.uuid4())


def get_instance_identity(device_registry=None) -> dict:
    """Build the external identity descriptor.

    Args:
        device_registry: Optional DeviceRegistry from S17.
            If provided, includes device-level identity info.
            If None, returns instance-only identity.

    Returns:
        A dict suitable for JSON serialization.
    """
    identity = {
        "instance_id": _INSTANCE_ID,
        "product": "zarya",
        "version": __version__,
        "protocol": PROTOCOL_VERSION,
        "platform": platform.system().lower(),
        "architecture": platform.machine(),
    }

    # Project from S17 device identity if available
    if device_registry is not None:
        try:
            devices = device_registry.list_all()
            if devices:
                local = devices[0]  # Primary local device
                identity["device"] = {
                    "device_id": local.get("device_id", "unknown"),
                    "display_name": local.get("display_name", "unknown"),
                    "device_type": local.get("device_type", "unknown"),
                    "platform": local.get("platform", "unknown"),
                }
        except Exception as e:
            log.warning("Could not project device identity: %s", e)

    return identity


def get_instance_id() -> str:
    """Return the current instance UUID."""
    return _INSTANCE_ID
