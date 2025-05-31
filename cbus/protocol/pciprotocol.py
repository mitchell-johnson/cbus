#!/usr/bin/env python
# cbus/protocol/pciprotocol.py - asyncio Protocol for C-Bus PCI/CNI
# Copyright 2012-2020 Michael Farrell <micolous+git@gmail.com>
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this library.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import
from __future__ import print_function

from asyncio import (CancelledError, Future, Lock, create_task,
                     get_running_loop, run, sleep)
from asyncio.transports import WriteTransport
from datetime import datetime
import logging
from typing import Iterable, Optional, Text, Union, Dict, Tuple, Any

from six import int2byte

from cbus.protocol.cal.report import BinaryStatusReport, LevelStatusReport

try:
    from serial_asyncio import create_serial_connection
except ImportError:
    async def create_serial_connection(*_, **__):
        raise ImportError('Serial device support requires pyserial-asyncio')

from cbus.common import (
    Application, CONFIRMATION_CODES, END_COMMAND, add_cbus_checksum)
from cbus.protocol.application.clock import (
    ClockSAL, ClockRequestSAL, ClockUpdateSAL, clock_update_sal)
from cbus.protocol.application.lighting import (
    LightingSAL, LightingOnSAL, LightingOffSAL, LightingRampSAL,
    LightingTerminateRampSAL)
from cbus.protocol.application.status_request import StatusRequestSAL
from cbus.protocol.base_packet import (
    BasePacket, SpecialServerPacket, SpecialClientPacket)
from cbus.protocol.cal.identify import IdentifyCAL
from cbus.protocol.cbus_protocol import CBusProtocol
from cbus.protocol.confirm_packet import ConfirmationPacket
from cbus.protocol.dm_packet import DeviceManagementPacket
from cbus.protocol.error_packet import PCIErrorPacket
# from cbus.protocol.po_packet import PowerOnPacket
from cbus.protocol.pm_packet import PointToMultipointPacket
from cbus.protocol.pp_packet import PointToPointPacket
from cbus.protocol.reset_packet import ResetPacket
from cbus.protocol.cal.extended import ExtendedCAL

logger = logging.getLogger('cbus')

__all__ = ['PCIProtocol']


