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
from .dlt_profiles import require
from .edlt import EdltError, _field as _pp_field
from .edlt_activation import WAKE_MODES
from .edlt_add_dialog import resolve as resolve_add_dialogs
from .edlt_application_cache import (
    ApplicationCache,
    CachedDisplay,
    CachedGroupList,
)
from .edlt_display_model import (
    EdltDisplayPreferences,
    evidence as display_evidence,
    present_application_cache,
)
from .edlt_dltp_index import DltpIndex
from .edlt_lifecycle import FORMAT, LifecycleCache, LifecycleGroup
from .edlt_parent_transaction import (
    EdltParentTransaction, _DYNAMIC_FIELD_OFFSETS, _SETTING_FIELDS,
    _candidate_widget, normalize_operations,
)
from .native import NativeDatabase, NativeProjects, _project
from .native_thermostat_schedule import _project_shape, _shape
from .programming import Programmer, database_address, xml_text
from .toolkit_database_csv_native import _byte, _children, _field, _oid, _path


PROFILE = 'cbus-native-edlt-parent-metadata-v1'
RESULT_FORMAT = 'cbus-native-edlt-parent-transaction-result-v1'
MAX_OBJECTS = 4096
APPLICATION_NAMES = MappingProxyType({
    56: 'Lighting', 172: 'Air Conditioning', 202: 'Trigger Control',
    203: 'Enable Control',
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
    return editor.snapshot(values), values


def _default_language(network):
    languages = _children(network, 'Languages')
    if len(languages) > 1:
        raise ValueError('Native network contains duplicate Languages collections')
    if not languages:
        return 1
    rows = _children(languages[0], 'Language')
    if not rows:
        return 1
    defaults = []
    definitions = set()
    for language in rows:
        # LanguageTypeDescriptor uses ID, unlike addressed C-Bus objects.
        # ID 0 stores the selected language ID in its TagValue.
        identifier = _byte(_field(language, 'ID'), 'Language ID')
        if identifier == 0:
            text = _field(language, 'TagValue')
            if re.fullmatch(r'0|[1-9][0-9]{0,2}', text) is None or int(text) > 255:
                raise ValueError('Native default language must be a canonical decimal byte')
            defaults.append(int(text))
        else:
            if identifier in definitions:
                raise ValueError('Native network contains duplicate language IDs')
            definitions.add(identifier)
    if len(defaults) > 1:
        raise ValueError('Native network contains duplicate default-language records')
    # A nonempty collection without an explicit default depends on the
    # original model's prior process state. A metadata-only default can also
    # be normalized during the original load. Neither is established by this
    # snapshot, so do not infer the language used for image/label facts.
    if not defaults:
        raise ValueError('A nonempty native Languages collection requires one default-language record')
    selected = defaults[0]
    if selected == 0 or selected not in definitions:
        raise ValueError('Native default language requires a matching nonzero language definition')
    return selected


@dataclass(frozen=True)
class NativeLevelRecord:
    application: int
    group: int
    address: int
    value: int
    oid: str
    tag: str
    dynamic_labels: tuple[tuple[str, str, bool], ...] | None
    dynamic_labels_known: bool
    shape: str


@dataclass(frozen=True)
class NativeGroupRecord:
    application: int
    address: int
    kind: str
    oid: str
    tag: str
    metadata: str
    levels: tuple[int, ...]
    level_records: tuple[NativeLevelRecord, ...]
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
    raw_values: tuple[tuple[str, str], ...]
    project_metadata: str
    unit_metadata: str
    network_metadata: str
    other_networks: tuple[str, ...]
    other_units: tuple[str, ...]
    applications: tuple[NativeApplicationRecord, ...]
    dltp_index: DltpIndex | None = None

    def value_map(self):
        return dict(self.values)

    def raw_map(self):
        return dict(self.raw_values)


def _dynamic_labels(node, default_language, dltp_index=None):
    """Derive the four original DataStore rows when image lookup is resolvable."""
    collections = _children(node, 'TagsDLT')
    if len(collections) > 1:
        raise ValueError('Native metadata contains duplicate TagsDLT collections')
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
            raise ValueError('Native metadata contains duplicate default-language TagDLT variants')
        tag_type = _field(tag, 'TagType')
        tag_value = _field(tag, 'TagValue')
        if len(tag_value) > 1024:
            raise ValueError('Native TagDLT value exceeds 1024 characters')
        if tag_type not in ('', 'TEXT', 'DYNAMIC', 'FONT', 'ICON'):
            raise ValueError('Native TagDLT type is outside the admitted profile')
        variants[variant] = (tag_type, tag_value)
    # InitialiseGroup always supplies four empty variants. TEXT and an empty
    # variant cannot have an Image. DYNAMIC/FONT depend on project image files
    # that DBGETXML does not carry, so those states remain explicitly unknown.
    # ICON depends on Toolkit's local DLTP index: TagDLT.PopulateImage matches
    # the exact key text when a SHA-256-bound index is supplied.
    unresolved = ('DYNAMIC', 'FONT') + (('ICON',) if dltp_index is None else ())
    if any(value[0] in unresolved for value in variants.values()):
        return None, False
    rows = []
    for variant in range(4):
        tag_type, tag_value = variants.get(variant, ('', ''))
        rows.append((str(variant), tag_value,
                     tag_type == 'ICON' and dltp_index.image_present(tag_value)))
    return tuple(rows), True


def _tag_images(group, default_language, dltp_index=None):
    """Derive image presence only when image lookup is resolvable."""
    labels, known = _dynamic_labels(group, default_language, dltp_index)
    if not known:
        return None, False
    return tuple(row[2] for row in labels), True


def _snapshot(text, unit_path, editor, *, dltp_index=None):
    if dltp_index is not None and type(dltp_index) is not DltpIndex:
        raise ValueError('A DLTP index must come from load_dltp_index')
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
    require('edlt-parent-metadata', _field(unit, 'UnitType'), _field(unit, 'FirmwareVersion'),
            _field(unit, 'CatalogNumber'), error=ValueError,
            message='Native unit is not KEYGL5 / 5055EDL firmware 5.5.00')
    unit_oid = _oid(_field(unit, 'OID'))
    values, raw_values = _pp_values(unit, editor)
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
            level_records, level_ids = [], set()
            for level in _children(group, 'Level'):
                level_address = _byte(_field(level, 'Address'), 'Level address')
                if (not level.hasAttribute('Value')
                        or re.fullmatch(r'0|[1-9][0-9]{0,2}',
                                        level.getAttribute('Value')) is None
                        or int(level.getAttribute('Value')) > 255):
                    raise ValueError(
                        'Native level Value must be a canonical decimal byte')
                level_value = int(level.getAttribute('Value'))
                level_identity = _oid(_field(level, 'OID'))
                if (any(row.address == level_address for row in level_records)
                        or level_identity in identities or level_identity in level_ids):
                    raise ValueError('Native group contains duplicate level address or identity')
                identities.add(level_identity); level_ids.add(level_identity)
                labels, labels_known = _dynamic_labels(
                    level, default_language, dltp_index)
                level_records.append(NativeLevelRecord(
                    address, group_address, level_address, level_value,
                    level_identity,
                    _field(level, 'TagName'), labels, labels_known,
                    _json(_shape(level))))
            level_records = tuple(level_records)
            images, known = _tag_images(group, default_language, dltp_index)
            groups.append(NativeGroupRecord(
                address, group_address, group.tagName, group_identity,
                _field(group, 'TagName'),
                _node_shape(group, exclude=frozenset(('Level',))),
                tuple(row.address for row in level_records), level_records,
                images, known, _json(_shape(group))))
        applications.append(NativeApplicationRecord(
            address, identity, _field(application, 'TagName'),
            _node_shape(application, exclude=frozenset(('Group', 'NetVar'))),
            tuple(groups)))
    if len(identities) > MAX_OBJECTS:
        raise ValueError('Native eDLT metadata inventory exceeds 4096 objects')
    project_metadata = _json(_project_shape(project))
    unit_metadata = _node_shape(unit, exclude=frozenset(('PP',)))
    network_metadata = _node_shape(
        network, exclude=frozenset(('Application', 'Unit')))
    other_networks = tuple(
        _json(_shape(row)) for row in networks if row is not network)
    other_units = tuple(sorted(
        _json(_shape(row)) for row in units if row is not unit))
    return NativeEdltProjectSnapshot(
        project_name, network_address, unit_address, unit_oid,
        tuple(sorted(values.items())), tuple(sorted(raw_values.items())),
        project_metadata, unit_metadata,
        network_metadata, other_networks, other_units,
        tuple(applications), dltp_index)


def _operation_groups(values, operations):
    primary = 56 if values['PrimaryApplication'] == (255,) else values['PrimaryApplication'][0]
    secondary = values['SecondaryApplication'][0]
    facts = []
    mode, proximity_group = values['ProximityMode'][0], values['ProximityGroup'][0]
    colour_groups = {
        'active_screen_group': 'BacklightActiveBrightnessControlGroup',
        'idle_screen_group': 'BacklightIdleBrightnessControlGroup',
        'active_indicator_group': 'IndicatorActiveBrightnessControlGroup',
        'idle_indicator_group': 'IndicatorIdleBrightnessControlGroup',
        'indicator_on_group': 'IndicatorOnColourControlGroup',
        'indicator_off_group': 'IndicatorOffColourControlGroup',
    }
    dynamic_widget_types = {
        'lighting': 2, 'enable': 14, 'fan': 4, 'multilevel': 16,
        'room-courtesy': 15, 'scene': 6, 'shutter': 3, 'timer': 5,
    }

    navigation = values['NavWidgetType'][0]

    def effective(operation, name, default):
        value = operation.get(name)
        return default if value is None else value

    def needs_images(operation):
        explicit = any(operation.get(name) in ('dynamic-text', 'dynamic-icon')
                       for name in ('label_type', 'status_type'))
        widget = _candidate_widget(
            operation, {**values, 'NavWidgetType': (navigation,)})
        if (widget is None or values[_pp_field(widget)][0] !=
                dynamic_widget_types.get(operation['op'])):
            return explicit
        control = values[_pp_field(widget, 1)][0]
        displays = _DYNAMIC_FIELD_OFFSETS.get(operation['op'], {})
        label = operation.get('label_type')
        if operation.get('label_text') is not None:
            label = 'static'
        label_dynamic = ('label' in displays and (
            ((control >> 4) & 7) in (1, 2) if label is None else
            label in ('dynamic-text', 'dynamic-icon')))
        status = operation.get('status_type')
        if operation.get('status_text') is not None:
            status = 'static'
        status_dynamic = ('status' in displays and (
            (control & 15) in (6, 7) if status is None else
            status in ('dynamic-text', 'dynamic-icon')))
        return explicit or label_dynamic or status_dynamic

    def add(application, group, reason, *, images=False):
        facts.append((application, group, reason, images))

    for index, operation in enumerate(operations, 1):
        kind = operation['op']
        page_mode = operation.get('page_mode')
        if page_mode is not None:
            navigation = 1 if page_mode == 'multiple' else 0
        if kind in ('lighting', 'fan', 'multilevel', 'room-courtesy',
                    'shutter', 'timer'):
            application = primary
            if operation.get('application', 'primary') == 'secondary':
                if secondary == 255:
                    raise EdltError(
                        'Secondary ' + kind + ' operation requires a configured '
                        'secondary application')
                application = secondary
            add(application, operation['group'],
                f'operation {index} {kind} selected group',
                images=needs_images(operation))
        elif kind == 'enable':
            add(203, operation['variable'],
                f'operation {index} Enable selected variable',
                images=needs_images(operation))
        elif kind == 'hvac':
            add(172, operation['group'],
                f'operation {index} HVAC communication group')
        elif kind == 'scene':
            if needs_images(operation):
                bucket = values['SceneBucket']
                slots = (operation.get('scenes', ())
                         if operation.get('mode') == 'cycle'
                         else (operation.get('scene'),))
                for slot in slots:
                    if type(slot) is not int or not 1 <= slot <= 8:
                        continue
                    pointer = values[f'Scene{slot}StartAddress'][0]
                    if pointer >= len(bucket) or bucket[pointer] == 255:
                        continue
                    trigger = bucket[pointer + 2]
                    if trigger != 255:
                        add(202, trigger,
                            f'operation {index} Scene{slot} dynamic binding',
                            images=True)
        elif kind == 'activation':
            if operation.get('wake_mode') is not None:
                mode = WAKE_MODES[operation['wake_mode']]
            if operation.get('group') is not None:
                proximity_group = operation['group']
            if mode in (2, 3) and proximity_group != 255:
                add(202 if mode == 3 else primary, proximity_group,
                    f'operation {index} activation event group')
        elif kind == 'colours':
            for option, parameter in colour_groups.items():
                group = effective(operation, option, values[parameter][0])
                if group != 255:
                    add(primary, group,
                        f'operation {index} colours {option}')
        elif kind == 'navigation':
            variant_names = {
                'time': 0, 'date': 1, 'time-date': 2,
                'time-temperature': 3, 'date-temperature': 4,
                'logo': 5, 'page-names': 6, 'dynamic-labels': 7,
                'blank': 15,
            }
            source_names = {'measurement': 0, 'hvac': 1}
            variant = variant_names.get(operation.get('variant'),
                                        values['NavWidgetVariant'][0])
            source = source_names.get(operation.get('temperature_source'),
                                      values['TemperatureApplication'][0])
            device_or_group = effective(
                operation, 'device_or_group', values['NavDevIDZoneGroup'][0])
            dynamic_group = effective(
                operation, 'dynamic_group', values['DynamicGroup'][0])
            if variant in (3, 4) and source == 1 and device_or_group != 255:
                add(172, device_or_group,
                    f'operation {index} navigation HVAC group')
            if variant in (5, 7) and dynamic_group != 255:
                add(primary, dynamic_group,
                    f'operation {index} navigation dynamic group', images=True)
        elif kind == 'quick-status':
            group = effective(operation, 'group', values['QuickStatusGroup'][0])
            if group != 255:
                add(primary, group,
                    f'operation {index} Quick Status group')
        elif kind == 'page-control':
            group = effective(operation, 'group', values['KeySetsEnableGroup'][0])
            if group != 255:
                add(203, group,
                    f'operation {index} Page Control group')
        elif kind == 'applications':
            # Later controls see the ordered application selections.  The
            # applications editor performs the authoritative validation; this
            # narrow projection only selects the application whose group fact
            # a later operation will consume.
            for edit in operation.get('edits', ()):
                if not isinstance(edit, dict):
                    continue
                address = edit.get('address')
                if type(address) is not int or not 0 <= address <= 255:
                    continue
                if edit.get('field') == 'primary':
                    primary = address
                elif edit.get('field') == 'secondary':
                    secondary = address
    return tuple(facts)


@dataclass(frozen=True)
class MetadataCreation:
    kind: str
    application: int
    address: int
    name: str
    group: int | None = None
    value: int | None = None
    safe_blank_variants: bool = False
    reasons: tuple[str, ...] = ()

    def as_dict(self):
        result = {'kind': self.kind, 'address': self.address, 'name': self.name}
        if self.kind != 'Application':
            result['application'] = self.application
        if self.kind == 'Level':
            result.update(group=self.group, value=self.value)
        if self.safe_blank_variants:
            result['default_dynamic_labels'] = [
                {'value': str(variant), 'name': '', 'image_present': False}
                for variant in range(4)
            ]
        if self.reasons:
            result['reasons'] = list(self.reasons)
        return result


@dataclass(frozen=True)
class NativeEdltParentPlan:
    unit: str
    before_xml: str
    snapshot: NativeEdltProjectSnapshot
    networks: tuple[str, ...]
    operations: tuple
    cache: object
    creations: tuple[object, ...]
    parent_plan: object
    requirements: str
    static_labels: str
    scene_metadata: object | None = None
    display_preferences: EdltDisplayPreferences | None = None
    add_dialogs: tuple = ()
    resolved_operations: tuple | None = None

    @property
    def mutation_required(self):
        return bool(self.creations or self.parent_plan.changes)

    def semantic_source(self):
        return (self.snapshot, self.operations, self.cache,
                self.creations, self.scene_metadata, self.display_preferences,
                self.add_dialogs,
                tuple(sorted(self.parent_plan.expected.items())),
                tuple(sorted(self.parent_plan.changes.items())))

    def as_dict(self):
        ordered_operations = tuple(
            row['op'] for row in self.operations
            if row['op'] in ('applications', 'corridor', 'reset'))
        ordered_application_cache = (
            self.cache.application_cache
            if hasattr(self.cache, 'application_cache') else self.cache)
        ordered_cache = None
        if (ordered_operations and
                isinstance(ordered_application_cache, ApplicationCache)):
            ordered_cache = {
                'operations': list(ordered_operations),
                'applications_complete':
                    ordered_application_cache.applications_complete,
                'group_lists_complete': [
                    row.application
                    for row in ordered_application_cache.group_lists
                    if row.complete
                ],
                **display_evidence(self.display_preferences,
                                   ordered_application_cache),
                'toolkit_registry_display_and_sort_preferences_observed': False,
                'projected_list_objects_admitted': False,
                'scene_manager_creations_enter_cache_before_pp_staging': bool(
                    self.scene_metadata is not None and self.creations),
                'operation_owned_creations_enter_cache_before_pp_staging':
                    bool(self.creations),
                'ordered_list_requirements_project_missing_objects': False,
                'combined_with_scene_manager_metadata':
                    self.scene_metadata is not None,
                'reset_raw_source': (
                    'exact selected Unit PP Value attributes'
                    if self.parent_plan.expected_raw is not None else None),
            }
        return {
            'format': 'cbus-native-edlt-parent-metadata-plan-v1',
            'profile': PROFILE, 'unit': self.unit,
            'project_xml_sha256': _digest(self.before_xml),
            'parameters_sha256': _digest(_json({
                name: list(value) for name, value in self.snapshot.values})),
            'raw_parameters_sha256': _digest(_json(
                dict(self.snapshot.raw_values))),
            'requirements': json.loads(self.requirements),
            'metadata_cache': self.cache.as_dict(),
            'metadata_provenance': 'one-admitted-native-project-xml-snapshot',
            'projected_cache_includes_planned_creations': True,
            'nested_parent_cache_role': ('issued projected cache; outer native '
                                         'manager owns metadata creation'),
            'static_labels': json.loads(self.static_labels),
            'planned_creations': [row.as_dict() for row in self.creations],
            'creation_order': (
                ['Application, then Group/NetVar, then Level dependency order',
                 'dialog-bearing histories preserve first creation order within kind']
                if self.scene_metadata is not None and self.scene_metadata.add_dialogs
                else ['Application address order',
                      'Group/NetVar application then address order',
                      'Trigger action Level group then address order']),
            'automatic_scene_metadata': (
                None if self.scene_metadata is None
                else self.scene_metadata.as_dict()),
            'automatic_ordered_application_cache': ordered_cache,
            'add_dialogs': [row.as_dict() for row in self.add_dialogs],
            'resolved_operations': (
                None if self.resolved_operations is None
                else json.loads(_json(list(self.resolved_operations)))),
            'add_dialog_boundary': {
                'blank_address_group_dialog_modeled': bool(self.add_dialogs),
                'application_add_dialog_supported': False,
                'level_add_dialog_supported': False,
                'scene_manager_trigger_action_dialog_supported': True,
                'original_dialog_executed': False,
                'created_before_pp_staging': True,
            } if self.add_dialogs else None,
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
            'toolkit_dltp_index': (
                None if self.snapshot.dltp_index is None
                else self.snapshot.dltp_index.evidence()),
            'icon_dynamic_labels_resolved': self.snapshot.dltp_index is not None,
            'unresolved_image_metadata_rejected_when_consumed': True,
            'full_scene_manager_control_binding_verified': False,
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


def _merge_lifecycle_fact(existing, replacement):
    """Join independently proven facts without weakening either source."""
    if existing is None:
        return replacement
    if existing.exists != replacement.exists:
        raise ValueError('Automatic metadata sources disagree on group presence')
    images = existing.dynamic_images
    images_known = existing.dynamic_images_known
    if replacement.dynamic_images_known:
        if images_known and images != replacement.dynamic_images:
            raise ValueError(
                'Automatic metadata sources disagree on dynamic image facts')
        images, images_known = replacement.dynamic_images, True
    levels = existing.levels
    if replacement.levels is not None:
        if levels is not None and levels != replacement.levels:
            raise ValueError(
                'Automatic metadata sources disagree on complete level facts')
        levels = replacement.levels
    return LifecycleGroup(
        existing.application, existing.group, existing.exists,
        images, images_known, levels)


def _accumulate_requirements(document, required_apps, requirement_rows):
    """Merge complete lifecycle requirement documents by consumed fact."""
    if (not isinstance(document, dict)
            or not isinstance(document.get('applications'), list)
            or not isinstance(document.get('groups'), list)):
        raise ValueError('Invalid automatic lifecycle requirement document')
    for row in document['applications']:
        required_apps.add(row['application'])
    for row in document['groups']:
        key = (row['application'], row['group'])
        target = requirement_rows.setdefault(key, {
            'application': row['application'],
            'group': row['group'],
            'facts': {},
        })
        for fact, reasons in row['facts'].items():
            if not isinstance(reasons, list):
                raise ValueError('Invalid automatic lifecycle fact reasons')
            bucket = target['facts'].setdefault(fact, [])
            for reason in reasons:
                if reason not in bucket:
                    bucket.append(reason)


def _accumulate_operation_groups(values, operations, required_apps,
                                 requirement_rows):
    for application, group, reason, needs_images in _operation_groups(
            values, operations):
        required_apps.add(application)
        key = (application, group)
        target = requirement_rows.setdefault(key, {
            'application': application,
            'group': group,
            'facts': {},
        })
        exists = target['facts'].setdefault('exists', [])
        if reason not in exists:
            exists.append(reason)
        if needs_images:
            images = target['facts'].setdefault(
                'dynamic_images_if_present', [])
            marker = {'reason': reason}
            if marker not in images:
                images.append(marker)


def _complete_application_cache(snapshot, required_apps, requirement_rows,
                                *, required_existing=(),
                                required_group_lists=(), projection=None,
                                display_preferences=None):
    """Resolve one complete database-view cache without projecting objects.

    ``TagName`` and XML child order are exact database facts.  Toolkit's
    registry-backed formatted-display and sorting preferences are not present
    in DBGETXML.  Without explicit preferences the cache deliberately uses a
    deterministic TagName view in XML order; supplied preferences apply the
    source-pinned eDLT FormattedDisplay and List.Sort model.
    """
    if projection is not None and type(projection) is not ApplicationCache:
        raise ValueError('Projected ordered cache must be an ApplicationCache')
    applications = {row.address: row for row in snapshot.applications}
    projected_applications = (
        set() if projection is None else
        set(projection.lifecycle.applications) - set(applications))
    required_existing = set(required_existing)
    required_group_lists = set(required_group_lists)
    required = (set(required_apps) | required_group_lists
                | {application for application, _group in required_existing})
    if 255 in required:
        raise ValueError(
            'Application255 is virtual and has no derivable native list')
    # A list/Reset requirement itself never authorizes object projection.
    # Exact objects carrying SceneManager/parent creation receipts may enter
    # the pre-PP cache, but a missing application whose full list is consumed
    # by Reset still fails closed.
    missing_lists = sorted(required_group_lists - set(applications))
    if missing_lists:
        raise ValueError(
            'Complete ordered application cache cannot project missing '
            'applications: ' + ', '.join(map(str, missing_lists)))
    missing = sorted(required - set(applications) - projected_applications)
    if missing:
        raise ValueError(
            'Complete ordered application cache cannot project missing '
            'applications: ' + ', '.join(map(str, missing)))

    facts = []
    for (application, group), requirement in sorted(requirement_rows.items()):
        projected_fact = (None if projection is None else
                          projection.lifecycle.find(application, group))
        if application not in applications and application not in projected_applications:
            raise ValueError(
                'Required native application is absent: ' + str(application))
        if group == 255:
            facts.append(LifecycleGroup(
                application, 255, True, (False,) * 4, True, ()))
            continue
        application_record = applications.get(application)
        record = (None if application_record is None else next(
            (row for row in application_record.groups
             if row.address == group), None))
        if record is None and projected_fact is not None and projected_fact.exists:
            if (application, group) in required_existing:
                raise ValueError(
                    'Reset does not infer a missing bound control group: '
                    f'application {application} group {group}')
            consumed = requirement.get('facts', {})
            needs_images = bool(consumed.get('dynamic_images_if_present'))
            if needs_images and not projected_fact.dynamic_images_known:
                raise ValueError(
                    'Consumed projected dynamic image metadata is unknown: '
                    f'application {application} group {group}')
            levels = (projected_fact.levels
                      if consumed.get('complete_levels_if_present') else None)
            if (consumed.get('complete_levels_if_present') and
                    levels is None):
                raise ValueError(
                    'Projected group lacks complete action levels: '
                    f'application {application} group {group}')
            facts.append(LifecycleGroup(
                application, group, True,
                projected_fact.dynamic_images if needs_images else None,
                needs_images, levels))
            continue
        if record is None:
            if (application, group) in required_existing:
                raise ValueError(
                    'Reset does not infer a missing bound control group: '
                    f'application {application} group {group}')
            facts.append(LifecycleGroup(application, group, False))
            continue
        consumed = requirement.get('facts', {})
        needs_images = bool(consumed.get('dynamic_images_if_present'))
        if needs_images and not record.dynamic_images_known:
            raise ValueError(
                'Consumed dynamic image metadata is not derivable from '
                'DBGETXML; application '
                f'{application} group {group} requires project/DLTP images')
        levels = (record.levels
                  if consumed.get('complete_levels_if_present') else None)
        facts.append(LifecycleGroup(
            application, group, True,
            record.dynamic_images if needs_images else None,
            needs_images, levels))

    for application, group in sorted(required_existing):
        key = (application, group)
        if any((row.application, row.group) == key for row in facts):
            continue
        if application not in applications:
            raise ValueError(
                'Reset bound-control application is absent: '
                + str(application))
        record = next((row for row in applications[application].groups
                       if row.address == group), None)
        if group != 255 and record is None:
            raise ValueError(
                'Reset does not infer a missing bound control group: '
                f'application {application} group {group}')
        facts.append(LifecycleGroup(
            application, group, True,
            (False,) * 4 if group == 255 else None,
            group == 255, () if group == 255 else None))
    facts = tuple(sorted(facts, key=lambda row: (row.application, row.group)))
    if len(facts) > 512:
        raise ValueError(
            'Complete ordered application cache exceeds 512 consumed group '
            'facts')

    application_order = (
        tuple(row.address for row in snapshot.applications)
        if projection is None else projection.lifecycle.applications)
    lifecycle = LifecycleCache(application_order, facts)
    displays = (
        tuple(CachedDisplay(row.address, row.tag, row.tag)
              for row in snapshot.applications)
        if projection is None else projection.applications)
    virtual = {
        row.application for row in facts
        if row.group == 255 and row.exists
    }
    group_lists = []
    count = 0
    for address in application_order:
        application = applications.get(address)
        projected_list = (None if projection is None else
                          projection.find_group_list(address))
        groups = (
            [CachedDisplay(row.address, row.tag, row.tag)
             for row in application.groups]
            if projected_list is None else list(projected_list.groups))
        if address in virtual and not any(row.address == 255 for row in groups):
            groups.append(CachedDisplay(255, '<Unused>', '<Unused>'))
        count += len(groups)
        if count > 4096:
            raise ValueError(
                'Complete ordered application cache exceeds 4096 groups')
        group_lists.append(CachedGroupList(
            address, True, tuple(groups)))
    cache = ApplicationCache(
        lifecycle, True, displays, tuple(group_lists))
    return (cache if display_preferences is None else
            present_application_cache(cache, display_preferences))


def _reset_requirements(snapshot, editor, operations):
    reset = next((row for row in operations if row['op'] == 'reset'), None)
    if reset is None:
        return None, frozenset(), frozenset()
    options = {name: value for name, value in reset.items()
               if name not in ('op', 'dirty_parameters')}
    document = editor._editor('reset').requirements(
        snapshot.raw_map(), **options).as_dict()
    control_groups = frozenset(
        (row['application'], row['group'])
        for row in document['control_groups'])
    return document, control_groups, frozenset(document['complete_group_lists'])


def _project_ordered_scene_source(editor, operations, values, cache):
    """Project the evidenced pre-SceneManager list/Reset controls.

    The parent transaction performs the authoritative projection again.  This
    helper supplies only the exact numeric state needed by the retained scene
    metadata resolver, without issuing a second save or accepting a caller PP
    overlay.
    """
    projected = dict(editor.snapshot(values))
    for operation in operations:
        kind = operation['op']
        if kind == 'scene-manager':
            break
        if kind == 'reset':
            # The caller already supplied ResetEdlt.after_controls.
            continue
        if kind == 'blank':
            slot = _candidate_widget(operation, projected)
            if slot is None:
                raise ValueError(
                    'Automatic Reset/Blank metadata could not resolve the '
                    'fresh graph placement')
            projected[_pp_field(slot)] = (0,)
            if slot >= 6:
                projected[f'Widget{slot}RestoreLevel'] = (0,)
            continue
        if kind == 'applications':
            plan = editor._editor(kind).plan(
                projected, cache=cache, edits=operation['edits'])
            after = dict(plan.after_controls)
            fields = list(_SETTING_FIELDS[kind])
            fields.extend(
                name for name in after
                if (name.startswith('Widget') and
                    name.endswith('WidgetByteValue1') and
                    after[name] != projected[name]))
            for name in fields:
                projected[name] = after[name]
    return editor.snapshot(projected)


def _merge_application_cache(primary, supplement):
    """Merge exact lifecycle facts while retaining the primary ordered lists."""
    facts = {
        (row.application, row.group): row
        for row in primary.lifecycle.groups
    }
    for row in supplement.lifecycle.groups:
        key = (row.application, row.group)
        existing = facts.get(key)
        if (existing is not None and existing.levels is not None and
                row.levels is not None and
                set(row.levels) <= set(existing.levels)):
            # The SceneManager resolver may append exact planned action levels
            # to the source list.  The ordered cache is a pre-creation view;
            # retain the projected superset while merging its other facts.
            row = LifecycleGroup(
                row.application, row.group, row.exists,
                row.dynamic_images, row.dynamic_images_known,
                existing.levels)
        facts[key] = _merge_lifecycle_fact(facts.get(key), row)
    if len(facts) > 512:
        raise ValueError('Resolved combined eDLT parent cache exceeds 512 group facts')
    applications = tuple(dict.fromkeys((
        *primary.lifecycle.applications,
        *supplement.lifecycle.applications,
    )))
    lifecycle = LifecycleCache(
        applications, tuple(facts[key] for key in sorted(facts)))
    return ApplicationCache(
        lifecycle, primary.applications_complete, primary.applications,
        primary.group_lists)


def _parent_container_projection(snapshot, requirements, values, operations):
    """Derive deterministic non-Level creation receipts for parent controls."""
    required_apps = {
        row['application'] for row in requirements['applications']
    }
    group_reasons = {}
    requirement_rows = {}
    for row in requirements['groups']:
        key = (row['application'], row['group'])
        requirement_rows[key] = row
        group_reasons.setdefault(key, []).extend(row['facts']['exists'])
    operation_images = {}
    for application, group, reason, needs_images in _operation_groups(
            values, operations):
        required_apps.add(application)
        group_reasons.setdefault((application, group), []).append(reason)
        if needs_images:
            operation_images.setdefault((application, group), []).append(
                reason)

    applications = {row.address: row for row in snapshot.applications}
    creations = []
    for address in sorted(required_apps):
        if address == 255:
            raise ValueError(
                'Application255 is virtual and cannot satisfy parent metadata')
        # The retained SceneManager resolver owns Trigger Control creation.
        if address not in applications and address != 202:
            creations.append(MetadataCreation(
                'Application', address, address,
                APPLICATION_NAMES.get(address, 'Application ' + str(address))))
    for (application, group), reasons in sorted(group_reasons.items()):
        if application == 255:
            raise ValueError(
                'Group metadata cannot belong to virtual application255')
        if group == 255:
            continue
        app = applications.get(application)
        record = None if app is None else next(
            (row for row in app.groups if row.address == group), None)
        if record is not None:
            continue
        requirement = requirement_rows.get((application, group), {})
        needs_levels = bool(requirement.get('facts', {}).get(
            'complete_levels_if_present'))
        if needs_levels:
            if application == 202:
                # Trigger groups and exact action levels are projected by the
                # retained resolver below.
                continue
            raise ValueError(
                'Missing scene trigger metadata requires level creation, '
                'which is outside the bounded parent metadata transaction: '
                f'application {application} group {group}')
        kind = 'NetVar' if application == 203 else 'Group'
        creations.append(MetadataCreation(
            kind, application, group, 'Group ' + str(group),
            safe_blank_variants=True,
            reasons=tuple(dict.fromkeys(reasons))))
    return (tuple(creations), operation_images, group_reasons,
            requirement_rows)


def _plan_parent_scene_metadata(text, unit_path, supplied, editor, operations,
                                snapshot, requirements, *, networks=(),
                                display_preferences=None):
    """Compose the exact SceneManager resolver with parent dependencies."""
    from .edlt_scene_manager import SceneManagerCache
    from .edlt_scene_metadata import (
        SceneContainerCreation, SceneLevelCreation,
        resolve_native_scene_metadata,
    )

    scene_operation = next(
        row for row in operations if row['op'] == 'scene-manager')
    scene_engine = editor._editor('scene-manager')

    def resolve_projection(source, source_requirements):
        outer, images, reasons, rows = _parent_container_projection(
            snapshot, source_requirements, source, operations)
        projected = tuple(
            SceneContainerCreation(
                row.kind, row.application, row.address, row.name, row.reasons)
            for row in outer
        )
        outcome = resolve_native_scene_metadata(
            text, unit_path, supplied, scene_engine,
            scene_operation['operations'], _projected_containers=projected,
            _projected_values=source, dltp_index=snapshot.dltp_index,
            display_preferences=display_preferences)
        if outcome.snapshot != snapshot:
            raise ValueError(
                'Parent and SceneManager metadata snapshots do not identify '
                'the same native project state')
        return outcome, outer, images, reasons, rows

    resolved, outer_creations, operation_images, group_reasons, \
        requirement_rows = resolve_projection(supplied, requirements)
    ordered_operations = tuple(
        row['op'] for row in operations
        if row['op'] in ('applications', 'corridor', 'reset'))
    ordered_cache = None
    parent_input = supplied
    scene_source = supplied
    if ordered_operations:
        ordered_apps = set()
        ordered_requirements = {}
        _accumulate_requirements(
            requirements, ordered_apps, ordered_requirements)
        reset_requirements, control_groups, complete_group_lists = \
            _reset_requirements(snapshot, editor, operations)
        if reset_requirements is not None:
            _accumulate_requirements(
                reset_requirements['initial_load'], ordered_apps,
                ordered_requirements)
            _accumulate_requirements(
                reset_requirements['fresh_reset_load'], ordered_apps,
                ordered_requirements)
        ordered_cache = _complete_application_cache(
            snapshot, ordered_apps, ordered_requirements,
            required_existing=control_groups,
            required_group_lists=complete_group_lists,
            projection=resolved.cache.application_cache,
            display_preferences=display_preferences)
        if reset_requirements is not None:
            reset = operations[0]
            options = {
                name: value for name, value in reset.items()
                if name != 'op'
            }
            options.setdefault('dirty_parameters', ())
            _raw, _dirty, _prepared, transition = \
                editor._editor('reset').prepare_unit_reset(
                    snapshot.raw_map(), metadata=ordered_cache, **options)
            scene_source = dict(transition.after_controls)
            parent_input = snapshot.raw_map()
        ordered_base_source = scene_source
        scene_source = _project_ordered_scene_source(
            editor, operations, ordered_base_source, ordered_cache)

        # Re-resolve the lifecycle facts after Applications and fresh-graph
        # Blank projection, then admit only objects with exact parent/scene
        # creation receipts into the pre-PP cache.
        _accumulate_requirements(
            editor.lifecycle.requirements(scene_source).as_dict(),
            ordered_apps, ordered_requirements)
        dependency_operations = tuple(
            row for row in operations if row['op'] != 'scene-manager')
        _accumulate_operation_groups(
            scene_source, dependency_operations, ordered_apps,
            ordered_requirements)
        projected_requirements = editor.lifecycle.requirements(
            scene_source).as_dict()
        resolved, outer_creations, operation_images, group_reasons, \
            requirement_rows = resolve_projection(
                scene_source, projected_requirements)
        ordered_cache = _complete_application_cache(
            snapshot, ordered_apps, ordered_requirements,
            required_existing=control_groups,
            required_group_lists=complete_group_lists,
            projection=resolved.cache.application_cache,
            display_preferences=display_preferences)
        stable_source = _project_ordered_scene_source(
            editor, operations, ordered_base_source, ordered_cache)
        if stable_source != scene_source:
            # One deterministic fixed-point retry admits metadata-dependent
            # application displays without allowing an unbounded projection.
            projected_requirements = editor.lifecycle.requirements(
                stable_source).as_dict()
            resolved, outer_creations, operation_images, group_reasons, \
                requirement_rows = resolve_projection(
                    stable_source, projected_requirements)
            ordered_cache = _complete_application_cache(
                snapshot, ordered_apps, ordered_requirements,
                required_existing=control_groups,
                required_group_lists=complete_group_lists,
                projection=resolved.cache.application_cache,
            display_preferences=display_preferences)
            if _project_ordered_scene_source(
                    editor, operations, ordered_base_source,
                    ordered_cache) != stable_source:
                raise ValueError(
                    'Automatic combined parent metadata did not reach a '
                    'stable pre-SceneManager state')
        scene_source = stable_source

    applications = {row.address: row for row in snapshot.applications}
    required_apps = set(resolved.cache.application_cache.lifecycle.applications)

    state = scene_engine.load(scene_source, metadata=resolved.cache)
    outcome = scene_engine.edit(
        state, operations=resolved.operations)
    if not outcome.complete:
        raise ValueError(
            'SceneManager capacity stopped the nested edit; partial scene '
            'graphs cannot enter automatic parent metadata')
    composition = scene_engine.prepare_composition(outcome.state)
    dependency_values = {**scene_source, **composition.fields}

    # Scene widgets after SceneManager must consume the final trigger graph.
    for application, group, reason, needs_images in _operation_groups(
            dependency_values, operations):
        required_apps.add(application)
        group_reasons.setdefault((application, group), []).append(reason)
        if needs_images:
            operation_images.setdefault((application, group), []).append(
                reason)

    scene_application_cache = resolved.cache.application_cache
    facts = {
        (row.application, row.group): row
        for row in scene_application_cache.lifecycle.groups
    }
    projected_apps = set(scene_application_cache.lifecycle.applications)
    for address in required_apps:
        if address not in projected_apps:
            raise ValueError(
                'Parent dependency application was not projected into the '
                'complete SceneManager cache: ' + str(address))
    for (application, group), _reasons in sorted(group_reasons.items()):
        if group == 255:
            replacement = LifecycleGroup(
                application, 255, True, (False,) * 4, True, ())
            facts[(application, group)] = _merge_lifecycle_fact(
                facts.get((application, group)), replacement)
            continue
        app = applications.get(application)
        record = None if app is None else next(
            (row for row in app.groups if row.address == group), None)
        current = facts.get((application, group))
        if record is None:
            if current is None or not current.exists:
                raise ValueError(
                    'Parent dependency group was not projected into the '
                    'complete SceneManager cache: '
                    f'{application}/{group}')
            replacement = current
        else:
            requirement = requirement_rows.get((application, group), {})
            needs_levels = bool(requirement.get('facts', {}).get(
                'complete_levels_if_present'))
            levels = (current.levels if current is not None
                      and current.levels is not None else
                      record.levels if needs_levels else None)
            needs_images = bool(
                requirement.get('facts', {}).get('dynamic_images_if_present')
                or (application, group) in operation_images)
            if needs_images and not record.dynamic_images_known:
                raise ValueError(
                    'Consumed dynamic image metadata is not derivable from '
                    'DBGETXML; application '
                    f'{application} group {group} requires project/DLTP images')
            replacement = LifecycleGroup(
                application, group, True,
                record.dynamic_images if needs_images else None,
                needs_images, levels)
        facts[(application, group)] = _merge_lifecycle_fact(
            current, replacement)
    if len(facts) > 512:
        raise ValueError('Resolved eDLT parent scene cache exceeds 512 group facts')
    lifecycle = LifecycleCache(
        scene_application_cache.lifecycle.applications,
        tuple(facts[key] for key in sorted(facts)))
    application_cache = ApplicationCache(
        lifecycle, scene_application_cache.applications_complete,
        scene_application_cache.applications,
        scene_application_cache.group_lists)
    if ordered_cache is not None:
        application_cache = _merge_application_cache(
            application_cache, ordered_cache)
    cache = SceneManagerCache(application_cache, resolved.cache.level_labels)

    scene_creations = []
    for row in resolved.creations:
        if isinstance(row, SceneLevelCreation):
            scene_creations.append(MetadataCreation(
                'Level', 202, row.address, row.name,
                group=row.group, value=row.address,
                safe_blank_variants=True, reasons=row.reasons))
        else:
            scene_creations.append(MetadataCreation(
                row.kind, row.application, row.address, row.name,
                safe_blank_variants=row.kind != 'Application',
                reasons=row.reasons))
    if resolved.add_dialogs:
        # Preserve dialog-bearing creation order within each dependency kind.
        creations = tuple(sorted((*outer_creations, *scene_creations),
                                 key=lambda row: 0 if row.kind == 'Application'
                                 else 1 if row.kind in ('Group', 'NetVar') else 2))
    else:
        creations = tuple(sorted(
            (*outer_creations, *scene_creations),
            key=lambda row: (
                0 if row.kind == 'Application' else
                1 if row.kind in ('Group', 'NetVar') else 2,
                row.application,
                row.group if row.group is not None else -1,
                row.address)))
    keys = [
        (row.kind, row.application, row.group, row.address)
        for row in creations
    ]
    if len(keys) != len(set(keys)):
        raise ValueError('Automatic parent metadata projected duplicate objects')
    if len(creations) > 512:
        raise ValueError('eDLT parent scene metadata plan exceeds 512 creations')
    resolved_parent_operations = tuple(
        {**row, 'operations': resolved.operations} if row['op'] == 'scene-manager'
        else row for row in operations)
    parent = editor.plan(parent_input, metadata=cache, operations=resolved_parent_operations)
    return NativeEdltParentPlan(
        unit_path, text, snapshot, tuple(networks), operations, cache,
        creations, parent, _json(requirements), _static_labels(supplied),
        resolved, display_preferences,
        resolved_operations=resolved_parent_operations)


def plan_native_parent_metadata(text, unit_path, values, editor, operations,
                                *, networks=(), display_preferences=None,
                                dltp_index=None):
    """Build the projected cache and parent plan without native I/O.

    ``display_preferences`` optionally applies the eDLT registry display/sort
    model to ordered lists; ``dltp_index`` resolves ICON dynamic-label images.
    """
    if type(editor) is not EdltParentTransaction:
        raise ValueError('Expected an EdltParentTransaction editor')
    if (display_preferences is not None
            and type(display_preferences) is not EdltDisplayPreferences):
        raise ValueError('Display preferences must be EdltDisplayPreferences')
    operations = normalize_operations(operations, allow_add_dialog=True)
    unit_path, _project_name, _network, _unit = _unit_path(unit_path)
    snapshot = _snapshot(text, unit_path, editor, dltp_index=dltp_index)
    supplied = editor.snapshot(values)
    if supplied != snapshot.value_map():
        raise ValueError('PP snapshot differs from the selected native project unit')
    requirements = editor.lifecycle.requirements(supplied).as_dict()
    if any(row['op'] == 'add-dialog' for row in operations):
        return _plan_add_dialogs(
            text, unit_path, supplied, editor, operations, snapshot,
            requirements, networks=networks,
            display_preferences=display_preferences)
    if any(row['op'] == 'scene-manager' for row in operations):
        return _plan_parent_scene_metadata(
            text, unit_path, supplied, editor, operations, snapshot,
            requirements, networks=networks,
            display_preferences=display_preferences)

    # Applications, Corridor and Reset consume complete ordered lists.  For
    # this branch a missing object cannot be appended at a position that is
    # evidenced by DBGETXML, so it is rejected rather than projected.  Reset
    # additionally consumes the exact PP Value spellings, which the numeric
    # public ``values`` argument deliberately cannot carry.
    ordered_cache_operations = {
        row['op'] for row in operations
        if row['op'] in ('applications', 'corridor', 'reset')
    }
    if ordered_cache_operations:
        required_apps = set()
        requirement_rows = {}
        _accumulate_requirements(
            requirements, required_apps, requirement_rows)
        reset_requirements, control_groups, complete_group_lists = \
            _reset_requirements(snapshot, editor, operations)
        if reset_requirements is not None:
            _accumulate_requirements(
                reset_requirements['initial_load'], required_apps,
                requirement_rows)
            _accumulate_requirements(
                reset_requirements['fresh_reset_load'], required_apps,
                requirement_rows)

            # Obtain the issued fresh graph using a first cache containing
            # exactly the initial/fresh Reset facts.  Later operation
            # dependencies are then resolved against the post-Reset numeric
            # state before the final canonical parent plan is issued.
            preliminary = _complete_application_cache(
                snapshot, required_apps, requirement_rows,
                required_existing=control_groups,
                required_group_lists=complete_group_lists,
                display_preferences=display_preferences)
            reset_operation = operations[0]
            reset_options = {
                name: value for name, value in reset_operation.items()
                if name != 'op'
            }
            reset_options.setdefault('dirty_parameters', ())
            _raw, _dirty, _prepared, transition = \
                editor._editor('reset').prepare_unit_reset(
                    snapshot.raw_map(), metadata=preliminary,
                    **reset_options)
            dependency_values = dict(transition.after_controls)
            dependency_operations = operations[1:]
        else:
            dependency_values = supplied
            dependency_operations = operations
        _accumulate_operation_groups(
            dependency_values, dependency_operations, required_apps,
            requirement_rows)
        cache = _complete_application_cache(
            snapshot, required_apps, requirement_rows,
            required_existing=control_groups,
            required_group_lists=complete_group_lists,
            display_preferences=display_preferences)
        parent_input = (snapshot.raw_map()
                        if reset_requirements is not None else supplied)
        parent = editor.plan(
            parent_input, metadata=cache, operations=operations)
        return NativeEdltParentPlan(
            unit_path, text, snapshot, tuple(networks), operations, cache,
            (), parent, _json(requirements), _static_labels(supplied),
            display_preferences=display_preferences)

    return _plan_unordered(text, unit_path, supplied, editor, operations,
                           snapshot, requirements, networks=networks,
                           display_preferences=display_preferences)


def _plan_add_dialogs(text, unit_path, supplied, editor, operations, snapshot,
                      requirements, *, networks, display_preferences):
    """Resolve blank-address Add dialogs, then plan the bound operations."""
    refused = sorted({row['op'] for row in operations
                      if row['op'] in ('applications', 'corridor', 'reset',
                                       'scene-manager')})
    if refused:
        raise ValueError(
            'add-dialog cannot share a plan with ' + ', '.join(refused) +
            ': their ordered-list or scene-graph contracts do not position a '
            'dialog-created object')
    existing = {row.address: {group.address: group.tag for group in row.groups}
                for row in snapshot.applications}
    load_groups = tuple(
        (row['application'], row['group']) for row in requirements['groups'])

    def preceding(index):
        # The parent load and earlier ordinary operations auto-create their
        # exact groups as ``Group N`` before the operator presses Add.
        prior = [row for row in operations[:index] if row['op'] != 'add-dialog']
        keys = list(load_groups) + [
            (application, group) for application, group, _reason, _images
            in _operation_groups(supplied, prior)]
        return tuple((application, group, 'Group ' + str(group))
                     for application, group in keys
                     if application != 255 and group != 255)

    resolved, dialogs = resolve_add_dialogs(
        operations, supplied, snapshot.project, existing, preceding)
    resolved = normalize_operations(resolved)
    return _plan_unordered(text, unit_path, supplied, editor, resolved,
                           snapshot, requirements, networks=networks,
                           display_preferences=display_preferences,
                           source_operations=operations, dialogs=dialogs)


def _plan_unordered(text, unit_path, supplied, editor, operations, snapshot,
                    requirements, *, networks, display_preferences,
                    source_operations=None, dialogs=()):
    dialog_rows = {(row.application, row.address): row for row in dialogs}
    required_apps = {row['application'] for row in requirements['applications']}
    required_apps.update(row.application for row in dialogs)
    group_reasons = {}
    requirement_rows = {}
    for row in requirements['groups']:
        key = (row['application'], row['group'])
        requirement_rows[key] = row
        group_reasons.setdefault(key, []).extend(row['facts']['exists'])
    operation_images = {}
    for application, group, reason, needs_images in _operation_groups(
            supplied, operations):
        required_apps.add(application)
        group_reasons.setdefault((application, group), []).append(reason)
        if needs_images:
            operation_images.setdefault((application, group), []).append(reason)

    applications = {row.address: row for row in snapshot.applications}
    creations = []
    for address in sorted(required_apps):
        if address == 255:
            raise ValueError('Application255 is virtual and cannot satisfy parent metadata')
        if address not in applications:
            creations.append(MetadataCreation(
                'Application', address, address,
                APPLICATION_NAMES.get(address, 'Application ' + str(address))))
    for key, row in dialog_rows.items():
        group_reasons.setdefault(key, []).append('add-dialog ' + row.field)
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
        if record is None and (application, group) in dialog_rows:
            dialog = dialog_rows[(application, group)]
            creations.append(MetadataCreation(
                'NetVar' if application == 203 else 'Group', application,
                group, dialog.name,
                reasons=('add-dialog ' + dialog.field,)))
            cache_groups.append(LifecycleGroup(
                application, group, True, (False,) * 4, True, ()))
            continue
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
        needs_images = bool(facts.get('dynamic_images_if_present')
                            or (application, group) in operation_images)
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
        unit_path, text, snapshot, tuple(networks),
        operations if source_operations is None else source_operations,
        cache, creations, parent, _json(requirements),
        _static_labels(supplied), display_preferences=display_preferences,
        add_dialogs=tuple(dialogs),
        resolved_operations=None if source_operations is None else operations)


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
    def __init__(self, client, editor, *, programmer=None,
                 display_preferences=None, dltp_index=None):
        if type(editor) is not EdltParentTransaction:
            raise ValueError('Expected an EdltParentTransaction editor')
        if (display_preferences is not None
                and type(display_preferences) is not EdltDisplayPreferences):
            raise ValueError('Display preferences must be EdltDisplayPreferences')
        if dltp_index is not None and type(dltp_index) is not DltpIndex:
            raise ValueError('A DLTP index must come from load_dltp_index')
        self.display_preferences, self.dltp_index = display_preferences, dltp_index
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
            'backup_source_save_attempted': False,
            'backup_source_save_confirmed': False,
            'backup_source_save_outcome_uncertain': False,
            'backup_copy_attempted': False,
            'backup_copy_confirmed': False,
            'backup_copy_outcome_uncertain': False,
            'saved': False, 'database_persistence': 'not-attempted',
            'metadata_mutation_attempted': False,
            'metadata_objects_created': 0,
            'unidentified_metadata_mutation': False,
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
            'full_scene_manager_control_binding_verified': False,
            'native_parent_form_executed': False,
        }

    def _finish(self):
        self.last_result = NativeEdltParentResult(_json(self._evidence))
        return self.last_result

    def _fail(self, error):
        backup_save_uncertain = (
            self._evidence['backup_source_save_attempted']
            and not self._evidence['backup_source_save_confirmed'])
        backup_copy_uncertain = (
            self._evidence['backup_copy_attempted']
            and not self._evidence['backup_copy_confirmed'])
        pp_save_uncertain = (self._evidence['pp_save_attempted']
                             and not self._evidence['pp_save_confirmed'])
        project_save_uncertain = (
            self._evidence['target_project_save_attempted']
            and not self._evidence['target_project_save_confirmed'])
        staging = self._evidence.get('staging_evidence') or {}
        rollback_verified = (self._evidence['rollback_verified']
                             or bool(staging.get('rollback_verified')))
        rollback_attempted = (self._evidence['rollback_attempted']
                              or bool(staging.get('attempted_parameters')))
        rollback_errors = [*self._evidence['rollback_errors'],
                           *staging.get('rollback_errors', ())]
        rollback_uncertain = rollback_attempted and not rollback_verified
        pp_uncertain = pp_save_uncertain or rollback_uncertain
        database_uncertain = (
            backup_save_uncertain or backup_copy_uncertain
            or pp_save_uncertain or project_save_uncertain
            or rollback_uncertain)
        partial = (self._evidence['backup_created']
                   or self._evidence['pp_save_attempted']
                   or self._evidence['target_project_save_attempted']
                   or database_uncertain)
        if rollback_verified:
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
            rollback_attempted=rollback_attempted,
            rollback_verified=rollback_verified,
            rollback_errors=rollback_errors,
            backup_source_save_outcome_uncertain=backup_save_uncertain,
            backup_copy_outcome_uncertain=backup_copy_uncertain,
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
                self.editor, operations, networks=networks,
                display_preferences=self.display_preferences,
                dltp_index=self.dltp_index)
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
            plan.operations, networks=plan.networks,
            display_preferences=plan.display_preferences,
            dltp_index=plan.snapshot.dltp_index)
        if exact and text != plan.before_xml:
            raise ValueError('Native project XML changed since planning')
        if current.semantic_source() != plan.semantic_source():
            raise ValueError('Native eDLT metadata or PP state changed since planning')
        return text

    def _add(self, plan, creation, known):
        if creation.kind == 'Application':
            parent = f'//{plan.snapshot.project}/{plan.snapshot.network}'
            kind = 'application'
        elif creation.kind == 'Level':
            parent = (f'//{plan.snapshot.project}/{plan.snapshot.network}/'
                      f'{creation.application}/{creation.group}')
            kind = 'level'
        else:
            parent = (f'//{plan.snapshot.project}/{plan.snapshot.network}/'
                      f'{creation.application}')
            kind = creation.kind.lower()
        receipt = {
            **creation.as_dict(), 'attempted': True, 'created': False,
            'value_initialized': False,
        }
        try:
            response = self.database.add(
                parent, kind, creation.address,
                _name(creation.name, 'Metadata name'))
        except BaseException:
            self._evidence['unidentified_metadata_mutation'] = True
            raise
        identities = [match[1].lower() for line in response.lines
                      if (match := re.fullmatch(
                          r'301[- ]OID=([0-9a-fA-F-]{36})', line))]
        if len(identities) != 1:
            self._evidence['unidentified_metadata_mutation'] = True
            raise RuntimeError('Created metadata did not return exactly one OID')
        try:
            identity = _oid(identities[0])
        except ValueError:
            self._evidence['unidentified_metadata_mutation'] = True
            raise
        if identity in known:
            self._evidence['unidentified_metadata_mutation'] = True
            raise RuntimeError('Created metadata returned an existing OID')
        known.add(identity)
        receipt.update(
            oid=identity, created=True,
            value_initialized=creation.kind == 'Level')
        self._evidence['objects'].append(receipt)
        self._evidence['metadata_objects_created'] = len(
            self._evidence['objects'])

    def _verify_created(self, plan, text):
        snapshot = _snapshot(text, plan.unit, self.editor,
                             dltp_index=plan.snapshot.dltp_index)
        before_apps = {row.address: row for row in plan.snapshot.applications}
        after_apps = {row.address: row for row in snapshot.applications}
        app_creations = {
            row.address: row for row in plan.creations
            if row.kind == 'Application'
        }
        group_creations = {
            (row.application, row.address): row for row in plan.creations
            if row.kind in ('Group', 'NetVar')
        }
        level_creations = {
            (row.application, row.group, row.address): row
            for row in plan.creations if row.kind == 'Level'
        }
        if set(after_apps) != set(before_apps) | set(app_creations):
            raise RuntimeError(
                'Native application inventory changed during the transaction')
        receipts = {}
        for row in self._evidence['objects']:
            key = (
                row['kind'], row.get('application'), row.get('group'),
                row['address'])
            if key in receipts:
                raise RuntimeError('Duplicate parent metadata creation receipt')
            receipts[key] = row

        for app_address, after_app in after_apps.items():
            before_app = before_apps.get(app_address)
            if before_app is None:
                creation = app_creations.get(app_address)
                receipt = receipts.get(
                    ('Application', None, None, app_address))
                if (creation is None or receipt is None
                        or after_app.oid != receipt['oid']
                        or after_app.tag != creation.name):
                    raise RuntimeError(
                        'Created parent application differs after native readback')
            elif (after_app.oid, after_app.tag, after_app.metadata) != (
                    before_app.oid, before_app.tag, before_app.metadata):
                raise RuntimeError('Existing application metadata changed')

            before_groups = ({row.address: row for row in before_app.groups}
                             if before_app is not None else {})
            expected_new_groups = {
                address: row for (application, address), row
                in group_creations.items() if application == app_address
            }
            after_groups = {row.address: row for row in after_app.groups}
            if set(after_groups) != (set(before_groups)
                                     | set(expected_new_groups)):
                raise RuntimeError(
                    'Native group inventory changed during the transaction')

            for group_address, after_group in after_groups.items():
                before_group = before_groups.get(group_address)
                if before_group is None:
                    creation = expected_new_groups.get(group_address)
                    receipt = receipts.get((
                        creation.kind if creation is not None else '',
                        app_address, None, group_address))
                    if (creation is None or receipt is None
                            or after_group.kind != creation.kind
                            or after_group.oid != receipt['oid']
                            or after_group.tag != creation.name):
                        raise RuntimeError(
                            'Created parent group differs after native readback')
                    if (creation.safe_blank_variants
                            and (not after_group.dynamic_images_known
                                 or after_group.dynamic_images !=
                                 (False,) * 4)):
                        raise RuntimeError(
                            'Created parent group lacks safe blank variants')
                elif (after_group.kind, after_group.oid, after_group.tag,
                      after_group.metadata, after_group.dynamic_images,
                      after_group.dynamic_images_known) != (
                          before_group.kind, before_group.oid,
                          before_group.tag, before_group.metadata,
                          before_group.dynamic_images,
                          before_group.dynamic_images_known):
                    raise RuntimeError('Existing group metadata changed')

                before_levels = (
                    {row.address: row for row in before_group.level_records}
                    if before_group is not None else {})
                expected_new_levels = {
                    address: row
                    for (application, group, address), row
                    in level_creations.items()
                    if (application, group) == (app_address, group_address)
                }
                after_levels = {
                    row.address: row for row in after_group.level_records
                }
                if set(after_levels) != (set(before_levels)
                                         | set(expected_new_levels)):
                    raise RuntimeError(
                        'Native level inventory changed during the transaction')
                for address, before_level in before_levels.items():
                    if after_levels[address] != before_level:
                        raise RuntimeError('Existing level metadata changed')
                for address, creation in expected_new_levels.items():
                    row = after_levels[address]
                    receipt = receipts.get(
                        ('Level', app_address, group_address, address))
                    blanks = tuple((str(variant), '', False)
                                   for variant in range(4))
                    if (receipt is None or row.oid != receipt['oid']
                            or row.address != address
                            or row.value != creation.value
                            or row.tag != creation.name
                            or (creation.safe_blank_variants
                                and (not row.dynamic_labels_known
                                     or row.dynamic_labels != blanks))):
                        raise RuntimeError(
                            'Created trigger action differs after native readback')

        if len(receipts) != len(plan.creations):
            raise RuntimeError('Parent metadata creation receipts are incomplete')
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
            if not self._evidence['unidentified_metadata_mutation']:
                for row in reversed(self._evidence['objects']):
                    row['rollback_delete_attempted'] = True
                    self.database.delete('!' + row['oid'])
                    row['rollback_delete_confirmed'] = True
                # Persist identified inverse operations. If an add reply was
                # ambiguous, reload the already saved source instead of
                # persisting an unidentified object.
                self._operation('save', plan.snapshot.project)
                self._evidence['rollback_project_save_confirmed'] = True
            for action in ('close', 'load'):
                self._operation(action, plan.snapshot.project)
            text = self._xml(plan.snapshot.project)
            current = _snapshot(text, plan.unit, self.editor,
                                dltp_index=plan.snapshot.dltp_index)
            if current != plan.snapshot:
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
            self._evidence['backup_source_save_attempted'] = True
            self._operation('save', plan.snapshot.project)
            self._evidence['backup_source_save_confirmed'] = True
            self._evidence['backup_copy_attempted'] = True
            self._operation('copy', plan.snapshot.project, backup)
            self._evidence['backup_copy_confirmed'] = True
            self._evidence['backup_created'] = True
            self._fresh(plan)
            self._operation('use', plan.snapshot.project)
            known = {plan.snapshot.unit_oid}
            for app in plan.snapshot.applications:
                known.add(app.oid)
                for group in app.groups:
                    known.add(group.oid)
                    known.update(level.oid for level in group.level_records)
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
                try:
                    result = self.editor.apply(session, plan.parent_plan)
                except BaseException as staging_error:
                    evidence = getattr(
                        staging_error, 'edlt_parent_transaction_evidence', None)
                    if isinstance(evidence, dict):
                        self._evidence['staging_evidence'] = evidence
                    raise
                self._evidence['staging_evidence'] = result
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
            if (not pp_save_attempted
                    and not self._evidence.get('target_project_save_attempted')
                    and self._evidence.get('backup_created')
                    and (self._evidence.get('metadata_mutation_attempted')
                         or self._evidence.get('pp_mutation_attempted'))):
                self._rollback_pre_save(plan)
            self._fail(error)
