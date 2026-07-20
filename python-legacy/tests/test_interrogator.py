"""Tests for the UnitInterrogator and emulator Device Management support."""
import asyncio
import pytest

from cbus.esp32.emulator.device import (
    ESP32Emulator, ESP32EmulatorConfig, EmulatedUnit,
)
from cbus.protocol.interrogator import UnitInterrogator, UnitInfo
from cbus.protocol.packet import decode_packet
from cbus.common import DeviceAttribute


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestPacketDecodeFixes:
    """Verify that previously-failing packet types now decode correctly."""

    def test_addr_type_1_identify_reply(self):
        """Address type 1 (short-form PP) should decode as ReplyCAL."""
        data = b'890150435F434E49454421\r\n'
        pkt, consumed = decode_packet(data, checksum=True, strict=True,
                                      from_pci=True)
        assert pkt is not None
        assert type(pkt).__name__ == 'PointToPointPacket'
        assert len(pkt) == 1
        cal = list(pkt)[0]
        assert cal.parameter == 0x01  # TYPE_NAME
        assert cal.data == b'PC_CNIED'

    def test_addr_type_2_dm_reply(self):
        """Address type 2 (DM reply) should decode as ReplyCAL."""
        data = b'8220104E\r\n'
        pkt, consumed = decode_packet(data, checksum=True, strict=True,
                                      from_pci=True)
        assert pkt is not None
        assert type(pkt).__name__ == 'PointToPointPacket'
        assert len(pkt) == 1
        assert list(pkt)[0].parameter == 0x20

    def test_addr_type_7_gav_reply(self):
        """Address type 7 (extended PP) should decode as ReplyCAL."""
        data = b'872AB64CF6BB1A9EE4\r\n'
        pkt, consumed = decode_packet(data, checksum=True, strict=True,
                                      from_pci=True)
        assert pkt is not None
        assert type(pkt).__name__ == 'PointToPointPacket'
        assert list(pkt)[0].parameter == 0x2A  # GAV_STORE

    def test_addr_type_6_still_works(self):
        """Standard PP (addr type 6) should still decode normally."""
        data = b'86011000890152454C444E313220E7\r\n'
        pkt, consumed = decode_packet(data, checksum=True, strict=True,
                                      from_pci=True)
        assert pkt is not None
        assert type(pkt).__name__ == 'PointToPointPacket'
        assert pkt.unit_address == 0x10
        assert pkt.source_address == 0x01
        assert list(pkt)[0].parameter == 0x01
        assert list(pkt)[0].data == b'RELDN12 '

    def test_pp_extended_status_still_works(self):
        """PP with ExtendedCAL status report should still decode."""
        data = (b'86141000F9403800AAAAAAA66A5666AA65A60A'
                b'00000000000000000000005C\r\n')
        pkt, consumed = decode_packet(data, checksum=True, strict=True,
                                      from_pci=True)
        assert pkt is not None
        assert type(pkt).__name__ == 'PointToPointPacket'
        assert pkt.unit_address == 0x10
        assert len(pkt) == 1
        assert type(list(pkt)[0]).__name__ == 'ExtendedCAL'


class TestEmulatedUnit:
    """Test EmulatedUnit attribute retrieval."""

    def test_type_name(self):
        unit = EmulatedUnit(address=5, type_name="KEYGL5  ")
        data = unit.get_attribute(DeviceAttribute.TYPE_NAME)
        assert data == b'KEYGL5  '

    def test_firmware_version(self):
        unit = EmulatedUnit(address=5, type_name="KEYGL5  ",
                            firmware_short="5.5.00  ")
        data = unit.get_attribute(DeviceAttribute.FIRMWARE_VERSION)
        assert data == b'5.5.00  '

    def test_serial_number(self):
        sn = bytes.fromhex("FFFFFF000018B3F682A40001")
        unit = EmulatedUnit(address=5, type_name="KEYGL5  ",
                            serial_number=sn)
        data = unit.get_attribute(DeviceAttribute.SERIAL_NUMBER)
        assert data == sn

    def test_installed_apps(self):
        unit = EmulatedUnit(address=5, type_name="KEYGL5  ",
                            installed_apps=[0x38, 0x19, 0x1B])
        data = unit.get_attribute(DeviceAttribute.INSTALLED_APPS)
        assert data[0] == 0x38
        assert data[1] == 0x19
        assert data[2] == 0x1B
        assert data[3] == 0xFF  # padded

    def test_unknown_attribute_returns_none(self):
        unit = EmulatedUnit(address=5, type_name="KEYGL5  ")
        assert unit.get_attribute(0x99) is None


class TestInterrogatorWithEmulator:
    """End-to-end tests: interrogator -> emulator -> parsed results."""

    def test_interrogate_keygl5(self):
        async def _test():
            config = ESP32EmulatorConfig(tcp_port=0, response_delay_ms=0)
            async with ESP32Emulator(config) as emu:
                async with UnitInterrogator(
                    '127.0.0.1', emu.actual_port, timeout=3.0
                ) as interr:
                    info = await interr.interrogate(5)
                    assert info.type_name.strip() == "KEYGL5"
                    assert "5.00" in info.firmware_version
                    assert info.firmware_extended == "01.05.00"
                    assert info.unique_id == "000018B3F682"
                    assert 0x38 in info.installed_apps
                    assert 0x19 in info.installed_apps
                    assert info.terminal_levels == bytes.fromhex("800000FF")
                    assert info.parameter_area == 0x40
                    assert len(info.raw_attributes) == 11
        run(_test())

    def test_interrogate_reldn12(self):
        async def _test():
            config = ESP32EmulatorConfig(tcp_port=0, response_delay_ms=0)
            async with ESP32Emulator(config) as emu:
                async with UnitInterrogator(
                    '127.0.0.1', emu.actual_port, timeout=3.0
                ) as interr:
                    info = await interr.interrogate(1)
                    assert info.type_name.strip() == "RELDN12"
                    assert 0x38 in info.installed_apps
        run(_test())

    def test_interrogate_nonexistent_unit(self):
        async def _test():
            config = ESP32EmulatorConfig(tcp_port=0, response_delay_ms=0)
            async with ESP32Emulator(config) as emu:
                async with UnitInterrogator(
                    '127.0.0.1', emu.actual_port, timeout=1.0
                ) as interr:
                    info = await interr.interrogate(99)
                    assert info.type_name == ""
                    assert len(info.raw_attributes) == 0
        run(_test())

    def test_interrogate_all_default_units(self):
        async def _test():
            config = ESP32EmulatorConfig(tcp_port=0, response_delay_ms=0)
            async with ESP32Emulator(config) as emu:
                async with UnitInterrogator(
                    '127.0.0.1', emu.actual_port, timeout=3.0
                ) as interr:
                    for addr in [1, 3, 5, 16]:
                        info = await interr.interrogate(addr)
                        assert info.type_name.strip() != "", \
                            f"Unit {addr} has no type name"
                        assert len(info.raw_attributes) >= 8, \
                            f"Unit {addr} only got {len(info.raw_attributes)} attrs"
        run(_test())
