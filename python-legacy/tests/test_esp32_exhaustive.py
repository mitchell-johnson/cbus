"""Exhaustive positive and negative tests for ESP32 emulator, connection, and discovery."""
import pytest
import pytest_asyncio
import asyncio

from cbus.esp32.emulator.device import ESP32Emulator, ESP32EmulatorConfig, EmulatedGroup
from cbus.esp32.connection import ESP32Connection, ESP32Config, ESP32ConnectionMode, ESP32Info
from cbus.esp32.discovery import DiscoveredDevice, CBUS_MDNS_SERVICE_TYPE
from cbus.transport.base import TransportState, TransportError


# ============================================================
# EmulatedGroup Exhaustive Tests
# ============================================================

class TestEmulatedGroupExhaustive:
    def test_default_level_zero(self):
        g = EmulatedGroup(0)
        assert g.level == 0
        assert g.is_on is False

    @pytest.mark.parametrize("level", [0, 1, 127, 128, 254, 255])
    def test_set_valid_levels(self, level):
        g = EmulatedGroup(0)
        g.level = level
        assert g.level == level
        assert g.is_on == (level > 0)

    @pytest.mark.parametrize("level,expected", [
        (-1, 0), (-100, 0), (-255, 0),
        (256, 255), (300, 255), (1000, 255), (65535, 255),
    ])
    def test_level_clamping(self, level, expected):
        g = EmulatedGroup(0)
        g.level = level
        assert g.level == expected

    def test_level_transitions(self):
        g = EmulatedGroup(0)
        g.level = 255
        assert g.is_on is True
        g.level = 0
        assert g.is_on is False
        g.level = 1
        assert g.is_on is True

    def test_default_name(self):
        g = EmulatedGroup(42)
        assert "42" in g.name

    def test_custom_name(self):
        g = EmulatedGroup(1, "Kitchen")
        assert g.name == "Kitchen"

    @pytest.mark.parametrize("gid", [0, 1, 127, 128, 254, 255])
    def test_group_ids(self, gid):
        g = EmulatedGroup(gid)
        assert g.group_id == gid


# ============================================================
# ESP32EmulatorConfig Tests
# ============================================================

class TestESP32EmulatorConfigExhaustive:
    def test_all_defaults(self):
        c = ESP32EmulatorConfig()
        assert c.tcp_port == 10001
        assert c.tcp_host == "127.0.0.1"
        assert c.firmware_version == "1.0.0"
        assert c.device_type == "ESP32-WROOM-EMULATED"
        assert c.mac_address == "AA:BB:CC:DD:EE:FF"
        assert c.network_id == 254
        assert c.num_groups == 256
        assert c.enable_mdns is False
        assert c.smart_mode_default is True

    @pytest.mark.parametrize("groups", [1, 16, 128, 256, 512])
    def test_custom_num_groups(self, groups):
        c = ESP32EmulatorConfig(num_groups=groups)
        emu = ESP32Emulator(c)
        assert len(emu.groups) == groups


# ============================================================
# ESP32Emulator State Tests
# ============================================================

class TestEmulatorStateExhaustive:
    @pytest.fixture
    def emu(self):
        return ESP32Emulator(ESP32EmulatorConfig(tcp_port=0))

    def test_all_groups_start_at_zero(self, emu):
        for i in range(256):
            assert emu.get_group_level(i) == 0

    @pytest.mark.parametrize("gid", [0, 1, 50, 100, 127, 128, 200, 254, 255])
    def test_set_get_specific_groups(self, emu, gid):
        emu.set_group_level(gid, 128)
        assert emu.get_group_level(gid) == 128

    def test_set_all_256_groups(self, emu):
        for i in range(256):
            emu.set_group_level(i, i)
        for i in range(256):
            assert emu.get_group_level(i) == i

    def test_out_of_range_group_returns_zero(self, emu):
        assert emu.get_group_level(256) == 0
        assert emu.get_group_level(999) == 0

    def test_device_info(self, emu):
        info = emu.device_info
        assert "firmware_version" in info
        assert "device_type" in info
        assert "mac_address" in info
        assert "network_id" in info

    def test_command_log_starts_empty(self, emu):
        assert len(emu.command_log) == 0

    def test_not_running_initially(self, emu):
        assert emu.is_running is False
        assert emu.actual_port == 0


# ============================================================
# ESP32Emulator TCP Tests
# ============================================================

