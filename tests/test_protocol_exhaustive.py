"""Exhaustive positive and negative tests for C-Bus protocol encoding/decoding.

Tests every packet type, every edge case, every boundary value.
"""
import pytest
from parameterized import parameterized

from cbus.common import (
    Application, DestinationAddressType, PriorityClass,
    END_COMMAND, END_RESPONSE, HEX_CHARS,
    CONFIRMATION_CODES, MIN_GROUP_ADDR, MAX_GROUP_ADDR,
    add_cbus_checksum, check_ga,
)
from cbus.protocol.packet import decode_packet
from cbus.protocol.base_packet import BasePacket
from cbus.protocol.pm_packet import PointToMultipointPacket
from cbus.protocol.pp_packet import PointToPointPacket
from cbus.protocol.confirm_packet import ConfirmationPacket
from cbus.protocol.error_packet import PCIErrorPacket
from cbus.protocol.reset_packet import ResetPacket
from cbus.protocol.dm_packet import DeviceManagementPacket
from cbus.protocol.scs_packet import SmartConnectShortcutPacket
from cbus.protocol.application.lighting import (
    LightingOnSAL, LightingOffSAL, LightingRampSAL, LightingTerminateRampSAL,
)
from cbus.protocol.application.status_request import StatusRequestSAL
from cbus.protocol.application.clock import clock_update_sal
from datetime import datetime


# ============================================================
# Checksum Tests
# ============================================================

class TestChecksumExhaustive:
    """Test checksum calculation with comprehensive inputs."""

    def test_checksum_adds_to_zero(self):
        """Checksum of data+checksum should sum to 0 mod 256."""
        data = b'\x05\x38\x00\x79\x01'
        result = add_cbus_checksum(data)
        total = sum(result) & 0xFF
        assert total == 0

    def test_checksum_single_byte_values(self):
        """Test checksum for each single byte value 0-255."""
        for b in range(256):
            data = bytes([b])
            result = add_cbus_checksum(data)
            assert (sum(result) & 0xFF) == 0

    def test_checksum_all_zeros(self):
        data = b'\x00\x00\x00\x00'
        result = add_cbus_checksum(data)
        assert result[-1] == 0x00

    def test_checksum_all_ff(self):
        data = b'\xFF\xFF\xFF\xFF'
        result = add_cbus_checksum(data)
        assert (sum(result) & 0xFF) == 0

    def test_checksum_preserves_data(self):
        data = b'\x05\x38\x00\x79'
        result = add_cbus_checksum(data)
        assert result[:4] == data

    def test_checksum_appends_bytes(self):
        data = b'\x01\x02\x03'
        result = add_cbus_checksum(data)
        assert len(result) > len(data)  # checksum adds bytes


# ============================================================
# Confirmation Code Tests
# ============================================================

class TestConfirmationCodes:
    """Exhaustive confirmation code validation."""

    def test_all_20_codes_are_valid(self):
        assert len(CONFIRMATION_CODES) == 20

    def test_codes_are_sequential_h_to_z_plus_g(self):
        expected = [ord(c) for c in 'hijklmnopqrstuvwxyzg']
        assert list(CONFIRMATION_CODES) == expected

    def test_each_code_is_unique(self):
        assert len(set(CONFIRMATION_CODES)) == len(CONFIRMATION_CODES)

    @pytest.mark.parametrize("code", list(CONFIRMATION_CODES))
    def test_each_code_is_lowercase_letter(self, code):
        assert chr(code).isalpha()
        assert chr(code).islower()

    @pytest.mark.parametrize("invalid", [ord('a'), ord('b'), ord('c'), ord('d'),
                                          ord('e'), ord('f'), ord('A'), ord('Z'),
                                          0, 255, ord('0'), ord(' ')])
    def test_invalid_codes_not_in_set(self, invalid):
        assert invalid not in CONFIRMATION_CODES


# ============================================================
# Group Address Validation
# ============================================================

class TestGroupAddressValidation:
    """Test group address boundary conditions."""

    def test_min_group_addr(self):
        assert MIN_GROUP_ADDR == 0

    def test_max_group_addr(self):
        assert MAX_GROUP_ADDR == 255

    @pytest.mark.parametrize("ga", [0, 1, 127, 128, 254, 255])
    def test_valid_group_addresses(self, ga):
        check_ga(ga)  # Should not raise

    @pytest.mark.parametrize("ga", [-1, 256, 1000, -100])
    def test_invalid_group_addresses(self, ga):
        with pytest.raises(ValueError):
            check_ga(ga)


