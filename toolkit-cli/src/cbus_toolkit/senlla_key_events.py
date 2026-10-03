"""Internal SENLLA key/application/Scene callbacks at their owning positions.

The projected entry is CoreKey GetKeyBlocks. A separate fresh factory retains
the same nil-reference objects through an internal prekey executor and validates
their handoff. This synchronous runtime is not input-file authority or a
complete unit-save implementation. Snapshots do not replace source callbacks.
"""
from dataclasses import dataclass, replace
from copy import deepcopy

from .native_sensor_scenes import loaded_scenes, scene_save_parameters
from .senlla_bank_graph import SENLLABankGraph
from .senlla_key_references import SENLLAKeyReferences
from .senlla_lifecycle import (AttributeManager, BooleanAttribute, FlashAttribute, FlashObject,
                               IntegerAttribute, ObjectReferenceAttribute,
                               TrackedReferenceHandle, ManagedUpdateObject, UpdateObject)
from .senlla_ordinary_keys import _MATCHES
from .sensors import SensorError


_SUBSET = frozenset((*range(14), 16, *range(17, 25), 26, 34))
_RECALL = (frozenset((17,)), frozenset((18, 19)), frozenset((20, 21, 22)))
# First default group for each admitted template, in the retained registration.
_DEFAULTS = {
    16: (0, 0, 0, 0), 0: (13, 0, 0, 0), 1: (15, 0, 0, 0),
    2: (11, 0, 0, 0), 3: (0, 11, 2, 14), 4: (0, 3, 5, 14),
    5: (0, 3, 4, 14), 6: (11, 7, 0, 7), 7: (13, 15, 0, 15),
    8: (0, 13, 5, 14), 9: (0, 15, 4, 14), 10: (0, 10, 5, 14),
    11: (0, 9, 4, 14), 12: (0, 12, 9, 0), 13: (0, 6, 9, 0),
    17: (12, 0, 0, 0), 18: (12, 0, 0, 0), 19: (6, 0, 0, 0),
    20: (12, 0, 0, 0), 21: (9, 0, 0, 0), 22: (6, 0, 0, 0),
    23: (0, 0, 0, 0), 24: (0, 0, 0, 0), 25: (0, 0, 0, 0),
    26: (0, 0, 0, 0), 34: (13, 15, 7, 15),
}
_BLOCK_FIELDS = ('secondary', 'group', 'light_level', 'store1', 'store2',
                 'timer', 'timer_cached', 'expiry', 'expiry_override')


def _integer(value, maximum, label):
    if type(value) is not int or not 0 <= value <= maximum:
        raise SensorError(f'{label} requires an integer in 0..{maximum}')
    return value


def _eight(values, maximum, label):
    if not isinstance(values, (list, tuple)) or len(values) != 8:
        raise SensorError(f'{label} requires eight values')
    return tuple(_integer(value, maximum, label) for value in values)


