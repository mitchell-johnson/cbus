import pytest
import asyncio
from unittest.mock import MagicMock

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