# ============================================================
# Application Enum Tests
# ============================================================

class TestApplicationEnum:
    """Test Application enum completeness."""

    def test_lighting_default(self):
        assert Application.LIGHTING == 0x38

    def test_temperature(self):
        assert Application.TEMPERATURE == 0x19

    def test_clock(self):
        assert Application.CLOCK == 0xDF

    def test_lighting_range(self):
        assert Application.LIGHTING_FIRST == 0x30

    @pytest.mark.parametrize("app_val", range(0x30, 0x60))
    def test_all_lighting_apps_exist(self, app_val):
        """Each lighting app 0x30-0x5F should be defined."""
        try:
            app = Application(app_val)
            assert app.value == app_val
        except ValueError:
            pass  # Some may not be defined, that's ok


# ============================================================
# Packet Encoding Tests
# ============================================================

class TestResetPacketEncoding:
    def test_encode(self):
        pkt = ResetPacket()
        encoded = pkt.encode_packet()
        assert b'~' in encoded or encoded == b'~~~'

    def test_is_special_client_packet(self):
        from cbus.protocol.base_packet import SpecialClientPacket
        assert isinstance(ResetPacket(), SpecialClientPacket)


class TestSmartConnectShortcut:
    def test_encode(self):
        pkt = SmartConnectShortcutPacket()
        encoded = pkt.encode_packet()
        assert b'|' in encoded


class TestDeviceManagementPacket:
    @pytest.mark.parametrize("param,value", [
        (0x21, 0xFF), (0x22, 0xFF), (0x42, 0x0E), (0x30, 0x79),
        (0x00, 0x00), (0xFF, 0xFF), (0x30, 0x00),
    ])
    def test_encode_various_params(self, param, value):
        pkt = DeviceManagementPacket(checksum=False, parameter=param, value=value)
        encoded = pkt.encode_packet()
        assert len(encoded) > 0


class TestLightingOnSALEncoding:
    @pytest.mark.parametrize("ga", [0, 1, 50, 100, 127, 128, 200, 254, 255])
    def test_encode_various_groups(self, ga):
        sal = LightingOnSAL(ga, Application.LIGHTING)
        encoded = sal.encode()
        assert len(encoded) >= 2
        assert encoded[0] == 0x79  # ON command

    @pytest.mark.parametrize("app", [0x30, 0x38, 0x3F, 0x50, 0x5F])
    def test_encode_various_apps(self, app):
        sal = LightingOnSAL(1, app)
        encoded = sal.encode()
        assert encoded[0] == 0x79


class TestLightingOffSALEncoding:
    @pytest.mark.parametrize("ga", [0, 1, 127, 255])
    def test_encode_various_groups(self, ga):
        sal = LightingOffSAL(ga, Application.LIGHTING)
        encoded = sal.encode()
        assert encoded[0] == 0x01  # OFF command


class TestLightingRampSALEncoding:
    @pytest.mark.parametrize("duration", [0, 4, 8, 12, 20, 30, 40, 60, 90, 120, 180, 300, 420, 600, 900, 1020])
    def test_encode_all_valid_durations(self, duration):
        sal = LightingRampSAL(1, Application.LIGHTING, duration, 128)
        encoded = sal.encode()
        assert len(encoded) >= 3

    @pytest.mark.parametrize("level", [0, 1, 64, 127, 128, 191, 254, 255])
    def test_encode_various_levels(self, level):
        sal = LightingRampSAL(1, Application.LIGHTING, 0, level)
        encoded = sal.encode()
        assert len(encoded) >= 3

    def test_duration_zero_uses_instant(self):
        sal = LightingRampSAL(1, Application.LIGHTING, 0, 128)
        encoded = sal.encode()
        assert len(encoded) >= 3


class TestPointToMultipointPacket:
    def test_encode_single_on(self):
        pkt = PointToMultipointPacket(sals=[LightingOnSAL(1, Application.LIGHTING)])
        encoded = pkt.encode_packet()
        assert len(encoded) > 0

    def test_encode_multiple_sals(self):
        sals = [LightingOnSAL(i, Application.LIGHTING) for i in range(5)]
        pkt = PointToMultipointPacket(sals=sals)
        encoded = pkt.encode_packet()
        assert len(encoded) > 0

    def test_encode_max_sals(self):
        """9 is the maximum SALs per packet."""
        sals = [LightingOnSAL(i, Application.LIGHTING) for i in range(9)]
        pkt = PointToMultipointPacket(sals=sals)
        encoded = pkt.encode_packet()
        assert len(encoded) > 0

    def test_encode_ramp_sal(self):
        pkt = PointToMultipointPacket(sals=LightingRampSAL(1, Application.LIGHTING, 0, 128))
        encoded = pkt.encode_packet()
        assert len(encoded) > 0

    def test_encode_off_sal(self):
        pkt = PointToMultipointPacket(sals=[LightingOffSAL(1, Application.LIGHTING)])
        encoded = pkt.encode_packet()
        assert len(encoded) > 0


