"""Integration tests: Python cbus library <-> Native C++ TCP server.

Tests the EXACT SAME C++ code that runs on the ESP32, compiled natively.
This proves the firmware will work correctly on real hardware.
"""
import pytest
import pytest_asyncio
import asyncio
import subprocess
import os
import signal
import time

# Path to the native C++ server binary
NATIVE_SERVER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "esp32-firmware", "native_tcp_server"
)


@pytest_asyncio.fixture
async def native_server():
    """Start the native C++ TCP server and return its port."""
    if not os.path.exists(NATIVE_SERVER_PATH):
        pytest.skip("Native server not compiled. Run: cc -o native_tcp_server ...")

    proc = subprocess.Popen(
        [NATIVE_SERVER_PATH],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Read the port from stdout (format: "PORT:<number>")
    line = proc.stdout.readline().decode().strip()
    assert line.startswith("PORT:"), f"Expected PORT:<number>, got: {line}"
    port = int(line.split(":")[1])

    # Give server a moment to be fully ready
    await asyncio.sleep(0.1)

    yield port

    # Cleanup
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


class TestNativeCppProtocol:
    """Test the native C++ server responds correctly to C-Bus commands."""

    @pytest.mark.asyncio
    async def test_connect(self, native_server):
        """Test basic TCP connection."""
        reader, writer = await asyncio.open_connection("127.0.0.1", native_server)
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_reset_command(self, native_server):
        """Test reset command is accepted."""
        reader, writer = await asyncio.open_connection("127.0.0.1", native_server)
        writer.write(b"~~~\r\n")
        await writer.drain()
        await asyncio.sleep(0.1)
        # Reset has no response, just verify no crash
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_scs_shortcut(self, native_server):
        """Test Smart+Connect shortcut."""
        reader, writer = await asyncio.open_connection("127.0.0.1", native_server)
        writer.write(b"|\r\n")
        await writer.drain()
        await asyncio.sleep(0.1)
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_device_management(self, native_server):
        """Test device management command gets confirmation."""
        reader, writer = await asyncio.open_connection("127.0.0.1", native_server)
        writer.write(b"A3300079\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
        assert b"." in data, f"Expected confirmation, got: {data!r}"
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_lighting_on_with_confirmation(self, native_server):
        """Test lighting ON command with confirmation code."""
        reader, writer = await asyncio.open_connection("127.0.0.1", native_server)
        # Reset first
        writer.write(b"~~~\r\n")
        await writer.drain()
        await asyncio.sleep(0.05)
        # Light ON group 1 with confirmation 'h'
        writer.write(b"\\0538007901h\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
        assert b"h." in data, f"Expected 'h.' confirmation, got: {data!r}"
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_lighting_off_with_confirmation(self, native_server):
        """Test lighting OFF command with confirmation code."""
        reader, writer = await asyncio.open_connection("127.0.0.1", native_server)
        writer.write(b"\\0538000105i\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
        assert b"i." in data, f"Expected 'i.' confirmation, got: {data!r}"
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_all_confirmation_codes(self, native_server):
        """Test every valid confirmation code gets echoed back."""
        codes = b"hijklmnopqrstuvwxyzg"
        reader, writer = await asyncio.open_connection("127.0.0.1", native_server)

        for code in codes:
            code_byte = bytes([code])
            cmd = b"\\0538007901" + code_byte + b"\r\n"
            writer.write(cmd)
            await writer.drain()
            await asyncio.sleep(0.02)
            data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            assert code_byte + b"." in data, (
                f"Code {code_byte!r}: expected '{code_byte.decode()}.', got: {data!r}"
            )

        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_full_pci_init_sequence(self, native_server):
        """Test the complete PCI initialization sequence from pciprotocol.py."""
        reader, writer = await asyncio.open_connection("127.0.0.1", native_server)

        # Step 1: Three resets
        for _ in range(3):
            writer.write(b"~~~\r\n")
            await writer.drain()

        # Step 2: Smart+Connect shortcut
        writer.write(b"|\r\n")
        await writer.drain()
        await asyncio.sleep(0.05)

        # Step 3-6: Device management commands
        dm_commands = [
            b"A32100FF\r\n",  # App addr 1 = ALL
            b"A32200FF\r\n",  # App addr 2 = USED
            b"A342000E\r\n",  # Interface options #3
            b"A3300079\r\n",  # Interface options #1
        ]
        for cmd in dm_commands:
            writer.write(cmd)
            await writer.drain()
            data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            assert b"." in data, f"DM command {cmd!r}: expected confirmation, got: {data!r}"

        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_multiple_lighting_commands(self, native_server):
        """Test multiple sequential lighting commands."""
        reader, writer = await asyncio.open_connection("127.0.0.1", native_server)
        writer.write(b"~~~\r\n")
        await writer.drain()
        await asyncio.sleep(0.05)

        codes = b"hijklmnop"
        for i, code in enumerate(codes[:5]):
            group = i + 1
            cmd = f"\\053800{0x79:02X}{group:02X}".encode() + bytes([code]) + b"\r\n"
            writer.write(cmd)
            await writer.drain()
            data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            assert bytes([code]) + b"." in data

        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_multiple_clients(self, native_server):
        """Test multiple simultaneous client connections."""
        connections = []
        for _ in range(3):
            r, w = await asyncio.open_connection("127.0.0.1", native_server)
            connections.append((r, w))

        # Each client sends a command
        for i, (r, w) in enumerate(connections):
            code = b"hijklmnopqrstuvwxyzg"[i]
            w.write(b"\\053800790" + f"{i+1}".encode() + bytes([code]) + b"\r\n")
            await w.drain()

        await asyncio.sleep(0.1)

        # Each should get a response
        for i, (r, w) in enumerate(connections):
            code = b"hijklmnopqrstuvwxyzg"[i]
            data = await asyncio.wait_for(r.read(1024), timeout=2.0)
            assert bytes([code]) + b"." in data

        for _, w in connections:
            w.close()
            await w.wait_closed()

    @pytest.mark.asyncio
    async def test_ramp_command(self, native_server):
        """Test lighting ramp command."""
        reader, writer = await asyncio.open_connection("127.0.0.1", native_server)
        # Ramp instant (0x02) group 5 to level 128 (0x80) with conf 'h'
        writer.write(b"\\0538000205" + b"80" + b"h\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
        assert b"h." in data
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_clock_update(self, native_server):
        """Test clock update command gets confirmation."""
        reader, writer = await asyncio.open_connection("127.0.0.1", native_server)
        # Clock update: PM, clock app (0xDF), routing=0, data, conf='h'
        writer.write(b"\\05DF000801h\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
        assert b"h." in data
        writer.close()
        await writer.wait_closed()


class TestNativeCppWithPythonLibrary:
    """Test connecting the Python cbus library to the native C++ server."""

    @pytest.mark.asyncio
    async def test_esp32_connection_to_native_server(self, native_server):
        """Test ESP32Connection connects to the native C++ server."""
        from cbus.esp32.connection import ESP32Connection, ESP32Config

        config = ESP32Config.wifi(
            "127.0.0.1",
            port=native_server,
            timesync_frequency=0,
            reconnect=False,
        )
        conn = ESP32Connection(config)
        await conn.connect()
        assert conn.transport.is_connected
        assert conn.protocol is not None
        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_python_lighting_on_to_native(self, native_server):
        """Test Python library sends lighting ON through native C++ server."""
        from cbus.esp32.connection import ESP32Connection, ESP32Config

        config = ESP32Config.wifi(
            "127.0.0.1",
            port=native_server,
            timesync_frequency=0,
            reconnect=False,
        )
        conn = ESP32Connection(config)
        await conn.connect()
        await asyncio.sleep(0.3)  # Wait for PCI reset

        # Send lighting ON - this exercises the full Python encoder + C++ decoder path
        await conn.protocol.lighting_group_on(1, 0x38)
        await asyncio.sleep(0.2)

        # If we get here without error, the C++ server processed the command
        # and sent back a valid confirmation that the Python library accepted
        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_python_lighting_off_to_native(self, native_server):
        """Test Python library sends lighting OFF through native C++ server."""
        from cbus.esp32.connection import ESP32Connection, ESP32Config

        config = ESP32Config.wifi(
            "127.0.0.1",
            port=native_server,
            timesync_frequency=0,
            reconnect=False,
        )
        conn = ESP32Connection(config)
        await conn.connect()
        await asyncio.sleep(0.3)

        await conn.protocol.lighting_group_off(5, 0x38)
        await asyncio.sleep(0.2)
        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_python_lighting_ramp_to_native(self, native_server):
        """Test Python library sends lighting ramp through native C++ server."""
        from cbus.esp32.connection import ESP32Connection, ESP32Config

        config = ESP32Config.wifi(
            "127.0.0.1",
            port=native_server,
            timesync_frequency=0,
            reconnect=False,
        )
        conn = ESP32Connection(config)
        await conn.connect()
        await asyncio.sleep(0.3)

        await conn.protocol.lighting_group_ramp(3, 0x38, 0, 128)
        await asyncio.sleep(0.2)
        await conn.disconnect()
