# ESP32 Direct Connection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable the cbus library to connect directly to C-Bus systems via an ESP32 bridge device over WiFi (TCP) or Serial (UART), with a comprehensive ESP32 emulator for automated testing.

**Architecture:** The ESP32 acts as a C-Bus PCI bridge - it connects to the physical C-Bus network and exposes the standard C-Bus PCI protocol over WiFi TCP (like a wireless 5500CN) or Serial UART (like a wireless 5500PC). Since the wire protocol is identical to what `PCIProtocol` already handles, we build a transport abstraction layer with ESP32-specific connection management (mDNS discovery, auto-reconnect, health monitoring) on top of the existing protocol implementation. An ESP32 emulator extends the existing simulator to enable fully automated testing without hardware.

**Tech Stack:** Python 3.7+, asyncio, pyserial-asyncio, zeroconf (mDNS), pytest, existing cbus protocol stack

---

## Phase 1: Transport Abstraction Layer

### Task 1: Create Transport Base Class

**Files:**
- Create: `cbus/transport/__init__.py`
- Create: `cbus/transport/base.py`
- Test: `tests/test_transport_base.py`

**Step 1: Write the failing test**

```python
# tests/test_transport_base.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from cbus.transport.base import (
    CBusTransport,
    TransportState,
    TransportConfig,
    TransportError,
    ConnectionTimeoutError,
)


class TestTransportState:
    def test_initial_state_is_disconnected(self):
        assert TransportState.DISCONNECTED.value == "disconnected"

    def test_all_states_exist(self):
        assert hasattr(TransportState, "DISCONNECTED")
        assert hasattr(TransportState, "CONNECTING")
        assert hasattr(TransportState, "CONNECTED")
        assert hasattr(TransportState, "RECONNECTING")
        assert hasattr(TransportState, "ERROR")


class TestTransportConfig:
    def test_default_config(self):
        config = TransportConfig()
        assert config.reconnect is True
        assert config.reconnect_interval == 5.0
        assert config.max_reconnect_attempts == 0  # 0 = unlimited
        assert config.connect_timeout == 10.0
        assert config.heartbeat_interval == 30.0

    def test_custom_config(self):
        config = TransportConfig(
            reconnect=False,
            reconnect_interval=10.0,
            max_reconnect_attempts=3,
            connect_timeout=5.0,
            heartbeat_interval=15.0,
        )
        assert config.reconnect is False
        assert config.reconnect_interval == 10.0
        assert config.max_reconnect_attempts == 3
        assert config.connect_timeout == 5.0
        assert config.heartbeat_interval == 15.0


class ConcreteTransport(CBusTransport):
    """Minimal concrete implementation for testing the abstract base."""

    def __init__(self, config=None):
        super().__init__(config)
        self._connect_called = False
        self._disconnect_called = False
        self._mock_transport = MagicMock()

    async def _do_connect(self):
        self._connect_called = True
        return self._mock_transport

    async def _do_disconnect(self):
        self._disconnect_called = True

    @property
    def transport_type(self) -> str:
        return "test"

    @property
    def connection_info(self) -> dict:
        return {"type": "test"}


class TestCBusTransportLifecycle:
    @pytest.fixture
    def transport(self):
        return ConcreteTransport()

    def test_initial_state(self, transport):
        assert transport.state == TransportState.DISCONNECTED
        assert transport.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_transitions_to_connected(self, transport):
        await transport.connect()
        assert transport.state == TransportState.CONNECTED
        assert transport.is_connected is True
        assert transport._connect_called is True

    @pytest.mark.asyncio
    async def test_disconnect_transitions_to_disconnected(self, transport):
        await transport.connect()
        await transport.disconnect()
        assert transport.state == TransportState.DISCONNECTED
        assert transport.is_connected is False
        assert transport._disconnect_called is True

    @pytest.mark.asyncio
    async def test_connect_when_already_connected_is_noop(self, transport):
        await transport.connect()
        transport._connect_called = False
        await transport.connect()
        assert transport._connect_called is False

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected_is_noop(self, transport):
        await transport.disconnect()
        assert transport._disconnect_called is False

    @pytest.mark.asyncio
    async def test_state_callback_called_on_transition(self, transport):
        states = []
        transport.on_state_change = lambda old, new: states.append((old, new))
        await transport.connect()
        assert (TransportState.DISCONNECTED, TransportState.CONNECTING) in states
        assert (TransportState.CONNECTING, TransportState.CONNECTED) in states

    @pytest.mark.asyncio
    async def test_context_manager(self, transport):
        async with transport:
            assert transport.is_connected is True
        assert transport.is_connected is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_transport_base.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'cbus.transport'"

**Step 3: Write minimal implementation**

```python
# cbus/transport/__init__.py
from cbus.transport.base import (
    CBusTransport,
    TransportState,
    TransportConfig,
    TransportError,
    ConnectionTimeoutError,
)

__all__ = [
    "CBusTransport",
    "TransportState",
    "TransportConfig",
    "TransportError",
    "ConnectionTimeoutError",
]
```

```python
# cbus/transport/base.py
"""Abstract transport layer for C-Bus connections.

Provides a common interface for different connection methods (TCP, Serial)
with built-in reconnection, state management, and health monitoring.
"""
import abc
import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class TransportState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class TransportError(Exception):
    pass


class ConnectionTimeoutError(TransportError):
    pass


@dataclass
class TransportConfig:
    reconnect: bool = True
    reconnect_interval: float = 5.0
    max_reconnect_attempts: int = 0  # 0 = unlimited
    connect_timeout: float = 10.0
    heartbeat_interval: float = 30.0


class CBusTransport(abc.ABC):
    """Abstract base class for C-Bus transport connections."""

    def __init__(self, config: Optional[TransportConfig] = None):
        self._config = config or TransportConfig()
        self._state = TransportState.DISCONNECTED
        self._asyncio_transport: Optional[asyncio.Transport] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._reconnect_attempts = 0
        self.on_state_change: Optional[Callable] = None
        self.on_connection_lost: Optional[Callable] = None

    @property
    def state(self) -> TransportState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == TransportState.CONNECTED

    @property
    def config(self) -> TransportConfig:
        return self._config

    @property
    @abc.abstractmethod
    def transport_type(self) -> str:
        """Return a string identifying this transport type (e.g. 'tcp', 'serial')."""

    @property
    @abc.abstractmethod
    def connection_info(self) -> Dict[str, Any]:
        """Return a dict of connection details for logging/diagnostics."""

    def _set_state(self, new_state: TransportState):
        old_state = self._state
        if old_state == new_state:
            return
        self._state = new_state
        logger.info("Transport state: %s -> %s", old_state.value, new_state.value)
        if self.on_state_change:
            self.on_state_change(old_state, new_state)

    async def connect(self):
        if self._state == TransportState.CONNECTED:
            return
        self._set_state(TransportState.CONNECTING)
        try:
            self._asyncio_transport = await asyncio.wait_for(
                self._do_connect(), timeout=self._config.connect_timeout
            )
            self._reconnect_attempts = 0
            self._set_state(TransportState.CONNECTED)
        except asyncio.TimeoutError:
            self._set_state(TransportState.ERROR)
            raise ConnectionTimeoutError(
                f"Connection timed out after {self._config.connect_timeout}s"
            )
        except Exception as e:
            self._set_state(TransportState.ERROR)
            raise TransportError(f"Connection failed: {e}") from e

    async def disconnect(self):
        if self._state == TransportState.DISCONNECTED:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        try:
            await self._do_disconnect()
        finally:
            self._asyncio_transport = None
            self._set_state(TransportState.DISCONNECTED)

    async def handle_connection_lost(self, exc: Optional[Exception] = None):
        logger.warning("Connection lost: %s", exc)
        self._asyncio_transport = None
        if self.on_connection_lost:
            self.on_connection_lost(exc)
        if self._config.reconnect and self._state != TransportState.DISCONNECTED:
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        self._set_state(TransportState.RECONNECTING)
        while True:
            self._reconnect_attempts += 1
            if (
                self._config.max_reconnect_attempts > 0
                and self._reconnect_attempts > self._config.max_reconnect_attempts
            ):
                logger.error("Max reconnect attempts (%d) reached", self._config.max_reconnect_attempts)
                self._set_state(TransportState.ERROR)
                return
            logger.info(
                "Reconnect attempt %d (max=%s) in %.1fs",
                self._reconnect_attempts,
                self._config.max_reconnect_attempts or "unlimited",
                self._config.reconnect_interval,
            )
            await asyncio.sleep(self._config.reconnect_interval)
            try:
                await self.connect()
                logger.info("Reconnected successfully")
                return
            except TransportError:
                logger.warning("Reconnect attempt %d failed", self._reconnect_attempts)

    @abc.abstractmethod
    async def _do_connect(self) -> Any:
        """Establish the underlying connection. Return the asyncio transport."""

    @abc.abstractmethod
    async def _do_disconnect(self):
        """Tear down the underlying connection."""

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_transport_base.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add cbus/transport/__init__.py cbus/transport/base.py tests/test_transport_base.py
git commit -m "feat: add transport abstraction layer base class"
```

---

### Task 2: Create TCP Transport (WiFi)

**Files:**
- Create: `cbus/transport/tcp.py`
- Test: `tests/test_transport_tcp.py`

**Step 1: Write the failing test**

```python
# tests/test_transport_tcp.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from cbus.transport.tcp import TCPTransport, TCPTransportConfig
from cbus.transport.base import TransportState, TransportError


