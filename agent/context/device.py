# S17 — Cross-Device Identity & Local Device Fabric
# Baseline: v0.16.0 (331a91c)
#
# This module owns:
#   - DeviceIdentity model
#   - DeviceRegistry (local, deterministic)
#   - resolve_device_reference()
#
# This module does NOT own:
#   - Flux integration (S18)
#   - Network discovery
#   - Transport or transfer
#   - Authorization decisions

