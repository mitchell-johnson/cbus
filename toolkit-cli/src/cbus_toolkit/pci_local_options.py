"""Read-only, bounded observation of the explicitly known local PCI option byte.

This narrow reader never changes options. It attributes a bare local RECALL
reply only to the caller's explicitly owned endpoint and local address.
"""
from __future__ import annotations

from dataclasses import dataclass
import socket
import threading
import time

from .pci import Confirmation, Frame, FrameStream, RecallCAL, ReplyCAL, encode_command
from .pci_serial_address_transport import PCISerialAddressTransport


def parse_local_options(data, *, local_unit):
    """Parse a whole capture: one successful g confirmation then one bare 82 CAL.

    Routed/extended replies, prefixes, extra frames and partial tails are outside
    this first proven local-only scope. A byte value says nothing about identity.
    """
    if type(local_unit) is not int or not 0 <= local_unit <= 255:
        raise ValueError('local_unit must be an integer in 0..255')
    if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) > 4096:
        raise ValueError('Local options capture must be at most 4096 bytes')
    stream = FrameStream(max_buffer=4096)
    events = []
    for byte in bytes(data): events.extend(stream.feed(bytes([byte])))
    if stream.buffer or len(events) != 2:
        raise ValueError('Local options require one whole confirmation and one whole reply')
    ack, frame = events
    if not isinstance(ack, Confirmation) or ack.code != b'g' or ack.status != '.':
        raise ValueError('Local options require the successful expected confirmation first')
    if not isinstance(frame, Frame) or not frame.bare or len(frame.cals) != 1:
        raise ValueError('Only the proven bare local RECALL reply is supported')
    cal = frame.cals[0]
    if (any(byte not in b'0123456789abcdefABCDEF' for byte in frame.raw) or
            not isinstance(cal, ReplyCAL) or cal.parameter != 66 or len(cal.data) != 1):
        raise ValueError('Local options require exactly parameter 66 and one byte')
    return cal.data[0]


@dataclass(frozen=True)
class LocalOptionsObservation:
    local_unit: int
    request: bytes
    received: bytes
    value: int | None
    send_attempted: bool
    capture_complete: bool
    termination: str
    connection_closed: bool
    errors: tuple[dict, ...]
    elapsed: float | None
    response_timeout: float
    overall_timeout: float

    @property
    def complete(self):
        return self.capture_complete and self.connection_closed and not self.errors and self.value is not None

    def as_dict(self):
        return {'format': 'cbus-pci-local-options-observation-v1', 'local_unit': self.local_unit,
                'request_hex': self.request.hex(), 'received_hex': self.received.hex(), 'value': self.value,
                'send_attempted': self.send_attempted, 'capture_complete': self.capture_complete,
                'complete': self.complete, 'termination': self.termination,
                'connection_closed': self.connection_closed, 'errors': [dict(x) for x in self.errors],
                'timing': {'elapsed_seconds': self.elapsed, 'response_timeout_seconds': self.response_timeout,
                           'overall_timeout_seconds': self.overall_timeout},
                'bare_reply_attribution': 'caller_owned_explicit_local_endpoint',
                'identity_verified': False, 'options_changed': False, 'automatic_retries': 0}


