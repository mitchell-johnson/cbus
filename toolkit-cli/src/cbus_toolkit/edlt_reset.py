"""Bounded original eDLT synchronous Reset controls and raw PP phase state.

This is a database model operation. It does not call physical Factory Reset,
construct the full Toolkit form, render it or resolve metadata from a network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
import hashlib
import json
import re
from types import MappingProxyType
from typing import Mapping
import weakref

from .edlt import EdltError, EdltApplyError, _field
from .edlt_lifecycle import (EdltLifecycle, LifecycleMetadataError, LoadedWidget,
                             ResetEdlt, FactoryResetEdlt, _LoadedOrigin, _json, _error_text)
from .edlt_application_cache import ApplicationCache

ACTIVE_TABS = ('widgets', 'general', 'standby', 'colour')
BINDING_VARIANTS = ('base-c3', 'audited-local-wiring')
RAW_FORMAT = 'cbus-edlt-raw-parameters-v1'
_EXCLUDED = frozenset(('UnitAddress', 'SerialNumber', 'Project', 'NetworkAddress',
                       'ConfigVersionMinor', 'ConfigVersionMajor'))
_INITIAL_TYPES = frozenset((0, 2, 6, 7, 8, 10, 255))
_FACTORY_IDENTITY = frozenset(('UnitAddress', 'UnitName', 'SerialNumber', 'Project'))
_FACTORY_SPEC_FIELDS = ('Address', 'ArraySize', 'ArraySkip', 'BitAddress', 'BitSize',
                        'DefaultValue', 'Endian', 'Name', 'Type')
_FACTORY_SPEC_SHA256 = '7b81b12878c4c1b93106f8d8228cad9023165c0804fe097faba5254e57caae42'
# Whole numeric source patterns, independently captured from the original
# factory/handler pairs. These are not per-field options or combinable ranges.
# Evidence: edlt-reset-factory-rich-vectors.json and edlt-reset-factory.md.
_FACTORY_PATTERNS = MappingProxyType({
    '1192611fda8de23c52c630cbeeb70653c0387471451bce3766f2b5381c4db729': 'default-like',
    '101095e90615d4c9b36314b310172ab4d9be08a5567f2c0a9f97d51d5c0c03ff': 'rich-scene',
    '4642cb6bd0f58b712218c546e25060a0b5e0494f1356718a723f07647ab08c4b': 'first-mra',
    'b3576c0bbccfb4f43c21209deaac6b44a96c5db4a792e9fcdbf0c691c670eddd': 'enable',
    'bec05af627fea0ea6f545566ad203f490f58bf37a582cec49c2b417df04ad66d': 'mixed-controls',
    'faea4abfb432a7e2bb45ee1a01f10679c10dafd672b474e2e1e38050b5ece036': 'fallback127',
})
_GROUP_FIELDS = ('BacklightActiveBrightnessControlGroup', 'BacklightIdleBrightnessControlGroup',
    'IndicatorActiveBrightnessControlGroup', 'IndicatorIdleBrightnessControlGroup',
    'IndicatorOnColourControlGroup', 'IndicatorOffColourControlGroup', 'QuickStatusGroup',
    'CorridorLinkingLinkGroup', 'CorridorLinkingOfficeGroup', 'CorridorLinkingCorridorGroup')


def _choice(value, choices, name):
    if type(value) is not str or value not in choices:
        raise EdltError(name + ' must be one of ' + ', '.join(choices))


def _dirty(names, known):
    if not isinstance(names, (tuple, list)) or len(names) > len(known):
        raise EdltError('Dirty parameters must be a bounded list of unique parameter names')
    if any(type(name) is not str or name not in known for name in names) or len(set(names)) != len(names):
        raise EdltError('Dirty parameters contain an unknown or duplicate name')
    return tuple(sorted(names))


def _join(tokens):
    # PPAttribute.Value: leading empty tokens do not add a separator until the
    # StringBuilder has content. Trailing empty tokens after content survive.
    value = ''
    for token in tokens:
        if value: value += ' '
        value += token
    return value


def _token(value):
    if value == '0xffffffff': return '0xff'
    if value.startswith('$x'): return '0' + value[1:]
    if value.startswith('$'): return '0x' + value[1:].upper()
    return value


@dataclass(frozen=True)
class ResetPhase:
    tokens: Mapping
    dirty_parameters: tuple[str, ...]
    initializing: bool

    def __post_init__(self):
        object.__setattr__(self, 'tokens', MappingProxyType({k: tuple(v) for k, v in self.tokens.items()}))

    @property
    def raw(self): return MappingProxyType({k: _join(v) for k, v in self.tokens.items()})

    def as_dict(self):
        return {'raw': dict(self.raw), 'tokens': {k: list(v) for k, v in self.tokens.items()},
                'dirty_parameters': list(self.dirty_parameters), 'initializing': self.initializing}


class _RawState:
    def __init__(self, raw, dirty=()):
        self.tokens = {name: [_token(part) for part in value.split(' ')] for name, value in raw.items()}
        self.dirty = set(dirty)
        self.initializing = True

    def phase(self): return ResetPhase(self.tokens, tuple(sorted(self.dirty)), self.initializing)
    @classmethod
    def from_phase(cls, phase):
        state = cls({})
        state.tokens = {name: list(tokens) for name, tokens in phase.tokens.items()}
        state.dirty = set(phase.dirty_parameters); state.initializing = phase.initializing
        return state
    def raw(self): return {k: _join(v) for k, v in self.tokens.items()}
    def number(self, name):
        value = self.tokens[name][0]
        return int(value[2:], 16) if value.lower().startswith('0x') else int(value)

    def set(self, name, value):
        # Original Value setter overwrites supplied slots, never clears a tail.
        target = self.tokens[name]
        for index, token in enumerate(value.split(' ')):
            token = _token(token)
            if index < len(target):
                changed = target[index] != token
                target[index] = token
            else:
                target.append(token); changed = True
            if changed and not self.initializing: self.dirty.add(name)

    def integer(self, name, value):
        # Actual ValueAsInt clamps to one byte. Public schema validation occurs
        # before this private original-setter projection.
        value = min(255, max(0, value))
        target = self.tokens[name]
        token = f'0x{value:X}'
        if target[0] != token and not self.initializing: self.dirty.add(name)
        target[0] = token


@dataclass(frozen=True)
class ResetRequirements:
    document: str
    def as_dict(self): return json.loads(self.document)


class _ContextOrigin:
    def __init__(self, owner): self.owner, self.reference = owner, None


@dataclass(frozen=True)
class _ResetContext:
    base: object
    expected_raw: Mapping
    metadata: ApplicationCache
    active_tab: str
    binding_variant: str
    dirty_parameters: tuple[str, ...]
    _origin: _ContextOrigin = field(repr=False, compare=False)

    def __post_init__(self): object.__setattr__(self, 'expected_raw', MappingProxyType(dict(self.expected_raw)))


@dataclass(frozen=True)
class _FactoryResetContext:
    base: object
    preparation_context: object
    _origin: _ContextOrigin = field(repr=False, compare=False)


def _validate_factory_reset_context(lifecycle, base, context):
    if (type(context) is not _FactoryResetContext or type(context._origin) is not _ContextOrigin
            or context._origin.reference is None or context._origin.reference() is not context
            or context._origin.owner.lifecycle is not lifecycle or context.base is not base):
        raise EdltError('Use the intact factory Reset context issued for this loaded model')
    from .edlt_global_preparation import _validate_factory_context
    return _validate_factory_context(context.preparation_context, context._origin.owner)


def _factory_reset_transition(lifecycle, base, context):
    _validate_factory_reset_context(lifecycle, base, context)
    return context._origin.owner._factory_transition(base, context)


def _validate_factory_reset(lifecycle, state):
    if (type(state) is not FactoryResetEdlt or type(state._origin) is not _LoadedOrigin
            or state._origin.owner is not lifecycle._loaded_owner
            or state._origin.reference is None or state._origin.reference() is not state):
        raise EdltError('Use an intact factory Reset state issued by this lifecycle')
    lifecycle._validate_loaded(state.base)
    lifecycle._validate_loaded(state.fresh)
    receipt = _validate_factory_reset_context(lifecycle, state.base, state.context)
    if (state.base is not getattr(state._origin, 'factory_base', None)
            or state.fresh is not getattr(state._origin, 'factory_fresh', None)
            or state.context is not getattr(state._origin, 'factory_context', None)
            or state.widgets is not getattr(state._origin, 'factory_widgets', None)
            or len(_factory_retained_objects(state)) != len(state._origin.factory_retained)
            or any(a is not b for a, b in zip(_factory_retained_objects(state), state._origin.factory_retained))
            or _factory_state_content(state) != getattr(state._origin, 'factory_content', None)):
        raise EdltError('Factory Reset state differs from its issued retained identities or phases')
    return receipt


def _factory_state_content(state):
    return _json({'expected': dict(state.expected), 'after_controls': dict(state.after_controls),
        'phases': {name: phase.as_dict() for name, phase in state.raw_phases.items()},
        'project_assignment': state.project_assignment.as_dict(),
        'loaded': [{'expected': dict(loaded.expected), 'after_load': dict(loaded.after_load),
            'metadata': loaded.metadata.as_dict(), 'requirements': loaded.requirements.as_dict(),
            'model': loaded.as_dict()} for loaded in (state.base, state.fresh)]})


def _factory_retained_objects(state):
    objects = [state.project_assignment, *state.widgets]
    for loaded in (state.base, state.fresh):
        objects.extend((loaded.widgets, *loaded.widgets, loaded.scenes, *loaded.scenes,
            loaded.static_labels, *loaded.static_labels, loaded.mra, loaded.page_widget,
            loaded.metadata, loaded.requirements))
        for scene in loaded.scenes:
            objects.extend((scene.trigger, scene.items, *scene.items, *(item.group for item in scene.items)))
    return tuple(objects)


@dataclass(frozen=True)
class FactoryResetSave:
    state: FactoryResetEdlt
    model_plan: object
    phases: Mapping

    def __post_init__(self): object.__setattr__(self, 'phases', MappingProxyType(dict(self.phases)))

    def as_dict(self):
        return {'format': 'cbus-edlt-factory-reset-save-v1', 'state': self.state.as_dict(),
            'model_plan': self.model_plan.as_dict(),
            'phases': {name: phase.as_dict() for name, phase in self.phases.items()},
            'third_after_load_performed': False, 'global_bridge_enabled': False,
            'saved': False, 'physical_device_verified': False}


def _validate_context(lifecycle, base, context):
    if (type(context) is not _ResetContext or type(context._origin) is not _ContextOrigin
            or context._origin.reference is None or context._origin.reference() is not context
            or context._origin.owner.lifecycle is not lifecycle or context.base is not base):
        raise EdltError('Use the intact Reset context issued for this loaded model and editor')


def _reset_transition(lifecycle, base, context):
    _validate_context(lifecycle, base, context)
    return context._origin.owner._transition(base, context)[0]


@dataclass(frozen=True)
class ResetPlan:
    expected_raw: Mapping
    expected: Mapping
    phases: Mapping
    before_save: Mapping
    changes: Mapping
    metadata: ApplicationCache
    active_tab: str
    binding_variant: str
    dirty_parameters: tuple[str, ...]
    specification_sha256: str
    evidence: str

    def __post_init__(self):
        for name in ('expected_raw', 'expected', 'phases', 'before_save', 'changes'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-reset-plan-v1', 'unit_type': 'KEYGL5',
            'catalog_number': '5055EDL', 'firmware': '5.5.00',
            'active_tab': self.active_tab, 'binding_variant': self.binding_variant,
            'initial_dirty_parameters': list(self.dirty_parameters),
            'dirty_state_provenance': 'caller-declared local editor state',
            'specification_sha256': self.specification_sha256,
            'phases': {name: phase.as_dict() for name, phase in self.phases.items()},
            'changes': {k: list(v) if isinstance(v, tuple) else v for k, v in self.changes.items()},
            **json.loads(self.evidence), 'metadata_provenance': 'caller-supplied-cache',
            'database_metadata_created': False, 'cache_freshness_verified': False,
            'full_form_initialization_verified': False, 'renderer_verified': False,
            'global_programming_initialization_verified': False,
            'physical_factory_reset_performed': False, 'physical_device_verified': False, 'saved': False}


class EdltResetControls:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00', lifecycle=None):
        if lifecycle is None:
            self.lifecycle = EdltLifecycle(spec, catalog_number=catalog_number, firmware=firmware)
        else:
            if (type(lifecycle) is not EdltLifecycle or lifecycle.spec is not spec
                    or (catalog_number, firmware) != ('5055EDL', '5.5.00')):
                raise EdltError('Use the exact shared EdltLifecycle and specification for this profile')
            self.lifecycle = lifecycle
        self.common, self.spec = self.lifecycle.common, spec
        self.codec = self.common.codec
        self.last_evidence = None
        if len(spec.parameters) != 874:
            raise EdltError('Reset requires the complete original 874-parameter profile')
        defaults = {}
        for name, parameter in spec.parameters.items():
            value = parameter.default
            if type(value) is not str:
                raise EdltError('Reset requires an explicit original default for ' + name)
            defaults[name] = value if name == 'UnitName' else ' '.join(
                ('0x0' if part == '0x' else part)
                for part in value.strip().replace('$0', '0x').replace('$', '0x').split(' '))
        self.defaults = MappingProxyType(defaults)
        # Critical constructor precondition: this transition recreates Blank
        # models from the actual default FF types before inserting Time/Date.
        if any(defaults[_field(i)] != '0xFF' for i in range(1, 22)) or defaults['NavWidgetType'] != '0xFF':
            raise EdltError('Unsupported Reset widget defaults; original uppercase 0xFF values are required')
        self.snapshot(_RawState(defaults).raw())
        self.specification_sha256 = hashlib.sha256(_json([
            (name, parameter.type, dict(parameter.fields)) for name, parameter in spec.parameters.items()
        ]).encode()).hexdigest()

    def snapshot(self, values): return self.common.snapshot(values)
    def crcs(self, values): return self.common.crcs(values)

    def raw_input(self, values):
        if not isinstance(values, Mapping) or set(values) != set(self.spec.parameters):
            raise EdltError('Reset requires all 874 raw PP strings matching the specification')
        if any(type(value) is not str or len(value) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in value)
               for value in values.values()) or sum(len(v) for v in values.values()) > 262144:
            raise EdltError('Reset requires bounded raw PP strings without control characters')
        for name, value in values.items():
            if self.spec.get(name).type not in ('string', 'sixbit'):
                if not re.fullmatch(r'(?:0[xX][0-9A-Fa-f]+|[0-9]+)(?: (?:0[xX][0-9A-Fa-f]+|[0-9]+))*', value):
                    raise EdltError('Numeric raw PP must contain decimal or 0x tokens separated by single spaces: ' + name)
        self.snapshot(values)
        return dict(values)

    def raw_document(self, values):
        return {'format': RAW_FORMAT, 'unit_type': 'KEYGL5', 'catalog_number': '5055EDL',
                'firmware': '5.5.00', 'parameters': self.raw_input(values)}

    def read_raw_document(self, document):
        if (not isinstance(document, Mapping) or set(document) != {
                'format', 'unit_type', 'catalog_number', 'firmware', 'parameters'}
                or document['format'] not in (RAW_FORMAT, 'cbus-cli-parameters-v1')
                or (document['unit_type'], document['catalog_number'], document['firmware']) !=
                   ('KEYGL5', '5055EDL', '5.5.00')):
            raise EdltError('Expected an exact-profile raw eDLT parameter export')
        return self.raw_input(document['parameters'])

    def requirements(self, raw_parameters, *, active_tab, binding_variant):
        raw = self.raw_input(raw_parameters)
        _choice(active_tab, ACTIVE_TABS, 'Active tab'); _choice(binding_variant, BINDING_VARIANTS, 'Binding variant')
        current = self.snapshot(raw)
        fresh = self.snapshot(_RawState(self.defaults).raw())
        for name in _EXCLUDED: fresh[name] = current[name]
        # Config fields may already normalize in the initial AfterLoad.
        for name, replacement in (('ConfigVersionMinor', 0), ('ConfigVersionMajor', 1)):
            if fresh[name] == (255,): fresh[name] = (replacement,)
        primary = 56 if current['PrimaryApplication'] == (255,) else current['PrimaryApplication'][0]
        control_groups = [{'application': primary, 'group': current[name][0], 'parameter': name}
                          for name in _GROUP_FIELDS if current[name] != (255,)]
        if current['KeySetsEnableGroup'] != (255,):
            control_groups.append({'application': 203, 'group': current['KeySetsEnableGroup'][0], 'parameter': 'KeySetsEnableGroup'})
        if current['ProximityGroup'] != (255,):
            control_groups.append({'application': 202 if current['ProximityMode'] == (3,) else primary,
                                   'group': current['ProximityGroup'][0], 'parameter': 'ProximityGroup'})
        initial_requirements = self.lifecycle.requirements(current).as_dict()
        fresh_requirements = self.lifecycle.requirements(fresh).as_dict()
        needed_lists = {primary, fresh['PrimaryApplication'][0], 202, 203}
        needed_lists.update(row['application'] for row in initial_requirements['groups'])
        return ResetRequirements(_json({'format': 'cbus-edlt-reset-requirements-v1',
            'active_tab': active_tab, 'binding_variant': binding_variant,
            'initial_load': initial_requirements,
            'fresh_reset_load': fresh_requirements,
            'control_groups': control_groups, 'complete_application_list': True,
            'complete_group_lists': sorted(needed_lists),
            'positive_control_presence_required': True, 'metadata_format': 'cbus-edlt-application-cache-v1',
            'initial_supported_widget_types': sorted(_INITIAL_TYPES),
            'no_io': True, 'cache_freshness_verified': False, 'physical_device_verified': False}))

    def _metadata(self, raw, active_tab, binding_variant, metadata):
        cache = ApplicationCache.from_dict(metadata.as_dict() if isinstance(metadata, ApplicationCache) else metadata)
        wanted = self.requirements(raw, active_tab=active_tab, binding_variant=binding_variant).as_dict()
        if not cache.applications_complete:
            raise EdltError('Reset requires an explicitly complete application list')
        lists = {row.application: row for row in cache.group_lists}
        for app in wanted['complete_group_lists']:
            if app not in lists or not lists[app].complete:
                raise LifecycleMetadataError('Reset requires a complete named group list', {'application': app, 'field': 'complete_group_list'}, original_stage='controls')
        for row in wanted['control_groups']:
            fact = cache.lifecycle.find(row['application'], row['group'])
            if fact is None or not fact.exists or not any(g.address == row['group'] for g in lists[row['application']].groups):
                raise LifecycleMetadataError('Reset does not infer a missing bound control group', row, original_stage='controls')
        return cache

    def _context(self, base, raw, cache, active_tab, binding_variant, dirty):
        origin = _ContextOrigin(self)
        context = _ResetContext(base, raw, cache, active_tab, binding_variant, dirty, origin)
        origin.reference = weakref.ref(context)
        return context

    def _raw_load(self, state, loaded):
        state.initializing = False  # actual base.AfterLoadPPData entry
        before = self.snapshot(state.raw())
        for name, value in loaded.after_load.items():
            if value != before[name]:
                if not isinstance(value, tuple) or len(value) != 1:
                    raise EdltError('Unverified raw AfterLoad assignment: ' + name)
                state.integer(name, value[0])
        # Blank SetToDefault calls RestoreLevel=0 even if numerically zero.
        for widget in loaded.widgets:
            if widget.original_type != widget.stored_type and widget.slot >= 6:
                state.integer(f'Widget{widget.slot}RestoreLevel', 0)
        if self.snapshot(state.raw()) != dict(loaded.after_load):
            raise EdltError('Raw AfterLoad differs from the retained model projection')

    def _transition(self, base, context):
        _validate_context(self.lifecycle, base, context)
        state = _RawState(context.expected_raw, context.dirty_parameters)
        phases = {'input': state.phase()}
        self._raw_load(state, base); phases['after-load'] = state.phase()
        # Initial selected-control dependencies not proved by this matrix must
        # be rejected, even though the generic lifecycle can load their bytes.
        if any(w.original_type not in _INITIAL_TYPES for w in base.widgets):
            raise EdltError('Reset initial widget-control context is not yet verified for this stored type')
        for widget in base.widgets:
            if widget.stored_type != 2: continue
            control = base.after_load[_field(widget.slot, 1)][0]
            app = base.after_load['SecondaryApplication' if control & 128 else 'PrimaryApplication'][0]
            number = base.after_load[_field(widget.slot, 6)][0]
            fact = context.metadata.lifecycle.find(app, number)
            if fact is None or not fact.exists:
                raise LifecycleMetadataError('Reset control binding requires the existing Lighting group',
                    {'application': app, 'group': number, 'widget': widget.slot}, original_stage='controls')
        if state.number('NavWidgetType') not in (0, 1):
            raise EdltError('Reset initial control setup requires NavWidgetType0 or1')
        if context.binding_variant == 'audited-local-wiring': phases['audited-local-wiring'] = state.phase()
        for stage in ('after-main-bindings', 'after-panel-population', 'after-control-setup'):
            phases[stage] = state.phase()
        if context.active_tab == 'general':
            for number in range(6, 22):
                name = f'Widget{number}RestoreLevel'
                if state.number(name): state.integer(name, state.number(name))
        phases['before-reset'] = state.phase()
        phases['component-show-blank'] = state.phase()
        if state.number('EnableLevelStore') != 0: state.integer('EnableLevelStore', 0)
        phases['component-before-change'] = state.phase()
        state.initializing = True
        for name, default in self.defaults.items():
            if name in _EXCLUDED: continue
            old = _join(state.tokens[name])
            comparison = old if name == 'UnitName' or old.startswith('0x') else '0x' + old
            if default != comparison and not (name.endswith('WidgetType') and comparison == '0x0' and default == '0xff'):
                state.set(name, default); state.dirty.add(name)
        phases['component-reset-defaults'] = state.phase()
        for number in range(1, 22): state.integer(_field(number, 1), 0)
        phases['component-zero-byte1'] = state.phase()
        fresh = self.lifecycle.load(self.snapshot(state.raw()), metadata=context.metadata.lifecycle)
        self._raw_load(state, fresh)
        if context.active_tab in ('widgets', 'general') and state.number('NavWidgetType') > 1:
            state.integer('NavWidgetType', 0)
        phases['component-after-change'] = state.phase()
        state.integer(_field(10), 10); state.integer('Widget10RestoreLevel', 0)
        state.set(_field(10, 1), '0x2')
        phases['after-reset'] = state.phase()
        if any(widget.stored_type != 0 for widget in fresh.widgets):
            raise EdltError('Unsupported Reset defaults did not create all Blank models')
        widgets = (*fresh.widgets[:9], LoadedWidget(10, 255, 10, 'TimeAndDateData'), *fresh.widgets[10:])
        origin = _LoadedOrigin(self.lifecycle._loaded_owner)
        result = ResetEdlt(base, fresh, self.snapshot(context.expected_raw), self.snapshot(state.raw()),
                           widgets, context, phases, origin)
        origin.reference = weakref.ref(result)
        return result, state, phases

    def plan(self, raw_parameters, *, metadata, active_tab, binding_variant, dirty_parameters=()):
        raw = self.raw_input(raw_parameters)
        _choice(active_tab, ACTIVE_TABS, 'Active tab'); _choice(binding_variant, BINDING_VARIANTS, 'Binding variant')
        dirty = _dirty(dirty_parameters, self.spec.parameters)
        cache = self._metadata(raw, active_tab, binding_variant, metadata)
        base = self.lifecycle.load(self.snapshot(_RawState(raw).raw()), metadata=cache.lifecycle)
        context = self._context(base, raw, cache, active_tab, binding_variant, dirty)
        edited = self.lifecycle.reset_unit_controls(base, reset_context=context)
        phases = dict(edited.raw_phases)
        state = _RawState.from_phase(phases['after-reset'])
        saved = self.lifecycle.prepare_save(edited)
        # Original BeforeSave setter spellings, not a numeric diff renderer.
        state.set('Application', ' '.join(f'0x{x:X}' for x in saved.before_save['Application']))
        state.integer('Widget11WidgetType', 255); state.integer('Widget11RestoreLevel', 0)
        state.integer('SceneCount', 8)
        for index in range(1, 9):
            name = f'Scene{index}StartAddress'; state.set(name, ' '.join(hex(x) for x in saved.before_save[name]))
        state.set('SceneBucket', ' '.join(hex(x) for x in saved.before_save['SceneBucket']))
        if self.snapshot(state.raw()) != dict(saved.before_save):
            raise EdltError('Raw Reset BeforeSave differs from the issued model projection')
        phases['before-save'] = state.phase()
        for name, value in self.crcs(saved.before_save).items(): state.set(name, ' '.join(hex(x) for x in value))
        phases['final'] = state.phase()
        final = self.snapshot(state.raw())
        evidence = {'model_edit_scope': 'bounded partial-dialog synchronous Reset and terminal model save',
            'model_cycle_complete': True, 'reset_transition': edited.as_dict(),
            'raw_dirty_state_verified_scope': 'explicit loaded control context, not arbitrary prior Toolkit UI state',
            'reset_excluded_parameters': sorted(_EXCLUDED), 'new_widget_models': 21, 'new_scene_models': 8,
            'source_model_families': [w.model_family for w in base.widgets],
            'terminal_navigation_raw': state.raw()['NavWidgetType'],
            'initial_requirements': self.requirements(raw, active_tab=active_tab, binding_variant=binding_variant).as_dict()}
        expected = self.snapshot(raw)
        return ResetPlan(raw, expected, phases, saved.before_save,
            {k: v for k, v in final.items() if v != expected[k]}, cache, active_tab,
            binding_variant, dirty, self.specification_sha256, _json(evidence))

    def prepare_global_factory(self, raw_parameters, *, metadata, preparation_context,
                               dirty_parameters=()):
        """Bounded issued factory Reset dependency; no form, Global payload or I/O."""
        self.last_evidence = None
        from .edlt_global_preparation import _validate_factory_context
        receipt = _validate_factory_context(preparation_context, self)
        raw = self.raw_input(raw_parameters)
        dirty = _dirty(dirty_parameters, self.spec.parameters)
        cache = ApplicationCache.from_dict(metadata.as_dict() if isinstance(metadata, ApplicationCache) else metadata)
        if (tuple(raw) != receipt.parameter_order or raw != dict(receipt.expected_raw)
                or dirty != receipt.dirty_parameters or _json(cache.as_dict()) != _json(receipt.metadata.as_dict())):
            raise EdltError('Factory Reset inputs differ from their issued raw/cache/order/dirty context')
        values = self.snapshot(raw)
        specification = [(name, parameter.type, {key: parameter.fields[key]
            for key in _FACTORY_SPEC_FIELDS if key in parameter.fields})
            for name, parameter in self.spec.parameters.items()]
        if hashlib.sha256(_json(specification).encode()).hexdigest() != _FACTORY_SPEC_SHA256:
            raise EdltError('Factory Reset requires the captured ordered original layouts and defaults')
        fingerprint = hashlib.sha256(json.dumps(
            {name: value for name, value in values.items() if name not in _FACTORY_IDENTITY},
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if fingerprint not in _FACTORY_PATTERNS:
            raise EdltError('Factory Reset requires one of the six complete captured source patterns')
        if values['UnitAddress'][0] != receipt.context.as_dict()['source_unit']:
            raise EdltError('Factory source unit differs from the raw UnitAddress')
        if values['NavWidgetType'] != (255,):
            raise EdltError('Factory Reset requires the evidenced initial Global-tab Nav255 state')
        layout = self.codec.layout('Project')
        if (layout.parameter.type, layout.address, layout.array_size) != ('sixbit', 0x23, 8):
            raise EdltError('Factory Reset requires the original legacy Project layout')
        # These are cache fact requirements only; the selected tab does not
        # affect them. No Standby control action or normalizing getter runs.
        self._metadata(raw, 'standby', 'audited-local-wiring', cache)
        projected = {**_RawState(raw).raw(), 'Project': raw['Project']}
        with self._factory_failure('initial_after_load', {}):
            base = self.lifecycle.load(self.snapshot(projected), metadata=cache.lifecycle)
        origin = _ContextOrigin(self)
        context = _FactoryResetContext(base, receipt, origin)
        origin.reference = weakref.ref(context)
        return self.lifecycle.reset_global_factory_controls(base, factory_context=context)

    def _factory_snapshot(self, raw, receipt):
        # Project has no place in eDLT OEM CRC regions. Its actual legacy model
        # text can exceed eight characters; never relax or feed it to the codec.
        return self.snapshot({**raw, 'Project': receipt.expected_raw['Project']})

    def _factory_raw_load(self, state, loaded, receipt):
        state.initializing = False
        before = self._factory_snapshot(state.raw(), receipt)
        for name, value in loaded.after_load.items():
            if value != before[name]:
                if name == 'Project' or not isinstance(value, tuple) or len(value) != 1:
                    raise EdltError('Unverified factory raw AfterLoad assignment: ' + name)
                state.integer(name, value[0])
        for widget in loaded.widgets:
            if widget.original_type != widget.stored_type and widget.slot >= 6:
                state.integer(f'Widget{widget.slot}RestoreLevel', 0)
        if self._factory_snapshot(state.raw(), receipt) != dict(loaded.after_load):
            raise EdltError('Raw factory load differs from its retained model projection')

    @contextmanager
    def _factory_failure(self, stage, phases):
        try:
            yield
        except BaseException as error:
            evidence = {'format': 'cbus-edlt-factory-reset-failure-v1', 'failure_stage': stage,
                'saved': False, 'pp_io_performed': False, 'physical_device_verified': False,
                'automatic_retries': 0, 'error_type': type(error).__name__, 'error': _error_text(error)}
            try:
                evidence['completed_phases'] = {name: phase.as_dict() for name, phase in phases.items()}
            except BaseException as secondary:
                evidence['evidence_export_complete'] = False
                evidence['evidence_error'] = _error_text(secondary)
            self.last_evidence = evidence
            try: error.edlt_reset_evidence = evidence
            except BaseException: pass
            raise

    def _factory_transition(self, base, context):
        phases = {}
        with self._factory_failure('reset_and_global_tab_removal', phases):
            return self._factory_transition_steps(base, context, phases)

    def _factory_transition_steps(self, base, context, phases):
        from .edlt_global_preparation import ProjectState, initialize_project
        receipt = _validate_factory_reset_context(self.lifecycle, base, context)
        state = _RawState(receipt.expected_raw, receipt.dirty_parameters)
        phases['input'] = state.phase()
        self._factory_raw_load(state, base, receipt)
        for stage in ('after-load', 'audited-local-wiring', 'after-main-bindings',
                      'after-panel-population', 'after-control-setup'):
            phases[stage] = state.phase()
        assignment = initialize_project(ProjectState(tuple(state.tokens['Project']), '',
            'Project' in state.dirty, state.initializing), receipt.context.form_project)
        state.tokens['Project'] = list(assignment.after.tokens)
        if assignment.after.dirty: state.dirty.add('Project')
        phases['conditional-project-initialization'] = state.phase()
        phases['before-reset'] = state.phase()
        phases['component-show-blank'] = state.phase()
        if state.number('EnableLevelStore') != 0: state.integer('EnableLevelStore', 0)
        phases['component-before-change'] = state.phase()
        state.initializing = True
        for name, default in self.defaults.items():
            if name in _EXCLUDED: continue
            old = _join(state.tokens[name])
            comparison = old if name == 'UnitName' or old.startswith('0x') else '0x' + old
            if default != comparison and not (name.endswith('WidgetType') and comparison == '0x0' and default == '0xff'):
                state.set(name, default); state.dirty.add(name)
        phases['component-reset-defaults'] = state.phase()
        for number in range(1, 22): state.integer(_field(number, 1), 0)
        phases['component-zero-byte1'] = state.phase()
        fresh = self.lifecycle.load(self._factory_snapshot(state.raw(), receipt), metadata=receipt.metadata.lifecycle)
        self._factory_raw_load(state, fresh, receipt)
        phases['component-after-change'] = state.phase()
        state.integer(_field(10), 10); state.integer('Widget10RestoreLevel', 0)
        state.set(_field(10, 1), '0x2')
        phases['after-reset'] = state.phase()
        # Original TabPages.Remove(tpGlobal) exposes Widgets and invokes the
        # bound MultiPage getter. It occurs strictly after silent Reset returns.
        if state.number('NavWidgetType') > 1: state.integer('NavWidgetType', 0)
        phases['after-global-tab-removal'] = state.phase()
        if any(widget.stored_type != 0 for widget in fresh.widgets):
            raise EdltError('Unsupported factory defaults did not create all Blank models')
        widgets = (*fresh.widgets[:9], LoadedWidget(10, 255, 10, 'TimeAndDateData'), *fresh.widgets[10:])
        origin = _LoadedOrigin(self.lifecycle._loaded_owner)
        result = FactoryResetEdlt(base, fresh, self.snapshot(receipt.expected_raw),
            self._factory_snapshot(state.raw(), receipt), widgets, context, phases, assignment, origin)
        origin.reference = weakref.ref(result)
        origin.factory_base, origin.factory_fresh = base, fresh
        origin.factory_context, origin.factory_widgets = context, widgets
        origin.factory_retained = _factory_retained_objects(result)
        origin.factory_content = _factory_state_content(result)
        return result

    def prepare_global_factory_save(self, state):
        """Terminal raw/model projection; leaves Project/category preworker separate."""
        self.last_evidence = None
        receipt = _validate_factory_reset(self.lifecycle, state)
        if state.context._origin.owner is not self:
            raise EdltError('Factory Reset save requires the exact issuing Reset editor')
        phases = dict(state.raw_phases)
        with self._factory_failure('terminal_before_save', phases):
            return self._factory_save_steps(state, receipt, phases)

    def _factory_save_steps(self, state, receipt, phases):
        raw = _RawState.from_phase(state.raw_phases['after-global-tab-removal'])
        saved = self.lifecycle.prepare_save(state)
        raw.set('Application', ' '.join(f'0x{x:X}' for x in saved.before_save['Application']))
        raw.integer('Widget11WidgetType', 255); raw.integer('Widget11RestoreLevel', 0)
        raw.integer('SceneCount', 8)
        for index in range(1, 9):
            name = f'Scene{index}StartAddress'; raw.set(name, ' '.join(hex(x) for x in saved.before_save[name]))
        raw.set('SceneBucket', ' '.join(hex(x) for x in saved.before_save['SceneBucket']))
        if self._factory_snapshot(raw.raw(), receipt) != dict(saved.before_save):
            raise EdltError('Raw factory save differs from its retained model projection')
        phases['before-save'] = raw.phase()
        for name, value in self.crcs(saved.before_save).items(): raw.set(name, ' '.join(hex(x) for x in value))
        phases['final'] = raw.phase()
        return FactoryResetSave(state, saved, phases)

    def _interrupted(self, error, plan, attempted, cause=None):
        try: evidence = {**plan.as_dict(), 'verified': False, 'saved': False,
                         'attempted_parameters': list(attempted), 'pp_state_uncertain': bool(attempted), 'automatic_retries': 0}
        except BaseException as secondary:
            evidence = {'verified': False, 'saved': False, 'attempted_parameters': list(attempted),
                        'evidence_export_complete': False, 'evidence_error': _error_text(secondary)}
        if cause is not None: evidence['original_error'] = {'type': type(cause).__name__, 'error': _error_text(cause)}
        self.last_evidence = evidence
        try: error.edlt_reset_evidence = evidence
        except BaseException: pass

    def apply(self, session, plan):
        self.last_evidence = None
        if type(plan) is not ResetPlan or type(plan.metadata) is not ApplicationCache:
            raise EdltError('Use a Reset plan returned by this editor')
        for values in (plan.expected, plan.before_save, {**plan.expected, **plan.changes}):
            self.snapshot(values)
        for phase in plan.phases.values():
            if type(phase) is not ResetPhase or type(phase.initializing) is not bool:
                raise EdltError('Invalid Reset phase state')
            _dirty(phase.dirty_parameters, self.spec.parameters)
            if (set(phase.tokens) != set(self.spec.parameters) or any(
                    type(token) is not str for tokens in phase.tokens.values() for token in tokens)):
                raise EdltError('Invalid Reset phase tokens')
            self.raw_input(phase.raw)
        canonical = self.plan(plan.expected_raw, metadata=plan.metadata, active_tab=plan.active_tab,
            binding_variant=plan.binding_variant, dirty_parameters=plan.dirty_parameters)
        if _json(canonical.as_dict()) != _json(plan.as_dict()) or canonical != plan:
            raise EdltError('Reset plan differs from its validated raw model sequence')
        self.common._verify_session(session)
        current = session.values()
        if self.raw_input(current) != dict(plan.expected_raw):
            raise EdltError('Raw PP values changed since the Reset plan was made')
        expected = {**plan.expected, **plan.changes}; attempted = []
        try:
            for name in plan.changes:
                attempted.append(name); session.set(name, plan.phases['final'].raw[name])
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the Reset plan')
        except (KeyboardInterrupt, SystemExit) as error:
            self._interrupted(error, plan, attempted); raise
        except Exception as error:
            rollback_errors = []
            try:
                for name in reversed(attempted):
                    if not getattr(session.programmer.client, 'connected', True):
                        rollback_errors.append('Connection lost; no further recovery I/O; PP state is uncertain'); break
                    try: session.set(name, plan.expected_raw[name])
                    except Exception as rollback: rollback_errors.append(_error_text(rollback))
                if getattr(session.programmer.client, 'connected', True):
                    try:
                        if self.snapshot(session.values()) != dict(plan.expected): rollback_errors.append('Original PP values could not be verified')
                    except Exception as rollback: rollback_errors.append(_error_text(rollback))
            except (KeyboardInterrupt, SystemExit) as interrupted:
                self._interrupted(interrupted, plan, attempted, error)
                self.last_evidence['rollback_errors'] = rollback_errors; raise
            wrapped = EdltApplyError(error, rollback_errors, attempted)
            self._interrupted(wrapped, plan, attempted, error)
            if hasattr(error, 'cgate_cleanup_errors'): wrapped.cgate_cleanup_errors = error.cgate_cleanup_errors
            raise wrapped from error
        self.last_evidence = {**plan.as_dict(), 'verified': True}
        return self.last_evidence

    def configure(self, session, *, metadata, active_tab, binding_variant, dirty_parameters=()):
        self.last_evidence = None
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), metadata=metadata, active_tab=active_tab,
            binding_variant=binding_variant, dirty_parameters=dirty_parameters))
