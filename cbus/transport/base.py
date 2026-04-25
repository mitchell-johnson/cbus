"""Abstract transport layer for C-Bus connections.

Provides a common interface for different connection methods (TCP, Serial)
with built-in reconnection, state management, and health monitoring.
"""
import abc
import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class TransportState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class TransportError(Exception):
    pass


class ConnectionTimeoutError(TransportError):
    pass


@dataclass
class TransportConfig:
    reconnect: bool = True
    reconnect_interval: float = 5.0
    max_reconnect_attempts: int = 0  # 0 = unlimited
    connect_timeout: float = 10.0
    heartbeat_interval: float = 30.0


class CBusTransport(abc.ABC):
    """Abstract base class for C-Bus transport connections."""

    def __init__(self, config: Optional[TransportConfig] = None):
        self._config = config or TransportConfig()
        self._state = TransportState.DISCONNECTED
        self._asyncio_transport: Optional[asyncio.Transport] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._reconnect_attempts = 0
        self._connect_lock: Optional[asyncio.Lock] = None
        self.on_state_change: Optional[Callable] = None
        self.on_connection_lost: Optional[Callable] = None

    @property
    def state(self) -> TransportState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == TransportState.CONNECTED

    @property
    def config(self) -> TransportConfig:
        return self._config

    @property
    @abc.abstractmethod
    def transport_type(self) -> str:
        """Return a string identifying this transport type (e.g. 'tcp', 'serial')."""

    @property
    @abc.abstractmethod
    def connection_info(self) -> Dict[str, Any]:
        """Return a dict of connection details for logging/diagnostics."""

    def _set_state(self, new_state: TransportState):
        old_state = self._state
        if old_state == new_state:
            return
        self._state = new_state
        logger.info("Transport state: %s -> %s", old_state.value, new_state.value)
        if self.on_state_change:
            try:
                self.on_state_change(old_state, new_state)
            except Exception:
                logger.exception("Error in on_state_change callback")

    async def connect(self):
        if self._connect_lock is None:
            self._connect_lock = asyncio.Lock()
        async with self._connect_lock:
            if self._state == TransportState.CONNECTED:
                return
            self._set_state(TransportState.CONNECTING)
            try:
                self._asyncio_transport = await asyncio.wait_for(
                    self._do_connect(), timeout=self._config.connect_timeout
                )
                self._reconnect_attempts = 0
                self._set_state(TransportState.CONNECTED)
            except asyncio.CancelledError:
                self._set_state(TransportState.DISCONNECTED)
                raise
            except asyncio.TimeoutError:
                self._set_state(TransportState.ERROR)
                raise ConnectionTimeoutError(
                    f"Connection timed out after {self._config.connect_timeout}s"
                )
            except Exception as e:
                self._set_state(TransportState.ERROR)
                raise TransportError(f"Connection failed: {e}") from e

    async def disconnect(self):
        if self._state == TransportState.DISCONNECTED:
            return
        # Cancel reconnect task first
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None
        # Set state before _do_disconnect so reconnect loop sees DISCONNECTED
        self._set_state(TransportState.DISCONNECTED)
        try:
            await self._do_disconnect()
        finally:
            self._asyncio_transport = None

    async def handle_connection_lost(self, exc: Optional[Exception] = None):
        logger.warning("Connection lost: %s", exc)
        self._asyncio_transport = None
        if self.on_connection_lost:
            try:
                self.on_connection_lost(exc)
            except Exception:
                logger.exception("Error in on_connection_lost callback")
        if self._config.reconnect and self._state != TransportState.DISCONNECTED:
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        self._set_state(TransportState.RECONNECTING)
        while self._state == TransportState.RECONNECTING:
            self._reconnect_attempts += 1
            if (
                self._config.max_reconnect_attempts > 0
                and self._reconnect_attempts > self._config.max_reconnect_attempts
            ):
                logger.error(
                    "Max reconnect attempts (%d) reached",
                    self._config.max_reconnect_attempts,
                )
                self._set_state(TransportState.ERROR)
                return
            logger.info(
                "Reconnect attempt %d (max=%s) in %.1fs",
                self._reconnect_attempts,
                self._config.max_reconnect_attempts or "unlimited",
                self._config.reconnect_interval,
            )
            try:
                await asyncio.sleep(self._config.reconnect_interval)
            except asyncio.CancelledError:
                return
            # Check state again after sleep (disconnect may have been called)
            if self._state == TransportState.DISCONNECTED:
                return
            try:
                await self.connect()
                logger.info("Reconnected successfully")
                return
            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning(
                    "Reconnect attempt %d failed", self._reconnect_attempts
                )

    @abc.abstractmethod
    async def _do_connect(self) -> Any:
        """Establish the underlying connection. Return the asyncio transport."""

    @abc.abstractmethod
    async def _do_disconnect(self):
        """Tear down the underlying connection."""

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
