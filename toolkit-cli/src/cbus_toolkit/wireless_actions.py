"""Frozen, bounded wireless cached reads and explicit one-shot native DO actions.

Cached properties are not physical observations. A successful DO acknowledgement
is not hardware acceptance, and these actions do not reproduce the Toolkit
Status form's broader Psync lifecycle. No network is opened or synchronized.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from types import MappingProxyType
from uuid import UUID

from .serials import parse_native_serial
from .unitspec import version_matches
from .wireless_commissioning import OP_STATS_COUNTERS, STATUS_ATTRIBUTES
from .wireless_project_remotes import (
    FrozenRemoteProject, MAX_PROJECT_XML_BYTES, MAX_CATALOGUE_XML_BYTES,
    MAX_PLAN_JSON_BYTES, _address, _children, _field, _parse, _tag,
)
from .programming import xml_text


PLAN_FORMAT = 'cbus-wireless-action-plan-v1'
CATALOGUE_FORMAT = 'cbus-wireless-action-catalogue-v1'
OPERATIONS = ('cached-status', 'cached-op-stats', 'mai-sync', 'recall-op-stats', 'reset-op-stats')
_METHODS = MappingProxyType({'mai-sync': 'MAISync', 'recall-op-stats': 'RecallOpStats',
                            'reset-op-stats': 'ResetOpStats'})
MAI_FIELDS = ('ManufacturerCode', 'ProductClass', 'MediaType', 'ProcessSelector', 'FeatureSet')
# Exact catalogue/class/spec cohort reviewed against the pinned native catalogue.
# WGATE5N, WTXU, older profiles and other wireless families are not admitted.
_CATALOGUES = MappingProxyType({
    '5852D2L1AA': ('WRM2D1', ''), '5854D2L1AA': ('WRM4D1', ''),
    '5858D2L1AA': ('WRM8D1', ''), '5854D1L2AA': ('WRM4D2', ''),
    '5858D1L2AA': ('WRM8D2', ''), '5852D2T1AA': ('WRM2D1', ''),
    '5854D2T1AA': ('WRM4D1', ''), '5858D2T1AA': ('WRM8D1', ''),
    '5854D1T2AA': ('WRM4D2', ''), '5858D1T2AA': ('WRM8D2', ''),
    'E5852D2L1TA': ('WRM2D1', 'E5852D2L1EC'), 'E5854D2L1TA': ('WRM4D1', 'E5854D2L1EC'),
    'E5858D2L1TA': ('WRM8D1', 'E5858D2L1EC'), 'E5854D1L2TA': ('WRM4D2', 'E5854D1L2EC'),
    'E5858D1L2TA': ('WRM8D2', 'E5858D1L2EC'), 'E5852D2T1TA': ('WRM2D1', 'E5852D2T1EC'),
    'E5854D2T1TA': ('WRM4D1', 'E5854D2T1EC'), 'E5858D2T1TA': ('WRM8D1', 'E5858D2T1EC'),
    'E5854D1T2TA': ('WRM4D2', 'E5854D1T2EC'), 'E5858D1T2TA': ('WRM8D2', 'E5858D1T2EC'),
    '5852R8F1AA': ('WRM2R1', ''), '5854R8F1AA': ('WRM4R1', ''),
    '5858R8F1AA': ('WRM8R1', ''), '5854R4F2AA': ('WRM4R2', ''),
    '5858R4F2AA': ('WRM8R2', ''), 'E5852R8F1TA': ('WRM2R1', 'E5852R8F1EC'),
    'E5854R8F1TA': ('WRM4R1', 'E5854R8F1EC'), 'E5858R8F1TA': ('WRM8R1', 'E5858R8F1EC'),
    'E5854R4F2TA': ('WRM4R2', 'E5854R4F2EC'), 'E5858R4F2TA': ('WRM8R2', 'E5858R4F2EC'),
    '5800WCGA': ('WGATE5F', '5800WCGC'), 'SLC5800WCGD': ('WGATE5F', ''),
})


class WirelessActionError(ValueError):
    pass


class WirelessActionApplyError(RuntimeError):
    def __init__(self, cause, details):
        self.details = json.loads(json.dumps(details))
        super().__init__('Wireless action stopped; inspect the receipt before manual recovery; '
                         'no action was replayed: ' + str(cause))


def _digest(payload):
    return hashlib.sha256(payload).hexdigest()


def _byte(value, name):
    if type(value) is not int or not 0 <= value <= 254:
        raise WirelessActionError(name + ' must be an integer in 0..254')
    return value


@dataclass(frozen=True)
class WirelessActionCatalogue:
    payload: bytes

    def __post_init__(self):
        if _tag(self.root) != 'CBusUnits':
            raise WirelessActionError('Expected a CBusUnits catalogue')

    @property
    def root(self):
        return _parse(self.payload, MAX_CATALOGUE_XML_BYTES)

    @classmethod
    def from_xml(cls, payload):
        return cls(payload)

    def as_dict(self):
        return {'format': CATALOGUE_FORMAT, 'xml': self.payload.decode('utf-8'),
                'source_sha256': _digest(self.payload)}

    @classmethod
    def from_dict(cls, data):
        if (not isinstance(data, dict) or set(data) != {'format', 'xml', 'source_sha256'}
                or data['format'] != CATALOGUE_FORMAT or not isinstance(data['xml'], str)):
            raise WirelessActionError('Invalid wireless action catalogue')
        result = cls.from_xml(data['xml'].encode('utf-8'))
        if result.as_dict() != data:
            raise WirelessActionError('Catalogue fingerprint mismatch')
        return result

    def resolve(self, unit_type, firmware, catalog_number):
        matches = []
        for unit in self.root.iter():
            if _tag(unit) != 'Unit':
                continue
            catalog = _field(unit, 'CatalogNumber') or ''
            alternatives = _field(unit, 'AlternativeCatalogNumbers') or ''
            candidates = [catalog, *re.split('[,;]', alternatives)]
            # Refuse competing native prefix/alternate matches as ambiguous.
            if not any(candidate == catalog_number or '*' in candidate and
                       catalog_number.startswith(candidate.split('*', 1)[0])
                       for candidate in candidates if candidate):
                continue
            for container in _children(unit, 'FirmwareRevisions'):
                for revision in _children(container, 'Revision'):
                    # Native catalogue rows deliberately share catalogues
                    # between F/N gateway types; selection already binds the
                    # exact database type, and only the reviewed F is admitted.
                    if _field(revision, 'UnitType') != unit_type:
                        continue
                    minimum = _field(revision, 'MinVersion', required=True)
                    maximum = _field(revision, 'MaxVersion', required=True)
                    if version_matches(firmware, minimum, maximum):
                        matches.append((catalog, alternatives, _field(revision, 'UnitType'),
                                        minimum, maximum, _field(revision, 'UnitSpecName'),
                                        _field(revision, 'ClassName')))
        if len(matches) != 1:
            raise WirelessActionError('Missing or ambiguous catalogue profile')
        catalog, alternatives, kind, minimum, maximum, spec, class_name = matches[0]
        gateway = kind == 'WGATE5F'
        ranges = (('2.2.90', '2.2.99'), ('2.3.0', '2.3.99'), ('2.4.0', '2.4.99')) if gateway else tuple(
            (f'2.{minor}.0', f'2.{minor}.99') for minor in range(5))
        if (_CATALOGUES.get(catalog) != (kind, alternatives) or kind != unit_type
                or (minimum, maximum) not in ranges
                or spec != ('WGATE5X_2.xml' if gateway else kind + '_2.xml')
                or class_name != ('WirelessCBusGateway' if gateway else 'CBusWirelessIOUnit')):
            raise WirelessActionError('Unsupported wireless action profile')
        return {'unit_type': kind, 'firmware': firmware, 'catalog_number': catalog_number,
                'catalogue_number': catalog, 'minimum_version': minimum, 'maximum_version': maximum,
                'spec_filename': spec, 'class_name': class_name}


@dataclass(frozen=True)
class WirelessActionPlan:
    project: FrozenRemoteProject
    catalogue: WirelessActionCatalogue
    source_network: int
    unit_address: int
    operation: str

    def __post_init__(self):
        if not isinstance(self.project, FrozenRemoteProject) or not isinstance(self.catalogue, WirelessActionCatalogue):
            raise WirelessActionError('Expected frozen project and wireless action catalogue')
        _byte(self.source_network, 'Source network')
        _byte(self.unit_address, 'Unit address')
        if self.operation not in OPERATIONS:
            raise WirelessActionError('Unsupported wireless action operation')
        self.target

    @property
    def network_path(self):
        return f'//{self.project.name}/{self.source_network}'

    @property
    def source(self):
        return f'{self.network_path}/p/{self.unit_address}'

    @property
    def physical_action(self):
        return self.operation in _METHODS

    @property
    def original_timeout_ms(self):
        return 8000 if self.operation in ('recall-op-stats', 'reset-op-stats') else None

    @property
    def target(self):
        networks = [n for n in _children(self.project.root, 'Network') if _address(n) == self.source_network]
        units = [u for n in networks for u in _children(n, 'Unit') if _address(u) == self.unit_address]
        if len(networks) != 1 or len(units) != 1:
            raise WirelessActionError('Expected one selected database unit')
        unit = units[0]
        kind, firmware, catalog, serial, oid = (_field(unit, name, required=True) for name in (
            'UnitType', 'FirmwareVersion', 'CatalogNumber', 'SerialNumber', 'OID'))
        try:
            identity = parse_native_serial(serial)
            if not identity.known or identity.canonical != serial:
                raise ValueError('unknown or noncanonical serial')
            if str(UUID(oid)) != oid.lower():
                raise ValueError('noncanonical OID')
        except ValueError as error:
            raise WirelessActionError('Selected unit requires a known canonical serial and UUID OID') from error
        profile = self.catalogue.resolve(kind, firmware, catalog)
        return dict(profile, serial_number=serial, oid=oid)

    def as_dict(self):
        result = {'format': PLAN_FORMAT, 'project': self.project.as_dict(), 'catalogue': self.catalogue.as_dict(),
                'source_network': self.source_network, 'unit_address': self.unit_address,
                'operation': self.operation, 'source': self.source, 'target': self.target,
                'physical_action': self.physical_action, 'original_timeout_ms': self.original_timeout_ms,
                'hardware_verified': False, 'implicit_refresh': False}
        if len(json.dumps(result, indent=2, ensure_ascii=True).encode('utf-8')) + 1 > MAX_PLAN_JSON_BYTES:
            raise WirelessActionError('Serialized wireless action plan exceeds the command size cap')
        return result

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get('format') != PLAN_FORMAT:
            raise WirelessActionError('Invalid wireless action plan')
        try:
            result = cls(FrozenRemoteProject.from_dict(data['project']),
                         WirelessActionCatalogue.from_dict(data['catalogue']),
                         data['source_network'], data['unit_address'], data['operation'])
        except KeyError as error:
            raise WirelessActionError('Incomplete wireless action plan') from error
        if result.as_dict() != data:
            raise WirelessActionError('Wireless action plan derived facts mismatch')
        return result


def plan_wireless_action(project, *, catalogue, source_network, unit_address, operation):
    return WirelessActionPlan(project, catalogue, source_network, unit_address, operation)


def validate_action_execution(plan, *, allow_physical_action, timeout, preview=False):
    if not isinstance(plan, WirelessActionPlan):
        raise WirelessActionError('Expected a wireless action plan')
    plan.target
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise WirelessActionError('Client timeout must be finite and positive')
    if type(preview) is not bool or type(allow_physical_action) is not bool:
        raise WirelessActionError('Action opt-in and preview must be booleans')
    if plan.physical_action and not preview:
        if not allow_physical_action:
            raise WirelessActionError('Physical action requires explicit allow_physical_action opt-in')
        if plan.original_timeout_ms and timeout * 1000 < plan.original_timeout_ms:
            raise WirelessActionError('Client timeout must allow the original 8000 ms command timeout')


def _lines(response, code):
    lines = tuple(response.lines)
    if (not lines or response.code != code or response.final != lines[-1]
            or any(not isinstance(line, str) or re.match(r'^\d{3}[ -]', line) is None
                   or int(line[:3]) >= 400 for line in lines)):
        raise WirelessActionError('Unexpected or failed C-Gate response')
    return lines


def _get(client, source, field):
    lines = _lines(client.command(f'GET {source} {field}'), 300)
    prefix = f'300 {source}: {field}='
    if len(lines) != 1 or not lines[0].startswith(prefix):
        raise WirelessActionError('Uncorrelated cached property response: ' + field)
    return lines[0][len(prefix):]


def _stale(client, plan):
    response = client.command('DBGETXML //' + plan.project.name)
    lines = _lines(response, 344)
    body = lines[1:] if lines[0] == '343-Begin XML snippet' else lines
    if (len(body) < 2 or not body[-1].startswith('344 ')
            or any(not line.startswith('347-') for line in body[:-1])):
        raise WirelessActionError('Unexpected project XML response rows')
    current = FrozenRemoteProject.from_xml(xml_text(response).encode('utf-8'))
    if current.fingerprint != plan.project.fingerprint:
        raise WirelessActionError('Stale project snapshot; create a new action plan')


def _preflight(client, plan):
    _stale(client, plan)
    target = plan.target
    for attribute, key in (('Type', 'unit_type'), ('Version', 'firmware'),
                           ('CatalogNumber', 'catalog_number'), ('SerialNumber', 'serial_number')):
        if _get(client, plan.source, attribute) != target[key]:
            raise WirelessActionError('Runtime identity mismatch: ' + attribute)
    _stale(client, plan)


def _receipt(plan, timeout):
    return {'operation': plan.operation, 'source': plan.source, 'target': plan.target,
            'stage': 'preflight', 'status': 'pending', 'command_attempted': False,
            'send_completed': False, 'uncertain_send': False, 'retry_performed': False,
            'cli_replay_performed': False,
            'backend_retry_behavior': 'native network configuration; not overridden or verified',
            'physical_transmissions_verified': False,
            'hardware_verified': False, 'physical_identity_verified': False,
            'identity_binding': 'database_snapshot_and_cached_runtime_profile',
            'client_timeout_seconds': timeout, 'original_timeout_ms': plan.original_timeout_ms,
            'cached_only': not plan.physical_action, 'fresh_recall': False,
            'database_save_performed': False, 'implicit_refresh': False}


def preview_wireless_action(client, plan):
    validate_action_execution(plan, allow_physical_action=False, timeout=client.timeout, preview=True)
    _preflight(client, plan)
    return dict(_receipt(plan, client.timeout), status='verified-preview', stage='complete')


def _op_stats(value, *, fresh=False):
    if value == '{}':
        if fresh:
            raise WirelessActionError('Recall succeeded but its operation statistics cache is empty')
        return None
    if not value.startswith('{') or not value.endswith('}'):
        raise WirelessActionError('Malformed operation statistics cache')
    result = {}
    for item in value[1:-1].split('; '):
        match = re.fullmatch(r'([A-Za-z]+)=(0|[1-9][0-9]{0,9})', item)
        if match is None or match[1] in result or int(match[2]) > 0xffffffff:
            raise WirelessActionError('Malformed or duplicate operation statistics counter')
        result[match[1]] = int(match[2])
    if set(result) != set(OP_STATS_COUNTERS):
        raise WirelessActionError('Expected all twelve operation statistics counters')
    return result


def apply_wireless_action(client, plan, *, allow_physical_action=False):
    validate_action_execution(plan, allow_physical_action=allow_physical_action, timeout=client.timeout)
    receipt = _receipt(plan, client.timeout)
    try:
        _preflight(client, plan)
        if plan.physical_action:
            receipt.update(stage='action', command_attempted=True, uncertain_send=True)
            response = client.command(f'DO {plan.source} {_METHODS[plan.operation]}')
            if _lines(response, 202) != (f'202 Done: {plan.source}',):
                raise WirelessActionError('Expected exact native action acknowledgement')
            receipt.update(send_completed=True, uncertain_send=False)
        receipt['stage'] = 'cached-readback'
        if plan.operation == 'cached-status':
            values = {field: _get(client, plan.source, field) for field in STATUS_ATTRIBUTES}
            if any(not value or len(value) > 256 or any(ord(c) < 32 for c in value) for value in values.values()):
                raise WirelessActionError('Malformed cached status text')
            receipt.update(values=values, cache_scope='four_native_status_properties',
                           cache_unknown=any(value == 'unknown' for value in values.values()))
        elif plan.operation in ('cached-op-stats', 'recall-op-stats'):
            values = _op_stats(_get(client, plan.source, 'OpStats'), fresh=plan.operation == 'recall-op-stats')
            receipt.update(values=values, cache_unknown=values is None,
                           fresh_recall=plan.operation == 'recall-op-stats')
        elif plan.operation == 'mai-sync':
            values = {}
            for field in MAI_FIELDS:
                text = _get(client, plan.source, field)
                if re.fullmatch(r'0|[1-9][0-9]{0,2}', text) is None or int(text) > 255:
                    raise WirelessActionError('Invalid or unknown manufacturer information after MAISync')
                values[field] = int(text)
            receipt.update(values=values, fresh_recall=True)
        else:
            receipt.update(values=None, cache_invalidated=False, reset_effect_verified=False)
        receipt.update(status='completed', stage='complete')
        return receipt
    except (Exception, KeyboardInterrupt) as error:
        receipt.update(status='failed', error=str(error))
        raise WirelessActionApplyError(error, receipt) from error