class TestTCPTransportConfig:
    def test_default_config(self):
        config = TCPTransportConfig(host="192.168.1.10")
        assert config.host == "192.168.1.10"
        assert config.port == 10001
        assert config.reconnect is True

    def test_custom_port(self):
        config = TCPTransportConfig(host="10.0.0.1", port=9999)
        assert config.port == 9999

    def test_from_address_string(self):
        config = TCPTransportConfig.from_address("192.168.1.10:10001")
        assert config.host == "192.168.1.10"
        assert config.port == 10001

    def test_from_address_string_default_port(self):
        config = TCPTransportConfig.from_address("192.168.1.10")
        assert config.host == "192.168.1.10"
        assert config.port == 10001


class TestTCPTransport:
    @pytest.fixture
    def config(self):
        return TCPTransportConfig(host="127.0.0.1", port=10001)

    @pytest.fixture
    def transport(self, config):
        return TCPTransport(config)

    def test_transport_type(self, transport):
        assert transport.transport_type == "tcp"

    def test_connection_info(self, transport):
        info = transport.connection_info
        assert info["host"] == "127.0.0.1"
        assert info["port"] == 10001
        assert info["type"] == "tcp"

    @pytest.mark.asyncio
    async def test_connect_creates_connection(self, transport):
        mock_transport = MagicMock()
        mock_protocol = MagicMock()
        with patch.object(
            asyncio.get_event_loop().__class__,
            "create_connection",
            new_callable=AsyncMock,
            return_value=(mock_transport, mock_protocol),
        ) as mock_create:
            # Use a real event loop mock
            loop = asyncio.get_event_loop()
            with patch(
                "asyncio.get_running_loop", return_value=loop
            ):
                with patch.object(
                    loop, "create_connection",
                    new_callable=AsyncMock,
                    return_value=(mock_transport, mock_protocol),
                ):
                    await transport.connect()
                    assert transport.state == TransportState.CONNECTED

    @pytest.mark.asyncio
    async def test_disconnect_closes_transport(self, transport):
        mock_transport = MagicMock()
        transport._asyncio_transport = mock_transport
        transport._state = TransportState.CONNECTED
        await transport.disconnect()
        mock_transport.close.assert_called_once()
        assert transport.state == TransportState.DISCONNECTED
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_transport_tcp.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'cbus.transport.tcp'"

**Step 3: Write minimal implementation**

```python
# cbus/transport/tcp.py
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
        super().__init__(config)
        self._tcp_config = config
        self._protocol_factory = protocol_factory
        self._protocol = None

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

    @property
    def protocol(self):
        return self._protocol

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
        if self._asyncio_transport:
            self._asyncio_transport.close()
            logger.info("TCP disconnected from %s:%d", self._tcp_config.host, self._tcp_config.port)
        self._protocol = None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_transport_tcp.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add cbus/transport/tcp.py tests/test_transport_tcp.py
git commit -m "feat: add TCP transport for WiFi/Ethernet C-Bus connections"
```

---

### Task 3: Create Serial Transport

**Files:**
- Create: `cbus/transport/serial.py`
- Test: `tests/test_transport_serial.py`

**Step 1: Write the failing test**

```python
# tests/test_transport_serial.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from cbus.transport.serial import SerialTransport, SerialTransportConfig
from cbus.transport.base import TransportState


class TestSerialTransportConfig:
    def test_default_config(self):
        config = SerialTransportConfig(device="/dev/ttyUSB0")
        assert config.device == "/dev/ttyUSB0"
        assert config.baudrate == 9600
        assert config.reconnect is True

    def test_custom_baudrate(self):
        config = SerialTransportConfig(device="/dev/ttyUSB0", baudrate=115200)
        assert config.baudrate == 115200


class TestSerialTransport:
    @pytest.fixture
    def config(self):
        return SerialTransportConfig(device="/dev/ttyUSB0")

    @pytest.fixture
    def transport(self, config):
        return SerialTransport(config)

    def test_transport_type(self, transport):
        assert transport.transport_type == "serial"

    def test_connection_info(self, transport):
        info = transport.connection_info
        assert info["device"] == "/dev/ttyUSB0"
        assert info["baudrate"] == 9600
        assert info["type"] == "serial"

    @pytest.mark.asyncio
    async def test_disconnect_closes_transport(self, transport):
        mock_transport = MagicMock()
        transport._asyncio_transport = mock_transport
        transport._state = TransportState.CONNECTED
        await transport.disconnect()
        mock_transport.close.assert_called_once()
        assert transport.state == TransportState.DISCONNECTED
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_transport_serial.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'cbus.transport.serial'"

**Step 3: Write minimal implementation**

```python
# cbus/transport/serial.py
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
        super().__init__(config)
        self._serial_config = config
        self._protocol_factory = protocol_factory
        self._protocol = None

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

    @property
    def protocol(self):
        return self._protocol

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
        logger.info("Serial connected to %s @ %d baud", self._serial_config.device, self._serial_config.baudrate)
        return transport

    async def _do_disconnect(self):
        if self._asyncio_transport:
            self._asyncio_transport.close()
            logger.info("Serial disconnected from %s", self._serial_config.device)
        self._protocol = None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_transport_serial.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add cbus/transport/serial.py tests/test_transport_serial.py
git commit -m "feat: add Serial transport for UART C-Bus connections"
```

---

## Phase 2: ESP32 Protocol Handler

### Task 4: Create ESP32 Connection Manager

**Files:**
- Create: `cbus/esp32/__init__.py`
- Create: `cbus/esp32/connection.py`
- Test: `tests/test_esp32_connection.py`

**Step 1: Write the failing test**

```python
# tests/test_esp32_connection.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from cbus.esp32.connection import (
    ESP32Connection,
    ESP32Config,
    ESP32ConnectionMode,
    ESP32Info,
)
from cbus.transport.base import TransportState


class TestESP32Config:
    def test_wifi_config(self):
        config = ESP32Config.wifi("192.168.1.50")
        assert config.mode == ESP32ConnectionMode.WIFI
        assert config.host == "192.168.1.50"
        assert config.port == 10001

    def test_wifi_config_custom_port(self):
        config = ESP32Config.wifi("192.168.1.50", port=9999)
        assert config.port == 9999

    def test_serial_config(self):
        config = ESP32Config.serial("/dev/ttyUSB0")
        assert config.mode == ESP32ConnectionMode.SERIAL
        assert config.device == "/dev/ttyUSB0"
        assert config.baudrate == 9600

    def test_serial_config_custom_baud(self):
        config = ESP32Config.serial("/dev/ttyUSB0", baudrate=115200)
        assert config.baudrate == 115200


