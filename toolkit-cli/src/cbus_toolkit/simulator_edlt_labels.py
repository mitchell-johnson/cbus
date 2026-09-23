"""Opt-in per-unit label-clear fixture with an explicit synthetic storage policy.

Only committed dynamic-label records are cleared; language selections remain.
This policy and file persistence are fixture behavior, not firmware evidence.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from .simulator import PCISimulator, UnitState, synthetic_units, _Rejected
from .simulator_labels import LabelState


@dataclass(frozen=True)
class LabelClearFault:
    clear: bool = True
    response: str = 'ack'

    def __post_init__(self):
        if type(self.clear) is not bool or type(self.response) is not str or self.response not in (
                'ack', 'missing', 'negative', 'extended', 'wrong_tag', 'wrong_source', 'wrong_destination', 'bad_checksum'):
            raise ValueError('Invalid explicit label clear fault')


def _labels(document):
    if not isinstance(document, dict) or set(document) != {'format', 'labels', 'languages'}:
        raise ValueError('Per-unit labels require a complete committed LabelState snapshot')
    for row in document['languages'] if isinstance(document['languages'], list) else ():
        if not isinstance(row, dict) or set(row) != {'key', 'language'}:
            raise ValueError('Invalid language state fields')
    for row in document['labels'] if isinstance(document['labels'], list) else ():
        data = row.get('data_hex') if isinstance(row, dict) else None
        if not isinstance(data, str) or len(data) % 2 or not re.fullmatch('[0-9a-f]*', data):
            raise ValueError('Label bytes must be canonical lowercase hexadecimal')
    result = LabelState.from_snapshot(document)
    if result.snapshot() != document:
        raise ValueError('Label snapshot differs from its validated representation')
    return result


class EdltLabelClearFixture(PCISimulator):
    """Fixed read-only synthetic network plus one explicit eDLT clear control.

    Unit5 is KEYGL5/5.5.00, unit4 is a separate label-cache witness, and unit16
    is the PCI. Transport fault settings are not persistent device state.
    """
    FORMAT = 'cbus-edlt-label-clear-fixture-v1'
    POLICY = 'clear_committed_labels_preserve_languages'
    MAX_BYTES = 4 * 1024 * 1024

    def __init__(self, labels_by_unit, *, clearing_policy, state_path=None, fault=None,
                 command_checksum=False, fragment_sizes=(), wire_log_path=None, response_delay=0):
        if clearing_policy != self.POLICY:
            raise ValueError('Choose the explicit clear_committed_labels_preserve_languages policy')
        if (not isinstance(labels_by_unit, dict) or set(labels_by_unit) != {4, 5}
                or any(type(key) is not int for key in labels_by_unit)):
            raise ValueError('Provide explicit committed label caches for units4 and5')
        self._unit_labels = {unit: _labels(value) for unit, value in labels_by_unit.items()}
        self.fault = LabelClearFault() if fault is None else fault
        if not isinstance(self.fault, LabelClearFault):
            raise ValueError('fault must be a LabelClearFault')
        if state_path is not None and os.path.lexists(state_path):
            raise ValueError('Load an existing fixture explicitly with from_state')
        self.clearing_policy = clearing_policy
        self.revision = 0
        self.clear_operations = []
        self._expected_file_bytes = None
        # All direct unit blocks are read-only. Programming address selection
        # remains available for the original eDLT's discovery reads.
        units = [UnitState(u.address, u.attributes, u.parameters, {}, u.mmi_state) for u in synthetic_units()]
        super().__init__(units, profile='synthetic', lighting_groups=[], command_checksum=command_checksum,
                         fragment_sizes=fragment_sizes, wire_log_path=wire_log_path, response_delay=response_delay)
        self._baseline = PCISimulator._document(self)
        self.state_path = None if state_path is None else Path(state_path)
        self._persist()

    @property
    def unit_labels(self):
        with self._lock:
            return {unit: state.snapshot() for unit, state in self._unit_labels.items()}

    def _document(self):
        base = PCISimulator._document(self)
        if base != self._baseline:
            raise ValueError('Read-only fixture programming or network state changed')
        return {'format': self.FORMAT, 'fixture_only': True, 'firmware_erasure_verified': False,
                'clearing_policy': self.clearing_policy, 'revision': self.revision,
                'base': base, 'unit_labels': {str(unit): state.snapshot() for unit, state in sorted(self._unit_labels.items())}}

    def snapshot(self):
        with self._lock:
            return self._document()

    @classmethod
    def _bytes(cls, document):
        raw = (json.dumps(document, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')
        if len(raw) > cls.MAX_BYTES:
            raise ValueError('Label fixture state exceeds4MiB')
        return raw

    @classmethod
    def _read(cls, path):
        if not os.path.lexists(path):
            return None
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('Fixture state must be a regular file, not a link or special file')
        with path.open('rb') as handle:
            raw = handle.read(cls.MAX_BYTES + 1)
        if len(raw) > cls.MAX_BYTES:
            raise ValueError('Label fixture state exceeds4MiB')
        return raw

    @staticmethod
    def _error(error):
        result = {'type': type(error).__name__}
        try:
            message = str(error)
            result['message'] = message[:1024]
            if len(message) > 1024:
                result['message_truncated'] = True
        except BaseException as secondary:
            result.update(message='Exception message unavailable', message_error_type=type(secondary).__name__)
        return result

    @staticmethod
    def _secondary(first, second):
        if first is None:
            return second
        errors = getattr(first, 'fixture_cleanup_errors', [])
        errors.append(EdltLabelClearFixture._error(second))
        first.fixture_cleanup_errors = errors
        return first

    @classmethod
    def _sync_directory(cls, path):
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        first = None
        try:
            os.fsync(descriptor)
        except BaseException as error:
            first = error
        try:
            os.close(descriptor)
        except BaseException as error:
            first = cls._secondary(first, error)
        if first is not None:
            raise first

    def _persist(self):
        if self.state_path is None:
            return
        if self._read(self.state_path) != self._expected_file_bytes:
            raise ValueError('Fixture state changed externally; refusing to overwrite it')
        raw = self._bytes(self._document())
        descriptor, temporary = tempfile.mkstemp(prefix='.edlt-label-state-', dir=self.state_path.parent)
        first = None
        try:
            offset = 0
            while offset < len(raw):
                count = os.write(descriptor, raw[offset:])
                if not count:
                    raise OSError('Fixture file write made no progress')
                offset += count
            os.fsync(descriptor)
        except BaseException as error:
            first = error
        try:
            os.close(descriptor)
        except BaseException as error:
            first = self._secondary(first, error)
        if first is None:
            try:
                os.replace(temporary, self.state_path)
                self._expected_file_bytes = raw
                self._sync_directory(self.state_path.parent)
            except BaseException as error:
                first = error
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except BaseException as error:
            first = self._secondary(first, error)
        if first is not None:
            raise first

    @classmethod
    def from_state(cls, path, **transport):
        if not set(transport) <= {'fault', 'command_checksum', 'fragment_sizes', 'wire_log_path', 'response_delay'}:
            raise ValueError('State loading accepts only explicit transport/fault settings')
        path = Path(path); raw = cls._read(path)
        if raw is None:
            raise ValueError('Fixture state does not exist')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate fixture JSON key')
                result[key] = value
            return result
        def nonfinite(_value):
            raise ValueError('Nonfinite JSON values are unsupported')
        try:
            document = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
            fields = {'format', 'fixture_only', 'firmware_erasure_verified', 'clearing_policy', 'revision', 'base', 'unit_labels'}
            if (not isinstance(document, dict) or set(document) != fields or document['format'] != cls.FORMAT
                    or document['fixture_only'] is not True or document['firmware_erasure_verified'] is not False
                    or type(document['revision']) is not int or not 0 <= document['revision'] < 2**63
                    or not isinstance(document['unit_labels'], dict) or set(document['unit_labels']) != {'4', '5'}):
                raise ValueError('Invalid per-unit label fixture state')
            fixture = cls({int(unit): state for unit, state in document['unit_labels'].items()},
                          clearing_policy=document['clearing_policy'], **transport)
            fixture.revision = document['revision']
            if fixture._bytes(fixture._document()) != fixture._bytes(document):
                raise ValueError('State differs from its validated fixed topology and label policy')
        except (KeyError, TypeError, AttributeError, UnicodeDecodeError) as error:
            raise ValueError('Invalid per-unit label fixture state') from error
        fixture.state_path = path; fixture._expected_file_bytes = raw
        return fixture

    def _command(self, line, context):
        # Reject SAL before the base application receivers can mutate their
        # separate network-wide state. Discovery MMI remains read-only.
        code = line[-1:] if line and ord('g') <= line[-1] <= ord('z') else b''
        text = line[:-1] if code else line
        addressed = text.startswith(b'\\'); basic = text.startswith(b'@')
        text = text[1:] if addressed or basic else text
        try:
            payload = bytes.fromhex(text.decode('ascii'))
        except (ValueError, UnicodeError):
            return super()._command(line, context)
        if not addressed and not basic and context['header'] is not None:
            payload = context['header'] + payload
        if (not basic and payload[:1] == b'\x05' and not
                (payload[:4] == b'\x05\xff\x00\xfa' and len(payload) == (7 if self.command_checksum else 6))):
            return code + b'#', 'Label clear fixture application and broadcast mutations are unsupported'
        return super()._command(line, context)

    def _physical_cal(self, unit, request):
        if request != b'\xa4\xff\x43\xc1\xea':
            if request[:1] == b'\x1a' or request[:3] == b'\xa4\x00\x41':
                return super()._physical_cal(unit, request)
            raise _Rejected('Only read address selection and exact label clear are supported')
        if unit != 5 or not isinstance(self.fault, LabelClearFault):
            raise _Rejected('Clear requires the declared eDLT unit and valid fault settings')
        record = {'unit': unit, 'control_hex': request.hex(), 'fault': asdict(self.fault),
                  'fixture_only': True, 'firmware_erasure_verified': False, 'clear_attempted': self.fault.clear,
                  'persistence_attempted': False, 'response_generated': False, 'outcome': 'pending'}
        self.clear_operations.append(record)
        previous = self._unit_labels[unit]; revision = self.revision
        previous_file = self._expected_file_bytes; proposed = None
        try:
            if self.fault.clear:
                if type(revision) is not int or not 0 <= revision < 2**63 - 1:
                    raise ValueError('Fixture revision exhausted or invalid')
                replacement = LabelState()
                replacement.languages = deepcopy(previous.languages)
                self._unit_labels[unit] = replacement; self.revision += 1
                proposed = self._bytes(self._document())
                record['persistence_attempted'] = self.state_path is not None
                self._persist()
            record.update(outcome='fixture_cleared' if self.fault.clear else 'fixture_unchanged',
                          persisted=self.fault.clear and self.state_path is not None)
        except BaseException as error:
            disk = None; matched = False
            if record['persistence_attempted']:
                try:
                    disk = self._read(self.state_path)
                    matched = proposed is not None and disk == proposed
                except BaseException as probe:
                    record['disk_probe_error'] = self._error(probe)
            if matched:
                self._expected_file_bytes = proposed
            else:
                self._unit_labels[unit] = previous; self.revision = revision; self._expected_file_bytes = previous_file
            record.update(outcome='persistence_error', disk_matches_proposed_state=matched,
                          memory_restored=not matched, persisted=False,
                          disk_state='proposed_observed_durability_uncertain' if matched else
                                     'original_observed' if disk == previous_file and record['persistence_attempted'] else 'unverified',
                          cause=self._error(error))
            if hasattr(error, 'fixture_cleanup_errors'):
                record['cleanup_errors'] = error.fixture_cleanup_errors
            error.edlt_label_fixture_evidence = record
            if not isinstance(error, Exception):
                raise
            raise _Rejected('Label fixture persistence failed; no normal acknowledgement') from error
        response = self.fault.response
        if response == 'missing':
            return []
        record['response_generated'] = True
        if response == 'negative':
            return [b'\x3b\xff\x43']
        if response == 'wrong_tag':
            return [b'\x32\xff\x44']
        if response == 'extended':
            return [b'\x32\xff\x43\xde\xad\xbe\xef']
        return [b'\x32\xff\x43']

    def _reply(self, payload):
        if payload == b'\x86\x05\x10\x01\x00\x32\xff\x43':
            if self.fault.response == 'wrong_source':
                payload = payload[:1] + b'\x04' + payload[2:]
            elif self.fault.response == 'wrong_destination':
                payload = payload[:2] + b'\x11' + payload[3:]
            elif self.fault.response == 'bad_checksum':
                return b'860510010032FF4300\r\n'
        return super()._reply(payload)