def _group(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise SensorError('Group identity requires (application, address)')
    return (_integer(value[0], 255, 'Group application'),
            _integer(value[1], 255, 'Group address'))


@dataclass(frozen=True)
class KeyEventContext:
    """Already-established source objects, supplied by an internal unit owner.

    Group identities represent actual app-owned objects, including unused255.
    This component neither reads a project nor admits a JSON-declared cache.
    Protected groups are the currently bound PEC/Join/Corridor objects, rather
    than a later enlarged inventory. Installed decision handlers remain an
    explicit dispatcher boundary; fresh load has none.
    """
    primary_application: int
    secondary_application: int | None
    application_addresses: tuple
    group_identities: tuple
    protected_groups: tuple = ()
    join_active: bool = False
    trigger_levels: tuple = ()

    def __post_init__(self):
        primary = _integer(self.primary_application, 255, 'Primary application')
        secondary = self.secondary_application
        if not 48 <= primary <= 95:
            raise SensorError('The retained SENLLA key profile requires primary Lighting')
        if secondary is not None and (type(secondary) is not int or not (48 <= secondary <= 95 or secondary == 255)):
            raise SensorError('Secondary application requires Lighting, the actual application255 object, or nil')
        if not isinstance(self.application_addresses, (list, tuple)):
            raise SensorError('Application inventory requires an ordered sequence')
        apps = tuple(_integer(value, 255, 'Application address') for value in self.application_addresses)
        if len(set(apps)) != len(apps) or primary not in apps or secondary is not None and secondary not in apps:
            raise SensorError('Application identities must be distinct and include both current references')
        if not isinstance(self.group_identities, (list, tuple)) or not isinstance(self.protected_groups, (list, tuple)):
            raise SensorError('Group inventories require ordered sequences')
        groups = tuple(_group(value) for value in self.group_identities)
        if len(set(groups)) != len(groups) or any(app not in apps for app, _ in groups):
            raise SensorError('Group inventory must contain distinct objects in established applications')
        if (primary, 255) not in groups:
            raise SensorError('The primary application requires its source-established unused group object')
        protected = tuple(_group(value) for value in self.protected_groups)
        if any(value not in groups for value in protected):
            raise SensorError('Protected group references must already exist at this causal position')
        if type(self.join_active) is not bool:
            raise SensorError('Join active requires a Boolean')
        object.__setattr__(self, 'application_addresses', apps)
        object.__setattr__(self, 'group_identities', groups)
        object.__setattr__(self, 'protected_groups', protected)
        levels = []
        if not isinstance(self.trigger_levels, (list, tuple)):
            raise SensorError('Trigger levels require actual ordered identities')
        for row in self.trigger_levels:
            if not isinstance(row, (list, tuple)) or len(row) != 3:
                raise SensorError('Trigger level identity requires application, group and level')
            identity = (*_group(row[:2]), _integer(row[2], 255, 'Trigger level'))
            if identity[:2] not in groups or identity[0] != 202:
                raise SensorError('Trigger levels require their actual Trigger Control group object')
            levels.append(identity)
        if len(set(levels)) != len(levels):
            raise SensorError('Trigger level identities must be distinct')
        object.__setattr__(self, 'trigger_levels', tuple(levels))


@dataclass(frozen=True)
class BlockValues:
    secondary: bool
    group: tuple
    light_level: int = 0
    store1: int = 0
    store2: int = 0
    timer: int = 0
    timer_cached: int = 0
    expiry: int | None = 0
    expiry_override: int | None = None

    def __post_init__(self):
        if type(self.secondary) is not bool:
            raise SensorError('Block secondary requires a Boolean')
        object.__setattr__(self, 'group', _group(self.group))
        for field in ('light_level', 'store1', 'store2'):
            _integer(getattr(self, field), 255, field)
        for field in ('timer', 'timer_cached'):
            _integer(getattr(self, field), 65535, field)
        if self.expiry is not None:
            _integer(self.expiry, 15, 'Timer expiry')
        if self.expiry_override is not None:
            _integer(self.expiry_override, 15, 'Timer expiry override')


class SourceObjectRequired(SensorError):
    """An actual source getter reaches an uncomposed object-creation route."""
    def __init__(self, application, address, source, *, kind='group', group=None, create=None):
        self._request = {'kind': kind, 'application': application, 'address': address, 'source': source}
        if group is not None:
            self._request['group'] = group
        if create is not None:
            self._request['create'] = create
            super().__init__(f'Native {source} requires the owning {kind} lookup route for {application}/{address}')
        else:
            super().__init__(f'Native {source} requires the owning GroupManager creation route for {application}/{address}')

    @property
    def request(self):
        return dict(self._request)


@dataclass(frozen=True)
class SourceLookupRequest:
    """An internal lookup position requiring actual creation/storage execution."""
    kind: str
    application: int | None
    address: int
    create: bool
    source: str

    def __post_init__(self):
        if self.kind not in ('application', 'group'):
            raise SensorError('Source lookup requires application or group')
        _integer(self.address, 255, 'Source lookup address')
        if self.application is not None:
            _integer(self.application, 255, 'Source lookup application')
        if self.kind == 'group' and self.application is None:
            raise SensorError('Source group lookup requires an actual application')
        if type(self.create) is not bool or not isinstance(self.source, str) or not self.source:
            raise SensorError('Source lookup requires its create flag and source position')

    def as_dict(self):
        return dict(kind=self.kind, application=self.application, address=self.address,
                    create=self.create, source=self.source)


@dataclass(frozen=True)
class SourceLevelRequest:
    """One CURRENT canonical group LevelManager lookup, without prefetch."""
    group: tuple
    address: int
    create: bool
    source: str

    def __post_init__(self):
        object.__setattr__(self, 'group', _group(self.group))
        _integer(self.address, 255, 'Source level address')
        if type(self.create) is not bool or not isinstance(self.source, str) or not self.source:
            raise SensorError('Source level lookup requires its create flag and source position')

    def as_dict(self):
        return dict(kind='level', group=list(self.group), address=self.address,
                    create=self.create, source=self.source)


@dataclass(frozen=True)
class ParameterWriteRequest:
    """One native cached PP assignment; programming eligibility is separate."""
    name: str
    value: object
    source: str
    operation: str = 'assign'
    index: int | None = None

    def as_dict(self):
        return dict(name=self.name, value=deepcopy(self.value), source=self.source,
                    operation=self.operation, index=self.index)


@dataclass(frozen=True)
class KeyControlRequest:
    """Synchronous native control work delegated to the complete form owner.

    The executor receives the live engine, executes the pinned control branch
    with its actual bindings, and returns after any nested native setters.
    It must reread current values; this request carries no flattened effects.
    """
    key: int
    operation: str = 'general_key_controls'
    source: str = 'ST7.CBusUnitInputKeyChanged'
    classification: bool = False

    def as_dict(self):
        return dict(key=self.key, operation=self.operation, source=self.source,
                    classification=self.classification)


class SourceControlRequired(SensorError):
    def __init__(self, request):
        self._request = request
        super().__init__('M8 general key hook requires the owning native control dispatcher')

    @property
    def request(self):
        return self._request.as_dict()


class _Object(FlashObject):
    def __init__(self, kind, identity):
        super().__init__(f'{kind}:{identity}')
        self.kind = kind
        self.identity = identity


class _Level(_Object):
    """Address is identity; the native current Integer Value is separate."""
    def __init__(self, identity, value, trace):
        super().__init__('level', identity)
        self.manager = AttributeManager(self, trace=trace)
        self.level_value = IntegerAttribute(self.manager, value,
                          name=f'level:{identity}.value', trace=trace)


class _CollectionManager(UpdateObject):
    """Entity manager publishes its parent after base Changed, at any depth.

    Its Begin/End do not call the parent's Begin/End. AttributeManager is a
    different native class and must not be substituted for this route.
    """
    def __init__(self, parent, name, trace):
        super().__init__(name, trace=trace)
        self.parent = parent

    def changed(self):
        super().changed()
        self.parent.changed()


class _SceneCollection(ManagedUpdateObject):
    def __init__(self, parent, name, trace):
        super().__init__(name, trace=trace)
        self.manager = _CollectionManager(parent, name + '.manager', trace)
        self.items = []

    def append(self, value):
        self.items.append(value)
        self.changed()

    def clear(self):
        # InternalClear deletes existing rows descending. Empty Clear does
        # not synthesize the publication that a reserved eight-object pool
        # would have produced.
        while self.items:
            self.items.pop()
            self.changed()

    def changed(self):
        super().changed()
        self.manager.changed()


class _Scene(_Object):
    def __init__(self, ordinal, trace):
        super().__init__('scene', ordinal)
        self.manager = AttributeManager(self, trace=trace)
        self.commands = _SceneCollection(self, f'scene:{ordinal}.commands', trace)
        self.live_groups = False


class _SceneCommand(FlashObject):
    def __init__(self, scene, ordinal, trace):
        super().__init__(f'scene:{scene.identity}.command:{ordinal}', trace=trace)
        self.manager = AttributeManager(self, trace=trace)
        self.group = ObjectReferenceAttribute(self.manager,
                          name=self.name + '.group', trace=trace)
        self.level = IntegerAttribute(self.manager, 0,
                          name=self.name + '.level', trace=trace)

    def set_group(self, value):
        self.group.set(value)
        self.resolve_change()
        self.changed()

    def set_level(self, value):
        self.level.set(value)
        self.resolve_change()
        self.changed()


class _IndicatorNumber(FlashObject):
    """Direct BlockNumber field; SetBlockNumber publishes even equal values."""
    def __init__(self, name, trace):
        super().__init__(name, trace=trace)
        self._value = 0

    @property
    def value(self):
        return self._value

    def set(self, value):
        _integer(value, 8, 'Indicator block number')
        self.begin_update()
        try:
            self._value = value
            self._record('assign')
        finally:
            self.end_update()


class _OwnedObjectAttribute(FlashAttribute):
    """Stable owned Indicator/Neo target and its reference notification.

    Native TObjectAttribute uses the custom reference-list channel after
    managed subscribers, rather than a managed target subscription. Each
    target here has exactly its owning attribute reference; registration does
    not synthesize ObjectChanged. Replacement/destruction is not admitted.
    """
    def __init__(self, manager, target, *, name, trace):
        super().__init__(manager, target, name=name, trace=trace)
        target.reference_notification = lambda _: self.changed()

    @property
    def value(self):
        self.resolve_change()
        return self._value


class _Block:
    def __init__(self, owner, index, raw):
        self.object = FlashObject(f'block:{index}', trace=owner._trace)
        self.manager = AttributeManager(self.object, trace=owner._trace)
        self.application = ObjectReferenceAttribute(
            self.manager, owner.apps[raw.group[0]] if raw is not None else None, name=f'block:{index}.application',
            after_change=lambda _: owner._block_application_changed(index), trace=owner._trace)
        self.secondary = BooleanAttribute(
            self.manager, raw.secondary if raw is not None else False, name=f'block:{index}.secondary',
            after_change=lambda _: owner._secondary_changed(index), trace=owner._trace)
        self.group = ObjectReferenceAttribute(
            self.manager, owner.groups[raw.group] if raw is not None else None, name=f'block:{index}.group',
            after_change=lambda _: owner._group_changed(index), trace=owner._trace)
        for field in ('light_level', 'store1', 'store2', 'timer', 'timer_cached'):
            setattr(self, field, IntegerAttribute(self.manager, getattr(raw, field) if raw is not None else 0,
                    name=f'block:{index}.{field}', trace=owner._trace))
        for field in ('expiry', 'expiry_override'):
            value = getattr(raw, field) if raw is not None else None
            value = None if value is None else owner.micro[value]
            setattr(self, field, ObjectReferenceAttribute(self.manager, value,
                    name=f'block:{index}.{field}', trace=owner._trace))
        self.object.publisher.subscribe(lambda _: owner._block_published(index))


class _Key:
    def __init__(self, owner, index, application):
        self.object = FlashObject(f'key:{index}', trace=owner._trace)
        self.manager = AttributeManager(self.object, trace=owner._trace)
        self.refs = []
        self.list_notifying = False
        self.macro_pin = 0
        self.group_pin = 0
        self.macro_type = 0
        self.stages = (None, None, None, None)
        self.template = ObjectReferenceAttribute(self.manager, name=f'key:{index}.template',
                after_change=lambda _: owner._template_changed(index), trace=owner._trace)
        self.primary_group = ObjectReferenceAttribute(self.manager, name=f'key:{index}.primary_group',
                after_change=lambda _: owner._primary_group_changed(index), trace=owner._trace)
        self.application = ObjectReferenceAttribute(self.manager, application,
                name=f'key:{index}.application', trace=owner._trace)
        self.application_state = IntegerAttribute(self.manager, 0, minimum=0, maximum=2,
                name=f'key:{index}.application_state',
                after_change=lambda _: owner._application_state_changed(index), trace=owner._trace)
        indicator = _IndicatorNumber(f'key:{index}.indicator', owner._trace)
        self._indicator = _OwnedObjectAttribute(self.manager, indicator,
                         name=f'key:{index}.indicator_owned', trace=owner._trace)
        extension = FlashObject(f'key:{index}.neo', trace=owner._trace)
        self._extension = _OwnedObjectAttribute(self.manager, extension,
                         name=f'key:{index}.extension_owned', trace=owner._trace)
        extension_manager = AttributeManager(extension, trace=owner._trace)
        self.scene_ramp_pin = 0
        self.scene_learning = False
        self._scene = ObjectReferenceAttribute(extension_manager, name=f'key:{index}.scene', trace=owner._trace)
        self._scene_rate = IntegerAttribute(extension_manager, 0, minimum=0, maximum=15,
                                           name=f'key:{index}.scene_rate', trace=owner._trace)
        self._scene_trigger = ObjectReferenceAttribute(extension_manager, name=f'key:{index}.scene_trigger', trace=owner._trace)
        self._scene_ramp_function = ObjectReferenceAttribute(extension_manager, name=f'key:{index}.scene_ramp_function', trace=owner._trace)
        self._scene_ramp_template = ObjectReferenceAttribute(extension_manager, name=f'key:{index}.scene_ramp_template',
                after_change=lambda _: owner._scene_ramp_changed(index), trace=owner._trace)
        self._label_flavour = IntegerAttribute(extension_manager, 0, minimum=0, maximum=3,
                                             name=f'key:{index}.label_flavour', trace=owner._trace)
        self.smart = TrackedReferenceHandle(self.template, lambda _: owner._smart_changed(index))
        self.smart.activate()
        self.general_hook = None
        self.function_hook = None

    @property
    def indicator(self):
        return self._indicator.value

    def _neo(self, attribute):
        # GetExtensionNeo performs the owned getter before its type/enabled
        # check and again to obtain the returned object in the live profile.
        self._extension.value
        self._extension.value
        return attribute

    @property
    def scene(self):
        return self._neo(self._scene)

    @property
    def scene_rate(self):
        return self._neo(self._scene_rate)

    @property
    def scene_trigger(self):
        return self._neo(self._scene_trigger)

    @property
    def scene_ramp_function(self):
        return self._neo(self._scene_ramp_function)

    @property
    def scene_ramp_template(self):
        return self._neo(self._scene_ramp_template)

    @property
    def label_flavour(self):
        return self._neo(self._label_flavour)


class SENLLAKeyEvents:
    """Private synchronous owning state; use snapshots to inspect it.

    Failures invalidate the runtime. In particular a native nil dereference,
    unresolved installed decision, or interrupted callback cannot be turned
    into a partial parameter projection or automatically replayed.
    """
    def __init__(self, context, blocks, bank_graph):
        if not isinstance(context, KeyEventContext):
            raise SensorError('Key engine requires internal source-established KeyEventContext')
        if (not isinstance(blocks, (list, tuple)) or len(blocks) != 8
                or any(not isinstance(value, BlockValues) for value in blocks)):
            raise SensorError('Key engine requires eight source-loaded BlockValues')
        if not isinstance(bank_graph, SENLLABankGraph):
            raise SensorError('Key engine requires the actual owning SENLLABankGraph')
        if any(value.group not in context.group_identities for value in blocks):
            raise SensorError('Every raw block requires its already-established group object')
        if any((value.group[0] != (context.secondary_application if value.secondary
                                else context.primary_application)) for value in blocks):
            raise SensorError('Raw block application/group/secondary identities disagree')
        if any(bank.store1 != raw.store1 or bank.store2 != raw.store2
               for bank, raw in zip(bank_graph.banks, blocks)):
            raise SensorError('Owning bank graph and raw block stores must agree at entry')
        if any(bank_graph.references.ordered_references):
            raise SensorError('GetKeyBlocks entry requires the fresh empty key-reference collection')
        self._initialize(context, blocks, bank_graph)

    @classmethod
    def fresh(cls, *, application_addresses=(), group_identities=(), trigger_levels=(),
              source_dispatch=None, application_dispatch=None):
        """Construct once, with nil source references and current inventory only.

        The inventory names actual source-existing objects, without PP-selected
        application references. Missing creation/storage and unit application
        callbacks require synchronous internal executors at their source sites.
        """
        for callback in (source_dispatch, application_dispatch):
            if callback is not None and not callable(callback):
                raise SensorError('Fresh source dispatchers require internal callable executors')
        if any(not isinstance(values, (tuple, list)) for values in
               (application_addresses, group_identities, trigger_levels)):
            raise SensorError('Source-existing inventories require ordered detached sequences')
        application_addresses = tuple(_integer(value, 255, 'Source application address')
                                      for value in application_addresses)
        group_identities = tuple(_group(value) for value in group_identities)
        if (len(set(application_addresses)) != len(application_addresses)
                or len(set(group_identities)) != len(group_identities)):
            raise SensorError('Source-existing inventory identities must be distinct')
        runtime = cls.__new__(cls)
        runtime._initialize(None, (None,) * 8, SENLLABankGraph.fresh(),
                            source_dispatch=source_dispatch, application_dispatch=application_dispatch)
        for address in application_addresses:
            runtime.add_source_application(address)
        for identity in group_identities:
            app, address = _group(identity)
            if app not in runtime.apps:
                raise SensorError('Source-existing group requires its actual application')
            runtime.add_source_group(runtime.apps[app], address)
        for identity in trigger_levels:
            if not isinstance(identity, (tuple, list)) or len(identity) != 3:
                raise SensorError('Source-existing level requires application/group/level')
            group = _group(identity[:2])
            level = _integer(identity[2], 255, 'Source-existing trigger level')
            if group not in runtime.groups or group[0] != 202:
                raise SensorError('Source-existing trigger level requires its actual Trigger group')
            full = (*group, level)
            if full in runtime.levels:
                raise SensorError('Source-existing level identities must be distinct')
            runtime.levels[full] = _Level(full, level, runtime._trace)
        return runtime

    def _initialize(self, context, blocks, bank_graph, *, source_dispatch=None, application_dispatch=None):
        self.context = context
        self._fresh_mode = context is None
        self.graph = bank_graph
        self.events = []
        self.phase = 'fresh_constructor' if self._fresh_mode else 'get_key_blocks'
        self.failed = False
        self.hooks_installed = False
        self.group_decision_handler_installed = False
        self.macro_decision_handler_installed = False
        self.event_handler_installed = False
        self.control_dispatch = None
        self.protected_group_attributes = None
        self.source_dispatch = source_dispatch
        self.level_dispatch = None
        self.application_dispatch = application_dispatch
        self.live_bank_dispatch = None
        self._live_occupancy_flags = None
        self.created_groups = []
        self.apps = {value: _Object('application', value) for value in context.application_addresses} if context else {}
        self.groups = {value: _Object('group', value) for value in context.group_identities} if context else {}
        self._source_group_orders = {}
        self.levels = {value: _Level(value, value[2], self._trace) for value in context.trigger_levels} if context else {}
        self.templates = {value: _Object('template', value) for value in range(59)}
        self.micro = {value: _Object('micro', value) for value in range(128)}
        # Projected entry historically reserves an eight-object pool. Fresh
        # owning construction has an actual empty native collection instead.
        self.scenes = tuple(_Object('scene', value) for value in range(8)) if context else ()
        self.scene_commands = ((),) * 8
        self.scene_expected = None
        self._control_group_cache = None
        self._causal_scenes = False
        self._causal_control = False
        self.unit = FlashObject('unit', trace=self._trace)
        self.block_collection = FlashObject('blocks', trace=self._trace)
        self.unit_manager = AttributeManager(self.unit, trace=self._trace)
        self.primary_application = ObjectReferenceAttribute(self.unit_manager,
                self.apps[context.primary_application] if context else None, name='unit.primary_application',
                after_change=lambda _: self._unit_application_changed(False), trace=self._trace)
        self.secondary_application = ObjectReferenceAttribute(self.unit_manager,
                self.apps.get(context.secondary_application) if context else None, name='unit.secondary_application',
                after_change=lambda _: self._unit_application_changed(True), trace=self._trace)
        self.area = ObjectReferenceAttribute(self.unit_manager, name='unit.area', trace=self._trace)
        self.control_app_group = ObjectReferenceAttribute(self.unit_manager,
                name='unit.control_app_group', after_change=lambda _: self._control_group_changed(),
                trace=self._trace)
        self.scenes_enabled = BooleanAttribute(self.unit_manager, False,
                name='unit.scenes_enabled', trace=self._trace)
        self.scene_collection = _SceneCollection(self.unit, 'unit.scenes', self._trace)
        self.broadcast_active = BooleanAttribute(self.unit_manager, False, name='unit.broadcast_active',
                after_change=lambda _: self._broadcast_changed(), trace=self._trace)
        self.broadcast_block = ObjectReferenceAttribute(self.unit_manager, name='unit.broadcast_block',
                after_change=lambda _: self._broadcast_changed(), trace=self._trace)
        self._bank_feedback = [0] * 8
        self.blocks = tuple(_Block(self, index, raw) for index, raw in enumerate(blocks))
        app = self.apps[context.primary_application] if context else None
        self.keys = tuple(_Key(self, index, app) for index in range(8))
        self._block_indices = {block.object: index for index, block in enumerate(self.blocks)}
        self._bank_block_links = tuple(block.object for block in self.blocks)
        if self._fresh_mode:
            for index in range(8):
                self._event('constructor_bank_link_activation', block=index)
        else:
            self.unit.begin_update()

    def _unit_application_changed(self, secondary):
        if self.application_dispatch is None:
            raise SensorError('Unit application setter requires its source application callback executor')
        result = self.application_dispatch(self, secondary)
        if result is not None:
            raise SensorError('Unit application dispatcher must finish its actual callbacks before returning')

    def application_object(self, secondary=False):
        if type(secondary) is not bool:
            raise SensorError('Application side requires a Boolean')
        return (self.secondary_application if secondary else self.primary_application).value

    @property
    def control_group(self):
        return self.control_app_group.value if self._causal_control else self._control_group_cache

    @control_group.setter
    def control_group(self, value):
        # Historical projected component binding is not a source setter.
        self._control_group_cache = value

    def set_control_app_group(self, value):
        if value is not None and (not isinstance(value, _Object) or value.kind != 'group'
                or self.groups.get(value.identity) is not value or value.identity[0] != 202):
            raise SensorError('Control group setter requires its actual canonical Trigger group')
        def execute():
            self._causal_control = True
            self.control_app_group.set(value)
        return self._run(execute)

    def _control_group_changed(self):
        # d08648 captures Count then reads CURRENT control group for each key.
        # Membership compares the actual level object pointer, not its byte.
        count = len(self.keys)
        for index in range(count):
            group = self.control_app_group.value
            if group is None:
                self.keys[index].scene_trigger.set(None)
                continue
            current = self.keys[index].scene_trigger.value
            group = self.control_app_group.value
            if group is None:
                raise SensorError('Control group changed to nil during native level-manager dereference')
            if current is None or not any(level is current for identity, level in self.levels.items()
                                           if identity[:2] == group.identity):
                self.keys[index].scene_trigger.set(None)

    def _application_address(self, secondary=False):
        application = self.application_object(secondary)
        return application.identity if application is not None else None

    def add_source_application(self, address):
        """Bind a source-confirmed existing/created identity without inventing its history."""
        address = _integer(address, 255, 'Source application address')
        if address not in self.apps:
            self.apps[address] = _Object('application', address)
        return self.apps[address]

    def add_source_group(self, application, address):
        address = _integer(address, 255, 'Source group address')
        if (not isinstance(application, _Object) or application.kind != 'application'
                or self.apps.get(application.identity) is not application):
            raise SensorError('Source group requires the same actual engine-owned application object')
        identity = (application.identity, address)
        if identity not in self.groups:
            self.groups[identity] = _Object('group', identity)
            self._source_group_orders.pop(application.identity, None)
        return self.groups[identity]

    def add_source_level(self, group, address, *, value=None):
        """Register source-confirmed Level address and actual current Value.

        Existing address lookups do not normalize Value. Fresh creation sets
        Value=address in the native backend before this method is called.
        """
        address = _integer(address, 255, 'Source level address')
        if (not isinstance(group, _Object) or group.kind != 'group'
                or self.groups.get(group.identity) is not group):
            raise SensorError('Source level requires its same canonical owning group')
        if value is None:
            value = address
        if type(value) is not int or not -(1 << 31) <= value < (1 << 31):
            raise SensorError('Native level Value requires a signed 32-bit integer')
        identity = (*group.identity, address)
        existing = self.levels.get(identity)
        if existing is None:
            existing = self.levels[identity] = _Level(identity, value, self._trace)
        elif existing.level_value._value != value:
            raise SensorError('Existing source level requires its actual setter rather than registration replacement')
        return existing

    def get_source_level(self, group, address, *, create=True, source):
        address = _integer(address, 255, 'Source level address')
        if (not isinstance(group, _Object) or group.kind != 'group'
                or self.groups.get(group.identity) is not group):
            raise SensorError('LevelManager lookup requires its CURRENT canonical group')
        request = SourceLevelRequest(group.identity, address, create, source)
        self._event('source_lookup', request=request.as_dict())
        identity = (*group.identity, address)
        current = self.levels.get(identity)
        if current is not None:
            return current
        if self.level_dispatch is None:
            raise SourceObjectRequired(group.identity[0], address, source,
                                       kind='level', group=group.identity[1], create=create)
        returned = self.level_dispatch(request, self)
        if returned is not None:
            raise SensorError('Source level dispatcher must complete lookup/creation before returning')
        current = self.levels.get(identity)
        if current is None and create:
            raise SourceObjectRequired(group.identity[0], address, source,
                                       kind='level', group=group.identity[1], create=create)
        return current

    def level_value(self, level):
        if (not isinstance(level, _Level) or self.levels.get(level.identity) is not level):
            raise SensorError('Level Value getter requires the actual canonical level object')
        return level.level_value.value

    def bind_source_group_order(self, application, addresses):
        """Bind actual CURRENT manager Items order, without changing any object."""
        if (not isinstance(application, _Object) or application.kind != 'application'
                or self.apps.get(application.identity) is not application):
            raise SensorError('Source manager order requires the same actual application object')
        if not isinstance(addresses, (tuple, list)):
            raise SensorError('Source manager order requires its actual ordered address sequence')
        addresses = tuple(_integer(address, 255, 'Source manager group address') for address in addresses)
        registered = {address for app, address in self.groups if app == application.identity}
        if len(set(addresses)) != len(addresses) or set(addresses) != registered:
            raise SensorError('Source manager order must contain exactly its currently registered groups')
        self._source_group_orders[application.identity] = tuple(self.groups[(application.identity, address)]
                                                                for address in addresses)

    def current_source_group_order(self, application):
        if (not isinstance(application, _Object) or application.kind != 'application'
                or self.apps.get(application.identity) is not application):
            raise SensorError('Source manager order requires the same actual application object')
        if application.identity not in self._source_group_orders:
            raise SensorError('Actual current GroupManager Items order requires its owning source executor')
        return self._source_group_orders[application.identity]

    def _source_lookup(self, request, inventory, identity):
        self._event('source_lookup', request=request.as_dict())
        result = inventory.get(identity)
        if result is not None:
            return result
        if self.source_dispatch is None:
            raise SourceObjectRequired(request.application, request.address, request.source,
                                       kind=request.kind, create=request.create)
        returned = self.source_dispatch(request, self)
        if returned is not None:
            raise SensorError('Source dispatcher must complete actual lookup/creation before returning')
        result = inventory.get(identity)
        if result is None and request.create:
            raise SourceObjectRequired(request.application, request.address, request.source,
                                       kind=request.kind, create=request.create)
        return result

    def get_source_application(self, address, create=True, *, source):
        request = SourceLookupRequest('application', None, address, create, source)
        return self._source_lookup(request, self.apps, address)

    def get_source_group(self, application, address, create=True, *, source):
        if (not isinstance(application, _Object) or application.kind != 'application'
                or self.apps.get(application.identity) is not application):
            raise SensorError('Source group lookup requires the same actual application object')
        request = SourceLookupRequest('group', application.identity, address, create, source)
        return self._source_lookup(request, self.groups, (application.identity, address))

    def begin_prekey_load(self):
        def execute():
            self._require_phase('fresh_constructor')
            if self.unit.depth != 0:
                raise SensorError('CoreKey fresh load requires the balanced constructor Unit')
            self.unit.begin_update()
            self.phase = 'prekey_load'
        return self._run(execute)

    def handoff_to_key_blocks(self):
        def execute():
            self._require_phase('prekey_load')
            if (self.unit.depth != 1 or self.unit_manager.updating
                    or any(attribute.updating for attribute in
                           (self.primary_application, self.secondary_application, self.area))
                    or any(block.object.updating for block in self.blocks)):
                raise SensorError('GetKeyBlocks handoff requires Unitdepth1 and balanced managers, attributes and blocks')
            primary = self.application_object()
            secondary = self.application_object(True)
            if primary is None:
                raise SensorError('GetKeyBlocks handoff requires actual primary Lighting')
            if (not isinstance(primary, _Object) or self.apps.get(primary.identity) is not primary
                    or (secondary is not None and (not isinstance(secondary, _Object)
                        or self.apps.get(secondary.identity) is not secondary))):
                raise SensorError('GetKeyBlocks handoff requires canonical engine-owned application objects')
            for block in self.blocks:
                application = block.application.value
                group = block.group.value
                selected = secondary if block.secondary.value else primary
                if (application is not selected or application is None
                        or self.apps.get(application.identity) is not application
                        or not isinstance(group, _Object) or self.groups.get(group.identity) is not group
                        or group.identity[0] != application.identity):
                    raise SensorError('GetKeyBlocks handoff requires canonical current app-owned block groups')
            if any(key.object.updating or key.refs or key.application.value is not primary
                   or key.application_state.value != 0 for key in self.keys):
                raise SensorError('GetKeyBlocks handoff requires balanced empty primary key references')
            if any(self.graph.references.ordered_references):
                raise SensorError('GetKeyBlocks handoff cannot replace an existing key graph')
            context = KeyEventContext(primary.identity, secondary.identity if secondary else None,
                                      tuple(self.apps), tuple(self.groups), trigger_levels=tuple(self.levels))
            self.context = context
            self.phase = 'get_key_blocks'
            self._event('same_object_get_key_blocks_handoff')
        return self._run(execute)

    def _trace(self, event):
        if len(self.events) >= 100000:
            self.failed = True
            raise SensorError('Owning callback trace exceeded the bounded execution budget')
        self.events.append(event.as_dict())

    def _event(self, operation, **values):
        self.events.append({'operation': operation, **values})

    def _run(self, callback):
        if self.failed:
            raise SensorError('An interrupted owning callback runtime cannot be resumed')
        try:
            return callback()
        except Exception:
            self.failed = True
            raise

    def _require_phase(self, phase):
        if self.phase != phase:
            raise SensorError(f'Owning key phase requires {phase}, currently {self.phase}')

    def _template_type(self, key):
        value = self.keys[key].template.value
        return value.identity if value is not None else None

    def _primary(self, key):
        refs = self.keys[key].refs
        return refs[0] if refs else None

    def _bind_refs(self):
        self.graph = self.graph.with_references(SENLLAKeyReferences(tuple(tuple(key.refs) for key in self.keys)))

    def _bank_stores(self):
        if self.live_bank_dispatch is not None:
            # Actual bank attributes and tracked block observers own this
            # route. The bounded graph is only an optional observation.
            self.live_bank_dispatch.sync_graph_observation()
            return
        banks = tuple(replace(bank, store1=block.store1.value, store2=block.store2.value)
                      for bank, block in zip(self.graph.banks, self.blocks))
        self.graph = replace(self.graph, banks=banks)

    def _bank_feedback_writes(self):
        if self.live_bank_dispatch is not None:
            return
        for index, (bank, block) in enumerate(zip(self.graph.banks, self.blocks)):
            if (bank.store1, bank.store2) == (block.store1.value, block.store2.value):
                continue
            self._bank_feedback[index] += 1
            try:
                block.object.begin_update()
                try:
                    block.store1.set(bank.store1)
                    block.store2.set(bank.store2)
                finally:
                    block.object.end_update()
            finally:
                self._bank_feedback[index] -= 1

    def _block_published(self, block):
        if self.live_bank_dispatch is not None:
            if self.live_bank_dispatch.block_changed(block, self) is not None:
                raise SensorError('Live bank observation must finish before returning')
            self._event('block_published_live', block=block)
            return
        if self._bank_feedback[block]:
            self._event('bank_feedback_suppressed', block=block)
            return
        self._bind_refs()
        self._bank_stores()
        self.graph = self.graph.block_changed(block)
        self._event('block_published', block=block)
        self._bank_feedback_writes()

    def _smart_changed(self, key):
        self._bind_refs()
        self._bank_stores()
        template = self._template_type(key)
        if self.live_bank_dispatch is not None:
            transition = self.graph.occupancy[key].macro_changed(template,
                decision_handler_installed=self.macro_decision_handler_installed,
                broadcast_key=(self.broadcast_active.value and self._has_broadcast(key)))
            state = transition.state
            # Smart assigns its decision fields before the ordered flag
            # setters. Flag callbacks can themselves change CURRENT flags.
            states = list(self.graph.occupancy)
            states[key] = replace(state, light=self.current_occupancy_flags(key)[0],
                dark=self.current_occupancy_flags(key)[1],
                any_movement=self.current_occupancy_flags(key)[2],
                sunset=self.current_occupancy_flags(key)[3])
            self.graph = replace(self.graph, occupancy=tuple(states))
            if template is not None and (template in (29,30,33,34,24,25) or state.refresh_from_macro):
                for flag, value in enumerate((template == 29,template == 30,template == 33,template == 34)):
                    self._set_live_flag(key, flag, value)
            self._event('macro_smart', key=key, template=template)
            return
        self.graph = self.graph.macro_changed(key, template,
                decision_handler_installed=self.macro_decision_handler_installed,
                broadcast_key=(self.broadcast_active.value and self._has_broadcast(key)))
        self._event('macro_smart', key=key, template=self._template_type(key))
        self._bank_feedback_writes()

    def _quick_flags(self, key):
        self._bind_refs()
        self._bank_stores()
        template = self._template_type(key)
        join = self.context.join_active if self.context is not None else False
        if self.live_bank_dispatch is not None:
            self.graph.occupancy[key].refresh_event_flags(template, key_index=key,
                join_active=join, event_template_handler_installed=self.event_handler_installed)
            if template is not None and not (join and key >= 4):
                for flag, value in enumerate((template == 29,template == 30,template == 33,template == 34)):
                    self._set_live_flag(key, flag, value)
            return
        self.graph = self.graph.refresh_event_flags(key, template,
                join_active=self.context.join_active if self.context is not None else False,
                event_template_handler_installed=self.event_handler_installed)
        self._bank_feedback_writes()

    def _set_flag(self, key, flag, value):
        if self.live_bank_dispatch is not None:
            if self.event_handler_installed and self.current_occupancy_flags(key)[flag] != value:
                raise SensorError('Installed event-to-template callback requires its owning decision dispatch')
            return self._set_live_flag(key, flag, value)
        state = self.graph.occupancy[key]
        transition = state._set_flags(((flag, value),))
        if transition.bank_events and self.event_handler_installed:
            raise SensorError('Installed event-to-template callback requires its owning decision dispatch')
        self._bind_refs()
        self._bank_stores()
        self.graph = self.graph.apply_occupancy_transition(key, transition)
        self._bank_feedback_writes()

    def current_occupancy_flags(self, key):
        """CURRENT flags at one native event, including nested callbacks."""
        if type(key) is not int or not 0 <= key < 8:
            raise SensorError('Occupancy key requires index0..7')
        if self._live_occupancy_flags is None:
            return self.graph.occupancy[key].flags
        return tuple(self._live_occupancy_flags[key])

    def _set_live_flag(self, key, flag, value):
        if self._live_occupancy_flags is None:
            self._live_occupancy_flags = [list(state.flags) for state in self.graph.occupancy]
        flags = self._live_occupancy_flags[key]
        if flags[flag] == value:
            return
        flags[flag] = value
        if value and flag < 3:
            for other in ((2,1),(0,2),(0,1))[flag]:
                self._set_live_flag(key, other, False)
        # Each nested clear and the initiating flag deliver separate events.
        # Reread flags after nested work, including an earlier bank callback.
        current = self.current_occupancy_flags(key)
        states = list(self.graph.occupancy)
        states[key] = replace(states[key], light=current[0], dark=current[1],
                              any_movement=current[2], sunset=current[3])
        self.graph = replace(self.graph, occupancy=tuple(states))
        self._event('occupancy_live_event', key=key, flags=list(current))
        if self.live_bank_dispatch.occupancy_bank_event(key, self) is not None:
            raise SensorError('Live bank event must finish its native setters before returning')

    def _has_broadcast(self, key):
        current = self.broadcast_block.value
        return current is not None and self._block_indices[current] in self.keys[key].refs

    def _refs_changed(self, key):
        owner = self.keys[key]
        self._bind_refs()
        if owner.list_notifying:
            self._event('same_reference_collection_notification_suppressed', key=key)
            return
        owner.list_notifying = True
        try:
            # UnitInputKeyBlocksChanged: Clear, Reassign, then changed-key QuickSet.
            for index in range(8):
                if self.broadcast_active.value and self._has_broadcast(index):
                    for flag in (0, 1, 2, 3):
                        self._set_flag(index, flag, False)
            candidate = None
            conflict = False
            for index in range(8):
                flags = self.graph.occupancy[index].flags
                if not any(flags) and candidate is None:
                    candidate = self._primary(index)
                elif any(flags) and self._has_broadcast(index):
                    conflict = True
            if conflict and candidate is not None:
                self.broadcast_block.set(self.blocks[candidate].object)
            self._quick_flags(key)
        finally:
            owner.list_notifying = False

    def _add(self, key, block):
        owner = self.keys[key]
        if block in owner.refs:
            return
        owner.object.begin_update()
        try:
            owner.refs.append(block)
            self._event('reference_add', key=key, block=block, references=list(owner.refs))
            self._refs_changed(key)
        finally:
            owner.object.end_update()
        if not owner.object.updating:
            self._block_secondary_refresh(block)
            self._primary_refresh(key)

    def _remove(self, key, block):
        owner = self.keys[key]
        if block not in owner.refs:
            return
        owner.object.begin_update()
        try:
            owner.refs.remove(block)
            self._event('reference_remove', key=key, block=block, references=list(owner.refs))
            self._refs_changed(key)
        finally:
            owner.object.end_update()
        if not owner.object.updating:
            self._primary_refresh(key)
            self._block_secondary_refresh(block)

    def _classification(self, key):
        sides = {self.blocks[index].secondary.value for index in self.keys[key].refs}
        return 2 if len(sides) > 1 else 1 if sides == {True} else 0

    def _primary_refresh(self, key):
        owner = self.keys[key]
        captured = owner.refs[0] if len(owner.refs) == 1 else None
        owner.group_pin += 1
        owner.object.begin_update()
        try:
            owner.application_state.set(self._classification(key))
            owner.primary_group.set(self.blocks[captured].group.value if captured is not None else None)
        finally:
            owner.object.end_update()
            owner.group_pin -= 1

    def _primary_group_changed(self, key):
        owner = self.keys[key]
        if owner.group_pin:
            return
        # Unlocked group edits need their separate group-to-block decision route.
        raise SensorError('Unlocked key primary-group edits require the owning group-control dispatcher')

    def _block_secondary_refresh(self, block):
        target = self.blocks[block]
        for key in range(8):
            owner = self.keys[key]
            if owner.object.updating:
                continue
            target.object.begin_update()
            try:
                self._event('block_secondary_key_refresh', block=block, key=key)
                owner.application_state.set(self._classification(key))
            finally:
                target.object.end_update()

    def _application_state_changed(self, key):
        owner = self.keys[key]
        state = owner.application_state.value
        if state == 2:
            block = key if key in owner.refs else self._primary(key)
            app = self.blocks[block].application.value if block is not None else self.application_object()
        else:
            app = self.application_object(state == 1)
        owner.application.set(app)
        # The native count is captured once; each item is read after callbacks.
        for ordinal in range(len(owner.refs)):
            if ordinal >= len(owner.refs):
                raise SensorError('Native key reference index became unavailable during application change')
            block = self.blocks[owner.refs[ordinal]]
            if block.object.updating:
                continue
            owner.object.begin_update()
            try:
                current_state = owner.application_state.value
                if current_state == 0:
                    block.secondary.set(False)
                elif current_state == 1:
                    block.secondary.set(True)
            finally:
                owner.object.end_update()
        self._primary_refresh(key)
        self._identical(key)
        self._refresh_template(key)
        if owner.application_state.value in (1, 2) and self._template_type(key) in (23, 24, 25):
            owner.template.set(self.templates[16])

    def _secondary_changed(self, source):
        block = self.blocks[source]
        address = self._application_address(block.secondary.value)
        for destination in range(8):
            if destination == source:
                continue
            group = self.blocks[destination].group.value
            if group is None or group.identity[1] == 255:
                continue
            source_group = block.group.value
            if source_group is None:
                raise SensorError('Native collision reads the current source group address from nil')
            if address is None:
                raise SensorError('Native secondary collision lookup has no application object')
            found = self.groups.get((address, source_group.identity[1]))
            if found is not group:
                continue
            for key in range(8):
                if source in self.keys[key].refs:
                    self._add(key, destination)
                    self._remove(key, source)
            block.group.set(self.groups[(address, 255)])
        block.application.set(self.apps[address] if address is not None else None)
        self._block_secondary_refresh(source)

    def _block_application_changed(self, index):
        block = self.blocks[index]
        app = block.application.value
        if app is None:
            raise SensorError('Native block application refresh has no application object')
        old = block.group.value
        address = old.identity[1] if old is not None else 255
        if self._fresh_mode:
            group = self.get_source_group(app, address, create=False, source='block_application_probe')
            if group is None and self.group_decision_handler_installed:
                raise SensorError('Missing destination group requires the installed native unit decision')
            # d0f9d5 tests a first allow-enabled getter, then d0f9f2 reads
            # CURRENT AppForBlock again and supplies a second getter result
            # to SetGroup. Creation/storage observers can change that app.
            # A create-enabled nil result remains an explicit source boundary.
            self.get_source_group(block.application.value, address, create=True,
                                  source='block_application_getter')
            group = self.get_source_group(block.application.value, address, create=True,
                                          source='block_application_assignment_getter')
            block.group.set(group)
            return
        group = self.groups.get((app.identity, address))
        if group is None:
            if self.group_decision_handler_installed:
                raise SensorError('Missing destination group requires the installed native unit decision')
            raise SourceObjectRequired(app.identity, address, 'block_application_getter')
        block.group.set(group)

    def _group_changed(self, block):
        group = self.blocks[block].group.value
        if self.block_collection.updating or not self.block_collection.enabled or group is None:
            self._event('block_group_notification_suppressed', block=block)
            return
        for key in range(8):
            if block in self.keys[key].refs:
                self._primary_refresh(key)
        group = self.blocks[block].group.value
        if self.protected_group_attributes is not None:
            if (not isinstance(self.protected_group_attributes, tuple)
                    or len(self.protected_group_attributes) != 3
                    or any(not isinstance(attr, ObjectReferenceAttribute)
                           for attr in self.protected_group_attributes)):
                raise SensorError('Source protection requires CURRENT PEC, Join, Corridor reference attributes')
            if group is not None and group.identity[1] != 255:
                for attr in self.protected_group_attributes:
                    if self.blocks[block].group.value is attr.value:
                        app = self.blocks[block].application.value
                        unused = self.get_source_group(app, 255, create=False, source='0xcfb6f0')
                        self.blocks[block].group.set(unused)
                        break
            return
        protected = self.context.protected_groups if self.context is not None else ()
        if group is not None and group.identity[1] != 255 and group.identity in protected:
            app = self.blocks[block].application.value
            self.blocks[block].group.set(self.groups[(app.identity, 255)])

    def _identical(self, key):
        owner = self.keys[key]
        block = self._primary(key)
        if owner.macro_type == 14 and block is not None:
            owner.macro_type = {249: 17, 252: 18, 255: 20}.get(self.blocks[block].store1.value, 14)
        elif owner.macro_type == 15 and block is not None:
            owner.macro_type = {2: 19, 5: 22}.get(self.blocks[block].store2.value, 15)

    def _refresh_template(self, key):
        owner = self.keys[key]
        if self._template_type(key) == 25:
            owner.scene_ramp_pin += 1
            try:
                owner.scene_ramp_template.set(self.templates[owner.macro_type])
            finally:
                owner.scene_ramp_pin -= 1
            return
        if owner.application.value is None:
            raise SensorError('Native macro subset reads a nil key application')
        template = owner.macro_type if owner.macro_type in _SUBSET else 26
        owner.macro_pin += 1
        try:
            owner.template.set(self.templates[template])
        finally:
            owner.macro_pin -= 1

    def _raw_macro_refresh(self, key):
        owner = self.keys[key]
        function = _MATCHES.get(owner.stages, 26)
        owner.macro_type = {27: 26, 31: 29, 32: 30}.get(function, function)
        self._identical(key)
        self._refresh_template(key)

    def _template_changed(self, key):
        owner = self.keys[key]
        template = self._template_type(key)
        if template is None:
            return
        block = self._primary(key)
        if template == 6 or 29 <= template <= 35:
            if block is not None:
                target = self.blocks[block]
                if target.timer.value == 0:
                    target.timer.set(300)
                if target.expiry.value is None:
                    target.expiry.set(self.micro[15])
        if self._template_type(key) in (23, 24, 25):
            self._claim_scene(key)
        if not owner.macro_pin:
            current = self._template_type(key)
            if current != 25:
                owner.macro_type = current
                owner.stages = _DEFAULTS[current]
        current = self._template_type(key)
        if current == 25:
            ramp = owner.scene_ramp_template.value
            if ramp is None or ramp.identity == 16:
                owner.scene_ramp_template.set(self.templates[3])
        else:
            owner.scene_ramp_template.set(self.templates[16])
        if self._template_type(key) in (23, 24):
            # Native logical LabelFlavour1 is raw enum0. Fresh raw0 is equal
            # and therefore produces no owned extension notification.
            owner.label_flavour.set(0)
        current = self._template_type(key)
        if current in (24, 25):
            owner.scene_learning = False
        elif current == 23:
            owner.scene_learning = True

    def _scene_ramp_changed(self, key):
        owner = self.keys[key]
        ramp = owner.scene_ramp_template.value
        if ramp is None or self._template_type(key) != 25 or owner.scene_ramp_pin:
            return
        template = ramp.identity
        if template not in _DEFAULTS:
            raise SensorError('Unlocked Scene ramp assignment requires its source default-group projection')
        owner.macro_type = template
        owner.stages = _DEFAULTS[template]

    def _associated(self, block):
        return tuple(key for key in range(8) if block in self.keys[key].refs)

    def _claim_scene(self, key):
        for block in range(8):
            self._remove(key, block)
        linear = key
        associated = self._associated(linear)
        candidate = associated[0] if len(associated) == 1 else None
        if candidate is not None:
            group = self.blocks[candidate].group.value
            if group is not None and group.identity[1] != 255 and self._associated(candidate):
                candidate = None
        if associated and candidate is None:
            for index in range(7, -1, -1):
                if index == linear:
                    continue
                group = self.blocks[index].group.value
                if group is not None and group.identity[1] == 255 and self._template_type(linear) not in (23, 24, 25):
                    candidate = index
        if associated and candidate is None:
            for index in range(7, -1, -1):
                if index != linear and not self._associated(index):
                    candidate = index
        if candidate is not None:
            self._swap(candidate, linear)
        for other in range(8):
            if other != key:
                self._remove(other, linear)
        self._add(key, linear)
        target = self.blocks[linear]
        target.secondary.set(False)
        app = target.application.value
        if app is None or (app.identity, 255) not in self.groups:
            raise SensorError('Native Scene claim requires the current unused group object')
        target.group.set(self.groups[(app.identity, 255)])
        self.keys[key].indicator.set(key + 1)
        self._event('scene_claim', key=key, candidate=candidate)

    def _swap(self, first, second):
        a, b = self.blocks[first], self.blocks[second]
        cached = {field: getattr(a, field).value for field in _BLOCK_FIELDS}
        a.object.begin_update()
        b.object.begin_update()
        try:
            # SwapBlockData has its own update pair for each destination,
            # nested inside the allocator's two outer block update pairs.
            a.object.begin_update()
            try:
                for field in _BLOCK_FIELDS:
                    getattr(a, field).set(getattr(b, field).value)
            finally:
                a.object.end_update()
            b.object.begin_update()
            try:
                for field in _BLOCK_FIELDS:
                    getattr(b, field).set(cached[field])
            finally:
                b.object.end_update()
            for key in range(8):
                refs = self.keys[key].refs
                if (first in refs) == (second in refs):
                    continue
                old, new = (first, second) if first in refs else (second, first)
                self._remove(key, old)
                self._add(key, new)
                if self.keys[key].indicator.value == old + 1:
                    self.keys[key].indicator.set(new + 1)
                    # SwapMappings explicitly rereads the owned indicator
                    # and calls Custom.Changed after SetBlockNumber's End.
                    self.keys[key].indicator.changed()
        finally:
            b.object.end_update()
            a.object.end_update()
        self._event('block_swap', first=first, second=second)

    def _broadcast_changed(self):
        current = self.broadcast_block.value
        maintenance = (self.blocks[self.graph.maintenance_block].object
                       if self.graph.maintenance_block is not None else None)
        if (self.graph.maintenance_active and self.broadcast_active.value and maintenance is current):
            return
        for block in range(8):
            same = self.blocks[block].object is self.broadcast_block.value
            value = self.micro[8] if same and self.broadcast_active.value else None
            self.blocks[block].expiry_override.set(value)
        if self.broadcast_active.value and self.broadcast_block.value is not None:
            for key in range(8):
                if self._has_broadcast(key):
                    template = self._template_type(key)
                    if template is None:
                        raise SensorError('Native broadcast function scan dereferences a nil template')
                    if template in (29, 30, 33, 34):
                        self.keys[key].template.set(self.templates[16])

    def load_allocations(self, masks, *, parameter_read=None):
        masks = _eight(masks, 255, 'BlockAllocation')
        if parameter_read is not None and not callable(parameter_read):
            raise SensorError('CURRENT allocation reader requires an internal callable executor')
        def execute():
            self._require_phase('get_key_blocks')
            for key in range(8):
                # AsArrayInteger is called separately before each key row;
                # callbacks from an earlier row may change a later mask.
                current = self._read_current_pp(parameter_read, 'BlockAllocation',
                                                masks, '0xcc7784')
                mask = _eight(current, 255, 'Current BlockAllocation')[key]
                for block in range(8):
                    if mask & (1 << block):
                        self._add(key, block)
                    else:
                        self._remove(key, block)
                self._primary_refresh(key)
            self.phase = 'corekey_application_refresh'
        return self._run(execute)

    def finish_corekey_application_refresh(self):
        def execute():
            self._require_phase('corekey_application_refresh')
            self.unit.end_update()
            for secondary in (False, True):
                app = self._application_address(secondary)
                if app in (None, 255):
                    for block in self.blocks:
                        block.secondary.set(False)
                else:
                    for block in self.blocks:
                        if block.secondary.value == secondary:
                            block.application.set(self.apps[app])
                    for key in self.keys:
                        if key.application_state.value == int(secondary):
                            key.application.set(self.apps[app])
                    for block in self.blocks:
                        block.object.resolve_change()
                        block.object.changed()
                    for key in self.keys:
                        key.object.resolve_change()
                        key.object.changed()
                self._application_group_refresh(secondary)
                for key in range(8):
                    if self.keys[key].application_state.value != int(secondary):
                        continue
                    template = self._template_type(key)
                    self._event('application_macro_subset_check', secondary=secondary,
                                key=key, template=template)
                    if template is not None and template not in _SUBSET:
                        self.keys[key].template.set(self.templates[16])
            self.phase = 'core_neo_scenes'
        return self._run(execute)

    def _application_group_refresh(self, secondary):
        # Virtual188 is source-qualified, rather than silently omitted.
        # Core.CheckGroups probes each matching block's CURRENT application
        # manager without creating. Pre-Neo Scene managers are still empty.
        app = self._application_address(secondary)
        if any(self.scene_commands):
            raise SensorError('Prekey application group refresh requires the fresh empty Scene manager')
        if app in (None, 255):
            # c9f280 has cleared true Secondary bits. The following unused
            # primary-group refresh has no matching secondary/mixed keys in
            # this balanced fresh context; broader state requires its owner.
            if any(owner.application_state.value in (1, 2) for owner in self.keys):
                raise SensorError('Unused application group refresh requires its owning nonfresh dispatch')
        else:
            for index, block in enumerate(self.blocks):
                if block.secondary.value != secondary:
                    continue
                current_app = block.application.value
                group = block.group.value
                address = group.identity[1] if group is not None else 255
                if current_app is None:
                    raise SensorError('Native application group check dereferences a nil block application')
                if (current_app.identity, address) not in self.groups:
                    raise SourceObjectRequired(current_app.identity, address, 'application_group_refresh')
            # Lighting CanAddGroups=true + missingfalse does not enter group
            # setters or decisions. Brightness support is false for SENLLA;
            # the primary-only Scene walk has zero current commands here.
        self._event('application_group_refresh_qualified_noop', secondary=secondary)

    def load_scenes(self, table, pointers, patch, control_group):
        scenes = loaded_scenes(table, pointers)
        if (not isinstance(patch, (list, tuple)) or len(patch) != 2
                or any(type(value) is not int or not 0 <= value <= 255 for value in patch)):
            raise SensorError('PatchEnable requires two bytes')
        identity = _group(control_group)
        if identity[0] != 202 or identity not in self.groups:
            raise SensorError('Scene control group requires its earlier actual Trigger Control getter object')
        def execute():
            self._require_phase('core_neo_scenes')
            for commands in scenes:
                for address, _ in commands:
                    if (self.context.primary_application, address) not in self.groups:
                        raise SourceObjectRequired(self.context.primary_application, address, 'scene_table_getter')
            self.control_group = self.groups[identity]
            if not self.scenes:
                self.scenes = tuple(_Object('scene', value) for value in range(8))
            self.scene_commands = scenes
            self.scene_expected = {'SceneTable': list(table), 'SceneTablePointer': list(pointers),
                                   'PatchEnable': list(patch)}
            self.phase = 'get_key_values'
        return self._run(execute)

    def _add_scene(self, source):
        scene = _Scene(len(self.scene_collection.items), self._trace)
        self._event('source_scene_add', source=source, ordinal=len(self.scene_collection.items))
        self.scene_collection.append(scene)
        self.scenes = tuple(self.scene_collection.items)
        return scene

    def _read_current_pp(self, reader, name, fallback, source):
        value = deepcopy(fallback if reader is None else reader(name, source, self))
        self._event('parameter_read', name=name, source=source, value=deepcopy(value))
        return value

    def load_scenes_causal(self, table, pointers, patch, *, parameter_read=None):
        """Execute native Add/command/getter order on the SAME owning objects.

        The owner has already assigned ScenesEnabled and ControlAppGroup at
        their earlier native positions. No level or Scene group is prefetched.
        Patch disabled still executes this complete loader.
        """
        if parameter_read is not None and not callable(parameter_read):
            raise SensorError('CURRENT PP reader requires an internal callable executor')
        loaded_scenes(table, pointers)  # exact unsigned widths/count admission
        if (not isinstance(patch, (list, tuple)) or len(patch) != 2
                or any(type(value) is not int or not 0 <= value <= 255 for value in patch)):
            raise SensorError('PatchEnable requires two bytes')
        def execute():
            self._require_phase('core_neo_scenes')
            self._causal_scenes = True
            self.scene_collection.clear()
            self.scenes = ()
            raw = tuple(self._read_current_pp(parameter_read, 'SceneTable', table, '0xccafb1'))
            # Native pointer parsing is skipped entirely for an empty table.
            positions = tuple(pointers)
            if raw and raw[0] != 255:
                positions = tuple(self._read_current_pp(
                    parameter_read, 'SceneTablePointer', pointers, '0xccaff4'))
            loaded_scenes(raw, positions)
            if raw[0] != 255:
                scene = self._add_scene('0xccb01d')
                ordinal = 0
                for offset in range(0, 80, 2):
                    address, value = raw[offset:offset + 2]
                    found = False
                    if address != 255:
                        for index in range(len(scene.commands.items)):
                            current_group = scene.commands.items[index].group.value
                            if current_group is None:
                                raise SensorError('Native Scene duplicate lookup dereferences a nil command group')
                            if current_group.identity[1] == address:
                                found = True
                                break
                    if address != 255 and not found:
                        command = _SceneCommand(scene, len(scene.commands.items), self._trace)
                        scene.commands.append(command)
                        if len(scene.commands.items) > 40:
                            raise SensorError('Native Scene command manager exceeds forty commands')
                        self._event('source_scene_command_add', source='0xccb062',
                                    scene=ordinal, offset=offset)
                        application = self.primary_application.value
                        if application is None:
                            raise SensorError('Native Scene getter dereferences CURRENT nil primary application')
                        group = self.get_source_group(application, address, create=True, source='0xccb08e')
                        command.set_group(group)
                        command.set_level(value)
                    if ordinal < 7 and positions[ordinal + 1] == 162 + offset + 2:
                        ordinal += 1
                        scene = self._add_scene('0xccb0e8')
            while len(self.scene_collection.items) < 8:
                self._add_scene('0xccb117')
            if len(self.scene_collection.items) != 8:
                raise SensorError('Source Scene collection must contain eight objects after raw load')
            self.scenes = tuple(self.scene_collection.items)
            self.scene_commands = tuple(tuple((command.group._value.identity[1], command.level._value)
                                             for command in scene.commands.items) for scene in self.scenes)
            self.scene_expected = {'SceneTable': list(raw), 'SceneTablePointer': list(positions),
                                   'PatchEnable': list(patch)}
            self.phase = 'get_key_values'
        return self._run(execute)

    def load_key_values(self, stages, selector, indicator, *, parameter_read=None):
        if parameter_read is not None and not callable(parameter_read):
            raise SensorError('CURRENT PP reader requires an internal callable executor')
        if not isinstance(stages, (list, tuple)) or len(stages) != 8:
            raise SensorError('Key stages require eight four-nibble rows')
        if any(not isinstance(row, (list, tuple)) or len(row) != 4 for row in stages):
            raise SensorError('Each key stage row requires four nibbles')
        rows = tuple(tuple(_integer(value, 15, 'Key stage') for value in row) for row in stages)
        selectors = _eight(selector, 1, 'SceneKeySelector')
        indicators = _eight(indicator, 7, 'IndicatorBlockAssignment')
        raw_commands = {name: tuple(row[index] for row in rows)
                        for index, name in enumerate(('JPCommand','SRCommand','LPCommand','LRCommand'))}
        def current(name, key, source):
            maximum, fallback = ((1, selectors) if name == 'SceneKeySelector' else
                                  (7, indicators) if name == 'IndicatorBlockAssignment' else
                                  (15, raw_commands[name]))
            return _eight(self._read_current_pp(parameter_read, name, fallback, source),
                          maximum, name)[key]
        def execute():
            self._require_phase('get_key_values')
            for key in range(8):
                owner = self.keys[key]
                selected = current('SceneKeySelector', key, '0xcca5d1')
                if selected:
                    owner.scene_ramp_function.set(self.micro[current('JPCommand', key, '0xcca5ee')])
                    invoke = owner.scene_ramp_function.value is self.micro[14]
                    owner.template.set(self.templates[24 if invoke else 25])
                    if invoke:
                        raw_indicator = current('IndicatorBlockAssignment', key, '0xcca679')
                        owner.scene.set(self.scenes[raw_indicator])
                        control_group = self.control_group
                        if self._causal_control:
                            if control_group is not None:
                                low = current('LRCommand', key, '0xcca6e0')
                                high = current('LPCommand', key, '0xcca712')
                                trigger = high * 16 + low
                                current_group = self.control_group
                                if current_group is None:
                                    raise SensorError('Native Invoke getter dereferences CURRENT nil control group')
                                owner.scene_trigger.set(self.get_source_level(
                                    current_group, trigger, create=True, source='0xcca758'))
                        else:
                            low = current('LRCommand', key, '0xcca6e0')
                            high = current('LPCommand', key, '0xcca712')
                            trigger = high * 16 + low
                            level_identity = (*control_group.identity, trigger)
                            if level_identity not in self.levels:
                                raise SourceObjectRequired(level_identity[0], trigger, 'scene_trigger_getter',
                                                           kind='level', group=level_identity[1])
                            owner.scene_trigger.set(self.levels[level_identity])
                        owner.scene_rate.set(current('SRCommand', key, '0xcca77d'))
                        continue
                    # Modify assigns Scene1 here before loading raw macro
                    # stages, and again in the common final branch below.
                    owner.scene.set(self.scenes[0])
                else:
                    owner.template.set(self.templates[16])
                owner.macro_pin += 1
                try:
                    sources = (('0xcca81f','0xcca86a','0xcca8b5','0xcca900') if selected else
                               ('0xccaa07','0xccaa52','0xccaa9d','0xccaae8'))
                    for index, (name, source) in enumerate(zip(raw_commands, sources)):
                        value = current(name, key, source)
                        changed = list(owner.stages)
                        changed[index] = value
                        owner.stages = tuple(changed)
                finally:
                    owner.macro_pin -= 1
                self._raw_macro_refresh(key)
                raw_indicator = current('IndicatorBlockAssignment', key,
                                        '0xcca9a9' if selected else '0xccabcf')
                owner.indicator.set(raw_indicator + 1)
                owner.scene.set(self.scenes[0])
            self.phase = 'fresh_function_bindings'
        return self._run(execute)

    def fresh_function_bindings(self):
        def execute():
            self._require_phase('fresh_function_bindings')
            for key in range(8):
                if self._template_type(key) not in _SUBSET:
                    self.keys[key].template.set(self.templates[16])
            self.phase = 'm8_hooks'
        return self._run(execute)

    def _recall_hook(self, key):
        template = self._template_type(key)
        category = next((row for row in _RECALL if template in row), None)
        if category is None:
            return
        group = self.keys[key].primary_group.value
        changed = False
        for other in range(8):
            if (other != key and self.keys[other].primary_group.value is group
                    and self._template_type(other) in (17, 18, 19, 20, 21, 22)
                    and self._template_type(other) not in category):
                self.keys[other].template.set(self.templates[16])
                changed = True
        if changed:
            self._event('recall_conflict_warning', key=key, warning=0x1ca2)

    def _general_key_hook(self, key):
        # The empty-expression Key link is CL=false. Inherited model writes
        # refresh b1/subset without Changed; the SENLLA subset cannot retain
        # the paired29/30 b1 predicate. Native root/list/control work still
        # runs and may recursively invoke actual setters before recall.
        request = KeyControlRequest(key)
        self._event('general_key_control_request', request=request.as_dict())
        if self.control_dispatch is None:
            raise SourceControlRequired(request)
        result = self.control_dispatch(request, self)
        if result is not None:
            raise SensorError('Native control dispatcher must return after executing its actual callbacks')
        self._recall_hook(key)

    def install_m8_hooks(self, *, control_dispatch=None):
        if control_dispatch is not None and not callable(control_dispatch):
            raise SensorError('Native control dispatcher requires an internal callable executor')
        def execute():
            self._require_phase('m8_hooks')
            self.control_dispatch = control_dispatch
            for key, owner in enumerate(self.keys):
                owner.general_hook = lambda _, key=key: self._general_key_hook(key)
                owner.object.publisher.subscribe(owner.general_hook)
                # SetActive immediately delivers the nonnil current Key.
                self._general_key_hook(key)
                owner.function_hook = TrackedReferenceHandle(owner.template, lambda _, key=key: self._recall_hook(key))
                owner.function_hook.activate()
            self.hooks_installed = True
            # M8 binds the unit's group-creation decision after all hook
            # activations. ST7 macro/event decisions are installed later.
            self.group_decision_handler_installed = True
            self.phase = 'component_complete'
        return self._run(execute)

    def set_secondary(self, block, value):
        _integer(block, 7, 'Block index')
        return self._run(lambda: self.blocks[block].secondary.set(value))

    def set_template(self, key, template):
        _integer(key, 7, 'Key index')
        _integer(template, 58, 'Macro template')
        if template not in _DEFAULTS:
            raise SensorError('Template assignment is outside the source-bound key dispatcher')
        return self._run(lambda: self.keys[key].template.set(self.templates[template]))

    def set_broadcast_block(self, block):
        if block is not None:
            _integer(block, 7, 'Broadcast block')
        return self._run(lambda: self.broadcast_block.set(
            self.blocks[block].object if block is not None else None))

    def set_broadcast_active(self, value):
        return self._run(lambda: self.broadcast_active.set(value))

    def set_label_flavour(self, key, value):
        _integer(key, 7, 'Key index')
        if type(value) is not int or not 1 <= value <= 4:
            raise SensorError('Logical LabelFlavour requires integer 1..4')
        return self._run(lambda: self.keys[key].label_flavour.set(value - 1))

    def set_group(self, block, identity):
        _integer(block, 7, 'Block index')
        identity = _group(identity)
        if identity not in self.groups:
            raise SensorError('Explicit group assignment requires an actual existing group object')
        return self._run(lambda: self.blocks[block].group.set(self.groups[identity]))

    def bind_context(self, context):
        """Bind facts established by a later owning getter or control phase.

        Existing canonical objects retain identity. This does not dispatch a
        hidden group, Join, or maintenance callback. The owner must execute
        those actual setters separately at their source positions.
        """
        if not isinstance(context, KeyEventContext):
            raise SensorError('Context binding requires source-established KeyEventContext')
        if self.context is None:
            raise SensorError('Context binding requires the completed SAME-object GetKeyBlocks handoff')
        if (context.primary_application, context.secondary_application) != (
                self.context.primary_application, self.context.secondary_application):
            raise SensorError('Application reference changes require their owning setter route')
        if (not set(self.apps).issubset(context.application_addresses)
                or not set(self.groups).issubset(context.group_identities)
                or not set(self.levels).issubset(context.trigger_levels)):
            raise SensorError('Context binding cannot discard existing canonical objects')
        def execute():
            for identity in context.application_addresses:
                if identity not in self.apps:
                    self.add_source_application(identity)
            for identity in context.group_identities:
                if identity not in self.groups:
                    self.add_source_group(self.apps[identity[0]], identity[1])
            for identity in context.trigger_levels:
                if identity not in self.levels:
                    self.levels[identity] = _Level(identity, identity[2], self._trace)
            self.context = context
            self._event('owning_context_bound')
        return self._run(execute)

    def adopt_bank_graph(self, graph):
        """Adopt already-executed owning bank/occupancy/maintenance events.

        Ordered references must match the live key objects. Changed stored
        bytes use the native bank-owned feedback suppression; this operation
        never invents occupancy or aggregate Allowed refresh events.
        """
        if self.context is None:
            raise SensorError('Fresh prekey loading cannot adopt a detached bank graph')
        if not isinstance(graph, SENLLABankGraph):
            raise SensorError('Bank adoption requires the owning SENLLABankGraph')
        if graph.references.ordered_references != tuple(tuple(key.refs) for key in self.keys):
            raise SensorError('Adopted bank graph must retain current ordered key references')
        def execute():
            self.graph = graph
            self._event('owning_bank_graph_adopted')
            self._bank_feedback_writes()
        return self._run(execute)

    def parameters(self, *, parameter_dispatch=None, corekey_light_level=None, core_neo_prefix=None):
        """Replay private key/block marshalling, including Invoke nil getter.

        This native save component can assign an existing trigger255 object.
        Missing creation or a nested callback invalidates an interrupted
        runtime; the caller cannot treat projection as a passive snapshot.
        """
        for callback in (parameter_dispatch, corekey_light_level, core_neo_prefix):
            if callback is not None and not callable(callback):
                raise SensorError('Native save-position executors require internal callables')
        return self._run(lambda: self._parameters(parameter_dispatch, corekey_light_level, core_neo_prefix))

    def _write_parameter(self, dispatch, name, value, source, *, operation='assign', index=None):
        if dispatch is not None:
            request = ParameterWriteRequest(name, deepcopy(value), source, operation, index)
            self._event('parameter_write_request', request=request.as_dict())
            if dispatch(request, self) is not None:
                raise SensorError('PP write executor must finish its native cached assignment before returning')

    def _scene_compatible(self):
        # IsSceneLearnCompatible reads command-manager counts only. In
        # particular, pointer output must not resolve Group references merely
        # to determine whether a Scene is empty.
        counts = [len(scene.commands.items) for scene in self.scene_collection.items]
        return sum(count > 0 for count in counts) <= 4 and max(counts, default=0) <= 10

    def _scene_table(self):
        table, cursor, nonempty = [255] * 80, 0, 0
        # The outer count and each command count are captured at their source
        # loop entries. Every GetItem/Group read within those loops remains
        # CURRENT, after the preceding getter's possible nested work.
        for scene_index in range(len(self.scene_collection.items)):
            if not self.scene_collection.items[scene_index].commands.items:
                continue
            if self._scene_compatible():
                cursor = nonempty * 20
            nonempty += 1
            count = len(self.scene_collection.items[scene_index].commands.items)
            for command_index in range(count):
                if cursor + 2 > 80:
                    raise SensorError('Native Scene table exceeds forty commands')
                command = self.scene_collection.items[scene_index].commands.items[command_index]
                group = command.group.value
                if group is None:
                    address = 255
                else:
                    group = self.scene_collection.items[scene_index].commands.items[command_index].group.value
                    if group is None:
                        raise SensorError('Native Scene table dereferences CURRENT nil command group')
                    address = group.identity[1]
                level = self.scene_collection.items[scene_index].commands.items[command_index].level.value
                table[cursor:cursor + 2] = [address, level]
                cursor += 2
        return table

    def _scene_pointers(self):
        pointers = [162, 255, 255, 255, 255, 255, 255, 255]
        if self._scene_compatible():
            pointers[1:4] = [182, 202, 222]
        else:
            count = len(self.scene_collection.items)
            if count > 8:
                raise SensorError('Native Scene pointer array requires at most eight Scenes')
            for index in range(1, count):
                if not self.scene_collection.items[index].commands.items:
                    break
                pointers[index] = pointers[index - 1] + 2 * len(
                    self.scene_collection.items[index - 1].commands.items)
        return pointers

    def _parameters(self, dispatch=None, corekey_light_level=None, core_neo_prefix=None):
        if self.failed:
            raise SensorError('An interrupted callback runtime has no save projection')
        if self.phase != 'component_complete':
            raise SensorError('Key projection requires the complete admitted component lifecycle')
        # CoreKey has already marshalled allocations and block scalars before
        # CoreNeo starts its Scene/key output. Do not retroactively reread
        # these PP fields after a nil-trigger setter's nested callbacks.
        result = {'BlockAllocation': [sum(1 << block for block in owner.refs) for owner in self.keys]}
        self._write_parameter(dispatch, 'BlockAllocation', result['BlockAllocation'], '0xcc8bf8')
        result['GroupAddress'] = [block.group.value.identity[1] if block.group.value is not None else 255
                                  for block in self.blocks]
        self._write_parameter(dispatch, 'GroupAddress', result['GroupAddress'], '0xcc8d1c')
        if corekey_light_level is not None and corekey_light_level(self) is not None:
            raise SensorError('CoreKey LightLevel owner must finish its capture before returning')
        # Each field is read at its native assignment, after the preceding
        # cache callback, rather than all being sampled before the first write.
        for name, values, source in (
                ('LightLevelStore1', lambda: [block.store1.value for block in self.blocks], '0xcc8f7b'),
                ('LightLevelStore2', lambda: [block.store2.value for block in self.blocks], '0xcc8fad'),
                ('TimerHighByte', lambda: [block.timer.value >> 8 for block in self.blocks], '0xcc8827'),
                ('TimerLowByte', lambda: [block.timer.value & 255 for block in self.blocks], '0xcc8853'),
                ('TimerExpiryCommand', lambda: [(block.expiry_override.value or block.expiry.value).identity
                    if block.expiry_override.value or block.expiry.value else 0 for block in self.blocks],
                 '0xcc88d1')):
            result[name] = values()
            self._write_parameter(dispatch, name, result[name], source)
        self._event('corekey_save_capture')
        if core_neo_prefix is not None and core_neo_prefix(self) is not None:
            raise SensorError('CoreNeo prefix owner must finish its captures before returning')
        if self._causal_scenes and self.scenes_enabled.value:
            result['SceneTable'] = self._scene_table()
            self._write_parameter(dispatch, 'SceneTable', result['SceneTable'], '0xccc703')
            result['SceneTablePointer'] = self._scene_pointers()
            self._write_parameter(dispatch, 'SceneTablePointer', result['SceneTablePointer'], '0xccc731')
        elif not self._causal_scenes and self.scene_expected is not None:
            result.update(scene_save_parameters(self.scene_expected))
            for name in ('SceneTable', 'SceneTablePointer'):
                if name in result:
                    self._write_parameter(dispatch, name, result[name], 'CoreNeo.' + name)
        self._event('core_neo_scene_save_capture')
        selectors, indicators, rows = [], [], []
        for key, owner in enumerate(self.keys):
            template = self._template_type(key)
            selectors.append(int(template in (23, 24, 25)))
            if template in (23, 24):
                # The native branch is captured before the create-enabled
                # nil-trigger getter/setter. Nested controls can change the
                # current template; marshalling still finishes Invoke here.
                if owner.scene_trigger.value is None:
                    group = self.control_group
                    if group is None:
                        raise SensorError('Native Invoke save dereferences CURRENT nil ControlAppGroup')
                    if self._causal_control:
                        owner.scene_trigger.set(self.get_source_level(group, 255, create=True, source='0xccb917'))
                    else:
                        identity = (*group.identity, 255)
                        if identity not in self.levels:
                            raise SourceObjectRequired(identity[0], 255, 'scene_trigger_before_save_getter',
                                                       kind='level', group=identity[1])
                        owner.scene_trigger.set(self.levels[identity])
                self._write_parameter(dispatch, 'SceneKeySelector', 1, '0xccb93f', operation='index', index=key)
                scene = owner.scene.value
                ordinal = (self.scene_collection.items.index(scene) if self._causal_scenes and scene in self.scene_collection.items
                           else scene.identity if scene is not None and not self._causal_scenes else 0)
                ordinal = ordinal if 0 <= ordinal <= 7 else 0
                indicators.append(ordinal)
                self._write_parameter(dispatch, 'IndicatorBlockAssignment', ordinal, '0xccb98f', operation='index', index=key)
                row = [14]
                self._write_parameter(dispatch, 'JPCommand', 14, '0xccb9a6', operation='append')
                row.append(owner.scene_rate.value & 127)
                self._write_parameter(dispatch, 'SRCommand', row[-1], '0xccb9d4', operation='append')
                for name, shift, source in (('LPCommand', 4, '0xccba09'), ('LRCommand', 0, '0xccba3e')):
                    trigger = owner.scene_trigger.value
                    if trigger is None:
                        raise SensorError('Native Invoke serializer dereferences current trigger after its getter')
                    row.append((trigger.identity[2] >> shift) & 15)
                    self._write_parameter(dispatch, name, row[-1], source, operation='append')
                rows.append(tuple(row))
            else:
                self._write_parameter(dispatch, 'SceneKeySelector', int(template == 25),
                                      '0xccba6d' if template == 25 else '0xccbb97', operation='index', index=key)
                indicators.append(owner.indicator.value - 1)
                self._write_parameter(dispatch, 'IndicatorBlockAssignment', indicators[-1],
                                      '0xccbbce', operation='index', index=key)
                row = []
                for index, name in enumerate(('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand')):
                    value = owner.stages[index]
                    if value is None:
                        raise SensorError('Native ordinary serializer requires its current microfunction object')
                    row.append(value & 127)
                    self._write_parameter(dispatch, name, row[-1], 'CoreNeo.AttribAppend.' + name, operation='append')
                rows.append(tuple(row))
        result.update({name: [row[index] for row in rows] for index, name in enumerate(
                  ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand'))})
        result.update(SceneKeySelector=selectors, IndicatorBlockAssignment=indicators)
        # This overlay belongs to CoreNeoPro, after inherited CoreNeo key
        # marshalling. It deliberately reads the current post-callback mask.
        result['SecondApplicationBlocks'] = [sum(1 << index for index, block in enumerate(self.blocks)
                                                if block.secondary.value)]
        self._write_parameter(dispatch, 'SecondApplicationBlocks', result['SecondApplicationBlocks'], '0xced7c7')
        return result

    def block_values(self):
        """Detached current block data for CoreKey's indexed LightLevel rebuild.

        The root owner rebuilds PP around its actual current LightLevelIndex,
        including source prefix/tail255 and any native array growth. Later
        global/power phases overlay that current array. This method returns
        no short PP LightLevel array that could imply the complete parameter.
        """
        if self.failed:
            raise SensorError('An interrupted callback runtime has no block projection')
        if any(block.group._value is None for block in self.blocks):
            raise SensorError('Source-loaded block projection requires actual current group objects')
        return tuple(BlockValues(
            block.secondary._value, block.group._value.identity,
            block.light_level._value, block.store1._value, block.store2._value,
            block.timer._value, block.timer_cached._value,
            block.expiry._value.identity if block.expiry._value is not None else None,
            block.expiry_override._value.identity if block.expiry_override._value is not None else None)
            for block in self.blocks)

    def snapshot(self):
        # Inspection must not invoke native value getters: those rearm managed
        # publication and would change subsequent callback admission.
        def value(attribute):
            raw = attribute._value
            return raw.identity if isinstance(raw, _Object) else raw

        return {'phase': self.phase, 'failed': self.failed,
            'unit_depth': self.unit.depth,
            'keys': [dict(template=value(owner.template), macro_type=owner.macro_type,
                          stages=list(owner.stages), references=list(owner.refs),
                          primary_group=value(owner.primary_group),
                          application=value(owner.application),
                          application_state=value(owner.application_state),
                          indicator_block_number=value(owner._indicator._value),
                          scene=value(owner._scene), scene_rate=value(owner._scene_rate),
                          scene_trigger=(owner._scene_trigger._value.identity[2]
                                         if owner._scene_trigger._value is not None else None),
                          scene_ramp_function=value(owner._scene_ramp_function),
                          scene_ramp_template=value(owner._scene_ramp_template),
                          label_flavour=owner._label_flavour._value + 1,
                          scene_learning=owner.scene_learning,
                          update_depth=owner.object.depth)
                     for index, owner in enumerate(self.keys)],
            'blocks': [dict(index=index, update_depth=block.object.depth,
                           application=value(block.application),
                           **{field: value(getattr(block, field)) for field in _BLOCK_FIELDS})
                       for index, block in enumerate(self.blocks)],
            'primary_application': value(self.primary_application),
            'secondary_application': value(self.secondary_application),
            'area': value(self.area),
            'bank_graph': self.graph.as_dict(), 'created_groups': [list(value) for value in self.created_groups],
            'events': deepcopy(self.events)}


__all__ = ['BlockValues', 'KeyEventContext', 'KeyControlRequest', 'SENLLAKeyEvents',
           'SourceControlRequired', 'SourceLookupRequest', 'SourceLevelRequest',
           'ParameterWriteRequest', 'SourceObjectRequired']
