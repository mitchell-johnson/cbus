import pytest
from unittest.mock import MagicMock

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