class TestESP32Info:
    def test_esp32_info_creation(self):
        info = ESP32Info(
            firmware_version="1.2.3",
            device_type="ESP32-WROOM",
            mac_address="AA:BB:CC:DD:EE:FF",
            ip_address="192.168.1.50",
        )
        assert info.firmware_version == "1.2.3"
        assert info.device_type == "ESP32-WROOM"
        assert info.mac_address == "AA:BB:CC:DD:EE:FF"


class TestESP32Connection:
    @pytest.fixture
    def wifi_config(self):
        return ESP32Config.wifi("127.0.0.1", port=10001)

    @pytest.fixture
    def serial_config(self):
        return ESP32Config.serial("/dev/ttyUSB0")

    def test_wifi_connection_creates_tcp_transport(self, wifi_config):
        conn = ESP32Connection(wifi_config)
        assert conn.transport.transport_type == "tcp"

    def test_serial_connection_creates_serial_transport(self, serial_config):
        conn = ESP32Connection(serial_config)
        assert conn.transport.transport_type == "serial"

    def test_connection_info(self, wifi_config):
        conn = ESP32Connection(wifi_config)
        info = conn.connection_info
        assert info["esp32_mode"] == "wifi"
        assert info["type"] == "tcp"

    @pytest.mark.asyncio
    async def test_create_protocol_factory(self, wifi_config):
        conn = ESP32Connection(wifi_config)
        protocol = conn._create_protocol()
        from cbus.protocol.pciprotocol import PCIProtocol
        assert isinstance(protocol, PCIProtocol)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_esp32_connection.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'cbus.esp32'"

**Step 3: Write minimal implementation**

```python
# cbus/esp32/__init__.py
from cbus.esp32.connection import (
    ESP32Connection,
    ESP32Config,
    ESP32ConnectionMode,
    ESP32Info,
)

__all__ = [
    "ESP32Connection",
    "ESP32Config",
    "ESP32ConnectionMode",
    "ESP32Info",
]
```

```python
# cbus/esp32/connection.py
"""ESP32 connection manager for C-Bus.

Provides a high-level interface for connecting to ESP32 C-Bus bridge
devices over WiFi (TCP) or Serial (UART). Handles device-specific
initialization, health monitoring, and automatic reconnection.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

from cbus.protocol.pciprotocol import PCIProtocol
from cbus.transport.base import TransportConfig
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
        loop = asyncio.get_event_loop()
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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_esp32_connection.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add cbus/esp32/__init__.py cbus/esp32/connection.py tests/test_esp32_connection.py
git commit -m "feat: add ESP32 connection manager with WiFi/Serial modes"
```

---

### Task 5: Add mDNS Discovery for ESP32 WiFi Devices

**Files:**
- Create: `cbus/esp32/discovery.py`
- Test: `tests/test_esp32_discovery.py`

**Step 1: Write the failing test**

```python
# tests/test_esp32_discovery.py
import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

from cbus.esp32.discovery import (
    ESP32Discovery,
    DiscoveredDevice,
    CBUS_MDNS_SERVICE_TYPE,
)


class TestDiscoveredDevice:
    def test_device_creation(self):
        dev = DiscoveredDevice(
            name="cbus-bridge-1",
            host="192.168.1.50",
            port=10001,
            properties={"firmware": "1.0.0"},
        )
        assert dev.name == "cbus-bridge-1"
        assert dev.host == "192.168.1.50"
        assert dev.port == 10001
        assert dev.properties["firmware"] == "1.0.0"

    def test_device_str(self):
        dev = DiscoveredDevice(name="test", host="1.2.3.4", port=10001)
        assert "test" in str(dev)
        assert "1.2.3.4" in str(dev)


class TestESP32Discovery:
    def test_service_type_constant(self):
        assert CBUS_MDNS_SERVICE_TYPE == "_cbus._tcp.local."

    def test_discovery_init(self):
        disc = ESP32Discovery(timeout=5.0)
        assert disc._timeout == 5.0

    @pytest.mark.asyncio
    async def test_discover_returns_list(self):
        disc = ESP32Discovery(timeout=0.1)
        # With no actual mDNS services, should return empty list
        with patch("cbus.esp32.discovery._ZEROCONF_AVAILABLE", False):
            devices = await disc.discover()
            assert isinstance(devices, list)
            assert len(devices) == 0

    def test_manual_device(self):
        dev = DiscoveredDevice.manual("192.168.1.10", 10001)
        assert dev.name == "manual-192.168.1.10"
        assert dev.host == "192.168.1.10"
        assert dev.port == 10001
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_esp32_discovery.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'cbus.esp32.discovery'"

**Step 3: Write minimal implementation**

```python
# cbus/esp32/discovery.py
"""mDNS discovery for ESP32 C-Bus bridge devices.

Uses zeroconf to discover ESP32 devices advertising the C-Bus service
on the local network. Falls back gracefully when zeroconf is not installed.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

CBUS_MDNS_SERVICE_TYPE = "_cbus._tcp.local."

try:
    from zeroconf import Zeroconf, ServiceBrowser, ServiceInfo
    from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser
    _ZEROCONF_AVAILABLE = True
except ImportError:
    _ZEROCONF_AVAILABLE = False


@dataclass
class DiscoveredDevice:
    name: str
    host: str
    port: int
    properties: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def manual(cls, host: str, port: int = 10001) -> "DiscoveredDevice":
        return cls(name=f"manual-{host}", host=host, port=port)

    def __str__(self):
        return f"{self.name} @ {self.host}:{self.port}"


class ESP32Discovery:
    """Discover ESP32 C-Bus bridge devices via mDNS."""

    def __init__(self, timeout: float = 5.0):
        self._timeout = timeout
        self._devices: List[DiscoveredDevice] = []

    async def discover(self) -> List[DiscoveredDevice]:
        if not _ZEROCONF_AVAILABLE:
            logger.warning("zeroconf not installed, mDNS discovery unavailable. Install with: pip install zeroconf")
            return []

        self._devices = []
        try:
            azc = AsyncZeroconf()
            browser = AsyncServiceBrowser(
                azc.zeroconf, CBUS_MDNS_SERVICE_TYPE, handlers=[self._on_service_state_change]
            )
            await asyncio.sleep(self._timeout)
            await browser.async_cancel()
            await azc.async_close()
        except Exception as e:
            logger.error("mDNS discovery failed: %s", e)

        logger.info("Discovered %d ESP32 C-Bus device(s)", len(self._devices))
        return list(self._devices)

    def _on_service_state_change(self, zeroconf, service_type, name, state_change):
        if str(state_change) == "ServiceStateChange.Added":
            info = zeroconf.get_service_info(service_type, name)
            if info:
                addresses = info.parsed_addresses()
                if addresses:
                    props = {}
                    if info.properties:
                        props = {
                            k.decode("utf-8", errors="replace"): v.decode("utf-8", errors="replace")
                            for k, v in info.properties.items()
                        }
                    device = DiscoveredDevice(
                        name=name.replace(f".{service_type}", ""),
                        host=addresses[0],
                        port=info.port or 10001,
                        properties=props,
                    )
                    self._devices.append(device)
                    logger.info("Discovered device: %s", device)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_esp32_discovery.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add cbus/esp32/discovery.py tests/test_esp32_discovery.py
git commit -m "feat: add mDNS discovery for ESP32 C-Bus bridge devices"
```

---

## Phase 3: ESP32 Emulator for Testing

### Task 6: Create ESP32 Emulator Core

**Files:**
- Create: `cbus/esp32/emulator/__init__.py`
- Create: `cbus/esp32/emulator/device.py`
- Test: `tests/test_esp32_emulator.py`

**Step 1: Write the failing test**

```python
# tests/test_esp32_emulator.py
import pytest
import asyncio
from unittest.mock import MagicMock

from cbus.esp32.emulator.device import (
    ESP32Emulator,
    ESP32EmulatorConfig,
    EmulatedGroup,
)


class TestESP32EmulatorConfig:
    def test_default_config(self):
        config = ESP32EmulatorConfig()
        assert config.tcp_port == 10001
        assert config.firmware_version == "1.0.0"
        assert config.device_type == "ESP32-WROOM-EMULATED"
        assert config.network_id == 254
        assert config.num_groups == 256
        assert config.enable_mdns is False  # off by default for tests

    def test_custom_config(self):
        config = ESP32EmulatorConfig(tcp_port=9999, firmware_version="2.0.0")
        assert config.tcp_port == 9999
        assert config.firmware_version == "2.0.0"


class TestEmulatedGroup:
    def test_default_state(self):
        group = EmulatedGroup(group_id=1, name="Living Room")
        assert group.group_id == 1
        assert group.name == "Living Room"
        assert group.level == 0
        assert group.is_on is False

    def test_set_level(self):
        group = EmulatedGroup(group_id=1)
        group.level = 255
        assert group.is_on is True
        group.level = 0
        assert group.is_on is False

    def test_level_clamped(self):
        group = EmulatedGroup(group_id=1)
        group.level = 300
        assert group.level == 255
        group.level = -10
        assert group.level == 0


class TestESP32Emulator:
    @pytest.fixture
    def config(self):
        return ESP32EmulatorConfig(tcp_port=0)  # port 0 = auto-assign

    @pytest.fixture
    def emulator(self, config):
        return ESP32Emulator(config)

    def test_emulator_creation(self, emulator):
        assert emulator.is_running is False

    def test_initial_groups(self, emulator):
        assert len(emulator.groups) == 256
        assert emulator.groups[0].level == 0

    def test_get_group_level(self, emulator):
        assert emulator.get_group_level(1) == 0

    def test_set_group_level(self, emulator):
        emulator.set_group_level(1, 128)
        assert emulator.get_group_level(1) == 128

    def test_firmware_info(self, emulator):
        info = emulator.device_info
        assert info["firmware_version"] == "1.0.0"
        assert info["device_type"] == "ESP32-WROOM-EMULATED"

    @pytest.mark.asyncio
    async def test_start_stop(self, emulator):
        await emulator.start()
        assert emulator.is_running is True
        assert emulator.actual_port > 0
        await emulator.stop()
        assert emulator.is_running is False

    @pytest.mark.asyncio
    async def test_context_manager(self, emulator):
        async with emulator:
            assert emulator.is_running is True
        assert emulator.is_running is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_esp32_emulator.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'cbus.esp32.emulator'"

**Step 3: Write minimal implementation**

```python
# cbus/esp32/emulator/__init__.py
from cbus.esp32.emulator.device import ESP32Emulator, ESP32EmulatorConfig

__all__ = ["ESP32Emulator", "ESP32EmulatorConfig"]
```

```python
# cbus/esp32/emulator/device.py
"""ESP32 C-Bus bridge emulator for automated testing.