class PCILocalOptionsReader:
    """One fresh numeric-IP RECALL66 session; fixed whole window, no retry/write."""

    def __init__(self, host, port=10001, *, local_unit, response_timeout=2.0,
                 overall_timeout=5.0, command_checksum=False):
        # Share only pure endpoint/bound validation, never a mutation exchange.
        validator = PCISerialAddressTransport(host, port, local_unit=local_unit,
            response_timeout=response_timeout, overall_timeout=overall_timeout,
            command_checksum=command_checksum)
        self.host, self.port, self.local_unit = validator.host, validator.port, validator.local_unit
        self._family = validator._family
        self.response_timeout, self.overall_timeout = validator.response_timeout, validator.overall_timeout
        self.command_checksum = command_checksum
        self._absolute_deadline = None
        self._lock, self._used, self.last_observation = threading.Lock(), False, None

    def _make_socket(self): return socket.socket(self._family, socket.SOCK_STREAM)

    def read_options(self):
        with self._lock:
            if self._used: raise RuntimeError('Local options reader is one-shot')
            self._used = True
            return self._read()

    def _read(self):
        import math
        request = encode_command(self.local_unit, RecallCAL(66, 1), confirmation=b'g', checksum=self.command_checksum)
        started = last = None
        sock, closed, attempted, complete = None, True, False, False
        received, errors, value, first = bytearray(), [], None, None
        termination, phase = 'not_started', 'initial_clock'

        def clock():
            nonlocal last
            last = time.monotonic()
            return last

        def failure(error, at):
            nonlocal first
            errors.append({'phase': at, 'type': type(error).__name__, 'message': str(error)})
            if first is None and not isinstance(error, (OSError, TimeoutError, ValueError)):
                first = error

        try:
            started = clock(); deadline = started + self.overall_timeout
            if self._absolute_deadline is not None:
                if (isinstance(self._absolute_deadline, bool) or not isinstance(self._absolute_deadline, (int, float))
                        or not math.isfinite(self._absolute_deadline)):
                    raise ValueError('Internal absolute deadline must be finite')
                deadline = min(deadline, self._absolute_deadline)
            if clock() >= deadline: termination = 'overall_timeout'
            else:
                phase = 'socket_creation'; sock = self._make_socket(); closed = False
                if deadline - clock() <= 0: termination = 'overall_timeout'
                else:
                    phase = 'connect'; sock.settimeout(deadline-last)
                    if clock() >= deadline: termination = 'overall_timeout'
                    else:
                        endpoint = (self.host, self.port, 0, 0) if self._family == socket.AF_INET6 else (self.host, self.port)
                        sock.connect(endpoint)
                        if deadline - clock() <= self.response_timeout: termination = 'insufficient_response_budget'
                        else:
                            phase = 'send'; sock.settimeout(deadline-last)
                            if deadline - clock() <= self.response_timeout: termination = 'insufficient_response_budget'
                            else:
                                attempted = True; sock.sendall(request)
                                end = clock() + self.response_timeout
                                if end >= deadline: termination = 'insufficient_response_budget'
                                else:
                                    phase = 'receive'; termination = 'collecting'
                                    while termination == 'collecting':
                                        now = clock()
                                        if now >= deadline: termination = 'overall_timeout'; break
                                        if now >= end: termination = 'response_window_elapsed'; complete = True; break
                                        sock.settimeout(min(end, deadline)-now)
                                        now = clock()
                                        if now >= deadline: termination = 'overall_timeout'; break
                                        if now >= end: termination = 'response_window_elapsed'; complete = True; break
                                        try: chunk = sock.recv(4097-len(received))
                                        except socket.timeout: continue
                                        # Retain data before the next interruptible clock call.
                                        received.extend(chunk)
                                        now = clock()
                                        if len(received) > 4096: termination = 'byte_limit'; break
                                        if now >= deadline: termination = 'overall_timeout'; break
                                        if now >= end: termination = 'late_data'; break
                                        if not chunk: termination = 'disconnected'; break
        except BaseException as error:
            failure(error, phase); termination = 'interrupted' if first is not None else 'transport_error'
        finally:
            if sock is not None:
                try: sock.close(); closed = True
                except BaseException as error: failure(error, 'close')
        try: value = parse_local_options(received[:4096], local_unit=self.local_unit)
        except BaseException as error: failure(error, 'parse')
        try: clock()
        except BaseException as error: failure(error, 'final_clock')
        result = LocalOptionsObservation(self.local_unit, request, bytes(received[:4096]), value,
            attempted, complete, termination, closed, tuple(errors),
            None if started is None or last is None else max(0., last-started),
            self.response_timeout, self.overall_timeout)
        self.last_observation = result
        if first is not None:
            first.pci_local_options_observation = result.as_dict()
            raise first
        return result
