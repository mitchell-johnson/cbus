"""ESP32 C-Bus bridge emulator for automated testing.

Emulates an ESP32 device running C-Bus bridge firmware. Accepts TCP
connections and responds to the C-Bus PCI protocol, maintaining internal
group state and emulated bus units. Designed for use in integration tests
without real hardware.
"""
import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from cbus.common import (
    CAL, add_cbus_checksum, DeviceAttribute, GroupState,
)
from cbus.protocol.cal.reply import ReplyCAL

logger = logging.getLogger(__name__)

CONFIRMATION_CODES = b'hijklmnopqrstuvwxyzg'

# CNI unit address (matches real hardware)
CNI_UNIT_ADDRESS = 0x10


@dataclass
class EmulatedUnit:
    """A C-Bus unit on the emulated bus with configurable attributes."""

    address: int
    type_name: str  # 8-char padded, e.g. "KEYGL5  "
    firmware_short: str = "2.5.00  "  # 8-char padded
    firmware_extended: str = "01.05.00"  # 9-byte extended version
    serial_number: bytes = field(
        default_factory=lambda: bytes.fromhex("FFFFFF000000000000000001"))
    manufacturer_code: bytes = field(
        default_factory=lambda: bytes.fromhex("00000000"))
    installed_apps: List[int] = field(default_factory=lambda: [0x38])
    terminal_levels: bytes = field(
        default_factory=lambda: bytes.fromhex("00000000"))
    parameter_area: int = 0x40
    gav_zone_data: bytes = field(default_factory=lambda: b'\x00' * 12)
    group_address_table: bytes = field(default_factory=lambda: b'\xff' * 12)
    output_summary: bytes = field(default_factory=lambda: b'\x00' * 6)
    gav_store: bytes = field(default_factory=lambda: b'\x00' * 6)

    def get_attribute(self, attr: int) -> Optional[bytes]:
        """Return raw bytes for a Device Management attribute."""
        if attr == DeviceAttribute.TYPE_NAME:
            return self.type_name.encode('ascii').ljust(8)[:8]
        elif attr == DeviceAttribute.FIRMWARE_VERSION:
            return self.firmware_short.encode('ascii').ljust(8)[:8]
        elif attr == DeviceAttribute.SERIAL_NUMBER:
            return self.serial_number[:12].ljust(12, b'\x00')
        elif attr == DeviceAttribute.TERMINAL_LEVELS:
            return self.terminal_levels[:4]
        elif attr == DeviceAttribute.GAV_ZONE_DATA:
            return self.gav_zone_data[:12]
        elif attr == DeviceAttribute.OUTPUT_SUMMARY:
            return self.output_summary[:6]
        elif attr == DeviceAttribute.GAV_STORE:
            return self.gav_store[:6]
        elif attr == DeviceAttribute.GROUP_ADDRESS_TABLE:
            return self.group_address_table[:12]
        elif attr == DeviceAttribute.PARAMETER_AREA:
            return bytes([self.parameter_area])
        elif attr == DeviceAttribute.TYPE_IDENTIFICATION:
            return self.manufacturer_code[:4] + \
                self.type_name.encode('ascii').ljust(8)[:8]
        elif attr == DeviceAttribute.INSTALLED_APPS:
            apps = bytearray()
            for app in self.installed_apps:
                apps.append(app)
            return bytes(apps).ljust(44, b'\xff')[:44]
        elif attr == DeviceAttribute.FIRMWARE_EXTENDED:
            return self.firmware_extended.encode('ascii').ljust(9, b'\x00')[:9]
        elif attr == DeviceAttribute.INSTALLED_APPS_SHORT:
            return bytes([len(self.installed_apps)])
        elif attr == DeviceAttribute.IDENTIFY_BLOCK:
            return b'\x00' * 12
        elif attr == DeviceAttribute.DSI_STATUS:
            return b'\x00'
        elif attr == DeviceAttribute.NETWORK_TERMINAL_LEVELS:
            return b'\x00' * 4
        return None


