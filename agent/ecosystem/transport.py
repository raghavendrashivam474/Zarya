"""EIP-1 Transport Abstraction.

Currently, the ecosystem boundary uses HTTP via FastAPI routes.
This module defines the abstract transport interface so that
future IPC mechanisms (named pipes, Unix sockets, shared memory)
can be added without changing the protocol layer.

For EIP-1, HTTP is the only implemented transport.
"""

import logging
from abc import ABC, abstractmethod

log = logging.getLogger("zarya.ecosystem.transport")


class EcosystemTransport(ABC):
    """Abstract transport interface for ecosystem communication.

    Any transport implementation must handle:
    - Sending a request and receiving a response
    - Connection lifecycle (connect/disconnect)
    - Serialization (JSON by default)
    """

    @abstractmethod
    def connect(self) -> bool:
        """Establish the transport connection."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Tear down the transport connection."""
        ...

    @abstractmethod
    def send_request(self, endpoint: str, payload: dict) -> dict:
        """Send a request and return the response."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the transport is currently connected."""
        ...


class HttpTransport(EcosystemTransport):
    """HTTP transport via FastAPI (current implementation).

    The actual HTTP handling is done by FastAPI/uvicorn.
    This class exists for the external client side.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8765"):
        self._base_url = base_url
        self._connected = False

    def connect(self) -> bool:
        self._connected = True
        log.info("HTTP transport connected to %s", self._base_url)
        return True

    def disconnect(self) -> None:
        self._connected = False

    def send_request(self, endpoint: str, payload: dict) -> dict:
        raise NotImplementedError(
            "Client-side HTTP transport should use requests/httpx. "
            "This class defines the interface only."
        )

    @property
    def is_connected(self) -> bool:
        return self._connected