class PCIProtocol(CBusProtocol):
    """
    Implements an asyncio Protocol for communicating with a C-Bus PCI/CNI over
    TCP or serial.

    """

    def __init__(
            self,
            timesync_frequency: int = 10,
            handle_clock_requests: bool = True,
            connection_lost_future: Optional[Future] = None):
        super(PCIProtocol, self).__init__(emulate_pci=False)

        self._transport = None  # type: Optional[WriteTransport]
        self._next_confirmation_index = 0
        self._recv_buffer = bytearray()
        self._recv_buffer_lock = Lock()
        self._timesync_frequency = timesync_frequency
        self._connection_lost_future = connection_lost_future
        self._handle_clock_requests = bool(handle_clock_requests)
        
        # Track which confirmation codes are in use along with their timestamp
        self._confirmation_codes_in_use = {}  # code -> timestamp
        self._confirmation_lock = Lock()
        self._confirmation_timeout = 30.0  # 30 seconds timeout
        
        # Track pending packets waiting for confirmation
        self._pending_confirmations = {}  # code -> (packet_data, attempts, last_attempt_time)
        self._max_retries = 3
        self._retry_interval = 1.0  # 1 second retry interval
        logger.info(f"PCIProtocol initialized with confirmation timeout of {self._confirmation_timeout} seconds, retry interval {self._retry_interval}s, max retries {self._max_retries}")

    def connection_made(self, transport: WriteTransport) -> None:
        """
        Called by asyncio when a connection is made to the PCI.  This will
        perform a reset of the PCI to establish the correct communications
        protocol, and start time synchronisation.

        """
        logger.info("Connection established to PCI device")
        self._transport = transport
        
        # Clean up any existing state from previous connections
        self._cleanup_state()
        
        create_task(self.pci_reset())
        if self._timesync_frequency:
            logger.info(f"Starting time synchronization task with frequency {self._timesync_frequency} seconds")
            create_task(self.timesync())
        # Start the packet retry task
        create_task(self._check_pending_confirmations())

    def connection_lost(self, exc: Optional[Exception]) -> None:
        logger.warning(f"Connection to PCI lost: {exc}")
        self._transport = None
        
        # Clean up resources to avoid memory leaks
        self._cleanup_state()
        
        # Signal connection lost
        if self._connection_lost_future and not self._connection_lost_future.done():
            self._connection_lost_future.set_result(True)
            
    def _cleanup_state(self):
        """Clean up internal state to prevent memory leaks"""
        logger.info("Cleaning up internal state")
        
        # Clear confirmation code tracking
        self._confirmation_codes_in_use.clear()
        self._pending_confirmations.clear()
        
        # Reset confirmation index
        self._next_confirmation_index = 0
        
        logger.info("Internal state cleaned up successfully")

    def handle_cbus_packet(self, p: BasePacket) -> None:
        """
        Dispatches all packet types into a high level event handler.
        """

        if isinstance(p, SpecialServerPacket):
            if isinstance(p, PCIErrorPacket):
                self.on_pci_cannot_accept_data()
            elif isinstance(p, ConfirmationPacket):
                self.on_confirmation(p.code, p.success)
            else:
                logger.debug(f'hcp: unhandled SpecialServerPacket: {p!r}')
        elif isinstance(p, PointToMultipointPacket):
            for s in p:
                if isinstance(s, LightingSAL):
                    # lighting application
                    if isinstance(s, LightingRampSAL):
                        self.on_lighting_group_ramp(p.source_address,
                                                    s.group_address,s.application_address,
                                                    s.duration, s.level)
                    elif isinstance(s, LightingOnSAL):
                        self.on_lighting_group_on(p.source_address,
                                                  s.group_address,s.application_address)
                    elif isinstance(s, LightingOffSAL):
                        self.on_lighting_group_off(p.source_address,
                                                   s.group_address,s.application_address)
                    elif isinstance(s, LightingTerminateRampSAL):
                        self.on_lighting_group_terminate_ramp(
                            p.source_address, s.group_address,s.application_address)
                    else:
                        logger.debug(f'hcp: unhandled lighting SAL type: {s!r}')
                elif isinstance(s, ClockSAL):
                    if isinstance(s, ClockRequestSAL):
                        self.on_clock_request(p.source_address)
                    elif isinstance(s, ClockUpdateSAL):
                        self.on_clock_update(p.source_address, s.val)
                else:
                    logger.debug(f'hcp: unhandled SAL type: {s!r}')
        elif isinstance(p,PointToPointPacket):
            for s in p:
                if isinstance(s,ExtendedCAL):
                    if isinstance(s.report,BinaryStatusReport):
                        pass
                    elif isinstance(s.report,LevelStatusReport):
                        self.on_level_report(s.child_application, s.block_start, s.report)
                    else:
                        pass
                else:
                    pass

        else:
            logger.debug(f'hcp: unhandled other packet: {p!r}')

    # event handlers
    def on_confirmation(self, code: bytes, success: bool):
        """
        Event called when a command confirmation event was received.

        :param code: A single byte matching the command that this is a response
                     to.

        :param success: True if the command was successful, False otherwise.
        """
        code_int = ord(code)
        logger.debug(f'Received confirmation: code={code_int} (0x{code_int:02X}), success={success}')
        
        # Remove from pending confirmations if present
        create_task(self._remove_from_pending_confirmations(code_int))
        
        # Mark the confirmation code as available again
        if code_int in CONFIRMATION_CODES:
            logger.debug(f"Queueing release of confirmation code {code_int} (0x{code_int:02X})")
            create_task(self._release_confirmation_code(code_int))
        else:
            logger.warning(f"Received unknown confirmation code: {code_int} (0x{code_int:02X})")

    async def _remove_from_pending_confirmations(self, code: int):
        """Remove a code from the pending confirmations dictionary"""
        async with self._confirmation_lock:
            if code in self._pending_confirmations:
                del self._pending_confirmations[code]
                logger.debug(f"Removed confirmation code {code} (0x{code:02X}) from pending confirmations")

    async def _release_confirmation_code(self, code: int):
        """Release a confirmation code back to the pool of available codes."""
        async with self._confirmation_lock:
            if code in self._confirmation_codes_in_use:
                acquisition_time = datetime.now().timestamp() - self._confirmation_codes_in_use[code]
                del self._confirmation_codes_in_use[code]
                used_count = len(self._confirmation_codes_in_use)
                available_count = len(CONFIRMATION_CODES) - used_count
                logger.info(f"Released confirmation code {code} (0x{code:02X}) after {acquisition_time:.2f}s. Used: {used_count}, Available: {available_count}")
                
                # Also remove from pending confirmations if present
                if code in self._pending_confirmations:
                    del self._pending_confirmations[code]
                    logger.debug(f"Removed confirmation code {code} (0x{code:02X}) from pending confirmations during release")
            else:
                logger.warning(f"Attempted to release confirmation code {code} (0x{code:02X}) that was not in use")

    async def _check_and_release_timed_out_codes(self):
        """Check for confirmation codes that have timed out and release them."""
        current_time = datetime.now().timestamp()
        async with self._confirmation_lock:
            timed_out = []
            for code, timestamp in list(self._confirmation_codes_in_use.items()):
                elapsed = current_time - timestamp
                if elapsed > self._confirmation_timeout:
                    timed_out.append((code, elapsed))
                    
            for code, elapsed in timed_out:
                del self._confirmation_codes_in_use[code]
                used_count = len(self._confirmation_codes_in_use)
                available_count = len(CONFIRMATION_CODES) - used_count
                logger.warning(f"Confirmation code {code} (0x{code:02X}) timed out after {elapsed:.2f}s (limit: {self._confirmation_timeout}s). Used: {used_count}, Available: {available_count}")
                
                # Also remove from pending confirmations if present
                if code in self._pending_confirmations:
                    del self._pending_confirmations[code]
                    logger.debug(f"Removed confirmation code {code} (0x{code:02X}) from pending confirmations during timeout")
            
            if timed_out:
                logger.info(f"Released {len(timed_out)} timed out confirmation codes")
                
            # Safety check: If we still have too many codes in use, force cleanup the oldest ones
            if len(self._confirmation_codes_in_use) > len(CONFIRMATION_CODES) * 0.9:  # If more than 90% of codes are in use
                logger.warning(f"Too many confirmation codes in use ({len(self._confirmation_codes_in_use)}), forcing cleanup of oldest codes")
                # Sort by timestamp (oldest first)
                codes_by_age = sorted(self._confirmation_codes_in_use.items(), key=lambda x: x[1])
                # Force release the oldest 25% of codes
                codes_to_force_release = codes_by_age[:max(1, len(codes_by_age) // 4)]
                
                for code, timestamp in codes_to_force_release:
                    elapsed = current_time - timestamp
                    del self._confirmation_codes_in_use[code]
                    logger.warning(f"Force released confirmation code {code} (0x{code:02X}) after {elapsed:.2f}s due to high usage")
                    
                    # Also remove from pending confirmations if present
                    if code in self._pending_confirmations:
                        del self._pending_confirmations[code]
                        logger.debug(f"Removed confirmation code {code} (0x{code:02X}) from pending confirmations during force cleanup")

    async def _check_pending_confirmations(self):
        """
        Background task that checks for pending confirmations that need to be resent.
        Tries to resend packets up to self._max_retries times before giving up.
        """
        logger.info(f"Starting packet retry task with interval {self._retry_interval}s, max retries {self._max_retries}")
        
        # Track consecutive failures to detect system issues
        consecutive_failures = 0
        max_consecutive_failures = 10
        
        while True:
            try:
                # Sleep first to avoid immediate retries on startup
                await sleep(self._retry_interval)
                
                current_time = datetime.now().timestamp()
                to_retry = []
                to_abandon = []
                
                # Check and handle timed out confirmation codes
                await self._check_and_release_timed_out_codes()
                
                async with self._confirmation_lock:
                    # Track how many pending confirmations we have
                    pending_count = len(self._pending_confirmations)
                    if pending_count > 20:  # If we have too many pending confirmations
                        logger.warning(f"High number of pending confirmations: {pending_count}")
                    
                    for code, (packet_data, attempts, last_attempt_time) in list(self._pending_confirmations.items()):
                        elapsed = current_time - last_attempt_time
                        
                        if elapsed >= self._retry_interval:
                            if attempts < self._max_retries:
                                to_retry.append((code, packet_data))
                            else:
                                to_abandon.append(code)
                
                # Process packets to be abandoned (outside the lock)
                for code in to_abandon:
                    logger.warning(f"Giving up on confirmation code {code} (0x{code:02X}) after {self._max_retries} attempts")
                    async with self._confirmation_lock:
                        if code in self._pending_confirmations:
                            del self._pending_confirmations[code]
                    await self._release_confirmation_code(code)
                    
                    # Count consecutive failures
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(f"Detected {consecutive_failures} consecutive failures. Connection may be unstable.")
                        # Reset counters after logging the issue
                        consecutive_failures = 0
                
                # Reset consecutive failures counter if we don't have abandonments
                if not to_abandon:
                    consecutive_failures = 0
                
                # Process packets to be retried (outside the lock)
                for code, packet_data in to_retry:
                    async with self._confirmation_lock:
                        if code in self._pending_confirmations:
                            attempts = self._pending_confirmations[code][1] + 1
                            self._pending_confirmations[code] = (packet_data, attempts, current_time)
                            logger.info(f"Resending packet with confirmation code {code} (0x{code:02X}), attempt {attempts}/{self._max_retries}")
                    
                    # Resend the packet
                    await self._send_packet(packet_data)
                    
            except CancelledError:
                logger.info("Packet retry task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in packet retry task: {e}", exc_info=True)
                # Continue the loop but with a short delay to avoid spamming logs
                await sleep(1)
        
        logger.info("Packet retry task ended")

    def on_reset(self):
        """
        Event called when the PCI has been hard reset.

        """
        logger.debug('recv: pci reset in progress!')

    def on_mmi(self, application: int, data: bytes):
        """
        Event called when a MMI was received.

        :param application: Application that this MMI concerns.
        :param data: MMI data

        """
        logger.debug(f'recv: mmi: application {application}, data {data!r}')

    def on_lighting_group_ramp(self, source_addr: int, group_addr: int,
                               application_address: int, duration: int, level: int):
        """
        Event called when a lighting application ramp (fade) request is
        received.

        :param source_addr: Source address of the unit that generated this
                            event.
        :type source_addr: int

        :param group_addr: Group address being ramped.
        :type group_addr: int
        
        :param application_address: Application address.
        :type application_address: int

        :param duration: Duration, in seconds, that the ramp is occurring over.
        :type duration: int

        :param level: Target brightness of the ramp (0 - 255).
        :type level: int
        """
        logger.debug(
            f'recv: light ramp: from {source_addr} to {group_addr}, application {application_address}, duration '
            f'{duration} seconds to level {level} ')

    def on_lighting_group_on(self, source_addr: int, group_addr: int, application_address: int):
        """
        Event called when a lighting application "on" request is received.

        :param source_addr: Source address of the unit that generated this
                            event.
        :type source_addr: int

        :param group_addr: Group address being turned on.
        :type group_addr: int
        
        :param application_address: Application address.
        :type application_address: int
        """
        logger.debug(f'recv: light on: from {source_addr} to {group_addr}, application {application_address}')

    def on_lighting_group_off(self, source_addr: int, group_addr: int, application_address: int):
        """
        Event called when a lighting application "off" request is received.

        :param source_addr: Source address of the unit that generated this
                            event.
        :type source_addr: int

        :param group_addr: Group address being turned off.
        :type group_addr: int
        
        :param application_address: Application address.
        :type application_address: int
        """
        logger.debug(f'recv: light off: from {source_addr} to {group_addr}, application {application_address}')

    def on_lighting_group_terminate_ramp(
            self, source_addr: int, group_addr: int, application_address: int):
        """
        Event called when a lighting application "terminate ramp" request is
        received.

        :param source_addr: Source address of the unit that generated this
                            event.
        :type source_addr: int

        :param group_addr: Group address stopping ramping.
        :type group_addr: int
        
        :param application_address: Application address.
        :type application_address: int
        """
        logger.debug(
            f'recv: terminate ramp: from {source_addr} to {group_addr}, application {application_address}')

    def on_lighting_label_text(self, source_addr: int, group_addr: int,
                               flavour: int, language_code: int, label: Text):
        """
        Event called when a group address' label text is updated.

        :param source_addr: Source address of the unit that generated this
                            event.
        :type source_addr: int

        :param group_addr: Group address to relabel.
        :type group_addr: int

        :param flavour: "Flavour" of the label to update.  This is a value
                        between 0 and 3.
        :type flavour: int

        :param language_code: Language code for the label.
        :type language_code: int

        :param label: Label text, or an empty string to delete the label.
        :type label: str

        """
        logger.debug(
            f'recv: lighting label text: from {source_addr} to {group_addr} '
            f'flavour {flavour} lang {language_code} text {label!r}')
            
    def on_level_report(self, application, block_start, report):
        """
        Event called when a level report is received.
        
        :param application: The application that generated the report
        :param block_start: The start address of the report block
        :param report: The level status report object
        """
        logger.debug(f'recv: level report: application {application}, block_start {block_start}, report {report!r}')

    def on_pci_cannot_accept_data(self):
        """
        Event called whenever the PCI cannot accept the supplied data. Common
        reasons for this occurring:

        * The checksum is incorrect.
        * The buffer in the PCI is full.

        Unfortunately the PCI does not tell us which requests these are
        associated with.

        This error can occur if data is being sent to the PCI too quickly, or
        if the cable connecting the PCI to the computer is faulty.

        While the PCI can operate at 9600 baud, this only applies to data it
        sends, not to data it recieves.

        """
        logger.debug('recv: PCI cannot accept data')

    def on_pci_power_up(self):
        """
        If Power-up Notification (PUN) is enabled on the PCI, this event is
        fired.

        This event may be fired multiple times in quick succession, as the PCI
        will send the event twice.

        """
        logger.debug('recv: PCI power-up notification')

    def on_clock_request(self, source_addr):
        """
        Event called when a unit requests time from the network.

        :param source_addr: Source address of the unit requesting time.
        :type source_addr: int
        """
        logger.debug(f'recv: clock request from {source_addr}')
        if self._handle_clock_requests:
            self.clock_datetime()

    def on_clock_update(self, source_addr, val):
        """
        Event called when a unit sends time to the network.

        :param source_addr: Source address of the unit requesting time.
        :type source_addr: int

        """
        logger.debug(f'recv: clock update from {source_addr} of {val!r}')

    async def _get_confirmation_code(self):
        """
        Creates a confirmation code, and increments forward the next in the
        list. If all codes are in use, waits until one becomes available.
        Automatically releases codes that have timed out.

        """
        logger.debug("Requesting confirmation code")
        
        # First check and release any timed out codes
        await self._check_and_release_timed_out_codes()
        
        async with self._confirmation_lock:
            used_count = len(self._confirmation_codes_in_use)
            available_count = len(CONFIRMATION_CODES) - used_count
            logger.debug(f"Currently {used_count} codes in use, {available_count} available")
            
            # Try to find an available code
            for _ in range(len(CONFIRMATION_CODES)):
                code = CONFIRMATION_CODES[self._next_confirmation_index]
                
                self._next_confirmation_index += 1
                self._next_confirmation_index %= len(CONFIRMATION_CODES)
                
                if code not in self._confirmation_codes_in_use:
                    # Store code with current timestamp
                    self._confirmation_codes_in_use[code] = datetime.now().timestamp()
                    used_count = len(self._confirmation_codes_in_use)
                    available_count = len(CONFIRMATION_CODES) - used_count
                    logger.info(f"Allocated confirmation code {code} (0x{code:02X}). Used: {used_count}, Available: {available_count}")
                    return int2byte(code)
        
        # If we get here, all codes are in use - force release the oldest code
        logger.warning("All confirmation codes are in use, releasing oldest code")
        
        async with self._confirmation_lock:
            # Find oldest code by timestamp
            if self._confirmation_codes_in_use:
                oldest_code = min(self._confirmation_codes_in_use.items(), key=lambda x: x[1])[0]
                elapsed = datetime.now().timestamp() - self._confirmation_codes_in_use[oldest_code]
                
                # Release the oldest code
                del self._confirmation_codes_in_use[oldest_code]
                if oldest_code in self._pending_confirmations:
                    del self._pending_confirmations[oldest_code] 
                
                logger.warning(f"Force released oldest confirmation code {oldest_code} (0x{oldest_code:02X}) after {elapsed:.2f}s")
                
                # Use the next available code (different from the one we just released)
                for _ in range(len(CONFIRMATION_CODES)):
                    code = CONFIRMATION_CODES[self._next_confirmation_index]
                    
                    self._next_confirmation_index += 1
                    self._next_confirmation_index %= len(CONFIRMATION_CODES)
                    
                    if code != oldest_code and code not in self._confirmation_codes_in_use:
                        # Store code with current timestamp
                        self._confirmation_codes_in_use[code] = datetime.now().timestamp()
                        used_count = len(self._confirmation_codes_in_use)
                        available_count = len(CONFIRMATION_CODES) - used_count
                        logger.info(f"Allocated confirmation code {code} (0x{code:02X}) after releasing oldest. Used: {used_count}, Available: {available_count}")
                        return int2byte(code)
                
                # If we couldn't find a different code, use the same one we just released
                code = oldest_code
                self._confirmation_codes_in_use[code] = datetime.now().timestamp()
                used_count = len(self._confirmation_codes_in_use)
                available_count = len(CONFIRMATION_CODES) - used_count
                logger.info(f"Re-allocated same confirmation code {code} (0x{code:02X}). Used: {used_count}, Available: {available_count}")
                return int2byte(code)
            else:
                # This should never happen, but just in case
                logger.error("No confirmation codes in use but couldn't find an available code!")
                # Use the first code
                code = CONFIRMATION_CODES[0]
                self._confirmation_codes_in_use[code] = datetime.now().timestamp()
                logger.info(f"Allocated emergency confirmation code {code} (0x{code:02X})")
                return int2byte(code)

    async def _prepare_packet(self,
                  cmd: BasePacket,
                  confirmation: bool = True,
                  basic_mode: bool = False):
        """
        Prepares a packet of CBus data for sending without actually sending it.
        
        Args:
            cmd: The packet to prepare
            confirmation: Whether to request confirmation
            basic_mode: Whether to send in basic mode
            
        Returns:
            Tuple of (prepared_data, confirmation_code)
            where confirmation_code is None if no confirmation was requested
        """
        if not isinstance(cmd, BasePacket):
            logger.error(f"Cannot prepare command - invalid type: {type(cmd)}")
            raise TypeError('cmd must be BasePacket')
        
        logger.debug(f'Preparing packet: {cmd!r}')
        
        checksum = False
        
        if isinstance(cmd, SpecialClientPacket):
            basic_mode = True
            confirmation = False
            logger.debug("Using basic mode and no confirmation for SpecialClientPacket")
        
        cmd_bytes = cmd.encode_packet()
        
        if not basic_mode:
            cmd_bytes = b'\\' + cmd_bytes
            logger.debug("Added escape character to non-basic mode packet")
        
        if checksum:
            cmd_bytes = add_cbus_checksum(cmd_bytes)
            logger.debug("Added checksum to packet")
        
        conf_code = None
        if confirmation:
            logger.debug("Getting confirmation code for packet")
            conf_code = await self._get_confirmation_code()
            cmd_bytes += conf_code
            logger.debug(f"Added confirmation code {ord(conf_code)} (0x{ord(conf_code):02X}) to packet")
        
        cmd_bytes += END_COMMAND
        logger.debug(f'Prepared encoded data: {cmd_bytes!r}')
        
        return cmd_bytes, conf_code
    
    async def _send_packet(self, prepared_data: bytes):
        """
        Sends previously prepared packet data.
        
        Args:
            prepared_data: The data to send
        """
        transport = self._transport
        if transport is None:
            logger.error("Cannot send command - transport not connected")
            raise IOError('transport not connected')
        
        # add a short delay to ensure the command is sent because the CNI is super slow
        await sleep(0.1)
        transport.write(prepared_data)
        logger.debug("Data sent to transport")

    async def _send(self,
              cmd: BasePacket,
              confirmation: bool = True,
              basic_mode: bool = False):
        """
        Prepares and sends a packet of CBus data.
        
        Args:
            cmd: The packet to send
            confirmation: Whether to request confirmation
            basic_mode: Whether to send in basic mode
            
        Returns:
            The confirmation code byte, or None if no confirmation was requested
        """
        prepared_data, conf_code = await self._prepare_packet(cmd, confirmation, basic_mode)
        await self._send_packet(prepared_data)
        
        # If confirmation was requested, add packet to pending confirmations
        if conf_code is not None:
            code_int = ord(conf_code)
            now = datetime.now().timestamp()
            async with self._confirmation_lock:
                self._pending_confirmations[code_int] = (prepared_data, 1, now)
                logger.debug(f"Added confirmation code {code_int} (0x{code_int:02X}) to pending confirmations")
        
        return conf_code

    async def pci_reset(self):
        """
        Performs a full reset of the PCI.

        """
        logger.info("Performing PCI reset")
        # reset the PCI, disable MMI reports so we know when buttons are
        # pressed. (mmi toggle is 59g disable vs 79g enable)
        #
        # MMI calls aren't needed to get events from light switches and other
        # device on the network.

        # full system reset
        for i in range(3):
            logger.debug(f"Sending reset packet {i+1}/3")
            await self._send(ResetPacket())

        logger.debug("Setting application address 1 to ALL applications")
        # serial user interface guide sect 10.2
        # Set application address 1 to ALL applications
        # self._send('A32100FF', encode=False, checksum=False)
        await self._send(DeviceManagementPacket(
            checksum=False, parameter=0x21, value=0xFF),
            basic_mode=True)
        
        logger.debug("Setting application address 2 to USED applications")
        # serial user interface guide sect 10.2
        # Set application address 2 to USED applications
        # self._send('A32200FF', encode=False, checksum=False)
        await self._send(DeviceManagementPacket(
            checksum=False, parameter=0x22, value=0xFF),
            basic_mode=True)

        logger.debug("Setting interface options #3")
        # Interface options #3
        # = 0x0E / 0000 1110
        # 1: LOCAL_SAL
        # 2: PUN - power-up notification
        # 3: EXSTAT
        # self._send('A342000E', encode=False, checksum=False)
        await self._send(DeviceManagementPacket(
            checksum=False, parameter=0x42, value=0x0E),
            basic_mode=True)

        logger.debug("Setting interface options #1")
        # Interface options #1
        # = 0x59 / 0101 1001
        # 0: CONNECT
        # 3: SRCHK - strict checksum check
        # 4: SMART
        # 5: MONITOR
        # 6: IDMON
        # self._send('A3300059', encode=False, checksum=False)
        await self._send(DeviceManagementPacket(
            checksum=False, parameter=0x30, value=0x79),
            basic_mode=True)
        logger.info("PCI reset complete")

    async def identify(self, unit_address, attribute):
        """
        Sends an IDENTIFY command to the given unit_address.

        :param unit_address: Unit address to send the packet to
        :type unit_address: int

        :param attribute: Attribute ID to retrieve information for. See s7.2
                          of Serial Interface Guide for acceptable codes.
        :type attribute: int

        :returns: Single-byte string with code for the confirmation event.
        :rtype: string
        """
        p = PointToPointPacket(
            unit_address=unit_address, cals=[IdentifyCAL(attribute)])
        return await self._send(p)

    async def lighting_group_on(self, group_addr: Union[int, Iterable[int]],application_addr: Union[int,Application] ):
        """
        Turns on the lights for the given group_id.

        :param group_addr: Group address(es) to turn the lights on for, up to 9
        :type group_addr: int, or iterable of ints of length <= 9.

        :returns: Single-byte string with code for the confirmation event.
        :rtype: string

        """
        if not isinstance(group_addr, Iterable):
            group_addr = [group_addr]

        group_addr = [int(g) for g in group_addr]
        group_addr_count = len(group_addr)

        if group_addr_count > 9:
            # maximum 9 group addresses per packet
            raise ValueError(
                f'group_addr iterable length is > 9 ({group_addr_count})')

        p = PointToMultipointPacket(
            sals=[LightingOnSAL(ga,application_addr) for ga in group_addr])
        return await self._send(p)

    async def request_status(self,group_addr: Union[int, Iterable[int]],application_addr: Union[int,Application] ):
        p = PointToMultipointPacket(sals=[
                StatusRequestSAL(level_request=True, group_address=group_addr,child_application=application_addr)
            ])
        return await self._send(p)
    
    
    async def lighting_group_off(self, group_addr: Union[int, Iterable[int]],application_addr: Union[int,Application] ):
        """
        Turns off the lights for the given group_id.

        :param group_addr: Group address(es) to turn the lights off for, up to
                           9
        :type group_addr: int, or iterable of ints of length <= 9.

        :returns: Single-byte string with code for the confirmation event.
        :rtype: string

        """
        if not isinstance(group_addr, Iterable):
            group_addr = [group_addr]

        group_addr = [int(g) for g in group_addr]
        group_addr_count = len(group_addr)

        if group_addr_count > 9:
            # maximum 9 group addresses per packet
            raise ValueError(
                f'group_addr iterable length is > 9 ({group_addr_count})')

        p = PointToMultipointPacket(
            sals=[LightingOffSAL(ga,application_addr) for ga in group_addr])
        return await self._send(p)

    async def lighting_group_ramp(
            self, group_addr: int, application_addr: Union[int,Application], duration: int, level: int = 255 ):
        """
        Ramps (fades) a group address to a specified lighting level.

        Note: CBus only supports a limited number of fade durations, in
        decreasing accuracy up to 17 minutes (1020 seconds). Durations
        longer than this will throw an error.

        A duration of 0 will ramp "instantly" to the given level.

        :param group_addr: The group address to ramp.
        :type group_addr: int
        :param duration: Duration, in seconds, that the ramp should occur over.
        :type duration: int
        :param level: A value between 0 and 255 indicating the brightness.
        :type level: int

        :returns: Single-byte string with code for the confirmation event.
        :rtype: string

        """
        p = PointToMultipointPacket(
            sals=LightingRampSAL(group_addr, application_addr, duration, level))
        return await self._send(p)

    async def lighting_group_terminate_ramp(
            self, group_addr: Union[int, Iterable[int]], application_addr: Union[int,Application]):
        """
        Stops ramping a group address at the current point.

        :param group_addr: Group address to stop ramping of.
        :type group_addr: int

        :returns: Single-byte string with code for the confirmation event.
        :rtype: string
        """

        if not isinstance(group_addr, Iterable):
            group_addr = [group_addr]

        group_addr = [int(g) for g in group_addr]
        group_addr_count = len(group_addr)

        if group_addr_count > 9:
            # maximum 9 group addresses per packet
            raise ValueError(
                f'group_addr iterable length is > 9 ({group_addr_count})')

        p = PointToMultipointPacket(
            sals=[LightingTerminateRampSAL(ga,application_addr) for ga in group_addr])
        return await self._send(p)

    async def clock_datetime(self, when: Optional[datetime] = None):
        """
        Sends the system's local time to the CBus network.

        :param when: The time and date to send to the CBus network. Defaults
                     to current local time.
        :type when: datetime.datetime

        """
        if when is None:
            when = datetime.now()

        p = PointToMultipointPacket(sals=clock_update_sal(when))
        return await self._send(p)

    async def timesync(self):
        frequency = self._timesync_frequency
        if frequency <= 0:
            logger.info("Time synchronization disabled")
            return

        logger.info(f"Starting time synchronization loop with frequency {frequency}s")
        sync_count = 0
        while True:
            try:
                sync_count += 1
                logger.debug(f"Sending time synchronization packet #{sync_count}")
                await self.clock_datetime()
                logger.debug(f"Time synchronization packet #{sync_count} sent, sleeping for {frequency}s")
                await sleep(frequency)
                # self._send(PointToMultipointPacket(sals=StatusRequestSAL(
                #     child_application=Application.LIGHTING,
                #     level_request=True,
                #     group_address=0,
                # )))
            except CancelledError:
                logger.info("Time synchronization task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in time synchronization: {e}", exc_info=True)
                # Sleep before retrying
                await sleep(1)
        logger.info("Time synchronization loop ended")

    # def recall(self, unit_addr, param_no, count):
    #    return self._send('%s%02X%s%s%02X%02X' % (
    #        POINT_TO_46, unit_addr, ROUTING_NONE, RECALL, param_no, count
    #    ))

    # def identify(self, unit_addr, attribute):
    #    return self._send('%s%02X%s%s%02X' % (
    #        POINT_TO_46, unit_addr, ROUTING_NONE, RECALL, attribute
    #    ))


async def main():
    """
    Test program for PCIProtocol.

    Imports are included inside of this method in order to avoid loading
    unneeded dependencies.
    """
    from argparse import ArgumentParser

    parser = ArgumentParser(description="""\
        Test program that displays events from a connected C-Bus PCI (over 
        serial, USB or TCP) or CNI (TCP).
    """)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '-s', '--serial',
        dest='serial', default=None, metavar='DEVICE',
        help='Serial port where the PCI is located. USB PCIs appear as a '
             'cp210x USB-serial adapter. (example: -s /dev/ttyUSB0)')

    group.add_argument(
        '-t', '--tcp',
        dest='tcp', default=None, metavar='ADDR:PORT',
        help='IP address and TCP port where the C-Bus CNI or PCI is located '
             '(eg: -t 192.0.2.1:10001)')

    option = parser.parse_args()

    global_logger = logging.getLogger('cbus')
    global_logger.setLevel(logging.DEBUG)
    logging.basicConfig(level=logging.DEBUG)
    loop = get_running_loop()
    connection_lost_future = loop.create_future()

    def factory():
        return PCIProtocol(connection_lost_future=connection_lost_future)

    if option.serial:
        await create_serial_connection(
            loop, factory, option.serial, baudrate=9600)
    elif option.tcp:
        addr, port = option.tcp.split(':', 2)
        await loop.create_connection(factory, addr, int(port))

    await connection_lost_future


if __name__ == '__main__':
    run(main())