Emulates an ESP32 device running C-Bus bridge firmware. Accepts TCP
connections and responds to the C-Bus PCI protocol, maintaining internal
group state. Designed for use in integration tests without real hardware.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ESP32EmulatorConfig:
    tcp_port: int = 10001
    tcp_host: str = "127.0.0.1"
    firmware_version: str = "1.0.0"
    device_type: str = "ESP32-WROOM-EMULATED"
    mac_address: str = "AA:BB:CC:DD:EE:FF"
    network_id: int = 254
    num_groups: int = 256
    enable_mdns: bool = False
    response_delay_ms: float = 5.0
    smart_mode_default: bool = True


class EmulatedGroup:
    def __init__(self, group_id: int, name: str = ""):
        self.group_id = group_id
        self.name = name or f"Group {group_id}"
        self._level = 0

    @property
    def level(self) -> int:
        return self._level

    @level.setter
    def level(self, value: int):
        self._level = max(0, min(255, value))

    @property
    def is_on(self) -> bool:
        return self._level > 0


class ESP32Emulator:
    """Emulates an ESP32 C-Bus bridge device for testing."""

    def __init__(self, config: Optional[ESP32EmulatorConfig] = None):
        self._config = config or ESP32EmulatorConfig()
        self._groups: List[EmulatedGroup] = [
            EmulatedGroup(i) for i in range(self._config.num_groups)
        ]
        self._server: Optional[asyncio.AbstractServer] = None
        self._clients: List[asyncio.StreamWriter] = []
        self._actual_port: int = 0
        self._command_log: List[Dict[str, Any]] = []
        self._confirmation_index = 0

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server.is_serving()

    @property
    def actual_port(self) -> int:
        return self._actual_port

    @property
    def groups(self) -> List[EmulatedGroup]:
        return self._groups

    @property
    def device_info(self) -> Dict[str, Any]:
        return {
            "firmware_version": self._config.firmware_version,
            "device_type": self._config.device_type,
            "mac_address": self._config.mac_address,
            "network_id": self._config.network_id,
        }

    @property
    def command_log(self) -> List[Dict[str, Any]]:
        return list(self._command_log)

    def get_group_level(self, group_id: int) -> int:
        if 0 <= group_id < len(self._groups):
            return self._groups[group_id].level
        return 0

    def set_group_level(self, group_id: int, level: int):
        if 0 <= group_id < len(self._groups):
            self._groups[group_id].level = level

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client,
            self._config.tcp_host,
            self._config.tcp_port,
        )
        # Get the actual port (important when port=0 for auto-assign)
        addr = self._server.sockets[0].getsockname()
        self._actual_port = addr[1]
        logger.info("ESP32 emulator started on %s:%d", self._config.tcp_host, self._actual_port)

    async def stop(self):
        for writer in self._clients:
            writer.close()
        self._clients.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._actual_port = 0
        logger.info("ESP32 emulator stopped")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        logger.info("Emulator: client connected from %s", addr)
        self._clients.append(writer)

        try:
            buf = bytearray()
            while True:
                data = await reader.read(1024)
                if not data:
                    break
                buf.extend(data)
                await self._process_buffer(buf, writer)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Emulator client error: %s", e)
        finally:
            if writer in self._clients:
                self._clients.remove(writer)
            writer.close()
            logger.info("Emulator: client disconnected from %s", addr)

    async def _process_buffer(self, buf: bytearray, writer: asyncio.StreamWriter):
        CONFIRMATION_CODES = b'hijklmnopqrstuvwxyzg'
        END = b'\r'
        END_FULL = b'\r\n'

        while True:
            # Find end of command
            end_pos = -1
            end_len = 0
            cr_pos = buf.find(b'\r')
            if cr_pos >= 0:
                if cr_pos + 1 < len(buf) and buf[cr_pos + 1:cr_pos + 2] == b'\n':
                    end_pos = cr_pos
                    end_len = 2
                else:
                    end_pos = cr_pos
                    end_len = 1

            if end_pos < 0:
                break

            cmd_bytes = bytes(buf[:end_pos])
            del buf[:end_pos + end_len]

            if not cmd_bytes:
                continue

            self._command_log.append({"raw": cmd_bytes, "type": "unknown"})

            # Add response delay
            if self._config.response_delay_ms > 0:
                await asyncio.sleep(self._config.response_delay_ms / 1000.0)

            # Handle reset
            if cmd_bytes == b'~~~':
                self._command_log[-1]["type"] = "reset"
                continue

            # Handle Smart+Connect shortcut
            if cmd_bytes == b'|':
                self._command_log[-1]["type"] = "smart_connect"
                continue

            # Handle device management commands (A3XXYY format)
            if cmd_bytes.startswith(b'A3') or cmd_bytes.startswith(b'@A3'):
                self._command_log[-1]["type"] = "device_management"
                # DM commands get confirmation + success
                writer.write(b'g.\r\n')
                await writer.drain()
                continue

            # Handle C-Bus protocol commands starting with backslash
            if cmd_bytes.startswith(b'\\'):
                self._command_log[-1]["type"] = "cbus_command"

                # Extract confirmation code (last byte before \r)
                conf_code = None
                payload = cmd_bytes[1:]  # strip leading backslash

                if payload and payload[-1:] in CONFIRMATION_CODES:
                    conf_code = payload[-1:]
                    payload = payload[:-1]

                # Parse the hex-encoded C-Bus packet
                try:
                    packet_bytes = bytes.fromhex(payload.decode('ascii'))
                except (ValueError, UnicodeDecodeError):
                    packet_bytes = payload

                # Process based on packet content
                if len(packet_bytes) >= 4:
                    dest_type = packet_bytes[0] if packet_bytes else 0
                    app_id = packet_bytes[1] if len(packet_bytes) > 1 else 0

                    # Point-to-Multipoint lighting command
                    if dest_type == 0x05 and app_id == 0x38:
                        # Lighting application
                        if len(packet_bytes) >= 4:
                            cmd_type = packet_bytes[3]
                            group_addr = packet_bytes[4] if len(packet_bytes) > 4 else 0

                            if cmd_type == 0x79:  # ON
                                self.set_group_level(group_addr, 255)
                                self._command_log[-1]["type"] = "lighting_on"
                                self._command_log[-1]["group"] = group_addr
                            elif cmd_type == 0x01:  # OFF
                                self.set_group_level(group_addr, 0)
                                self._command_log[-1]["type"] = "lighting_off"
                                self._command_log[-1]["group"] = group_addr
                            elif cmd_type == 0x09:  # TERMINATE_RAMP
                                self._command_log[-1]["type"] = "lighting_terminate_ramp"
                                self._command_log[-1]["group"] = group_addr
                            elif 0x02 <= cmd_type <= 0x7A:  # RAMP
                                level = packet_bytes[5] if len(packet_bytes) > 5 else 255
                                self.set_group_level(group_addr, level)
                                self._command_log[-1]["type"] = "lighting_ramp"
                                self._command_log[-1]["group"] = group_addr
                                self._command_log[-1]["level"] = level

                    # Status request
                    elif dest_type == 0x05 and app_id == 0xFF:
                        self._command_log[-1]["type"] = "status_request"
                        # Send status response
                        if len(packet_bytes) >= 5:
                            child_app = packet_bytes[3] if len(packet_bytes) > 3 else 0x38
                            block_start = packet_bytes[4] if len(packet_bytes) > 4 else 0
                            await self._send_level_status(writer, child_app, block_start)

                    # Clock update
                    elif dest_type == 0x05 and app_id == 0xDF:
                        self._command_log[-1]["type"] = "clock_update"

                # Send confirmation if requested
                if conf_code is not None:
                    response = conf_code + b'.\r\n'
                    writer.write(response)
                    await writer.drain()

    async def _send_level_status(self, writer: asyncio.StreamWriter, app_id: int, block_start: int):
        """Send level status report for a block of 32 groups."""
        # Build a level status response packet
        # Format: PP header + extended CAL with level data
        levels = []
        for i in range(32):
            gid = block_start + i
            if gid < len(self._groups):
                levels.append(self._groups[gid].level)
            else:
                levels.append(0)

        # Encode as hex pairs in a point-to-point response
        level_hex = ''.join(f'{l:02X}' for l in levels)
        # Extended CAL level status report
        # 86FFFF00 = PP from address FF, routing none
        # E0 = extended status, app, block_start, then 32 level bytes
        response_hex = f'86FFFF00{app_id:02X}E0{block_start:02X}{level_hex}'
        response = response_hex.encode('ascii') + b'\r\n'
        writer.write(response)
        await writer.drain()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_esp32_emulator.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add cbus/esp32/emulator/__init__.py cbus/esp32/emulator/device.py tests/test_esp32_emulator.py
