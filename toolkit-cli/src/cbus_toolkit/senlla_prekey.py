"""Internal SENLLA fresh prekey loading on the owning key engine's objects.

Canonical metadata and inherited agent work are synchronous executor
boundaries. This component owns the fresh application/Area callbacks and the
ordered block setters; it neither programs a unit nor completes a 93-field save.
"""
from dataclasses import dataclass
from copy import deepcopy

from .senlla_block_values import block_load_plan, current_light_levels, TIMER_EXPIRY_TYPES
from .senlla_inputs import SENLLAInputSnapshot, SCHEMA, _value
from .senlla_key_events import SENLLAKeyEvents, _SUBSET
from .senlla_lifecycle import IntegerAttribute
from .sensors import SensorError


@dataclass(frozen=True)
class PrekeyOwnerRequest:
    """Inherited native work that the actual unit owner executes in place.

The executor receives this request and the live SENLLAPrekey, reads the bound
raw snapshot and current objects, and returns after any nested callbacks. No
future context, detached object graph or parameter projection is a response.
"""
    operation: str
    source: str
    parameters: tuple = ()

    def as_dict(self):
        return dict(operation=self.operation, source=self.source,
                    parameters=list(self.parameters))


class PrekeyOwnerRequired(SensorError):
    def __init__(self, request):
        self._request = request
        super().__init__('Fresh SENLLA loading requires the inherited owning executor')

    @property
    def request(self):
        return self._request.as_dict()


