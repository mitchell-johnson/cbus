"""Explicit claimed eDLT USB ownership, separate from a one-use DFU lease.

Claim/release is not a read-only workflow. Release may issue SET_INTERFACE.
Only control transfers have supplied timeouts; lifecycle calls are not bounded.
"""
from __future__ import annotations

import array
from dataclasses import asdict, dataclass
import hashlib
import math
import threading
import time

from .dfu_transport import ControlReply, DFUInterface, parse_descriptors
from .dfu import MAX_IMAGE_SIZE, parse_command
from .usb_inspection import (_Reader, _bound, _cached_descriptor, _configuration,
                             _find, _metadata, _modules)


def _message(error):
    return str(error) or type(error).__name__


@dataclass(frozen=True)
class USBAcquisition:
    complete: bool
    selector: dict
    descriptor: dict
    device: dict | None
    serial: str | None
    language_ids: tuple[int, ...]
    selected_language_id: int | None
    active_configuration: int | None
    active_alternate: int | None
    claim_attempted: bool
    claim_succeeded: bool
    stage: str
    error: str | None
    trace: tuple[dict, ...]

    def as_dict(self):
        return {**asdict(self), 'language_ids': list(self.language_ids), 'trace': list(self.trace),
                'configuration_index': 0, 'interface': 0, 'device_exclusive': False,
                'deadline_bounded': False, 'scope': 'Validated identity and claimed interface; no DFU operation yet'}


@dataclass(frozen=True)
class USBReleaseOutcome:
    complete: bool
    release_policy: str
    claim_attempted: bool
    claimed_before_release: bool
    release_attempted: bool
    release_succeeded: bool
    release_error: str | None
    close_attempted: bool
    close_succeeded: bool
    close_error: str | None
    elapsed_seconds: float
    timing_error: str | None = None

    def as_dict(self):
        return {**asdict(self), 'implicit_set_interface_possible': self.release_attempted,
                'state_after_release_unknown': self.claim_attempted, 'deadline_bounded': False,
                'release_scope': 'May reset interface to its first alternate; no DFU recovery or request replay'}


class USBAcquisitionError(RuntimeError):
    def __init__(self, session):
        self.session = session
        self.acquisition = session.acquisition
        self.release = session.last_release
        self.details = {'acquisition': self.acquisition.as_dict(),
                        'release': self.release.as_dict() if self.release else None}
        super().__init__(self.acquisition.error or 'USB acquisition failed')


