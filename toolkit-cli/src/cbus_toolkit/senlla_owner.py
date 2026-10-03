"""Owning SENLLA lifecycle and source-position parameter serialization.

The owner retains one live inherited/prekey graph. Source phases are added at
their native positions; an unclosed phase interrupts the owner instead of
substituting a final component projection or an acknowledged no-op callback.
"""
from copy import deepcopy
from dataclasses import dataclass

from .senlla_inputs import SCHEMA, SENLLAInputSnapshot, _value
from .sensors import SensorError


# Native synchronous SAVE-agent constructor facts. These are cache values,
# distinct from device/vendor defaults and from the earlier loaded PP cache.
# Numeric string fields normalize blank text to an empty numeric sequence.
_SAVE_STRING_FIELDS = frozenset((
    'Application','AreaGroupAddress','BankSwitchGroupUsed','BlockAllocation',
    'BlockBankSwitchActive','BlockGroupLogic','ControlAppGroupAddress','GroupAddress',
    'IndicatorBlockAssignment','JPCommand','LPCommand','LRCommand','LightLevel',
    'LightLevelStore1','LightLevelStore2','PatchEnable','Project','RampRate','SRCommand',
    'SceneKeySelector','SceneTable','SceneTablePointer','SerialNo','TimerExpiryCommand',
    'TimerHighByte','TimerLowByte','UnitName'))
_ABSENT_SAVE_FIELDS = frozenset((
    'CUSTYPE','EEPROM Checksum','EEPROMCheckSumActive','EEPROMChecksumAlarm',
    'RetardationIndex','SceneCycleSelector','SceneToggleSelector'))


@dataclass(frozen=True)
class ParameterCapture:
    ordinal: int
    name: str
    source: str
    value: str | tuple[int, ...]

    def as_dict(self):
        return dict(ordinal=self.ordinal, name=self.name, source=self.source,
                    value=self.value if isinstance(self.value, str) else list(self.value))


