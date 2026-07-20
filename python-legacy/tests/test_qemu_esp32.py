"""Integration tests against real ESP32 firmware running in QEMU.

Uses Espressif's QEMU fork to run the actual Xtensa firmware binary.
The QEMU test mode firmware uses Serial for C-Bus commands (forwarded to TCP).
"""
import pytest
import pytest_asyncio
import asyncio
import subprocess
import os
import signal
import time

QEMU_BIN = "/tmp/qemu/bin/qemu-system-xtensa"
FLASH_IMAGE = "/tmp/esp32_qemu_test.bin"
def qemu_available():
    return os.path.exists(QEMU_BIN) and os.path.exists(FLASH_IMAGE)


# Module-level QEMU process and port
_qemu_proc = None
_qemu_port = None


def _find_free_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_qemu():
    global _qemu_proc, _qemu_port
    if _qemu_proc is not None and _qemu_proc.poll() is None:
        return _qemu_port

    _qemu_port = _find_free_port()
    _qemu_proc = subprocess.Popen(
        [
            QEMU_BIN,
            "-machine", "esp32",
            "-nographic",
            "-drive", f"file={FLASH_IMAGE},if=mtd,format=raw",
            "-serial", f"tcp:127.0.0.1:{_qemu_port},server=on,wait=off",
            "-no-reboot",
            "-monitor", "none",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for boot
    time.sleep(4)
    if _qemu_proc.poll() is not None:
        raise RuntimeError("QEMU exited early")
    return _qemu_port


def _stop_qemu():
    global _qemu_proc
    if _qemu_proc is not None:
        _qemu_proc.send_signal(signal.SIGTERM)
        try:
            _qemu_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _qemu_proc.kill()
        _qemu_proc = None


@pytest_asyncio.fixture
async def qemu_esp32():
    """Start QEMU ESP32 emulator (one instance for all tests in module)."""
    if not qemu_available():
        pytest.skip("QEMU ESP32 or flash image not available")

    port = _start_qemu()

    # Drain boot output
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await asyncio.sleep(1)
        try:
            await asyncio.wait_for(reader.read(4096), timeout=0.5)
        except asyncio.TimeoutError:
            pass
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass

    yield port

    _stop_qemu()


class TestQemuESP32Protocol:
    """Test C-Bus protocol against real ESP32 firmware in QEMU."""

    @pytest.mark.asyncio
    async def test_connect(self, qemu_esp32):
        """Test TCP connection to QEMU serial port."""
        reader, writer = await asyncio.open_connection("127.0.0.1", qemu_esp32)
        assert reader is not None
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_reset_command(self, qemu_esp32):
        """Test reset command on real ESP32 firmware."""
        reader, writer = await asyncio.open_connection("127.0.0.1", qemu_esp32)
        # Drain boot output
        await asyncio.sleep(0.5)
        try:
            await asyncio.wait_for(reader.read(4096), timeout=0.3)
        except asyncio.TimeoutError:
            pass

        writer.write(b"~~~\r\n")
        await writer.drain()
        await asyncio.sleep(0.2)
        # Reset has no response - just verify no crash
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_device_management_confirmation(self, qemu_esp32):
        """Test DM command gets g. confirmation from real ESP32."""
        reader, writer = await asyncio.open_connection("127.0.0.1", qemu_esp32)
        # Drain boot output
        await asyncio.sleep(0.5)
        try:
            await asyncio.wait_for(reader.read(4096), timeout=0.3)
        except asyncio.TimeoutError:
            pass

        writer.write(b"A3300079\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=3.0)
        assert b"g." in data, f"Expected 'g.' confirmation, got: {data!r}"
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_lighting_on_confirmation(self, qemu_esp32):
        """Test lighting ON gets proper confirmation from real ESP32."""
        reader, writer = await asyncio.open_connection("127.0.0.1", qemu_esp32)
        await asyncio.sleep(0.5)
        try:
            await asyncio.wait_for(reader.read(4096), timeout=0.3)
        except asyncio.TimeoutError:
            pass

        # Reset first
        writer.write(b"~~~\r\n")
        await writer.drain()
        await asyncio.sleep(0.2)

        # Lighting ON group 1 with confirmation 'h'
        writer.write(b"\\0538007901h\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=3.0)
        assert b"h." in data, f"Expected 'h.' confirmation from ESP32, got: {data!r}"
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_lighting_off_confirmation(self, qemu_esp32):
        """Test lighting OFF gets proper confirmation from real ESP32."""
        reader, writer = await asyncio.open_connection("127.0.0.1", qemu_esp32)
        await asyncio.sleep(0.5)
        try:
            await asyncio.wait_for(reader.read(4096), timeout=0.3)
        except asyncio.TimeoutError:
            pass

        writer.write(b"\\0538000105i\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=3.0)
        assert b"i." in data, f"Expected 'i.' confirmation from ESP32, got: {data!r}"
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_all_20_confirmation_codes(self, qemu_esp32):
        """Test every confirmation code works on real ESP32 Xtensa CPU."""
        codes = b"hijklmnopqrstuvwxyzg"
        reader, writer = await asyncio.open_connection("127.0.0.1", qemu_esp32)
        await asyncio.sleep(0.5)
        try:
            await asyncio.wait_for(reader.read(4096), timeout=0.3)
        except asyncio.TimeoutError:
            pass

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
                f"Code {chr(code)}: expected '{chr(code)}.' from ESP32, got: {data!r}"
            )

        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_full_pci_init_sequence(self, qemu_esp32):
        """Test the complete PCI init sequence on real ESP32 Xtensa CPU."""
        reader, writer = await asyncio.open_connection("127.0.0.1", qemu_esp32)
        await asyncio.sleep(0.5)
        try:
            await asyncio.wait_for(reader.read(4096), timeout=0.3)
        except asyncio.TimeoutError:
            pass

        # 3x reset
        for _ in range(3):
            writer.write(b"~~~\r\n")
            await writer.drain()

        # SCS shortcut
        writer.write(b"|\r\n")
        await writer.drain()
        await asyncio.sleep(0.2)

        # 4x DM commands - each should get confirmation
        for cmd in [b"A32100FF\r\n", b"A32200FF\r\n", b"A342000E\r\n", b"A3300079\r\n"]:
            writer.write(cmd)
            await writer.drain()
            data = await asyncio.wait_for(reader.read(1024), timeout=3.0)
            assert b"." in data, f"DM {cmd.strip()!r}: expected confirmation from ESP32"

        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_ramp_command(self, qemu_esp32):
        """Test ramp command on real ESP32."""
        reader, writer = await asyncio.open_connection("127.0.0.1", qemu_esp32)
        await asyncio.sleep(0.5)
        try:
            await asyncio.wait_for(reader.read(4096), timeout=0.3)
        except asyncio.TimeoutError:
            pass

        # Ramp instant group 5 to level 128 with conf 'h'
        writer.write(b"\\053800020580h\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=3.0)
        assert b"h." in data, f"Expected ramp confirmation from ESP32, got: {data!r}"
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_clock_update(self, qemu_esp32):
        """Test clock update on real ESP32."""
        reader, writer = await asyncio.open_connection("127.0.0.1", qemu_esp32)
        await asyncio.sleep(0.5)
        try:
            await asyncio.wait_for(reader.read(4096), timeout=0.3)
        except asyncio.TimeoutError:
            pass

        writer.write(b"\\05DF000801h\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=3.0)
        assert b"h." in data, f"Expected clock confirmation from ESP32, got: {data!r}"
        writer.close()
        await writer.wait_closed()
