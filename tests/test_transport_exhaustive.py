"""Exhaustive positive and negative tests for transport layer."""
import pytest
import pytest_asyncio
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from cbus.transport.base import (
    CBusTransport, TransportState, TransportConfig,
    TransportError, ConnectionTimeoutError,
)
from cbus.transport.tcp import TCPTransport, TCPTransportConfig, DEFAULT_CBUS_TCP_PORT
from cbus.transport.serial import SerialTransport, SerialTransportConfig, DEFAULT_CBUS_BAUDRATE


# ============================================================
# TransportConfig Exhaustive Tests
# ============================================================

class TestTransportConfigExhaustive:
    def test_default_reconnect_true(self):
        assert TransportConfig().reconnect is True

    def test_default_reconnect_interval(self):
        assert TransportConfig().reconnect_interval == 5.0

    def test_default_max_reconnect_zero(self):
        assert TransportConfig().max_reconnect_attempts == 0

    def test_default_connect_timeout(self):
        assert TransportConfig().connect_timeout == 10.0

    def test_default_heartbeat(self):
        assert TransportConfig().heartbeat_interval == 30.0

    @pytest.mark.parametrize("val", [True, False])
    def test_reconnect_values(self, val):
        assert TransportConfig(reconnect=val).reconnect is val

    @pytest.mark.parametrize("val", [0.1, 1.0, 5.0, 30.0, 300.0])
    def test_reconnect_interval_values(self, val):
        assert TransportConfig(reconnect_interval=val).reconnect_interval == val

    @pytest.mark.parametrize("val", [0, 1, 5, 10, 100])
    def test_max_reconnect_values(self, val):
        assert TransportConfig(max_reconnect_attempts=val).max_reconnect_attempts == val


# ============================================================
# TransportState Tests
# ============================================================

class TestTransportStateExhaustive:
    def test_all_states(self):
        states = [s.value for s in TransportState]
        assert "disconnected" in states
        assert "connecting" in states
        assert "connected" in states
        assert "reconnecting" in states
        assert "error" in states

    def test_state_count(self):
        assert len(TransportState) == 5

    @pytest.mark.parametrize("state", list(TransportState))
    def test_state_has_string_value(self, state):
        assert isinstance(state.value, str)
        assert len(state.value) > 0


# ============================================================
# TCPTransportConfig Tests
# ============================================================

class TestTCPTransportConfigExhaustive:
    def test_default_port(self):
        assert DEFAULT_CBUS_TCP_PORT == 10001

    def test_default_host(self):
        assert TCPTransportConfig().host == "127.0.0.1"

    @pytest.mark.parametrize("addr,expected_host,expected_port", [
        ("192.168.1.10:10001", "192.168.1.10", 10001),
        ("10.0.0.1:9999", "10.0.0.1", 9999),
        ("192.168.1.10", "192.168.1.10", 10001),
        ("localhost", "localhost", 10001),
        ("127.0.0.1:80", "127.0.0.1", 80),
    ])
    def test_from_address_parsing(self, addr, expected_host, expected_port):
        config = TCPTransportConfig.from_address(addr)
        assert config.host == expected_host
        assert config.port == expected_port

    def test_inherits_transport_config(self):
        config = TCPTransportConfig(host="1.2.3.4", reconnect=False)
        assert config.reconnect is False
        assert config.host == "1.2.3.4"


# ============================================================
# SerialTransportConfig Tests
# ============================================================

class TestSerialTransportConfigExhaustive:
    def test_default_baudrate(self):
        assert DEFAULT_CBUS_BAUDRATE == 9600

    @pytest.mark.parametrize("baud", [9600, 19200, 38400, 57600, 115200])
    def test_standard_baudrates(self, baud):
        config = SerialTransportConfig(device="/dev/ttyUSB0", baudrate=baud)
        assert config.baudrate == baud

    @pytest.mark.parametrize("dev", [
        "/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0",
        "/dev/tty.usbserial", "COM1", "COM3",
    ])
    def test_various_device_paths(self, dev):
        config = SerialTransportConfig(device=dev)
        assert config.device == dev


# ============================================================
# CBusTransport Abstract Base Tests
# ============================================================

class ConcreteTransport(CBusTransport):
    def __init__(self, config=None, fail_connect=False, connect_delay=0):
        super().__init__(config)
        self._fail_connect = fail_connect
        self._connect_delay = connect_delay
        self._mock_transport = MagicMock()

    async def _do_connect(self):
        if self._connect_delay:
            await asyncio.sleep(self._connect_delay)
        if self._fail_connect:
            raise ConnectionRefusedError("Connection refused")
        return self._mock_transport

    async def _do_disconnect(self):
        pass

    @property
    def transport_type(self):
        return "test"

    @property
    def connection_info(self):
        return {"type": "test"}