class SENLLAParameterJournal:
    """Current agent PP values, written at individual native save positions.

    Captures are ordered and can overwrite an earlier native write. A later
    key callback sees earlier CoreKey/Scene values, while a later surface save
    can overwrite the earlier ST7 bank bytes. It cannot import a final partial
    dictionary as proof that the intervening setters and callbacks ran.
    """
    def __init__(self, snapshot):
        if not isinstance(snapshot, SENLLAInputSnapshot):
            raise SensorError('Parameter journal requires the complete guarded SENLLA snapshot')
        self.snapshot = SENLLAInputSnapshot(snapshot.identity, snapshot.expected)
        self._values = self.snapshot.parameters()
        self._captures = []
        # Native setters can update a cached PP attribute before its
        # programmable filter is disabled. Physical programming is a later
        # operation, so unknown filter states cannot authorize a send.
        self._programmable = {name: None for name in SCHEMA}
        self._filters = []
        self._agent = 'load'
        self._load_cache = None
        self._save_prepared = False
        self._agent_events = []

    def begin_save_agent(self, *, mode='synchronous_default'):
        """Allocate the normal source's FRESH save cache, once.

        Normal LoadPP and database/network save verbs omit LiveAgentMode; the
        earlier load agent is freed. Retained agents or pending asynchronous
        commands require another proven cache lifetime and are refused here.
        Seven raw protected rows have no actual constructor attribute.
        """
        if mode != 'synchronous_default':
            raise SensorError('Native save cache requires the proven synchronous default-agent route')
        if self._agent != 'load':
            raise SensorError('Native fresh save agent is allocated once')
        self._load_cache = deepcopy(self._values)
        self._values = {name: ('' if SCHEMA[name][0] == 'sixbit' else []
                              if name in _SAVE_STRING_FIELDS else [0])
                        for name in SCHEMA if name not in _ABSENT_SAVE_FIELDS}
        self._programmable = {name: name not in _ABSENT_SAVE_FIELDS and name != 'SerialNo'
                              for name in SCHEMA}
        self._agent = 'save'
        self._agent_events.append(dict(operation='fresh_save_agent_constructor',
            parameter_count=len(self._values), lifetime='synchronous_default',
            source='0x7f409c'))

    def prepare_save_agent(self):
        """Mark every actual agent attribute edited before native BeforeSave."""
        if self._agent != 'save' or self._save_prepared:
            raise SensorError('Edited-state preparation requires one fresh save agent')
        self._save_prepared = True
        self._agent_events.append(dict(operation='all_actual_attributes_edited',
                                       value=True,source='0xcbdd59'))

    def _require_attribute(self, name):
        if name not in SCHEMA:
            raise SensorError('Unknown SENLLA parameter ' + str(name))
        if name not in self._values:
            raise SensorError('Native fresh save agent has no attribute for ' + name)

    def read(self, name):
        self._require_attribute(name)
        return deepcopy(self._values[name])

    def capture(self, name, value, *, source):
        self._require_attribute(name)
        if not isinstance(source, str) or not source:
            raise SensorError('Each parameter capture requires its native source position')
        if name == 'LightLevel':
            # CoreKey can grow this array from its CURRENT loaded index/count.
            # Public encoding must independently establish representability.
            if (not isinstance(value, (list, tuple)) or not 10 <= len(value) <= 263
                    or any(type(x) is not int or not 0 <= x <= 255 for x in value)):
                raise SensorError('Native current LightLevel requires 10..263 unsigned bytes')
            normalized = tuple(value)
        else:
            normalized = _value(name, value)
        stored = normalized if isinstance(normalized, str) else list(normalized)
        self._values[name] = stored
        capture = ParameterCapture(len(self._captures), name, source, normalized)
        self._captures.append(capture)
        return capture

    def set_programmable(self, name, value, *, source):
        if name not in SCHEMA or type(value) is not bool:
            raise SensorError('Programmable filter requires a known parameter and Boolean value')
        if not isinstance(source, str) or not source:
            raise SensorError('Programmable filter requires its native source position')
        if name not in self._values:
            raise SensorError('Native programmable setter requires an actual agent attribute')
        self._programmable[name] = value
        self._filters.append(dict(name=name, value=value, source=source))

    def clear(self, name, *, source):
        """Record a proven native cache clear, without authorizing a send."""
        self._require_attribute(name)
        if isinstance(self._values[name], str):
            raise SensorError('Numeric cache clear requires a known numeric parameter')
        if type(source) is not str or not source:
            raise SensorError('Cache clear requires its native source position')
        self._values[name] = []
        event = ParameterCapture(len(self._captures), name, source, ())
        self._captures.append(event)
        return event

    def _partial(self, name, values, source):
        if type(source) is not str or not source:
            raise SensorError('Indexed cache write requires its native source position')
        self._require_attribute(name)
        if isinstance(self._values[name], str):
            raise SensorError('Indexed cache write requires a numeric parameter')
        layout = SCHEMA[name]
        # These are internal intermediate cached values. Eligibility and the
        # final fixed-width schema are checked again before programming.
        maximum = (1 << layout[3]) - 1
        if (len(values) > layout[2] or any(type(value) is not int or not 0 <= value <= maximum
                                         for value in values)):
            raise SensorError('Partial cached parameter is outside its recovered unsigned width')
        self._values[name] = list(values)
        event = ParameterCapture(len(self._captures), name, source, tuple(values))
        self._captures.append(event)
        return event

    def append(self, name, value, *, source):
        if name not in ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand'):
            raise SensorError('Native key AttribAppend requires a command parameter')
        current = self.read(name)
        if not isinstance(current, list):
            raise SensorError('Native numeric append requires its current numeric cache')
        return self._partial(name, [*current, value], source)

    def capture_index(self, name, index, value, *, source):
        if name not in ('SceneKeySelector', 'IndicatorBlockAssignment') or type(index) is not int or not 0 <= index < 8:
            raise SensorError('Native key indexed write requires its recovered eight-key array')
        current = self.read(name)
        # Source execution visits these indices ascending. Refuse an
        # unspecified extension-fill policy rather than inventing holes.
        if index > len(current):
            raise SensorError('Native indexed cache extension requires contiguous source writes')
        if index == len(current):
            current.append(value)
        else:
            current[index] = value
        return self._partial(name, current, source)

    def dispatch(self, request, runtime):
        """Execute one kernel-native cached write, preserving request order."""
        from .senlla_key_events import ParameterWriteRequest
        if type(request) is not ParameterWriteRequest:
            raise SensorError('PP journal requires a native parameter write request')
        if request.operation == 'assign':
            self.capture(request.name, request.value, source=request.source)
        elif request.operation == 'append':
            self.append(request.name, request.value, source=request.source)
        elif request.operation == 'index':
            self.capture_index(request.name, request.index, request.value, source=request.source)
        else:
            raise SensorError('Unsupported native PP write operation')

    def programming_values(self):
        """Actual eligible sends, only after every filter has been established.

        Cached nonprogrammable rows remain inspectable. They are omitted from
        programming rather than silently restored inside the cached PP model.
        """
        if any(value is None for value in self._programmable.values()):
            raise SensorError('Physical programming requires all native programmable filters')
        if self._agent == 'save' and not self._save_prepared:
            raise SensorError('Physical programming requires native edited-state preparation')
        eligible = {name:deepcopy(value) for name,value in self._values.items()
                    if self._programmable[name]}
        for name, value in eligible.items():
            if name == 'LightLevel' and len(value) != 10:
                raise SensorError('Programming requires a representable ten-byte LightLevel schema')
            _value(name, value)
        return eligible

    def physical_parameters(self):
        """Expected readback combines actual eligible sends with physical baseline."""
        return self.snapshot.parameters() | self.programming_values()

    def parameters(self):
        return deepcopy(self._values)

    def captures(self):
        return tuple(self._captures)

    def as_dict(self):
        return dict(parameters=self.parameters(),
                    captures=[capture.as_dict() for capture in self._captures],
                    physical_baseline=self.snapshot.parameters(),
                    programmable=deepcopy(self._programmable),
                    programmable_events=deepcopy(self._filters),
                    agent=self._agent, load_cache=deepcopy(self._load_cache),
                    save_prepared=self._save_prepared,
                    agent_events=deepcopy(self._agent_events))


