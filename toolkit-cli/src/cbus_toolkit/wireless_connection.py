"""Source-bounded WGATE5N/F Connection controls; no radio or parent-dialog save.

Routes are resolved from an immutable project projection. The gateway's own
address names the adjacent network; route entries are networks BEYOND it.
See docs/wireless.md and research/fixtures/wireless-connection-source-review.json.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
import xml.etree.ElementTree as ET

from .macros import _numbers
from .memory import MemoryCodec
from .unitspec import version_matches
from .wireless_gateway import LAYOUT as REMOTE_LAYOUT, SPEC_FILENAME, verify_native_schema


class WirelessConnectionError(ValueError):
    pass


class WirelessConnectionApplyError(RuntimeError):
    def __init__(self, cause, attempted):
        self.details = {'attempted_parameters': list(attempted), 'saved': False,
                        'device_verified': False, 'retry_performed': False}
        super().__init__('Wireless Connection staging stopped; changes may be partial and were not saved: ' + str(cause))


PLAN_FORMAT = 'cbus-wireless-connection-plan-v1'
TOPOLOGY_FORMAT = 'cbus-wireless-connection-topology-v1'
MAX_PROJECT_XML_BYTES = 16 * 1024 * 1024
OWNED = MappingProxyType({
    'Application': (0x21, 2, 8, 0, 0, 'int'),
    'ApplicationConnectEnabled': (0x41, 1, 1, 0, 0, 'bit'),
    'SynchroniseToWired': (0x41, 1, 1, 2, 0, 'bit'),
    'ForwardingMode': (0x41, 1, 1, 1, 0, 'bit'),
    'ForwardingRoute': (0x42, 7, 8, 0, 0, 'int'),
    'StatusMonitorApplication': (0x37, 1, 8, 0, 0, 'int'),
})
LAYOUT = MappingProxyType({**OWNED, **{k: v for k, v in REMOTE_LAYOUT.items() if k not in OWNED}})
FIELDS = tuple(LAYOUT)
BRIDGE_TYPES = frozenset({'BRIDGE2N', 'BRIDGE2F'})
# Original IsBridge has more families. Their route profiles remain unaccepted.
ALL_BRIDGE_TYPES = frozenset({'BRIDGE1N', 'BRIDGE1F', 'GATEWLS', 'GATEWLSN', 'GATEWLSF',
                             'WGATE5N', 'WGATE5F', 'WGATE5XN', 'WGATE5XF', *BRIDGE_TYPES})
# GetCanAddGroups / standard application registry and combo AllowUnused.
NON_GROUP_APPLICATIONS = frozenset({192, 205, 206, 208, 223, 224, 228})
OPTION_NAMES = frozenset({'application1', 'application2', 'adjacent_network', 'synchronise_to_wired',
                          'destination_network', 'status_monitor_application'})
UNIT_TYPES = ('WGATE5N', 'WGATE5F')
FIRMWARE_RANGE = ('2.2.90', '2.4.99')


def check_profile(unit_type, firmware, catalog_number=None):
    # Original 0x1388745 registers N with the base gateway class; 0x13888e8
    # registers F with Advanced. Shared spec fields do not confer its controls.
    if (unit_type not in UNIT_TYPES or not isinstance(firmware, str)
            or not re.fullmatch(r'[0-9]{1,4}(\.[0-9]{1,4}){1,3}', firmware)
            or not version_matches(firmware, *FIRMWARE_RANGE)):
        raise WirelessConnectionError('Only WGATE5N/F Connection profiles at firmware 2.2.90..2.4.99 are admitted')
    return unit_type, firmware, catalog_number


def fields_for(unit_type):
    # Base N has no remote/scene model. Its opaque PP tables are preserved,
    # without importing Advanced application callbacks into this profile.
    return FIELDS if unit_type == 'WGATE5F' else tuple(OWNED)


def _byte(value, label, maximum=254):
    if type(value) is not int or not 0 <= value <= maximum:
        raise WirelessConnectionError(f'{label} must be an integer in 0..{maximum}')
    return value


def _boolean(value, label):
    if type(value) is not bool:
        raise WirelessConnectionError(label + ' must be a Boolean')
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _children(node, name):
    namespace = node.tag.partition('}')[0] + '}' if node.tag.startswith('{') else ''
    return [child for child in node if child.tag == namespace + name]


def _field(node, name, *, required=False):
    nodes = _children(node, name)
    if len(nodes) > 1:
        raise WirelessConnectionError('Ambiguous duplicate ' + name)
    if not nodes:
        if required:
            raise WirelessConnectionError('Missing ' + name)
        return ''
    if len(nodes[0]):
        raise WirelessConnectionError(name + ' must be scalar')
    return (nodes[0].text or '').strip()


def _address(node, maximum=254):
    value = _field(node, 'Address', required=True)
    if not re.fullmatch(r'[0-9]{1,3}', value):
        raise WirelessConnectionError('Address must be a decimal byte')
    return _byte(int(value), 'Address', maximum)


@dataclass(frozen=True)
class FrozenTopology:
    """Canonical, immutable consumed project facts, with original-byte provenance."""
    document: str
    source_sha256: str

    def __post_init__(self):
        if not isinstance(self.source_sha256, str) or not re.fullmatch('[0-9a-f]{64}', self.source_sha256):
            raise WirelessConnectionError('Topology source SHA-256 is invalid')
        try:
            data = json.loads(self.document)
        except (TypeError, ValueError) as error:
            raise WirelessConnectionError('Invalid frozen topology') from error
        if self.document != _canonical(data):
            raise WirelessConnectionError('Frozen topology must be canonical')
        self._validate(data)

    @staticmethod
    def _validate(data):
        if not isinstance(data, dict) or set(data) != {'project', 'networks'}:
            raise WirelessConnectionError('Invalid frozen topology fields')
        if not isinstance(data['project'], str) or not re.fullmatch(r'[A-Za-z0-9_\-]+', data['project']):
            raise WirelessConnectionError('Unsupported project identity')
        if not isinstance(data['networks'], list) or not data['networks']:
            raise WirelessConnectionError('Missing project networks')
        seen = set()
        for network in data['networks']:
            if not isinstance(network, dict) or set(network) != {'address', 'interface_type', 'interface_address', 'units', 'applications'}:
                raise WirelessConnectionError('Invalid frozen network fields')
            address = _byte(network['address'], 'Network address')
            if address in seen:
                raise WirelessConnectionError('Ambiguous duplicate network address')
            seen.add(address)
            if (not isinstance(network['interface_type'], str) or not network['interface_type']
                    or not isinstance(network['interface_address'], str)):
                raise WirelessConnectionError('Missing network interface')
            if not isinstance(network['units'], list) or not isinstance(network['applications'], list):
                raise WirelessConnectionError('Invalid frozen network collections')
            units = set()
            for unit in network['units']:
                if not isinstance(unit, dict) or set(unit) != {'address', 'unit_type', 'firmware', 'catalog_number'}:
                    raise WirelessConnectionError('Invalid frozen unit fields')
                unit_address = _byte(unit['address'], 'Unit address')
                if unit_address in units:
                    raise WirelessConnectionError('Ambiguous duplicate unit address')
                units.add(unit_address)
                if not all(isinstance(unit[n], str) for n in ('unit_type', 'firmware', 'catalog_number')) or not unit['unit_type']:
                    raise WirelessConnectionError('Missing unit identity')
            apps = [_byte(a, 'Application address', 255) for a in network['applications']]
            if len(apps) != len(set(apps)):
                raise WirelessConnectionError('Ambiguous duplicate application address')

    @classmethod
    def from_xml(cls, payload):
        if type(payload) is not bytes or len(payload) > MAX_PROJECT_XML_BYTES:
            raise WirelessConnectionError('Project XML must be bytes no larger than 16 MiB')
        if b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():
            raise WirelessConnectionError('Unsupported project XML declarations')
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as error:
            raise WirelessConnectionError('Invalid project XML') from error
        projects = [root] if root.tag.rsplit('}', 1)[-1] == 'Project' else _children(root, 'Project')
        if len(projects) != 1:
            raise WirelessConnectionError('Expected exactly one project')
        project = projects[0]
        name = _field(project, 'Address') or _field(project, 'TagName', required=True)
        networks = []
        for node in _children(project, 'Network'):
            interfaces = _children(node, 'Interface')
            if len(interfaces) != 1:
                raise WirelessConnectionError('Each network needs exactly one Interface')
            units = [{'address': _address(u), 'unit_type': _field(u, 'UnitType', required=True).upper(),
                      'firmware': _field(u, 'FirmwareVersion'), 'catalog_number': _field(u, 'CatalogNumber')}
                     for u in _children(node, 'Unit')]
            networks.append({'address': _address(node),
                             'interface_type': _field(interfaces[0], 'InterfaceType', required=True),
                             'interface_address': _field(interfaces[0], 'InterfaceAddress'),
                             'units': sorted(units, key=lambda u: u['address']),
                             'applications': sorted(_address(a, 255) for a in _children(node, 'Application'))})
        data = {'project': name, 'networks': sorted(networks, key=lambda n: n['address'])}
        return cls(_canonical(data), hashlib.sha256(payload).hexdigest())

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != {'format', 'source_sha256', 'facts', 'facts_sha256'} or data['format'] != TOPOLOGY_FORMAT:
            raise WirelessConnectionError('Invalid topology document')
        result = cls(_canonical(data['facts']), data['source_sha256'])
        if data['facts_sha256'] != result.fingerprint:
            raise WirelessConnectionError('Topology fingerprint mismatch')
        return result

    @property
    def facts(self):
        return json.loads(self.document)

    @property
    def fingerprint(self):
        return hashlib.sha256(self.document.encode()).hexdigest()

    def as_dict(self):
        return {'format': TOPOLOGY_FORMAT, 'source_sha256': self.source_sha256,
                'facts_sha256': self.fingerprint, 'facts': self.facts}

    def selected(self, source_network, unit_address):
        _byte(source_network, 'Source network'); _byte(unit_address, 'Gateway address')
        nets = {n['address']: n for n in self.facts['networks']}
        if source_network not in nets:
            raise WirelessConnectionError('Missing gateway source network')
        units = {u['address']: u for u in nets[source_network]['units']}
        if unit_address not in units:
            raise WirelessConnectionError('Missing selected gateway unit')
        unit = units[unit_address]
        try:
            check_profile(unit['unit_type'], unit['firmware'], unit['catalog_number'] or None)
        except ValueError as error:
            raise WirelessConnectionError('Unsupported Connection profile: ' + str(error)) from error
        return nets, units[unit_address]

    def routes(self, source_network, unit_address):
        """Directional actual bridge-unit addresses; never synthesize reverse edges."""
        nets, _ = self.selected(source_network, unit_address)
        if unit_address == source_network or unit_address not in nets:
            raise WirelessConnectionError('Missing or self-linked adjacent network')
        routes, active = {}, {source_network}

        def explore(address, previous, path):
            if address in active:
                raise WirelessConnectionError('Cyclic forwarding topology')
            if address in routes:
                raise WirelessConnectionError('Ambiguous forwarding topology: multiple routes')
            routes[address] = path
            active.add(address)
            for unit in nets[address]['units']:
                kind, target = unit['unit_type'], unit['address']
                if kind not in ALL_BRIDGE_TYPES:
                    continue
                # Original exploration pre-seeds the source; a real return half
                # to the preceding network is not a new forward transition.
                if target == source_network and path:
                    raise WirelessConnectionError('Cyclic forwarding topology returns to source network')
                if target in (source_network, previous):
                    continue
                if kind not in BRIDGE_TYPES:
                    raise WirelessConnectionError('Unsupported forwarding bridge profile: ' + kind)
                if target not in nets:
                    raise WirelessConnectionError('Missing forwarding network ' + str(target))
                explore(target, address, path + (target,))
            active.remove(address)

        explore(unit_address, source_network, ())
        return routes


def loaded_route(current, topology):
    """Original load validates every entry, then chooses the contiguous prefix.

    This is a diagnostic projection only: it never rewrites a malformed tail.
    """
    known = {n['address'] for n in topology.facts['networks']}
    stored = tuple(current['ForwardingRoute'])[1:] if current['ForwardingMode'] == (1,) else (255,) * 6
    bridges = tuple(n if n in known else 255 for n in stored)
    prefix = []
    for network in bridges:
        if network == 255:
            break
        prefix.append(network)
    return {'bridge_addresses': list(bridges), 'destination_network': prefix[-1] if prefix else None,
            'stored_route_preserved': True}


def encode_route(bridges):
    """Only contiguous 1..5-hop routes with a first-unused sentinel are admitted."""
    if not bridges:
        return (255,) * 7
    if len(bridges) > 5:
        raise WirelessConnectionError('Six-entry forwarding route has unverified original header behavior; at most five are admitted')
    return (9 * (len(bridges) + 1), *bridges, *((255,) * (6 - len(bridges))))


@dataclass(frozen=True)
class WirelessConnectionPlan:
    expected: dict
    changes: dict
    topology: FrozenTopology
    source_network: int
    unit_address: int
    identity: tuple
    options: dict

    def __post_init__(self):
        try:
            for field in ('expected', 'changes'):
                object.__setattr__(self, field, MappingProxyType({k: tuple(v) for k, v in getattr(self, field).items()}))
            object.__setattr__(self, 'identity', tuple(self.identity))
            object.__setattr__(self, 'options', MappingProxyType(dict(self.options)))
        except (TypeError, AttributeError) as error:
            raise WirelessConnectionError('Invalid Connection plan collections') from error

    def as_dict(self):
        return {'format': PLAN_FORMAT, 'unit_type': self.identity[0], 'firmware': self.identity[1],
                'catalog_number': self.identity[2], 'spec_filename': SPEC_FILENAME,
                'source_network': self.source_network, 'unit_address': self.unit_address,
                'topology': self.topology.as_dict(), 'options': dict(self.options),
                'expected': {k: list(v) for k, v in self.expected.items()},
                'changes': {k: list(v) for k, v in self.changes.items()},
                'saved': False, 'device_verified': False, 'original_toolkit_executed': False,
                'whole_dialog_save_executed': False, 'physical_forwarding_verified': False}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get('format') != PLAN_FORMAT:
            raise WirelessConnectionError('Expected ' + PLAN_FORMAT)
        try:
            result = cls(data['expected'], data['changes'], FrozenTopology.from_dict(data['topology']),
                         data['source_network'], data['unit_address'],
                         (data['unit_type'], data['firmware'], data.get('catalog_number')), data['options'])
            result.validate()
            return result
        except (KeyError, TypeError, AttributeError) as error:
            raise WirelessConnectionError('Incomplete Connection plan') from error

    def validate(self):
        if len(self.identity) != 3:
            raise WirelessConnectionError('Invalid plan identity')
        check_profile(*self.identity)
        if (type(self.topology) is not FrozenTopology
                or set(self.expected) != set(fields_for(self.identity[0])) or set(self.changes) - set(OWNED)):
            raise WirelessConnectionError('Plan contains fields outside Connection ownership')
        for name in fields_for(self.identity[0]):
            layout = LAYOUT[name]
            for values in (self.expected[name], self.changes.get(name, self.expected[name])):
                if len(values) != layout[1] or any(type(v) is not int or not 0 <= v <= (1 if layout[5] == 'bit' else 255) for v in values):
                    raise WirelessConnectionError('Invalid Connection parameter: ' + name)
        if set(self.options) - OPTION_NAMES:
            raise WirelessConnectionError('Unknown Connection options')
        updates = _planned(self.expected, self.topology, self.source_network, self.unit_address, self.identity, self.options)
        changes = {k: v for k, v in updates.items() if v != self.expected[k]}
        if dict(self.changes) != changes:
            raise WirelessConnectionError('Connection plan changes differ from its controls and topology')


def _planned(current, topology, source_network, unit_address, identity, options):
    nets, unit = topology.selected(source_network, unit_address)
    try:
        check_profile(*identity)
    except ValueError as error:
        raise WirelessConnectionError('Unsupported Connection profile: ' + str(error)) from error
    if identity[:2] != (unit['unit_type'], unit['firmware']) or (identity[2] or '') != unit['catalog_number']:
        raise WirelessConnectionError('Identity differs from frozen selected gateway')
    routes = topology.routes(source_network, unit_address)
    advanced = identity[0] == 'WGATE5F'
    if advanced and current['MapWirelessRemotes'] != (0,):
        raise WirelessConnectionError('Connection tab is hidden in Remote Switch mode')
    result = dict(current)
    apps = list(current['Application'])
    for i in (1, 2):
        if 'application' + str(i) in options:
            apps[i - 1] = _byte(options['application' + str(i)], 'Application ' + str(i), 255)
    editing_apps = 'application1' in options or 'application2' in options
    if editing_apps and apps[0] == 255:
        if 'application2' in options and apps[1] != 255:
            raise WirelessConnectionError('Application 2 is disabled while Application 1 is All Applications')
        apps[1] = 255
    for address in apps if editing_apps else ():
        if address in NON_GROUP_APPLICATIONS:
            raise WirelessConnectionError('Application is excluded by the original group-capable application selector')
        if address != 255 and address not in nets[source_network]['applications']:
            raise WirelessConnectionError('Missing selected application in frozen source network: ' + str(address))
    if advanced and tuple(apps) != current['Application']:
        # Original application change hooks run in all eight remote directors
        # and in the SceneManager, even while the Connection tab is visible.
        # Their group rebinding/object creation is outside this subset save.
        if any(v != 255 for v in current['SceneVectorOffset']):
            raise WirelessConnectionError('Application change requires the original scene dependency workflow')
        for remote in range(1, 9):
            if (current[f'RemoteIdentity{remote}'] != (255,) * 4
                    or any(current[f'KeySceneMask{remote}'])
                    or any(current[f'ApplicationSeconday{remote}'])
                    or any(v != 255 for v in current[f'GroupAddress{remote}'])):
                raise WirelessConnectionError('Application change requires the original remote mapping dependency workflow')
    result['Application'] = tuple(apps)
    if 'adjacent_network' in options:
        result['ApplicationConnectEnabled'] = (int(_boolean(options['adjacent_network'], 'Adjacent network')),)
    if 'synchronise_to_wired' in options:
        sync = _boolean(options['synchronise_to_wired'], 'Synchronise to wired')
        if sync and result['ApplicationConnectEnabled'] != (1,):
            raise WirelessConnectionError('Synchronise to wired is disabled without adjacent network connection')
        result['SynchroniseToWired'] = (int(sync),)
    if options.get('adjacent_network') is False:
        result['SynchroniseToWired'] = (0,)
    if 'destination_network' in options:
        destination = options['destination_network']
        bridges = ()
        if destination is not None:
            _byte(destination, 'Destination network')
            if destination in (source_network, unit_address):
                raise WirelessConnectionError('Remote destination must be beyond the adjacent network')
            if destination not in routes:
                raise WirelessConnectionError('Missing or unreachable directional destination network')
            bridges = routes[destination]
        result['ForwardingRoute'] = encode_route(bridges)
        result['ForwardingMode'] = (int(bool(bridges)),)
    if 'status_monitor_application' in options:
        monitor = _byte(options['status_monitor_application'], 'Status monitor application', 255)
        if monitor in NON_GROUP_APPLICATIONS:
            raise WirelessConnectionError('Status monitor application is excluded by the original group-capable selector')
        if monitor != 255 and monitor not in nets[source_network]['applications']:
            raise WirelessConnectionError('Missing status monitor application in frozen source network')
        result['StatusMonitorApplication'] = (monitor,)
    return result


class WirelessConnectionEditor:
    def __init__(self, spec):
        if spec.filename != SPEC_FILENAME:
            raise WirelessConnectionError('Use ' + SPEC_FILENAME + ' for the admitted WGATE5N/F Connection profiles')
        self.spec, self.codec = spec, MemoryCodec(spec)
        self._verify_layout(OWNED)

    def _verify_layout(self, fields):
        for name in fields:
            expected = LAYOUT[name]
            try:
                layout = self.codec.layout(name)
                actual = (layout.address, layout.array_size, layout.bit_size, layout.bit_address, layout.array_skip, layout.parameter.type)
            except Exception as error:  # noqa: BLE001 - malformed specifications fail closed
                raise WirelessConnectionError('Unsupported Connection layout: ' + name) from error
            if actual != expected:
                raise WirelessConnectionError('Unsupported Connection layout: ' + name)

    def snapshot(self, current, unit_type='WGATE5F'):
        result = {}
        for name in fields_for(unit_type):
            if name not in current:
                raise WirelessConnectionError('Missing current Connection parameter: ' + name)
            try:
                values = _numbers(current[name])
            except (ValueError, TypeError) as error:
                raise WirelessConnectionError('Invalid Connection parameter: ' + name) from error
            if not self.spec.get(name).validate_value(list(values))['valid']:
                raise WirelessConnectionError('Invalid Connection parameter: ' + name)
            result[name] = values
        return result

    def plan(self, current, *, topology, source_network, unit_address, identity=None, **options):
        if type(topology) is not FrozenTopology or set(options) - OPTION_NAMES:
            raise WirelessConnectionError('Use frozen topology and supported Connection options')
        _, unit = topology.selected(source_network, unit_address)
        if identity is None:
            identity = (unit['unit_type'], unit['firmware'], unit['catalog_number'] or None)
        check_profile(*identity)
        self._verify_layout(fields_for(identity[0]))
        original = self.snapshot(current, identity[0])
        updates = _planned(original, topology, source_network, unit_address, identity, options)
        changes = {k: v for k, v in updates.items() if v != original[k]}
        self.codec.encode_many(changes)
        return WirelessConnectionPlan(original, changes, topology, source_network, unit_address, identity, options)

    def show(self, current, *, topology, source_network, unit_address, identity=None):
        plan = self.plan(current, topology=topology, source_network=source_network, unit_address=unit_address, identity=identity)
        values = plan.expected
        return {'format': 'cbus-wireless-connection-v1', 'parameters': {k: list(v) for k, v in values.items()},
                'unit_type': plan.identity[0], 'advanced_controls_available': plan.identity[0] == 'WGATE5F',
                'application2_enabled': values['Application'][0] != 255,
                'synchronise_to_wired_enabled': bool(values['ApplicationConnectEnabled'][0]),
                'remote_destinations': sorted(n for n in topology.routes(source_network, unit_address) if n != unit_address),
                'loaded_route': loaded_route(values, topology), 'device_verified': False}

    def apply(self, session, plan, *, topology, exclusive_project=False):
        # Pure validation precedes all session I/O and rejects forged documents.
        if type(plan) is not WirelessConnectionPlan:
            raise WirelessConnectionError('Expected a Connection plan')
        plan.validate()
        if exclusive_project is not True:
            raise WirelessConnectionError('Connection apply requires exclusive project ownership')
        if type(topology) is not FrozenTopology or topology.fingerprint != plan.topology.fingerprint:
            raise WirelessConnectionError('Project topology changed since the Connection plan was created')
        project = topology.facts['project']
        network = f'//{project}/{plan.source_network}'
        source = f'/db{network}/p/{plan.unit_address}'
        if getattr(session, 'source', None) != source or getattr(session, 'lock_address', None) != network:
            raise WirelessConnectionError('Connection source and lock must exactly match the planned database gateway')
        identity = (session.unit_type, session.firmware, getattr(session, 'catalog_number', None))
        if identity != plan.identity:
            raise WirelessConnectionError('Native session identity differs from the Connection plan')
        self._verify_layout(fields_for(plan.identity[0]))
        self.codec.encode_many(plan.changes)
        verify_native_schema(session, self.spec, fields_for(plan.identity[0]), WirelessConnectionError)
        before = session.values()
        if self.snapshot(before, plan.identity[0]) != dict(plan.expected):
            raise WirelessConnectionError('PP parameters changed since the Connection plan was created')
        attempted = []
        try:
            for name in fields_for(plan.identity[0]):
                if name in plan.changes:
                    attempted.append(name)
                    session.set(name, ' '.join(map(str, plan.changes[name])))
            after = session.values()
            expected = {**plan.expected, **plan.changes}
            if self.snapshot(after, plan.identity[0]) != expected:
                raise WirelessConnectionError('Connection PP readback differs from the plan')
            if {k: v for k, v in before.items() if k not in OWNED} != {k: v for k, v in after.items() if k not in OWNED}:
                raise WirelessConnectionError('Unrelated gateway parameters changed during Connection staging')
        except (RuntimeError, OSError, ValueError) as error:
            raise WirelessConnectionApplyError(error, attempted) from error
        return {**plan.as_dict(), 'verified': True, 'unrelated_parameters_preserved': True}


def native_topology(session, plan, *, exclusive_project=False):
    """Read fresh consumed facts only from the exact owned, closed database project."""
    from .addressing import NetworkAddressing
    from .native import NativeDatabase
    from .programming import xml_text
    plan.validate()
    if exclusive_project is not True:
        raise WirelessConnectionError('Connection apply requires exclusive project ownership')
    project = plan.topology.facts['project']
    network = f'//{project}/{plan.source_network}'
    if session.source != f'/db{network}/p/{plan.unit_address}' or session.lock_address != network:
        raise WirelessConnectionError('Connection source and lock must exactly match the planned database gateway')
    client = session.programmer.client
    response = NativeDatabase(client).get('//' + project, xml=True)
    if response.code != 344:
        raise WirelessConnectionError('Native project XML response did not complete')
    topology = FrozenTopology.from_xml(xml_text(response).encode())
    if topology.fingerprint != plan.topology.fingerprint:
        raise WirelessConnectionError('Project topology changed since the Connection plan was created')
    guard = NetworkAddressing(client)
    for row in topology.facts['networks']:
        runtime = dict(guard._runtime('//' + project + '/' + str(row['address'])))
        if any(runtime.get(key) != value for key, value in (
                ('InterfaceState', 'closed'), ('TargetInterfaceState', 'closed'), ('SyncState', 'idle'))):
            raise WirelessConnectionError('Every project network must be closed with synchronization idle')
    return topology
