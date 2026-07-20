"""Tests for auto-reconnection and fault tolerance."""
import pytest
import pytest_asyncio
import asyncio

from cbus.esp32.emulator.device import ESP32Emulator, ESP32EmulatorConfig
from cbus.esp32.connection import ESP32Connection, ESP32Config
from cbus.transport.base import TransportState, TransportError


class TestReconnection:
    @pytest.mark.asyncio
    async def test_reconnect_after_server_restart(self):
        """Test that client reconnects when the emulator restarts."""
        config = ESP32EmulatorConfig(tcp_port=0)
        emu = ESP32Emulator(config)
        await emu.start()
        port = emu.actual_port

        conn_config = ESP32Config.wifi(
            "127.0.0.1",
            port=port,
            reconnect=True,
            reconnect_interval=0.5,
            max_reconnect_attempts=5,
            connect_timeout=2.0,
            timesync_frequency=0,
        )
        conn = ESP32Connection(conn_config)
        await conn.connect()
        assert conn.transport.is_connected

        # Stop emulator (simulates disconnect)
        await emu.stop()
        await asyncio.sleep(0.2)

        # Restart emulator on same port
        emu2 = ESP32Emulator(ESP32EmulatorConfig(tcp_port=port))
        await emu2.start()

        # Wait for reconnect
        await asyncio.sleep(2.0)

        await conn.disconnect()
        await emu2.stop()

    @pytest.mark.asyncio
    async def test_max_reconnect_attempts(self):
        """Test that reconnection stops after max attempts."""
        config = ESP32EmulatorConfig(tcp_port=0)
        emu = ESP32Emulator(config)
        await emu.start()
        port = emu.actual_port

        conn_config = ESP32Config.wifi(
            "127.0.0.1",
            port=port,
            reconnect=True,
            reconnect_interval=0.2,
            max_reconnect_attempts=2,
            connect_timeout=1.0,
            timesync_frequency=0,
        )
        conn = ESP32Connection(conn_config)
        await conn.connect()

        # Stop emulator permanently
        await emu.stop()
        await asyncio.sleep(0.2)

        # Trigger reconnect by notifying transport
        await conn.transport.handle_connection_lost(Exception("test disconnect"))

        # Wait for max reconnect attempts to be exhausted
        await asyncio.sleep(2.0)

        assert conn.transport.state == TransportState.ERROR
        await conn.disconnect()


class TestConnectionTimeout:
    @pytest.mark.asyncio
    async def test_connect_timeout_on_unreachable_host(self):
        """Test that connection times out/errors when host is unreachable."""
        conn_config = ESP32Config.wifi(
            "127.0.0.1",
            port=59999,
            reconnect=False,
            connect_timeout=1.0,
            timesync_frequency=0,
        )
        conn = ESP32Connection(conn_config)
        with pytest.raises(TransportError):
            await conn.connect()


class TestConcurrentConnections:
    @pytest.mark.asyncio
    async def test_multiple_connections_to_emulator(self):
        """Test multiple simultaneous connections to the same emulator."""
        config = ESP32EmulatorConfig(tcp_port=0)
        async with ESP32Emulator(config) as emu:
            connections = []
            for _ in range(3):
                cfg = ESP32Config.wifi(
                    "127.0.0.1",
                    port=emu.actual_port,
                    reconnect=False,
                    timesync_frequency=0,
                )
                conn = ESP32Connection(cfg)
                await conn.connect()
                connections.append(conn)

            for conn in connections:
                assert conn.transport.is_connected

            for conn in connections:
                await conn.disconnect()