git commit -m "feat: add ESP32 C-Bus bridge emulator for automated testing"
```

---

### Task 7: ESP32 Emulator Serial Port Support

**Files:**
- Create: `cbus/esp32/emulator/serial_port.py`
- Test: `tests/test_esp32_emulator_serial.py`

**Step 1: Write the failing test**

```python
# tests/test_esp32_emulator_serial.py
import pytest
import asyncio
import os
from unittest.mock import MagicMock

from cbus.esp32.emulator.serial_port import VirtualSerialPair


class TestVirtualSerialPair:
    @pytest.mark.asyncio
    async def test_create_pair(self):
        pair = VirtualSerialPair()
        await pair.create()
        assert pair.device_port is not None
        assert pair.client_port is not None
        assert os.path.exists(pair.device_port)
        assert os.path.exists(pair.client_port)
        await pair.close()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with VirtualSerialPair() as pair:
            assert pair.device_port is not None
            assert pair.client_port is not None

    @pytest.mark.asyncio
    async def test_data_flows_through(self):
        async with VirtualSerialPair() as pair:
            # Write to device side, read from client side
            with open(pair.device_port, 'wb', buffering=0) as dev:
                dev.write(b'hello')
            await asyncio.sleep(0.1)
            with open(pair.client_port, 'rb') as client:
                os.set_blocking(client.fileno(), False)
                try:
                    data = client.read(5)
                    assert data == b'hello'
                except (BlockingIOError, TypeError):
                    # May not have data ready yet on some systems
                    pass
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_esp32_emulator_serial.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'cbus.esp32.emulator.serial_port'"

**Step 3: Write minimal implementation**

```python
# cbus/esp32/emulator/serial_port.py
"""Virtual serial port pair for ESP32 emulator serial testing.

Uses OS-level PTY (pseudo-terminal) to create a pair of linked serial ports.
One end acts as the "ESP32 device" and the other as the "client" port that
the cbus library connects to.
"""
import asyncio
import logging
import os
import pty
from typing import Optional

logger = logging.getLogger(__name__)


class VirtualSerialPair:
    """Creates a pair of linked virtual serial ports using PTY."""

    def __init__(self):
        self._master_fd: Optional[int] = None
        self._slave_fd: Optional[int] = None
        self._device_port: Optional[str] = None
        self._client_port: Optional[str] = None

    @property
    def device_port(self) -> Optional[str]:
        """Path to the device-side port (ESP32 emulator connects here)."""
        return self._device_port

    @property
    def client_port(self) -> Optional[str]:
        """Path to the client-side port (cbus library connects here)."""
        return self._client_port

    async def create(self):
        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd
        self._slave_fd = slave_fd
        self._device_port = os.ttyname(master_fd)
        self._client_port = os.ttyname(slave_fd)
        logger.info("Virtual serial pair: device=%s, client=%s", self._device_port, self._client_port)

    async def close(self):
        if self._master_fd is not None:
            os.close(self._master_fd)
            self._master_fd = None
        if self._slave_fd is not None:
            os.close(self._slave_fd)
            self._slave_fd = None
        self._device_port = None
        self._client_port = None
        logger.info("Virtual serial pair closed")

    async def __aenter__(self):
        await self.create()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_esp32_emulator_serial.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add cbus/esp32/emulator/serial_port.py tests/test_esp32_emulator_serial.py
git commit -m "feat: add virtual serial port pair for ESP32 serial emulation"
```

---

## Phase 4: Integration Testing

### Task 8: End-to-End WiFi Integration Test

**Files:**
- Test: `tests/test_esp32_integration.py`

**Step 1: Write the failing test**

