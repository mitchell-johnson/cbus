"""End-to-end integration tests: ESP32 emulator <-> cbus library over TCP."""
import pytest
import pytest_asyncio
import asyncio

from cbus.esp32.emulator.device import ESP32Emulator, ESP32EmulatorConfig
from cbus.esp32.connection import ESP32Connection, ESP32Config
from cbus.protocol.pciprotocol import PCIProtocol
from cbus.transport.base import TransportState


class TestESP32WiFiIntegration:
    """Tests connecting the real cbus protocol to the ESP32 emulator over TCP."""

    @pytest_asyncio.fixture
    async def emulator(self):
        config = ESP32EmulatorConfig(tcp_port=0, response_delay_ms=1.0)
        emu = ESP32Emulator(config)
        await emu.start()
        yield emu
        await emu.stop()

    @pytest_asyncio.fixture
    async def connection(self, emulator):
        config = ESP32Config.wifi(
            "127.0.0.1",
            port=emulator.actual_port,
            timesync_frequency=0,  # disable timesync for tests
            reconnect=False,
        )
        conn = ESP32Connection(config)
        await conn.connect()
        yield conn
        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_connect_to_emulator(self, emulator):
        """Test that we can establish a TCP connection to the emulator."""
        config = ESP32Config.wifi(
            "127.0.0.1",
            port=emulator.actual_port,
            timesync_frequency=0,
            reconnect=False,
        )
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
        await asyncio.sleep(0.3)
        await connection.protocol.lighting_group_on(1, 0x38)
        await asyncio.sleep(0.3)
        assert emulator.get_group_level(1) == 255

    @pytest.mark.asyncio
    async def test_lighting_off_command(self, connection, emulator):
        """Test sending a lighting OFF command through to the emulator."""
        await asyncio.sleep(0.3)
        emulator.set_group_level(5, 255)
        await connection.protocol.lighting_group_off(5, 0x38)
        await asyncio.sleep(0.3)
        assert emulator.get_group_level(5) == 0

    @pytest.mark.asyncio
    async def test_lighting_ramp_command(self, connection, emulator):
        """Test sending a lighting RAMP command through to the emulator."""
        await asyncio.sleep(0.3)
        await connection.protocol.lighting_group_ramp(3, 0x38, 0, 128)
        await asyncio.sleep(0.3)
        assert emulator.get_group_level(3) == 128

    @pytest.mark.asyncio
    async def test_multiple_groups(self, connection, emulator):
        """Test controlling multiple groups sequentially."""
        await asyncio.sleep(0.3)
        for g in [1, 2, 3]:
            await connection.protocol.lighting_group_on(g, 0x38)
            await asyncio.sleep(0.15)

        await asyncio.sleep(0.3)
        for g in [1, 2, 3]:
            assert emulator.get_group_level(g) == 255, f"Group {g} should be ON"

    @pytest.mark.asyncio
    async def test_emulator_command_log(self, connection, emulator):
        """Test that the emulator logs all commands received."""
        await asyncio.sleep(0.3)
        initial_count = len(emulator.command_log)
        await connection.protocol.lighting_group_on(10, 0x38)
        await asyncio.sleep(0.3)
        assert len(emulator.command_log) > initial_count


class TestESP32EmulatorStandalone:
    """Test the emulator as a standalone TCP server."""

    @pytest.mark.asyncio
    async def test_emulator_accepts_raw_connection(self):
        """Test connecting with raw TCP and sending C-Bus commands."""
        config = ESP32EmulatorConfig(tcp_port=0, response_delay_ms=1.0)
        async with ESP32Emulator(config) as emu:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", emu.actual_port
            )
            # Send a reset command
            writer.write(b"~~~\r\n")
            await writer.drain()
            await asyncio.sleep(0.05)
            # Send a lighting ON command with confirmation
            # \0538007901h = Light ON group 1 with conf code 'h'
            writer.write(b"\\0538007901h\r\n")
            await writer.drain()
            await asyncio.sleep(0.1)
            # Read response (should be confirmation)
            data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            assert b"." in data  # confirmation success marker
            assert emu.get_group_level(1) == 255
            writer.close()
            await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_emulator_multiple_clients(self):
        """Test that multiple clients can connect simultaneously."""
        config = ESP32EmulatorConfig(tcp_port=0, response_delay_ms=1.0)
        async with ESP32Emulator(config) as emu:
            readers_writers = []
            for _ in range(3):
                r, w = await asyncio.open_connection(
                    "127.0.0.1", emu.actual_port
                )
                readers_writers.append((r, w))

            await asyncio.sleep(0.1)
            assert len(emu._clients) == 3

            for _, w in readers_writers:
                w.close()
                await w.wait_closed()
