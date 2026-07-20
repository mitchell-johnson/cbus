#!/usr/bin/env python3
"""
Test utilities for C-Bus simulator integration.

This module provides utilities to easily start and use the C-Bus simulator
in test suites, enabling integration testing without physical hardware.
"""

import asyncio
import logging
import os
import signal
import time
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from cbus.protocol.pciprotocol import PCIProtocol

logger = logging.getLogger(__name__)


class SimulatorTestFixture:
    """
    A test fixture for running the C-Bus simulator.

    This class makes it easy to start/stop the simulator for tests and
    provides utilities for connecting clients.
    """

    def __init__(self, host: str = '127.0.0.1', port: int = 0, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the simulator fixture.

        Args:
            host: Host address to bind to (default: 127.0.0.1 for tests)
            port: Port to listen on (0 = auto-assign free port)
            config: Optional configuration dict for simulator state
        """
        self.host = host
        self.requested_port = port
        self.actual_port: Optional[int] = None
        self.config = config or self._get_default_config()
        self.server = None
        self.server_task: Optional[asyncio.Task] = None
        self._clients = []
        self._is_running = False

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default test configuration."""
        return {
            "device": {
                "type": "5500CN",
                "serial_number": "TEST0001",
                "firmware_version": "1.0.0-test"
            },
            "networks": [{
                "network_id": 254,
                "name": "Test Network",
                "applications": [{
                    "application_id": 56,
                    "name": "Lighting",
                    "groups": [
                        {"group_id": i, "name": f"Test Light {i}", "initial_level": 0}
                        for i in range(1, 11)  # 10 test lights
                    ]
                }]
            }],
            "simulation": {
                "smart_mode": True,
                "delay_min_ms": 1,  # Fast for tests
                "delay_max_ms": 5,  # Fast for tests
                "packet_loss_probability": 0.0  # No packet loss in tests
            }
        }

    async def start(self, timeout: float = 5.0) -> None:
        """
        Start the simulator server.

        Args:
            timeout: Maximum time to wait for server to start (seconds)

        Raises:
            TimeoutError: If server doesn't start within timeout
            RuntimeError: If server fails to start
        """
        if self._is_running:
            logger.warning("Simulator already running")
            return

        # Import here to avoid circular dependencies
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cbus-simulator'))
        from simulator.server import CBusSimulatorServer
        from simulator.state import SimulatorState

        # Create state with config
        state = SimulatorState()
        if self.config:
            state.apply_configuration(self.config)

        # Create server
        from simulator.protocol import PCISimulatorProtocol

        async def client_handler(reader, writer):
            protocol = PCISimulatorProtocol(reader, writer, state)
            self._clients.append(protocol)
            try:
                await protocol.process_client()
            finally:
                if protocol in self._clients:
                    self._clients.remove(protocol)

        # Start server
        try:
            self.server = await asyncio.start_server(
                client_handler,
                self.host,
                self.requested_port
            )

            # Get actual port (important when port=0 for auto-assign)
            sockets = self.server.sockets
            if sockets:
                self.actual_port = sockets[0].getsockname()[1]
            else:
                raise RuntimeError("Server has no sockets")

            self._is_running = True
            logger.info(f"Simulator started on {self.host}:{self.actual_port}")

            # Start serving in background
            self.server_task = asyncio.create_task(self.server.serve_forever())

            # Wait a bit for server to be ready
            await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"Failed to start simulator: {e}")
            await self.stop()
            raise RuntimeError(f"Simulator failed to start: {e}") from e

    async def stop(self, timeout: float = 2.0) -> None:
        """
        Stop the simulator server.

        Args:
            timeout: Maximum time to wait for graceful shutdown (seconds)
        """
        if not self._is_running:
            return

        logger.info("Stopping simulator...")
        self._is_running = False

        # Close all client connections
        for client in list(self._clients):
            try:
                client.writer.close()
                await asyncio.wait_for(client.writer.wait_closed(), timeout=1.0)
            except Exception as e:
                logger.debug(f"Error closing client: {e}")

        self._clients.clear()

        # Cancel server task
        if self.server_task and not self.server_task.done():
            self.server_task.cancel()
            try:
                await asyncio.wait_for(self.server_task, timeout=timeout)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # Close server
        if self.server:
            self.server.close()
            try:
                await asyncio.wait_for(self.server.wait_closed(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("Server close timed out")

        logger.info("Simulator stopped")

    async def create_client_connection(self) -> tuple:
        """
        Create a client connection to the simulator.

        Returns:
            Tuple of (reader, writer) for the connection

        Raises:
            RuntimeError: If simulator is not running
        """
        if not self._is_running or self.actual_port is None:
            raise RuntimeError("Simulator is not running")

        reader, writer = await asyncio.open_connection(self.host, self.actual_port)
        return reader, writer

    async def create_protocol_client(self, **protocol_kwargs) -> PCIProtocol:
        """
        Create and connect a PCIProtocol client to the simulator.

        Args:
            **protocol_kwargs: Arguments to pass to PCIProtocol constructor

        Returns:
            Connected PCIProtocol instance

        Raises:
            RuntimeError: If simulator is not running
        """
        if not self._is_running or self.actual_port is None:
            raise RuntimeError("Simulator is not running")

        loop = asyncio.get_event_loop()
        connection_lost_future = loop.create_future()

        protocol = PCIProtocol(
            connection_lost_future=connection_lost_future,
            **protocol_kwargs
        )

        transport, _ = await loop.create_connection(
            lambda: protocol,
            self.host,
            self.actual_port
        )

        # Give connection time to establish
        await asyncio.sleep(0.1)

        return protocol

    @property
    def is_running(self) -> bool:
        """Check if simulator is running."""
        return self._is_running

    @property
    def address(self) -> tuple:
        """Get simulator address as (host, port) tuple."""
        return (self.host, self.actual_port or 0)


@asynccontextmanager
async def simulator_context(host: str = '127.0.0.1', port: int = 0,
                           config: Optional[Dict[str, Any]] = None):
    """
    Context manager for running the simulator in tests.

    Example:
        async with simulator_context() as simulator:
            protocol = await simulator.create_protocol_client()
            await protocol.lighting_group_on(1, Application.LIGHTING)
            await protocol.lighting_group_off(1, Application.LIGHTING)

    Args:
        host: Host address to bind to
        port: Port to listen on (0 = auto-assign)
        config: Optional configuration for simulator

    Yields:
        SimulatorTestFixture instance
    """
    simulator = SimulatorTestFixture(host, port, config)
    try:
        await simulator.start()
        yield simulator
    finally:
        await simulator.stop()


async def wait_for_simulator_ready(host: str, port: int, timeout: float = 5.0) -> bool:
    """
    Wait for simulator to be ready to accept connections.

    Args:
        host: Simulator host
        port: Simulator port
        timeout: Maximum time to wait (seconds)

    Returns:
        True if simulator is ready, False if timeout
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.close()
            await writer.wait_closed()
            return True
        except (ConnectionRefusedError, OSError):
            await asyncio.sleep(0.1)
    return False
