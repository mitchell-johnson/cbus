"""One-shot IDENTIFY with explicit wire expectations, never cached identity inference."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import math
import socket
import threading
import time

from .pci import PCIRejected, ProtocolError, IdentifyCAL, ReplyCAL
from .pci_routing import RoutedCALCommand, ReceivedCALRoute, inspect_received_cal_route
from .pci_routed_recall import RoutedReplyPath, _Stream, _path, _integer, _copy, _error


@dataclass(frozen=True)
class RoutedIdentifyEvent:
    kind: str
    raw: bytes
    matched: bool
    status: str | None = None
    frame: ReceivedCALRoute | None = None

    def as_dict(self):
        value = {'kind': self.kind, 'raw_hex': self.raw.hex().upper(), 'matched': self.matched}
        if self.status is not None:
            value['status'] = self.status
        if self.frame is not None:
            value['frame'] = self.frame.as_dict()
        return value


@dataclass(frozen=True)
class RoutedIdentifyResult:
    command: RoutedCALCommand
    expected: RoutedReplyPath
    expected_count: int | None
    sent: bytes
    confirmation: bytes
    response: ReceivedCALRoute
    events: tuple[RoutedIdentifyEvent, ...]
    received_chunks: tuple[bytes, ...]

    @property
    def data(self):
        return self.response.cal.data

    def as_dict(self):
        return {'format': 'cbus-routed-identify-result-v1', 'complete': True,
                'sent_hex': self.sent.hex().upper(), 'confirmation': self.confirmation.decode('ascii'),
                'response': self.response.as_dict(), 'data_hex': self.data.hex().upper(),
                'expected': self.expected.as_dict(), 'expected_count': self.expected_count,
                'actual_count': len(self.data), 'original_typed_getter_used': False,
                'original_short_matcher_used': False, 'events': [v.as_dict() for v in self.events],
                'received_chunks_hex': [v.hex().upper() for v in self.received_chunks],
                'matches_declared_wire_expectation': True, 'confirmation_received': True,
                'response_received': True, 'request_sent_once': True,
                'completion_boundary': 'all bytes in the final received chunk processed',
                'raw_zero_address_ambiguous': self.command.unit == 0,
                'logical_network_resolved': False, 'device_origin_verified': False,
                'causal_freshness_verified': False, 'physical_delivery_verified': False,
                'original_cached_object_correlation_verified': False}


class RoutedIdentifyClient:
    """Own one socket and direct IDENTIFY; require confirmation and an exact path.

    Replies carry 0..30 raw data bytes; expected_count adds a caller constraint.
    Original typed getters and bare/full matcher fallback are not invoked.

    Stronger checksum/path/destination/dual-success policies are intentional.
    A supplied path is never promoted to an original logical network identity.
    No physical transport acceptance or implicit/flow-control framing is claimed.
    """
    def __init__(self, host, port=10001, *, timeout=5.0, command_checksum=False,
                 max_events=256, max_received_bytes=32768):
        if type(host) is not str or not 1 <= len(host) <= 45 or '%' in host:
            raise ValueError('host must be a numeric IPv4 or IPv6 address without a zone')
        address = ipaddress.ip_address(host)
        self.host = str(address)
        self.family = socket.AF_INET if address.version == 4 else socket.AF_INET6
        self.port = _integer(port, 'port', 1, 65535)
        if type(timeout) not in (int, float):
            raise ValueError('timeout must be finite and positive')
        try:
            timeout = float(timeout)
        except OverflowError as error:
            raise ValueError('timeout must be finite and positive') from error
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be finite and positive')
        if type(command_checksum) is not bool:
            raise ValueError('command_checksum must be a Boolean')
        self.timeout, self.command_checksum = timeout, command_checksum
        self.max_events = _integer(max_events, 'max_events', 1, 4096)
        self.max_received_bytes = _integer(max_received_bytes, 'max_received_bytes', 1, 1048576)
        self._used = False
        self._lock = threading.Lock()
        self.last_error = None
        self.last_evidence = None

    def _remember(self, error, evidence):
        try:
            value = _copy(evidence)
        except BaseException as export_error:
            if error is None:
                error = export_error
            value = {'format': 'cbus-routed-identify-evidence-v1', 'complete': False,
                     'evidence_export_failed': True,
                     'error_type': None if error is None else type(error).__name__}
        self.last_error, self.last_evidence = error, value
        if error is not None:
            try:
                error.pci_routed_identify_evidence = _copy(value)
            except BaseException:
                pass
        return error

    @staticmethod
    def _preflight(command, expected, expected_count):
        if type(command) is not RoutedCALCommand or type(command.cal) is not IdentifyCAL:
            raise ValueError('Only an exact RoutedCALCommand containing IdentifyCAL is supported')
        if type(command.addressing) is not str or command.addressing != 'direct':
            raise ValueError('Routed IDENTIFY requires explicit direct addressing')
        _integer(command.cal.attribute, 'attribute', 0, 255)
        if expected_count is not None:
            _integer(expected_count, 'expected_count', 0, 30)
        canonical = RoutedCALCommand(command.unit, IdentifyCAL(command.cal.attribute),
                                     bridges=command.bridges, addressing='direct')
        if type(expected) is not RoutedReplyPath:
            raise ValueError('expected must be an exact RoutedReplyPath')
        path = RoutedReplyPath(expected.outer_source_byte, expected.destination_byte, expected.route_entries)
        terminal = path.route_entries[-1] if path.route_entries else path.outer_source_byte
        if terminal != canonical.unit:
            raise ValueError('Final declared reply path byte must equal the requested unit')
        return canonical, path, expected_count

    def exchange(self, command, *, expected, expected_count=None):
        # A concurrent caller cannot overwrite the active operation's evidence.
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('A routed IDENTIFY exchange is already active')
        self.last_error = self.last_evidence = None
        evidence = {'format': 'cbus-routed-identify-evidence-v1', 'complete': False, 'stage': 'preflight',
                    'connect_attempted': False, 'send_attempted': False, 'send_completed': False,
                    'close_attempted': False, 'close_completed': False, 'resubmitted': False,
                    'confirmation_received': False, 'response_received': False,
                    'events': [], 'received_chunks_hex': [], 'cleanup_errors': [],
                    'logical_network_resolved': False, 'device_origin_verified': False,
                    'original_cached_object_correlation_verified': False,
                    'original_short_matcher_used': False, 'original_typed_getter_used': False}
        first = traceback = sock = result = None
        stream = _Stream()
        events = []
        chunks = []
        try:
            if self._used:
                raise RuntimeError('A routed IDENTIFY client permits only one exchange')
            command, expected, expected_count = self._preflight(command, expected, expected_count)
            # Public configuration may have changed; snapshot and revalidate it
            # before a socket exists, including the no-DNS endpoint restriction.
            settings = RoutedIdentifyClient(self.host, self.port, timeout=self.timeout,
                command_checksum=self.command_checksum, max_events=self.max_events,
                max_received_bytes=self.max_received_bytes)
            code = b'g'  # Locally chosen only; no globally unique/fresh tag claim.
            sent = command.encode(confirmation=code, checksum=settings.command_checksum)
            evidence.update(expected=expected.as_dict(), expected_count=expected_count, sent_hex=sent.hex().upper(),
                            confirmation=code.decode('ascii'), raw_zero_address_ambiguous=command.unit == 0)
            self._used = True
            deadline = time.monotonic() + settings.timeout
            def remaining():
                value = deadline - time.monotonic()
                if value <= 0:
                    raise TimeoutError('Routed IDENTIFY I/O deadline expired')
                return value
            evidence['stage'] = 'connect'
            evidence['connect_attempted'] = True
            sock = socket.socket(settings.family, socket.SOCK_STREAM)
            sock.settimeout(remaining())
            endpoint = (settings.host, settings.port) if settings.family == socket.AF_INET else (settings.host, settings.port, 0, 0)
            sock.connect(endpoint)
            evidence['stage'] = 'send'
            sock.settimeout(remaining())
            evidence['send_attempted'] = True
            sock.sendall(sent)
            evidence['send_completed'] = True
            confirmed = False
            response = None
            received = 0
            evidence['stage'] = 'receive'
            while not (confirmed and response is not None):
                if received >= settings.max_received_bytes:
                    raise ProtocolError('Routed IDENTIFY received-byte limit reached')
                sock.settimeout(remaining())
                chunk = sock.recv(min(4096, settings.max_received_bytes - received))
                if type(chunk) is not bytes or len(chunk) > settings.max_received_bytes - received:
                    raise ProtocolError('Socket returned bytes outside the requested receive bound')
                chunks.append(chunk)
                received += len(chunk)
                evidence['received_chunks_hex'].append(chunk.hex().upper())
                remaining()  # A late final chunk is evidence, never success.
                if not chunk:
                    raise ConnectionError('PCI disconnected before the bounded routed exchange completed')
                for kind, raw in stream.feed(chunk):
                    if len(events) >= settings.max_events:
                        raise ProtocolError('Routed IDENTIFY event limit reached')
                    if kind == 'confirmation':
                        matched = raw[:1] == code
                        event = RoutedIdentifyEvent(kind, raw, matched, chr(raw[1]))
                        events.append(event); evidence['events'].append(event.as_dict())
                        if matched:
                            if confirmed:
                                raise ProtocolError('Multiple matching confirmations in the received prefix')
                            if raw[1:] != b'.':
                                raise PCIRejected('PCI did not positively confirm the routed command')
                            confirmed = True
                            evidence['confirmation_received'] = True
                    else:
                        # Unsupported CALs, including3B, fail strict decoding.
                        # No original short-form or negative-prefix fallback.
                        frame = inspect_received_cal_route(raw)
                        matched = (_path(frame) == expected and type(frame.cal) is ReplyCAL
                                   and frame.cal.parameter == command.cal.attribute)
                        event = RoutedIdentifyEvent('frame', raw, matched, frame=frame)
                        events.append(event); evidence['events'].append(event.as_dict())
                        if matched:
                            if response is not None:
                                raise ProtocolError('Multiple matching replies in the received prefix')
                            if expected_count is not None and len(frame.cal.data) != expected_count:
                                raise ProtocolError('Matching routed REPLY has a different explicit expected byte count')
                            response = frame
                            evidence['response_received'] = True
                            evidence['actual_count'] = len(frame.cal.data)
                if confirmed and response is not None and stream.buffer:
                    raise ProtocolError('Incomplete trailing bytes in the final received chunk')
            result = RoutedIdentifyResult(command, expected, expected_count, sent, code, response, tuple(events), tuple(chunks))
        except BaseException as error:
            first, traceback = error, error.__traceback__
        finally:
            if sock is not None:
                evidence['close_attempted'] = True
                try:
                    sock.close()
                    evidence['close_completed'] = True
                except BaseException as error:
                    if first is None:
                        first, traceback = error, error.__traceback__
                        evidence['stage'] = 'close'
                    else:
                        evidence['cleanup_errors'].append(_error(error))
            try:
                evidence['pending_fragment_hex'] = bytes(stream.buffer).hex().upper()
                if first is None:
                    evidence['complete'] = True
                    evidence['stage'] = 'complete'
                else:
                    evidence['error'] = _error(first)
                remembered = self._remember(first, evidence)
                if first is None and remembered is not None:
                    first, traceback = remembered, remembered.__traceback__
            except BaseException as evidence_error:
                if first is None:
                    first, traceback = evidence_error, evidence_error.__traceback__
                self.last_error = first
                self.last_evidence = {'format': 'cbus-routed-identify-evidence-v1',
                                      'complete': False, 'evidence_export_failed': True,
                                      'error_type': type(first).__name__}
            finally:
                self._lock.release()
        if first is not None:
            raise BaseException.with_traceback(first, traceback)
        return result
