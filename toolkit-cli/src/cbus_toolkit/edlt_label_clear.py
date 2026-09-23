"""Guarded native eDLT dynamic-label clear requests; erasure is unverified."""
from __future__ import annotations

from dataclasses import dataclass
import re

from .addressing import _container
from .cgate import CGateError
from .physical_addressing import PhysicalAddressing, _digest
from .serial_population import _fingerprint
from .serials import parse_native_serial


def _path(value):
    if type(value) is not str:
        raise ValueError('Clear requires one complete physical unit path')
    match = re.fullmatch(r'//([A-Za-z0-9_]{1,8})/(0|[1-9][0-9]{0,2})/p/([1-9][0-9]{0,2})', value)
    if not match or int(match[2]) > 255 or int(match[3]) > 254:
        raise ValueError('Clear requires //PROJECT/NETWORK/p/UNIT with one unit in 1..254')
    return value.rsplit('/p/', 1)[0], int(match[3])


@dataclass(frozen=True)
class EdltLabelClearPlan:
    source: str
    serial: str
    unit_type: str
    firmware: str
    inventory: tuple[tuple, ...]
    runtime: tuple[tuple[str, str], ...]
    database_hash: str

    def as_dict(self):
        return {'format': 'cbus-edlt-label-clear-plan-v1', 'source': self.source, 'serial': self.serial,
                'unit_type': self.unit_type, 'firmware': self.firmware,
                'inventory': [list(row) for row in self.inventory], 'runtime': dict(self.runtime),
                'database_hash': self.database_hash, 'physical_refresh_scope': 'entire_network',
                'native_command': 'LABEL CLEAREDLT ' + self.source, 'native_retries': 0,
                'automatic_retries': 0, 'request_attempted': False,
                'labels_cleared_verified': False, 'label_persistence_verified': False, 'database_updated': False}


class EdltLabelClearUncertain(RuntimeError):
    def __init__(self, message, evidence):
        self.details = evidence
        super().__init__(message)


