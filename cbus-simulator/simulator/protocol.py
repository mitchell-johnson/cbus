#!/usr/bin/env python3
"""
C-Bus Simulator Protocol

This module implements the C-Bus PCI protocol for the simulator, handling
command parsing, processing, and response generation.
"""

import asyncio
import logging
import random
import re
import time
import binascii
from asyncio import StreamReader, StreamWriter
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union, Any

from simulator.state import SimulatorState

logger = logging.getLogger(__name__)

# C-Bus protocol constants
END_COMMAND = b'\r\n'
CONFIRMATION_CODES = list(range(0x80, 0xFF + 1))
BASIC_MODE_PROMPT = b'>'
SMART_MODE_NO_ECHO = '+'

# Command regex patterns
RESET_PATTERN = re.compile(r'^~~~$')
LIGHTING_ON_PATTERN = re.compile(r'^(#)?(\d+)//(\d+)A(\d+)N(\d+)$')
LIGHTING_OFF_PATTERN = re.compile(r'^(#)?(\d+)//(\d+)A(\d+)F(\d+)$')
LIGHTING_RAMP_PATTERN = re.compile(r'^(#)?(\d+)//(\d+)A(\d+)R(\d+)D(\d+)$')
STATUS_REQUEST_PATTERN = re.compile(r'^(#)?(\d+)//(\d+)A(\d+)G(\d+)$')
CLOCK_UPDATE_PATTERN = re.compile(r'^(#)?(\d+)//223A201T(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})W(\d)$')
IDENTIFY_PATTERN = re.compile(r'^(#)?(\d+)//(\d+)I(\d+)A(\d+)$')
MMI_REQUEST_PATTERN = re.compile(r'^(#)?(\d+)//(\d+)MMI(\d+)$')
BASIC_MODE_PATTERN = re.compile(r'^X$')
SMART_MODE_PATTERN = re.compile(r'^Y$')

