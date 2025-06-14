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
# C-Bus confirmation codes are a specific set of ASCII characters
# These are used as transaction identifiers for command confirmation
# When a client sends a command with a confirmation code, the server must respond
# with the same code followed by a success/failure indicator
CONFIRMATION_CODES = b'hijklmnopqrstuvwxyzg'
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

# ----------------------
# Helper functions for C-Bus string-encoded binary parsing
# ----------------------

def _clean_ascii_bytes(data: bytes) -> str:
    """Return ASCII string without CR/LF; fallback to empty string on decode error."""
    try:
        return data.replace(b"\r", b"").replace(b"\n", b"").decode("ascii")
    except UnicodeDecodeError:
        logger.error("Unable to decode data as ASCII: %s", data)
        return ""


def _parse_backslash_pairs(hex_str: str) -> Optional[bytearray]:
    """Parse strings where every byte is encoded as \XX (backslash + two hex digits)."""
    result = bytearray()
    i = 0
    while i < len(hex_str):
        if hex_str[i] == "\\" and i + 2 < len(hex_str):
            try:
                result.append(int(hex_str[i + 1 : i + 3], 16))
                i += 3
                continue
            except ValueError:
                logger.debug("Invalid hex at pos %s -> %s", i, hex_str[i + 1 : i + 3])
        i += 1
    return result if result else None


def _parse_slash05_format(hex_str: str) -> Optional[bytearray]:
    """Handle legacy C-Bus encoding starting with '\\05'. Detects command types, etc."""
    if not hex_str.startswith("\\05"):
        return None

    def _hex_pairs(sub: str) -> List[int]:
        out: List[int] = []
        for i in range(0, len(sub), 2):
            if i + 1 < len(sub):
                try:
                    out.append(int(sub[i : i + 2], 16))
                except ValueError:
                    logger.debug("Skipping invalid hex %s", sub[i : i + 2])
        return out

    result = bytearray([0x05])

    # Determine command byte & terminator letter
    if len(hex_str) < 5:
        return None

    cmd_byte_part = hex_str[3:5]
    try:
        cmd_byte = int(cmd_byte_part, 16)
    except ValueError:
        logger.debug("Invalid cmd byte %s", cmd_byte_part)
        return None

    result.append(cmd_byte)

    # Find trailing terminator letter (common cases h/i/j/x/t etc.)
    end_idx = len(hex_str)
    # If last char is a lowercase letter, treat as terminator
    if hex_str[-1].isalpha():
        end_idx = len(hex_str) - 1
    else:
        # Fallback: look for first 'h' which is common
        if "h" in hex_str:
            end_idx = hex_str.find("h")

    payload = hex_str[5:end_idx]
    result.extend(_hex_pairs(payload))

    return result if len(result) > 2 else None


def _parse_hex_pairs_no_backslash(hex_str: str) -> Optional[bytearray]:
    """Fallback extractor: grab any hex pairs inside a malformed string."""
    result = bytearray([0x05])
    start = 1 if hex_str.startswith("\\") else 0
    for i in range(start, len(hex_str) - 1, 2):
        pair = hex_str[i : i + 2]
        if all(ch.isalnum() for ch in pair):
            try:
                result.append(int(pair, 16))
            except ValueError:
                pass
    return result if len(result) > 1 else None


