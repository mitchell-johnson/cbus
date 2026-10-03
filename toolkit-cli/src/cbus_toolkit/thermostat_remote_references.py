"""Enabled thermostat remote references in one bounded settings transaction.

Raw candidate edits precede the recovered agent load, remote validators and
save projection. Missing reference objects are planned in getter order. The
native settings owner performs persistence; this module has no I/O. It does
not replay unrelated inherited HVAC allocation or GUI source-change callbacks.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from types import MappingProxyType
from typing import Mapping
from xml.dom import Node

from .addressing import _container
from .native_thermostat_schedule import _byte, _children, _field, _oid
from .native_thermostat_scheduling import _unit_path
from .thermostat_output_groups import (OUTPUT_FIELDS, OUTPUT_READ_FIELDS, OutputGroupModel,
    normalize_output_selections, normalize_output_operations)
from .thermostat_remote_levels import (RemoteLevelCreation, normalize_level_prompts, project_remote_levels)
from .thermostat_templates import FAMILIES, ThermostatTemplateError, family_for_unit_type
from .unitspec import UnitSpecError, UnitSpecStore, _integer

FORMAT = 'cbus-thermostat-remote-references-plan-v1'
SETBACK_FIELDS = ('RemoteSetbackControlSource', 'RemoteSetbackOnGroup', 'RemoteSetbackOffGroup')
SCHEDULE_GROUP_FIELDS = ('RemoteScheduleOnGroup', 'RemoteScheduleOffGroup', 'RemoteScheduleOverrideGroup')
PROGRAM_FIELDS = ('EvapProgramEnabled', 'NonEvapProgramEnabled')
REMOTE_EDIT_FIELDS = MappingProxyType({'basic': SETBACK_FIELDS,
    'programmable': SETBACK_FIELDS + SCHEDULE_GROUP_FIELDS})
REMOTE_READ_FIELDS = MappingProxyType({'basic': ('ApplicationNumber',) + SETBACK_FIELDS,
    'programmable': ('ApplicationNumber',) + SETBACK_FIELDS + SCHEDULE_GROUP_FIELDS
                    + ('RemoteScheduleEnable',) + PROGRAM_FIELDS})
MAX_PROJECT_BYTES = 16 * 1024 * 1024
MAX_OBJECTS = 16384


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _fail(message):
    raise ThermostatTemplateError(message)


def _canonical(node, *, config=False, unit_oid=None):
    """Full native shape, exempting only known save/reload representation changes."""
    if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
        return ('text', node.data)
    if node.nodeType == Node.COMMENT_NODE:
        return ('comment', node.data)
    if node.nodeType == Node.PROCESSING_INSTRUCTION_NODE:
        return ('instruction', node.target, node.data)
    if node.nodeType != Node.ELEMENT_NODE:
        _fail('Unsupported project metadata node')
    attrs = sorted((node.attributes.item(i).name, node.attributes.item(i).value)
                   for i in range(node.attributes.length))
    children, parameters = [], []
    selected = (node.tagName == 'Unit' and not node.namespaceURI and unit_oid is not None
                and _field(node, 'OID') == unit_oid)
    for child in node.childNodes:
        element = child.nodeType == Node.ELEMENT_NODE
        if element and config and child.tagName == 'OID' and not child.namespaceURI:
            continue
        if (element and node.tagName == 'Level' and child.tagName == 'TagsDLT'
                and not child.attributes.length and not child.childNodes):
            continue
        if selected and element and child.tagName == 'PP' and not child.namespaceURI and child.hasAttribute('Name'):
            parameters.append((child.getAttribute('Name'), _canonical(child)))
            continue
        children.append(_canonical(child, unit_oid=unit_oid, config=config or (
            element and node.tagName == 'Project' and child.tagName == 'Config' and not child.namespaceURI)))
    if selected:
        return (node.tagName, attrs, children, ('parameters', sorted(parameters)))
    return (node.tagName, attrs, children)


def _all_oids(root):
    """Require real graph identities and fence optional native Interface IDs."""
    required = frozenset(('Network', 'Application', 'Group', 'NetVar', 'Unit', 'Level'))
    result = []

    def visit(node):
        if node.nodeType != Node.ELEMENT_NODE:
            return
        if not node.namespaceURI and (node.tagName in required or node.tagName in ('Project', 'Interface')):
            rows = _children(node, 'OID')
            if len(rows) != 1 and (node.tagName in required or rows):
                _fail('Native ' + node.tagName + ' requires exactly one canonical object identity')
            if rows:
                result.append(_oid(_field(node, 'OID')))
        for child in node.childNodes:
            visit(child)

    visit(root)
    if len(result) != len(set(result)):
        _fail('Native project contains duplicate object identities')
    return tuple(result)


def _all_addresses(root):
    """Reject ambiguous real native collections, including unselected networks."""
    def visit(node):
        if node.nodeType != Node.ELEMENT_NODE:
            return
        if not node.namespaceURI:
            collections = {'Project': (('Network',),), 'Network': (('Unit',), ('Application',)),
                           'Application': (('Group', 'NetVar'),), 'Group': (('Level',),),
                           'NetVar': (('Level',),)}.get(node.tagName, ())
            for kinds in collections:
                rows = [child for child in _children(node)
                        if child.tagName in kinds and not child.namespaceURI]
                addresses = [_byte(_field(row, 'Address')) for row in rows]
                if len(addresses) != len(set(addresses)):
                    _fail('Duplicate native address in ' + '/'.join(kinds) + ' collection')
        for child in node.childNodes:
            visit(child)
    visit(root)


def _document(text):
    if type(text) is not str or len(text.encode('utf-8')) > MAX_PROJECT_BYTES:
        _fail('Supply one bounded complete native project XML snapshot')
    return _container(text, 'Installation')


def _scalar(node, name, *, optional=False):
    if optional and not _children(node, name):
        return None
    return _field(node, name)


def _address_rows(node, kind):
    rows = _children(node, kind)
    result = [(_byte(_field(row, 'Address')), row) for row in rows]
    if len(result) != len({address for address, _ in result}):
        _fail('Duplicate native ' + kind + ' address')
    return result


def _select(rows, address, label):
    matches = [row for value, row in rows if value == address]
    if len(matches) != 1:
        _fail('Expected exactly one selected ' + label)
    return matches[0]


@dataclass(frozen=True)
class RemoteLevel:
    address: int
    value: int
    identity: str
    name: str
    metadata: str

    def as_dict(self):
        return {'address': self.address, 'value': self.value, 'oid': self.identity,
                'name': self.name, 'metadata_sha256': _hash(self.metadata)}


@dataclass(frozen=True)
class RemoteGroup:
    application: int
    address: int
    identity: str
    name: str
    stored_kind: str
    metadata: str
    levels: tuple[RemoteLevel, ...] = ()

    def as_dict(self):
        return {'application': self.application, 'address': self.address, 'oid': self.identity,
                'name': self.name, 'stored_kind': self.stored_kind, 'metadata_sha256': _hash(self.metadata),
                'levels': [level.as_dict() for level in self.levels]}


@dataclass(frozen=True)
class RemoteApplication:
    address: int
    identity: str
    name: str
    groups: tuple[RemoteGroup, ...]
    metadata: str

    def as_dict(self):
        return {'address': self.address, 'oid': self.identity, 'name': self.name,
                'metadata_sha256': _hash(self.metadata), 'groups': [row.as_dict() for row in self.groups]}


@dataclass(frozen=True)
class ProjectGraphSnapshot:
    project: str
    network: int
    unit: int
    unit_path: str
    unit_identity: tuple[tuple[str, str | None], ...]
    applications: tuple[RemoteApplication, ...]
    all_oids: tuple[str, ...]
    shape: str
    xml_sha256: str

    @property
    def fingerprint(self):
        return _hash(self.shape)

    @property
    def object_oids(self):
        return self.all_oids

    def as_dict(self):
        return {'project': self.project, 'network': self.network, 'unit': self.unit,
                'unit_path': self.unit_path, 'identity': dict(self.unit_identity),
                'fingerprint': self.fingerprint, 'xml_sha256': self.xml_sha256,
                'all_oids': list(self.all_oids), 'applications': [a.as_dict() for a in self.applications]}


def _snapshot_project(text, unit_path):
    path, project_name, network_path, address = _unit_path(unit_path)
    network_address = int(network_path.rsplit('/', 1)[1])
    root = _document(text).documentElement
    _all_addresses(root)
    projects = _children(root, 'Project')
    if len(projects) != 1 or _field(projects[0], 'Address').upper() != project_name.upper():
        _fail('Native XML must contain exactly the selected project')
    project = projects[0]
    network = _select(_address_rows(project, 'Network'), network_address, 'network')
    unit = _select(_address_rows(network, 'Unit'), address, 'unit')
    identity = tuple((name, _scalar(unit, name, optional=name == 'CatalogNumber'))
                     for name in ('OID', 'UnitType', 'FirmwareVersion', 'CatalogNumber'))
    _oid(dict(identity)['OID'])
    family_for_unit_type(dict(identity)['UnitType'])
    if not dict(identity)['FirmwareVersion']:
        _fail('Thermostat firmware identity is missing')
    pp_names = [row.getAttribute('Name') for row in _children(unit, 'PP') if row.hasAttribute('Name')]
    if len(pp_names) != len(set(pp_names)):
        _fail('Selected unit contains duplicate PP parameters')
    oids = _all_oids(root)
    if len(oids) > MAX_OBJECTS:
        _fail('Native project graph exceeds the supported object bound')
    applications = []
    for app_address, application in _address_rows(network, 'Application'):
        if app_address == 255:
            _fail('Application address 255 is outside this remote graph profile')
        app_oid = _oid(_field(application, 'OID'))
        groups, addresses = [], set()
        for group in _children(application):
            if group.tagName not in ('Group', 'NetVar') or group.namespaceURI:
                continue
            group_address = _byte(_field(group, 'Address'))
            if group_address in addresses:
                _fail('Duplicate native group address within application ' + str(app_address))
            addresses.add(group_address)
            group_oid = _oid(_field(group, 'OID'))
            levels = []
            for level_address, level in _address_rows(group, 'Level'):
                if not level.hasAttribute('Value'):
                    _fail('Native Level requires an independent Value attribute')
                levels.append(RemoteLevel(level_address, _byte(level.getAttribute('Value')),
                    _oid(_field(level, 'OID')), _field(level, 'TagName'), _json(_canonical(level))))
            groups.append(RemoteGroup(app_address, group_address, group_oid, _field(group, 'TagName'),
                                      group.tagName, _json(_canonical(group)), tuple(levels)))
        if len(groups) > 256:
            _fail('Remote group collection exceeds the byte address space')
        applications.append(RemoteApplication(app_address, app_oid, _field(application, 'TagName'),
                                              tuple(groups), _json(_canonical(application))))
    return ProjectGraphSnapshot(project_name, network_address, address, path, identity,
        tuple(applications), tuple(oids), _json(_canonical(root, unit_oid=dict(identity)['OID'])), _hash(text))


def snapshot_project(project_xml, unit_path):
    """Validate a complete graph and retain its complete preservation fingerprint."""
    try:
        return _snapshot_project(project_xml, unit_path)
    except ThermostatTemplateError:
        raise
    except (ValueError, KeyError, TypeError) as error:
        raise ThermostatTemplateError('Invalid thermostat project graph: ' + str(error)) from error


def project_fingerprint(project_xml, unit_path):
    return snapshot_project(project_xml, unit_path).fingerprint


@dataclass(frozen=True)
class RemoteCreation:
    kind: str
    application: int
    address: int
    name: str
    reason: str
    output_add: bool = False

    @property
    def action(self):
        return 'create'

    @property
    def key(self):
        return self.kind, self.application, self.address

    def as_dict(self):
        value = {'kind': self.kind, 'application': self.application, 'address': self.address,
                 'name': self.name, 'reason': self.reason}
        if self.output_add:
            value['output_add'] = self.output_add
        return value


@dataclass(frozen=True)
class RemoteGroupRename:
    application: int
    address: int
    identity: str
    previous_name: str
    name: str
    reason: str
    output_edit: bool = False

    @property
    def kind(self):
        return 'Group'

    @property
    def action(self):
        return 'rename'

    @property
    def key(self):
        return 'Group', self.application, self.address

    def as_dict(self):
        value = {'action': self.action, 'kind': self.kind, 'application': self.application,
                'address': self.address, 'identity': self.identity, 'previous_name': self.previous_name,
                'name': self.name, 'reason': self.reason}
        if self.output_edit:
            value['output_edit'] = self.output_edit
        return value


class _GraphResolver:
    """One causal inventory for inherited setback, output and schedule getters."""

    def __init__(self, graph):
        self.apps = {app.address: app for app in graph.applications}
        self.live = {(app.address, group.address): group for app in graph.applications for group in app.groups}
        self.operations = []
        self.getters = []

    def application(self, address, reason, enable_application=True, *, creation_name=None):
        created = address not in self.apps
        if created:
            if address != 203 and creation_name is None:
                _fail('The selected ApplicationNumber application must already exist')
            name = 'Enable Control' if creation_name is None else creation_name
            self.apps[address] = RemoteApplication(address, f'planned-application:{address}', name, (), '')
            self.operations.append(RemoteCreation('Application', address, address, name, reason))
        self.getters.append({'getter': 'GetEnableControlApplication' if enable_application else 'ApplicationObject',
            'application': address, 'identity': self.apps[address].identity, 'created': created})
        return self.apps[address]

    def group(self, address, value, create, role, *, enable_application=True):
        app = self.application(address, role, enable_application)
        found = self.live.get((address, value))
        created = found is None and create
        if created:
            prefix = {172: 'Communication Group ', 203: 'Enable Network Variable '}.get(address, 'Group ')
            name = '<Unused>' if value == 255 else prefix + str(value)
            found = self.create(address, value, name, role)
        self.getters.append({'getter': 'GroupByAddress', 'role': role, 'application': address,
            'application_identity': app.identity, 'address': value, 'create': create,
            'identity': found.identity if found else None, 'created': created})
        return found

    def create(self, application, address, name, reason, *, output_add=False):
        if (application, address) in self.live:
            _fail('Planned group address is already occupied')
        if sum(key[0] == application for key in self.live) >= 256:
            _fail('Group capacity prevents resolving ' + reason)
        group = RemoteGroup(application, address, f'planned-group:{application}:{address}', name, 'Group', '')
        self.live[application, address] = group
        self.operations.append(RemoteCreation('Group', application, address, name, reason, output_add))
        return group

    def rename(self, group, name, reason, *, output_edit=False):
        current = self.live[group.application, group.address]
        if current.identity != group.identity:
            _fail('Group identity changed inside the shared resolver')
        if current.name != name:
            self.operations.append(RemoteGroupRename(group.application, group.address, group.identity,
                                                     current.name, name, reason, output_edit))
            current = replace(current, name=name)
            self.live[group.application, group.address] = current
        return current

    def current(self, group):
        return None if group is None else self.live[group.application, group.address]


@dataclass(frozen=True)
class RemoteReferencePlan:
    family: str
    unit_type: str
    before: tuple[tuple[str, str], ...]
    edits: tuple[tuple[str, int], ...]
    project_xml: str
    graph: ProjectGraphSnapshot
    owned_values: tuple[tuple[str, int], ...]
    creations: tuple[RemoteCreation, ...]
    getters_json: str
    roles_json: str
    validation_json: str
    schema_json: str
    level_prompts: tuple[tuple[str, str], ...]
    level_creations: tuple[RemoteLevelCreation, ...]
    level_prompts_json: str
    output_selections: tuple[tuple[str, int], ...] | None = None
    output_values: tuple[tuple[str, int], ...] = ()
    output_projection_json: str = 'null'
    graph_operations: tuple[RemoteCreation | RemoteGroupRename, ...] = ()
    output_operations: tuple[str, ...] | None = None

    @property
    def output_requested_parameters(self):
        """Explicit writes in request order, excluding direct cancellation."""
        if self.output_operations is None:
            return tuple(dict.fromkeys(name for name, _address in self.output_selections or ()))
        rows = [json.loads(row) for row in self.output_operations]
        return tuple(dict.fromkeys(row['parameter'] for row in rows
            if row['op'] == 'select-output-group'
            or row['op'] == 'add-output-group' and row['outcome'] == 'accept'))

    @property
    def output_expected(self):
        return dict(self.output_values)

    @property
    def renames(self):
        return tuple(row for row in self.graph_operations if type(row) is RemoteGroupRename)

    @property
    def expected(self):
        return dict(self.owned_values)

    @property
    def changed_parameters(self):
        before = dict(self.before)
        return [{'name': name, 'before': _integer(before[name]), 'after': value}
                for name, value in self.owned_values if _integer(before[name]) != value]

    @property
    def pp_mutation_required(self):
        return bool(self.changed_parameters)

    @property
    def graph_mutation_required(self):
        return bool(self.creations or self.level_creations or self.renames)

    @property
    def apply_would_mutate(self):
        return self.pp_mutation_required or self.graph_mutation_required

    def semantic_source(self):
        value = {'before': self.before, 'identity': self.graph.unit_identity,
                      'graph': self.graph.fingerprint, 'edits': self.edits, 'schema': self.schema_json,
                      'level_prompts': self.level_prompts, 'output_selections': self.output_selections}
        if self.output_operations is not None:
            value['output_operations'] = self.output_operations
        return _json(value)

    def as_dict(self):
        result = {'format': FORMAT, 'family': self.family, 'unit_type': self.unit_type,
                'requested': dict(self.edits), 'expected': self.expected,
                'changed_parameters': self.changed_parameters,
                'project_graph': self.graph.as_dict(),
                'planned_creations': [row.as_dict() for row in self.creations],
                'graph_operations': [row.as_dict() | {'action': row.action} for row in self.graph_operations],
                'planned_renames': [row.as_dict() for row in self.renames],
                'output_selections': None if self.output_selections is None else [
                    {'parameter': name, 'address': address} for name, address in self.output_selections],
                'output_projection': json.loads(self.output_projection_json),
                'planned_level_creations': [row.as_dict() for row in self.level_creations],
                'level_prompts': json.loads(self.level_prompts_json),
                'getters': json.loads(self.getters_json), 'resolved_roles': json.loads(self.roles_json),
                'remote_validation': json.loads(self.validation_json),
                'pp_mutation_required': self.pp_mutation_required,
                'graph_mutation_required': self.graph_mutation_required,
                'apply_would_mutate': self.apply_would_mutate,
                'level_creation_policy': 'explicit-optional-prompt-responses',
                'level_projection': 'final-records-with-inherited-prompt-and-role-order',
                'original_level_storage_callbacks_reproduced': False,
                'existing_levels_preserved': True, 'complete_form_lifecycle_reproduced': False,
                'gui_source_change_callbacks_reproduced': False, 'physical_device_programmed': False,
                'saved': False}
        if self.output_operations is not None:
            result['output_operations'] = [json.loads(row) for row in self.output_operations]
        return result


def _byte_parameter(spec, name, value):
    parameter = spec.parameters.get(name)
    if (parameter is None or parameter.type != 'int' or parameter.array_size != 1 or parameter.bit_size != 8):
        _fail('Unit specification lacks one-byte remote dependency: ' + name)
    if type(value) not in (int, str):
        _fail('Thermostat setting must be an integer: ' + name)
    checked = parameter.validate_value(value if type(value) is str else str(value))
    if not checked['valid']:
        _fail(name + ': ' + '; '.join(checked['errors']))
    parsed = checked['parsed']
    if type(parsed) is not int or not 0 <= parsed <= 255:
        _fail('Thermostat parameter must fit one unsigned byte: ' + name)
    return parsed


def plan_remote_references(store, unit_type, snapshot, edits, *, project_xml, unit_path, level_prompts=None,
                           output_selections=None, output_operations=None):
    """Project all remote fields from one candidate and its authoritative graph.

    Ordinary edits are consumed for the same candidate as the owning settings
    plan, but only remote fields and program-enable normalization are returned.
    """
    try:
        return _plan(store, unit_type, snapshot, edits, project_xml=project_xml, unit_path=unit_path,
                     level_prompts=level_prompts, output_selections=output_selections,
                     output_operations=output_operations)
    except ThermostatTemplateError:
        raise
    except (ValueError, KeyError, TypeError, UnitSpecError) as error:
        raise ThermostatTemplateError('Invalid thermostat remote reference plan: ' + str(error)) from error


def _plan(store, unit_type, snapshot, edits, *, project_xml, unit_path, level_prompts=None,
          output_selections=None, output_operations=None):
    if not isinstance(store, UnitSpecStore):
        _fail('Remote reference planning requires a decoded UnitSpecStore')
    family = family_for_unit_type(unit_type)
    prompts = normalize_level_prompts(level_prompts, family)
    if output_selections is not None and output_operations is not None:
        _fail('Output selections and output operations are mutually exclusive')
    selections = normalize_output_selections(output_selections)
    operations = normalize_output_operations(output_operations)
    output_active = selections is not None or operations is not None
    spec = store.load(FAMILIES[family]['unit_spec'])
    if spec.unit_type != {'basic': 'THERMOSTATB', 'programmable': 'THERMOSTATA'}[family]:
        _fail('Decoded thermostat specification identity differs from the selected family')
    if not isinstance(snapshot, Mapping) or any(type(k) is not str or type(v) is not str for k, v in snapshot.items()):
        _fail('Full thermostat snapshot must map parameter names to raw native value strings')
    if not isinstance(edits, Mapping):
        _fail('Thermostat edits must be a parameter mapping')
    parsed_edits = {}
    for name, value in edits.items():
        # Ordinary edits are already admitted by the owning settings planner.
        # Validate their scalar/schema domain here without importing that owner
        # (which composes this projection). This component never writes them.
        if (type(name) is not str or name == 'ApplicationNumber' or name in OUTPUT_FIELDS
                or (name.startswith('Remote') and name not in REMOTE_EDIT_FIELDS[family])
                or (family == 'basic' and name in PROGRAM_FIELDS)):
            _fail('Setting is not admitted for ' + unit_type + ': ' + str(name))
        if name not in snapshot:
            _fail('Full thermostat snapshot lacks edited parameter: ' + name)
        parsed_edits[name] = _byte_parameter(spec, name, value)
    values = {}
    schema = {}
    read_fields = tuple(dict.fromkeys(REMOTE_READ_FIELDS[family]
        + (OUTPUT_READ_FIELDS if output_active else ())))
    for name in read_fields:
        if name not in snapshot:
            _fail('Full thermostat snapshot lacks remote dependency: ' + name)
        values[name] = _byte_parameter(spec, name, snapshot[name])
        p = spec.get(name)
        schema[name] = {key: p.fields.get(key, default) for key, default in (
            ('Type', 'int'), ('Address', None), ('ArraySize', '1'), ('BitSize', '8'),
            ('BitAddress', '0'), ('ArraySkip', '0'))}
    values.update(parsed_edits)
    source = values['RemoteSetbackControlSource']
    if source > 2:
        _fail('RemoteSetbackControlSource must be 0..2; larger values leave unresolved save references')
    graph = snapshot_project(project_xml, unit_path)
    project_tag_name = None
    if operations is not None and any(json.loads(row).get('outcome') == 'accept' for row in operations):
        project = _children(_document(project_xml).documentElement, 'Project')[0]
        tags = _children(project, 'TagName')
        if len(tags) != 1 or tags[0].namespaceURI:
            _fail('Accepted output Add/Edit requires an explicit scalar Project.TagName')
        project_tag_name = _field(project, 'TagName')
    if dict(graph.unit_identity)['UnitType'] != unit_type:
        _fail('Project thermostat identity differs from the selected unit type')
    if not spec.supports_version(dict(graph.unit_identity)['FirmwareVersion']):
        _fail('Thermostat firmware is outside the decoded specification bounds')
    _, stored_unit = _selected_unit(_document(project_xml).documentElement, unit_path)
    for row in _children(stored_unit, 'PP'):
        name = row.getAttribute('Name')
        if name in read_fields:
            if (not row.hasAttribute('Value')
                    or _byte_parameter(spec, name, row.getAttribute('Value'))
                    != _byte_parameter(spec, name, snapshot[name])):
                _fail('Stored project PP differs from the supplied remote snapshot: ' + name)
    schema = {'parameters': schema, 'spec_filename': spec.filename,
              'metadata': {key: spec.metadata.get(key, '') for key in ('Type', 'MinVersion', 'MaxVersion')}}
    resolver = _GraphResolver(graph)
    apps, live = resolver.apps, resolver.live
    group = resolver.group
    getters = resolver.getters
    output = OutputGroupModel(values, family, unit_type, resolver) if output_active else None
    if selections is not None:
        for name, address in selections:
            _byte_parameter(spec, name, address)

    references = {}
    if source:
        app_address = 203 if source == 2 else values['ApplicationNumber']
        if source == 1 and not (48 <= app_address <= 95 or app_address == 203):
            _fail('Source 1 admits existing Lighting applications 48..95 or Enable Control 203')
        if source == 1 and app_address not in apps:
            _fail('Source 1 requires its selected ApplicationNumber application to exist')
        for name, role in zip(SETBACK_FIELDS[1:], ('setback_on', 'setback_off')):
            references[role] = group(app_address, values[name], True, role, enable_application=source == 2)
    else:
        references.update(setback_on=None, setback_off=None)
    expected = {name: values[name] for name in SETBACK_FIELDS}
    if source == 0:
        expected.update(RemoteSetbackOnGroup=30, RemoteSetbackOffGroup=31)
    if output is not None:
        output.load()
    enabled = False
    if family == 'programmable':
        evap = values['EvapProgramEnabled'] if values['EvapProgramEnabled'] <= 1 else 0
        nonevap = values['NonEvapProgramEnabled'] if values['NonEvapProgramEnabled'] <= 1 else 1
        enabled = bool(evap or nonevap)
        expected.update(EvapProgramEnabled=evap, NonEvapProgramEnabled=nonevap, RemoteScheduleEnable=int(enabled))
        for name, role, default in zip(SCHEDULE_GROUP_FIELDS, ('schedule_on', 'schedule_off', 'schedule_override'), (32, 33, 34)):
            references[role] = group(203, values[name] if enabled else 255, enabled, role)
            expected[name] = values[name] if enabled else default

    # Explicit group choices happen after the inherited and derived agents
    # have finished loading. Names may have changed on an earlier reference;
    # refresh immutable references from the one causal inventory before any
    # role or optional-Level receipts are emitted.
    references = {role: resolver.current(value) for role, value in references.items()}
    if output is not None:
        if operations is not None:
            output.operate(operations, project_tag_name=project_tag_name,
                           validate_address=lambda parameter, address: _byte_parameter(spec, parameter, address))
        else:
            output.select(selections)
        output.validate()
        expected.update(output.expected)
    references = {role: resolver.current(value) for role, value in references.items()}

    def unique(roles, label):
        selected = [references[role] for role in roles if references[role] is not None and references[role].address != 255]
        identities = [(row.application, row.identity) for row in selected]
        if len(identities) != len(set(identities)):
            _fail('Original remote validation rejects duplicate ' + label + ' group identities')

    unique(('setback_on', 'setback_off'), 'setback')
    if source and not any(references[role] is not None and references[role].address != 255
                          for role in ('setback_on', 'setback_off')):
        _fail('Original remote validation requires at least one non-unused setback group')
    if family == 'programmable':
        schedule = ('schedule_on', 'schedule_off', 'schedule_override')
        unique(schedule, 'schedule')
        if enabled and any(references[role] is None or references[role].address == 255 for role in schedule):
            _fail('Original enabled schedule validation rejects every unused or unresolved role')
        unique(schedule + ('setback_on', 'setback_off'), 'schedule/setback')
    roles = {name: None if value is None else {
        'application': value.application, 'address': value.address, 'identity': value.identity,
        'unused': value.address == 255} for name, value in references.items()}
    for name, value in expected.items():
        _byte_parameter(spec, name, value)
    level_creations, prompt_receipts = project_remote_levels(references, family=family,
        setback_source=source, schedule_enabled=enabled, prompts=prompts)
    creations = tuple(row for row in resolver.operations if type(row) is RemoteCreation)
    if len(graph.all_oids) + len(creations) + len(level_creations) > MAX_OBJECTS:
        _fail('Planned remote graph exceeds the supported object bound')
    validation = {'passed': True, 'setback_source': source, 'schedule_enabled': enabled,
        'duplicate_nonunused_identities_rejected': True, 'one_unused_setback_permitted': True,
        'enabled_schedule_unused_roles_rejected': family == 'programmable',
        'cross_role_identity_validation': family == 'programmable',
        'optional_missing_level_additions': dict(prompts), 'complete_parent_validation_reproduced': False,
        'all_reference_validation_precedes_mutation': True,
        'original_validation_failure_prefix_reproduced': False}
    return RemoteReferencePlan(family, unit_type, tuple(sorted(snapshot.items())), tuple(sorted(parsed_edits.items())),
        project_xml, graph, tuple(sorted(expected.items())), tuple(creations), _json(getters), _json(roles),
        _json(validation), _json(schema), prompts, level_creations, _json(prompt_receipts), selections,
        tuple(sorted(output.expected.items())) if output is not None else (),
        _json(output.as_dict()) if output is not None else 'null', tuple(resolver.operations), operations)


def validate_remote_plan(store, plan):
    """Replay every bound input before the native owner starts mutations."""
    if type(plan) is not RemoteReferencePlan:
        _fail('Expected an issued thermostat remote reference plan')
    if any(type(row) is RemoteCreation and (type(row.output_add) is not bool
            or row.output_add and row.kind != 'Group') for row in (*plan.creations, *plan.graph_operations)):
        _fail('Malformed output Add creation provenance')
    if any(type(row) is RemoteGroupRename and type(row.output_edit) is not bool
            for row in plan.graph_operations):
        _fail('Malformed output Edit rename provenance')
    try:
        if plan.output_operations is not None and (type(plan.output_operations) is not tuple
                or any(type(row) is not str for row in plan.output_operations)):
            _fail('Output operations must retain the issued immutable history')
        operations = None if plan.output_operations is None else [json.loads(row) for row in plan.output_operations]
    except (ValueError, TypeError) as error:
        raise ThermostatTemplateError('Invalid thermostat output operation history') from error
    rebuilt = plan_remote_references(store, plan.unit_type, dict(plan.before), dict(plan.edits),
        project_xml=plan.project_xml, unit_path=plan.graph.unit_path, level_prompts=dict(plan.level_prompts),
        output_selections=None if plan.output_selections is None else [
            {'parameter': name, 'address': address} for name, address in plan.output_selections],
        output_operations=operations)
    if rebuilt != plan or _json(rebuilt.as_dict()) != _json(plan.as_dict()):
        _fail('Thermostat remote plan differs from its complete deterministic replay')
    return plan


def _selected_unit(root, path):
    _, project_name, network_path, address = _unit_path(path)
    project = _children(root, 'Project')[0]
    if _field(project, 'Address').upper() != project_name.upper():
        _fail('Preservation project differs')
    network = _select(_address_rows(project, 'Network'), int(network_path.rsplit('/', 1)[1]), 'network')
    unit = _select(_address_rows(network, 'Unit'), address, 'unit')
    return network, unit


def _normalize_owned_pp(old_root, new_root, path, names):
    _, old_unit = _selected_unit(old_root, path)
    network, new_unit = _selected_unit(new_root, path)
    old = {row.getAttribute('Name'): row for row in _children(old_unit, 'PP') if row.hasAttribute('Name')}
    new = {row.getAttribute('Name'): row for row in _children(new_unit, 'PP') if row.hasAttribute('Name')}
    for name in names:
        before, after = old.get(name), new.get(name)
        if before is not None:
            if after is None or not after.hasAttribute('Value'):
                _fail('Owned stored PP parameter disappeared: ' + name)
            # Preserve every other attribute and child, including extensions.
            before.setAttribute('Value', '<owned-value>')
            after.setAttribute('Value', '<owned-value>')
        elif after is not None:
            attrs = {after.attributes.item(i).name for i in range(after.attributes.length)}
            if attrs != {'Name', 'Value'} or after.childNodes:
                _fail('Newly stored PP parameter has unplanned metadata: ' + name)
            new_unit.removeChild(after)
    return network


def _graph_operation_names(before, operations, created_oids):
    """Replay names and identities without allowing a rename to mask other data."""
    if type(operations) is not tuple:
        _fail('Graph operations must be the issued immutable create/rename history')
    current = {('Application', app.address, app.address): (app.identity, app.name)
               for app in before.applications}
    current.update({('Group', app.address, group.address): (group.identity, group.name)
                    for app in before.applications for group in app.groups})
    added, renamed = set(), {}
    for row in operations:
        if type(row) not in (RemoteCreation, RemoteGroupRename):
            _fail('Unknown graph operation record')
        if (type(row.application) is not int or type(row.address) is not int
                or not 0 <= row.application <= 254 or not 0 <= row.address <= 255
                or type(row.name) is not str or type(row.reason) is not str):
            _fail('Malformed graph operation')
        key = row.key
        if type(row) is RemoteCreation:
            if type(row.output_add) is not bool or row.output_add and row.kind != 'Group':
                _fail('Malformed output Add creation provenance')
            if row.kind not in ('Application', 'Group') or key in current or key in added:
                _fail('Graph creation collides with an existing or already created object')
            if row.kind == 'Application' and row.application != row.address:
                _fail('Application creation address differs from its application')
            if row.kind == 'Group' and ('Application', row.application, row.application) not in current:
                _fail('Graph group creation precedes its owning application')
            identity = (f'planned-application:{row.address}' if row.kind == 'Application'
                        else f'planned-group:{row.application}:{row.address}')
            current[key] = identity, row.name
            added.add(key)
        else:
            if type(row.output_edit) is not bool:
                _fail('Malformed output Edit rename provenance')
            if (type(row.identity) is not str or type(row.previous_name) is not str
                    or current.get(key) != (row.identity, row.previous_name)):
                _fail('Group rename differs from its preceding identity or name')
            current[key] = row.identity, row.name
            if key not in added:
                if key not in renamed:
                    renamed[key] = (row.identity, row.previous_name, row.name)
                else:
                    renamed[key] = (*renamed[key][:2], row.name)
    if added != set(created_oids):
        _fail('Created object receipts differ from the graph operation history')
    return {key: name for key, (_identity, name) in current.items() if key in added}, renamed


def _mask_group_name(node):
    rows = _children(node, 'TagName')
    if len(rows) != 1 or any(child.nodeType not in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE)
                             for child in rows[0].childNodes):
        _fail('A renamed group TagName contains unplanned structured metadata')
    tag = rows[0]
    for child in tuple(tag.childNodes):
        tag.removeChild(child)
    tag.appendChild(tag.ownerDocument.createTextNode('<owned-group-name>'))


def verify_project_preservation(before_xml, after_xml, unit_path, *, changed_parameters, created_oids,
                                created_level_oids=None, level_creations=(), graph_operations=()):
    """Compare the whole graph after removing exactly the admitted mutation set.

    ``created_oids`` maps (command kind, application, address) to returned OID.
    Group creates under 203 may serialize as Group or NetVar; retained kinds
    and all retained metadata remain exact. Changed PP readback belongs to the
    owning PP session; this helper preserves every other stored parameter.
    ``created_level_oids`` maps (application, group, address) to returned OID,
    with exact final records supplied by the replayed ``level_creations``.
    ``graph_operations`` is the issued ordered creation/rename history; its
    presence admits only exact final names after replaying each old name.
    """
    try:
        before, after = snapshot_project(before_xml, unit_path), snapshot_project(after_xml, unit_path)
        if created_level_oids is None:
            created_level_oids = {}
        if not isinstance(created_oids, Mapping) or not isinstance(changed_parameters, (Mapping, tuple, list, set, frozenset)):
            _fail('Preservation requires explicit changed parameter names and creation receipts')
        if (not isinstance(created_level_oids, Mapping) or type(level_creations) is not tuple
                or any(type(row) is not RemoteLevelCreation for row in level_creations)):
            _fail('Preservation requires exact planned Level records and creation receipts')
        planned_levels = {row.key: row for row in level_creations}
        if len(planned_levels) != len(level_creations) or set(planned_levels) != set(created_level_oids):
            _fail('Created Level receipts differ from the planned Level records')
        if any(type(name) is not str for name in changed_parameters):
            _fail('Changed parameter names must be text')
        names = set(changed_parameters)
        all_created_ids = tuple(created_oids.values()) + tuple(created_level_oids.values())
        if len(set(all_created_ids)) != len(all_created_ids):
            _fail('Created object receipts contain duplicate OIDs')
        for key, oid in created_oids.items():
            if (type(key) is not tuple or len(key) != 3 or key[0] not in ('Application', 'Group')
                    or type(key[1]) is not int or type(key[2]) is not int):
                _fail('Malformed remote creation receipt key')
            _oid(oid)
            if oid in before.all_oids:
                _fail('Created object receipt reused an original OID')
        for key, oid in created_level_oids.items():
            if (type(key) is not tuple or len(key) != 3
                    or any(type(value) is not int for value in key)
                    or not 0 <= key[0] <= 254 or not 0 <= key[1] <= 254 or not 1 <= key[2] <= 31):
                _fail('Malformed remote Level creation receipt key')
            _oid(oid)
            if oid in before.all_oids:
                _fail('Created Level receipt reused an original OID')
        final_names, renamed = (_graph_operation_names(before, graph_operations, created_oids)
                                if graph_operations else ({}, {}))
        old_root, new_root = _document(before_xml).documentElement, _document(after_xml).documentElement
        network = _normalize_owned_pp(old_root, new_root, unit_path, names)
        applications = dict(_address_rows(network, 'Application'))
        rows, remove, level_rows, rename_rows = [], [], [], []
        old_network, _ = _selected_unit(old_root, unit_path)
        old_apps = dict(_address_rows(old_network, 'Application'))
        for key, (identity, previous_name, final_name) in renamed.items():
            _, application, address = key
            pair = []
            for inventory in (old_apps, applications):
                if application not in inventory:
                    _fail('Renamed group application disappeared')
                matches = [node for node in _children(inventory[application])
                    if node.tagName in ('Group', 'NetVar') and not node.namespaceURI
                    and _byte(_field(node, 'Address')) == address]
                if len(matches) != 1 or _field(matches[0], 'OID') != identity:
                    _fail('Renamed group identity differs from the plan')
                pair.append(matches[0])
            if _field(pair[0], 'TagName') != previous_name or _field(pair[1], 'TagName') != final_name:
                _fail('Renamed group name differs from the ordered graph projection')
            for node in pair:
                _mask_group_name(node)
            rename_rows.append({'application': application, 'address': address, 'oid': identity,
                                'previous_name': previous_name, 'name': final_name})
        # Verify/remove exact Levels first so a newly created parent cannot
        # hide an unplanned Level. All old Level metadata stays in the graph.
        for key, oid in created_level_oids.items():
            application, group_address, address = key
            planned = planned_levels[key]
            if application not in applications:
                _fail('Created Level application is missing from readback')
            parent_app = applications[application]
            groups = [row for row in _children(parent_app) if row.tagName in ('Group', 'NetVar')
                      and not row.namespaceURI and _byte(_field(row, 'Address')) == group_address]
            if len(groups) != 1:
                _fail('Created Level parent group is missing or duplicated')
            parent = groups[0]
            group_oid = created_oids.get(('Group', application, group_address), planned.group_identity)
            if _field(parent, 'OID') != group_oid:
                _fail('Created Level parent identity differs from the planned group')
            level = _select(_address_rows(parent, 'Level'), address, 'created Level')
            if (_field(level, 'OID') != oid or _byte(level.getAttribute('Value')) != planned.value
                    or _field(level, 'TagName') != planned.name):
                _fail('Created Level identity, Value or name differs from its planned record')
            level_rows.append({**planned.as_dict(), 'oid': oid, 'parent_oid': group_oid})
            parent.removeChild(level)
        # Resolve and verify all receipts before removing parent applications.
        for (kind, application, address), oid in created_oids.items():
            if application not in applications:
                _fail('Created application is missing from readback')
            parent = applications[application]
            if kind == 'Application':
                if not graph_operations and (application != 203 or address != 203):
                    _fail('Unexpected application creation')
                node, name = parent, 'Enable Control'
            else:
                groups = [row for row in _children(parent) if row.tagName in ('Group', 'NetVar')
                          and not row.namespaceURI and _byte(_field(row, 'Address')) == address]
                if len(groups) != 1:
                    _fail('Created remote group is missing or duplicated')
                node = groups[0]
                if node.tagName == 'NetVar' and application != 203:
                    _fail('Unexpected native group serialization kind')
                name = '<Unused>' if address == 255 else ('Enable Network Variable ' if application == 203 else 'Group ') + str(address)
                if _children(node, 'Level'):
                    _fail('Created remote group contains unplanned Levels')
            name = final_names.get((kind, application, address), name)
            if _field(node, 'OID') != oid or _field(node, 'TagName') != name:
                _fail('Created remote object identity or name differs from its receipt')
            rows.append({'kind': kind, 'application': application, 'address': address, 'oid': oid,
                         'stored_kind': node.tagName})
            remove.append(node)
        removed_ids = set(all_created_ids)
        if set(after.all_oids) != set(before.all_oids) | removed_ids:
            _fail('Unexpected added or removed project object identities')
        # Parent removal must not conceal unplanned groups or levels.
        for (kind, app, _address), oid in created_oids.items():
            if kind == 'Application':
                parent = applications[app]
                descendants = _all_oids(parent)
                if set(descendants) - removed_ids:
                    _fail('Created application contains an unplanned child object')
        for node in reversed(remove):
            if node.parentNode is not None:
                node.parentNode.removeChild(node)
        unit_oid = dict(before.unit_identity)['OID']
        if _json(_canonical(old_root, unit_oid=unit_oid)) != _json(_canonical(new_root, unit_oid=unit_oid)):
            _fail('Unrelated project, unit, application, group or level metadata changed')
        return {'preserved': True, 'existing_metadata_preserved': True, 'unit_record_preserved': True,
                'unknown_project_data_preserved': True, 'created_objects': rows,
                'created_levels': level_rows, 'renamed_groups': rename_rows,
                'config_oid_normalization_ignored': True, 'empty_level_tags_dlt_normalization_ignored': True,
                'selected_unit_pp_collection_order_ignored': True}
    except ThermostatTemplateError:
        raise
    except (ValueError, KeyError, TypeError) as error:
        raise ThermostatTemplateError('Thermostat project preservation failed: ' + str(error)) from error