def _make_default_units() -> Dict[int, EmulatedUnit]:
    """Create default bus units matching the real Grenache Way network."""
    units = {}

    units[1] = EmulatedUnit(
        address=1, type_name="RELDN12 ",
        firmware_short="2.7.00  ",
        firmware_extended="01.07.00",
        serial_number=bytes.fromhex("FFFFFF000018A664A3B10001"),
        manufacturer_code=bytes.fromhex("18A664A3"),
        installed_apps=[0x38],
    )
    units[3] = EmulatedUnit(
        address=3, type_name="DIMDN8  ",
        firmware_short="2.7.00  ",
        firmware_extended="01.07.00",
        serial_number=bytes.fromhex("FFFFFF000018A664A3B20002"),
        manufacturer_code=bytes.fromhex("18A664A3"),
        installed_apps=[0x38],
    )
    units[5] = EmulatedUnit(
        address=5, type_name="KEYGL5  ",
        firmware_short="5.5.00  ",
        firmware_extended="01.05.00",
        serial_number=bytes.fromhex("FFFFFF000018B3F682A40001"),
        manufacturer_code=bytes.fromhex("18B3F682"),
        installed_apps=[0x38, 0x19, 0x1B, 0x18, 0x21],
        terminal_levels=bytes.fromhex("800000FF"),
        parameter_area=0x40,
    )
    units[CNI_UNIT_ADDRESS] = EmulatedUnit(
        address=CNI_UNIT_ADDRESS, type_name="PC_CNIED",
        firmware_short="5.5.00  ",
        firmware_extended="01.05.00",
        serial_number=bytes.fromhex("FFFFFF000018B3F682000001"),
        manufacturer_code=bytes.fromhex("18B3F682"),
        installed_apps=[0x38, 0xFF],
    )
    return units


@dataclass
class ESP32EmulatorConfig:
    tcp_port: int = 10001
    tcp_host: str = "127.0.0.1"
    firmware_version: str = "1.0.0"
    device_type: str = "ESP32-WROOM-EMULATED"
    mac_address: str = "AA:BB:CC:DD:EE:FF"
    network_id: int = 254
    num_groups: int = 256
    enable_mdns: bool = False
    response_delay_ms: float = 5.0
    smart_mode_default: bool = True


class EmulatedGroup:
    def __init__(self, group_id: int, name: str = ""):
        self.group_id = group_id
        self.name = name or f"Group {group_id}"
        self._level = 0

    @property
    def level(self) -> int:
        return self._level

    @level.setter
    def level(self, value: int):
        self._level = max(0, min(255, value))

    @property
    def is_on(self) -> bool:
        return self._level > 0


