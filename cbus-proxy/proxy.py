#!/usr/bin/env python3
"""
C-Bus Protocol Analyzer and Proxy

This module implements a transparent proxy between cmqttd and a real CNI/PCI,
intercepting and logging all communications with detailed packet analysis.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, Set
import socket
from asyncio import StreamReader, StreamWriter
import argparse
import sys
from enum import Enum
import colorama
from colorama import Fore, Back, Style

from cbus.protocol.packet import decode_packet
from cbus.protocol.base_packet import BasePacket, InvalidPacket
from cbus.protocol.reset_packet import ResetPacket
from cbus.protocol.confirm_packet import ConfirmationPacket
from cbus.protocol.error_packet import PCIErrorPacket
from cbus.protocol.pm_packet import PointToMultipointPacket
from cbus.protocol.pp_packet import PointToPointPacket
from cbus.protocol.dm_packet import DeviceManagementPacket
from cbus.protocol.po_packet import PowerOnPacket
from cbus.protocol.application.lighting import (
    LightingSAL, LightingOnSAL, LightingOffSAL, LightingRampSAL, LightingTerminateRampSAL
)
from cbus.protocol.application.clock import ClockSAL, ClockUpdateSAL, ClockRequestSAL
from cbus.protocol.application.status_request import StatusRequestSAL
from cbus.protocol.cal.report import BinaryStatusReport, LevelStatusReport
from cbus.protocol.cal.extended import ExtendedCAL
from cbus.common import (
    Application, CONFIRMATION_CODES, HEX_CHARS, 
    LightCommand, ramp_rate_to_duration,
    END_COMMAND, END_RESPONSE
)

# Initialize colorama for cross-platform colored output
colorama.init()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('cbus.proxy')


class Direction(Enum):
    """Direction of packet flow"""
    FROM_CLIENT = "CLIENT→CNI"  # From cmqttd to CNI
    FROM_CNI = "CNI→CLIENT"     # From CNI to cmqttd


class ClientInfo:
    """Information about a connected client"""
    def __init__(self, writer: StreamWriter, address: str):
        self.writer = writer
        self.address = address
        self.connected_at = datetime.now()
        self.packet_count = 0
        
    def __str__(self):
        return f"Client({self.address})"


class PacketAnalyzer:
    """Analyzes C-Bus packets and provides detailed explanations"""
    
    def __init__(self):
        self.packet_count = 0
        self.error_count = 0
        self.confirmation_map: Dict[int, Tuple[datetime, str]] = {}
        
    def format_hex(self, data: bytes) -> str:
        """Format bytes as hex string with ASCII representation"""
        hex_str = ' '.join(f'{b:02X}' for b in data)
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data)
        return f"{hex_str:<48} | {ascii_str}"
    
    def get_application_name(self, app_id: int) -> str:
        """Get human-readable application name"""
        if app_id is None:
            return "Unknown App"
            
        if Application.LIGHTING_FIRST <= app_id <= Application.LIGHTING_LAST:
            return f"Lighting App {app_id:02X}"
        
        app_names = {
            0x19: "Temperature",      # Application.TEMPERATURE
            0xDF: "Clock",           # Application.CLOCK
            0xCA: "Trigger",         # Application.TRIGGER
            0xCB: "Enable",          # Application.ENABLE
            0xFF: "Status Request"   # Application.STATUS_REQUEST
        }
        return app_names.get(app_id, f"Unknown App {app_id:02X}")
    
    def get_light_command_name(self, cmd: int) -> str:
        """Get human-readable lighting command name"""
        if cmd == LightCommand.ON:
            return "ON"
        elif cmd == LightCommand.OFF:
            return "OFF"
        elif cmd == LightCommand.TERMINATE_RAMP:
            return "TERMINATE RAMP"
        elif LightCommand.RAMP_INSTANT <= cmd <= LightCommand.RAMP_FASTEST:
            return "RAMP INSTANT"
        elif LightCommand.RAMP_00_04 <= cmd <= LightCommand.RAMP_SLOWEST:
            try:
                duration = ramp_rate_to_duration(cmd)
                minutes = duration // 60
                seconds = duration % 60
                if minutes > 0:
                    return f"RAMP {minutes}m{seconds:02d}s"
                else:
                    return f"RAMP {seconds}s"
            except:
                return f"RAMP (cmd: {cmd:02X})"
        else:
            return f"Unknown ({cmd:02X})"
    
    def analyze_packet(self, raw_data: bytes, direction: Direction, client_info: Optional[ClientInfo] = None) -> str:
        """Analyze a packet and return detailed explanation"""
        self.packet_count += 1
        
        # Format header with direction and packet number
        header_color = Fore.CYAN if direction == Direction.FROM_CLIENT else Fore.YELLOW
        client_tag = f" [{client_info}]" if client_info and direction == Direction.FROM_CLIENT else ""
        header = f"\n{header_color}━━━ Packet #{self.packet_count} {direction.value}{client_tag} ━━━{Style.RESET_ALL}"
        
        # Show raw data
        raw_display = f"{Fore.BLUE}Raw Data:{Style.RESET_ALL}\n{self.format_hex(raw_data)}"
        
        # Decode packet
        try:
            from_pci = (direction == Direction.FROM_CNI)
            packet, consumed = decode_packet(raw_data, from_pci=from_pci)
            
            if packet is None:
                return f"{header}\n{raw_display}\n{Fore.RED}Failed to decode packet{Style.RESET_ALL}"
            
            # Basic packet info
            packet_info = [
                f"{Fore.GREEN}Packet Type:{Style.RESET_ALL} {type(packet).__name__}",
            ]
            
            # Analyze specific packet types
            if isinstance(packet, ResetPacket):
                packet_info.append(f"{Fore.MAGENTA}Action:{Style.RESET_ALL} PCI Reset Request")
                
            elif isinstance(packet, ConfirmationPacket):
                code_int = ord(packet.code)
                status = "SUCCESS" if packet.success else "FAILURE"
                status_color = Fore.GREEN if packet.success else Fore.RED
                packet_info.extend([
                    f"{Fore.MAGENTA}Confirmation Code:{Style.RESET_ALL} {code_int} (0x{code_int:02X}, '{packet.code.decode('ascii', errors='ignore')}')",
                    f"{Fore.MAGENTA}Status:{Style.RESET_ALL} {status_color}{status}{Style.RESET_ALL}"
                ])
                
                # Look up what command this confirms
                if code_int in self.confirmation_map:
                    timestamp, cmd_desc = self.confirmation_map[code_int]
                    elapsed = (datetime.now() - timestamp).total_seconds()
                    packet_info.append(f"{Fore.MAGENTA}Confirms:{Style.RESET_ALL} {cmd_desc} (sent {elapsed:.3f}s ago)")
                    del self.confirmation_map[code_int]
                    
            elif isinstance(packet, PCIErrorPacket):
                self.error_count += 1
                packet_info.append(f"{Fore.RED}ERROR: PCI cannot accept data (buffer full or invalid checksum){Style.RESET_ALL}")
                
            elif isinstance(packet, PowerOnPacket):
                packet_info.append(f"{Fore.MAGENTA}Event:{Style.RESET_ALL} PCI Power On")
                
            elif isinstance(packet, PointToMultipointPacket):
                # Handle source address safely
                if hasattr(packet, 'source_address') and packet.source_address is not None:
                    packet_info.extend([
                        f"{Fore.MAGENTA}Source Address:{Style.RESET_ALL} {packet.source_address} (0x{packet.source_address:02X})",
                    ])
                else:
                    packet_info.extend([
                        f"{Fore.MAGENTA}Source Address:{Style.RESET_ALL} None (command originated locally)",
                    ])
                
                if packet.confirmation:
                    code_int = ord(packet.confirmation)
                    packet_info.append(f"{Fore.MAGENTA}Confirmation Code:{Style.RESET_ALL} {code_int} (0x{code_int:02X}, '{packet.confirmation.decode('ascii', errors='ignore')}')")
                
                # Analyze SAL data
                for sal in packet:
                    sal_info = self._analyze_sal(sal, packet.confirmation)
                    if sal_info:
                        packet_info.extend(sal_info)
                        
            elif isinstance(packet, PointToPointPacket):
                packet_info.extend([
                    f"{Fore.MAGENTA}Destination:{Style.RESET_ALL} Unit {packet.unit_address} (0x{packet.unit_address:02X})",
                ])
                
                if hasattr(packet, 'source_address') and packet.source_address is not None:
                    packet_info.append(f"{Fore.MAGENTA}Source Address:{Style.RESET_ALL} {packet.source_address} (0x{packet.source_address:02X})")
                
                # Analyze CAL data
                for cal in packet:
                    cal_info = self._analyze_cal(cal)
                    if cal_info:
                        packet_info.extend(cal_info)
                        
            elif isinstance(packet, DeviceManagementPacket):
                packet_info.append(f"{Fore.MAGENTA}Device Management Command{Style.RESET_ALL}")
                
            elif isinstance(packet, InvalidPacket):
                self.error_count += 1
                packet_info.extend([
                    f"{Fore.RED}INVALID PACKET{Style.RESET_ALL}",
                    f"{Fore.RED}Error:{Style.RESET_ALL} {packet.exception}"
                ])
                
            # Combine all information
            details = '\n'.join(packet_info)
            return f"{header}\n{raw_display}\n\n{details}"
            
        except Exception as e:
            self.error_count += 1
            error_msg = f"{Fore.RED}Exception during analysis: {str(e)}{Style.RESET_ALL}"
            logger.exception("Error analyzing packet")
            return f"{header}\n{raw_display}\n{error_msg}"
    
    def _analyze_sal(self, sal: Any, confirmation: Optional[bytes]) -> list:
        """Analyze SAL (Smart Application Language) data"""
        info = []
        
        if isinstance(sal, LightingOnSAL):
            app_name = self.get_application_name(sal.application_address) if hasattr(sal, 'application_address') else "Unknown App"
            group_addr = sal.group_address if hasattr(sal, 'group_address') and sal.group_address is not None else 0
            
            info.extend([
                f"{Fore.CYAN}━━ Lighting ON Command ━━{Style.RESET_ALL}",
                f"  Application: {app_name}",
                f"  Group: {group_addr} (0x{group_addr:02X})",
            ])
            if confirmation:
                code_int = ord(confirmation)
                self.confirmation_map[code_int] = (datetime.now(), f"Light ON Group {group_addr}")
                
        elif isinstance(sal, LightingOffSAL):
            app_name = self.get_application_name(sal.application_address) if hasattr(sal, 'application_address') else "Unknown App"
            group_addr = sal.group_address if hasattr(sal, 'group_address') and sal.group_address is not None else 0
            
            info.extend([
                f"{Fore.CYAN}━━ Lighting OFF Command ━━{Style.RESET_ALL}",
                f"  Application: {app_name}",
                f"  Group: {group_addr} (0x{group_addr:02X})",
            ])
            if confirmation:
                code_int = ord(confirmation)
                self.confirmation_map[code_int] = (datetime.now(), f"Light OFF Group {group_addr}")
                
        elif isinstance(sal, LightingRampSAL):
            app_name = self.get_application_name(sal.application_address) if hasattr(sal, 'application_address') else "Unknown App"
            group_addr = sal.group_address if hasattr(sal, 'group_address') and sal.group_address is not None else 0
            level = sal.level if hasattr(sal, 'level') and sal.level is not None else 0
            duration = sal.duration if hasattr(sal, 'duration') and sal.duration is not None else 0
            level_percent = (level / 255) * 100 if level else 0
            
            info.extend([
                f"{Fore.CYAN}━━ Lighting RAMP Command ━━{Style.RESET_ALL}",
                f"  Application: {app_name}",
                f"  Group: {group_addr} (0x{group_addr:02X})",
                f"  Target Level: {level} (0x{level:02X}) = {level_percent:.1f}%",
                f"  Duration: {duration} seconds",
            ])
            if confirmation:
                code_int = ord(confirmation)
                self.confirmation_map[code_int] = (datetime.now(), f"Light RAMP Group {group_addr} to {level_percent:.0f}%")
                
        elif isinstance(sal, LightingTerminateRampSAL):
            app_name = self.get_application_name(sal.application_address) if hasattr(sal, 'application_address') else "Unknown App"
            group_addr = sal.group_address if hasattr(sal, 'group_address') and sal.group_address is not None else 0
            
            info.extend([
                f"{Fore.CYAN}━━ Lighting TERMINATE RAMP Command ━━{Style.RESET_ALL}",
                f"  Application: {app_name}",
                f"  Group: {group_addr} (0x{group_addr:02X})",
            ])
            
        elif isinstance(sal, ClockRequestSAL):
            info.extend([
                f"{Fore.CYAN}━━ Clock Request ━━{Style.RESET_ALL}",
                f"  Requesting current time from network"
            ])
            
        elif isinstance(sal, ClockUpdateSAL):
            info.extend([
                f"{Fore.CYAN}━━ Clock Update ━━{Style.RESET_ALL}",
                f"  Time: {sal.val}"
            ])
            
        elif isinstance(sal, StatusRequestSAL):
            app_val = sal.application if hasattr(sal, 'application') and sal.application is not None else 0
            group_start = sal.group_start if hasattr(sal, 'group_start') and sal.group_start is not None else 0
            group_count = sal.group_count if hasattr(sal, 'group_count') and sal.group_count is not None else 0
            
            info.extend([
                f"{Fore.CYAN}━━ Status Request ━━{Style.RESET_ALL}",
                f"  Application: {self.get_application_name(app_val)}",
                f"  Group Start: {group_start} (0x{group_start:02X})",
                f"  Group Count: {group_count}",
                f"  Groups: {group_start} to {group_start + group_count - 1}",
            ])
            if confirmation:
                code_int = ord(confirmation)
                self.confirmation_map[code_int] = (datetime.now(), f"Status Request App {app_val:02X} Groups {group_start}-{group_start + group_count - 1}")
                
        return info
    
    def _analyze_cal(self, cal: Any) -> list:
        """Analyze CAL (C-Bus Application Language) data"""
        info = []
        
        if isinstance(cal, ExtendedCAL):
            if isinstance(cal.report, LevelStatusReport):
                app_val = cal.child_application if hasattr(cal, 'child_application') and cal.child_application is not None else 0
                block_start = cal.block_start if hasattr(cal, 'block_start') and cal.block_start is not None else 0
                
                info.extend([
                    f"{Fore.CYAN}━━ Level Status Report ━━{Style.RESET_ALL}",
                    f"  Application: {self.get_application_name(app_val)}",
                    f"  Block Start: Group {block_start} (0x{block_start:02X})",
                    f"  Levels:"
                ])
                
                # Display levels in a grid format
                if hasattr(cal.report, 'levels') and cal.report.levels:
                    for i, level in enumerate(cal.report.levels):
                        if level is not None:
                            group = block_start + i
                            percent = (level / 255) * 100
                            info.append(f"    Group {group:3d}: {level:3d} (0x{level:02X}) = {percent:5.1f}%")
                        
            elif isinstance(cal.report, BinaryStatusReport):
                app_val = cal.child_application if hasattr(cal, 'child_application') and cal.child_application is not None else 0
                block_start = cal.block_start if hasattr(cal, 'block_start') and cal.block_start is not None else 0
                
                info.extend([
                    f"{Fore.CYAN}━━ Binary Status Report ━━{Style.RESET_ALL}",
                    f"  Application: {self.get_application_name(app_val)}",
                    f"  Block Start: Group {block_start} (0x{block_start:02X})",
                    f"  States:"
                ])
                
                # Display binary states
                if hasattr(cal.report, 'states') and cal.report.states:
                    for i, state in enumerate(cal.report.states):
                        if state is not None:
                            group = block_start + i
                            state_str = "ON" if state else "OFF"
                            state_color = Fore.GREEN if state else Fore.WHITE
                            info.append(f"    Group {group:3d}: {state_color}{state_str}{Style.RESET_ALL}")
                        
        return info
    
    def print_summary(self):
        """Print session summary"""
        print(f"\n{Fore.CYAN}━━━ Session Summary ━━━{Style.RESET_ALL}")
        print(f"Total Packets: {self.packet_count}")
        print(f"Errors: {self.error_count}")
        if self.confirmation_map:
            print(f"Unconfirmed Commands: {len(self.confirmation_map)}")
            for code, (timestamp, desc) in self.confirmation_map.items():
                elapsed = (datetime.now() - timestamp).total_seconds()
                print(f"  - {desc} (code {code}, waiting {elapsed:.1f}s)")


class CBusProxy:
    """C-Bus proxy server that intercepts and logs all communication"""
    
    def __init__(self, listen_host: str, listen_port: int, 
                 target_host: str, target_port: int):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.target_host = target_host
        self.target_port = target_port
        self.analyzer = PacketAnalyzer()
        self.clients: Dict[str, ClientInfo] = {}  # client_id -> ClientInfo
        self.clients_lock = asyncio.Lock()
        self.cni_writer: Optional[StreamWriter] = None
        self.cni_reader: Optional[StreamReader] = None
        self.running = False
        self.cni_connected = False
        self.cni_task: Optional[asyncio.Task] = None
        
    async def start(self):
        """Start the proxy server"""
        self.running = True
        
        # Connect to CNI first
        await self.connect_to_cni()
        
        # Start the CNI reader task
        if self.cni_connected:
            self.cni_task = asyncio.create_task(self.cni_reader_task())
        
        # Start accepting client connections
        server = await asyncio.start_server(
            self.handle_client, self.listen_host, self.listen_port)
        
        addr = server.sockets[0].getsockname()
        logger.info(f"{Fore.GREEN}C-Bus Proxy listening on {addr[0]}:{addr[1]}{Style.RESET_ALL}")
        logger.info(f"Forwarding to CNI at {self.target_host}:{self.target_port}")
        logger.info(f"Configure cmqttd to connect to {addr[0]}:{addr[1]}")
        
        async with server:
            await server.serve_forever()
    
    async def connect_to_cni(self):
        """Establish connection to the real CNI"""
        try:
            self.cni_reader, self.cni_writer = await asyncio.open_connection(
                self.target_host, self.target_port)
            self.cni_connected = True
            logger.info(f"{Fore.GREEN}Connected to CNI at {self.target_host}:{self.target_port}{Style.RESET_ALL}")
        except Exception as e:
            logger.error(f"{Fore.RED}Failed to connect to CNI at {self.target_host}:{self.target_port}: {e}{Style.RESET_ALL}")
            self.cni_connected = False
    
    async def cni_reader_task(self):
        """Task that reads from CNI and broadcasts to all clients"""
        buffer = bytearray()
        
        try:
            while self.running and self.cni_connected:
                # Read available data from CNI
                data = await self.cni_reader.read(1024)
                if not data:
                    logger.warning("CNI connection closed")
                    break
                
                # Add to buffer
                buffer.extend(data)
                
                # Process complete packets from buffer
                while buffer:
                    # Responses end with \r\n (except confirmations)
                    # Check for confirmation first (single char + status)
                    if len(buffer) >= 2 and buffer[0] in CONFIRMATION_CODES:
                        packet_data = bytes(buffer[:2])
                        buffer = buffer[2:]
                    else:
                        end_pos = buffer.find(END_RESPONSE)
                        if end_pos == -1:
                            # Also check for power-on packet
                            if buffer.startswith(b'+'):
                                packet_data = bytes(buffer[:1])
                                buffer = buffer[1:]
                            elif buffer.startswith(b'!'):
                                packet_data = bytes(buffer[:1])
                                buffer = buffer[1:]
                            else:
                                break
                        else:
                            packet_data = bytes(buffer[:end_pos + len(END_RESPONSE)])
                            buffer = buffer[end_pos + len(END_RESPONSE):]
                    
                    # Analyze and log the packet
                    analysis = self.analyzer.analyze_packet(packet_data, Direction.FROM_CNI)
                    print(analysis)
                    
                    # Broadcast to all connected clients
                    await self.broadcast_to_clients(packet_data)
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in CNI reader task: {e}")
        finally:
            self.cni_connected = False
            if self.cni_writer:
                self.cni_writer.close()
                await self.cni_writer.wait_closed()
    
    async def broadcast_to_clients(self, data: bytes):
        """Broadcast data to all connected clients"""
        disconnected_clients = []
        
        async with self.clients_lock:
            client_count = len(self.clients)
            if client_count > 0:
                logger.debug(f"Broadcasting to {client_count} client(s)")
            
            for client_id, client_info in self.clients.items():
                try:
                    client_info.writer.write(data)
                    await client_info.writer.drain()
                except Exception as e:
                    logger.error(f"Failed to send to {client_info}: {e}")
                    disconnected_clients.append(client_id)
        
        # Remove disconnected clients
        if disconnected_clients:
            async with self.clients_lock:
                for client_id in disconnected_clients:
                    if client_id in self.clients:
                        logger.info(f"{Fore.RED}Removing disconnected client: {self.clients[client_id]}{Style.RESET_ALL}")
                        del self.clients[client_id]
    
    async def handle_client(self, client_reader: StreamReader, 
                           client_writer: StreamWriter):
        """Handle incoming client connection"""
        client_addr = client_writer.get_extra_info('peername')
        client_id = f"{client_addr[0]}:{client_addr[1]}"
        client_info = ClientInfo(client_writer, client_id)
        
        logger.info(f"{Fore.GREEN}Client connected: {client_info}{Style.RESET_ALL}")
        
        # Register the client
        async with self.clients_lock:
            self.clients[client_id] = client_info
            logger.info(f"Active clients: {len(self.clients)}")
        
        try:
            # Check CNI connection
            if not self.cni_connected:
                logger.warning(f"Client {client_info} connected but CNI is not available")
                # Try to reconnect to CNI
                await self.connect_to_cni()
                if self.cni_connected and not self.cni_task:
                    self.cni_task = asyncio.create_task(self.cni_reader_task())
            
            # Forward data from this client to CNI
            await self.forward_client_to_cni(client_reader, client_info)
                
        except Exception as e:
            logger.error(f"Error handling client {client_info}: {e}")
            
        finally:
            # Unregister the client
            async with self.clients_lock:
                if client_id in self.clients:
                    del self.clients[client_id]
                    logger.info(f"{Fore.RED}Client disconnected: {client_info}{Style.RESET_ALL}")
                    logger.info(f"Active clients: {len(self.clients)}")
            
            client_writer.close()
            await client_writer.wait_closed()
    
    async def forward_client_to_cni(self, reader: StreamReader, client_info: ClientInfo):
        """Forward data from a client to the CNI"""
        buffer = bytearray()
        
        try:
            while self.running:
                # Read available data
                data = await reader.read(1024)
                if not data:
                    break
                
                # Add to buffer
                buffer.extend(data)
                
                # Process complete packets from buffer
                while buffer:
                    # Commands end with \r
                    end_pos = buffer.find(END_COMMAND)
                    if end_pos == -1:
                        break
                    packet_data = bytes(buffer[:end_pos + len(END_COMMAND)])
                    buffer = buffer[end_pos + len(END_COMMAND):]
                    
                    # Update client packet count
                    client_info.packet_count += 1
                    
                    # Analyze and log the packet
                    analysis = self.analyzer.analyze_packet(packet_data, Direction.FROM_CLIENT, client_info)
                    print(analysis)
                    
                    # Forward the packet to CNI
                    if self.cni_connected and self.cni_writer:
                        try:
                            self.cni_writer.write(packet_data)
                            await self.cni_writer.drain()
                        except Exception as e:
                            logger.error(f"Failed to send to CNI: {e}")
                            self.cni_connected = False
                    else:
                        logger.warning(f"Cannot forward packet from {client_info} - CNI not connected")
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error forwarding data from {client_info}: {e}")
    
    async def shutdown(self):
        """Gracefully shutdown the proxy"""
        logger.info("Shutting down proxy...")
        self.running = False
        
        # Cancel CNI reader task
        if self.cni_task:
            self.cni_task.cancel()
            try:
                await self.cni_task
            except asyncio.CancelledError:
                pass
        
        # Close CNI connection
        if self.cni_writer:
            self.cni_writer.close()
            await self.cni_writer.wait_closed()
        
        # Disconnect all clients
        async with self.clients_lock:
            for client_info in self.clients.values():
                try:
                    client_info.writer.close()
                    await client_info.writer.wait_closed()
                except:
                    pass
            self.clients.clear()
        
        # Print summary
        self.analyzer.print_summary()
        
        # Print client statistics
        logger.info(f"\n{Fore.CYAN}━━━ Client Statistics ━━━{Style.RESET_ALL}")
        logger.info(f"Total clients served: {len(self.clients)}")


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='C-Bus Protocol Analyzer and Proxy')
    parser.add_argument('--listen-host', default='0.0.0.0',
                       help='Host to listen on (default: 0.0.0.0)')
    parser.add_argument('--listen-port', type=int, default=10001,
                       help='Port to listen on (default: 10001)')
    parser.add_argument('--target-host', required=True,
                       help='Target CNI host/IP')
    parser.add_argument('--target-port', type=int, default=10001,
                       help='Target CNI port (default: 10001)')
    
    args = parser.parse_args()
    
    # Print banner
    print(f"{Fore.CYAN}╔══════════════════════════════════════╗{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║   C-Bus Protocol Analyzer & Proxy    ║{Style.RESET_ALL}")
    print(f"{Fore.CYAN}╚══════════════════════════════════════╝{Style.RESET_ALL}")
    print()
    print(f"{Fore.YELLOW}Multi-client mode enabled - accepting multiple connections{Style.RESET_ALL}")
    print()
    
    proxy = CBusProxy(
        args.listen_host, args.listen_port,
        args.target_host, args.target_port)
    
    try:
        await proxy.start()
    except KeyboardInterrupt:
        await proxy.shutdown()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Proxy stopped by user{Style.RESET_ALL}")
        sys.exit(0) 