import pytest
import asyncio
from unittest.mock import patch

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
        with patch("cbus.esp32.discovery._ZEROCONF_AVAILABLE", False):
            devices = await disc.discover()
            assert isinstance(devices, list)
            assert len(devices) == 0

    def test_manual_device(self):
        dev = DiscoveredDevice.manual("192.168.1.10", 10001)
        assert dev.name == "manual-192.168.1.10"
        assert dev.host == "192.168.1.10"
        assert dev.port == 10001
