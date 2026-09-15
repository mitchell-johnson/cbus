"""Bounded synchronous C-Gate command transport.

Frames follow the C-Gate Manual section 4.3.1.5. A space, including on a
1xx response, terminates a reply; a hyphen continues it. Commands are tagged
so asynchronous events cannot accidentally complete a command. No command
is retried automatically: a timeout or framing failure closes the connection.
"""
from __future__ import annotations

import math
import re
import socket
import ssl
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass


_STATUS = re.compile(r"^([1-6][0-9]{2})([- ])(.*)$")
_TAG = re.compile(r"^\[([^]\r\n]+)\] ?(.*)$")
_EVENT = re.compile(r"^(?:#[esc]#(?: |$)|[0-9]{8}-[0-9]{6}(?:\.[0-9]{3})? [789][0-9]{2} )")
_OVERFLOW = "###!!!Event buffer overflow. Events have been missed.!!!###"


@dataclass(frozen=True)
class CGateResponse:
    """Reply lines have their command tag removed but retain status prefixes."""

    lines: tuple[str, ...]
    final: str
    status: int

    @property
    def code(self) -> int:
        return self.status

    @property
    def successful(self) -> bool:
        return 100 <= self.status < 400


class CGateError(RuntimeError):
    """A complete server error reply; the connection remains synchronized."""

    def __init__(self, response: CGateResponse):
        self.response = response
        super().__init__(f"C-Gate error: {response.final}")