class TestTransportLifecycleExhaustive:
    @pytest.mark.asyncio
    async def test_double_connect(self):
        t = ConcreteTransport()
        await t.connect()
        await t.connect()  # Should be noop
        assert t.state == TransportState.CONNECTED

    @pytest.mark.asyncio
    async def test_double_disconnect(self):
        t = ConcreteTransport()
        await t.disconnect()
        await t.disconnect()  # Should be noop
        assert t.state == TransportState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_connect_disconnect_connect(self):
        t = ConcreteTransport()
        await t.connect()
        assert t.is_connected
        await t.disconnect()
        assert not t.is_connected
        await t.connect()
        assert t.is_connected
        await t.disconnect()

    @pytest.mark.asyncio
    async def test_connect_failure_sets_error_state(self):
        t = ConcreteTransport(fail_connect=True)
        with pytest.raises(TransportError):
            await t.connect()
        assert t.state == TransportState.ERROR

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        config = TransportConfig(connect_timeout=0.1)
        t = ConcreteTransport(config=config, connect_delay=5)
        with pytest.raises(ConnectionTimeoutError):
            await t.connect()
        assert t.state == TransportState.ERROR

    @pytest.mark.asyncio
    async def test_state_transitions_tracked(self):
        transitions = []
        t = ConcreteTransport()
        t.on_state_change = lambda old, new: transitions.append((old.value, new.value))
        await t.connect()
        await t.disconnect()
        assert ("disconnected", "connecting") in transitions
        assert ("connecting", "connected") in transitions
        assert ("connected", "disconnected") in transitions

    @pytest.mark.asyncio
    async def test_connection_lost_callback(self):
        called = []
        t = ConcreteTransport(config=TransportConfig(reconnect=False))
        t.on_connection_lost = lambda exc: called.append(exc)
        await t.connect()
        await t.handle_connection_lost(Exception("test"))
        assert len(called) == 1

    @pytest.mark.asyncio
    async def test_reconnect_limited_attempts(self):
        config = TransportConfig(
            reconnect=True,
            max_reconnect_attempts=2,
            reconnect_interval=0.1,
        )
        t = ConcreteTransport(config=config, fail_connect=True)
        # Force into connected state, then trigger reconnect
        t._state = TransportState.CONNECTED
        t._fail_connect = True
        await t.handle_connection_lost(Exception("lost"))
        await asyncio.sleep(1.5)  # Wait for reconnect attempts
        assert t.state == TransportState.ERROR

    @pytest.mark.asyncio
    async def test_no_reconnect_when_disabled(self):
        config = TransportConfig(reconnect=False)
        t = ConcreteTransport(config=config)
        await t.connect()
        t._state = TransportState.CONNECTED
        await t.handle_connection_lost(Exception("lost"))
        await asyncio.sleep(0.2)
        assert t.state != TransportState.RECONNECTING


# ============================================================
# TCP Transport Negative Tests
# ============================================================

class TestTCPTransportNegative:
    @pytest.mark.asyncio
    async def test_connect_to_closed_port(self):
        config = TCPTransportConfig(host="127.0.0.1", port=1, connect_timeout=1.0)
        t = TCPTransport(config)
        with pytest.raises(TransportError):
            await t.connect()

    @pytest.mark.asyncio
    async def test_connect_to_nonexistent_host(self):
        config = TCPTransportConfig(host="192.0.2.1", port=10001, connect_timeout=1.0)
        t = TCPTransport(config)
        with pytest.raises((TransportError, ConnectionTimeoutError)):
            await t.connect()

    def test_protocol_none_before_connect(self):
        config = TCPTransportConfig(host="127.0.0.1")
        t = TCPTransport(config)
        assert t.protocol is None


# ============================================================
# Serial Transport Negative Tests
# ============================================================

class TestSerialTransportNegative:
    @pytest.mark.asyncio
    async def test_connect_to_nonexistent_device(self):
        config = SerialTransportConfig(device="/dev/ttyNONEXISTENT", connect_timeout=1.0)
        t = SerialTransport(config)
        with pytest.raises(TransportError):
            await t.connect()

    def test_protocol_none_before_connect(self):
        config = SerialTransportConfig(device="/dev/ttyUSB0")
        t = SerialTransport(config)
        assert t.protocol is None