class TestEmulatorTCPExhaustive:
    @pytest_asyncio.fixture
    async def emu(self):
        e = ESP32Emulator(ESP32EmulatorConfig(tcp_port=0, response_delay_ms=1.0))
        await e.start()
        yield e
        await e.stop()

    @pytest.mark.asyncio
    async def test_start_assigns_port(self, emu):
        assert emu.actual_port > 0

    @pytest.mark.asyncio
    async def test_stop_clears_port(self):
        e = ESP32Emulator(ESP32EmulatorConfig(tcp_port=0))
        await e.start()
        assert e.actual_port > 0
        await e.stop()
        assert e.actual_port == 0

    @pytest.mark.asyncio
    async def test_accept_connection(self, emu):
        r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
        w.close()
        await w.wait_closed()

    @pytest.mark.asyncio
    async def test_multiple_sequential_connections(self, emu):
        for _ in range(5):
            r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
            w.close()
            await w.wait_closed()

    @pytest.mark.asyncio
    async def test_concurrent_connections(self, emu):
        conns = []
        for _ in range(5):
            r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
            conns.append((r, w))
        await asyncio.sleep(0.1)
        for r, w in conns:
            w.close()
            await w.wait_closed()

    @pytest.mark.asyncio
    async def test_empty_command_ignored(self, emu):
        r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
        w.write(b"\r\n")
        await w.drain()
        await asyncio.sleep(0.1)
        w.close()
        await w.wait_closed()

    @pytest.mark.asyncio
    async def test_rapid_commands(self, emu):
        r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
        for i in range(20):
            code = bytes([CONF_CODES[i % len(CONF_CODES)]])
            w.write(b"\\053800790" + f"{i % 10}".encode() + code + b"\r\n")
        await w.drain()
        await asyncio.sleep(0.5)
        w.close()
        await w.wait_closed()

    @pytest.mark.asyncio
    async def test_lighting_on_all_groups(self, emu):
        """Test lighting ON for every group 0-255."""
        r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
        for g in range(256):
            cmd = f"\\053800{0x79:02X}{g:02X}h\r\n".encode()
            w.write(cmd)
            await w.drain()
        await asyncio.sleep(1.0)
        data = await asyncio.wait_for(r.read(65536), timeout=2.0)
        w.close()
        await w.wait_closed()
        for g in range(256):
            assert emu.get_group_level(g) == 255, f"Group {g} not set to 255"

    @pytest.mark.asyncio
    async def test_lighting_off_all_groups(self, emu):
        # First set all on
        for g in range(256):
            emu.set_group_level(g, 255)
        r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
        for g in range(256):
            cmd = f"\\053800{0x01:02X}{g:02X}h\r\n".encode()
            w.write(cmd)
            await w.drain()
        await asyncio.sleep(1.0)
        await asyncio.wait_for(r.read(65536), timeout=2.0)
        w.close()
        await w.wait_closed()
        for g in range(256):
            assert emu.get_group_level(g) == 0, f"Group {g} not set to 0"

    @pytest.mark.asyncio
    async def test_ramp_to_each_level(self, emu):
        """Test ramp to levels 0, 64, 128, 192, 255."""
        r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
        for level in [0, 64, 128, 192, 255]:
            cmd = f"\\053800{0x02:02X}01{level:02X}h\r\n".encode()
            w.write(cmd)
            await w.drain()
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)
        await asyncio.wait_for(r.read(4096), timeout=2.0)
        w.close()
        await w.wait_closed()
        # Last ramp should stick
        assert emu.get_group_level(1) == 255

    @pytest.mark.asyncio
    async def test_malformed_hex_handled(self, emu):
        """Malformed hex should not crash the emulator."""
        r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
        w.write(b"\\ZZZZZZZZ\r\n")
        await w.drain()
        await asyncio.sleep(0.1)
        # Should still be running
        assert emu.is_running
        w.close()
        await w.wait_closed()

    @pytest.mark.asyncio
    async def test_binary_garbage_handled(self, emu):
        """Binary garbage should not crash the emulator."""
        r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
        w.write(bytes(range(256)) + b"\r\n")
        await w.drain()
        await asyncio.sleep(0.1)
        assert emu.is_running
        w.close()
        await w.wait_closed()

    @pytest.mark.asyncio
    async def test_very_long_command_handled(self, emu):
        """Very long command should not crash."""
        r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
        w.write(b"A" * 10000 + b"\r\n")
        await w.drain()
        await asyncio.sleep(0.1)
        assert emu.is_running
        w.close()
        await w.wait_closed()

    @pytest.mark.asyncio
    async def test_command_log_grows(self, emu):
        r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
        w.write(b"~~~\r\n")
        await w.drain()
        await asyncio.sleep(0.1)
        assert len(emu.command_log) >= 1
        w.close()
        await w.wait_closed()

    @pytest.mark.asyncio
    async def test_dm_all_four_init_commands(self, emu):
        """Test all four DM commands from PCI init sequence."""
        r, w = await asyncio.open_connection("127.0.0.1", emu.actual_port)
        for cmd in [b"A32100FF", b"A32200FF", b"A342000E", b"A3300079"]:
            w.write(cmd + b"\r\n")
            await w.drain()
            data = await asyncio.wait_for(r.read(1024), timeout=2.0)
            assert b"." in data
        w.close()
        await w.wait_closed()


CONF_CODES = b"hijklmnopqrstuvwxyzg"


# ============================================================
# ESP32Config Exhaustive Tests
# ============================================================

