"""One-shot RECALL with explicit wire expectations, never cached identity inference."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import math
import socket
import threading
import time

from .pci import PCIRejected, ProtocolError, RecallCAL, ReplyCAL
from .pci_routing import RoutedCALCommand, ReceivedCALRoute, inspect_received_cal_route


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in {low}..{high}')
    return value


def _copy(value):
    return json.loads(json.dumps(value))


def _error(error):
    result = {'type': type(error).__name__}
    try:
        result['message'] = str(error)
    except BaseException:
        result['message'] = '<unavailable>'
    return result


@dataclass(frozen=True)
class RoutedReplyPath:
    outer_source_byte: int
    destination_byte: int
    route_entries: tuple[int, ...] = ()

    def __post_init__(self):
        _integer(self.outer_source_byte, 'outer_source_byte', 0, 255)
        _integer(self.destination_byte, 'destination_byte', 0, 255)
        if type(self.route_entries) is not tuple or len(self.route_entries) > 6:
            raise ValueError('route_entries must be a tuple of at most six bytes')
        for value in self.route_entries:
            _integer(value, 'route entry', 0, 255)

    def as_dict(self):
        return {'outer_source_byte': self.outer_source_byte,
                'destination_byte': self.destination_byte,
                'route_entries': list(self.route_entries)}


@dataclass(frozen=True)
class RoutedRecallEvent:
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
class RoutedRecallResult:
    command: RoutedCALCommand
    expected: RoutedReplyPath
    sent: bytes
    confirmation: bytes
    response: ReceivedCALRoute
    events: tuple[RoutedRecallEvent, ...]
    received_chunks: tuple[bytes, ...]

    @property
    def data(self):
        return self.response.cal.data

    def as_dict(self):
        return {'format': 'cbus-routed-recall-result-v1', 'complete': True,
                'sent_hex': self.sent.hex().upper(), 'confirmation': self.confirmation.decode('ascii'),
                'response': self.response.as_dict(), 'data_hex': self.data.hex().upper(),
                'expected': self.expected.as_dict(), 'events': [v.as_dict() for v in self.events],
                'received_chunks_hex': [v.hex().upper() for v in self.received_chunks],
                'matches_declared_wire_expectation': True, 'confirmation_received': True,
                'response_received': True, 'request_sent_once': True,
                'completion_boundary': 'all bytes in the final received chunk processed',
                'raw_zero_address_ambiguous': self.command.unit == 0,
                'logical_network_resolved': False, 'device_origin_verified': False,
                'causal_freshness_verified': False, 'physical_delivery_verified': False,
                'original_cached_object_correlation_verified': False}


class _Stream:
    """Strict private subset: CR frames, explicit tag/status and idle CR/LF."""
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk):
        for byte in chunk:
            if not self.buffer:
                if byte in (10, 13):
                    continue
                if byte not in b'0123456789abcdefABCDEFghijklmnopqrstuvwxyz':
                    raise ProtocolError('Unsupported routed PCI stream byte')
                self.buffer.append(byte)
                continue
            if ord('g') <= self.buffer[0] <= ord('z'):
                raw = bytes(self.buffer) + bytes((byte,))
                self.buffer.clear()
                if byte not in b".#$%&'":
                    raise ProtocolError('Unsupported explicit PCI confirmation status')
                yield 'confirmation', raw
                continue
            if byte == 13:
                raw = bytes(self.buffer) + b'\r'
                self.buffer.clear()
                yield 'frame', raw
                continue
            if byte not in b'0123456789abcdefABCDEF':
                raise ProtocolError('Addressed routed frames require ASCII hex and CR')
            self.buffer.append(byte)
            if len(self.buffer) > 86:
                raise ProtocolError('Received routed frame exceeds87bytes including CR')


def _negative_path(raw):
    """Return only a checked envelope with opaque3B prefix, never decode a CAL."""
    if not 13 <= len(raw) <= 87 or not raw.endswith(b'\r'):
        return None
    text = raw[:-1]
    if len(text) % 2 or any(v not in b'0123456789abcdefABCDEF' for v in text):
        return None
    payload = bytes.fromhex(text.decode('ascii'))
    if payload[0] not in (6, 134) or payload[3] > 6:
        return None
    offset = 4 + payload[3]
    if len(payload) < offset + 2 or sum(payload) & 255 or payload[offset] != 0x3B:
        return None
    return RoutedReplyPath(payload[1], payload[2], tuple(payload[4:offset]))


def _path(frame):
    return RoutedReplyPath(frame.outer_source_byte, frame.destination_byte, frame.route_entries)


class RoutedRecallClient:
    """Own one socket and one direct RECALL; require confirmation and exact reply.

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
            value = {'format': 'cbus-routed-recall-evidence-v1', 'complete': False,
                     'evidence_export_failed': True,
                     'error_type': None if error is None else type(error).__name__}
        self.last_error, self.last_evidence = error, value
        if error is not None:
            try:
                error.pci_routed_recall_evidence = _copy(value)
            except BaseException:
                pass
        return error

    @staticmethod
    def _preflight(command, expected):
        if type(command) is not RoutedCALCommand or type(command.cal) is not RecallCAL:
            raise ValueError('Only an exact RoutedCALCommand containing RecallCAL is supported')
        if type(command.addressing) is not str or command.addressing != 'direct':
            raise ValueError('Routed RECALL requires explicit direct addressing')
        _integer(command.cal.parameter, 'parameter', 0, 255)
        _integer(command.cal.count, 'count', 1, 30)
        canonical = RoutedCALCommand(command.unit, RecallCAL(command.cal.parameter, command.cal.count),
                                     bridges=command.bridges, addressing='direct')
        if type(expected) is not RoutedReplyPath:
            raise ValueError('expected must be an exact RoutedReplyPath')
        path = RoutedReplyPath(expected.outer_source_byte, expected.destination_byte, expected.route_entries)
        terminal = path.route_entries[-1] if path.route_entries else path.outer_source_byte
        if terminal != canonical.unit:
            raise ValueError('Final declared reply path byte must equal the requested unit')
        return canonical, path

    def exchange(self, command, *, expected):
        # A concurrent caller cannot overwrite the active operation's evidence.
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('A routed RECALL exchange is already active')
        self.last_error = self.last_evidence = None
        evidence = {'format': 'cbus-routed-recall-evidence-v1', 'complete': False, 'stage': 'preflight',
                    'connect_attempted': False, 'send_attempted': False, 'send_completed': False,
                    'close_attempted': False, 'close_completed': False, 'resubmitted': False,
                    'confirmation_received': False, 'response_received': False,
                    'events': [], 'received_chunks_hex': [], 'cleanup_errors': [],
                    'logical_network_resolved': False, 'device_origin_verified': False,
                    'original_cached_object_correlation_verified': False}
        first = traceback = sock = result = None
        stream = _Stream()
        events = []
        chunks = []
        try:
            if self._used:
                raise RuntimeError('A routed RECALL client permits only one exchange')
            command, expected = self._preflight(command, expected)
            # Public configuration may have changed; snapshot and revalidate it
            # before a socket exists, including the no-DNS endpoint restriction.
            settings = RoutedRecallClient(self.host, self.port, timeout=self.timeout,
                command_checksum=self.command_checksum, max_events=self.max_events,
                max_received_bytes=self.max_received_bytes)
            code = b'g'  # Locally chosen only; no globally unique/fresh tag claim.
            sent = command.encode(confirmation=code, checksum=settings.command_checksum)
            evidence.update(expected=expected.as_dict(), sent_hex=sent.hex().upper(),
                            confirmation=code.decode('ascii'), raw_zero_address_ambiguous=command.unit == 0)
            self._used = True
            deadline = time.monotonic() + settings.timeout
            def remaining():
                value = deadline - time.monotonic()
                if value <= 0:
                    raise TimeoutError('Routed RECALL I/O deadline expired')
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
                    raise ProtocolError('Routed RECALL received-byte limit reached')
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
                        raise ProtocolError('Routed RECALL event limit reached')
                    if kind == 'confirmation':
                        matched = raw[:1] == code
                        event = RoutedRecallEvent(kind, raw, matched, chr(raw[1]))
                        events.append(event); evidence['events'].append(event.as_dict())
                        if matched:
                            if confirmed:
                                raise ProtocolError('Multiple matching confirmations in the received prefix')
                            if raw[1:] != b'.':
                                raise PCIRejected('PCI did not positively confirm the routed command')
                            confirmed = True
                            evidence['confirmation_received'] = True
                    else:
                        negative = _negative_path(raw)
                        if negative is not None:
                            matched = negative == expected
                            event = RoutedRecallEvent('observed_negative_prefix', raw, matched)
                            events.append(event); evidence['events'].append(event.as_dict())
                            if matched:
                                raise PCIRejected('Matching envelope has the original negative3B prefix; suffix is opaque')
                            continue
                        frame = inspect_received_cal_route(raw)
                        matched = (_path(frame) == expected and type(frame.cal) is ReplyCAL
                                   and frame.cal.parameter == command.cal.parameter)
                        event = RoutedRecallEvent('frame', raw, matched, frame=frame)
                        events.append(event); evidence['events'].append(event.as_dict())
                        if matched:
                            if response is not None:
                                raise ProtocolError('Multiple matching replies in the received prefix')
                            if len(frame.cal.data) != command.cal.count:
                                raise ProtocolError('Matching routed REPLY has a different requested byte count')
                            response = frame
                            evidence['response_received'] = True
                if confirmed and response is not None and stream.buffer:
                    raise ProtocolError('Incomplete trailing bytes in the final received chunk')
            result = RoutedRecallResult(command, expected, sent, code, response, tuple(events), tuple(chunks))
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
                self.last_evidence = {'format': 'cbus-routed-recall-evidence-v1',
                                      'complete': False, 'evidence_export_failed': True,
                                      'error_type': type(first).__name__}
            finally:
                self._lock.release()
        if first is not None:
            raise BaseException.with_traceback(first, traceback)
        return result