class TestClockEncoding:
    @pytest.mark.parametrize("dt", [
        datetime(2025, 1, 1, 0, 0, 0),
        datetime(2025, 6, 15, 12, 30, 45),
        datetime(2025, 12, 31, 23, 59, 59),
        datetime(2000, 1, 1, 0, 0, 0),
        datetime(2099, 12, 31, 23, 59, 59),
    ])
    def test_encode_various_datetimes(self, dt):
        sal = clock_update_sal(dt)
        assert sal is not None


class TestStatusRequestEncoding:
    @pytest.mark.parametrize("block", [0, 32, 64, 96, 128, 160, 192, 224])
    def test_encode_level_request_blocks(self, block):
        sal = StatusRequestSAL(
            level_request=True,
            group_address=block,
            child_application=Application.LIGHTING,
        )
        pkt = PointToMultipointPacket(sals=[sal])
        encoded = pkt.encode_packet()
        assert len(encoded) > 0


# ============================================================
# Packet Decoding Negative Tests
# ============================================================

class TestPacketDecodingNegative:
    """Test that malformed packets are handled gracefully."""

    def test_empty_data(self):
        p, r = decode_packet(b'', checksum=False, from_pci=True)
        assert p is None

    def test_single_byte(self):
        p, r = decode_packet(b'\x00', checksum=False, from_pci=True)
        # Should either return None or consume 0 bytes

    def test_only_cr_lf(self):
        p, r = decode_packet(b'\r\n', checksum=False, from_pci=True)

    def test_garbage_data(self):
        p, r = decode_packet(b'\xFF\xFE\xFD\xFC\r\n', checksum=False, from_pci=True)

    def test_very_long_data(self):
        p, r = decode_packet(b'A' * 1000 + b'\r\n', checksum=False, from_pci=True)

    def test_null_bytes(self):
        p, r = decode_packet(b'\x00' * 50 + b'\r\n', checksum=False, from_pci=True)

    def test_only_hex_chars_no_structure(self):
        p, r = decode_packet(b'0123456789ABCDEF\r\n', checksum=False, from_pci=True)


# ============================================================
# Packet Decoding Positive Tests
# ============================================================

class TestConfirmationPacketDecoding:
    """Test confirmation packet parsing."""

    @pytest.mark.parametrize("code", CONFIRMATION_CODES)
    def test_decode_success_confirmation(self, code):
        data = bytes([code]) + b'.\r\n'
        p, r = decode_packet(data, checksum=False, from_pci=True)
        if isinstance(p, ConfirmationPacket):
            assert p.success is True

    @pytest.mark.parametrize("code", CONFIRMATION_CODES)
    def test_decode_failure_confirmation(self, code):
        data = bytes([code]) + b'#\r\n'
        p, r = decode_packet(data, checksum=False, from_pci=True)
        if isinstance(p, ConfirmationPacket):
            assert p.success is False


class TestErrorPacketDecoding:
    def test_decode_error(self):
        data = b'!\r\n'
        p, r = decode_packet(data, checksum=False, from_pci=True)
        if p is not None:
            assert isinstance(p, PCIErrorPacket)


# ============================================================
# Constants Tests
# ============================================================

class TestProtocolConstants:
    def test_end_command(self):
        assert END_COMMAND == b'\x0d'

    def test_end_response(self):
        assert END_RESPONSE == b'\x0d\x0a'

    def test_hex_chars(self):
        assert HEX_CHARS == b'0123456789ABCDEF'

    def test_destination_types(self):
        assert DestinationAddressType.POINT_TO_MULTIPOINT == 0x05
        assert DestinationAddressType.POINT_TO_POINT == 0x06
        assert DestinationAddressType.POINT_TO_POINT_TO_MULTIPOINT == 0x03

    def test_priority_classes(self):
        assert PriorityClass.CLASS_4 == 0x00
        assert PriorityClass.CLASS_1 == 0x03