class EdltDynamicLabelClear:
    """Plan, repeat identity guards, then issue one native request without replay.

    No native response in this API proves device-side label storage contents.
    A rejected request also does not prove that no side effect occurred.
    """
    def __init__(self, client):
        self.client = client
        self._guards = PhysicalAddressing(client)
        self.scanner = self._guards.scanner
        self.last_evidence = None

    @staticmethod
    def _validate(plan):
        if type(plan) is not EdltLabelClearPlan:
            raise ValueError('Use an EdltLabelClearPlan returned by plan()')
        network, address = _path(plan.source)
        if any(type(value) is not str for value in (plan.serial, plan.unit_type, plan.firmware)):
            raise ValueError('Clear plan identity fields must be exact strings')
        serial = parse_native_serial(plan.serial)
        if not serial.known or serial.canonical != plan.serial:
            raise ValueError('Clear plan requires a known canonical serial')
        if plan.unit_type != 'KEYGL5' or plan.firmware != '5.5.00':
            raise ValueError('Clear plan requires KEYGL5 firmware 5.5.00')
        if (type(plan.inventory) is not tuple or not 1 <= len(plan.inventory) <= 256 or
                any(type(row) is not tuple or len(row) != 5 or type(row[0]) is not int or not 0 <= row[0] <= 255
                    or any(type(v) is not str or not v or len(v) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in v)
                           for v in row[1:]) or row[4] != 'ok' for row in plan.inventory)):
            raise ValueError('Invalid clear plan identity inventory')
        addresses = tuple(row[0] for row in plan.inventory)
        serials = [parse_native_serial(row[3]) for row in plan.inventory]
        if (addresses != tuple(sorted(set(addresses))) or len({s.canonical for s in serials}) != len(serials)
                or any(not s.known or s.canonical != row[3] for s, row in zip(serials, plan.inventory))
                or (address, plan.unit_type, plan.firmware, plan.serial, 'ok') not in plan.inventory):
            raise ValueError('Clear plan inventory has duplicate, unknown or inconsistent identities')
        if (type(plan.runtime) is not tuple or not plan.runtime or len(plan.runtime) > 16 or
                any(type(row) is not tuple or len(row) != 2 or
                    any(type(v) is not str or not v or len(v) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in v)
                        for v in row) for row in plan.runtime)):
            raise ValueError('Invalid clear plan runtime settings')
        expected = {'InterfaceState': 'running', 'TargetInterfaceState': 'running', 'SyncState': 'idle',
                    'AutoUnravel': 'no', 'AutoUpdate': 'no', 'Retries': '0', 'NetworkType': 'Wired',
                    'Name': network.rsplit('/', 1)[1]}
        runtime = dict(plan.runtime)
        if (tuple(sorted(runtime.items())) != plan.runtime or set(runtime) != set(expected) | {'Type', 'InterfaceAddress'}
                or any(runtime[key] != value for key, value in expected.items()) or runtime['Type'].lower() not in ('cni', 'serial')):
            raise ValueError('Clear plan runtime preconditions are not canonical')
        if type(plan.database_hash) is not str or not re.fullmatch('[0-9a-f]{64}', plan.database_hash):
            raise ValueError('Invalid clear plan database fingerprint')

    @staticmethod
    def _guard(call, *args, **kwargs):
        try:
            return call(*args, **kwargs)
        except ValueError as error:
            message = str(error).replace('Physical readdress', 'eDLT label clear').replace(
                'Physical address', 'eDLT label clear').replace('Physical identity refresh', 'eDLT label clear identity refresh')
            raise ValueError(message) from error

    def plan(self, source, *, expected_serial):
        network, address = _path(source)
        if type(expected_serial) is not str:
            raise ValueError('Clear requires an expected native serial string')
        expected = parse_native_serial(expected_serial)
        if not expected.known:
            raise ValueError('Clear requires a known expected native serial')
        runtime = self._guard(self._guards._runtime, network)
        database = self._guard(self._guards._database, network)
        document = _container(database, 'Network')
        endpoints = document.getElementsByTagName('InterfaceAddress')
        types = document.getElementsByTagName('InterfaceType')
        if (len(endpoints) != 1 or not endpoints[0].firstChild or endpoints[0].firstChild.data != dict(runtime)['InterfaceAddress']
                or len(types) != 1 or not types[0].firstChild or types[0].firstChild.data.lower() != dict(runtime)['Type'].lower()):
            raise ValueError('Runtime and database interface definitions differ')
        observation = self._guard(self.scanner.refresh, network, [address])
        if (observation.errors or not observation.refresh_completed or len(observation.records) != 1):
            raise ValueError('Clear requires a completed physical identity refresh')
        unit = observation.records[0]
        if unit.address != address or unit.status != 'ok' or unit.state != 'ok' or unit.presence != 'single' or unit.errors:
            raise ValueError('Clear requires exactly one healthy physical unit at the target')
        if unit.unit_type != 'KEYGL5' or unit.firmware != '5.5.00':
            raise ValueError('Clear is bounded to KEYGL5 firmware 5.5.00')
        actual = parse_native_serial(unit.serial)
        if actual.canonical != expected.canonical:
            raise ValueError('Physical source serial differs from the expected unit')
        inventory = self._guard(_fingerprint, self.scanner.cached(network))
        if any(row[1] == 'BRIDGE' or row[1].startswith('WGATE') for row in inventory):
            raise ValueError('Bridge and wireless gateway topologies are outside this clear workflow')
        if (address, unit.unit_type, unit.firmware, unit.serial, 'ok') not in inventory:
            raise ValueError('Physical source identity changed during observation')
        if _digest(self._guard(self._guards._database, network)) != _digest(database):
            raise ValueError('Database changed during physical observation')
        if self._guard(self._guards._runtime, network) != runtime:
            raise ValueError('Runtime settings changed during observation')
        self._guard(self._guards._coverage, network, inventory, present=(address,))
        result = EdltLabelClearPlan(source, actual.canonical, unit.unit_type, unit.firmware,
                                   inventory, runtime, _digest(database))
        self._validate(result)
        return result

    @staticmethod
    def _failure(evidence, error):
        evidence['cause_type'] = type(error).__name__
        try:
            evidence['cause'] = str(error)
        except BaseException as secondary:
            evidence['cause'] = 'Exception message unavailable'
            evidence['cause_export_error_type'] = type(secondary).__name__

    @staticmethod
    def _uncertain(message, evidence, cause):
        result = EdltLabelClearUncertain(message, evidence)
        if hasattr(cause, 'cgate_cleanup_errors'):
            result.cgate_cleanup_errors = cause.cgate_cleanup_errors
        return result

    def request(self, plan):
        self._validate(plan)
        self.last_evidence = None
        fresh = self.plan(plan.source, expected_serial=plan.serial)
        if fresh != plan:
            raise ValueError('Clear preconditions changed since the plan was made')
        network, address = _path(plan.source)
        coverage = self._guard(self._guards._coverage, network, plan.inventory, present=(address,))
        evidence = {**plan.as_dict(), 'outcome': 'outcome_uncertain', 'request_attempted': True,
                    'native_accepted': False, 'device_side_effect_possible': True,
                    'strict_receipt_correlation_verified': False, 'pre_request_coverage': coverage,
                    'reply': None}
        self.last_evidence = evidence
        try:
            response = self.client.command('LABEL CLEAREDLT ' + plan.source)
            evidence.update(reply=list(response.lines), native_code=response.code)
            if response.code == 200 and response.lines == ('200 OK.',):
                evidence.update(outcome='native_accepted', native_accepted=True)
                return evidence
            raise EdltLabelClearUncertain('Unexpected native clear reply; request was not replayed', evidence)
        except EdltLabelClearUncertain:
            raise
        except CGateError as error:
            response = error.response
            if (400 <= response.code <= 599 and response.lines and
                    all(re.fullmatch(r'[45][0-9]{2}[- ].+', line) for line in response.lines)):
                evidence.update(outcome='native_rejected', reply=list(response.lines), native_code=response.code)
                return evidence
            self._failure(evidence, error)
            evidence.update(reply=list(response.lines))
            raise self._uncertain('Clear request outcome is uncertain; request was not replayed', evidence, error) from error
        except BaseException as error:
            self._failure(evidence, error)
            if not isinstance(error, Exception):
                error.edlt_label_clear_evidence = evidence
                raise
            raise self._uncertain('Clear request outcome is uncertain; request was not replayed', evidence, error) from error
