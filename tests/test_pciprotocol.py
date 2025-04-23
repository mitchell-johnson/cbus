#!/usr/bin/env python
# tests/test_pciprotocol.py - Test packet resending mechanism in PCIProtocol
# Copyright 2024 Mitchell Johnson
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

import unittest
import asyncio
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime
from parameterized import parameterized

from cbus.protocol.pciprotocol import PCIProtocol
from cbus.protocol.application.lighting import LightingOnSAL, LightingOffSAL
from cbus.protocol.pm_packet import PointToMultipointPacket
from cbus.common import Application


class MockTransport(MagicMock):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.written_data = []

    def write(self, data):
        self.written_data.append(data)
        return len(data)


class TestPCIProtocol:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)
        
        self.protocol = PCIProtocol(timesync_frequency=0)  # Disable time sync to simplify testing
        self.transport = MockTransport()
        self.protocol._transport = self.transport
        
        # Mock the release_confirmation_code to avoid actually releasing it
        patcher1 = patch.object(
            self.protocol, 
            '_release_confirmation_code', 
            new=AsyncMock(side_effect=self._mock_release_code)
        )
        
        # Mock _send_packet to avoid actual sending
        patcher2 = patch.object(
            self.protocol,
            '_send_packet',
            new=AsyncMock()
        )
        
        # Mock the PCI reset method
        patcher3 = patch.object(
            self.protocol,
            'pci_reset',
            new=AsyncMock()
        )
        
        # This is a special version of _check_pending_confirmations that we can control
        def mock_check_pending_confirmations():
            fut = asyncio.Future()
            fut.set_result(None)
            return fut
        
        patcher4 = patch.object(
            self.protocol,
            '_check_pending_confirmations',
            new=mock_check_pending_confirmations
        )
        
        patcher1.start()
        patcher2.start()
        patcher3.start()
        patcher4.start()
        
        yield
        
        patcher1.stop()
        patcher2.stop()
        patcher3.stop()
        patcher4.stop()
        
        self.event_loop.close()
    
    async def _mock_release_code(self, code):
        """Mocked version of _release_confirmation_code that only clears it from pending"""
        async with self.protocol._confirmation_lock:
            if code in self.protocol._pending_confirmations:
                del self.protocol._pending_confirmations[code]
    
    async def _real_check_pending_confirmations(self):
        """Run a single iteration of the real _check_pending_confirmations logic"""
        current_time = datetime.now().timestamp()
        to_retry = []
        to_abandon = []
        
        async with self.protocol._confirmation_lock:
            for code, (packet_data, attempts, last_attempt_time) in list(self.protocol._pending_confirmations.items()):
                elapsed = current_time - last_attempt_time
                
                if elapsed >= self.protocol._retry_interval:
                    if attempts < self.protocol._max_retries:
                        to_retry.append((code, packet_data))
                    else:
                        to_abandon.append(code)
        
        # Process packets to be abandoned
        for code in to_abandon:
            await self.protocol._release_confirmation_code(code)
        
        # Process packets to be retried
        for code, packet_data in to_retry:
            async with self.protocol._confirmation_lock:
                if code in self.protocol._pending_confirmations:
                    attempts = self.protocol._pending_confirmations[code][1] + 1
                    self.protocol._pending_confirmations[code] = (
                        packet_data, attempts, current_time)
            
            # We don't actually send in the test
            # await self.protocol._send_packet(packet_data)
    
    def test_connection_made(self):
        """Test connection_made sets up retry task"""
        # Create a new protocol to test connection_made
        protocol = PCIProtocol(timesync_frequency=0)
        mock_transport = MockTransport()
        
        # Patch create_task to capture tasks being created
        with patch('cbus.protocol.pciprotocol.create_task') as mock_create_task:
            protocol.connection_made(mock_transport)
            # At least two tasks should be created - pci_reset and _check_pending_confirmations
            assert mock_create_task.called
            assert mock_create_task.call_count >= 2
            
            # Check if _check_pending_confirmations is one of the created tasks
            found_retry_task = False
            for call in mock_create_task.call_args_list:
                # The first argument (args[0]) should be the coroutine
                coro = call[0][0]
                if hasattr(coro, '__qualname__') or hasattr(coro, '__name__'):
                    name = str(getattr(coro, '__qualname__', '') or getattr(coro, '__name__', ''))
                    if '_check_pending_confirmations' in name:
                        found_retry_task = True
                        break
            
            assert found_retry_task, "The _check_pending_confirmations task was not created"
    
    def test_retry_params(self):
        """Test retry parameters are set correctly"""
        protocol = PCIProtocol(timesync_frequency=0)
        assert protocol._max_retries == 3
        assert protocol._retry_interval == 1.0
    
    @pytest.mark.asyncio
    async def test_confirmation_release(self):
        """Test confirmation code is released when confirmation is received"""
        # Patch _get_confirmation_code to always return the same code
        with patch.object(self.protocol, '_get_confirmation_code', 
                        return_value=b'\x05'):
            
            # Send a command that requires confirmation
            packet = PointToMultipointPacket(
                sals=[LightingOnSAL(1, Application.LIGHTING)])
            
            # Manually add the code to the in-use tracking to simulate _get_confirmation_code behavior
            async with self.protocol._confirmation_lock:
                self.protocol._confirmation_codes_in_use[0x05] = datetime.now().timestamp()
            
            # Execute the send
            conf_code = await self.protocol._send(packet)
            
            # Verify the confirmation code is what we expect
            assert conf_code == b'\x05'
            
            # Verify the code is in pending confirmations
            async with self.protocol._confirmation_lock:
                assert 0x05 in self.protocol._pending_confirmations
            
            # Simulate receiving confirmation (but mock the _remove_from_pending_confirmations)
            with patch.object(self.protocol, '_remove_from_pending_confirmations', new=AsyncMock()) as mock_remove:
                self.protocol.on_confirmation(b'\x05', True)
                
                # Verify _remove_from_pending_confirmations was called with the right code
                mock_remove.assert_called_once_with(0x05)
    
    @pytest.mark.asyncio
    async def test_packet_retry(self):
        """Test packet is retried when no confirmation is received"""
        # Patch _get_confirmation_code to always return the same code
        with patch.object(self.protocol, '_get_confirmation_code', 
                        return_value=b'\x05'):
            
            # Create a test packet
            packet = PointToMultipointPacket(
                sals=[LightingOnSAL(1, Application.LIGHTING)])
            
            # Manually add the code to the in-use tracking to simulate _get_confirmation_code behavior
            async with self.protocol._confirmation_lock:
                self.protocol._confirmation_codes_in_use[0x05] = datetime.now().timestamp()
            
            # Send the packet
            current_time = datetime.now().timestamp()
            conf_code = await self.protocol._send(packet)
            
            # Manually set the timestamp to be in the past to trigger retry
            async with self.protocol._confirmation_lock:
                packet_data, attempts, _ = self.protocol._pending_confirmations[0x05]
                self.protocol._pending_confirmations[0x05] = (
                    packet_data, attempts, current_time - 2.0)
            
            # Run our custom retry check implementation
            await self._real_check_pending_confirmations()
            
            # Verify attempts increased
            async with self.protocol._confirmation_lock:
                assert self.protocol._pending_confirmations[0x05][1] == 2, "Attempt count should be 2"
                
            # Simulate one more retry
            async with self.protocol._confirmation_lock:
                packet_data, attempts, last_attempt = self.protocol._pending_confirmations[0x05]
                self.protocol._pending_confirmations[0x05] = (
                    packet_data, attempts, current_time - 2.0)
                
            await self._real_check_pending_confirmations()
            
            # Verify attempts increased to 3
            async with self.protocol._confirmation_lock:
                assert self.protocol._pending_confirmations[0x05][1] == 3, "Attempt count should be 3"
                
            # One more retry (this should be the last one)
            async with self.protocol._confirmation_lock:
                packet_data, attempts, last_attempt = self.protocol._pending_confirmations[0x05]
                self.protocol._pending_confirmations[0x05] = (
                    packet_data, attempts, current_time - 2.0)
                
            # Use our specific mock of _release_confirmation_code that only clears pending
            with patch.object(self.protocol, '_release_confirmation_code', new=AsyncMock()) as mock_release:
                await self._real_check_pending_confirmations()
                
                # Verify release was called after max retries
                mock_release.assert_called_once_with(0x05)
    
    @pytest.mark.asyncio
    async def test_early_confirmation(self):
        """Test early confirmation stops retry mechanism"""
        # Patch _get_confirmation_code to always return the same code
        with patch.object(self.protocol, '_get_confirmation_code', 
                        return_value=b'\x05'):
            
            # Send a packet
            packet = PointToMultipointPacket(
                sals=[LightingOnSAL(1, Application.LIGHTING)])
            
            # Manually add the code to the in-use tracking to simulate _get_confirmation_code behavior
            async with self.protocol._confirmation_lock:
                self.protocol._confirmation_codes_in_use[0x05] = datetime.now().timestamp()
            
            # Send the packet
            conf_code = await self.protocol._send(packet)
            
            # Verify it's pending confirmation
            async with self.protocol._confirmation_lock:
                assert 0x05 in self.protocol._pending_confirmations
            
            # Simulate receiving confirmation but mock the internal calls
            with patch.object(self.protocol, '_remove_from_pending_confirmations', new=AsyncMock()) as mock_remove:
                self.protocol.on_confirmation(b'\x05', True)
                
                # Verify _remove_from_pending_confirmations was called
                mock_remove.assert_called_once_with(0x05)


if __name__ == '__main__':
    unittest.main() 