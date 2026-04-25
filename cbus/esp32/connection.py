"""ESP32 connection manager for C-Bus.

Provides a high-level interface for connecting to ESP32 C-Bus bridge
devices over WiFi (TCP) or Serial (UART). Handles device-specific
initialization, health monitoring, and automatic reconnection.
"""
import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from cbus.protocol.pciprotocol import PCIProtocol
from cbus.transport.tcp import TCPTransport, TCPTransportConfig
from cbus.transport.serial import SerialTransport, SerialTransportConfig

logger = logging.getLogger(__name__)


class ESP32ConnectionMode(Enum):
    WIFI = "wifi"
    SERIAL = "serial"


@dataclass
class ESP32Info:
    firmware_version: str = "unknown"
    device_type: str = "ESP32"
    mac_address: str = ""
    ip_address: str = ""
    cbus_network_id: int = 254
    uptime_seconds: int = 0


@dataclass
class ESP32Config:
    mode: ESP32ConnectionMode = ESP32ConnectionMode.WIFI
    # WiFi/TCP settings
    host: str = "127.0.0.1"
    port: int = 10001
    # Serial settings
    device: str = ""
    baudrate: int = 9600
    # Common settings
    reconnect: bool = True
    reconnect_interval: float = 5.0
    max_reconnect_attempts: int = 0
    connect_timeout: float = 10.0
    heartbeat_interval: float = 30.0
    timesync_frequency: int = 300
    handle_clock_requests: bool = True

    @classmethod
    def wifi(cls, host: str, port: int = 10001, **kwargs) -> "ESP32Config":
        return cls(mode=ESP32ConnectionMode.WIFI, host=host, port=port, **kwargs)

    @classmethod
    def serial(cls, device: str, baudrate: int = 9600, **kwargs) -> "ESP32Config":
        return cls(mode=ESP32ConnectionMode.SERIAL, device=device, baudrate=baudrate, **kwargs)


class ESP32Connection:
    """Manages a connection to an ESP32 C-Bus bridge device."""

    def __init__(self, config: ESP32Config):
        self._config = config
        self._esp32_info = ESP32Info()
        self._protocol: Optional[PCIProtocol] = None
        self._connection_lost_future: Optional[asyncio.Future] = None

        if config.mode == ESP32ConnectionMode.WIFI:
            tcp_config = TCPTransportConfig(
                host=config.host,
                port=config.port,
                reconnect=config.reconnect,
                reconnect_interval=config.reconnect_interval,
                max_reconnect_attempts=config.max_reconnect_attempts,
                connect_timeout=config.connect_timeout,
                heartbeat_interval=config.heartbeat_interval,
            )
            self._transport = TCPTransport(tcp_config, self._create_protocol)
        else:
            serial_config = SerialTransportConfig(
                device=config.device,
                baudrate=config.baudrate,
                reconnect=config.reconnect,
                reconnect_interval=config.reconnect_interval,
                max_reconnect_attempts=config.max_reconnect_attempts,
                connect_timeout=config.connect_timeout,
                heartbeat_interval=config.heartbeat_interval,
            )
            self._transport = SerialTransport(serial_config, self._create_protocol)

    @property
    def transport(self):
        return self._transport

    @property
    def protocol(self) -> Optional[PCIProtocol]:
        return self._protocol

    @property
    def esp32_info(self) -> ESP32Info:
        return self._esp32_info

    @property
    def connection_info(self) -> Dict[str, Any]:
        info = self._transport.connection_info.copy()
        info["esp32_mode"] = self._config.mode.value
        return info

    def _create_protocol(self) -> PCIProtocol:
        loop = asyncio.get_running_loop()
        self._connection_lost_future = loop.create_future()
        self._protocol = PCIProtocol(
            timesync_frequency=self._config.timesync_frequency,
            handle_clock_requests=self._config.handle_clock_requests,
            connection_lost_future=self._connection_lost_future,
        )
        return self._protocol

    async def connect(self):
        await self._transport.connect()
        if self._config.mode == ESP32ConnectionMode.WIFI:
            self._esp32_info.ip_address = self._config.host
        logger.info("ESP32 connection established: %s", self.connection_info)

    async def disconnect(self):
        await self._transport.disconnect()
        self._protocol = None
        logger.info("ESP32 connection closed")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
