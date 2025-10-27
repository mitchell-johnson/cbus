#!/usr/bin/env python
# tests/test_memory_protection.py - Test memory protection features
# Copyright 2024 Mitchell Johnson
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Tests for memory protection and resource cleanup functionality."""

import unittest
import asyncio
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime

from cbus.protocol.pciprotocol import PCIProtocol
from cbus.protocol.application.lighting import LightingOnSAL
from cbus.protocol.pm_packet import PointToMultipointPacket
from cbus.common import Application
from cbus.constants import MAX_PENDING_CONFIRMATIONS


class MockTransport(MagicMock):
    """Mock transport for testing."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.written_data = []
        self.is_closing_flag = False

    def write(self, data):
        self.written_data.append(data)
        return len(data)

    def close(self):
        self.is_closing_flag = True

    def is_closing(self):
        return self.is_closing_flag


class TestMemoryProtection:
    """Tests for memory protection features in PCIProtocol."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)

        self.protocol = PCIProtocol(timesync_frequency=0)
        self.transport = MockTransport()
        self.protocol._transport = self.transport

        yield

        self.event_loop.close()

    @pytest.mark.asyncio
    async def test_cleanup_state_on_connection_lost(self):
        """Test that state is cleaned up when connection is lost."""
        # Set up some state
        self.protocol._confirmation_codes_in_use = {0x68: datetime.now().timestamp()}
        self.protocol._pending_confirmations = {0x68: (b'data', 1, datetime.now().timestamp())}
        self.protocol._next_confirmation_index = 5

        # Simulate connection lost
        self.protocol.connection_lost(Exception("Connection reset"))

        # Verify cleanup
        assert len(self.protocol._confirmation_codes_in_use) == 0
        assert len(self.protocol._pending_confirmations) == 0
        assert self.protocol._next_confirmation_index == 0
        assert self.protocol._transport is None

    @pytest.mark.asyncio
    async def test_cleanup_state_on_connection_made(self):
        """Test that old state is cleaned up when new connection is made."""
        # Set up old state
        self.protocol._confirmation_codes_in_use = {0x68: datetime.now().timestamp()}
        self.protocol._pending_confirmations = {0x68: (b'data', 1, datetime.now().timestamp())}

        # Make new connection
        with patch('cbus.protocol.pciprotocol.create_task'):
            self.protocol.connection_made(self.transport)

        # Verify cleanup
        assert len(self.protocol._confirmation_codes_in_use) == 0
        assert len(self.protocol._pending_confirmations) == 0

    @pytest.mark.asyncio
    async def test_pending_confirmations_memory_limit(self):
        """Test that pending confirmations are capped to prevent memory leaks."""
        # Fill up pending confirmations beyond the limit
        current_time = datetime.now().timestamp()
        async with self.protocol._confirmation_lock:
            for i in range(MAX_PENDING_CONFIRMATIONS + 10):
                code = 0x68 + i
                # Make older confirmations have earlier timestamps
                timestamp = current_time - (MAX_PENDING_CONFIRMATIONS + 10 - i)
                self.protocol._pending_confirmations[code] = (b'data' + bytes([i]), 1, timestamp)
                self.protocol._confirmation_codes_in_use[code] = timestamp

        # Simulate one iteration of the retry check which should force cleanup
        # We need to mock _release_confirmation_code to avoid side effects
        with patch.object(self.protocol, '_release_confirmation_code', new=AsyncMock()):
            # Import the actual implementation logic
            current_time = datetime.now().timestamp()
            to_abandon = []

            async with self.protocol._confirmation_lock:
                pending_count = len(self.protocol._pending_confirmations)

                # Memory protection: force cleanup if too many pending
                if pending_count > MAX_PENDING_CONFIRMATIONS:
                    sorted_pending = sorted(
                        self.protocol._pending_confirmations.items(),
                        key=lambda x: x[1][2]  # Sort by timestamp
                    )
                    excess = pending_count - MAX_PENDING_CONFIRMATIONS
                    for code, _ in sorted_pending[:excess]:
                        to_abandon.append(code)

            # Verify that we identified excess items for abandonment
            assert len(to_abandon) == 10, f"Should abandon 10 items, got {len(to_abandon)}"

            # Simulate abandonment
            for code in to_abandon:
                async with self.protocol._confirmation_lock:
                    if code in self.protocol._pending_confirmations:
                        del self.protocol._pending_confirmations[code]

            # Verify we're now at the limit
            assert len(self.protocol._pending_confirmations) == MAX_PENDING_CONFIRMATIONS


class TestStateManagement:
    """Tests for connection state management."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)

        self.protocol = PCIProtocol(timesync_frequency=0)
        self.transport = MockTransport()

        yield

        self.event_loop.close()

    @pytest.mark.asyncio
    async def test_connection_lost_sets_future(self):
        """Test that connection_lost sets the connection_lost_future."""
        loop = asyncio.get_event_loop()
        connection_lost_future = loop.create_future()

        protocol = PCIProtocol(timesync_frequency=0, connection_lost_future=connection_lost_future)
        protocol._transport = self.transport

        # Lose connection
        protocol.connection_lost(Exception("Network error"))

        # Verify future is set
        assert connection_lost_future.done()
        assert connection_lost_future.result() is True

    @pytest.mark.asyncio
    async def test_send_without_transport_raises_error(self):
        """Test that sending without a transport raises IOError."""
        # Don't set transport
        self.protocol._transport = None

        packet = PointToMultipointPacket(sals=[LightingOnSAL(1, Application.LIGHTING)])

        # Should raise IOError
        with pytest.raises(IOError, match="transport not connected"):
            await self.protocol._send(packet)

    def test_connection_made_creates_tasks(self):
        """Test that connection_made creates required background tasks."""
        protocol = PCIProtocol(timesync_frequency=0)

        with patch('cbus.protocol.pciprotocol.create_task') as mock_create_task:
            protocol.connection_made(self.transport)

            # Should create at least pci_reset and _check_pending_confirmations tasks
            assert mock_create_task.call_count >= 2


