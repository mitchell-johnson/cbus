"""Unit interrogator for reading device details from the C-Bus network.

Connects to a CNI/PCI (or emulator) via TCP and reads Device Management
attributes from individual bus units using the same command sequence that
cmqttd and the C-Bus Toolkit use.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from cbus.common import (
    CAL, DeviceAttribute, CONFIRMATION_CODES, END_RESPONSE,
)
from cbus.protocol.packet import decode_packet
from cbus.protocol.cal.reply import ReplyCAL

logger = logging.getLogger(__name__)

# PP command header byte (Point-to-Point, extended message format)
_PP_HEADER = 0x46


@dataclass
class UnitInfo:
    """Decoded information about a C-Bus unit on the network."""
    address: int
    type_name: str = ""
    firmware_version: str = ""
    firmware_extended: str = ""
    serial_number: bytes = b""
    installed_apps: List[int] = field(default_factory=list)
    terminal_levels: bytes = b""
    parameter_area: int = 0
    gav_zone_data: bytes = b""
    group_address_table: bytes = b""
    output_summary: bytes = b""
    gav_store: bytes = b""
    raw_attributes: Dict[int, bytes] = field(default_factory=dict)

    @property
    def serial_hex(self) -> str:
        return self.serial_number.hex(':') if self.serial_number else ""

    @property
    def unique_id(self) -> str:
        if len(self.serial_number) >= 9:
            return self.serial_number[3:9].hex().upper()
        return ""

    def __str__(self) -> str:
        apps = ', '.join(f'0x{a:02X}' for a in self.installed_apps)
        return (f"Unit {self.address} (0x{self.address:02X}): "
                f"{self.type_name.strip()} fw={self.firmware_version.strip()} "
                f"apps=[{apps}]")


_INTERROGATION_ATTRS = [
    (CAL.IDENTIFY, DeviceAttribute.TYPE_NAME),
    (CAL.IDENTIFY, DeviceAttribute.FIRMWARE_VERSION),
    (CAL.IDENTIFY, DeviceAttribute.SERIAL_NUMBER),
    (CAL.RECALL, DeviceAttribute.TERMINAL_LEVELS),
    (CAL.RECALL, DeviceAttribute.PARAMETER_AREA),
    (CAL.RECALL, DeviceAttribute.INSTALLED_APPS),
    (CAL.RECALL, DeviceAttribute.FIRMWARE_EXTENDED),
    (CAL.RECALL, DeviceAttribute.GAV_ZONE_DATA),
    (CAL.RECALL, DeviceAttribute.GROUP_ADDRESS_TABLE),
    (CAL.RECALL, DeviceAttribute.OUTPUT_SUMMARY),
    (CAL.RECALL, DeviceAttribute.GAV_STORE),
]

_RECALL_COUNTS = {
    DeviceAttribute.TERMINAL_LEVELS: 4,
    DeviceAttribute.PARAMETER_AREA: 1,
    DeviceAttribute.INSTALLED_APPS: 44,
    DeviceAttribute.FIRMWARE_EXTENDED: 9,
    DeviceAttribute.GAV_ZONE_DATA: 12,
    DeviceAttribute.GROUP_ADDRESS_TABLE: 12,
    DeviceAttribute.OUTPUT_SUMMARY: 6,
    DeviceAttribute.GAV_STORE: 6,
}

# Maps DeviceAttribute -> (UnitInfo field name, decoder).
# Decoder is None for raw bytes, 'ascii' for text, or a callable.
_ATTR_DECODERS = {
    DeviceAttribute.TYPE_NAME: ('type_name', 'ascii'),
    DeviceAttribute.FIRMWARE_VERSION: ('firmware_version', 'ascii'),
    DeviceAttribute.SERIAL_NUMBER: ('serial_number', None),
    DeviceAttribute.TERMINAL_LEVELS: ('terminal_levels', None),
    DeviceAttribute.PARAMETER_AREA: ('parameter_area', lambda d: d[0] if d else 0),
    DeviceAttribute.INSTALLED_APPS: ('installed_apps', lambda d: [b for b in d if b != 0xFF]),
    DeviceAttribute.FIRMWARE_EXTENDED: ('firmware_extended', lambda d: d.rstrip(b'\x00').decode('ascii', errors='replace')),
    DeviceAttribute.GAV_ZONE_DATA: ('gav_zone_data', None),
    DeviceAttribute.GROUP_ADDRESS_TABLE: ('group_address_table', None),
    DeviceAttribute.OUTPUT_SUMMARY: ('output_summary', None),
    DeviceAttribute.GAV_STORE: ('gav_store', None),
}


class UnitInterrogator:
    """Reads device attributes from C-Bus units via TCP connection to CNI."""

    def __init__(self, host: str, port: int = 10001,
                 timeout: float = 5.0):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._conf_idx = 0

    async def connect(self):
        """Connect to the CNI and initialize the PCI."""
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port),
            timeout=self._timeout)
        await self._send_raw(b'||')
        await asyncio.sleep(0.1)
        try:
            await asyncio.wait_for(
                self._reader.read(4096), timeout=0.5)
        except asyncio.TimeoutError:
            pass

    async def disconnect(self):
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def interrogate(self, unit_address: int) -> UnitInfo:
        """Read all standard attributes from a unit and return UnitInfo."""
        info = UnitInfo(address=unit_address)

        for cal_cmd, attr in _INTERROGATION_ATTRS:
            try:
                if cal_cmd == CAL.IDENTIFY:
                    data = await self._pp_identify(unit_address, attr)
                elif cal_cmd == CAL.RECALL:
                    count = _RECALL_COUNTS.get(attr, 12)
                    data = await self._pp_recall(unit_address, attr, count)
                else:
                    continue

                if data is not None:
                    info.raw_attributes[attr] = data
                    self._apply_attribute(info, attr, data)
            except (asyncio.TimeoutError, ConnectionError) as e:
                logger.warning("Failed to read attr 0x%02X from unit %d: %s",
                               attr, unit_address, e)

        return info

    async def discover_units(self, max_address: int = 37) -> List[UnitInfo]:
        """Discover all units on the network by reading type names."""
        units = []
        for addr in range(max_address + 1):
            try:
                data = await self._pp_identify(addr, DeviceAttribute.TYPE_NAME)
                if data and data != b'\x00' * len(data):
                    type_name = data.decode('ascii', errors='replace').strip()
                    if type_name:
                        units.append(UnitInfo(address=addr, type_name=type_name))
            except (asyncio.TimeoutError, ConnectionError):
                continue
        return units

    def _next_conf(self) -> bytes:
        code = CONFIRMATION_CODES[self._conf_idx % len(CONFIRMATION_CODES)]
        self._conf_idx += 1
        return bytes([code])

    async def _send_raw(self, data: bytes):
        self._writer.write(data + b'\r')
        await self._writer.drain()

    async def _pp_identify(self, unit: int, attr: int) -> Optional[bytes]:
        """Send PP IDENTIFY command and return reply data."""
        conf = self._next_conf()
        cmd = bytes([_PP_HEADER, unit, 0x00, CAL.IDENTIFY, attr])
        cmd_hex = b'\\' + cmd.hex().upper().encode('ascii') + conf
        await self._send_raw(cmd_hex)
        return await self._read_reply()

    async def _pp_recall(self, unit: int, attr: int,
                         count: int) -> Optional[bytes]:
        """Send PP RECALL command and return reply data."""
        conf = self._next_conf()
        cmd = bytes([_PP_HEADER, unit, 0x00, CAL.RECALL, attr, count])
        cmd_hex = b'\\' + cmd.hex().upper().encode('ascii') + conf
        await self._send_raw(cmd_hex)
        return await self._read_reply()

    async def _read_reply(self) -> Optional[bytes]:
        """Read response packets until we get a reply CAL or timeout."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self._timeout
        buf = bytearray()

        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                chunk = await asyncio.wait_for(
                    self._reader.read(4096), timeout=remaining)
                if not chunk:
                    return None
                buf.extend(chunk)
            except asyncio.TimeoutError:
                break

            while END_RESPONSE in buf:
                line_end = buf.index(END_RESPONSE)
                line = bytes(buf[:line_end])
                del buf[:line_end + len(END_RESPONSE)]

                if len(line) == 2 and line[1:2] == b'.':
                    continue

                try:
                    pkt, _ = decode_packet(
                        line + END_RESPONSE,
                        checksum=True, strict=False, from_pci=True)
                    if pkt is None:
                        continue

                    # PointToPointPacket implements Sequence[AnyCAL]
                    for cal in pkt:
                        if isinstance(cal, ReplyCAL):
                            return cal.data
                except Exception:
                    pass

        return None

    @staticmethod
    def _apply_attribute(info: UnitInfo, attr: int, data: bytes):
        """Apply decoded attribute data to a UnitInfo instance."""
        entry = _ATTR_DECODERS.get(attr)
        if entry is None:
            return
        field_name, decoder = entry
        if decoder is None:
            setattr(info, field_name, data)
        elif decoder == 'ascii':
            setattr(info, field_name, data.decode('ascii', errors='replace'))
        else:
            setattr(info, field_name, decoder(data))

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
