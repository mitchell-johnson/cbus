import pytest
import asyncio
import os

from cbus.esp32.emulator.serial_port import VirtualSerialPair


class TestVirtualSerialPair:
    @pytest.mark.asyncio
    async def test_create_pair(self):
        pair = VirtualSerialPair()
        await pair.create()
        assert pair.device_port is not None
        assert pair.client_port is not None
        assert os.path.exists(pair.device_port)
        assert os.path.exists(pair.client_port)
        await pair.close()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with VirtualSerialPair() as pair:
            assert pair.device_port is not None
            assert pair.client_port is not None

    @pytest.mark.asyncio
    async def test_close_cleans_up(self):
        pair = VirtualSerialPair()
        await pair.create()
        await pair.close()
        assert pair.device_port is None
        assert pair.client_port is None