class ESP32Emulator:
    """Emulates an ESP32 C-Bus bridge device for testing."""

    def __init__(self, config: Optional[ESP32EmulatorConfig] = None):
        self._config = config or ESP32EmulatorConfig()
        self._groups: List[EmulatedGroup] = [
            EmulatedGroup(i) for i in range(self._config.num_groups)
        ]
        self._units: Dict[int, EmulatedUnit] = _make_default_units()
        self._server: Optional[asyncio.AbstractServer] = None
        self._clients: List[asyncio.StreamWriter] = []
        self._actual_port: int = 0
        self._command_log: deque = deque(maxlen=10000)

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server.is_serving()

    @property
    def actual_port(self) -> int:
        return self._actual_port

    @property
    def groups(self) -> List[EmulatedGroup]:
        return self._groups

    @property
    def units(self) -> Dict[int, EmulatedUnit]:
        return self._units

    @property
    def device_info(self) -> Dict[str, Any]:
        return {
            "firmware_version": self._config.firmware_version,
            "device_type": self._config.device_type,
            "mac_address": self._config.mac_address,
            "network_id": self._config.network_id,
        }

    @property
    def command_log(self) -> List[Dict[str, Any]]:
        return list(self._command_log)

    def get_group_level(self, group_id: int) -> int:
        if 0 <= group_id < len(self._groups):
            return self._groups[group_id].level
        return 0

    def set_group_level(self, group_id: int, level: int):
        if 0 <= group_id < len(self._groups):
            self._groups[group_id].level = level

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client,
            self._config.tcp_host,
            self._config.tcp_port,
        )
        addr = self._server.sockets[0].getsockname()
        self._actual_port = addr[1]
        logger.info(
            "ESP32 emulator started on %s:%d",
            self._config.tcp_host,
            self._actual_port,
        )

    async def stop(self):
        for writer in self._clients:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self._clients.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._actual_port = 0
        logger.info("ESP32 emulator stopped")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        addr = writer.get_extra_info("peername")
        logger.info("Emulator: client connected from %s", addr)
        self._clients.append(writer)

        try:
            buf = bytearray()
            while True:
                data = await reader.read(1024)
                if not data:
                    break
                buf.extend(data)
                await self._process_buffer(buf, writer)
        except asyncio.CancelledError:
            pass
        except ConnectionResetError:
            pass
        except Exception as e:
            logger.error("Emulator client error: %s", e)
        finally:
            if writer in self._clients:
                self._clients.remove(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info("Emulator: client disconnected from %s", addr)

    async def _process_buffer(
        self, buf: bytearray, writer: asyncio.StreamWriter
    ):
        while True:
            end_pos = -1
            end_len = 0
            cr_pos = buf.find(b"\r")
            if cr_pos >= 0:
                if cr_pos + 1 < len(buf) and buf[cr_pos + 1: cr_pos + 2] == b"\n":
                    end_pos = cr_pos
                    end_len = 2
                else:
                    end_pos = cr_pos
                    end_len = 1

            if end_pos < 0:
                break

            cmd_bytes = bytes(buf[:end_pos])
            del buf[: end_pos + end_len]

            if not cmd_bytes:
                continue

            log_entry: Dict[str, Any] = {"raw": cmd_bytes, "type": "unknown"}
            self._command_log.append(log_entry)

            if self._config.response_delay_ms > 0:
                await asyncio.sleep(self._config.response_delay_ms / 1000.0)

            # Handle reset
            if cmd_bytes in (b"~~~", b"~"):
                log_entry["type"] = "reset"
                continue

            # Handle null (PCI wakeup)
            if cmd_bytes == b"null":
                log_entry["type"] = "null"
                continue

            # Handle Smart+Connect shortcut
            if cmd_bytes in (b"|", b"||"):
                log_entry["type"] = "smart_connect"
                continue

            # Handle DM parameter set: @1A2001, A3XXYY, etc.
            if cmd_bytes.startswith(b"@"):
                log_entry["type"] = "device_management_cal"
                dm_data = cmd_bytes[1:]
                await self._handle_dm_cal(dm_data, writer)
                continue

            if cmd_bytes.startswith(b"A3") or cmd_bytes.startswith(b"@A3"):
                log_entry["type"] = "device_management"
                writer.write(b"g.\r\n")
                await writer.drain()
                continue

            # Handle C-Bus protocol commands starting with backslash
            if cmd_bytes.startswith(b"\\"):
                log_entry["type"] = "cbus_command"
                conf_code = None
                payload = cmd_bytes[1:]

                if payload and bytes([payload[-1]]) in CONFIRMATION_CODES:
                    conf_code = bytes([payload[-1]])
                    payload = payload[:-1]

                try:
                    packet_bytes = bytes.fromhex(payload.decode("ascii"))
                except (ValueError, UnicodeDecodeError):
                    packet_bytes = payload

                if len(packet_bytes) >= 2:
                    dest_type = packet_bytes[0]

                    # Point-to-Point command (0x46 = PP header)
                    if dest_type == 0x46:
                        try:
                            await self._handle_pp_command(
                                packet_bytes[1:], conf_code, writer, log_entry)
                        except Exception as e:
                            logger.debug("PP command error: %s", e)
                            if conf_code:
                                writer.write(conf_code + b".\r\n")
                                await writer.drain()
                        continue

                    # Point-to-Multipoint
                    if len(packet_bytes) >= 4:
                        app_id = packet_bytes[1]

                        if dest_type == 0x05 and app_id == 0x38:
                            self._handle_lighting(
                                packet_bytes, log_entry)

                        elif dest_type == 0x05 and app_id == 0xFF:
                            log_entry["type"] = "status_request"
                            if len(packet_bytes) >= 5:
                                await self._send_binary_status(
                                    writer, packet_bytes[3], packet_bytes[4])

                        elif dest_type == 0x05 and app_id == 0xDF:
                            log_entry["type"] = "clock_update"

                if conf_code is not None:
                    writer.write(conf_code + b".\r\n")
                    await writer.drain()

            # Handle bare DM CAL commands (no @ or \ prefix)
            else:
                bare = cmd_bytes
                conf_code = None
                if bare and bytes([bare[-1]]) in CONFIRMATION_CODES:
                    conf_code = bytes([bare[-1]])
                    bare = bare[:-1]
                try:
                    bytes.fromhex(bare.decode('ascii'))
                except (ValueError, UnicodeDecodeError):
                    continue
                if bare:
                    log_entry["type"] = "bare_dm_cal"
                    await self._handle_dm_cal(bare, writer, conf_code)

    def _handle_lighting(self, packet_bytes: bytes,
                         log_entry: Dict[str, Any]):
        """Handle Point-to-Multipoint lighting command."""
        cmd_type = packet_bytes[3]
        group_addr = packet_bytes[4] if len(packet_bytes) > 4 else 0

        if cmd_type == 0x79:  # ON
            self.set_group_level(group_addr, 255)
            log_entry["type"] = "lighting_on"
            log_entry["group"] = group_addr
        elif cmd_type == 0x01:  # OFF
            self.set_group_level(group_addr, 0)
            log_entry["type"] = "lighting_off"
            log_entry["group"] = group_addr
        elif cmd_type == 0x09:  # TERMINATE_RAMP
            log_entry["type"] = "lighting_terminate_ramp"
            log_entry["group"] = group_addr
        elif 0x02 <= cmd_type <= 0x7A:  # RAMP
            level = packet_bytes[5] if len(packet_bytes) > 5 else 255
            self.set_group_level(group_addr, level)
            log_entry["type"] = "lighting_ramp"
            log_entry["group"] = group_addr
            log_entry["level"] = level

    async def _handle_dm_cal(self, data: bytes,
                             writer: asyncio.StreamWriter,
                             conf_code: Optional[bytes] = None):
        """Handle Device Management CAL commands (@ prefix or bare)."""
        try:
            cal_bytes = bytes.fromhex(data.decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            return

        if not cal_bytes:
            return

        cmd = cal_bytes[0]
        if cmd == CAL.IDENTIFY and len(cal_bytes) >= 2:
            attr = cal_bytes[1]
            cni = self._units.get(CNI_UNIT_ADDRESS)
            if cni:
                attr_data = cni.get_attribute(attr)
                if attr_data is not None:
                    reply = self._build_reply_cal(attr, attr_data)
                    writer.write(reply)
                    await writer.drain()

        elif cmd == CAL.RECALL and len(cal_bytes) >= 3:
            attr = cal_bytes[1]
            count = cal_bytes[2]
            cni = self._units.get(CNI_UNIT_ADDRESS)
            if cni:
                attr_data = cni.get_attribute(attr)
                if attr_data is not None:
                    reply = self._build_reply_cal(attr, attr_data[:count])
                    writer.write(reply)
                    await writer.drain()

        if conf_code:
            writer.write(conf_code + b".\r\n")
            await writer.drain()

    async def _handle_pp_command(self, data: bytes,
                                 conf_code: Optional[bytes],
                                 writer: asyncio.StreamWriter,
                                 log_entry: Dict[str, Any]):
        """Handle Point-to-Point command addressed to a specific unit."""
        if len(data) < 3:
            if conf_code:
                writer.write(conf_code + b".\r\n")
                await writer.drain()
            return

        unit_addr = data[0]
        bridge = data[1]  # 0x00 = no bridge
        cal_data = data[2:]

        log_entry["type"] = "pp_cal"
        log_entry["unit"] = unit_addr

        unit = self._units.get(unit_addr)

        # Send confirmation first
        if conf_code:
            writer.write(conf_code + b".\r\n")
            await writer.drain()

        if not unit or not cal_data:
            return

        # Parse CAL commands (may be chained)
        pos = 0
        while pos < len(cal_data):
            cmd = cal_data[pos]

            if cmd == CAL.IDENTIFY:
                if pos + 1 >= len(cal_data):
                    break
                attr = cal_data[pos + 1]
                pos += 2
                attr_data = unit.get_attribute(attr)
                if attr_data is not None:
                    reply = self._build_pp_reply(
                        unit_addr, attr, attr_data)
                    writer.write(reply)
                    await writer.drain()

            elif cmd == CAL.RECALL:
                if pos + 2 >= len(cal_data):
                    break
                attr = cal_data[pos + 1]
                count = cal_data[pos + 2]
                pos += 3
                attr_data = unit.get_attribute(attr)
                if attr_data is not None:
                    reply = self._build_pp_reply(
                        unit_addr, attr, attr_data[:count])
                    writer.write(reply)
                    await writer.drain()

            else:
                break

    @staticmethod
    def _build_reply_cal(param: int, data: bytes) -> bytes:
        """Build a direct CAL reply (for DM commands to the PCI itself)."""
        raw = add_cbus_checksum(ReplyCAL(param, data).encode())
        return raw.hex().upper().encode('ascii') + b'\r\n'

    @staticmethod
    def _build_pp_reply(source_unit: int, param: int,
                        data: bytes) -> bytes:
        """Build a Point-to-Point reply packet (addressed, from a bus unit)."""
        pp_header = bytes([
            0x86,  # flags: addr_type=6 (PP), priority=2
            source_unit,
            CNI_UNIT_ADDRESS,
            0x00,  # no bridge
        ])
        raw = add_cbus_checksum(pp_header + ReplyCAL(param, data).encode())
        return raw.hex().upper().encode('ascii') + b'\r\n'

    async def _send_binary_status(
        self, writer: asyncio.StreamWriter, app_id: int, block_start: int
    ):
        """Send binary status report for a block of groups."""
        # Build group state bitmap: 4 groups per byte, 2 bits each
        state_bytes = bytearray()
        for byte_idx in range(22):  # 22 bytes = 88 groups per block
            byte_val = 0
            for bit_pair in range(4):
                gid = block_start + byte_idx * 4 + bit_pair
                if gid < len(self._groups):
                    level = self._groups[gid].level
                    if level > 0:
                        state = GroupState.ON
                    else:
                        state = GroupState.OFF
                else:
                    state = GroupState.MISSING
                byte_val |= (state & 0x03) << (6 - bit_pair * 2)
            state_bytes.append(byte_val)

        # PP format with ExtendedCAL status report
        cal_len = len(state_bytes) + 3  # coding + app + block_start + data
        raw = bytes([
            0x86,  # flags: PP, priority 2
            CNI_UNIT_ADDRESS,  # source (CNI)
            CNI_UNIT_ADDRESS,  # dest
            0x00,  # no bridge
            0xE0 | (cal_len & 0x1F),  # ExtendedCAL header
            0x40,  # coding: externally initiated, binary report
            app_id,
            block_start,
        ]) + bytes(state_bytes)
        raw = add_cbus_checksum(raw)
        writer.write(raw.hex().upper().encode('ascii') + b'\r\n')
        await writer.drain()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
