"""Native-project metadata for one bounded eDLT parent transaction.

The original Toolkit model resolves applications and groups while loading the
parent form.  This module admits one exact C-Gate ``DBGETXML`` project
snapshot, derives only the facts consumed by :mod:`edlt_lifecycle`, and plans
missing application/group records in deterministic address order.  Static
labels are PP data owned by the parent transaction; they are inventoried from
the same unit record and are never represented as database objects.

Project metadata and PP persistence are not one native atomic primitive.  The
native manager therefore creates a backup first, rolls back only before the PP
save boundary, and reports every later failure as potentially partial.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from uuid import uuid4
from xml.dom import Node

from .addressing import NetworkAddressing, _container
from .edlt import EdltError
from .edlt_activation import WAKE_MODES
from .edlt_lifecycle import FORMAT, LifecycleCache, LifecycleGroup
from .edlt_parent_transaction import EdltParentTransaction, normalize_operations
from .native import NativeDatabase, NativeProjects, _project
from .native_thermostat_schedule import _shape
from .programming import Programmer, database_address, xml_text
from .toolkit_database_csv_native import _byte, _children, _field, _oid, _path


PROFILE = 'cbus-native-edlt-parent-metadata-v1'
RESULT_FORMAT = 'cbus-native-edlt-parent-transaction-result-v1'
MAX_OBJECTS = 4096
APPLICATION_NAMES = MappingProxyType({
    56: 'Lighting', 202: 'Trigger Control', 203: 'Enable Control',
})


def _json(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _error(error):
    try:
        message = str(error)
    except BaseException:
        message = '<unprintable>'
    return {'type': type(error).__name__, 'message': message[:2048]}


def _name(value, label):
    if (type(value) is not str or not value or len(value) > 128
            or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(label + ' must be 1..128 trimmed characters without controls')
    value.encode('utf-8', 'strict')
    return value


def _unit_path(value):
    if type(value) is not str:
        raise ValueError('eDLT unit path must be text')
    if value.lower().startswith('/db/'):
        value = value[4:]
        if value.startswith('/'):
            value = '/' + value
    project, network, unit = _path(value)
    return f'//{project}/{network}/p/{unit}', project, network, unit


def _one_by_address(parent, kind, address):
    rows = [row for row in _children(parent, kind)
            if _byte(_field(row, 'Address'), kind + ' address') == address]
    if len(rows) != 1:
        raise ValueError('Expected exactly one native ' + kind + ' at address '
                         + str(address))
    return rows[0]


def _node_shape(node, *, exclude=frozenset()):
    attrs = sorted((node.attributes.item(index).name,
                    node.attributes.item(index).value)
                   for index in range(node.attributes.length))
    children = [_shape(child) for child in node.childNodes
                if not(child.nodeType == Node.ELEMENT_NODE
                       and child.tagName in exclude)]
    return _json((node.tagName, attrs, children))


def _pp_values(unit, editor):
    rows = _children(unit, 'PP')
    if len(rows) > 16384:
        raise ValueError('Native eDLT PP collection exceeds 16384 records')
    values = {}
    for row in rows:
        if (not row.hasAttribute('Name') or not row.hasAttribute('Value')
                or row.childNodes):
            raise ValueError('Native eDLT PP records require only Name and Value attributes')
        name = row.getAttribute('Name')
        if not name or name in values:
            raise ValueError('Native eDLT PP parameter names must be nonempty and unique')
        values[name] = row.getAttribute('Value')
    return editor.snapshot(values)


def _default_language(network):
    languages = _children(network, 'Languages')
    if len(languages) > 1:
        raise ValueError('Native network contains duplicate Languages collections')
    if not languages:
        return 1
    defaults = []
    for language in _children(languages[0], 'Language'):
        if _byte(_field(language, 'Address'), 'Language address') == 0:
            text = _field(language, 'TagValue')
            if re.fullmatch(r'0|[1-9][0-9]{0,2}', text) is None or int(text) > 255:
                raise ValueError('Native default language must be a canonical decimal byte')
            defaults.append(int(text))
    if len(defaults) > 1:
        raise ValueError('Native network contains duplicate default-language records')
    return defaults[0] if defaults else 1


@dataclass(frozen=True)
class NativeGroupRecord:
    application: int
    address: int
    kind: str
    oid: str
    tag: str
    levels: tuple[int, ...]
    dynamic_images: tuple[bool, ...] | None
    dynamic_images_known: bool
    shape: str


@dataclass(frozen=True)
class NativeApplicationRecord:
    address: int
    oid: str
    tag: str
    metadata: str
    groups: tuple[NativeGroupRecord, ...]


@dataclass(frozen=True)
class NativeEdltProjectSnapshot:
    project: str
    network: int
    unit: int
    unit_oid: str
    values: tuple[tuple[str, tuple[int, ...]], ...]
    project_metadata: str
    unit_metadata: str
    network_metadata: str
    other_networks: tuple[str, ...]
    other_units: tuple[str, ...]
    applications: tuple[NativeApplicationRecord, ...]

    def value_map(self):
        return dict(self.values)


def _tag_images(group, default_language):
    """Derive image presence only when project/built-in image lookup is irrelevant."""
    collections = _children(group, 'TagsDLT')
    if len(collections) > 1:
        raise ValueError('Native group contains duplicate TagsDLT collections')
    tags = [] if not collections else _children(collections[0], 'TagDLT')
    variants = {}
    for tag in tags:
        language = _field(tag, 'LanguageID')
        flavour = _field(tag, 'FlavourID')
        if (re.fullmatch(r'0|[1-9][0-9]{0,2}', language) is None
                or re.fullmatch(r'[1-4]', flavour) is None):
            raise ValueError('Native TagDLT language/flavour is outside the admitted profile')
        if int(language) != default_language:
            continue
        variant = int(flavour) - 1
        if variant in variants:
            raise ValueError('Native group contains duplicate default-language TagDLT variants')
        tag_type = _field(tag, 'TagType')
        _field(tag, 'TagValue')
        if tag_type not in ('', 'TEXT', 'DYNAMIC', 'FONT', 'ICON'):
            raise ValueError('Native TagDLT type is outside the admitted profile')
        variants[variant] = tag_type
    # InitialiseGroup always supplies four empty variants. TEXT and an empty
    # variant cannot have an Image. DYNAMIC/FONT depend on project image files;
    # ICON depends on Toolkit's local DLTP index, neither of which is present in
    # DBGETXML, so those states remain explicitly unknown.
    if any(value in ('DYNAMIC', 'FONT', 'ICON') for value in variants.values()):
        return None, False
    return (False, False, False, False), True


def _snapshot(text, unit_path, editor):
    unit_path, project_name, network_address, unit_address = _unit_path(unit_path)
    root = _container(text, 'Installation').documentElement
    projects = _children(root, 'Project')
    if len(projects) != 1 or _field(projects[0], 'Address') != project_name:
        raise ValueError('Native XML must contain exactly the selected project')
    project = projects[0]
    networks = _children(project, 'Network')
    addresses = [_byte(_field(node, 'Address'), 'Network address') for node in networks]
    if not addresses or len(addresses) != len(set(addresses)):
        raise ValueError('Native project networks must have unique byte addresses')
    network = _one_by_address(project, 'Network', network_address)
    units = _children(network, 'Unit')
    unit_addresses = [_byte(_field(node, 'Address'), 'Unit address') for node in units]
    if len(unit_addresses) != len(set(unit_addresses)):
        raise ValueError('Native network contains duplicate unit addresses')
    unit = _one_by_address(network, 'Unit', unit_address)
    if (_field(unit, 'UnitType'), _field(unit, 'FirmwareVersion'),
            _field(unit, 'CatalogNumber')) != ('KEYGL5', '5.5.00', '5055EDL'):
        raise ValueError('Native unit is not KEYGL5 / 5055EDL firmware 5.5.00')
    unit_oid = _oid(_field(unit, 'OID'))
    values = _pp_values(unit, editor)
    default_language = _default_language(network)

    applications = []
    app_addresses, identities = set(), {unit_oid}
    for application in _children(network, 'Application'):
        address = _byte(_field(application, 'Address'), 'Application address')
        if address == 255 or address in app_addresses:
            raise ValueError('Native applications must have unique addresses in 0..254')
        identity = _oid(_field(application, 'OID'))
        if identity in identities:
            raise ValueError('Native project metadata contains duplicate object identities')
        identities.add(identity); app_addresses.add(address)
        groups = []
        group_addresses = set()
        for group in [node for node in application.childNodes
                      if node.nodeType == Node.ELEMENT_NODE
                      and node.tagName in ('Group', 'NetVar')]:
            group_address = _byte(_field(group, 'Address'), 'Group address')
            if group_address == 255:
                # CBusApplication.ReadXmlData ignores stored address255 and
                # recreates one virtual <Unused> group in memory.
                continue
            if group_address in group_addresses:
                raise ValueError('Native application contains duplicate group addresses')
            group_identity = _oid(_field(group, 'OID'))
            if group_identity in identities:
                raise ValueError('Native project metadata contains duplicate object identities')
            identities.add(group_identity); group_addresses.add(group_address)
            level_addresses, level_ids = [], set()
            for level in _children(group, 'Level'):
                level_address = _byte(_field(level, 'Address'), 'Level address')
                level_identity = _oid(_field(level, 'OID'))
                if level_address in level_addresses or level_identity in identities or level_identity in level_ids:
                    raise ValueError('Native group contains duplicate level address or identity')
                identities.add(level_identity); level_ids.add(level_identity)
                level_addresses.append(level_address)
            images, known = _tag_images(group, default_language)
            groups.append(NativeGroupRecord(
                address, group_address, group.tagName, group_identity,
                _field(group, 'TagName'), tuple(sorted(level_addresses)),
                images, known, _json(_shape(group))))
        applications.append(NativeApplicationRecord(
            address, identity, _field(application, 'TagName'),
            _node_shape(application, exclude=frozenset(('Group', 'NetVar'))),
            tuple(sorted(groups, key=lambda row: row.address))))
    if len(identities) > MAX_OBJECTS:
        raise ValueError('Native eDLT metadata inventory exceeds 4096 objects')
    project_metadata = _node_shape(project, exclude=frozenset(('Network',)))
    unit_metadata = _node_shape(unit, exclude=frozenset(('PP',)))
    network_metadata = _node_shape(
        network, exclude=frozenset(('Application', 'Unit')))
    other_networks = tuple(
        _json(_shape(row)) for row in networks if row is not network)
    other_units = tuple(sorted(
        _json(_shape(row)) for row in units if row is not unit))
    return NativeEdltProjectSnapshot(
        project_name, network_address, unit_address, unit_oid,
        tuple(sorted(values.items())), project_metadata, unit_metadata,
        network_metadata, other_networks, other_units,
        tuple(sorted(applications, key=lambda row: row.address)))


def _operation_groups(values, operations):
    primary = 56 if values['PrimaryApplication'] == (255,) else values['PrimaryApplication'][0]
    secondary = values['SecondaryApplication'][0]
    facts = []
    mode, proximity_group = values['ProximityMode'][0], values['ProximityGroup'][0]
    for index, operation in enumerate(operations, 1):
        if operation['op'] == 'lighting':
            application = primary
            if operation.get('application', 'primary') == 'secondary':
                if secondary == 255:
                    raise EdltError('Secondary Lighting operation requires a configured secondary application')
                application = secondary
            facts.append((application, operation['group'],
                          f'operation {index} Lighting selected group'))
        elif operation['op'] == 'activation':
            if operation.get('wake_mode') is not None:
                mode = WAKE_MODES[operation['wake_mode']]
            if operation.get('group') is not None:
                proximity_group = operation['group']
            if mode in (2, 3) and proximity_group != 255:
                facts.append((202 if mode == 3 else primary, proximity_group,
                              f'operation {index} activation event group'))
    return tuple(facts)


@dataclass(frozen=True)
class MetadataCreation:
    kind: str
    application: int
    address: int
    name: str

    def as_dict(self):
        result = {'kind': self.kind, 'address': self.address, 'name': self.name}
        if self.kind != 'Application':
            result['application'] = self.application
        return result


@dataclass(frozen=True)
class NativeEdltParentPlan:
    unit: str
    before_xml: str
    snapshot: NativeEdltProjectSnapshot
    networks: tuple[str, ...]
    operations: tuple
    cache: LifecycleCache
    creations: tuple[MetadataCreation, ...]
    parent_plan: object
    requirements: str
    static_labels: str

    @property
    def mutation_required(self):
        return bool(self.creations or self.parent_plan.changes)

    def semantic_source(self):
        return (self.snapshot, self.operations, self.cache,
                self.creations, self.parent_plan.expected)

    def as_dict(self):
        return {
            'format': 'cbus-native-edlt-parent-metadata-plan-v1',
            'profile': PROFILE, 'unit': self.unit,
            'project_xml_sha256': _digest(self.before_xml),
            'parameters_sha256': _digest(_json({
                name: list(value) for name, value in self.snapshot.values})),
            'requirements': json.loads(self.requirements),
            'metadata_cache': self.cache.as_dict(),
            'metadata_provenance': 'one-admitted-native-project-xml-snapshot',
            'projected_cache_includes_planned_creations': True,
            'nested_parent_cache_role': ('issued projected cache; outer native '
                                         'manager owns metadata creation'),
            'static_labels': json.loads(self.static_labels),
            'planned_creations': [row.as_dict() for row in self.creations],
            'creation_order': ['Application address order',
                               'Group/NetVar application then address order'],
            'mutation_required': self.mutation_required,
            'parent_transaction': self.parent_plan.as_dict(),
            'closed_networks': list(self.networks),
            'caller_exclusive_project_required': True,
            'database_only': True,
            'batch_atomic': False,
            'atomic_boundary': ('C-Gate exposes separate DBADDSAFE, PP SAVE and '
                                'PROJECT SAVE operations; no cross-operation commit exists'),
            'rollback_before_pp_save': True,
            'rollback_after_pp_save_attempt': False,
            'project_images_loaded': False,
            'unresolved_image_metadata_rejected_when_consumed': True,
            'native_parent_form_executed': False,
            'physical_device_programmed': False,
        }


def _static_labels(values):
    rows = []
    for index in range(64):
        raw = bytes(values[f'StaticTextString{index}'])
        head = raw.split(b'\0', 1)[0]
        try:
            text = head.decode('utf-8')
        except UnicodeDecodeError:
            text = None
        rows.append({'index': index, 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                     'text': text})
    return _json({'complete': True, 'count': 64,
                  'source': 'selected Unit PP records in project XML',
                  'database_objects_created': False, 'labels': rows})


def plan_native_parent_metadata(text, unit_path, values, editor, operations,
                                *, networks=()):
    """Build the projected cache and parent plan without native I/O."""
    if type(editor) is not EdltParentTransaction:
        raise ValueError('Expected an EdltParentTransaction editor')
    operations = normalize_operations(operations)
    unit_path, _project_name, _network, _unit = _unit_path(unit_path)
    snapshot = _snapshot(text, unit_path, editor)
    supplied = editor.snapshot(values)
    if supplied != snapshot.value_map():
        raise ValueError('PP snapshot differs from the selected native project unit')
    requirements = editor.lifecycle.requirements(supplied).as_dict()
    required_apps = {row['application'] for row in requirements['applications']}
    group_reasons = {}
    requirement_rows = {}
    for row in requirements['groups']:
        key = (row['application'], row['group'])
        requirement_rows[key] = row
        group_reasons.setdefault(key, []).extend(row['facts']['exists'])
    for application, group, reason in _operation_groups(supplied, operations):
        required_apps.add(application)
        group_reasons.setdefault((application, group), []).append(reason)

    applications = {row.address: row for row in snapshot.applications}
    creations = []
    for address in sorted(required_apps):
        if address == 255:
            raise ValueError('Application255 is virtual and cannot satisfy parent metadata')
        if address not in applications:
            creations.append(MetadataCreation(
                'Application', address, address,
                APPLICATION_NAMES.get(address, 'Application ' + str(address))))
    cache_groups = []
    for (application, group), _reasons in sorted(group_reasons.items()):
        if application == 255:
            raise ValueError('Group metadata cannot belong to virtual application255')
        if group == 255:
            cache_groups.append(LifecycleGroup(application, 255, True,
                                               (False,) * 4, True, ()))
            continue
        app = applications.get(application)
        record = None if app is None else next(
            (row for row in app.groups if row.address == group), None)
        if record is None:
            requirement = requirement_rows.get((application, group), {})
            if requirement.get('facts', {}).get('complete_levels_if_present'):
                raise ValueError(
                    'Missing scene trigger metadata requires level creation, '
                    'which is outside the bounded parent metadata transaction: '
                    f'application {application} group {group}')
            kind = 'NetVar' if application == 203 else 'Group'
            creations.append(MetadataCreation(
                kind, application, group, 'Group ' + str(group)))
            cache_groups.append(LifecycleGroup(
                application, group, True, (False,) * 4, True, ()))
            continue
        requirement = requirement_rows.get((application, group), {})
        facts = requirement.get('facts', {})
        needs_images = bool(facts.get('dynamic_images_if_present'))
        if needs_images and not record.dynamic_images_known:
            raise ValueError(
                'Consumed dynamic image metadata is not derivable from DBGETXML; '
                f'application {application} group {group} requires project/DLTP images')
        levels = record.levels if facts.get('complete_levels_if_present') else None
        cache_groups.append(LifecycleGroup(
            application, group, True,
            record.dynamic_images if needs_images else None,
            needs_images, levels))
    creations = tuple(sorted(creations, key=lambda row: (
        0 if row.kind == 'Application' else 1, row.application, row.address)))
    if len(creations) > 512:
        raise ValueError('eDLT metadata plan exceeds 512 creations')
    cache = LifecycleCache(tuple(sorted(required_apps)), tuple(cache_groups))
    parent = editor.plan(supplied, metadata=cache, operations=operations)
    return NativeEdltParentPlan(
        unit_path, text, snapshot, tuple(networks), operations, cache,
        creations, parent, _json(requirements), _static_labels(supplied))


@dataclass(frozen=True)
class NativeEdltParentResult:
    document: str

    def as_dict(self):
        return json.loads(self.document)


class NativeEdltParentError(RuntimeError):
    def __init__(self, cause, result):
        self.cause, self.result = cause, result
        self.details = {'edlt_parent_metadata_evidence': result.as_dict()}
        super().__init__('Native eDLT parent transaction stopped: '
                         + _error(cause)['message'])


class NativeEdltParentTransaction:
    """Single-use database-only metadata plus PP transaction manager."""
    def __init__(self, client, editor, *, programmer=None):
        if type(editor) is not EdltParentTransaction:
            raise ValueError('Expected an EdltParentTransaction editor')
        self.client, self.editor = client, editor
        self.database, self.projects = NativeDatabase(client), NativeProjects(client)
        self.programmer = Programmer(client) if programmer is None else programmer
        self.network_guard = NetworkAddressing(client)
        self._plans, self._fingerprints, self._consumed = [], {}, set()
        self.last_result = None
        self._evidence = None

    def _start(self, operation):
        self.last_result = None
        self._evidence = {
            'format': RESULT_FORMAT, 'profile': PROFILE, 'operation': operation,
            'state': 'preconditions', 'complete': False, 'commands': [],
            'objects': [], 'backup_created': False,
            'saved': False, 'database_persistence': 'not-attempted',
            'metadata_mutation_attempted': False,
            'pp_mutation_attempted': False, 'pp_readback_verified': False,
            'pp_save_attempted': False, 'pp_save_confirmed': False,
            'pp_save_outcome_uncertain': False,
            'target_project_save_attempted': False,
            'target_project_save_confirmed': False,
            'target_project_save_outcome_uncertain': False,
            'persistence_verified': False, 'rollback_attempted': False,
            'rollback_verified': False, 'rollback_errors': [],
            'pp_state_uncertain': False, 'database_state_uncertain': False,
            'partial_failure_possible': False,
            'batch_atomic': False, 'automatic_retries': 0,
            'caller_exclusive_project_required': True,
            'server_project_edit_lock_acquired': False,
            'physical_device_programmed': False,
            'native_parent_form_executed': False,
        }

    def _finish(self):
        self.last_result = NativeEdltParentResult(_json(self._evidence))
        return self.last_result

    def _fail(self, error):
        pp_save_uncertain = (self._evidence['pp_save_attempted']
                             and not self._evidence['pp_save_confirmed'])
        project_save_uncertain = (
            self._evidence['target_project_save_attempted']
            and not self._evidence['target_project_save_confirmed'])
        rollback_uncertain = (
            (self._evidence['metadata_mutation_attempted']
             or self._evidence['pp_mutation_attempted'])
            and self._evidence['rollback_attempted']
            and not self._evidence['rollback_verified'])
        pp_uncertain = pp_save_uncertain or rollback_uncertain
        database_uncertain = (pp_save_uncertain or project_save_uncertain
                              or rollback_uncertain)
        partial = (self._evidence['pp_save_attempted']
                   or self._evidence['target_project_save_attempted']
                   or rollback_uncertain)
        if self._evidence['rollback_verified']:
            persistence = 'original-state-verified-after-rollback'
        elif (self._evidence['target_project_save_confirmed']
              and not self._evidence['persistence_verified']):
            persistence = 'save-confirmed-verification-incomplete'
        elif database_uncertain:
            persistence = 'uncertain'
        elif self._evidence['pp_save_confirmed']:
            persistence = 'pp-save-confirmed-project-persistence-incomplete'
        else:
            persistence = 'not-saved'
        self._evidence.update(
            complete=False, error=_error(error),
            state='uncertain' if database_uncertain else 'stopped',
            saved=False, database_persistence=persistence,
            pp_state_uncertain=pp_uncertain,
            database_state_uncertain=database_uncertain,
            pp_save_outcome_uncertain=pp_save_uncertain,
            target_project_save_outcome_uncertain=project_save_uncertain,
            partial_failure_possible=partial,
        )
        result = self._finish()
        if not isinstance(error, Exception):
            try:
                error.edlt_parent_metadata_evidence = result.as_dict()
            except BaseException:
                pass
            raise error
        raise NativeEdltParentError(error, result) from error

    def _xml(self, project):
        response = self.database.get('//' + project, xml=True)
        if response.code != 344:
            raise RuntimeError('Native project XML response did not complete')
        return xml_text(response)

    def _operation(self, action, project, other=None):
        row = {'command': 'PROJECT ' + action.upper(), 'attempted': True,
               'completed': False}
        self._evidence['commands'].append(row)
        result = self.projects.operation(action, project, other)
        row.update(completed=True, code=result.code)
        if result.code != 200 or len(result.lines) != 1:
            raise RuntimeError('Native project operation did not return one completion')
        return result

    def _closed_networks(self, project, text):
        root = _container(text, 'Installation').documentElement
        projects = _children(root, 'Project')
        if len(projects) != 1 or _field(projects[0], 'Address') != project:
            raise ValueError('Expected exactly the selected native project')
        paths = ['//' + project + '/' + str(_byte(
            _field(node, 'Address'), 'Network address'))
                 for node in _children(projects[0], 'Network')]
        if not paths or len(paths) != len(set(paths)):
            raise ValueError('Project must contain unique networks')
        for path in paths:
            runtime = dict(self.network_guard._runtime(path))
            if any(runtime.get(name) != value for name, value in (
                    ('InterfaceState', 'closed'),
                    ('TargetInterfaceState', 'closed'),
                    ('SyncState', 'idle'))):
                raise ValueError('Every project network must be closed with synchronization idle')
        return tuple(sorted(paths))

    def plan(self, unit, *, operations, exclusive_project=False):
        self._start('plan')
        try:
            if exclusive_project is not True:
                raise ValueError('Caller must exclusively own project editing/reloading')
            if len(self._plans) >= 16:
                raise ValueError('Use a new manager after sixteen issued plans')
            unit, project, _network, _address = _unit_path(unit)
            text = self._xml(project)
            networks = self._closed_networks(project, text)
            plan = plan_native_parent_metadata(
                text, unit, _snapshot(text, unit, self.editor).value_map(),
                self.editor, operations, networks=networks)
            self._plans.append(plan); self._fingerprints[id(plan)] = repr(plan)
            self._evidence.update(state='planned', complete=True,
                                  plan=plan.as_dict())
            self._finish()
            return plan
        except BaseException as error:
            self._fail(error)

    def _issued(self, plan):
        if (type(plan) is not NativeEdltParentPlan
                or not any(plan is row for row in self._plans)
                or self._fingerprints.get(id(plan)) != repr(plan)):
            raise ValueError('Use an unchanged native eDLT plan issued by this manager')

    def _fresh(self, plan, *, exact=False):
        text = self._xml(plan.snapshot.project)
        if self._closed_networks(plan.snapshot.project, text) != plan.networks:
            raise ValueError('Project network inventory changed since planning')
        current = plan_native_parent_metadata(
            text, plan.unit, plan.snapshot.value_map(), self.editor,
            plan.operations, networks=plan.networks)
        if exact and text != plan.before_xml:
            raise ValueError('Native project XML changed since planning')
        if current.semantic_source() != plan.semantic_source():
            raise ValueError('Native eDLT metadata or PP state changed since planning')
        return text

    def _add(self, plan, creation, known):
        if creation.kind == 'Application':
            parent = f'//{plan.snapshot.project}/{plan.snapshot.network}'
            kind = 'application'
        else:
            parent = (f'//{plan.snapshot.project}/{plan.snapshot.network}/'
                      f'{creation.application}')
            kind = creation.kind.lower()
        response = self.database.add(parent, kind, creation.address,
                                     _name(creation.name, 'Metadata name'))
        identities = [match[1].lower() for line in response.lines
                      if (match := re.fullmatch(
                          r'301[- ]OID=([0-9a-fA-F-]{36})', line))]
        if len(identities) != 1:
            raise RuntimeError('Created metadata did not return exactly one OID')
        identity = _oid(identities[0])
        if identity in known:
            raise RuntimeError('Created metadata returned an existing OID')
        known.add(identity)
        self._evidence['objects'].append({
            **creation.as_dict(), 'oid': identity, 'created': True})

    def _verify_created(self, plan, text):
        snapshot = _snapshot(text, plan.unit, self.editor)
        apps = {row.address: row for row in snapshot.applications}
        created = {(row['kind'], row.get('application'), row['address']): row
                   for row in self._evidence['objects']}
        initial_apps = {row.address: row for row in plan.snapshot.applications}
        expected_apps = set(initial_apps)
        expected_groups = {
            address: {group.address for group in row.groups}
            for address, row in initial_apps.items()}
        for creation in plan.creations:
            if creation.kind == 'Application':
                expected_apps.add(creation.address)
                expected_groups.setdefault(creation.address, set())
            else:
                expected_groups.setdefault(creation.application, set()).add(
                    creation.address)
        if set(apps) != expected_apps:
            raise RuntimeError('Native application inventory changed during the transaction')
        for address, expected in expected_groups.items():
            if {group.address for group in apps[address].groups} != expected:
                raise RuntimeError(
                    'Native group inventory changed during the transaction')
        for creation in plan.creations:
            receipt = created[(creation.kind,
                               None if creation.kind == 'Application'
                               else creation.application, creation.address)]
            if creation.kind == 'Application':
                row = apps.get(creation.address)
            else:
                app = apps.get(creation.application)
                row = None if app is None else next(
                    (item for item in app.groups
                     if item.address == creation.address), None)
            if (row is None or row.oid != receipt['oid']
                    or row.tag != creation.name
                    or (creation.kind != 'Application'
                        and row.kind != creation.kind)):
                raise RuntimeError('Created metadata differs after native readback')
        # Existing metadata and unrelated selected-unit fields must remain exact.
        for address, before in initial_apps.items():
            after = apps.get(address)
            if after is None or (after.oid, after.tag, after.metadata) != (
                    before.oid, before.tag, before.metadata):
                raise RuntimeError('Existing application metadata changed')
            after_groups = {row.address: row for row in after.groups}
            for group in before.groups:
                saved = after_groups.get(group.address)
                if saved is None or saved != group:
                    raise RuntimeError('Existing group metadata changed')
        if (snapshot.unit_oid != plan.snapshot.unit_oid
                or snapshot.project_metadata != plan.snapshot.project_metadata
                or snapshot.unit_metadata != plan.snapshot.unit_metadata
                or snapshot.network_metadata != plan.snapshot.network_metadata
                or snapshot.other_networks != plan.snapshot.other_networks
                or snapshot.other_units != plan.snapshot.other_units):
            raise RuntimeError('Unrelated native project/unit/network metadata changed')
        return snapshot

    def _rollback_pre_save(self, plan):
        self._evidence['rollback_attempted'] = True
        try:
            for row in reversed(self._evidence['objects']):
                row['rollback_delete_attempted'] = True
                self.database.delete('!' + row['oid'])
                row['rollback_delete_confirmed'] = True
            # Persist the inverse database operations, then reload the project
            # so verification observes the same native boundary as apply.
            self._operation('save', plan.snapshot.project)
            self._evidence['rollback_project_save_confirmed'] = True
            for action in ('close', 'load'):
                self._operation(action, plan.snapshot.project)
            text = self._xml(plan.snapshot.project)
            current = plan_native_parent_metadata(
                text, plan.unit, plan.snapshot.value_map(), self.editor,
                plan.operations, networks=plan.networks)
            if current.semantic_source() != plan.semantic_source():
                raise RuntimeError('Reload did not restore the admitted eDLT source')
            self._evidence['rollback_verified'] = True
        except BaseException as error:
            self._evidence['rollback_errors'].append(_error(error))

    def apply(self, plan, *, backup_project=None):
        self._start('apply')
        pp_save_attempted = False
        try:
            self._issued(plan)
            if id(plan) in self._consumed:
                raise ValueError('This plan already had an apply attempt')
            self._consumed.add(id(plan))
            backup = (_project(backup_project) if backup_project is not None
                      else 'B' + uuid4().hex[:7].upper())
            if backup.upper() == plan.snapshot.project.upper():
                raise ValueError('Backup project must differ from the edited project')
            self._evidence.update(plan=plan.as_dict(), backup_project=backup)
            self._fresh(plan, exact=True)
            self._evidence['state'] = 'backup'
            self._operation('save', plan.snapshot.project)
            self._evidence['backup_source_save_confirmed'] = True
            self._operation('copy', plan.snapshot.project, backup)
            self._evidence['backup_created'] = True
            self._fresh(plan)
            self._operation('use', plan.snapshot.project)
            known = {plan.snapshot.unit_oid}
            for app in plan.snapshot.applications:
                known.add(app.oid)
                for group in app.groups:
                    known.add(group.oid)
            if plan.creations:
                self._evidence.update(state='metadata',
                                      metadata_mutation_attempted=True)
            for creation in plan.creations:
                self._add(plan, creation, known)
            if plan.creations:
                self._verify_created(plan, self._xml(plan.snapshot.project))

            self._evidence.update(state='pp', pp_mutation_attempted=True)
            lock = f'//{plan.snapshot.project}/{plan.snapshot.network}'
            source = database_address(plan.unit)
            with self.programmer.load(lock, source) as session:
                if self.editor.snapshot(session.values()) != plan.snapshot.value_map():
                    raise ValueError('PP source changed after native metadata planning')
                result = self.editor.apply(session, plan.parent_plan)
                self._evidence['pp_readback_verified'] = bool(result.get('verified'))
                self._evidence['state'] = 'pp_save'
                self._evidence['pp_save_attempted'] = True
                pp_save_attempted = True
                session.save_to_source()
                self._evidence['pp_save_confirmed'] = True

            self._evidence.update(state='project_save',
                                  target_project_save_attempted=True)
            self._operation('save', plan.snapshot.project)
            self._evidence['target_project_save_confirmed'] = True
            for action in ('close', 'load'):
                self._operation(action, plan.snapshot.project)
            final_text = self._xml(plan.snapshot.project)
            final = self._verify_created(plan, final_text)
            expected = {**plan.parent_plan.expected, **plan.parent_plan.changes}
            if final.value_map() != expected:
                raise RuntimeError('Persisted native PP differs from the parent transaction')
            self._evidence.update(
                state='verified_saved', complete=True,
                saved=True,
                database_persistence='verified-after-project-reload',
                persistence_verified=True,
                existing_metadata_preserved=True,
                unrelated_unit_and_network_metadata_preserved=True,
                parameters_sha256=_digest(_json({
                    name: list(value) for name, value in final.values})),
            )
            return self._finish()
        except BaseException as error:
            if (not pp_save_attempted and self._evidence.get('backup_created')
                    and (self._evidence.get('metadata_mutation_attempted')
                         or self._evidence.get('pp_mutation_attempted'))):
                self._rollback_pre_save(plan)
            self._fail(error)
