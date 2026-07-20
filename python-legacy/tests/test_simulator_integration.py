#!/usr/bin/env python
# tests/test_simulator_integration.py - Integration tests using C-Bus simulator
# Copyright 2024 Mitchell Johnson
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Integration tests using the C-Bus simulator."""

import asyncio
import pytest
from tests.simulator_utils import simulator_context, SimulatorTestFixture
from cbus.common import Application


class TestSimulatorBasics:
    """Basic tests to verify simulator functionality."""

    @pytest.mark.asyncio
    async def test_simulator_starts_and_stops(self):
        """Test that simulator can start and stop cleanly."""
        simulator = SimulatorTestFixture()

        # Start simulator
        await simulator.start()
        assert simulator.is_running
        assert simulator.actual_port is not None
        assert simulator.actual_port > 0

        # Stop simulator
        await simulator.stop()
        assert not simulator.is_running

    @pytest.mark.asyncio
    async def test_simulator_context_manager(self):
        """Test simulator context manager."""
        async with simulator_context() as simulator:
            assert simulator.is_running
            assert simulator.actual_port is not None

        # Should be stopped after context
        assert not simulator.is_running

    @pytest.mark.asyncio
    async def test_simulator_can_accept_connections(self):
        """Test that simulator accepts client connections."""
        async with simulator_context() as simulator:
            # Create a connection
            reader, writer = await simulator.create_client_connection()

            # Read initial prompt
            data = await asyncio.wait_for(reader.read(1024), timeout=1.0)
            assert data  # Should receive prompt

            # Close connection
            writer.close()
            await writer.wait_closed()


class TestSimulatorLightingCommands:
    """Test lighting commands through the simulator."""

    @pytest.mark.asyncio
    async def test_lighting_on_command(self):
        """Test turning a light on through simulator."""
        async with simulator_context() as simulator:
            protocol = await simulator.create_protocol_client(timesync_frequency=0)

            try:
                # Turn on light at group address 1
                confirmation_code = await protocol.lighting_group_on(1, Application.LIGHTING)
                assert confirmation_code is not None

                # Give simulator time to process
                await asyncio.sleep(0.2)

                # Verify command was sent (no exception = success)
                assert protocol._transport is not None

            finally:
                if protocol._transport:
                    protocol._transport.close()

    @pytest.mark.asyncio
    async def test_lighting_off_command(self):
        """Test turning a light off through simulator."""
        async with simulator_context() as simulator:
            protocol = await simulator.create_protocol_client(timesync_frequency=0)

            try:
                # Turn off light at group address 1
                confirmation_code = await protocol.lighting_group_off(1, Application.LIGHTING)
                assert confirmation_code is not None

                # Give simulator time to process
                await asyncio.sleep(0.2)

                assert protocol._transport is not None

            finally:
                if protocol._transport:
                    protocol._transport.close()

    @pytest.mark.asyncio
    async def test_lighting_ramp_command(self):
        """Test ramping a light through simulator."""
        async with simulator_context() as simulator:
            protocol = await simulator.create_protocol_client(timesync_frequency=0)

            try:
                # Ramp light to 50% over 4 seconds
                confirmation_code = await protocol.lighting_group_ramp(
                    1, Application.LIGHTING, 4, 128
                )
                assert confirmation_code is not None

                # Give simulator time to process
                await asyncio.sleep(0.2)

                assert protocol._transport is not None

            finally:
                if protocol._transport:
                    protocol._transport.close()

    @pytest.mark.asyncio
    async def test_multiple_lights(self):
        """Test controlling multiple lights."""
        async with simulator_context() as simulator:
            protocol = await simulator.create_protocol_client(timesync_frequency=0)

            try:
                # Turn on multiple lights (groups 1-5)
                for group_id in range(1, 6):
                    confirmation_code = await protocol.lighting_group_on(
                        group_id, Application.LIGHTING
                    )
                    assert confirmation_code is not None
                    await asyncio.sleep(0.05)

                # Turn them all off
                for group_id in range(1, 6):
                    confirmation_code = await protocol.lighting_group_off(
                        group_id, Application.LIGHTING
                    )
                    assert confirmation_code is not None
                    await asyncio.sleep(0.05)

            finally:
                if protocol._transport:
                    protocol._transport.close()


class TestSimulatorConfirmations:
    """Test confirmation handling with simulator."""

    @pytest.mark.asyncio
    async def test_confirmations_received(self):
        """Test that confirmations are received from simulator."""
        async with simulator_context() as simulator:
            protocol = await simulator.create_protocol_client(timesync_frequency=0)

            try:
                # Track confirmations received
                confirmations_received = []

                original_on_confirmation = protocol.on_confirmation

                def track_confirmation(code, success):
                    confirmations_received.append((code, success))
                    original_on_confirmation(code, success)

                protocol.on_confirmation = track_confirmation

                # Send command
                confirmation_code = await protocol.lighting_group_on(1, Application.LIGHTING)
                assert confirmation_code is not None

                # Wait for confirmation
                await asyncio.sleep(0.3)

                # Verify we received a confirmation
                assert len(confirmations_received) > 0
                code, success = confirmations_received[0]
                assert success is True  # Should be successful

            finally:
                if protocol._transport:
                    protocol._transport.close()

    @pytest.mark.asyncio
    async def test_multiple_confirmations(self):
        """Test handling multiple confirmations."""
        async with simulator_context() as simulator:
            protocol = await simulator.create_protocol_client(timesync_frequency=0)

            try:
                confirmations_received = []

                def track_confirmation(code, success):
                    confirmations_received.append((code, success))

                protocol.on_confirmation = track_confirmation

                # Send multiple commands
                for i in range(5):
                    await protocol.lighting_group_on(i + 1, Application.LIGHTING)
                    await asyncio.sleep(0.05)

                # Wait for confirmations
                await asyncio.sleep(0.5)

                # Should have received confirmations
                assert len(confirmations_received) >= 3  # At least some confirmations

            finally:
                if protocol._transport:
                    protocol._transport.close()


class TestSimulatorMultipleClients:
    """Test multiple simultaneous clients."""

    @pytest.mark.asyncio
    async def test_two_clients_simultaneously(self):
        """Test that simulator handles two clients at once."""
        async with simulator_context() as simulator:
            # Create two clients
            protocol1 = await simulator.create_protocol_client(timesync_frequency=0)
            protocol2 = await simulator.create_protocol_client(timesync_frequency=0)

            try:
                # Both clients send commands
                code1 = await protocol1.lighting_group_on(1, Application.LIGHTING)
                code2 = await protocol2.lighting_group_on(2, Application.LIGHTING)

                assert code1 is not None
                assert code2 is not None

                await asyncio.sleep(0.2)

                # Both should still be connected
                assert protocol1._transport is not None
                assert protocol2._transport is not None

            finally:
                if protocol1._transport:
                    protocol1._transport.close()
                if protocol2._transport:
                    protocol2._transport.close()


class TestSimulatorStability:
    """Test simulator stability and error handling."""

    @pytest.mark.asyncio
    async def test_rapid_connect_disconnect(self):
        """Test rapid connection/disconnection cycles."""
        async with simulator_context() as simulator:
            for i in range(10):
                reader, writer = await simulator.create_client_connection()
                writer.close()
                await writer.wait_closed()

            # Simulator should still be running
            assert simulator.is_running

    @pytest.mark.asyncio
    async def test_connection_after_client_disconnect(self):
        """Test that new clients can connect after others disconnect."""
        async with simulator_context() as simulator:
            # Connect and disconnect first client
            protocol1 = await simulator.create_protocol_client(timesync_frequency=0)
            if protocol1._transport:
                protocol1._transport.close()

            await asyncio.sleep(0.1)

            # Connect second client
            protocol2 = await simulator.create_protocol_client(timesync_frequency=0)

            try:
                # Second client should work fine
                code = await protocol2.lighting_group_on(1, Application.LIGHTING)
                assert code is not None

            finally:
                if protocol2._transport:
                    protocol2._transport.close()

    @pytest.mark.asyncio
    async def test_many_rapid_commands(self):
        """Test sending many commands rapidly."""
        async with simulator_context() as simulator:
            protocol = await simulator.create_protocol_client(timesync_frequency=0)

            try:
                # Send 50 commands rapidly
                for i in range(50):
                    group = (i % 10) + 1
                    if i % 2 == 0:
                        await protocol.lighting_group_on(group, Application.LIGHTING)
                    else:
                        await protocol.lighting_group_off(group, Application.LIGHTING)

                # Give time to process
                await asyncio.sleep(1.0)

                # Connection should still be alive
                assert protocol._transport is not None

            finally:
                if protocol._transport:
                    protocol._transport.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