def preprocess_cbus_data(data):
    """High-level wrapper that delegates to specialised converters.

    Keeps the original public signature while improving readability.
    """
    try:
        # Short-circuit for data that is already binary or lacks backslashes
        if not (isinstance(data, bytes) and b"\\" in data):
            return data

        logger.info("Received string-encoded binary data: %s", data)

        hex_str = _clean_ascii_bytes(data)
        if not hex_str:
            return data

        logger.info("Cleaned string: %s", hex_str)

        # 1. Special legacy format starting with \05
        result = _parse_slash05_format(hex_str)
        if result:
            logger.info("Parsed via _parse_slash05_format: %s", " ".join(f"{b:02X}" for b in result))
            return result

        # 2. Regular backslash-pairs format (\XX)
        result = _parse_backslash_pairs(hex_str)
        if result and len(result) > 2:
            logger.info("Parsed via _parse_backslash_pairs: %s", " ".join(f"{b:02X}" for b in result))
            return result

        # 3. Fallback extractor for malformed input
        result = _parse_hex_pairs_no_backslash(hex_str)
        if result:
            logger.info("Parsed via _parse_hex_pairs_no_backslash: %s", " ".join(f"{b:02X}" for b in result))
            return result

        logger.warning("Failed to parse C-Bus message; returning raw data")
        return data

    except Exception as exc:
        logger.error("Error preprocessing data: %s", exc, exc_info=True)
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
            # Initial preprocessing for ASCII-encoded binary commands
            if isinstance(data, bytes) or isinstance(data, bytearray):
                # Handle ASCII representation of a binary command
                try:
                    # Convert to ASCII string for inspection
                    ascii_str = None
                    try:
                        ascii_str = data.decode('ascii', errors='ignore')
                    except Exception:
                        pass
                    
                    # Check if this looks like a string-encoded C-Bus message (like '\053800790248x')
                    if ascii_str and '\\05' in ascii_str:
                        logger.debug(f"Detected string-encoded C-Bus message: {ascii_str}")
                        
                        # If we somehow reached here without prior preprocessing, attempt it now
                        pre = preprocess_cbus_data(data)
                        if isinstance(pre, (bytes, bytearray)) and pre and pre[0] == 0x05:
                            data = pre  # Switch to parsed binary form for the rest of this handler
                        else:
                            logger.debug("Inline preprocessing failed or returned unparsed data")
                        
                        # Extract the command type right after the \05 prefix
                        cmd_type_pos = ascii_str.find('\\05') + 3
                        if len(ascii_str) >= cmd_type_pos + 2:
                            try:
                                # Try to convert next two chars to a hex value
                                hex_cmd = ascii_str[cmd_type_pos:cmd_type_pos+2]
                                cmd_type = int(hex_cmd, 16)
                                logger.debug(f"Extracted command type from string: 0x{cmd_type:02X}")
                                
                                # Special case - directly handle lighting commands (0x38)
                                if cmd_type == 0x38 or cmd_type == 0xFF:
                                    # For 0xFF we still need to inspect further bytes to know application and group; fall back to heuristic
                                    logger.info(f"Detected lighting command 0x{cmd_type:02X} in string-encoded message")
                                    
                                    # Try to extract group address from the message if possible
                                    group_addr = 1  # Default
                                    if len(ascii_str) >= cmd_type_pos + 6:  # Need at least 4 more chars for group
                                        try:
                                            group_hex = ascii_str[cmd_type_pos+4:cmd_type_pos+6]
                                            group_addr = int(group_hex, 16)
                                        except ValueError:
                                            pass
                                    
                                    # Update the group state
                                    network_id = 254
                                    application = 56  # Lighting
                                    # Try to extract level from the message if possible
                                    level = 255  # Default to full on
                                    if len(ascii_str) >= cmd_type_pos + 8:  # Need at least 2 more chars for level
                                        try:
                                            level_hex = ascii_str[cmd_type_pos+6:cmd_type_pos+8]
                                            level = int(level_hex, 16)
                                        except ValueError:
                                            pass
                                    
                                    self.state.set_group_level(network_id, application, group_addr, level)
                                    logger.info(f"Setting group {group_addr} to ON from string-encoded message to Level = {level}")
                                    
                                    # Check if there's a confirmation request in the message
                                    # In C-Bus protocol, confirmation is requested by appending a character from
                                    # a specific set (hijklmnopqrstuvwxyzg) to the end of a command.
                                    # This character serves as a transaction identifier that the server
                                    # must echo back in its response, along with a success/failure indicator.
                                    needs_confirmation = False
                                    confirmation_code = None
                                    
                                    # Check the last byte of the command (if it exists)
                                    if len(data) > 0:
                                        last_byte = data[-1]
                                        # Convert to ASCII character for checking
                                        last_char = bytes([last_byte])
                                        # Check if it's a valid confirmation code
                                        if last_char in CONFIRMATION_CODES:
                                            needs_confirmation = True
                                            confirmation_code = last_byte
                                            logger.info(f"Detected confirmation request with code: {chr(confirmation_code)} (0x{confirmation_code:02X})")
                                    
                                    if needs_confirmation and confirmation_code is not None:
                                        logger.info(f"Sending confirmation with code: {chr(confirmation_code)} (0x{confirmation_code:02X})")
                                        
                                        # Format confirmation response according to CBus protocol:
                                        # The proper format is: [confirmation_code_byte][success_indicator][CR][LF]
                                        # Where:
                                        # - confirmation_code_byte is the same byte from the request (0x80-0xFF)
                                        # - success_indicator is '.' for success, '!' for failure
                                        # - CR+LF is the standard C-Bus command terminator
                                        success_indicator = b'.'  # success
                                        confirmation_response = bytes([confirmation_code]) + success_indicator + END_COMMAND
                                        await self._write(confirmation_response)
                                        
                                        # Then send prompt
                                        if self.smart_mode:
                                            await self._write(SMART_MODE_NO_ECHO.encode('ascii') + END_COMMAND)
                                        else:
                                            await self._write(BASIC_MODE_PROMPT)
                                        
                                        # Return empty since we've already written the response
                                        return b""
                                    else:
                                        # Return standard response for non-confirmation requests
                                        return b"\x05\x86\x00\x01\x00\x00\x00\x01\x00"
                            except ValueError:
                                logger.debug(f"Could not extract command type from {ascii_str}")
                except Exception as e:
                    logger.debug(f"Error during string preprocessing: {e}")
            
            # For readability, convert binary data to hex string
            hex_data = " ".join(f"{b:02X}" for b in data)
            logger.info(f"Processing binary data: {hex_data}")
            
            # Initialize cmd_type to a default value
            cmd_type = 0x00
            
            # Look for common C-Bus command patterns
            if len(data) > 0:
                # Standard C-Bus message prefix (0x05) - but be more forgiving
                # We'll consider any data that's been preprocessed as valid
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
                
                # Handle command type 0x38 directly (often appears in some malformed messages)
                elif cmd_type == 0x38:
                    logger.info("Handling direct command type 0x38 (lighting command)")
                    # Try to extract relevant information
                    # Typical format might be: 05 38 00 79 02 ...
                    network_id = 254  # Default network
                    application = 56   # Default to lighting app
                    
                    # Extract what we can from the available data
                    group_addr = data[4] if len(data) > 4 else 1
                    level = 255  # Default to ON
                    
                    # Update the group level
                    self.state.set_group_level(network_id, application, group_addr, level)
                    logger.info(f"Set group {group_addr} to level {level} (from direct 0x38 command)")
                    
                    # Return a standard response
                    return b"\x05\x86\x00\x01\x00\x00\x00\x01\x00"
                
                else:
                    # Only log if cmd_type is not None
                    logger.info(f"Unknown command type: 0x{cmd_type:02X}")
                    # Generate a valid response even for unknown command types
                    return b"\x05\x86\x00\x01\x00\x00\x00\x00\x00"
            
            # If message doesn't start with 0x05 but contains 0x38, try to handle it as a lighting command
            elif 0x38 in data:
                idx = data.index(0x38)
                logger.info(f"Found lighting command pattern at index {idx}")
                
                # Try to extract group info (assuming typical format)
                group_addr = data[idx+2] if len(data) > idx+2 else 1
                
                # Update state with best guess
                network_id = 254
                application = 56  # Lighting
                level = 255  # ON
                
                self.state.set_group_level(network_id, application, group_addr, level)
                logger.info(f"Set group {group_addr} to ON (best guess from non-standard format)")
                
                # Return a generic positive response
                return b"\x05\x86\x00\x01\x00\x00\x00\x00\x00"
            else:
                # If it doesn't start with 0x05, this would normally be an error
                # But to be more forgiving, return a generic response
                logger.warning(f"Received non-standard message format (no 0x05 prefix): {hex_data}")
                return b"\x05\x86\x00\x01\x00\x00\x00\x00\x00"
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
        Send a command confirmation according to the C-Bus protocol specification.
        
        The C-Bus confirmation protocol works as follows:
        1. When a client sends a command requiring confirmation, it includes a
           confirmation code (one of the characters in 'hijklmnopqrstuvwxyzg') as the 
           last byte of the command.
        2. The server must respond with a confirmation message containing:
           - The exact same confirmation code character
           - A success/failure indicator: '.' for success, '!' for failure
           - Followed by the standard command terminator (CR+LF)
        
        This is implemented in the CBus library as a ConfirmationPacket, which is a
        type of SpecialServerPacket. The encoded format is: [confirmation_code][indicator]
        
        Args:
            code: The ASCII value of the confirmation code character from the original request
            success: True if the command was successful, False otherwise
        """
        # Format confirmation response according to CBus protocol:
        # confirmation code byte followed by success/failure indicator
        # '.' for success, '!' for failure
        success_indicator = b'.' if success else b'!'
        confirmation_response = bytes([code]) + success_indicator + END_COMMAND
        
        await self._write(confirmation_response)
        await self._send_prompt()
    
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
        Get a unique confirmation code for command acknowledgments.
        
        In the C-Bus protocol, confirmation codes are specific ASCII characters
        from the set 'hijklmnopqrstuvwxyzg' that serve as transaction identifiers 
        for commands. When a client wants to confirm that a command was received 
        and processed, it appends a confirmation code to the command.
        The server must echo back this exact same code in its response.
        
        This method cycles through the valid confirmation codes sequentially, ensuring
        each command gets a unique identifier. In a real implementation, you might want 
        to track which codes are in use and reuse them only when responses have been 
        received, similar to how the PCIProtocol._get_confirmation_code method works
        in the client library.
        
        Returns:
            The ASCII integer value of a confirmation code character
        """
        code_char = CONFIRMATION_CODES[self.confirmation_index]
        self.confirmation_index = (self.confirmation_index + 1) % len(CONFIRMATION_CODES)
        return code_char 