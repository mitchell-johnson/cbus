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
    async def test_disconnect_closes_transport(self, transport):
        mock_transport = MagicMock()
        transport._asyncio_transport = mock_transport
        transport._state = TransportState.CONNECTED
        await transport.disconnect()
        mock_transport.close.assert_called_once()
        assert transport.state == TransportState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_connect_to_real_server(self):
        """Test connecting to a real TCP server (ephemeral port)."""
        # Start a simple server
        connected = asyncio.Event()

        async def handle(reader, writer):
            connected.set()
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        config = TCPTransportConfig(host="127.0.0.1", port=port)
        transport = TCPTransport(config)
        await transport.connect()
        assert transport.state == TransportState.CONNECTED
        await transport.disconnect()
        server.close()
        await server.wait_closed()