class OwnerPhaseRequired(SensorError):
    """An exact remaining owner phase has no completed semantic executor."""
    def __init__(self, phase, source):
        self.phase, self.source = phase, source
        super().__init__('Complete SENLLA owner requires phase ' + phase + ' at ' + source)


class SENLLAOwner:
    """One live complete-profile owner; no snapshot adoption at phase changes.

    ``inherited_owner`` is the concrete inherited/project bridge adapter. Its
    ``prekey`` owns the already-reviewed live prefix and its runtime is retained
    through every later phase. ``control_provider`` is the concrete persistent
    native primitive provider. Neither parameter is a final-state JSON cache.

    This module is under composition: a phase without a source-closed body
    refuses explicitly. No complete save or public admission is exposed until
    all load, fresh-control and ordered save phases are implemented.
    """
    def __init__(self, snapshot, *, inherited_owner, control_provider):
        from .senlla_inherited_owner import SENLLAInheritedOwner
        from .senlla_control_primitives import PersistentControlPrimitives
        from .senlla_late_unit import SENLLALateUnit
        if not isinstance(snapshot, SENLLAInputSnapshot):
            raise SensorError('SENLLA owner requires the complete guarded 93-field snapshot')
        if not isinstance(inherited_owner, SENLLAInheritedOwner):
            raise SensorError('Complete owner requires the concrete shared inherited/backend owner')
        self.raw = SENLLAInputSnapshot(snapshot.identity, snapshot.expected)
        prekey = getattr(inherited_owner, 'prekey', None)
        if (prekey is None or prekey.raw.identity != self.raw.identity
                or prekey.raw.expected != self.raw.expected):
            raise SensorError('Inherited owner must retain this exact source snapshot and prekey graph')
        if not isinstance(control_provider, PersistentControlPrimitives):
            raise SensorError('Complete SENLLA owner requires its concrete control provider')
        self.inherited_owner = inherited_owner
        self.control_provider = control_provider
        self.prekey = prekey
        self.runtime = prekey.runtime
        self.journal = SENLLAParameterJournal(self.raw)
        # Bind the actual LOAD-agent cache before any source getter. These
        # hooks are execution, not a final projection of the raw snapshot.
        inherited_owner.parameter_read = self._parameter_read
        self.prekey.parameter_read = self._parameter_read
        self.runtime.level_dispatch = self._level_lookup
        self.late = SENLLALateUnit(inherited_owner, self.journal)
        self.phase = 'fresh_constructor'
        self.runtime.application_dispatch = self._application_changed
        self.failed = False
        self.events = []
        self._objects = self._object_signature()

    def _parameter_read(self, name, source, runtime):
        if runtime is not self.runtime:
            raise SensorError('PP getter belongs to another owning runtime')
        self.runtime._event('owner_parameter_read', name=name, source=source)
        return self.journal.read(name)

    def _application_changed(self, runtime, secondary):
        # The retained prefix closes constructor/empty-Scene application
        # dispatch. Later application edits additionally need loaded Scene
        # and hidden-reference observers; do not reuse the fresh no-op tail.
        if self.phase != 'fresh_constructor':
            raise OwnerPhaseRequired('loaded_application_and_hidden_reference_dispatch',
                                     '0xc9e984' if not secondary else '0xc9eb0c')
        self.prekey._application_changed(runtime, secondary)

    def _level_lookup(self, request, runtime):
        if runtime is not self.runtime:
            raise SensorError('Level getter belongs to another owning runtime')
        group = self.runtime.groups.get(request.group)
        if group is None:
            raise SensorError('Native action-level getter requires its CURRENT canonical group')
        self.inherited_owner.bridge.get_level(runtime, group, request.address,
            create=request.create, source=request.source)

    def _read_byte(self, name, source, index=0):
        value = self._parameter_read(name, source, self.runtime)
        normalized = _value(name, value)
        if isinstance(normalized, str) or not 0 <= index < len(normalized):
            raise SensorError('Native CURRENT PP ordinal is unavailable: ' + name)
        return normalized[index]

    def _object_signature(self):
        engine = self.runtime
        return (engine.unit, engine.unit_manager, engine.primary_application,
                engine.secondary_application, engine.area,
                *(item for block in engine.blocks for item in
                  (block.object, block.manager, block.application, block.group)),
                *(item for key in engine.keys for item in
                  (key.object, key.manager, key.application, key.template)))

    def _same_objects(self):
        current = self._object_signature()
        if (len(current) != len(self._objects)
                or any(a is not b for a,b in zip(current,self._objects))):
            raise SensorError('Owning lifecycle cannot replace its original objects or managers')

    def _event(self, phase, source):
        self.events.append(dict(phase=phase, source=source,
                                unit_depth=self.runtime.unit.depth))

    def _run(self, action):
        if self.failed or self.runtime.failed:
            raise SensorError('Interrupted complete owner cannot resume or serialize')
        try:
            self._same_objects()
            result = action()
            self._same_objects()
            return result
        except Exception:
            self.failed = True
            self.runtime.failed = True
            raise

    def load(self):
        """Continue the actual source load once; never prefetch later facts."""
        def execute():
            if self.phase != 'fresh_constructor':
                raise SensorError('Complete owner source load starts once at fresh constructor')
            engine = self.prekey.load_to_key_blocks()
            if engine is not self.runtime:
                raise SensorError('Prekey loader returned a replacement runtime')
            self._event('prekey_handoff', '0xcc862e')
            engine.load_allocations(self.raw.expected['BlockAllocation'],
                                    parameter_read=self._parameter_read)
            engine.finish_corekey_application_refresh()
            self.phase = 'core_neo_load'
            self._event(self.phase, '0xccb1a9')
            return self._load_core_neo()
        return self._run(execute)

    def _load_core_neo(self):
        engine = self.runtime
        # SENLLA IsNeoMultisensor skips the brightness/Neo infrared prefix.
        # Patch reads short-circuit exactly; disabled Patch still loads Scenes.
        first = self._read_byte('PatchEnable', '0xccb3ae')
        enabled = first != 157 or self._read_byte('PatchEnable', '0xccb3cd', 1) != 64
        engine.scenes_enabled.set(enabled)
        self.late.set('Nightlight', False, source='0xcebdd2')
        engine._event('guarded_nightlight_absent_name_default', source='0xcebcf8',
                      qualification='guarded93 excludes extra LOAD-cache Nightlight input')
        trigger = engine.get_source_application(202, create=True, source='0xcca366')
        address = self._read_byte('ControlAppGroupAddress', '0xcca397')
        control = engine.get_source_group(trigger, address, create=True, source='0xcca3a1')
        engine.set_control_app_group(control)
        raw = self.raw.expected
        engine.load_scenes_causal(raw['SceneTable'], raw['SceneTablePointer'], raw['PatchEnable'],
                                  parameter_read=self._parameter_read)
        stages = tuple(tuple(raw[name][key] for name in
                             ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand'))
                       for key in range(8))
        engine.load_key_values(stages, raw['SceneKeySelector'], raw['IndicatorBlockAssignment'],
                               parameter_read=self._parameter_read)
        # KeysChanged invokes virtual Changed only; it does not prepend a
        # ResolveChange. No extra classic-indicator or Blink setter applies.
        for key in engine.keys:
            key.object.changed()
        self._event('core_neo_keys_changed', '0xccaef4')
        self._load_neopro()
        self.phase = 'st7_load'
        self._event(self.phase, '0xcf4890')
        self.late.load_st7()
        self.phase = 'surface_load'
        self._event(self.phase, '0x1217764')
        self.late.load_surface()
        self.phase = 'fresh_identification'
        self._event(self.phase, 'MainForm.SetData')
        return self

    def _load_neopro(self):
        engine, late = self.runtime, self.late
        self.phase = 'neopro_load'
        self._event(self.phase, '0xced154')
        self.inherited_owner.load_neopro_infrared()
        enable = engine.get_source_application(203, create=True, source='0xced2a1')
        # SENLLA's KeyDisable property is false, so native lookup is false and
        # an actually absent unused group stays nil.
        group = engine.get_source_group(enable, 255, create=False, source='0xced2b3')
        late.set('KeyDisableGroup', group, source='0xced2c2')
        late.set('KeyDisableGroupInvert', bool(self._read_byte('KeyDisableInverted', '0xced2d2')),
                 source='0xced2e2')
        late.set('CorridorLinkActive', bool(self._read_byte('CorridorLinkActive', '0xced093')),
                 source='0xced0a3')
        # This helper captures the PP address BEFORE the current primary
        # getter. Area loading has the opposite manager/read order.
        address = self._read_byte('CorridorLinkEnablerGroup', '0xced0b3')
        primary = engine.application_object()
        if primary is None:
            raise SensorError('Native Corridor getter dereferences CURRENT nil primary')
        group = engine.get_source_group(primary, address, create=True, source='0xced0d3')
        late.set('CorridorLinkGroup', group, source='0xced0e2')
        for name, parameter, read, source in (
            ('CorridorLinkCorridorBlock', 'CorridorLinkBlock', '0xced0f2', '0xced117'),
            ('CorridorLinkOfficeBlock', 'CorridorLinkOfficeBlock', '0xced127', '0xced14c')):
            index = self._read_byte(parameter, read)
            late.set(name, engine.blocks[index].object, source=source)
        single = self._read_byte('SingleJoinEnablerControlGroup', '0xced2fa')
        control = single != 255 or self._read_byte('DualJoinEnablerControlGroup', '0xced312') != 255
        if control:
            application = engine.get_source_application(203, create=True, source='0xced330')
            fields = (('JoinGroup', 'SingleJoinEnablerControlGroup', '0xced34f', '0xced36c', '0xced37b'),
                      ('DualJoinGroup', 'DualJoinEnablerControlGroup', '0xced38b', '0xced3a8', '0xced3b7'))
            application_source = '0xced33f'
        else:
            single = self._read_byte('SingleJoinEnablerGroup', '0xced3cc')
            lighting = single != 255 or self._read_byte('DualJoinEnablerGroup', '0xced3e4') != 255
            if lighting:
                application = engine.application_object()
                fields = (('JoinGroup', 'SingleJoinEnablerGroup', '0xced41f', '0xced43c', '0xced44b'),
                          ('DualJoinGroup', 'DualJoinEnablerGroup', '0xced45b', '0xced478', '0xced487'))
                application_source = '0xced40f'
            else:
                application = engine.get_source_application(255, create=True, source='0xced49b')
                fields = (('JoinGroup', None, None, '0xced4c9', '0xced4d8'),
                          ('DualJoinGroup', None, None, '0xced4f7', '0xced506'))
                application_source = '0xced4aa'
        late.set('JoinApplication', application, source=application_source)
        for name, parameter, read, getter, source in fields:
            address = 255 if parameter is None else self._read_byte(parameter, read)
            current = late.attribute('JoinApplication').value
            if current is None:
                raise SensorError('Native Join getter dereferences CURRENT nil application')
            group = engine.get_source_group(current, address, create=True, source=getter)
            late.set(name, group, source=source)

    def initialize(self):
        # The real late binding/Show/Apply provider is being composed. The
        # owner must not call isolated fresh projections as a substitute.
        if self.failed or self.phase != 'fresh_identification':
            raise SensorError('Fresh form initialization requires the retained loaded owner')
        raise OwnerPhaseRequired('main_identification_then_director_and_late_bindings', 'MainForm.SetData')

    def parameters(self):
        if self.failed or self.runtime.failed or self.phase != 'save_complete':
            raise SensorError('Complete parameters require every owning load/control/save phase')
        return self.journal.parameters()

    def snapshot(self):
        return dict(identity=list(self.raw.identity), expected=self.raw.parameters(),
                    phase=self.phase, failed=self.failed, events=deepcopy(self.events),
                    runtime=self.runtime.snapshot(), parameter_journal=self.journal.as_dict(),
                    complete_toolkit_save=self.phase == 'save_complete' and not self.failed,
                    saved=False, original_execution=False, physical_acceptance=False)


__all__ = ['ParameterCapture', 'SENLLAParameterJournal', 'OwnerPhaseRequired', 'SENLLAOwner']
