"""Protocol compliance tests verifying the ESP32 emulator matches real PCI behavior."""
import pytest
import pytest_asyncio
import asyncio

from cbus.esp32.emulator.device import ESP32Emulator, ESP32EmulatorConfig


@pytest_asyncio.fixture
async def emulator():
    config = ESP32EmulatorConfig(tcp_port=0, response_delay_ms=1.0)
    emu = ESP32Emulator(config)
    await emu.start()
    yield emu
    await emu.stop()


@pytest_asyncio.fixture
async def client(emulator):
    reader, writer = await asyncio.open_connection(
        "127.0.0.1", emulator.actual_port
    )
    yield reader, writer
    writer.close()
    await writer.wait_closed()


class TestResetBehavior:
    @pytest.mark.asyncio
    async def test_triple_reset(self, client, emulator):
        reader, writer = client
        for _ in range(3):
            writer.write(b"~~~\r\n")
            await writer.drain()
        await asyncio.sleep(0.1)
        resets = [c for c in emulator.command_log if c["type"] == "reset"]
        assert len(resets) == 3


class TestConfirmationCodes:
    CONF_CODES = b"hijklmnopqrstuvwxyzg"

    @pytest.mark.asyncio
    async def test_each_confirmation_code(self, client, emulator):
        reader, writer = client
        writer.write(b"~~~\r\n")
        await writer.drain()
        await asyncio.sleep(0.05)

        for code in self.CONF_CODES:
            code_char = bytes([code])
            cmd = b"\\05380079" + b"01" + code_char + b"\r\n"
            writer.write(cmd)
            await writer.drain()
            await asyncio.sleep(0.05)

            data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            assert code_char + b"." in data, (
                f"Expected confirmation {code_char!r}. in response, got {data!r}"
            )


class TestLightingCommands:
    @pytest.mark.asyncio
    async def test_on_sets_level_255(self, client, emulator):
        reader, writer = client
        # ON command for group 5 with conf code 'h'
        writer.write(b"\\053800790500FFh\r\n")
        await writer.drain()
        await asyncio.sleep(0.1)
        # Read confirmation
        await asyncio.wait_for(reader.read(1024), timeout=2.0)
        assert emulator.get_group_level(5) == 255

    @pytest.mark.asyncio
    async def test_off_sets_level_0(self, client, emulator):
        reader, writer = client
        emulator.set_group_level(5, 255)
        # OFF command for group 5 (0x01 = OFF)
        writer.write(b"\\053800010500h\r\n")
        await writer.drain()
        await asyncio.sleep(0.1)
        await asyncio.wait_for(reader.read(1024), timeout=2.0)
        assert emulator.get_group_level(5) == 0

    @pytest.mark.asyncio
    async def test_all_256_groups(self, client, emulator):
        reader, writer = client
        for g in range(256):
            emulator.set_group_level(g, g)
        for g in range(256):
            assert emulator.get_group_level(g) == g


class TestDeviceManagement:
    @pytest.mark.asyncio
    async def test_dm_command_acknowledged(self, client, emulator):
        reader, writer = client
        writer.write(b"A3300079\r\n")
        await writer.drain()
        await asyncio.sleep(0.1)
        data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
        assert b"." in data
