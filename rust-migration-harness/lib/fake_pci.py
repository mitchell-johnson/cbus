"""Scripted fake C-Bus PCI (TCP server) for the behavioral suite.

Pure stdlib. Accepts a single cmqttd connection, records every frame the
client sends, auto-acknowledges confirmation codes (like a real PCI in
smart mode), and lets the test inject raw server->client wire bytes.

Optionally withholds the confirmation for the first confirmed frame of
any kind, to exercise the client's retransmission logic. (Status
requests are sent without confirmation chars, so the first confirmed
frame is typically an MQTT-command or clock-update frame.)
"""
import asyncio
import time
from typing import List, Optional

from wire import ClientFrame, split_client_frames


class RecordedFrame:
    def __init__(self, frame: ClientFrame):
        self.frame = frame
        self.ts = time.monotonic()

    @property
    def payload(self) -> str:
        return self.frame.payload

    @property
    def conf(self) -> Optional[bytes]:
        return self.frame.conf


class FakePCI:
    def __init__(self, host='127.0.0.1', port=0,
                 withhold_first_conf=False):
        self._host = host
        self._port = port
        self._server: Optional[asyncio.AbstractServer] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self.frames: List[RecordedFrame] = []
        self.reset_count = 0
        self.smart_connect_count = 0
        self.connections = 0
        self._withhold_first_conf = withhold_first_conf
        self._withheld: Optional[tuple] = None  # (payload, conf)
        self.withheld_seen = 0

    @property
    def port(self) -> int:
        return self._server.sockets[0].getsockname()[1]

    async def start(self):
        self._server = await asyncio.start_server(
            self._on_client, self._host, self._port)

    async def stop(self):
        if self._writer is not None:
            self._writer.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _on_client(self, reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter):
        self.connections += 1
        self._writer = writer
        buf = bytearray()
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                buf.extend(data)
                for f in split_client_frames(buf):
                    self._handle_frame(f, writer)
        except (ConnectionResetError, asyncio.CancelledError):
            pass

    def _handle_frame(self, f: ClientFrame, writer: asyncio.StreamWriter):
        rec = RecordedFrame(f)
        self.frames.append(rec)
        if f.is_reset:
            self.reset_count += 1
            return
        if f.is_smart_connect:
            self.smart_connect_count += 1
            return
        if f.conf is not None:
            if self._withhold_first_conf and self._withheld is None:
                # withhold this one; count repeats of the exact same frame
                self._withheld = (f.payload, f.conf)
                self.withheld_seen = 1
                return
            if self._withheld is not None \
                    and (f.payload, f.conf) == self._withheld:
                self.withheld_seen += 1
                return  # keep withholding: client should retry then abandon
            # ordinary confirmation: `<code>.` with no CR/LF (s4.3.3.3)
            writer.write(f.conf + b'.')

    def inject(self, wire_bytes: bytes):
        """Write raw server->client bytes (a from-PCI frame incl CRLF)."""
        if self._writer is None:
            raise RuntimeError('no client connected')
        self._writer.write(wire_bytes)

    # ---- query helpers ---------------------------------------------------
    def payloads(self) -> List[str]:
        return [r.payload for r in self.frames
                if not r.frame.is_reset and not r.frame.is_smart_connect]

    def count_payload(self, payload: str) -> int:
        return sum(1 for r in self.frames if r.payload == payload)
