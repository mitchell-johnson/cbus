"""Integration tests running against real ESP32 firmware in Wokwi simulator.

These tests connect to an ESP32 running in Wokwi's ESP32 emulator.
The firmware is the EXACT binary that would be flashed to real hardware.

Requirements:
    - wokwi-cli installed
    - WOKWI_CLI_TOKEN env var set
    - ESP32 firmware compiled (.pio/build/esp32dev/firmware.bin)

Usage:
    pytest tests/test_wokwi_esp32.py -v
"""
import pytest
import pytest_asyncio
import asyncio
import subprocess
import os
import signal
import sys
import time

FIRMWARE_DIR = os.path.join(os.path.dirname(__file__), "..", "esp32-firmware")
WOKWI_CLI = os.path.expanduser("~/.wokwi/bin/wokwi-cli")


def wokwi_available():
    return (
        os.path.exists(WOKWI_CLI)
        and os.environ.get("WOKWI_CLI_TOKEN")
        and os.path.exists(os.path.join(FIRMWARE_DIR, ".pio/build/esp32dev/firmware.bin"))
    )


@pytest_asyncio.fixture(scope="module")
async def wokwi_esp32():
    """Start the Wokwi ESP32 simulator and wait for the bridge to be ready.

    The firmware prints "CBUS_BRIDGE_READY:<ip>:<port>" on serial when
    WiFi is connected and the TCP server is listening. We read serial
    output to detect this, then use port forwarding (localhost:10001)
    to connect.
    """
    if not wokwi_available():
        pytest.skip("Wokwi CLI not available or firmware not compiled")

    proc = subprocess.Popen(
        [
            WOKWI_CLI,
            FIRMWARE_DIR,
            "--timeout", "60000",
            "--serial-log-file", "/tmp/wokwi_serial.log",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "WOKWI_CLI_TOKEN": os.environ["WOKWI_CLI_TOKEN"]},
    )

    # Wait for the bridge to come up by polling the serial log
    ready = False
    for _ in range(40):  # 40 * 0.5s = 20s max wait
        await asyncio.sleep(0.5)
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            pytest.fail(f"Wokwi exited early: {stderr}")
        try:
            with open("/tmp/wokwi_serial.log", "r") as f:
                log = f.read()
                if "CBUS_BRIDGE_READY:" in log:
                    ready = True
                    break
        except FileNotFoundError:
            continue

    if not ready:
        proc.terminate()
        try:
            with open("/tmp/wokwi_serial.log", "r") as f:
                print("Serial log:", f.read(), file=sys.stderr)
        except FileNotFoundError:
            pass
        pytest.fail("ESP32 bridge did not become ready within 20s")

    # Port forwarding: localhost:10001 -> ESP32:10001
    yield {"host": "127.0.0.1", "port": 10001}

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


class TestWokwiESP32:
    """Tests running against the actual ESP32 firmware in Wokwi."""

    @pytest.mark.asyncio
    async def test_tcp_connect(self, wokwi_esp32):
        """Test TCP connection to the simulated ESP32."""
        reader, writer = await asyncio.open_connection(
            wokwi_esp32["host"], wokwi_esp32["port"]
        )
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_reset_command(self, wokwi_esp32):
        """Test sending reset to the simulated ESP32."""
        reader, writer = await asyncio.open_connection(
            wokwi_esp32["host"], wokwi_esp32["port"]
        )
        writer.write(b"~~~\r\n")
        await writer.drain()
        await asyncio.sleep(0.2)
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_device_management(self, wokwi_esp32):
        """Test DM command gets confirmation from simulated ESP32."""
        reader, writer = await asyncio.open_connection(
            wokwi_esp32["host"], wokwi_esp32["port"]
        )
        writer.write(b"A3300079\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=3.0)
        assert b"." in data, f"Expected confirmation, got: {data!r}"
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_lighting_on(self, wokwi_esp32):
        """Test lighting ON command on simulated ESP32."""
        reader, writer = await asyncio.open_connection(
            wokwi_esp32["host"], wokwi_esp32["port"]
        )
        writer.write(b"~~~\r\n")
        await writer.drain()
        await asyncio.sleep(0.1)

        writer.write(b"\\0538007901h\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=3.0)
        assert b"h." in data, f"Expected 'h.' confirmation, got: {data!r}"
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_all_confirmation_codes(self, wokwi_esp32):
        """Test all 20 confirmation codes on simulated ESP32."""
        codes = b"hijklmnopqrstuvwxyzg"
        reader, writer = await asyncio.open_connection(
            wokwi_esp32["host"], wokwi_esp32["port"]
        )
        writer.write(b"~~~\r\n")
        await writer.drain()
        await asyncio.sleep(0.1)

        for code in codes:
            code_byte = bytes([code])
            cmd = b"\\0538007901" + code_byte + b"\r\n"
            writer.write(cmd)
            await writer.drain()
            await asyncio.sleep(0.05)
            data = await asyncio.wait_for(reader.read(1024), timeout=3.0)
            assert code_byte + b"." in data, (
                f"Code {code_byte!r}: expected confirmation, got: {data!r}"
            )

        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_full_pci_init_sequence(self, wokwi_esp32):
        """Test the full PCI initialization sequence on simulated ESP32."""
        reader, writer = await asyncio.open_connection(
            wokwi_esp32["host"], wokwi_esp32["port"]
        )

        # 3x reset
        for _ in range(3):
            writer.write(b"~~~\r\n")
            await writer.drain()

        # SCS shortcut
        writer.write(b"|\r\n")
        await writer.drain()
        await asyncio.sleep(0.1)

        # 4x DM commands
        for cmd in [b"A32100FF\r\n", b"A32200FF\r\n", b"A342000E\r\n", b"A3300079\r\n"]:
            writer.write(cmd)
            await writer.drain()
            data = await asyncio.wait_for(reader.read(1024), timeout=3.0)
            assert b"." in data, f"DM {cmd!r}: expected confirmation"

        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_python_library_connection(self, wokwi_esp32):
        """Test the Python cbus library connects to the simulated ESP32."""
        from cbus.esp32.connection import ESP32Connection, ESP32Config

        config = ESP32Config.wifi(
            wokwi_esp32["host"],
            port=wokwi_esp32["port"],
            timesync_frequency=0,
            reconnect=False,
        )
        conn = ESP32Connection(config)
        await conn.connect()
        assert conn.transport.is_connected
        await asyncio.sleep(0.5)

        # Send a lighting command through the Python library
        await conn.protocol.lighting_group_on(1, 0x38)
        await asyncio.sleep(0.3)

        await conn.disconnect()