class CGateClient:
    """One command at a time over a persistent TCP or verified TLS connection.

    Enter a context or call connect() before command(). Interleaved event
    strings are available in events; read_event() also waits for new events.
    An overflow marker is queued and sets events_lost. Application errors
    (4xx/5xx) raise CGateError with the complete response attached.
    """

    def __init__(self, host: str, port: int = 20023, timeout: float = 10.0,
                 ssl_context: ssl.SSLContext | None = None, *,
                 max_line_bytes: int = 1024 * 1024,
                 max_response_bytes: int = 16 * 1024 * 1024,
                 max_response_lines: int = 100000, max_events: int = 4096):
        if not isinstance(host, str) or not host:
            raise ValueError("C-Gate host is required")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("C-Gate port must be in 1..65535")
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("C-Gate timeout must be positive and finite")
        for limit in (max_line_bytes, max_response_bytes, max_response_lines, max_events):
            if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                raise ValueError("C-Gate limits must be positive integers")
        self.host, self.port, self.timeout = host, port, float(timeout)
        self.ssl_context = ssl_context
        self.max_line_bytes, self.max_response_bytes = max_line_bytes, max_response_bytes
        self.max_response_lines, self.max_events = max_response_lines, max_events
        self.events: deque[str] = deque()
        self.events_lost = False
        self.greeting: str | None = None
        self._socket: socket.socket | None = None
        self._buffer = bytearray()
        self._sequence = 0
        self._lock = threading.RLock()

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def connect(self) -> CGateClient:
        with self._lock:
            if self.connected:
                return self
            deadline = time.monotonic() + self.timeout
            try:
                self._socket = socket.create_connection((self.host, self.port), self.timeout)
                if self.ssl_context is not None:
                    self._set_timeout(deadline)
                    self._socket = self.ssl_context.wrap_socket(self._socket, server_hostname=self.host)
                greeting = self._readline(deadline)
                if not greeting.startswith("201 "):
                    raise RuntimeError("C-Gate did not send a 201 service-ready greeting")
                self.greeting = greeting
                return self
            except (OSError, RuntimeError) as exc:
                if isinstance(exc, RuntimeError):
                    self._close_preserving(exc)
                    raise
                error = RuntimeError("Unable to establish C-Gate connection")
                self._close_preserving(error)
                raise error from None
            except BaseException as exc:
                # Cancellation can interrupt a greeting or TLS negotiation.
                # Invalidate the stream without replacing the interruption.
                self._close_preserving(exc)
                raise

    def __enter__(self) -> CGateClient:
        return self.connect()

    def __exit__(self, _type, error, _traceback) -> None:
        if error is None:
            self.close()
        else:
            self._close_preserving(error)

    def _close_preserving(self, error: BaseException) -> None:
        """Invalidate the stream and retain secondary cleanup failures."""
        try:
            self.close()
        except BaseException as cleanup:
            failures = tuple(getattr(error, "cgate_cleanup_errors", ()))
            error.cgate_cleanup_errors = failures + (cleanup,)

    def close(self) -> None:
        with self._lock:
            sock, self._socket = self._socket, None
            self._buffer.clear()
            if sock is not None:
                sock.close()

    def _set_timeout(self, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("C-Gate operation timed out; connection closed; outcome may be unknown")
        if self._socket is None:
            raise RuntimeError("C-Gate is not connected; call connect() explicitly")
        self._socket.settimeout(remaining)

    def _readline(self, deadline: float) -> str:
        while True:
            self._set_timeout(deadline)
            pos = self._buffer.find(b"\n")
            if pos >= 0:
                # Native C-Gate DBGETXML mixes LF-only XML lines with CRLF
                # status lines. Both terminate a line; embedded CR is invalid.
                end = pos - 1 if pos and self._buffer[pos - 1] == 13 else pos
                if end > self.max_line_bytes:
                    raise RuntimeError("C-Gate line exceeded configured limit")
                raw = bytes(self._buffer[:end])
                del self._buffer[:pos + 1]
                if b"\r" in raw or b"\x00" in raw:
                    raise RuntimeError("C-Gate line contains invalid control characters")
                try:
                    return raw.decode("utf-8", errors="strict")
                except UnicodeDecodeError:
                    raise RuntimeError("C-Gate sent invalid UTF-8 text") from None
            if len(self._buffer) > self.max_line_bytes + 1:
                raise RuntimeError("C-Gate line exceeded configured limit")
            assert self._socket is not None
            try:
                chunk = self._socket.recv(min(65536, self.max_line_bytes + 2))
            except (TimeoutError, socket.timeout):
                raise RuntimeError("C-Gate operation timed out; connection closed; outcome may be unknown") from None
            if not chunk:
                raise RuntimeError("C-Gate connection ended before a complete reply; outcome may be unknown")
            self._buffer.extend(chunk)

    def _queue_event(self, line: str) -> bool:
        if line == _OVERFLOW or _EVENT.match(line):
            if len(self.events) >= self.max_events:
                self.events_lost = True
                raise RuntimeError("C-Gate event queue exceeded configured limit")
            self.events.append(line)
            if line == _OVERFLOW:
                self.events_lost = True
            return True
        return False

    def command(self, command: str) -> CGateResponse:
        """Execute one command, returning its complete reply or raising RuntimeError.

        LOGIN reply text is redacted because some servers echo authentication
        arguments. Invalid input is rejected before any bytes are sent.
        """
        return self._command(command)

    def command_document(self, command: str, document: str) -> CGateResponse:
        """Send one C-Gate here document under the command's response ID.

        Only documented document-consuming commands are allowed: an ordinary
        command would otherwise interpret document lines as more commands.
        Limits and the whole document are checked before any bytes are sent.
        """
        if not isinstance(command, str) or not re.fullmatch(
                r"(?:CGL IMPORT|DBSETXML) [^\s<>]+", command, re.IGNORECASE):
            raise ValueError("Document command must be CGL IMPORT project or DBSETXML path")
        if not isinstance(document, str) or not document:
            raise ValueError("C-Gate document must be nonempty text")
        document = document.replace("\r\n", "\n")
        if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in document):
            raise ValueError("C-Gate document contains invalid control characters")
        try:
            body = document.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("C-Gate document contains invalid Unicode") from None
        if len(body) > self.max_response_bytes:
            raise ValueError("C-Gate document exceeded configured byte limit")
        if any(len(line) > self.max_line_bytes for line in body.split(b"\n")):
            raise ValueError("C-Gate document exceeded configured line limit")
        delimiter = "CBUS_END_" + uuid.uuid4().hex
        while delimiter in document.splitlines():
            delimiter = "CBUS_END_" + uuid.uuid4().hex
        # The server compares the end tag exactly and adds LF to body lines.
        body = body + (b"" if body.endswith(b"\n") else b"\n")
        return self._command(command + " << " + delimiter,
                             body + delimiter.encode("ascii") + b"\r\n")

    def _command(self, command: str, document_wire: bytes = b"") -> CGateResponse:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("C-Gate command must be a nonempty string")
        if any(ord(c) < 32 and c != "\t" or ord(c) == 127 for c in command):
            raise ValueError("C-Gate command must be a single line without control characters")
        command = command.strip()
        if command.startswith("["):
            raise ValueError("C-Gate command IDs are assigned by the client")
        try:
            encoded = command.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("C-Gate command contains invalid Unicode") from None
        sensitive = command.split(None, 1)[0].upper() == "LOGIN"
        with self._lock:
            if not self.connected:
                raise RuntimeError("C-Gate is not connected; call connect() explicitly")
            tag = str(self._sequence + 1)
            wire = b"[" + tag.encode("ascii") + b"] " + encoded
            if len(wire) > self.max_line_bytes:
                raise ValueError("C-Gate command exceeded configured line limit")
            self._sequence += 1
            deadline = time.monotonic() + self.timeout
            lines: list[str] = []
            size = 0
            try:
                self._set_timeout(deadline)
                assert self._socket is not None
                self._socket.sendall(wire + b"\r\n" + document_wire)
                while True:
                    line = self._readline(deadline)
                    if self._queue_event(line):
                        continue
                    match = _TAG.match(line)
                    if match is None or match[1] != tag:
                        raise RuntimeError("C-Gate reply has an unexpected or missing command ID")
                    payload = match[2]
                    size += len(line.encode("utf-8")) + 2
                    if size > self.max_response_bytes or len(lines) >= self.max_response_lines:
                        raise RuntimeError("C-Gate response exceeded configured limit")
                    status = _STATUS.match(payload)
                    if status is None and not lines:
                        raise RuntimeError("C-Gate reply did not begin with a status code")
                    # Native DBGETXML emits tagged XML payload lines between its
                    # opening continuation and final status line.
                    if sensitive:
                        payload = (payload[:4] if status else "") + "[redacted]"
                    lines.append(payload)
                    if status is not None and status[2] == " ":
                        response = CGateResponse(tuple(lines), payload, int(status[1]))
                        break
            except (OSError, RuntimeError) as exc:
                if isinstance(exc, RuntimeError):
                    self._close_preserving(exc)
                    raise
                if isinstance(exc, (TimeoutError, socket.timeout)):
                    error = RuntimeError("C-Gate operation timed out; connection closed; outcome may be unknown")
                else:
                    error = RuntimeError("C-Gate transport failed; connection closed; outcome may be unknown")
                self._close_preserving(error)
                raise error from None
            except BaseException as exc:
                # A cancelled send/read may already have reached the server.
                # A late response must never satisfy another command.
                self._close_preserving(exc)
                raise
            if 400 <= response.status < 600:
                raise CGateError(response)
            return response

    def read_event(self) -> str:
        """Return a queued event or wait up to timeout for one on this session.

        Subscribe first with the C-Gate EVENT command. Like command(), a timeout
        closes the stream. This client has no background event-reading thread.
        """
        with self._lock:
            if self.events:
                return self.events.popleft()
            deadline = time.monotonic() + self.timeout
            try:
                line = self._readline(deadline)
                if not self._queue_event(line):
                    raise RuntimeError("Unexpected command response while waiting for a C-Gate event")
                return self.events.popleft()
            except (OSError, RuntimeError) as exc:
                if isinstance(exc, RuntimeError):
                    self._close_preserving(exc)
                    raise
                error = RuntimeError("C-Gate event transport failed; connection closed")
                self._close_preserving(error)
                raise error from None
            except BaseException as exc:
                self._close_preserving(exc)
                raise