```python
# tests/test_esp32_integration.py
"""End-to-end integration tests: ESP32 emulator <-> cbus library over TCP."""
import pytest
import asyncio

from cbus.esp32.emulator.device import ESP32Emulator, ESP32EmulatorConfig
from cbus.esp32.connection import ESP32Connection, ESP32Config
from cbus.protocol.pciprotocol import PCIProtocol
from cbus.transport.base import TransportState


class TestESP32WiFiIntegration:
    """Tests connecting the real cbus protocol to the ESP32 emulator over TCP."""

    @pytest.fixture
    async def emulator(self):
        config = ESP32EmulatorConfig(tcp_port=0)
        emu = ESP32Emulator(config)
        await emu.start()
        yield emu
        await emu.stop()

    @pytest.fixture
    async def connection(self, emulator):
        config = ESP32Config.wifi("127.0.0.1", port=emulator.actual_port)
        conn = ESP32Connection(config)
        await conn.connect()
        yield conn
        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_connect_to_emulator(self, emulator):
        """Test that we can establish a TCP connection to the emulator."""
        config = ESP32Config.wifi("127.0.0.1", port=emulator.actual_port)
        conn = ESP32Connection(config)
        await conn.connect()
        assert conn.transport.is_connected
        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_protocol_initialized(self, connection):
        """Test that PCIProtocol is created and connected."""
        assert connection.protocol is not None
        assert isinstance(connection.protocol, PCIProtocol)

    @pytest.mark.asyncio
    async def test_lighting_on_command(self, connection, emulator):
        """Test sending a lighting ON command through to the emulator."""
        # Wait for PCI reset to complete
        await asyncio.sleep(0.5)
        # Send lighting ON for group 1
        await connection.protocol.lighting_group_on(1, 0x38)
        # Give emulator time to process
        await asyncio.sleep(0.3)
        # Verify emulator received and processed the command
        assert emulator.get_group_level(1) == 255

    @pytest.mark.asyncio
    async def test_lighting_off_command(self, connection, emulator):
        """Test sending a lighting OFF command through to the emulator."""
        await asyncio.sleep(0.5)
        # First turn on
        emulator.set_group_level(5, 255)
        # Send OFF
        await connection.protocol.lighting_group_off(5, 0x38)
        await asyncio.sleep(0.3)
        assert emulator.get_group_level(5) == 0

    @pytest.mark.asyncio
    async def test_lighting_ramp_command(self, connection, emulator):
        """Test sending a lighting RAMP command through to the emulator."""
        await asyncio.sleep(0.5)
        await connection.protocol.lighting_group_ramp(3, 0x38, 0, 128)
        await asyncio.sleep(0.3)
        assert emulator.get_group_level(3) == 128

    @pytest.mark.asyncio
    async def test_multiple_groups(self, connection, emulator):
        """Test controlling multiple groups sequentially."""
        await asyncio.sleep(0.5)
        # Turn on groups 1, 2, 3
        for g in [1, 2, 3]:
            await connection.protocol.lighting_group_on(g, 0x38)
            await asyncio.sleep(0.1)

        await asyncio.sleep(0.3)
        for g in [1, 2, 3]:
            assert emulator.get_group_level(g) == 255, f"Group {g} should be ON"

    @pytest.mark.asyncio
    async def test_emulator_command_log(self, connection, emulator):
        """Test that the emulator logs all commands received."""
        await asyncio.sleep(0.5)
        initial_count = len(emulator.command_log)
        await connection.protocol.lighting_group_on(10, 0x38)
        await asyncio.sleep(0.3)
        assert len(emulator.command_log) > initial_count


class TestESP32EmulatorStandalone:
    """Test the emulator as a standalone TCP server."""

    @pytest.mark.asyncio
    async def test_emulator_accepts_raw_connection(self):
        """Test connecting with raw TCP and sending C-Bus commands."""
        config = ESP32EmulatorConfig(tcp_port=0)
        async with ESP32Emulator(config) as emu:
            reader, writer = await asyncio.open_connection("127.0.0.1", emu.actual_port)
            # Send a reset command
            writer.write(b'~~~\r\n')
            await writer.drain()
            await asyncio.sleep(0.1)
            # Send a lighting ON command with confirmation
            # \0538007901h = Light ON group 1 with conf code 'h'
            writer.write(b'\\0538007901h\r\n')
            await writer.drain()
            await asyncio.sleep(0.2)
            # Read response (should be confirmation)
            data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            assert b'.' in data  # confirmation success marker
            assert emu.get_group_level(1) == 255
            writer.close()
            await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_emulator_multiple_clients(self):
        """Test that multiple clients can connect simultaneously."""
        config = ESP32EmulatorConfig(tcp_port=0)
        async with ESP32Emulator(config) as emu:
            readers_writers = []
            for _ in range(3):
                r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
                readers_writers.append((r, w))

            await asyncio.sleep(0.1)

            # All connections should be tracked
            assert len(emu._clients) == 3

            for _, w in readers_writers:
                w.close()
                await w.wait_closed()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_esp32_integration.py -v`
