"""Explicit eDLT database model load/before-save cycle with caller cache facts.

This is the unchanged model lifecycle, not WinForms binding initialization,
validation dialogs, metadata creation, DLT upload, or saving a physical unit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from types import MappingProxyType
from typing import Mapping
import weakref

from .edlt import EdltLighting, EdltError, EdltApplyError, _field, _int, _render

FORMAT = 'cbus-edlt-lifecycle-cache-v1'
MAX_GROUPS = 512
MAX_LEVELS = 8192
_APP_GROUP_TYPES = frozenset((2, 3, 4, 5, 14, 15, 16))


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def _error_text(error):
    try: return str(error)[:1024]
    except BaseException: return '<unprintable ' + type(error).__name__ + '>'


def _changes(before, after):
    return {name: value for name, value in after.items() if value != before[name]}


def _delta(before, after):
    return {name: {'before': list(before[name]) if isinstance(before[name], tuple) else before[name],
                   'after': list(value) if isinstance(value, tuple) else value}
            for name, value in _changes(before, after).items()}


class LifecycleMetadataError(EdltError):
    def __init__(self, message, fact, *, original_stage=None):
        self.fact, self.original_stage = dict(fact), original_stage
        super().__init__(message)
        self.details = self.as_dict()

    def as_dict(self):
        return {'error': str(self), 'required_fact': dict(self.fact), 'original_stage': self.original_stage,
                'saved': False, 'physical_device_verified': False}


@dataclass(frozen=True)
class LifecycleGroup:
    application: int
    group: int
    exists: bool
    dynamic_images: tuple[bool, ...] | None = None
    dynamic_images_known: bool = False
    levels: tuple[int, ...] | None = None

    def __post_init__(self):
        _int(self.application, 'Cache application'); _int(self.group, 'Cache group')
        if type(self.exists) is not bool or type(self.dynamic_images_known) is not bool:
            raise EdltError('Cache presence and image-state flags must be boolean')
        if self.dynamic_images is not None and (not isinstance(self.dynamic_images, tuple) or
                len(self.dynamic_images) > 4 or any(type(value) is not bool for value in self.dynamic_images)):
            raise EdltError('dynamic_images must be null or at most four boolean image-presence values')
        if not self.dynamic_images_known and self.dynamic_images is not None:
            raise EdltError('Unknown dynamic_images cannot contain values')
        if self.levels is not None:
            if not isinstance(self.levels, tuple) or len(self.levels) > 256:
                raise EdltError('Cache levels must be at most256 unique addresses')
            for level in self.levels: _int(level, 'Cache level')
            if len(set(self.levels)) != len(self.levels): raise EdltError('Duplicate cache level')
        if not self.exists and (self.dynamic_images_known or self.levels is not None):
            raise EdltError('Absent groups cannot provide image or level data')

    def as_dict(self):
        result = {'application': self.application, 'group': self.group, 'exists': self.exists}
        if self.dynamic_images_known:
            result['dynamic_images'] = None if self.dynamic_images is None else list(self.dynamic_images)
        if self.levels is not None: result['levels'] = list(self.levels)
        return result


@dataclass(frozen=True)
class LifecycleCache:
    applications: tuple[int, ...]
    groups: tuple[LifecycleGroup, ...]

    def __post_init__(self):
        if not isinstance(self.applications, tuple) or len(self.applications) > 256:
            raise EdltError('Cache applications must be at most256 unique addresses')
        for application in self.applications: _int(application, 'Cache application')
        if len(set(self.applications)) != len(self.applications): raise EdltError('Duplicate cache application')
        if not isinstance(self.groups, tuple) or len(self.groups) > MAX_GROUPS or any(type(g) is not LifecycleGroup for g in self.groups):
            raise EdltError('Cache must contain at most512 valid group records')
        keys = [(g.application, g.group) for g in self.groups]
        if len(set(keys)) != len(keys): raise EdltError('Duplicate cache group')
        if any(g.application not in self.applications for g in self.groups):
            raise EdltError('Cache group application must be explicitly present')
        if sum(len(g.levels or ()) for g in self.groups) > MAX_LEVELS:
            raise EdltError('Cache exceeds8192 level addresses')

    @classmethod
    def from_dict(cls, document):
        if not isinstance(document, Mapping) or set(document) != {'format', 'applications', 'groups'} or document['format'] != FORMAT:
            raise EdltError('Invalid lifecycle cache format or fields')
        if not isinstance(document['applications'], (tuple, list)) or not isinstance(document['groups'], (tuple, list)):
            raise EdltError('Cache applications and groups must be arrays')
        if len(document['applications']) > 256: raise EdltError('Cache exceeds256 applications')
        if len(document['groups']) > MAX_GROUPS: raise EdltError('Cache exceeds512 groups')
        groups = []
        for row in document['groups']:
            if not isinstance(row, Mapping) or not {'application', 'group', 'exists'} <= set(row) or set(row) - {
                    'application', 'group', 'exists', 'dynamic_images', 'levels'}:
                raise EdltError('Invalid lifecycle cache group fields')
            images = row.get('dynamic_images'); levels = row.get('levels')
            if images is not None and (not isinstance(images, (tuple, list)) or len(images) > 4):
                raise EdltError('dynamic_images must be null or at most four booleans')
            if 'levels' in row and (not isinstance(levels, (tuple, list)) or len(levels) > 256):
                raise EdltError('levels must be an array of at most256 addresses')
            groups.append(LifecycleGroup(row['application'], row['group'], row['exists'],
                None if images is None else tuple(images), 'dynamic_images' in row,
                None if levels is None else tuple(levels)))
        return cls(tuple(document['applications']), tuple(groups))

    def as_dict(self):
        return {'format': FORMAT, 'applications': list(self.applications), 'groups': [g.as_dict() for g in self.groups]}

    def find(self, application, group):
        return next((row for row in self.groups if (row.application, row.group) == (application, group)), None)


@dataclass(frozen=True)
class LifecycleRequirements:
    """JSON stored canonically so nested requirement facts remain immutable."""
    document: str

    def as_dict(self):
        return json.loads(self.document)


@dataclass(frozen=True)
class LifecyclePlan:
    expected: Mapping
    after_load: Mapping
    before_save: Mapping
    changes: Mapping
    metadata: LifecycleCache
    requirements: LifecycleRequirements
    evidence: str

    def __post_init__(self):
        for name in ('expected', 'after_load', 'before_save', 'changes'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        final = {**self.expected, **self.changes}
        return {'format': 'cbus-edlt-lifecycle-plan-v1', 'unit_type': 'KEYGL5', 'catalog_number': '5055EDL',
                'firmware': '5.5.00', 'phases': {'after_load': _delta(self.expected, self.after_load),
                    'before_save': _delta(self.after_load, self.before_save), 'crc': _delta(self.before_save, final)},
                'changes': {name: list(value) if isinstance(value, tuple) else value for name, value in self.changes.items()},
                'requirements': self.requirements.as_dict(), **json.loads(self.evidence),
                'model_cycle_complete': True, 'model_cycle_scope': 'AfterLoadPPData; BeforeSavePPData(saveDb=true,saveNw=false); configuration CRCs',
                'metadata_provenance': 'caller-supplied-cache', 'database_metadata_created': False, 'cache_freshness_verified': False,
                'physical_device_verified': False, 'winforms_initialization_verified': False, 'saved': False}


@dataclass(frozen=True)
class LoadedWidget:
    """Stable slot identity and actual retained model, without invoking getters."""
    slot: int
    original_type: int
    stored_type: int
    model_family: str

    def as_dict(self):
        return {'identity': 'widget:' + str(self.slot), 'slot': self.slot,
                'original_type': self.original_type, 'stored_type': self.stored_type,
                'model_family': self.model_family}


@dataclass(frozen=True)
class LoadedPageWidget:
    stored_variant: int

    def as_dict(self):
        return {'identity': 'page-widget', 'model_family': 'PageWidgetData',
                'stored_variant': self.stored_variant}


@dataclass(frozen=True)
class LoadedSceneItem:
    # This is the same immutable cache object shared by other items referring
    # to it, not a group number to resolve using a future scene selector.
    group: LifecycleGroup
    ramp_rate: int
    can_edit: bool
    level: int

    def as_dict(self):
        return {'group_reference': {'application': self.group.application, 'group': self.group.group},
                'ramp_rate': self.ramp_rate, 'can_edit': self.can_edit, 'level': self.level}


@dataclass(frozen=True)
class LoadedScene:
    slot: int
    source_pointer: int
    primary_secondary: int
    can_edit: bool
    trigger: LifecycleGroup
    action_selector: int
    name_index: int
    items: tuple[LoadedSceneItem, ...]

    def as_dict(self):
        return {'identity': 'scene:' + str(self.slot), 'slot': self.slot,
                'source_pointer': self.source_pointer, 'primary_secondary': self.primary_secondary,
                'can_edit': self.can_edit, 'trigger_group': self.trigger.group,
                'stored_action_selector': self.action_selector, 'name_index': self.name_index,
                'items': [item.as_dict() for item in self.items]}


@dataclass(frozen=True)
class LoadedStaticLabel:
    index: int
    original_bytes: tuple[int, ...]

    def as_dict(self):
        raw = bytes(self.original_bytes).split(b'\0', 1)[0]
        try: text = raw.decode('utf-8')
        except UnicodeDecodeError: text = None
        return {'index': self.index, 'original_bytes': list(self.original_bytes),
                'valid_utf8_text': text, 'original_invalid_utf8_text_evaluated': False}


@dataclass(frozen=True)
class LoadedMRA:
    source_widget: int | None
    multiplexer: int
    zone: int

    def as_dict(self):
        return {'source_widget': self.source_widget, 'multiplexer': self.multiplexer, 'zone': self.zone}


class _LoadedOrigin:
    """Identity receipt: dataclass.replace is not an accepted model operation."""
    def __init__(self, owner):
        self.owner = owner
        self.reference = None


@dataclass(frozen=True)
class LoadedEdlt:
    """Immutable, unbound AfterLoad state issued by one EdltLifecycle instance.

    The diagnostic representation is deliberately not a deserialization API.
    It retains model references that cannot be recovered from PP bytes alone.
    No application controls or dependency getters have been invoked.
    """
    expected: Mapping
    after_load: Mapping
    metadata: LifecycleCache
    requirements: LifecycleRequirements
    widgets: tuple[LoadedWidget, ...]
    page_widget: LoadedPageWidget
    scenes: tuple[LoadedScene, ...]
    static_labels: tuple[LoadedStaticLabel, ...]
    mra: LoadedMRA
    consumed_facts: str
    events: str
    _origin: _LoadedOrigin = field(repr=False, compare=False)

    def __post_init__(self):
        for name in ('expected', 'after_load'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-loaded-model-v1', 'phase': 'after_load',
                'unit_type': 'KEYGL5', 'catalog_number': '5055EDL', 'firmware': '5.5.00',
                'after_load_changes': _delta(self.expected, self.after_load),
                'widgets': [widget.as_dict() for widget in self.widgets],
                'page_widget': self.page_widget.as_dict(),
                'scenes': [scene.as_dict() for scene in self.scenes],
                'static_labels': [label.as_dict() for label in self.static_labels],
                'mra': self.mra.as_dict(), 'metadata_facts_consumed': json.loads(self.consumed_facts),
                'events': json.loads(self.events), 'bound_controls': [],
                'model_state_resumption_supported': False, 'metadata_provenance': 'caller-supplied-cache',
                'physical_device_verified': False, 'winforms_initialization_verified': False}


@dataclass(frozen=True)
class BlankedEdlt:
    """One engine-issued Blank selection on an intact, retained loaded model."""
    base: LoadedEdlt
    slot: int
    type_changed: bool
    after_controls: Mapping
    widgets: tuple[LoadedWidget, ...]
    _origin: _LoadedOrigin = field(repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, 'after_controls', MappingProxyType(dict(self.after_controls)))

    def as_dict(self):
        return {'format': 'cbus-edlt-blanked-model-v1', 'phase': 'after_controls',
                'operation': 'select Blank', 'slot': self.slot, 'type_changed': self.type_changed,
                'after_controls_changes': _delta(self.base.after_load, self.after_controls),
                'widgets': [widget.as_dict() for widget in self.widgets],
                'scene_references_retained': True, 'static_references_retained': True,
                'mra_globals_retained': self.base.mra.as_dict(),
                'physical_device_verified': False, 'winforms_initialization_verified': False}


@dataclass(frozen=True)
class ResetEdlt:
    """Issued Reset transition: an original base and genuinely fresh models."""
    base: LoadedEdlt
    fresh: LoadedEdlt
    expected: Mapping
    after_controls: Mapping
    widgets: tuple[LoadedWidget, ...]
    context: object = field(repr=False)
    raw_phases: Mapping = field(repr=False)
    _origin: _LoadedOrigin = field(repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, 'expected', MappingProxyType(dict(self.expected)))
        object.__setattr__(self, 'after_controls', MappingProxyType(dict(self.after_controls)))
        object.__setattr__(self, 'raw_phases', MappingProxyType(dict(self.raw_phases)))

    def as_dict(self):
        return {'format': 'cbus-edlt-reset-model-v1', 'phase': 'after_reset_controls',
                'new_widget_models': 21, 'new_scene_models': 8,
                'old_scene_references_retained': False,
                'original_expected_retained': True,
                'fresh_load': self.fresh.as_dict(),
                'widget10': {'type': 10, 'display_type': 2},
                'physical_device_verified': False, 'full_form_verified': False}


@dataclass(frozen=True)
class FactoryResetEdlt:
    """Issued Global-tab Reset and removal; raw Project is a model sidecar."""
    base: LoadedEdlt
    fresh: LoadedEdlt
    expected: Mapping
    after_controls: Mapping
    widgets: tuple[LoadedWidget, ...]
    context: object = field(repr=False)
    raw_phases: Mapping = field(repr=False)
    project_assignment: object
    _origin: _LoadedOrigin = field(repr=False, compare=False)

    def __post_init__(self):
        for name in ('expected', 'after_controls', 'raw_phases'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-factory-reset-model-v1',
                'factory_context': 'factory-global-reset-then-remove-global-tab-v1',
                'phase': 'after-global-tab-removal', 'original_expected_retained': True,
                'new_widget_models': 21, 'new_scene_models': 8,
                'old_scene_references_retained': False, 'fresh_load': self.fresh.as_dict(),
                'project_assignment': self.project_assignment.as_dict(),
                'oem_projection': {'parameter': 'Project', 'original_value': self.expected['Project'],
                    'raw_model_value': self.project_assignment.after.value,
                    'physical_codec_relaxed': False},
                'initial_global_tab': True, 'global_tab_removed_after_reset': True,
                'widget10': {'type': 10, 'display_type': 2},
                'full_form_executed': False, 'renderer_verified': False,
                'global_bridge_enabled': False, 'physical_device_verified': False}


_MODEL_FAMILIES = {0: 'BlankData', 2: 'LightingData', 3: 'ShutterRelayData',
    4: 'FanControllerData', 5: 'TimerData', 6: 'SceneData', 7: 'MRAZoneControlData',
    8: 'MRASourceSelectData', 9: 'MRASourceControlData', 10: 'TimeAndDateData',
    11: 'TimeAndDateData', 12: 'MeasurementData', 13: 'HVACTempDisplayData',
    14: 'EnableData', 15: 'RCPData', 16: 'MultiLevelData'}


def _scene_bytes(scene):
    """SaveScenes projection using retained private state and cached objects."""
    action = scene.action_selector
    if scene.trigger.group == 255:
        action = 255
    elif action == -1:
        action = 0 if 0 in scene.trigger.levels else 255
    header = (int(scene.can_edit) * 2 + scene.primary_secondary, len(scene.items),
              scene.trigger.group, action, scene.name_index)
    items = tuple((int(item.can_edit) * 16 + item.ramp_rate, item.group.group, item.level)
                  for item in scene.items)
    return header, items


class EdltLifecycle:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        self._loaded_owner = object()
        for name, wanted in {'InvertDisplay': (0x118, 'bit', 3, 1, 1),
                             'SceneCount': (0x2100, 'int', 0, 8, 1)}.items():
            try: layout = self.codec.layout(name)
            except (ValueError, KeyError) as error: raise EdltError('Unsupported lifecycle layout: ' + name) from error
            if (layout.address, layout.parameter.type, layout.bit_address, layout.bit_size, layout.array_size) != wanted or layout.array_skip:
                raise EdltError('Unsupported lifecycle layout: ' + name)

    def snapshot(self, values): return self.common.snapshot(values)
    def crcs(self, values): return self.common.crcs(values)

    @staticmethod
    def _scenes(values):
        bucket = values['SceneBucket']
        if len(bucket) != 232: raise EdltError('Lifecycle requires all232 scene bucket bytes')
        _int(values['SceneCount'][0], 'SceneCount', 0, 8)
        result = []
        for slot in range(1, 9):
            pointer = values[f'Scene{slot}StartAddress'][0]
            if pointer >= 255:
                result.append((slot, pointer, (2, 0, 255, 255, 255), ())); continue
            if pointer >= len(bucket): raise EdltError(f'Scene{slot} pointer is outside the232-byte bucket')
            if bucket[pointer] == 255:
                result.append((slot, pointer, (2, 0, 255, 255, 255), ())); continue
            if pointer + 5 > len(bucket): raise EdltError(f'Scene{slot} header is truncated')
            header = tuple(bucket[pointer:pointer + 5]); count = header[1]
            if count > 64 or pointer + 5 + 3 * count > len(bucket):
                raise EdltError(f'Scene{slot} item data is outside the scene bucket')
            items = tuple(tuple(bucket[pointer + 5 + 3*i:pointer + 8 + 3*i]) for i in range(count))
            result.append((slot, pointer, header, items))
        if 40 + 3 * sum(len(row[3]) for row in result) > 232:
            raise EdltError('Eight loaded scene slots exceed232 repacked bytes')
        return tuple(result)

    @staticmethod
    def _primary(values): return 56 if values['PrimaryApplication'] == (255,) else values['PrimaryApplication'][0]

    def requirements(self, current):
        values = self.snapshot(current); scenes = self._scenes(values); primary = self._primary(values)
        apps, groups = {}, {}
        def app(address, reason): apps.setdefault(address, []).append(reason)
        def group(address, number, reason, *, images=None, levels=False, conditional=None):
            app(address, reason)
            row = groups.setdefault((address, number), {'application': address, 'group': number,
                    'facts': {'exists': []}, 'conditional_reasons': []})
            row['facts']['exists'].append(reason)
            if conditional: row['conditional_reasons'].append(conditional)
            if images is not None: row['facts'].setdefault('dynamic_images_if_present', []).append({'effective_index': images, 'reason': reason})
            if levels: row['facts'].setdefault('complete_levels_if_present', []).append(reason)
        app(primary, 'Primary application and unit-level group bindings')
        app(202, 'All eight scene trigger lookups')
        app(203, 'KeySetsEnableGroup binding')
        stopped = False
        for widget in range(1, 22):
            kind = values[_field(widget)][0]; control = values[_field(widget, 1)][0]
            selected = values['SecondaryApplication'][0] if control & 128 and values['SecondaryApplication'] != (255,) else primary
            if kind == 2:
                label = control >> 4 & 7; index = values[_field(widget, 13)][0]
                group(selected, values[_field(widget, 6)][0], f'Widget{widget} Lighting constructor (including hidden tails)',
                      images=(index if index < 4 else 0) if label in (1, 2) else None)
            retained = kind not in (1, 255) and not (widget >= 6 and stopped)
            if retained and kind in _APP_GROUP_TYPES:
                group(203 if kind == 14 else selected, values[_field(widget, 6)][0], f'Widget{widget} final group lookup')
            if widget >= 6 and kind == 255: stopped = True
        for slot, pointer, header, items in scenes:
            trigger = header[2]
            group(202, trigger, f'Scene{slot} trigger', levels=trigger != 255)
            if trigger != 255:
                group(202, 255, f'Scene{slot} missing-trigger fallback', conditional=f'Only if cached trigger{trigger} is absent')
            selected = values['SecondaryApplication'][0] if header[0] & 1 and values['SecondaryApplication'] != (255,) else primary
            for _, number, _ in items: group(selected, number, f'Scene{slot} output item; group must exist')
        return LifecycleRequirements(_json({'format': 'cbus-edlt-lifecycle-requirements-v1',
            'unit_type': 'KEYGL5', 'catalog_number': '5055EDL', 'firmware': '5.5.00',
            'applications': [{'application': address, 'reasons': list(dict.fromkeys(reasons))} for address, reasons in sorted(apps.items())],
            'groups': [row for _, row in sorted(groups.items())], 'metadata_format': FORMAT,
            'no_io': True, 'level_cache_contract': 'levels lists complete populated native level objects, including initialized DynamicAll collections; partial uninitialized level caches cannot be represented',
            'conditional_image_null_means': 'Existing DynamicAll is unpopulated; original constructor preserves label type',
            'cache_freshness_verified': False, 'physical_device_verified': False}))

    def plan(self, current, *, metadata):
        return self.prepare_save(self.load(current, metadata=metadata))

    def load(self, current, *, metadata):
        """Load one unbound model; preserve the original no-edit preflight rules."""
        original = self.snapshot(current); scenes = self._scenes(original); requirements = self.requirements(original)
        cache = LifecycleCache.from_dict(metadata.as_dict() if isinstance(metadata, LifecycleCache) else metadata)
        consumed, events = [], []
        def application(address, reason):
            if address not in cache.applications:
                raise LifecycleMetadataError('Required cached application is missing: ' + str(address),
                    {'application': address, 'reason': reason}, original_stage='after_load')
        def group(address, number, reason):
            application(address, reason); row = cache.find(address, number)
            if row is None:
                raise LifecycleMetadataError('Unknown cached group; provide explicit exists evidence',
                    {'application': address, 'group': number, 'field': 'exists', 'reason': reason})
            consumed.append({'application': address, 'group': number, 'field': 'exists', 'value': row.exists, 'reason': reason})
            return row
        def event(phase, reason, **fields): events.append(dict(phase=phase, reason=reason, **fields))
        values = dict(original); primary = self._primary(values)
        for address, reason in ((primary, 'primary bindings'), (202, 'scenes'), (203, 'enable binding')): application(address, reason)
        for name, old, new in (('PrimaryApplication',255,56), ('InvertDisplay',1,0),
                              ('ConfigVersionMajor',255,1), ('ConfigVersionMinor',255,0)):
            if values[name] == (old,): values[name] = (new,); event('after_load', 'original load normalization', parameter=name)
        loaded_scenes = []
        for slot, pointer, header, items in scenes:
            flags, _, trigger, action, name = header
            selected = values['SecondaryApplication'][0] if flags & 1 and values['SecondaryApplication'] != (255,) else primary
            flags = (flags & 2) | (1 if flags & 1 and values['SecondaryApplication'] != (255,) else 0)
            trigger_row = group(202, trigger, f'Scene{slot} trigger')
            if not trigger_row.exists:
                trigger = 255; trigger_row = group(202, 255, f'Scene{slot} missing-trigger fallback')
            if not trigger_row.exists:
                raise LifecycleMetadataError('Original scene load requires the cached unused trigger group255',
                    {'application':202,'group':255,'reason':f'Scene{slot}'}, original_stage='after_load')
            if trigger == 255: action = -1
            else:
                if trigger_row.levels is None:
                    raise LifecycleMetadataError('Unknown cached scene actions; complete level addresses are required',
                        {'application':202,'group':trigger,'field':'levels','reason':f'Scene{slot}'})
                consumed.append({'application':202,'group':trigger,'field':'levels','value':list(trigger_row.levels),'reason':f'Scene{slot}'})
                if action not in trigger_row.levels: action = -1
            output = []
            for control, number, level in items:
                output_group = group(selected, number, f'Scene{slot} output item')
                if not output_group.exists:
                    raise LifecycleMetadataError('Original scene save fails for an absent output group',
                        {'application':selected,'group':number,'reason':f'Scene{slot}'}, original_stage='before_save')
                output.append(LoadedSceneItem(output_group, control & 15, bool(control & 16), level))
            scene = LoadedScene(slot, pointer, flags & 1, bool(flags & 2), trigger_row, action, name, tuple(output))
            loaded_scenes.append(scene)
            saved_header, saved_items = _scene_bytes(scene)
            if saved_header != header or saved_items != items:
                event('before_save','scene fields resolved from original flags and cache',scene=slot)
        stopped = False
        def reset_type(widget, wanted):
            key = _field(widget)
            if values[key] != (wanted,):
                values[key] = (wanted,)
                if widget >= 6: values[f'Widget{widget}RestoreLevel'] = (0,)
        for widget in range(1,22):
            kind = values[_field(widget)][0]
            if kind == 1:
                reset_type(widget,0); kind=0; event('after_load','legacy type1 reads as Blank',widget=widget)
            if kind == 2:
                control=values[_field(widget,1)][0]
                if control & 128 and values['SecondaryApplication'] == (255,):
                    control &= 127; values[_field(widget,1)] = (control,)
                selected = values['SecondaryApplication'][0] if control & 128 else primary
                row=group(selected,values[_field(widget,6)][0],f'Widget{widget} Lighting constructor')
                label=control>>4 & 7
                if row.exists and label in (1,2):
                    if not row.dynamic_images_known:
                        raise LifecycleMetadataError('Unknown cached image presence for dynamic Lighting label',
                            {'application':selected,'group':row.group,'field':'dynamic_images','reason':f'Widget{widget}'})
                    consumed.append({'application':selected,'group':row.group,'field':'dynamic_images',
                                     'value':None if row.dynamic_images is None else list(row.dynamic_images),'reason':f'Widget{widget}'})
                    if row.dynamic_images is not None:
                        stored=values[_field(widget,13)][0]; index=stored if stored<4 else 0
                        if index >= len(row.dynamic_images):
                            raise LifecycleMetadataError('Original Lighting constructor indexes outside the supplied DynamicAll list',
                                {'application':selected,'group':row.group,'field':'dynamic_images','effective_index':index,'reason':f'Widget{widget}'}, original_stage='after_load')
                        chosen=2 if row.dynamic_images[index] else 1
                        values[_field(widget,1)] = ((control & 0xCF) | (chosen<<4),)
            if kind == 14:
                old=(values[_field(widget,7)][0],values[_field(widget,8)][0])
                if not any(macro in (23,24) for macro in old): values[_field(widget,9)] = (255,)
                values[_field(widget,7)],values[_field(widget,8)] = (10,),(23,)
            if stopped or kind == 255:
                reset_type(widget,0)
                if widget>=6 and kind == 255: stopped=True
                if kind != 0: event('after_load','functional terminator tail' if widget>=6 else 'standby unused type',widget=widget,old_type=kind)
        # The original final CheckIfGroupsExist visits only surviving models.
        for widget in range(1,22):
            kind=values[_field(widget)][0]
            if kind not in _APP_GROUP_TYPES: continue
            control=values[_field(widget,1)][0]
            if kind != 14 and control & 128 and values['SecondaryApplication'] == (255,):
                control &= 127; values[_field(widget,1)] = (control,)
            selected=203 if kind==14 else values['SecondaryApplication'][0] if control&128 else primary
            group(selected,values[_field(widget,6)][0],f'Widget{widget} final group lookup')
        after_load=dict(values)
        widgets = tuple(LoadedWidget(widget, original[_field(widget)][0], values[_field(widget)][0],
                        _MODEL_FAMILIES.get(values[_field(widget)][0], 'BlankData')) for widget in range(1,22))
        first_mra = next((widget.slot for widget in widgets if widget.stored_type in (7,8,9)), None)
        mra_control = 0 if first_mra is None else values[_field(first_mra,1)][0]
        origin = _LoadedOrigin(self._loaded_owner)
        loaded = LoadedEdlt(original, after_load, cache, requirements, widgets,
                    LoadedPageWidget(values['NavWidgetType'][0]), tuple(loaded_scenes),
                    tuple(LoadedStaticLabel(index, values[f'StaticTextString{index}']) for index in range(64)),
                    LoadedMRA(first_mra, mra_control >> 6 & 3, mra_control >> 3 & 7),
                    _json(consumed), _json(events), origin)
        origin.reference = weakref.ref(loaded)
        return loaded

    def _validate_loaded(self, loaded):
        if (type(loaded) is not LoadedEdlt or type(loaded._origin) is not _LoadedOrigin or
                loaded._origin.owner is not self._loaded_owner or loaded._origin.reference is None or
                loaded._origin.reference() is not loaded):
            raise EdltError('Use an intact loaded model returned by this EdltLifecycle.load instance')

    def blank_widget(self, loaded, slot):
        """Select Blank once, retaining the loaded scenes and cached MRA globals.

        This model transition does not invoke the outer dialog or decide whether
        a position is visible; EdltBlankWidget supplies the bounded UI placement.
        """
        self._validate_loaded(loaded)
        _int(slot, 'Blank widget slot', 1, 21)
        values = dict(loaded.after_load)
        changed = values[_field(slot)] != (0,)
        widgets = loaded.widgets
        if changed:
            values[_field(slot)] = (0,)
            if slot >= 6:
                values[f'Widget{slot}RestoreLevel'] = (0,)
            old = loaded.widgets[slot - 1]
            widgets = (*loaded.widgets[:slot - 1],
                       LoadedWidget(slot, old.original_type, 0, 'BlankData'),
                       *loaded.widgets[slot:])
        origin = _LoadedOrigin(self._loaded_owner)
        result = BlankedEdlt(loaded, slot, changed, values, widgets, origin)
        origin.reference = weakref.ref(result)
        return result

    def reset_unit_controls(self, loaded, *, reset_context):
        """Perform the narrow validated Reset action; no PP override interface."""
        self._validate_loaded(loaded)
        from .edlt_reset import _reset_transition
        return _reset_transition(self, loaded, reset_context)

    def reset_global_factory_controls(self, loaded, *, factory_context):
        """Consume an issued factory context, never a caller PP overlay."""
        self._validate_loaded(loaded)
        from .edlt_reset import _factory_reset_transition
        return _factory_reset_transition(self, loaded, factory_context)

    def prepare_save(self, loaded):
        """Save retained models without another load or re-resolving scene groups.

        This pure terminal projection leaves the issued loaded state unchanged.
        It accepts only an intact state issued by this engine instance.
        """
        reset = loaded if type(loaded) in (ResetEdlt, FactoryResetEdlt) else None
        if reset is not None:
            if (type(reset._origin) is not _LoadedOrigin or reset._origin.owner is not self._loaded_owner
                    or reset._origin.reference is None or reset._origin.reference() is not reset):
                raise EdltError('Use an intact Reset transition returned by this EdltLifecycle instance')
            self._validate_loaded(reset.base)
            self._validate_loaded(reset.fresh)
            if type(reset) is FactoryResetEdlt:
                from .edlt_reset import _validate_factory_reset
                _validate_factory_reset(self, reset)
            else:
                from .edlt_reset import _validate_context
                _validate_context(self, reset.base, reset.context)
            loaded = reset.fresh
        blank = loaded if type(loaded) is BlankedEdlt else None
        if blank is not None:
            if (type(blank._origin) is not _LoadedOrigin or blank._origin.owner is not self._loaded_owner
                    or blank._origin.reference is None or blank._origin.reference() is not blank):
                raise EdltError('Use an intact Blank transition returned by this EdltLifecycle.blank_widget instance')
            loaded = blank.base
        self._validate_loaded(loaded)
        original = loaded.expected if reset is None else reset.expected
        after_load = loaded.after_load if reset is None else reset.base.after_load
        values = dict(reset.after_controls if reset is not None else
                      after_load if blank is None else blank.after_controls)
        def reset_type(widget, wanted):
            key = _field(widget)
            if values[key] != (wanted,):
                values[key] = (wanted,)
                if widget >= 6: values[f'Widget{widget}RestoreLevel'] = (0,)
        values['Application']=(values['PrimaryApplication'][0],values['SecondaryApplication'][0])
        bucket=bytearray(); pointers=[]
        for scene in loaded.scenes:
            header, items = _scene_bytes(scene)
            pointers.append(len(bucket)); bucket.extend(header)
            for item in items: bucket.extend(item)
        values['SceneCount']=(8,); values['SceneBucket']=tuple(bucket.ljust(232,b'\xff'))
        for index,pointer in enumerate(pointers,1): values[f'Scene{index}StartAddress']=(pointer,)
        first_mra=loaded.mra.source_widget
        if first_mra is not None:
            upper=(loaded.mra.multiplexer << 6) | (loaded.mra.zone << 3)
            for widget in range(1,22):
                if values[_field(widget)][0] in (7,8,9): values[_field(widget,1)]=((values[_field(widget,1)][0]&7)|upper,)
        last=21
        while last>=6 and values[_field(last)][0] in (0,255):last-=1
        if last<21:reset_type(last+1,255)
        for widget in range(6,last):
            if values[_field(widget)]==(255,):reset_type(widget,0)
        for widget in range(1,22):
            kind=values[_field(widget)][0]
            if kind==2 and values[_field(widget,12)]==(0,):values[_field(widget,12)]=(1,)
            if kind==5 and values[_field(widget,9)]==(0,):values[_field(widget,9)]=(1,)
            if kind in (4,16):
                control=values[_field(widget,1)][0]
                if control&15 != 5:values[_field(widget,10)]=(0,)
                values[_field(widget,1)]=((control&0xF0)|5,)
        before_save=dict(values); values.update(self.crcs(values))
        evidence={'metadata_facts_consumed':json.loads(loaded.consumed_facts),'events':json.loads(loaded.events),'scene_count':8,'scene_item_count':sum(len(scene.items) for scene in loaded.scenes),
                  'scene_pointers':pointers,'scene_bucket_hex':bytes(before_save['SceneBucket']).hex(),
                  'mra_source_widget':first_mra,'source_scene_count_ignored':original['SceneCount'][0],
                  'blank_fallback_widgets':[{'widget':widget,'stored_type':values[_field(widget)][0]} for widget in range(1,22) if 17<=values[_field(widget)][0]<=254]}
        if blank is not None:
            evidence['blank_transition'] = blank.as_dict()
        if reset is not None:
            evidence['reset_transition'] = reset.as_dict()
        return LifecyclePlan(original,after_load,before_save,_changes(original,values),loaded.metadata,loaded.requirements,_json(evidence))

    @staticmethod
    def _interrupted(error, plan, attempted, original_error=None):
        evidence={**plan.as_dict(),'verified':False,'saved':False,'attempted_parameters':list(attempted),
                  'pp_state_uncertain':bool(attempted),'automatic_retries':0}
        if original_error is not None:evidence['original_error']={'type':type(original_error).__name__,'error':_error_text(original_error)}
        error.edlt_lifecycle_evidence=evidence

    def apply(self, session, plan):
        if type(plan) is not LifecyclePlan or type(plan.metadata) is not LifecycleCache or type(plan.requirements) is not LifecycleRequirements:
            raise EdltError('Use a lifecycle plan returned by EdltLifecycle.plan')
        for values in (plan.expected,plan.after_load,plan.before_save,{**plan.expected,**plan.changes}):self.snapshot(values)
        canonical=self.plan(plan.expected,metadata=plan.metadata)
        if canonical != plan or _json(canonical.as_dict()) != _json(plan.as_dict()):
            raise EdltError('Plan differs from its validated original model lifecycle')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):raise EdltError('PP values changed since the lifecycle plan was made')
        expected={**plan.expected,**plan.changes};attempted=[]
        try:
            for name,value in plan.changes.items():attempted.append(name);session.set(name,_render(value))
            if self.snapshot(session.values()) != expected:raise EdltError('Native PP readback differs from the lifecycle plan')
        except (KeyboardInterrupt,SystemExit) as error:
            self._interrupted(error,plan,attempted);raise
        except Exception as error:
            rollback_errors=[]
            try:
                for name in reversed(attempted):
                    if not getattr(session.programmer.client,'connected',True):
                        rollback_errors.append('Connection lost; rollback stopped without recovery I/O; PP state is uncertain');break
                    try:session.set(name,_render(plan.expected[name]))
                    except Exception as rollback:rollback_errors.append(_error_text(rollback))
                if getattr(session.programmer.client,'connected',True):
                    try:
                        if self.snapshot(session.values()) != dict(plan.expected):rollback_errors.append('Original PP values could not be verified')
                    except Exception as rollback:rollback_errors.append(_error_text(rollback))
            except (KeyboardInterrupt,SystemExit) as interrupted:
                self._interrupted(interrupted,plan,attempted,error);interrupted.edlt_lifecycle_evidence['rollback_errors']=rollback_errors;raise
            raise EdltApplyError(error,rollback_errors,attempted) from error
        return {**plan.as_dict(),'verified':True}

    def configure(self,session,*,metadata):
        cache=LifecycleCache.from_dict(metadata.as_dict() if isinstance(metadata,LifecycleCache) else metadata)
        self.common._verify_identity(session)
        return self.apply(session,self.plan(session.values(),metadata=cache))
