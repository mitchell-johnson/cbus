"""Virtual serial port pair for ESP32 emulator serial testing.

Uses OS-level PTY (pseudo-terminal) to create a pair of linked serial ports.
One end acts as the "ESP32 device" and the other as the "client" port that
the cbus library connects to.
"""
import logging
import os
import pty
from typing import Optional

logger = logging.getLogger(__name__)


class VirtualSerialPair:
    """Creates a pair of linked virtual serial ports using PTY."""

    def __init__(self):
        self._master_fd: Optional[int] = None
        self._slave_fd: Optional[int] = None
        self._device_port: Optional[str] = None
        self._client_port: Optional[str] = None

    @property
    def device_port(self) -> Optional[str]:
        """Path to the device-side port (ESP32 emulator connects here)."""
        return self._device_port

    @property
    def client_port(self) -> Optional[str]:
        """Path to the client-side port (cbus library connects here)."""
        return self._client_port

    async def create(self):
        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd
        self._slave_fd = slave_fd
        # os.ttyname can fail on macOS for the master fd; use slave for client
        # and fall back to /dev/fd/N for the master side
        try:
            self._device_port = os.ttyname(master_fd)
        except OSError:
            self._device_port = f"/dev/fd/{master_fd}"
        try:
            self._client_port = os.ttyname(slave_fd)
        except OSError:
            self._client_port = f"/dev/fd/{slave_fd}"
        logger.info(
            "Virtual serial pair: device=%s, client=%s",
            self._device_port,
            self._client_port,
        )

    async def close(self):
        if self._master_fd is not None:
            os.close(self._master_fd)
            self._master_fd = None
        if self._slave_fd is not None:
            os.close(self._slave_fd)
            self._slave_fd = None
        self._device_port = None
        self._client_port = None
        logger.info("Virtual serial pair closed")

    async def __aenter__(self):
        await self.create()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
