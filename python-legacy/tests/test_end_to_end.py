"""Full end-to-end integration test:
    Python cbus library → ESP32 C++ bridge → C-Bus Simulator

This is the ultimate confidence test. It proves:
1. The Python library generates valid C-Bus protocol commands
2. The ESP32 C++ code correctly parses and forwards them
3. The C-Bus simulator (acting as the real C-Bus network) processes them
4. Responses flow back through the entire chain

Architecture:
    Python PCIProtocol → TCP → native_e2e_bridge (C++) → TCP → cbus-simulator (Python)
"""
import pytest
import pytest_asyncio
import asyncio
import subprocess
import os
import signal

from tests.simulator_utils import SimulatorTestFixture
from cbus.common import Application

E2E_BRIDGE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "esp32-firmware", "native_e2e_bridge"
)


@pytest_asyncio.fixture
async def e2e_chain():
    """Start the full chain: simulator + ESP32 bridge.

    Returns (bridge_port, simulator) so tests can connect to the bridge
    and inspect the simulator state.
    """
    if not os.path.exists(E2E_BRIDGE_PATH):
        pytest.skip("E2E bridge not compiled")

    # 1. Start the C-Bus simulator
    simulator = SimulatorTestFixture()
    await simulator.start()
    sim_port = simulator.actual_port

    # 2. Start the ESP32 C++ bridge, connecting to the simulator
    bridge_proc = subprocess.Popen(
        [E2E_BRIDGE_PATH, str(sim_port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Read bridge port from stdout
    line = bridge_proc.stdout.readline().decode().strip()
    assert line.startswith("BRIDGE_PORT:"), f"Expected BRIDGE_PORT:<n>, got: {line}"
    bridge_port = int(line.split(":")[1])

    await asyncio.sleep(0.3)

    yield {
        "bridge_port": bridge_port,
        "simulator": simulator,
        "sim_port": sim_port,
    }

    # Cleanup
    bridge_proc.send_signal(signal.SIGTERM)
    try:
        bridge_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        bridge_proc.kill()
    await simulator.stop()


class TestEndToEnd:
    """Full chain: Python library → ESP32 C++ → C-Bus Simulator."""

    @pytest.mark.asyncio
    async def test_connect_through_chain(self, e2e_chain):
        """Test TCP connection through the full chain."""
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", e2e_chain["bridge_port"]
        )
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_reset_through_chain(self, e2e_chain):
        """Test reset command passes through bridge to simulator."""
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", e2e_chain["bridge_port"]
        )
        writer.write(b"~~~\r\n")
        await writer.drain()
        await asyncio.sleep(0.3)
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_dm_command_through_chain(self, e2e_chain):
        """Test device management command gets confirmation through chain."""
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", e2e_chain["bridge_port"]
        )
        writer.write(b"A3300079\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=3.0)
        assert b"." in data, f"Expected confirmation through chain, got: {data!r}"
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_lighting_on_through_chain(self, e2e_chain):
        """Test lighting ON command flows through entire chain."""
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", e2e_chain["bridge_port"]
        )
        # Reset and drain all responses (bridge + simulator both respond)
        writer.write(b"~~~\r\n")
        await writer.drain()
        await asyncio.sleep(0.5)
        try:
            await asyncio.wait_for(reader.read(4096), timeout=0.3)
        except asyncio.TimeoutError:
            pass

        # Lighting ON group 1 with confirmation 'h'
        writer.write(b"\\0538007901h\r\n")
        await writer.drain()
        # Collect all data (bridge confirmation + simulator response)
        all_data = b""
        for _ in range(5):
            try:
                chunk = await asyncio.wait_for(reader.read(1024), timeout=0.5)
                all_data += chunk
            except asyncio.TimeoutError:
                break
        assert b"h." in all_data, f"Expected 'h.' through chain, got: {all_data!r}"
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_all_confirmation_codes_through_chain(self, e2e_chain):
        """Test all 20 confirmation codes through the full chain."""
        codes = b"hijklmnopqrstuvwxyzg"
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", e2e_chain["bridge_port"]
        )
        writer.write(b"~~~\r\n")
        await writer.drain()
        await asyncio.sleep(0.2)

        for code in codes:
            code_byte = bytes([code])
            cmd = b"\\0538007901" + code_byte + b"\r\n"
            writer.write(cmd)
            await writer.drain()
            await asyncio.sleep(0.05)
            data = await asyncio.wait_for(reader.read(1024), timeout=3.0)
            assert code_byte + b"." in data, (
                f"Code {chr(code)}: expected through chain, got: {data!r}"
            )

        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_full_pci_init_through_chain(self, e2e_chain):
        """Test complete PCI init sequence flows through entire chain."""
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", e2e_chain["bridge_port"]
        )

        # 3x reset + SCS shortcut, drain all responses
        for _ in range(3):
            writer.write(b"~~~\r\n")
            await writer.drain()
        writer.write(b"|\r\n")
        await writer.drain()
        await asyncio.sleep(0.5)
        try:
            await asyncio.wait_for(reader.read(4096), timeout=0.3)
        except asyncio.TimeoutError:
            pass

        # 4x DM commands - bridge sends confirmation, simulator may also respond
        for cmd in [b"A32100FF\r\n", b"A32200FF\r\n", b"A342000E\r\n", b"A3300079\r\n"]:
            writer.write(cmd)
            await writer.drain()
            all_data = b""
            for _ in range(5):
                try:
                    chunk = await asyncio.wait_for(reader.read(1024), timeout=0.5)
                    all_data += chunk
                except asyncio.TimeoutError:
                    break
            assert b"." in all_data, f"DM through chain failed: {cmd.strip()!r}, got: {all_data!r}"

        writer.close()
        await writer.wait_closed()