def preprocess_cbus_data(data):
    """
    Preprocess C-Bus protocol data, handling escape sequences and special characters
    The C-Bus protocol often includes escape characters and backslashes that need to be handled
    """
    try:
        # If data is bytes and contains backslashes
        if isinstance(data, bytes) and b'\\' in data:
            # Data appears to be a string representation with backslashes
            # First log the raw data
            logger.info(f"Received string-encoded binary data: {data}")
            
            # Remove newlines and carriage returns
            cleaned = data.replace(b'\r', b'').replace(b'\n', b'')
            
            # Convert to string for easier processing
            try:
                hex_str = cleaned.decode('ascii')
            except UnicodeDecodeError:
                logger.error(f"Unable to decode data as ASCII: {cleaned}")
                return data
                
            # Log for debugging
            logger.info(f"Cleaned string: {hex_str}")
            
            # C-Bus protocol format: each byte is represented as \XX where XX is a hex value
            # Example: \05\DF\00\0E\02...
            
            result_bytes = bytearray()
            
            # Special case for strings that don't have a backslash before each byte
            # The format seems to be \05XXXXXXXXh where XXXXXXXX are hex digits
            if hex_str.startswith('\\05'):
                # Extract the initial byte
                result_bytes.append(0x05)
                
                # Check if this is a lighting command format: '\05FF00730738004Ai'
                if len(hex_str) >= 5 and hex_str[3:5] == 'FF' and hex_str.endswith('i'):
                    # Extract the command type byte (FF)
                    result_bytes.append(0xFF)
                    
                    # Process the rest of the string in pairs until the 'i'
                    rest = hex_str[5:-1]  # Skip '\05FF' and the trailing 'i'
                    for i in range(0, len(rest), 2):
                        if i + 1 < len(rest):
                            try:
                                byte_val = int(rest[i:i+2], 16)
                                result_bytes.append(byte_val)
                            except ValueError:
                                # Skip invalid hex
                                pass
                    
                    hex_display = " ".join(f"{b:02X}" for b in result_bytes)
                    logger.info(f"Parsed lighting command: {hex_display}")
                    return result_bytes
                
                # Check if this is an initialization command format: '\05DF000E0207E90415000D010F3720FF90h'
                elif len(hex_str) >= 5 and hex_str[3:5] == 'DF' and ('h' in hex_str):
                    # Extract the command type byte (DF)
                    result_bytes.append(0xDF)
                    
                    # Process the rest of the string in pairs until the 'h'
                    rest = hex_str[5:hex_str.find('h')]
                    for i in range(0, len(rest), 2):
                        if i + 1 < len(rest):
                            try:
                                byte_val = int(rest[i:i+2], 16)
                                result_bytes.append(byte_val)
                            except ValueError:
                                # Skip invalid hex
                                pass
                    
                    hex_display = " ".join(f"{b:02X}" for b in result_bytes)
                    logger.info(f"Parsed initialization command: {hex_display}")
                    return result_bytes
                
                # Generic parsing for any other command type
                elif len(hex_str) >= 5:
                    try:
                        # Try to extract the command type
                        cmd_byte = int(hex_str[3:5], 16)
                        result_bytes.append(cmd_byte)
                        
                        # Determine the endpoint
                        end_idx = len(hex_str)
                        if 'h' in hex_str:
                            end_idx = hex_str.find('h')
                        elif hex_str[-1].isalpha():  # Ends with a letter like 'i', 'j', etc.
                            end_idx = len(hex_str) - 1
                        
                        # Process the rest of the string in pairs
                        rest = hex_str[5:end_idx]
                        for i in range(0, len(rest), 2):
                            if i + 1 < len(rest):
                                try:
                                    byte_val = int(rest[i:i+2], 16)
                                    result_bytes.append(byte_val)
                                except ValueError:
                                    # Skip invalid hex
                                    pass
                    except ValueError:
                        # Failed to parse command byte
                        logger.warning(f"Failed to parse command byte: {hex_str[3:5]}")
                
                # Check if we have a valid result
                if len(result_bytes) > 1:
                    hex_display = " ".join(f"{b:02X}" for b in result_bytes)
                    logger.info(f"Parsed C-Bus message: {hex_display}")
                    return result_bytes
            
            # Handle format where each byte starts with a backslash
            result_bytes = bytearray()  # Reset result_bytes
            i = 0
            while i < len(hex_str):
                if hex_str[i] == '\\' and i + 2 < len(hex_str):
                    # Extract the two hex characters after the backslash
                    hex_chars = hex_str[i+1:i+3]
                    try:
                        # Convert hex to byte value
                        byte_val = int(hex_chars, 16)
                        result_bytes.append(byte_val)
                        i += 3  # Move past this hex sequence
                    except ValueError:
                        logger.warning(f"Invalid hex value at position {i}: {hex_chars}")
                        i += 1  # Skip just the backslash
                else:
                    # Skip any non-backslash characters
                    i += 1
            
            # Log and return the result
            if result_bytes:
                hex_display = " ".join(f"{b:02X}" for b in result_bytes)
                logger.info(f"Parsed using backslash method: {hex_display}")
                return result_bytes
            
            logger.warning("Failed to extract valid binary data")
            return data
        
        # Already binary data
        return data
    
    except Exception as e:
        logger.error(f"Error preprocessing data: {e}", exc_info=True)
        # Return original data if there's an error
        return data

