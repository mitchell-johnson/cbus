"""Tests against real ESP32 hardware. Set ESP32_HOST env var to run."""
import pytest
import pytest_asyncio
import asyncio
import os

ESP32_HOST = os.environ.get("ESP32_HOST", "")
ESP32_PORT = int(os.environ.get("ESP32_PORT", "10001"))


def esp32_reachable():
    if not ESP32_HOST:
        return False
    import socket
    try:
        s = socket.create_connection((ESP32_HOST, ESP32_PORT), timeout=2)
        s.close()
        return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


@pytest.fixture(scope="module", autouse=True)
def check_esp32():
    if not esp32_reachable():
        pytest.skip(f"ESP32 not reachable at {ESP32_HOST}:{ESP32_PORT}")


class TestRealESP32RawTCP:
    @pytest.mark.asyncio
    async def test_tcp_connect(self):
        r, w = await asyncio.open_connection(ESP32_HOST, ESP32_PORT)
        w.close()
        await w.wait_closed()

    @pytest.mark.asyncio
    async def test_reset(self):
        r, w = await asyncio.open_connection(ESP32_HOST, ESP32_PORT)
        w.write(b"~~~\r\n")
        await w.drain()
        await asyncio.sleep(0.2)
        try:
            w.close()
            await w.wait_closed()
        except ConnectionResetError:
            pass  # Expected: ESP32 may reset the connection

    @pytest.mark.asyncio
    async def test_dm_confirmation(self):
        r, w = await asyncio.open_connection(ESP32_HOST, ESP32_PORT)
        w.write(b"A3300079\r\n")
        await w.drain()
        data = await asyncio.wait_for(r.read(1024), timeout=3.0)
        assert b"." in data
        w.close()
        await w.wait_closed()

    @pytest.mark.asyncio
    async def test_lighting_on_confirmation(self):
        r, w = await asyncio.open_connection(ESP32_HOST, ESP32_PORT)
        w.write(b"~~~\r\n")
        await w.drain()
        await asyncio.sleep(0.1)
        w.write(b"\\0538007901h\r\n")
        await w.drain()
        data = await asyncio.wait_for(r.read(1024), timeout=3.0)
        assert b"h." in data
        w.close()
        await w.wait_closed()

    @pytest.mark.asyncio
    async def test_all_confirmation_codes(self):
        codes = b"hijklmnopqrstuvwxyzg"
        r, w = await asyncio.open_connection(ESP32_HOST, ESP32_PORT)
        w.write(b"~~~\r\n")
        await w.drain()
        await asyncio.sleep(0.1)
        for code in codes:
            cb = bytes([code])
            w.write(b"\\0538007901" + cb + b"\r\n")
            await w.drain()
            await asyncio.sleep(0.05)
            data = await asyncio.wait_for(r.read(1024), timeout=3.0)
            assert cb + b"." in data, f"Code {chr(code)}: got {data!r}"
        w.close()
        await w.wait_closed()

    @pytest.mark.asyncio
    async def test_full_pci_init_sequence(self):
        r, w = await asyncio.open_connection(ESP32_HOST, ESP32_PORT)
        for _ in range(3):
            w.write(b"~~~\r\n")
            await w.drain()
        w.write(b"|\r\n")
        await w.drain()
        await asyncio.sleep(0.2)
        for cmd in [b"A32100FF\r\n", b"A32200FF\r\n", b"A342000E\r\n", b"A3300079\r\n"]:
            w.write(cmd)
            await w.drain()
            data = await asyncio.wait_for(r.read(1024), timeout=3.0)
            assert b"." in data
        w.close()
        await w.wait_closed()


class TestRealESP32PythonLibrary:
    @pytest.mark.asyncio
    async def test_esp32_connection(self):
        from cbus.esp32.connection import ESP32Connection, ESP32Config
        config = ESP32Config.wifi(ESP32_HOST, port=ESP32_PORT, timesync_frequency=0, reconnect=False)
        conn = ESP32Connection(config)
        await conn.connect()
        assert conn.transport.is_connected
        assert conn.protocol is not None
        await asyncio.sleep(0.5)
        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_lighting_on(self):
        from cbus.esp32.connection import ESP32Connection, ESP32Config
        config = ESP32Config.wifi(ESP32_HOST, port=ESP32_PORT, timesync_frequency=0, reconnect=False)
        conn = ESP32Connection(config)
        await conn.connect()
        await asyncio.sleep(0.5)
        await conn.protocol.lighting_group_on(1, 0x38)
        await asyncio.sleep(0.3)
        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_lighting_off(self):
        from cbus.esp32.connection import ESP32Connection, ESP32Config
        config = ESP32Config.wifi(ESP32_HOST, port=ESP32_PORT, timesync_frequency=0, reconnect=False)
        conn = ESP32Connection(config)
        await conn.connect()
        await asyncio.sleep(0.5)
        await conn.protocol.lighting_group_off(1, 0x38)
        await asyncio.sleep(0.3)
        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_lighting_ramp(self):
        from cbus.esp32.connection import ESP32Connection, ESP32Config
        config = ESP32Config.wifi(ESP32_HOST, port=ESP32_PORT, timesync_frequency=0, reconnect=False)
        conn = ESP32Connection(config)
        await conn.connect()
        await asyncio.sleep(0.5)
        await conn.protocol.lighting_group_ramp(3, 0x38, 0, 128)
        await asyncio.sleep(0.3)
        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_multiple_commands(self):
        from cbus.esp32.connection import ESP32Connection, ESP32Config
        config = ESP32Config.wifi(ESP32_HOST, port=ESP32_PORT, timesync_frequency=0, reconnect=False)
        conn = ESP32Connection(config)
        await conn.connect()
        await asyncio.sleep(0.5)
        for g in range(1, 6):
            await conn.protocol.lighting_group_on(g, 0x38)
            await asyncio.sleep(0.15)
        for g in range(1, 6):
            await conn.protocol.lighting_group_off(g, 0x38)
            await asyncio.sleep(0.15)
        await conn.disconnect()