class ClaimedUSBSession:
    """Private physical owner. Always call release() in an outer finally block.

    endpoint().close() invalidates only the logical lease. It deliberately does
    not release the physical claim or handle. Failed acquisition releases its
    owned resources and raises USBAcquisitionError containing both outcomes.
    """
    def __init__(self):
        raise TypeError('Use ClaimedUSBSession.acquire with an explicit release policy')

    @classmethod
    def acquire(cls, *, bus, address, expected_serial, descriptor,
                release_policy, inspection_timeout=5.0, backend=None):
        _bound(bus, 'bus', 0, 255); _bound(address, 'address', 1, 127)
        if release_policy != 'reset-first-alternate':
            raise ValueError('release_policy must explicitly be reset-first-alternate')
        if not isinstance(descriptor, DFUInterface) or parse_descriptors(
                descriptor.device_descriptor, descriptor.configuration_descriptor) != descriptor:
            raise ValueError('descriptor must be a validated DFUInterface')
        if descriptor.device_descriptor[17] != 1 or descriptor.serial_index == 0:
            raise ValueError('Claimed DFU requires one configuration at index0 and a USB serial string')
        _configuration(descriptor.configuration_descriptor)
        if not isinstance(expected_serial, str) or not expected_serial or '\0' in expected_serial:
            raise ValueError('expected_serial must be nonempty Unicode without NUL')
        try: encoded = expected_serial.encode('utf-16-le')
        except UnicodeEncodeError as error: raise ValueError('expected_serial must be valid Unicode') from error
        if len(encoded) > 252: raise ValueError('expected_serial exceeds the USB string descriptor limit')
        if type(inspection_timeout) not in (int, float) or not math.isfinite(inspection_timeout) or not 0 < inspection_timeout <= 3600:
            raise ValueError('inspection_timeout must be positive, finite and at most 3600 seconds per transfer')
        self = object.__new__(cls)
        self.descriptor = descriptor; self.release_policy = release_policy
        self._devices = []; self._device = None; self._claimed = False; self._claim_attempted = False
        self._released = False; self._lease = None; self._lease_created = False; self._lock = threading.Lock()
        self.acquisition = None; self.last_release = None
        self._util = None
        selector = {'bus': bus, 'address': address, 'expected_serial': expected_serial}
        metadata = serial = selected_language = active = alternate = None
        languages = (); trace = []; stage = 'backend'; failure = None
        try:
            core, backend = _modules(backend)
            import usb.util
            self._util = usb.util
            stage = 'enumeration'; _find(core, backend, self._devices, 64)
            candidates = [device for device in self._devices if device.bus == bus and device.address == address]
            if len(candidates) != 1:
                raise ValueError(f'Exact USB selector matched {len(candidates)} eDLT devices; exactly one is required')
            self._device = device = candidates[0]; metadata = _metadata(device)
            reader = _Reader(device, inspection_timeout, trace)
            stage = 'device_descriptor'; actual_device = reader.read(6, 0x100, 0, 18)
            if actual_device != _cached_descriptor(device) or actual_device != descriptor.device_descriptor:
                raise ValueError('Device descriptor differs from cached or explicit expected identity')
            stage = 'configuration_descriptor'; header = reader.read(6, 0x200, 0, 9)
            expected_configuration = descriptor.configuration_descriptor
            if header != expected_configuration[:9]:
                raise ValueError('Configuration header differs from the expected index0 descriptor')
            configuration = reader.read(6, 0x200, 0, len(expected_configuration))
            if configuration != expected_configuration:
                raise ValueError('Configuration differs from the explicit expected descriptor')
            stage = 'active_configuration'; active = reader.read(8, 0, 0, 1)[0]
            if active != expected_configuration[5]:
                raise ValueError('Active configuration does not match the expected descriptor; configuration will not be changed')
            stage = 'usb_serial'; raw_languages = reader.string_descriptor(0, 0)
            languages = tuple(int.from_bytes(raw_languages[i:i+2], 'little') for i in range(2, len(raw_languages), 2))
            if not languages or 0 in languages or len(set(languages)) != len(languages):
                raise ValueError('USB language identifiers must be unique and nonzero')
            selected_language = languages[0]
            raw_serial = reader.string_descriptor(descriptor.serial_index, selected_language)
            try: serial = raw_serial[2:].decode('utf-16-le', errors='strict')
            except UnicodeDecodeError as error: raise ValueError('USB serial contains invalid UTF-16LE') from error
            if serial != expected_serial:
                raise ValueError('USB serial does not match expected_serial')
            stage = 'claim'; self._claim_attempted = True
            self._util.claim_interface(device, 0); self._claimed = True
            stage = 'active_alternate'
            row = {'bmRequestType': 0x81, 'bRequest': 10, 'wValue': 0, 'wIndex': 0,
                   'wLength': 1, 'timeout_ms': reader.timeout}
            trace.append(row)
            try:
                response = device.ctrl_transfer(0x81, 10, 0, 0, 1, timeout=reader.timeout)
                if not isinstance(response, array.array) or response.typecode != 'B':
                    raise ValueError('GET_INTERFACE returned an invalid IN response')
                row.update(transferred=len(response), data=response.tobytes().hex())
                if len(response) != 1: raise ValueError('GET_INTERFACE did not return exactly one byte')
                alternate = response[0]
                if alternate != 0: raise ValueError('Active alternate must already be zero; it will not be selected')
            except BaseException as error:
                row['error'] = _message(error); raise
            stage = 'configuration_recheck'
            if reader.read(8, 0, 0, 1)[0] != active:
                raise ValueError('Active configuration changed during claim')
            stage = 'complete'
        except BaseException as error:
            failure = error
        self.acquisition = USBAcquisition(failure is None, selector, descriptor.as_dict(), metadata,
            serial, languages, selected_language, active, alternate, self._claim_attempted, self._claimed,
            stage, _message(failure) if failure is not None else None, tuple(dict(row) for row in trace))
        if failure is not None:
            cleanup_interruption = None
            try: self.release()
            except BaseException as error: cleanup_interruption = error
            interruption = failure if not isinstance(failure, Exception) else cleanup_interruption
            if interruption is not None:
                interruption.usb_acquisition = self.acquisition
                interruption.usb_release = self.last_release
                raise interruption.with_traceback(interruption.__traceback__)
            raise USBAcquisitionError(self) from failure
        return self

    def endpoint(self):
        if not self._lock.acquire(blocking=False): raise RuntimeError('USB session is busy')
        try:
            if self._released or not self.acquisition or not self.acquisition.complete or self._lease_created:
                raise RuntimeError('A validated USB session supplies exactly one Endpoint0 lease')
            self._lease_created = True; self._lease = USBEndpoint0Lease._create(self)
            return self._lease
        finally: self._lock.release()

    def release(self):
        """Release once, preserving errors; may send SET_INTERFACE and block.

        Repeated calls return the recorded outcome without any USB request.
        An interruption is re-raised after last_release has been recorded.
        """
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('Cannot release a USB session while a control call is active')
        try:
            if self._released: return self.last_release
            self._released = True
            if self._lease is not None: self._lease.close()
            started = None; claimed = self._claimed
            released = False; release_error = close_error = None; interruption = None; timing_errors = []
            try: started = time.monotonic()
            except BaseException as error:
                timing_errors.append('Starting release clock failed: '+_message(error))
                if not isinstance(error, Exception): interruption = error
            if claimed:
                try: self._util.release_interface(self._device, 0); released = True
                except BaseException as error:
                    release_error = _message(error)
                    if not isinstance(error, Exception) and interruption is None: interruption = error
                finally: self._claimed = False
            failures = []; close_attempted = False
            for device in self._devices:
                close_attempted |= device._ctx.handle is not None
                try: device.finalize()
                except BaseException as error:
                    failures.append(_message(error))
                    if not isinstance(error, Exception) and interruption is None: interruption = error
            if failures: close_error = '; '.join(failures)
            elapsed = 0.
            if started is not None:
                try: elapsed = max(0., time.monotonic()-started)
                except BaseException as error:
                    timing_errors.append('Finishing release clock failed: '+_message(error))
                    if not isinstance(error, Exception) and interruption is None: interruption = error
            timing_error = '; '.join(timing_errors) if timing_errors else None
            result = USBReleaseOutcome(release_error is None and close_error is None and timing_error is None, self.release_policy,
                self._claim_attempted, claimed, claimed, released, release_error,
                close_attempted, close_error is None, close_error, elapsed, timing_error)
            self.last_release = result
            if interruption is not None: raise interruption.with_traceback(interruption.__traceback__)
            return result
        finally: self._lock.release()