class PCISimulatorProtocol:
    """
    Implements the C-Bus PCI protocol for the simulator.
    """
    
    def __init__(self, reader: StreamReader, writer: StreamWriter, state: SimulatorState):
        """
        Initialize the protocol handler.
        
        Args:
            reader: Stream reader for client data
            writer: Stream writer for sending data to client
            state: Simulator state manager
        """
        self.reader = reader
        self.writer = writer
        self.state = state
        self.buffer = bytearray()
        self.addr = writer.get_extra_info('peername')
        self.smart_mode = self.state.smart_mode
        self.source_address = self.state.simulation_settings["default_source_address"]
        self.confirmation_index = 0
        
        # Track command processing for simulation
        self.last_command_time = time.time()
        self.client_id = f"{self.addr[0]}:{self.addr[1]}"
        
        logger.info(f"Protocol handler initialized for client {self.client_id}")
    
    async def process_client(self) -> None:
        """
        Process client communication, reading commands and sending responses.
        """
        # Send initial prompt
        await self._send_prompt()
        
        while True:
            try:
                # Read data from client
                data = await self.reader.read(1024)
                if not data:
                    # Connection closed
                    break
                
                # Add data to buffer
                self.buffer.extend(data)
                
                # Process commands in buffer
                await self._process_buffer()
            except asyncio.CancelledError:
                # Task cancelled
                break
            except Exception as e:
                logger.error(f"Error processing client data: {e}")
                break
    
    async def _process_buffer(self) -> None:
        """
        Process commands in the buffer.
        """
        while END_COMMAND in self.buffer or b'\r' in self.buffer:
            # Find command end (support both \r\n and just \r)
            if END_COMMAND in self.buffer:
                cmd_end = self.buffer.find(END_COMMAND)
                end_len = len(END_COMMAND)
            else:
                cmd_end = self.buffer.find(b'\r')
                end_len = 1
            
            # Extract command bytes
            cmd_bytes = self.buffer[:cmd_end]
            
            # Remove command from buffer
            self.buffer = self.buffer[cmd_end + end_len:]
            
            # Skip empty commands
            if not cmd_bytes:
                continue
            
            # Preprocess binary commands
            if cmd_bytes.startswith(b'\\'):
                # This is likely a binary command in string format
                processed_data = preprocess_cbus_data(cmd_bytes)
                
                # Process as binary data
                response = await self._handle_binary_command(processed_data)
                await self._write(response)
                continue
            
            # Try to decode as text command
            try:
                cmd = cmd_bytes.decode('ascii', errors='ignore').strip()
                
                # Log the command
                self.state.log_command(cmd, self.client_id)
                logger.debug(f"Received command: {cmd}")
                
                # Process command with simulated delay
                await self._simulate_delay()
                
                # Echo command in basic mode
                if not self.smart_mode:
                    await self._write(cmd.encode('ascii') + END_COMMAND)
                
                # Process the command
                await self._process_command(cmd)
            except UnicodeDecodeError:
                # If it's not a text command, try to process as binary
                response = await self._handle_binary_command(cmd_bytes)
                await self._write(response)
    
    async def _handle_binary_command(self, data: bytearray) -> bytes:
        """
        Handle binary C-Bus commands.
        
        Args:
            data: The binary command data
            
        Returns:
            The response data
        """
        try:
            # For readability, convert binary data to hex string
            hex_data = " ".join(f"{b:02X}" for b in data)
            logger.info(f"Processing binary data: {hex_data}")
            
            # Look for common C-Bus command patterns
            if len(data) > 0:
                # Standard C-Bus message prefix (0x05)
                if data[0] == 0x05:
                    # Parse command type (second byte)
                    cmd_type = data[1] if len(data) > 1 else 0x00
                    
                    logger.info(f"Command type: 0x{cmd_type:02X}")
                    
                    if cmd_type == 0xDF:  # Initialization message
                        logger.info("Received initialization message")
                        # Respond with ACK for initialization
                        return b"\x05\x86\x00\x02\x00\x00\x00\x00\x00"
                        
                    elif cmd_type == 0xFF:  # Standard command
                        # Try to extract group address if present
                        if len(data) >= 6:
                            # Extract data from bytes which might contain group info
                            application = data[3] if len(data) > 3 else 0
                            group_addr = data[5] if len(data) > 5 else 0
                            logger.info(f"Command for application: {application}, group: {group_addr}")
                            
                            # Update state if this is a lighting command
                            if application == 56:  # Lighting application
                                # Check the command type (usually at index 4)
                                if len(data) > 6:
                                    command_type = data[4]
                                    level = data[6]
                                    
                                    # Update the group level
                                    network_id = 254  # Default network
                                    if command_type == 0x38:  # ON command
                                        self.state.set_group_level(network_id, application, group_addr, level)
                                        logger.info(f"Set group {group_addr} to level {level}")
                        
                        # Generate confirmation code (the confirmation char at the end of message)
                        confirmation = data[-1:] if len(data) > 0 else b'\x00'
                        if isinstance(confirmation, (bytes, bytearray)) and len(confirmation) > 0:
                            logger.info(f"Confirmation code: 0x{confirmation[0]:02X}")
                        
                        # Return positive response with the same confirmation code
                        return b"\x05\x86\x00\x01\x00\x00\x00\x01" + confirmation
                    
                    else:
                        logger.info(f"Unknown command type: 0x{cmd_type:02X}")
                        # Generic response
                        return b"\x05\x86\x00\x01\x00\x00\x00\x00\x00"
                else:
                    logger.warning(f"Not a valid C-Bus message format (invalid prefix): {hex_data}")
                    return b"\x05\x86\xFF\xFF\x00\x00\x00\x00\x00"  # Error response
            else:
                logger.warning(f"Invalid data (empty)")
                return b"\x05\x86\xFF\xFF\x00\x00\x00\x00\x00"  # Error response
        
        except Exception as e:
            logger.error(f"Error processing binary command: {e}", exc_info=True)
            return b"\x05\x86\x00\x01\x00\x00\x00\x00\xFF"  # Error response
    
    async def _simulate_delay(self) -> None:
        """
        Simulate network delay and processing time.
        """
        delay_min = self.state.simulation_settings["delay_min_ms"] / 1000.0
        delay_max = self.state.simulation_settings["delay_max_ms"] / 1000.0
        delay = random.uniform(delay_min, delay_max)
        
        # Simulate packet loss
        loss_prob = self.state.simulation_settings["packet_loss_probability"]
        if random.random() < loss_prob:
            logger.debug(f"Simulating packet loss (probability: {loss_prob})")
            await asyncio.sleep(delay * 2)
            return
        
        await asyncio.sleep(delay)
    
    async def _process_command(self, cmd: str) -> None:
        """
        Process a C-Bus command.
        
        Args:
            cmd: The command string
        """
        # Reset command
        if RESET_PATTERN.match(cmd):
            await self._handle_reset()
            return
        
        # Basic mode command
        if BASIC_MODE_PATTERN.match(cmd):
            await self._handle_basic_mode()
            return
        
        # Smart mode command
        if SMART_MODE_PATTERN.match(cmd):
            await self._handle_smart_mode()
            return
        
        # Lighting on command
        lighting_on_match = LIGHTING_ON_PATTERN.match(cmd)
        if lighting_on_match:
            await self._handle_lighting_on(lighting_on_match)
            return
        
        # Lighting off command
        lighting_off_match = LIGHTING_OFF_PATTERN.match(cmd)
        if lighting_off_match:
            await self._handle_lighting_off(lighting_off_match)
            return
        
        # Lighting ramp command
        lighting_ramp_match = LIGHTING_RAMP_PATTERN.match(cmd)
        if lighting_ramp_match:
            await self._handle_lighting_ramp(lighting_ramp_match)
            return
        
        # Status request command
        status_request_match = STATUS_REQUEST_PATTERN.match(cmd)
        if status_request_match:
            await self._handle_status_request(status_request_match)
            return
        
        # Clock update command
        clock_update_match = CLOCK_UPDATE_PATTERN.match(cmd)
        if clock_update_match:
            await self._handle_clock_update(clock_update_match)
            return
        
        # Identify command
        identify_match = IDENTIFY_PATTERN.match(cmd)
        if identify_match:
            await self._handle_identify(identify_match)
            return
        
        # MMI request command
        mmi_match = MMI_REQUEST_PATTERN.match(cmd)
        if mmi_match:
            await self._handle_mmi_request(mmi_match)
            return
        
        # Unknown command
        logger.warning(f"Unknown command: {cmd}")
        await self._send_error("Unknown command", cmd)
    
    async def _handle_reset(self) -> None:
        """
        Handle C-Bus reset command.
        """
        logger.info("Handling reset command")
        self.state.reset()
        await self._write(b"OK\r\n")
        await self._send_prompt()
    
    async def _handle_basic_mode(self) -> None:
        """
        Handle switch to basic mode command.
        """
        logger.info("Switching to basic mode")
        self.smart_mode = False
        await self._write(b"OK\r\n")
        await self._send_prompt()
    
    async def _handle_smart_mode(self) -> None:
        """
        Handle switch to smart mode command.
        """
        logger.info("Switching to smart mode")
        self.smart_mode = True
        await self._write(b"OK\r\n")
        await self._send_prompt()
    
    async def _handle_lighting_on(self, match) -> None:
        """
        Handle lighting on command.
        
        Args:
            match: The regex match object
        """
        confirm_flag = match.group(1) == "#"
        source_addr = int(match.group(2))
        network_id = int(match.group(3))
        application_id = int(match.group(4))
        group_id = int(match.group(5))
        
        logger.info(f"Lighting ON: network={network_id}, app={application_id}, group={group_id}, source={source_addr}")
        
        # Update the state
        success = self.state.set_group_level(network_id, application_id, group_id, 255)
        
        # Send confirmation if requested
        if confirm_flag:
            confirmation_code = self._get_confirmation_code()
            await self._send_confirmation(confirmation_code, success)
        
        # Broadcast the event to simulate actual C-Bus behavior
        await self._broadcast_lighting_event(network_id, application_id, group_id, "on", source_addr)
    
    async def _handle_lighting_off(self, match) -> None:
        """
        Handle lighting off command.
        
        Args:
            match: The regex match object
        """
        confirm_flag = match.group(1) == "#"
        source_addr = int(match.group(2))
        network_id = int(match.group(3))
        application_id = int(match.group(4))
        group_id = int(match.group(5))
        
        logger.info(f"Lighting OFF: network={network_id}, app={application_id}, group={group_id}, source={source_addr}")
        
        # Update the state
        success = self.state.set_group_level(network_id, application_id, group_id, 0)
        
        # Send confirmation if requested
        if confirm_flag:
            confirmation_code = self._get_confirmation_code()
            await self._send_confirmation(confirmation_code, success)
        
        # Broadcast the event to simulate actual C-Bus behavior
        await self._broadcast_lighting_event(network_id, application_id, group_id, "off", source_addr)
    
    async def _handle_lighting_ramp(self, match) -> None:
        """
        Handle lighting ramp command.
        
        Args:
            match: The regex match object
        """
        confirm_flag = match.group(1) == "#"
        source_addr = int(match.group(2))
        network_id = int(match.group(3))
        application_id = int(match.group(4))
        group_id = int(match.group(5))
        duration = int(match.group(6))  # in seconds
        
        # For simplicity, we'll set the level to 50% in a ramp command
        # A real implementation would parse the level from the command
        level = 128
        
        logger.info(f"Lighting RAMP: network={network_id}, app={application_id}, group={group_id}, duration={duration}, level={level}, source={source_addr}")
        
        # Update the state
        success = self.state.set_group_level(network_id, application_id, group_id, level)
        
        # Send confirmation if requested
        if confirm_flag:
            confirmation_code = self._get_confirmation_code()
            await self._send_confirmation(confirmation_code, success)
        
        # Broadcast the event to simulate actual C-Bus behavior
        await self._broadcast_lighting_event(network_id, application_id, group_id, f"ramp:{level}", source_addr)
    
    async def _handle_status_request(self, match) -> None:
        """
        Handle status request command.
        
        Args:
            match: The regex match object
        """
        confirm_flag = match.group(1) == "#"
        source_addr = int(match.group(2))
        network_id = int(match.group(3))
        application_id = int(match.group(4))
        group_id = int(match.group(5))
        
        logger.info(f"Status request: network={network_id}, app={application_id}, group={group_id}, source={source_addr}")
        
        # Get the group level
        level = self.state.get_group_level(network_id, application_id, group_id)
        
        # Send confirmation if requested
        if confirm_flag:
            confirmation_code = self._get_confirmation_code()
            await self._send_confirmation(confirmation_code, True)
        
        # Send status response
        await self._send_status_response(network_id, application_id, group_id, level)
    
    async def _handle_clock_update(self, match) -> None:
        """
        Handle clock update command.
        
        Args:
            match: The regex match object
        """
        confirm_flag = match.group(1) == "#"
        source_addr = int(match.group(2))
        hours = int(match.group(3))
        minutes = int(match.group(4))
        seconds = int(match.group(5))
        day = int(match.group(6))
        month = int(match.group(7))
        year = int(match.group(8)) + 2000  # Assuming 2-digit year
        day_of_week = int(match.group(9))
        
        logger.info(f"Clock update: {year:04d}-{month:02d}-{day:02d} {hours:02d}:{minutes:02d}:{seconds:02d}, weekday={day_of_week}, source={source_addr}")
        
        # Send confirmation if requested
        if confirm_flag:
            confirmation_code = self._get_confirmation_code()
            await self._send_confirmation(confirmation_code, True)
    
    async def _handle_identify(self, match) -> None:
        """
        Handle identify command.
        
        Args:
            match: The regex match object
        """
        confirm_flag = match.group(1) == "#"
        source_addr = int(match.group(2))
        network_id = int(match.group(3))
        unit_address = int(match.group(4))
        attribute = int(match.group(5))
        
        logger.info(f"Identify: network={network_id}, unit={unit_address}, attribute={attribute}, source={source_addr}")
        
        # Send confirmation if requested
        if confirm_flag:
            confirmation_code = self._get_confirmation_code()
            await self._send_confirmation(confirmation_code, True)
        
        # Send identify response based on attribute
        await self._send_identify_response(network_id, unit_address, attribute)
    
    async def _handle_mmi_request(self, match) -> None:
        """
        Handle MMI request command.
        
        Args:
            match: The regex match object
        """
        confirm_flag = match.group(1) == "#"
        source_addr = int(match.group(2))
        network_id = int(match.group(3))
        application_id = int(match.group(4))
        
        logger.info(f"MMI request: network={network_id}, app={application_id}, source={source_addr}")
        
        # Send confirmation if requested
        if confirm_flag:
            confirmation_code = self._get_confirmation_code()
            await self._send_confirmation(confirmation_code, True)
    
    async def _broadcast_lighting_event(self, network_id: int, application_id: int, group_id: int, 
                                        event_type: str, source_addr: int) -> None:
        """
        Broadcast a lighting event to simulate C-Bus network behavior.
        
        Args:
            network_id: The network ID
            application_id: The application ID
            group_id: The group ID
            event_type: The type of event (on, off, ramp)
            source_addr: The source address
        """
        if event_type == "on":
            response = f"{source_addr}//{network_id}A{application_id}N{group_id}\r\n"
        elif event_type == "off":
            response = f"{source_addr}//{network_id}A{application_id}F{group_id}\r\n"
        elif event_type.startswith("ramp:"):
            level = event_type.split(":")[1]
            # In a real implementation, this would include the ramp duration
            response = f"{source_addr}//{network_id}A{application_id}R{group_id}L{level}\r\n"
        else:
            return
        
        await self._write(response.encode('ascii'))
    
    async def _send_status_response(self, network_id: int, application_id: int, group_id: int, level: int) -> None:
        """
        Send a status response for a lighting group.
        
        Args:
            network_id: The network ID
            application_id: The application ID
            group_id: The group ID
            level: The current level (0-255)
        """
        # Format depends on the level
        if level == 0:
            response = f"{self.source_address}//{network_id}A{application_id}F{group_id}\r\n"
        elif level == 255:
            response = f"{self.source_address}//{network_id}A{application_id}N{group_id}\r\n"
        else:
            response = f"{self.source_address}//{network_id}A{application_id}L{group_id}={level}\r\n"
        
        await self._write(response.encode('ascii'))
    
    async def _send_identify_response(self, network_id: int, unit_address: int, attribute: int) -> None:
        """
        Send an identify response.
        
        Args:
            network_id: The network ID
            unit_address: The unit address
            attribute: The attribute being requested
        """
        # Respond based on the attribute
        # 0 = Interface type
        # 1 = Version information
        # 2 = Network variable
        if attribute == 0:
            # Interface type (5500CN)
            response = f"{self.source_address}//{network_id}IC{unit_address}A{attribute}=\"5500CN\"\r\n"
        elif attribute == 1:
            # Version information
            version = self.state.device_info["firmware_version"]
            response = f"{self.source_address}//{network_id}IC{unit_address}A{attribute}=\"{version}\"\r\n"
        elif attribute == 2:
            # Network variable
            name = self.state.networks.get(network_id, {}).get("name", "Default Network")
            response = f"{self.source_address}//{network_id}IC{unit_address}A{attribute}=\"{name}\"\r\n"
        else:
            # Unknown attribute
            response = f"{self.source_address}//{network_id}IC{unit_address}A{attribute}=\"Unknown\"\r\n"
        
        await self._write(response.encode('ascii'))
    
    async def _send_confirmation(self, code: int, success: bool) -> None:
        """
        Send a command confirmation.
        
        Args:
            code: The confirmation code
            success: True if the command was successful, False otherwise
        """
        if success:
            response = f".\r\n{hex(code)[2:].upper()}{SMART_MODE_NO_ECHO}\r\n"
        else:
            response = f"!\r\n{hex(code)[2:].upper()}{SMART_MODE_NO_ECHO}\r\n"
        
        await self._write(response.encode('ascii'))
    
    async def _send_error(self, error_type: str, cmd: str) -> None:
        """
        Send an error response.
        
        Args:
            error_type: The type of error
            cmd: The command that caused the error
        """
        # Increment error count
        self.state.pci_status["error_count"] += 1
        
        # Send error response
        await self._write(f"!{error_type}: {cmd}\r\n".encode('ascii'))
        await self._send_prompt()
    
    async def _send_prompt(self) -> None:
        """
        Send the appropriate command prompt based on the current mode.
        """
        if self.smart_mode:
            await self._write(SMART_MODE_NO_ECHO.encode('ascii') + END_COMMAND)
        else:
            await self._write(BASIC_MODE_PROMPT)
    
    async def _write(self, data: bytes) -> None:
        """
        Write data to the client.
        
        Args:
            data: The data to write
        """
        self.writer.write(data)
        await self.writer.drain()
    
    def _get_confirmation_code(self) -> int:
        """
        Get a unique confirmation code.
        
        Returns:
            A confirmation code (0x80-0xFF)
        """
        code = CONFIRMATION_CODES[self.confirmation_index]
        self.confirmation_index = (self.confirmation_index + 1) % len(CONFIRMATION_CODES)
        return code 