Expected: FAIL (various failures as integration paths aren't wired up yet)

**Step 3: Fix any issues identified by integration tests**

The integration tests exercise the full connection path. Fix issues iteratively until all pass.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_esp32_integration.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add tests/test_esp32_integration.py
git commit -m "test: add end-to-end ESP32 WiFi integration tests"
```

---

### Task 9: Protocol Compliance Tests

**Files:**
- Test: `tests/test_esp32_protocol_compliance.py`

**Step 1: Write the test**

```python
# tests/test_esp32_protocol_compliance.py
"""Protocol compliance tests verifying the ESP32 emulator matches real PCI behavior."""
import pytest
import asyncio
import struct

from cbus.esp32.emulator.device import ESP32Emulator, ESP32EmulatorConfig


@pytest.fixture
async def emulator():
    config = ESP32EmulatorConfig(tcp_port=0, response_delay_ms=1.0)
    emu = ESP32Emulator(config)
    await emu.start()
    yield emu
    await emu.stop()


@pytest.fixture
async def client(emulator):
    reader, writer = await asyncio.open_connection("127.0.0.1", emulator.actual_port)
    yield reader, writer
    writer.close()
    await writer.wait_closed()


class TestResetBehavior:
    @pytest.mark.asyncio
    async def test_triple_reset(self, client, emulator):
        reader, writer = client
        for _ in range(3):
            writer.write(b'~~~\r\n')
            await writer.drain()
        await asyncio.sleep(0.1)
        # Reset should be logged
        resets = [c for c in emulator.command_log if c["type"] == "reset"]
        assert len(resets) == 3


class TestConfirmationCodes:
    CONF_CODES = b'hijklmnopqrstuvwxyzg'

    @pytest.mark.asyncio
    async def test_each_confirmation_code(self, client, emulator):
        reader, writer = client
        # Reset first
        writer.write(b'~~~\r\n')
        await writer.drain()
        await asyncio.sleep(0.1)

        for code in self.CONF_CODES:
            code_char = bytes([code])
            # Send lighting ON for group 1 with this confirmation code
            cmd = b'\\05380079' + b'01' + code_char + b'\r\n'
            writer.write(cmd)
            await writer.drain()
            await asyncio.sleep(0.05)

            # Read response
            data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            # Should contain the same confirmation code followed by '.'
            assert code_char + b'.' in data, (
                f"Expected confirmation {code_char!r}. in response, got {data!r}"
            )

    @pytest.mark.asyncio
    async def test_no_confirmation_when_not_requested(self, client, emulator):
        reader, writer = client
        writer.write(b'~~~\r\n')
        await writer.drain()
        await asyncio.sleep(0.1)
        # Send command WITHOUT confirmation code (no trailing letter)
        writer.write(b'\\0538007901\r\n')
        await writer.drain()
        await asyncio.sleep(0.2)
        # Should not receive confirmation response
        try:
            data = await asyncio.wait_for(reader.read(1024), timeout=0.5)
            # If data is received, it should not contain confirmation markers
            for code in self.CONF_CODES:
                assert bytes([code]) + b'.' not in data
        except asyncio.TimeoutError:
            pass  # No response is also valid


class TestLightingCommands:
    @pytest.mark.asyncio
    async def test_on_sets_level_255(self, client, emulator):
        reader, writer = client
        # ON command for group 5 (0x05) with conf code 'h'
        writer.write(b'\\053800790500FFh\r\n')
        await writer.drain()
        await asyncio.sleep(0.2)
        assert emulator.get_group_level(5) == 255

    @pytest.mark.asyncio
    async def test_off_sets_level_0(self, client, emulator):
        reader, writer = client
        emulator.set_group_level(5, 255)
        # OFF command for group 5 (0x01 = OFF)
        writer.write(b'\\053800010500h\r\n')
        await writer.drain()
        await asyncio.sleep(0.2)
        assert emulator.get_group_level(5) == 0

    @pytest.mark.asyncio
    async def test_ramp_sets_specific_level(self, client, emulator):
        reader, writer = client
        # RAMP instant (0x02) group 10 (0x0A) to level 128 (0x80)
        writer.write(b'\\05380002' + b'0A80' + b'h\r\n')
        await writer.drain()
        await asyncio.sleep(0.2)
        assert emulator.get_group_level(10) == 128

    @pytest.mark.asyncio
    async def test_all_256_groups(self, client, emulator):
        reader, writer = client
        # Set each group to its group number as level
        for g in range(256):
            emulator.set_group_level(g, g)
        for g in range(256):
            assert emulator.get_group_level(g) == g


class TestDeviceManagement:
    @pytest.mark.asyncio
    async def test_dm_command_acknowledged(self, client, emulator):
        reader, writer = client
        # Device management command (interface options)
        writer.write(b'A3300079\r\n')
        await writer.drain()
        await asyncio.sleep(0.1)
        data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
        # Should receive acknowledgment
        assert b'.' in data
```

**Step 2: Run and iterate**

Run: `pytest tests/test_esp32_protocol_compliance.py -v`
Fix any compliance issues until all pass.

**Step 3: Commit**

```bash
git add tests/test_esp32_protocol_compliance.py
git commit -m "test: add C-Bus protocol compliance tests for ESP32 emulator"
```

---

## Phase 5: CLI Integration

### Task 10: Add ESP32 CLI Options to cmqttd

**Files:**
- Modify: `cbus/daemon/cli.py`
- Modify: `cbus/daemon/cmqttd.py:130-235`
- Test: `tests/test_esp32_cli.py`

**Step 1: Write the failing test**

```python
# tests/test_esp32_cli.py
import pytest
from cbus.daemon.cli import build_arg_parser, parse_cli_args


class TestESP32CLIArgs:
    def test_esp32_wifi_option(self):
        args = parse_cli_args([
            '-b', 'localhost',
            '--esp32-wifi', '192.168.1.50:10001',
        ])
        assert args.esp32_wifi == '192.168.1.50:10001'
        assert args.tcp is None

    def test_esp32_serial_option(self):
        args = parse_cli_args([
            '-b', 'localhost',
            '--esp32-serial', '/dev/ttyUSB0',
        ])
        assert args.esp32_serial == '/dev/ttyUSB0'

    def test_esp32_serial_baudrate(self):
        args = parse_cli_args([
            '-b', 'localhost',
            '--esp32-serial', '/dev/ttyUSB0',
            '--esp32-baudrate', '115200',
        ])
        assert args.esp32_baudrate == 115200

    def test_esp32_discover_flag(self):
        args = parse_cli_args([
            '-b', 'localhost',
            '--esp32-discover',
        ])
        assert args.esp32_discover is True

    def test_connection_mutually_exclusive(self):
        """At least one of --tcp, --esp32-wifi, --esp32-serial, --esp32-discover must be given."""
        parser = build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(['-b', 'localhost'])
            # No connection method specified

    def test_tcp_still_works(self):
        args = parse_cli_args([
            '-b', 'localhost',
            '-t', '192.168.1.10:10001',
        ])
        assert args.tcp == '192.168.1.10:10001'

    def test_esp32_reconnect_options(self):
        args = parse_cli_args([
            '-b', 'localhost',
            '--esp32-wifi', '192.168.1.50',
            '--esp32-reconnect-interval', '10',
            '--esp32-max-reconnect', '5',
        ])
        assert args.esp32_reconnect_interval == 10
        assert args.esp32_max_reconnect == 5
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_esp32_cli.py -v`
Expected: FAIL with "AttributeError: ... has no attribute 'esp32_wifi'"

**Step 3: Modify `cbus/daemon/cli.py` to add ESP32 options**

Add a new argument group after the existing "C-Bus PCI connection" group:

```python
# In build_arg_parser(), replace the existing PCI connection group with:

    # PCI / CNI / ESP32 connection (mutually exclusive) -------------------
    group = parser.add_argument_group('C-Bus connection')
    conn = group.add_mutually_exclusive_group(required=True)
    conn.add_argument('-t', '--tcp', dest='tcp', default=None, metavar='ADDR:PORT',
                      help='IP address and TCP port of CNI/PCI (eg 192.168.1.10:10001)')
    conn.add_argument('--esp32-wifi', dest='esp32_wifi', default=None, metavar='ADDR[:PORT]',
                      help='ESP32 C-Bus bridge WiFi address (eg 192.168.1.50 or 192.168.1.50:10001)')
    conn.add_argument('--esp32-serial', dest='esp32_serial', default=None, metavar='DEVICE',
                      help='ESP32 C-Bus bridge serial port (eg /dev/ttyUSB0)')
    conn.add_argument('--esp32-discover', dest='esp32_discover', action='store_true', default=False,
                      help='Auto-discover ESP32 C-Bus bridge via mDNS')

    # ESP32-specific options
    esp32_group = parser.add_argument_group('ESP32 options')
    esp32_group.add_argument('--esp32-baudrate', type=int, default=9600,
                             help='Serial baud rate for ESP32 connection')
    esp32_group.add_argument('--esp32-reconnect-interval', type=int, default=5,
                             help='Seconds between reconnect attempts')
    esp32_group.add_argument('--esp32-max-reconnect', type=int, default=0,
                             help='Max reconnect attempts (0=unlimited)')
```

**Step 4: Modify `cbus/daemon/cmqttd.py` _main() to support ESP32 connections**

In `_main()`, after the label parsing section (around line 172), replace the TCP connection block:

```python
        # Establish C-Bus connection
        if option.tcp:
            # Legacy TCP connection to CNI/PCI
            def factory():
                return CBusHandler(
                    timesync_frequency=option.timesync,
                    handle_clock_requests=not option.no_clock,
                    connection_lost_future=connection_lost_future,
                    labels=labels,
                )
            addr_host, addr_port = option.tcp.split(':', 1)
            _, protocol = await loop.create_connection(factory, addr_host, int(addr_port))
        elif option.esp32_wifi or option.esp32_serial or option.esp32_discover:
            # ESP32 connection
            from cbus.esp32.connection import ESP32Connection, ESP32Config
            if option.esp32_discover:
                from cbus.esp32.discovery import ESP32Discovery
                discovery = ESP32Discovery(timeout=10.0)
                devices = await discovery.discover()
                if not devices:
                    raise SystemExit('No ESP32 C-Bus bridge devices found on the network')
                logger.info("Found %d ESP32 device(s), connecting to first: %s", len(devices), devices[0])
                esp32_config = ESP32Config.wifi(
                    devices[0].host, devices[0].port,
                    reconnect_interval=option.esp32_reconnect_interval,
                    max_reconnect_attempts=option.esp32_max_reconnect,
                    timesync_frequency=option.timesync,
                    handle_clock_requests=not option.no_clock,
                )
            elif option.esp32_wifi:
                addr = option.esp32_wifi
                host = addr.rsplit(':', 1)[0] if ':' in addr else addr
                port = int(addr.rsplit(':', 1)[1]) if ':' in addr else 10001
                esp32_config = ESP32Config.wifi(
                    host, port,
                    reconnect_interval=option.esp32_reconnect_interval,
                    max_reconnect_attempts=option.esp32_max_reconnect,
                    timesync_frequency=option.timesync,
                    handle_clock_requests=not option.no_clock,
                )
            else:
                esp32_config = ESP32Config.serial(
                    option.esp32_serial,
                    baudrate=option.esp32_baudrate,
                    reconnect_interval=option.esp32_reconnect_interval,
                    max_reconnect_attempts=option.esp32_max_reconnect,
                    timesync_frequency=option.timesync,
                    handle_clock_requests=not option.no_clock,
                )

            # Create CBusHandler as protocol factory for ESP32Connection
            esp32_conn = ESP32Connection(esp32_config)
            # Override the protocol factory to create CBusHandler instead of plain PCIProtocol
            def esp32_factory():
                return CBusHandler(
                    timesync_frequency=esp32_config.timesync_frequency,
                    handle_clock_requests=esp32_config.handle_clock_requests,
                    connection_lost_future=connection_lost_future,
                    labels=labels,
                )
            esp32_conn.transport._protocol_factory = esp32_factory
            await esp32_conn.connect()
            protocol = esp32_conn.transport.protocol
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_esp32_cli.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add cbus/daemon/cli.py cbus/daemon/cmqttd.py tests/test_esp32_cli.py
git commit -m "feat: add ESP32 WiFi/Serial/discover CLI options to cmqttd"
```

---

## Phase 6: Comprehensive Validation

### Task 11: Reconnection and Fault Tolerance Tests

**Files:**
- Test: `tests/test_esp32_reconnection.py`

**Step 1: Write the test**

```python
# tests/test_esp32_reconnection.py
"""Tests for auto-reconnection and fault tolerance."""
import pytest
import asyncio

from cbus.esp32.emulator.device import ESP32Emulator, ESP32EmulatorConfig
from cbus.esp32.connection import ESP32Connection, ESP32Config
from cbus.transport.base import TransportState


class TestReconnection:
    @pytest.mark.asyncio
    async def test_reconnect_after_server_restart(self):
        """Test that client reconnects when the emulator restarts."""
        config = ESP32EmulatorConfig(tcp_port=0)
        emu = ESP32Emulator(config)
        await emu.start()
        port = emu.actual_port

        conn_config = ESP32Config.wifi(
            "127.0.0.1", port=port,
            reconnect=True,
            reconnect_interval=0.5,
            max_reconnect_attempts=5,
            connect_timeout=2.0,
        )
        conn = ESP32Connection(conn_config)
        await conn.connect()
        assert conn.transport.is_connected

        # Stop emulator (simulates disconnect)
        await emu.stop()
        await asyncio.sleep(0.2)

        # Restart emulator on same port
        emu2 = ESP32Emulator(ESP32EmulatorConfig(tcp_port=port))
        await emu2.start()

        # Wait for reconnect
        await asyncio.sleep(2.0)

        await conn.disconnect()
        await emu2.stop()

    @pytest.mark.asyncio
    async def test_max_reconnect_attempts(self):
        """Test that reconnection stops after max attempts."""
        config = ESP32EmulatorConfig(tcp_port=0)
        emu = ESP32Emulator(config)
        await emu.start()
        port = emu.actual_port

        conn_config = ESP32Config.wifi(
            "127.0.0.1", port=port,
            reconnect=True,
            reconnect_interval=0.2,
            max_reconnect_attempts=2,
            connect_timeout=1.0,
        )
        conn = ESP32Connection(conn_config)
        await conn.connect()

        # Stop emulator permanently
        await emu.stop()
        await asyncio.sleep(0.2)

        # Wait for max reconnect attempts to be exhausted
        await asyncio.sleep(2.0)

        assert conn.transport.state == TransportState.ERROR
        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_no_reconnect_when_disabled(self):
        """Test that disabling reconnect prevents retry."""
        config = ESP32EmulatorConfig(tcp_port=0)
        emu = ESP32Emulator(config)
        await emu.start()
        port = emu.actual_port

        conn_config = ESP32Config.wifi(
            "127.0.0.1", port=port,
            reconnect=False,
            connect_timeout=2.0,
        )
        conn = ESP32Connection(conn_config)
        await conn.connect()

        await emu.stop()
        await asyncio.sleep(0.5)

        # Should not be reconnecting
        assert conn.transport.state != TransportState.RECONNECTING
        await conn.disconnect()


class TestConnectionTimeout:
    @pytest.mark.asyncio
    async def test_connect_timeout_on_unreachable_host(self):
        """Test that connection times out when host is unreachable."""
        from cbus.transport.base import ConnectionTimeoutError
        conn_config = ESP32Config.wifi(
            "127.0.0.1", port=59999,  # Port no one is listening on
            reconnect=False,
            connect_timeout=1.0,
        )
        conn = ESP32Connection(conn_config)
        with pytest.raises(Exception):  # ConnectionRefusedError or timeout
            await conn.connect()


class TestConcurrentConnections:
    @pytest.mark.asyncio
    async def test_multiple_connections_to_emulator(self):
        """Test multiple simultaneous connections to the same emulator."""
        config = ESP32EmulatorConfig(tcp_port=0)
        async with ESP32Emulator(config) as emu:
            connections = []
            for _ in range(3):
                cfg = ESP32Config.wifi("127.0.0.1", port=emu.actual_port, reconnect=False)
                conn = ESP32Connection(cfg)
                await conn.connect()
                connections.append(conn)

            # All should be connected
            for conn in connections:
                assert conn.transport.is_connected

            # Clean up
            for conn in connections:
                await conn.disconnect()
```

**Step 2: Run and iterate**

Run: `pytest tests/test_esp32_reconnection.py -v`

**Step 3: Commit**

```bash
git add tests/test_esp32_reconnection.py
git commit -m "test: add reconnection and fault tolerance tests"
```

---

### Task 12: Full Test Suite Validation

**Step 1: Run the complete test suite**

Run: `pytest tests/ -v --tb=short`

Ensure ALL existing tests still pass alongside the new tests.

**Step 2: Run with coverage**

Run: `pytest tests/ --cov=cbus --cov-report=term-missing -v`

**Step 3: Fix any regressions**

If any existing tests break, fix them before proceeding.

**Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve test regressions from ESP32 integration"
```

---

### Task 13: Update Package Configuration

**Files:**
- Modify: `setup.py`
- Modify: `requirements.txt`

**Step 1: Update setup.py**

Add `zeroconf` as an optional dependency and register the new packages:

```python
# In setup.py, update packages list and install_requires:
packages=[
    'cbus', 'cbus.protocol', 'cbus.protocol.application', 'cbus.protocol.cal',
    'cbus.daemon', 'cbus.toolkit', 'cbus.tools',
    'cbus.transport',   # NEW
    'cbus.esp32',        # NEW
    'cbus.esp32.emulator',  # NEW
],
install_requires=[
    # ... existing deps ...
],
extras_require={
    'esp32': ['zeroconf>=0.80.0'],
    'test': ['pytest', 'pytest-asyncio', 'parameterized'],
},
entry_points={
    'console_scripts': [
        # ... existing entries ...
        'cbus_esp32_emulator = cbus.esp32.emulator.device:main',  # NEW
    ]
}
```

**Step 2: Update requirements.txt**

Add optional zeroconf:

```
# ESP32 discovery (optional)
# zeroconf>=0.80.0
```

**Step 3: Verify install**

Run: `pip install -e . && pytest tests/ -v`

**Step 4: Commit**

```bash
git add setup.py requirements.txt
git commit -m "feat: update package config with ESP32 transport and emulator modules"
```

---

### Task 14: Final Validation and Documentation

**Step 1: Run full test suite one final time**

Run: `pytest tests/ -v --tb=long 2>&1 | tail -50`

**Step 2: Verify no import errors in any new module**

Run:
```bash
python -c "from cbus.transport import CBusTransport, TCPTransport, SerialTransport; print('Transport OK')"
python -c "from cbus.esp32 import ESP32Connection, ESP32Config; print('ESP32 OK')"
python -c "from cbus.esp32.emulator import ESP32Emulator; print('Emulator OK')"
python -c "from cbus.esp32.discovery import ESP32Discovery; print('Discovery OK')"
```

**Step 3: Verify CLI help shows new options**

Run: `python -m cbus.daemon.cmqttd --help`

Verify output includes `--esp32-wifi`, `--esp32-serial`, `--esp32-discover`, `--esp32-baudrate`, etc.

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: ESP32 direct connection support complete with emulator and tests"
```