class USBEndpoint0Lease:
    """One logical DFU service, already opened/claimed by its physical owner."""
    def __init__(self, owner):
        raise TypeError('Obtain the one-use lease through ClaimedUSBSession.endpoint()')

    @classmethod
    def _create(cls, owner):
        self = object.__new__(cls)
        self._owner = owner; self.closed = False; self.trace = []
        self._next_sequence = 0; self._program_remaining = None
        return self

    def close(self):
        """Invalidate logical use only. The owner still requires release()."""
        self.closed = True

    def control(self, bm_request_type, request, value, index, *, data=b'', length=0, timeout):
        owner = self._owner
        if not owner._lock.acquire(blocking=False): raise RuntimeError('Concurrent USB control calls are not supported')
        try:
            if self.closed or owner._released: raise RuntimeError('USB Endpoint0 lease is closed')
            for field, name, maximum in ((bm_request_type, 'bm_request_type', 255),
                (request, 'request', 255), (value, 'value', 65535), (index, 'index', 65535),
                (length, 'length', 65535)):
                _bound(field, name, 0, maximum)
            if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
                raise ValueError('Control timeout must be finite, positive and at most 3600 seconds')
            milliseconds = math.floor(timeout*1000)
            if milliseconds < 1: raise TimeoutError('Less than one millisecond remains; no USB transfer was started')
            if not isinstance(data, bytes) or index != 0:
                raise ValueError('DFU control requires byte payloads and interface/index zero')
            transfer = owner.descriptor.transfer_size
            incoming = bool(bm_request_type & 0x80)
            if (incoming and data) or (not incoming and len(data) != length):
                raise ValueError('Control payload/direction/length is inconsistent')
            allowed = (
                (bm_request_type == 0x80 and request == 6 and not data and
                    ((value == 0x100 and length == 18) or
                     (value == 0x200 and length in (9, len(owner.descriptor.configuration_descriptor)))))
                or (bm_request_type == 0xa1 and request == 3 and value == 0 and length == 6)
                or (bm_request_type == 0xa1 and request == 0x42 and value == 0x23 and length == 4)
                or (bm_request_type == 0xa1 and request == 2 and 1 <= length <= transfer)
                or (bm_request_type == 0x21 and request == 1 and length <= transfer)
                or (bm_request_type == 0x21 and request == 6 and value == 0 and length == 0))
            if not allowed: raise ValueError('USB request is outside the accepted DFUClient grammar')
            sequence_request = (bm_request_type, request) in ((0x21, 1), (0xa1, 2))
            if sequence_request and value != self._next_sequence:
                raise ValueError('DFU upload/download sequence must advance once without replay or wrap')
            next_remaining = self._program_remaining
            if bm_request_type == 0x21 and request == 1:
                if next_remaining is None:
                    command = parse_command(data)
                    if command.operation not in ('info', 'program', 'read', 'erase', 'binary'):
                        raise ValueError('Vendor reset/check commands are outside the accepted DFUClient grammar')
                    if command.length is not None and not 0 < command.length <= MAX_IMAGE_SIZE:
                        raise ValueError('Vendor command length must be positive and bounded')
                    if command.external and command.address not in (None, 0):
                        raise ValueError('External memory commands currently require address zero')
                    if command.operation == 'program': next_remaining = command.length
                else:
                    if length > next_remaining or (length == 0 and next_remaining != 0):
                        raise ValueError('Program data/termination does not match its declared remaining length')
                    next_remaining = None if length == 0 else next_remaining-length
            elif self._program_remaining is not None and (bm_request_type, request) in ((0xa1, 2), (0x21, 6)):
                raise ValueError('A selected program stream cannot be uploaded or aborted by this lease')
            row = {'bmRequestType': bm_request_type, 'bRequest': request, 'wValue': value,
                   'wIndex': index, 'wLength': length, 'timeout_ms': milliseconds}
            if data: row['out_sha256'] = hashlib.sha256(data).hexdigest()
            self.trace.append(row)
            try:
                response = owner._device.ctrl_transfer(bm_request_type, request, value, index,
                    length if incoming else data, timeout=milliseconds)
                if incoming:
                    if not isinstance(response, array.array) or response.typecode != 'B':
                        raise ValueError('PyUSB returned an invalid IN transfer result')
                    received = response.tobytes(); count = len(received)
                    row['in_sha256'] = hashlib.sha256(received).hexdigest()
                else:
                    if type(response) is not int or not 0 <= response <= length:
                        raise ValueError('PyUSB returned an invalid OUT transfer count')
                    received = b''; count = response
                row['transferred'] = count
                if count != length: self.closed = True
                elif sequence_request:
                    self._next_sequence += 1; self._program_remaining = next_remaining
                return ControlReply(True, count, received)
            except BaseException as error:
                self.closed = True; row['error'] = _message(error)
                if getattr(error, 'backend_error_code', None) is not None:
                    row['backend_error_code'] = error.backend_error_code
                raise
        finally: owner._lock.release()