class TestESP32ConfigExhaustive:
    def test_wifi_defaults(self):
        c = ESP32Config.wifi("10.0.0.1")
        assert c.mode == ESP32ConnectionMode.WIFI
        assert c.host == "10.0.0.1"
        assert c.port == 10001
        assert c.reconnect is True

    def test_serial_defaults(self):
        c = ESP32Config.serial("/dev/ttyUSB0")
        assert c.mode == ESP32ConnectionMode.SERIAL
        assert c.device == "/dev/ttyUSB0"
        assert c.baudrate == 9600

    @pytest.mark.parametrize("port", [80, 443, 8080, 10001, 65535])
    def test_wifi_custom_ports(self, port):
        c = ESP32Config.wifi("host", port=port)
        assert c.port == port

    @pytest.mark.parametrize("baud", [9600, 19200, 38400, 57600, 115200])
    def test_serial_custom_bauds(self, baud):
        c = ESP32Config.serial("/dev/tty", baudrate=baud)
        assert c.baudrate == baud

    def test_wifi_with_all_options(self):
        c = ESP32Config.wifi(
            "1.2.3.4", port=9999,
            reconnect=False, reconnect_interval=10.0,
            max_reconnect_attempts=5, connect_timeout=30.0,
            timesync_frequency=600, handle_clock_requests=False,
        )
        assert c.reconnect is False
        assert c.reconnect_interval == 10.0
        assert c.max_reconnect_attempts == 5
        assert c.connect_timeout == 30.0
        assert c.timesync_frequency == 600
        assert c.handle_clock_requests is False


# ============================================================
# ESP32Info Tests
# ============================================================

class TestESP32InfoExhaustive:
    def test_defaults(self):
        i = ESP32Info()
        assert i.firmware_version == "unknown"
        assert i.device_type == "ESP32"
        assert i.mac_address == ""
        assert i.ip_address == ""
        assert i.cbus_network_id == 254

    def test_custom_values(self):
        i = ESP32Info(
            firmware_version="2.0.0",
            device_type="ESP32-S3",
            mac_address="11:22:33:44:55:66",
            ip_address="10.0.0.50",
            cbus_network_id=100,
            uptime_seconds=3600,
        )
        assert i.firmware_version == "2.0.0"
        assert i.uptime_seconds == 3600


# ============================================================
# ESP32Connection Tests
# ============================================================

class TestESP32ConnectionExhaustive:
    def test_wifi_creates_tcp_transport(self):
        c = ESP32Connection(ESP32Config.wifi("1.2.3.4"))
        assert c.transport.transport_type == "tcp"

    def test_serial_creates_serial_transport(self):
        c = ESP32Connection(ESP32Config.serial("/dev/ttyUSB0"))
        assert c.transport.transport_type == "serial"

    def test_protocol_none_before_connect(self):
        c = ESP32Connection(ESP32Config.wifi("1.2.3.4"))
        assert c.protocol is None

    def test_connection_info_has_mode(self):
        c = ESP32Connection(ESP32Config.wifi("1.2.3.4"))
        assert c.connection_info["esp32_mode"] == "wifi"

    def test_serial_connection_info(self):
        c = ESP32Connection(ESP32Config.serial("/dev/ttyUSB0"))
        assert c.connection_info["esp32_mode"] == "serial"

    @pytest.mark.asyncio
    async def test_connect_to_nonexistent_host_fails(self):
        c = ESP32Connection(ESP32Config.wifi("127.0.0.1", port=1, connect_timeout=0.5))
        with pytest.raises(TransportError):
            await c.connect()

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        c = ESP32Connection(ESP32Config.wifi("1.2.3.4"))
        await c.disconnect()  # Should not raise


# ============================================================
# DiscoveredDevice Tests
# ============================================================

class TestDiscoveredDeviceExhaustive:
    def test_creation(self):
        d = DiscoveredDevice(name="test", host="1.2.3.4", port=10001)
        assert d.name == "test"
        assert d.host == "1.2.3.4"
        assert d.port == 10001

    def test_empty_properties(self):
        d = DiscoveredDevice(name="test", host="1.2.3.4", port=10001)
        assert d.properties == {}

    def test_with_properties(self):
        d = DiscoveredDevice(name="test", host="1.2.3.4", port=10001,
                             properties={"fw": "1.0", "type": "ESP32"})
        assert d.properties["fw"] == "1.0"

    def test_manual_factory(self):
        d = DiscoveredDevice.manual("192.168.1.50")
        assert d.host == "192.168.1.50"
        assert d.port == 10001
        assert "manual" in d.name

    def test_manual_custom_port(self):
        d = DiscoveredDevice.manual("10.0.0.1", 9999)
        assert d.port == 9999

    def test_str_contains_name_and_host(self):
        d = DiscoveredDevice(name="bridge-1", host="192.168.1.50", port=10001)
        s = str(d)
        assert "bridge-1" in s
        assert "192.168.1.50" in s

    def test_mdns_service_type(self):
        assert CBUS_MDNS_SERVICE_TYPE == "_cbus._tcp.local."