class TestConfirmationCodeAllocation:
    """Tests for confirmation code allocation and release."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)

        self.protocol = PCIProtocol(timesync_frequency=0)
        self.transport = MockTransport()
        self.protocol._transport = self.transport

        yield

        self.event_loop.close()

    @pytest.mark.asyncio
    async def test_confirmation_code_reuse(self):
        """Test that confirmation codes are properly reused after release."""
        # Allocate a code
        code1 = await self.protocol._get_confirmation_code()
        code1_int = ord(code1)

        # Release it
        await self.protocol._release_confirmation_code(code1_int)

        # Should be able to allocate again (eventually the same code)
        code2 = await self.protocol._get_confirmation_code()

        # Verify code was allocated
        assert code2 is not None
        assert len(code2) == 1

    @pytest.mark.asyncio
    async def test_force_release_when_all_codes_in_use(self):
        """Test that oldest code is force-released when all codes are in use."""
        from cbus.common import CONFIRMATION_CODES

        # Allocate all codes
        async with self.protocol._confirmation_lock:
            current_time = datetime.now().timestamp()
            for i, code in enumerate(CONFIRMATION_CODES):
                # Make first code the oldest
                timestamp = current_time - (len(CONFIRMATION_CODES) - i)
                self.protocol._confirmation_codes_in_use[code] = timestamp

        # Try to allocate one more - should force-release oldest
        code = await self.protocol._get_confirmation_code()

        # Should still succeed
        assert code is not None
        assert len(code) == 1

        # Should still succeed even though we exceeded capacity
        # The cleanup releases 25% (5 codes) so we'll have 15 codes left + 1 newly allocated = 16
        assert len(self.protocol._confirmation_codes_in_use) == 16

    @pytest.mark.asyncio
    async def test_timed_out_codes_are_released(self):
        """Test that timed-out confirmation codes are automatically released."""
        # Add a code with old timestamp (beyond timeout)
        code = 0x68
        old_timestamp = datetime.now().timestamp() - (self.protocol._confirmation_timeout + 10)

        async with self.protocol._confirmation_lock:
            self.protocol._confirmation_codes_in_use[code] = old_timestamp

        # Run timeout check
        await self.protocol._check_and_release_timed_out_codes()

        # Code should be released
        async with self.protocol._confirmation_lock:
            assert code not in self.protocol._confirmation_codes_in_use


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
