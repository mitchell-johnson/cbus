"""Serial transport for C-Bus connections over UART.

Wraps pyserial-asyncio to provide managed serial connections
to ESP32 or PCI devices running the C-Bus protocol over serial/USB.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from cbus.transport.base import CBusTransport, TransportConfig, TransportError

logger = logging.getLogger(__name__)

DEFAULT_CBUS_BAUDRATE = 9600

try:
    from serial_asyncio import create_serial_connection
except ImportError:
    create_serial_connection = None


@dataclass
class SerialTransportConfig(TransportConfig):
    device: str = "/dev/ttyUSB0"
    baudrate: int = DEFAULT_CBUS_BAUDRATE


class SerialTransport(CBusTransport):
    """Serial transport for C-Bus PCI connections."""

    def __init__(self, config: SerialTransportConfig, protocol_factory: Optional[Callable] = None):
        super().__init__(config, protocol_factory)
        self._serial_config = config

    @property
    def transport_type(self) -> str:
        return "serial"

    @property
    def connection_info(self) -> Dict[str, Any]:
        return {
            "type": "serial",
            "device": self._serial_config.device,
            "baudrate": self._serial_config.baudrate,
        }

    async def _do_connect(self) -> Any:
        if create_serial_connection is None:
            raise TransportError("Serial support requires pyserial-asyncio")
        loop = asyncio.get_running_loop()
        transport, protocol = await create_serial_connection(
            loop,
            self._protocol_factory or (lambda: asyncio.Protocol()),
            self._serial_config.device,
            baudrate=self._serial_config.baudrate,
        )
        self._protocol = protocol
        logger.info(
            "Serial connected to %s @ %d baud",
            self._serial_config.device,
            self._serial_config.baudrate,
        )
        return transport

    async def _do_disconnect(self):
        try:
            if self._asyncio_transport:
                self._asyncio_transport.close()
                logger.info("Serial disconnected from %s", self._serial_config.device)
        finally:
            self._protocol = None