class SENLLAPrekey:
    """A private live prefix from fresh constructor to GetKeyBlocks.

source_dispatch(request, engine) resolves an actual application/group getter
against the source manager and registers the canonical identity on that SAME
engine only after the lookup/creation/storage route finishes. inherited_dispatch
(request, prekey) executes the inherited base agent, metadata, Learn and scalar
branches at their pinned positions. Both contracts are internal owner boundaries,
not JSON declarations or simulated proof of native backend persistence.
"""
    def __init__(self, snapshot, *, source_dispatch=None, inherited_dispatch=None,
                 parameter_read=None):
        if not isinstance(snapshot, SENLLAInputSnapshot):
            raise SensorError('Fresh prekey loading requires the complete guarded SENLLA snapshot')
        self.raw = SENLLAInputSnapshot(snapshot.identity, snapshot.expected)
        primary, secondary = self.raw.expected['Application']
        if not 48 <= primary <= 95 or not (48 <= secondary <= 95 or secondary == 255):
            raise SensorError('Fresh prekey source profile requires primary Lighting and secondary Lighting or actual255')
        if source_dispatch is not None and not callable(source_dispatch):
            raise SensorError('Source getter dispatcher must be callable')
        if inherited_dispatch is not None and not callable(inherited_dispatch):
            raise SensorError('Inherited owner dispatcher must be callable')
        if parameter_read is not None and not callable(parameter_read):
            raise SensorError('Current prekey parameter reader must be callable')
        self.inherited_dispatch = inherited_dispatch
        self.parameter_read = parameter_read
        self.plan = block_load_plan(self.raw)
        self.initialized = False  # Unit.Init field194; independent of state1.
        self.saving = False       # Native Unit fielddf, not the update counter.
        self._primary_refreshing = False  # Native CoreKey field208.
        self.light_index = 0
        self.loaded_light_count = 0
        self.requests = []
        self.runtime = SENLLAKeyEvents.fresh(
            source_dispatch=source_dispatch,
            application_dispatch=self._application_changed)
        self.status_report_interval = IntegerAttribute(
            self.runtime.unit_manager, 0, name='unit.status_report_interval',
            trace=self.runtime._trace)

    def _read(self, name, source):
        value = (self.parameter_read(name, source, self.runtime)
                 if self.parameter_read is not None else self.raw.expected[name])
        if SCHEMA[name][0] != 'sixbit' and (not isinstance(value, (list, tuple))
                or any(type(item) is not int for item in value)):
            raise SensorError('Current prekey PP requires exact unsigned integers: ' + name)
        current = current_light_levels(value) if name == 'LightLevel' else _value(name, value)
        self.runtime._event('prekey_parameter_read', field=name, source=source,
                            value=deepcopy(current))
        return current

    def _owner(self, request):
        self.requests.append(request.as_dict())
        self.runtime._event('prekey_owner_request', request=request.as_dict())
        if self.inherited_dispatch is None:
            raise PrekeyOwnerRequired(request)
        if self.inherited_dispatch(request, self) is not None:
            raise SensorError('Inherited dispatcher must finish actual work before returning')

    def _area_refresh(self):
        engine = self.runtime
        app = engine.application_object()
        if not engine.unit.enabled or app is None:
            return
        current = engine.area.value
        address = current.identity[1] if current is not None else 255
        group = engine.get_source_group(app, address, create=True,
                                       source='0xc9d566')
        engine.area.set(group)

    def _types_refresh(self, secondary):
        engine = self.runtime
        app = engine.application_object(secondary)
        if secondary and (app is None or app.identity == 255):
            for block in engine.blocks:
                if block.secondary.value:
                    block.secondary.set(False)
            return
        # c9f329 captures the application object once; each matching predicate
        # is read after the preceding setter and its nested callbacks.
        for block in engine.blocks:
            if block.secondary.value == secondary:
                block.application.set(app)
        for key in engine.keys:
            if key.application_state.value == int(secondary):
                key.application.set(app)
        for block in engine.blocks:
            block.object.resolve_change()
            block.object.changed()
        for key in engine.keys:
            key.object.resolve_change()
            key.object.changed()

    def _groups_and_macros_refresh(self, secondary):
        engine = self.runtime
        app = engine.application_object(secondary)
        # Fresh Neo command managers and protected/Surface refs are still nil.
        # Their later getters are outside this prefix. Lighting CanAddGroups is
        # true; actual block-app setters have established all matching groups.
        if any(engine.scene_commands):
            raise SensorError('Fresh prekey group refresh requires the not-yet-loaded Scene managers')
        if app is not None and app.identity != 255:
            for block in engine.blocks:
                if block.secondary.value != secondary:
                    continue
                current_app, group = block.application.value, block.group.value
                if current_app is None:
                    raise SensorError('Native prekey group check dereferences a nil application')
                address = group.identity[1] if group is not None else 255
                if engine.get_source_group(current_app, address, create=False,
                                           source='CoreKey.CheckGroups') is None:
                    raise SensorError('Fresh prekey group check needs the owning group decision branch')
        elif any(key.application_state.value in (1, 2) for key in engine.keys):
            raise SensorError('Unused-app fresh group branch requires its nonfresh owning dispatcher')
        engine._event('prekey_application_group_refresh_qualified_noop', secondary=secondary)
        for index, key in enumerate(engine.keys):
            if key.application_state.value != int(secondary):
                continue
            template = engine._template_type(index)
            if template is not None and template not in _SUBSET:
                key.template.set(engine.templates[16])
        # RefreshOtherApplication's primary255 predicate is false for this
        # source profile. Secondary invocation does not enter that branch.

    def _application_changed(self, engine, secondary):
        if engine is not self.runtime:
            raise SensorError('Application callback belongs to another owning runtime')
        # Inherited InputUnit primary Area work precedes CoreKey's saving and
        # recursion guards. Unit.GetUpdating is deliberately not a guard.
        if not secondary:
            self._area_refresh()
        app = engine.application_object(secondary)
        if not engine.unit.enabled or app is None or self.saving:
            return
        if not secondary and self._primary_refreshing:
            return
        if not secondary:
            self._primary_refreshing = True
        try:
            self._types_refresh(secondary)
            self._groups_and_macros_refresh(secondary)
        finally:
            if not secondary:
                self._primary_refreshing = False

    def _block_request(self, request):
        engine = self.runtime
        self.requests.append(request.as_dict())
        engine._event('prekey_block_request', request=request.as_dict())
        if request.field == 'light_index':
            self.light_index = request.value
            return
        if request.field == 'loaded_light_count':
            self.loaded_light_count = request.value
            return
        block = engine.blocks[request.block]
        if request.operation == 'get_indexed_level_and_set':
            current_index = self.light_index
            levels = self._read('LightLevel', '0xcc8230')
            index = current_index + request.block
            value = levels[index] if index < len(levels) else 0
            engine._event('prekey_current_indexed_level', block=request.block,
                          light_index=current_index, value=value, source=request.source)
            block.light_level.set(value)
        elif request.operation == 'set_microfunction':
            block.expiry.set(engine.micro[request.value])
        elif request.operation == 'check_expiry':
            # Read CURRENT pointer after its setter publication. Canonical0 is
            # a real object. Actual nil is a native error at this boundary.
            current = block.expiry.value
            if current is None:
                raise SensorError('Native expiry membership dereferences a nil microfunction')
            engine._event('prekey_current_expiry_membership', block=request.block,
                          value=current.identity, source=request.source)
            if current.identity not in TIMER_EXPIRY_TYPES:
                block.expiry.set(engine.micro[15])
        elif request.operation == 'get_group':
            if block.secondary.value:
                app = engine.application_object(True)
                if app is not None:
                    app = engine.application_object(True)
            else:
                app = block.application.value
                if app is None:
                    raise SensorError('Native primary block group getter dereferences nil application')
            group = (None if app is None else engine.get_source_group(
                app, request.value, create=True, source=request.source))
            engine._event('prekey_current_group_getter', block=request.block,
                          application=app.identity if app is not None else None,
                          value=group.identity if group is not None else None,
                          source=request.source)
            block.group.set(group)
        else:
            getattr(block, request.field).set(request.value)

    def load_to_key_blocks(self):
        """Execute the fresh source prefix once and return its SAME runtime.

Success leaves CoreKey's outer Unit update active at depth1. load_allocations
then finish_corekey_application_refresh consume that same counter. A failed
prefix executes CoreKey's UnitEnd/application-refresh finally and invalidates
the runtime; no partial projection or automatic replay is admitted.
"""
        engine = self.runtime
        def execute():
            engine._require_phase('fresh_constructor')
            engine.phase = 'prekey_load'
            engine.unit.begin_update()
            handed_off = False
            try:
                self._owner(PrekeyOwnerRequest('base_agent_after_load', '0xcbe66d'))
                self.initialized = True
                engine._event('unit_init', source='0xcbe67c')
                engine.unit.begin_update()
                try:
                    for secondary, source in ((False, '0xcbe6a1'), (True, '0xcbe6bb')):
                        if not secondary:
                            # Native primary getter tests the string, then
                            # reads it again for parsing. Guarded input is
                            # nonempty; the empty-default route is excluded.
                            self._read('Application', '0xcb80bc')
                        raw = self._read('Application',
                                         '0xcb830b' if secondary else '0xcb80f1')[int(secondary)]
                        if not (48 <= raw <= 95 or secondary and raw == 255):
                            raise SensorError('Current application is outside the source Lighting profile')
                        app = engine.get_source_application(raw, create=True, source=source)
                        attribute = engine.secondary_application if secondary else engine.primary_application
                        attribute.set(app)
                finally:
                    engine.unit.end_update()
                self._owner(PrekeyOwnerRequest('unit_metadata_after_applications', '0xcbe6f2',
                                               ('Project', 'UnitName')))
                self._owner(PrekeyOwnerRequest('learn_after_inherited_unit', '0xcc5d43',
                                               ('LearnMode', 'LearnAnyApp', 'LearnedFlag')))
                primary = engine.application_object()
                if primary is None:
                    raise SensorError('Native raw Area getter dereferences a nil primary application')
                group = engine.get_source_group(primary, self._read('AreaGroupAddress', '0xcc6717')[0],
                                                create=True, source='0xcc66de')
                engine.area.set(group)
                self.status_report_interval.set(self._read('StatusReportInterval', '0xcc674a')[0])
                self._owner(PrekeyOwnerRequest('core_scalars_before_blocks', '0xcc861f',
                    ('DebounceTime', 'LongPressTime', 'EEPROMLevelStore', 'EEPROMCheckSumActive',
                     'EEPROMChecksumAlarm', 'RampRate', 'IRBank', 'DisableIR', 'DisableIRNEC')))
                for request in self.plan.current_requests(self._read):
                    self._block_request(request)
                engine.handoff_to_key_blocks()
                handed_off = True
                return engine
            finally:
                if not handed_off:
                    engine.unit.end_update()
                    for secondary in (False, True):
                        self._types_refresh(secondary)
                        self._groups_and_macros_refresh(secondary)
        return engine._run(execute)

    def snapshot(self):
        """Detached inspection does not invoke live native value getters."""
        return dict(format='cbus-senlla-prekey-v1', identity=list(self.raw.identity),
                    expected=self.raw.parameters(), initialized=self.initialized,
                    light_index=self.light_index, loaded_light_count=self.loaded_light_count,
                    status_report_interval=self.status_report_interval._value,
                    runtime=self.runtime.snapshot(), requests=deepcopy(self.requests),
                    complete_toolkit_save=False, saved=False,
                    original_execution=False, physical_acceptance=False)


__all__ = ['PrekeyOwnerRequest', 'PrekeyOwnerRequired', 'SENLLAPrekey']