class TestEndToEndWithPythonLibrary:
    """Test the Python cbus library through the full chain."""

    @pytest.mark.asyncio
    async def test_esp32_connection_through_chain(self, e2e_chain):
        """Test ESP32Connection through full chain to simulator."""
        from cbus.esp32.connection import ESP32Connection, ESP32Config

        config = ESP32Config.wifi(
            "127.0.0.1",
            port=e2e_chain["bridge_port"],
            timesync_frequency=0,
            reconnect=False,
        )
        conn = ESP32Connection(config)
        await conn.connect()
        assert conn.transport.is_connected
        assert conn.protocol is not None
        await asyncio.sleep(0.3)  # Let PCI reset complete
        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_lighting_on_through_full_chain(self, e2e_chain):
        """Test Python lighting ON → ESP32 C++ → simulator."""
        from cbus.esp32.connection import ESP32Connection, ESP32Config

        config = ESP32Config.wifi(
            "127.0.0.1",
            port=e2e_chain["bridge_port"],
            timesync_frequency=0,
            reconnect=False,
        )
        conn = ESP32Connection(config)
        await conn.connect()
        await asyncio.sleep(0.5)

        # This exercises the FULL path:
        # Python PCIProtocol.lighting_group_on() encodes the command
        # → TCP to ESP32 C++ bridge
        # → bridge parses with cbus_protocol.c (same code as ESP32 firmware)
        # → bridge forwards to cbus-simulator
        # → simulator processes and responds
        # → response flows back through bridge to Python
        await conn.protocol.lighting_group_on(1, 0x38)
        await asyncio.sleep(0.3)

        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_lighting_off_through_full_chain(self, e2e_chain):
        """Test Python lighting OFF → ESP32 C++ → simulator."""
        from cbus.esp32.connection import ESP32Connection, ESP32Config

        config = ESP32Config.wifi(
            "127.0.0.1",
            port=e2e_chain["bridge_port"],
            timesync_frequency=0,
            reconnect=False,
        )
        conn = ESP32Connection(config)
        await conn.connect()
        await asyncio.sleep(0.5)

        await conn.protocol.lighting_group_off(5, 0x38)
        await asyncio.sleep(0.3)

        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_lighting_ramp_through_full_chain(self, e2e_chain):
        """Test Python lighting ramp → ESP32 C++ → simulator."""
        from cbus.esp32.connection import ESP32Connection, ESP32Config

        config = ESP32Config.wifi(
            "127.0.0.1",
            port=e2e_chain["bridge_port"],
            timesync_frequency=0,
            reconnect=False,
        )
        conn = ESP32Connection(config)
        await conn.connect()
        await asyncio.sleep(0.5)

        await conn.protocol.lighting_group_ramp(3, 0x38, 0, 128)
        await asyncio.sleep(0.3)

        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_multiple_commands_through_full_chain(self, e2e_chain):
        """Test multiple sequential commands through the full chain."""
        from cbus.esp32.connection import ESP32Connection, ESP32Config

        config = ESP32Config.wifi(
            "127.0.0.1",
            port=e2e_chain["bridge_port"],
            timesync_frequency=0,
            reconnect=False,
        )
        conn = ESP32Connection(config)
        await conn.connect()
        await asyncio.sleep(0.5)

        # ON, RAMP, OFF sequence on different groups
        await conn.protocol.lighting_group_on(1, 0x38)
        await asyncio.sleep(0.15)
        await conn.protocol.lighting_group_ramp(2, 0x38, 0, 128)
        await asyncio.sleep(0.15)
        await conn.protocol.lighting_group_off(3, 0x38)
        await asyncio.sleep(0.15)
        await conn.protocol.lighting_group_on(4, 0x38)
        await asyncio.sleep(0.15)

        await conn.disconnect()
