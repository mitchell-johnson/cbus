import pytest
import asyncio
from unittest.mock import MagicMock

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
        assert config.max_reconnect_attempts == 0
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
