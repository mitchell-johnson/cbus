"""TCP transport for C-Bus connections over WiFi or Ethernet.

Wraps asyncio's create_connection to provide managed TCP connections
to ESP32 or CNI devices running the C-Bus PCI protocol on a TCP socket.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from cbus.transport.base import CBusTransport, TransportConfig

logger = logging.getLogger(__name__)

DEFAULT_CBUS_TCP_PORT = 10001


@dataclass
class TCPTransportConfig(TransportConfig):
    host: str = "127.0.0.1"
    port: int = DEFAULT_CBUS_TCP_PORT

    @classmethod
    def from_address(cls, address: str, **kwargs) -> "TCPTransportConfig":
        if ":" in address:
            host, port_str = address.rsplit(":", 1)
            return cls(host=host, port=int(port_str), **kwargs)
        return cls(host=address, port=DEFAULT_CBUS_TCP_PORT, **kwargs)


class TCPTransport(CBusTransport):
    """TCP transport for C-Bus PCI connections."""

    def __init__(self, config: TCPTransportConfig, protocol_factory: Optional[Callable] = None):
        super().__init__(config, protocol_factory)
        self._tcp_config = config

    @property
    def transport_type(self) -> str:
        return "tcp"

    @property
    def connection_info(self) -> Dict[str, Any]:
        return {
            "type": "tcp",
            "host": self._tcp_config.host,
            "port": self._tcp_config.port,
        }

    async def _do_connect(self) -> Any:
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_connection(
            self._protocol_factory or (lambda: asyncio.Protocol()),
            self._tcp_config.host,
            self._tcp_config.port,
        )
        self._protocol = protocol
        logger.info("TCP connected to %s:%d", self._tcp_config.host, self._tcp_config.port)
        return transport

    async def _do_disconnect(self):
        try:
            if self._asyncio_transport:
                self._asyncio_transport.close()
                logger.info("TCP disconnected from %s:%d", self._tcp_config.host, self._tcp_config.port)
        finally:
            self._protocol = None
