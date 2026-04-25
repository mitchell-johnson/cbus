"""ESP32 C-Bus bridge emulator for automated testing.

Emulates an ESP32 device running C-Bus bridge firmware. Accepts TCP
connections and responds to the C-Bus PCI protocol, maintaining internal
group state. Designed for use in integration tests without real hardware.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CONFIRMATION_CODES = b'hijklmnopqrstuvwxyzg'


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
        self._server: Optional[asyncio.AbstractServer] = None
        self._clients: List[asyncio.StreamWriter] = []
        self._actual_port: int = 0
        self._command_log: List[Dict[str, Any]] = []

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
            # Find end of command
            end_pos = -1
            end_len = 0
            cr_pos = buf.find(b"\r")
            if cr_pos >= 0:
                if cr_pos + 1 < len(buf) and buf[cr_pos + 1 : cr_pos + 2] == b"\n":
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
            if len(self._command_log) > 10000:
                self._command_log = self._command_log[-5000:]

            # Add response delay
            if self._config.response_delay_ms > 0:
                await asyncio.sleep(self._config.response_delay_ms / 1000.0)

            # Handle reset
            if cmd_bytes == b"~~~":
                log_entry["type"] = "reset"
                continue

            # Handle Smart+Connect shortcut
            if cmd_bytes == b"|":
                log_entry["type"] = "smart_connect"
                continue

            # Handle device management commands (A3XXYY format)
            if cmd_bytes.startswith(b"A3") or cmd_bytes.startswith(b"@A3"):
                log_entry["type"] = "device_management"
                writer.write(b"g.\r\n")
                await writer.drain()
                continue

            # Handle C-Bus protocol commands starting with backslash
            if cmd_bytes.startswith(b"\\"):
                log_entry["type"] = "cbus_command"

                # Extract confirmation code (last byte before \r)
                conf_code = None
                payload = cmd_bytes[1:]  # strip leading backslash

                if payload and bytes([payload[-1]]) in CONFIRMATION_CODES:
                    conf_code = bytes([payload[-1]])
                    payload = payload[:-1]

                # Parse the hex-encoded C-Bus packet
                try:
                    packet_bytes = bytes.fromhex(payload.decode("ascii"))
                except (ValueError, UnicodeDecodeError):
                    packet_bytes = payload

                # Process based on packet content
                if len(packet_bytes) >= 4:
                    dest_type = packet_bytes[0]
                    app_id = packet_bytes[1]

                    # Point-to-Multipoint lighting command
                    if dest_type == 0x05 and app_id == 0x38:
                        if len(packet_bytes) >= 4:
                            routing = packet_bytes[2]
                            cmd_type = packet_bytes[3]
                            group_addr = (
                                packet_bytes[4] if len(packet_bytes) > 4 else 0
                            )

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
                                level = (
                                    packet_bytes[5]
                                    if len(packet_bytes) > 5
                                    else 255
                                )
                                self.set_group_level(group_addr, level)
                                log_entry["type"] = "lighting_ramp"
                                log_entry["group"] = group_addr
                                log_entry["level"] = level

                    # Status request
                    elif dest_type == 0x05 and app_id == 0xFF:
                        log_entry["type"] = "status_request"
                        if len(packet_bytes) >= 5:
                            child_app = packet_bytes[3]
                            block_start = packet_bytes[4]
                            await self._send_level_status(
                                writer, child_app, block_start
                            )

                    # Clock update
                    elif dest_type == 0x05 and app_id == 0xDF:
                        log_entry["type"] = "clock_update"

                # Send confirmation if requested
                if conf_code is not None:
                    response = conf_code + b".\r\n"
                    writer.write(response)
                    await writer.drain()

    async def _send_level_status(
        self, writer: asyncio.StreamWriter, app_id: int, block_start: int
    ):
        """Send level status report for a block of 32 groups."""
        levels = []
        for i in range(32):
            gid = block_start + i
            if gid < len(self._groups):
                levels.append(self._groups[gid].level)
            else:
                levels.append(0)

        level_hex = "".join(f"{l:02X}" for l in levels)
        response_hex = f"86FFFF00{app_id:02X}E0{block_start:02X}{level_hex}"
        response = response_hex.encode("ascii") + b"\r\n"
        writer.write(response)
        await writer.drain()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
