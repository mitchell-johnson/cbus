"""Pure Project phases and separately issued Global factory preparation.

Original Project token/backing/dirty semantics are separate from physical
encoding. The partial methods remain partial. The bounded factory composition
uses an issued Reset dependency and never performs I/O or physical programming.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Mapping
import weakref

from .edlt import EdltError, EdltLighting
from .edlt_global_programming import CATEGORIES

_PATH = re.compile(r'//([A-Za-z][A-Za-z0-9_]{0,7})/(0|[1-9][0-9]{0,2})/p/(0|[1-9][0-9]{0,2})')
_PROJECT = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,7}')


def _text(value, name, maximum=256):
    if type(value) is not str or len(value) > maximum or any(not 32 <= ord(c) <= 126 for c in value):
        raise EdltError(name + ' must be bounded printable ASCII text')
    return value


def _token(value):
    if value == '0xffffffff': return '0xff'
    if value.startswith('$x'): return '0' + value[1:]
    if value.startswith('$'): return '0x' + value[1:].upper()
    return value


def _join(tokens):
    value = ''
    for token in tokens:
        if value: value += ' '
        value += token
    return value


@dataclass(frozen=True)
class ProjectState:
    """An original model sidecar, including absent PP and private backing text."""
    tokens: tuple[str, ...] | None
    backing: str = ''
    dirty: bool = False
    initializing: bool = False

    def __post_init__(self):
        _text(self.backing, 'Backing Project')
        if type(self.dirty) is not bool or type(self.initializing) is not bool:
            raise EdltError('Project dirty/initializing flags must be exact booleans')
        if self.tokens is None:
            if self.dirty: raise EdltError('An absent Project parameter cannot have a dirty flag')
        elif (type(self.tokens) is not tuple or not 1 <= len(self.tokens) <= 64 or
              any(type(token) is not str or ' ' in token for token in self.tokens)):
            raise EdltError('Project tokens must be a bounded exact tuple without embedded spaces')
        else:
            for token in self.tokens: _text(token, 'Project token')
            if sum(map(len, self.tokens)) > 4096: raise EdltError('Project token state exceeds its bound')

    @classmethod
    def from_raw(cls, raw, *, backing='', dirty=False, initializing=False):
        if cls is not ProjectState: raise EdltError('Use the exact ProjectState type')
        if raw is None: return cls(None, backing, dirty, initializing)
        _text(raw, 'Raw Project', 4096)
        return cls(tuple(_token(part) for part in raw.split(' ')), backing, dirty, initializing)

    @property
    def value(self):
        return self.backing if self.tokens is None else _join(self.tokens)

    def as_dict(self):
        return {'tokens':None if self.tokens is None else list(self.tokens), 'value':self.value,
            'backing':self.backing, 'dirty':self.dirty, 'initializing':self.initializing,
            'physical_encoding_verified':False}


def _state(value):
    if type(value) is not ProjectState: raise EdltError('Use an exact ProjectState')
    value.__post_init__()
    return value


@dataclass(frozen=True)
class ProjectAssignment:
    before: ProjectState
    after: ProjectState
    notification_states: tuple[ProjectState, ...]
    setter_called: bool

    def as_dict(self):
        return {'before':self.before.as_dict(), 'after':self.after.as_dict(),
            'notification_states':[state.as_dict() for state in self.notification_states],
            'setter_called':self.setter_called,
            'notifications_executed':False, 'model_assignment_only':True}


def assign_project(state: ProjectState, value: str) -> ProjectAssignment:
    """Model exact positional writes; record pre-notification states, no callbacks.

    A failing original notification can leave the corresponding intermediate
    state without the final private backing assignment. No callback is run here.
    """
    state = _state(state); _text(value, 'Assigned Project')
    tokens = None if state.tokens is None else list(state.tokens)
    dirty = state.dirty; notifications = []
    if tokens is not None:
        for index, token in enumerate(value.split(' ')):
            token = _token(token)
            changed = index >= len(tokens) or tokens[index] != token
            if index < len(tokens): tokens[index] = token
            else: tokens.append(token)
            if changed and not state.initializing:
                dirty = True
                notifications.append(ProjectState(tuple(tokens), state.backing, dirty, state.initializing))
    after = ProjectState(None if tokens is None else tuple(tokens), value, dirty, state.initializing)
    return ProjectAssignment(state, after, tuple(notifications), True)


def initialize_project(state: ProjectState, form_project: str) -> ProjectAssignment:
    """Original SetEDLTFrm conditional only; no form binding or Reset implied."""
    state = _state(state); _text(form_project, 'Form Project')
    if state.value: return ProjectAssignment(state, state, (), False)
    return assign_project(state, form_project)


@dataclass(frozen=True)
class GlobalPreparationContext:
    source: str
    form_project: str
    cached_network_project: str

    def __post_init__(self):
        match = _PATH.fullmatch(self.source) if type(self.source) is str else None
        if not match or any(int(match[index]) > 255 for index in (2,3)):
            raise EdltError('Source must be a canonical full project/network/unit database path')
        for value in (self.form_project, self.cached_network_project):
            if type(value) is not str or not _PROJECT.fullmatch(value):
                raise EdltError('Explicit form/cached project names require one to eight letters, digits or underscore, starting with a letter')

    def as_dict(self):
        source_project, network, unit = _PATH.fullmatch(self.source).groups()
        return {'source':self.source, 'source_project':source_project, 'source_network':int(network),
            'source_unit':int(unit), 'form_project':self.form_project,
            'cached_network_project':self.cached_network_project,
            'cached_project_differs_from_source':self.cached_network_project != source_project}


class _Origin:
    def __init__(self, owner): self.owner, self.reference = owner, None


@dataclass(frozen=True)
class GlobalPreparation:
    expected_raw: Mapping
    raw: Mapping
    context: GlobalPreparationContext
    project: ProjectState
    dirty_parameters: tuple[str, ...]
    parameter_order: tuple[str, ...]
    stages: tuple[str, ...]
    project_assignments: tuple[ProjectAssignment, ...]
    destination: str | None
    forced_parameters: tuple[str, ...]
    _origin: _Origin = field(repr=False, compare=False)

    def __post_init__(self):
        for name in ('expected_raw','raw'):
            object.__setattr__(self,name,MappingProxyType(dict(getattr(self,name))))

    def as_dict(self):
        return {'format':'cbus-edlt-global-preparation-partial-v1', 'unit_type':'KEYGL5',
            'catalog_number':'5055EDL','firmware':'5.5.00', 'expected_raw':dict(self.expected_raw),
            'raw_model_projection':dict(self.raw), 'context':self.context.as_dict(),
            'project':self.project.as_dict(), 'dirty_parameters':list(self.dirty_parameters),
            'parameter_order':list(self.parameter_order), 'stages':list(self.stages),
            'project_assignments':[item.as_dict() for item in self.project_assignments],
            'destination':self.destination, 'forced_parameters':list(self.forced_parameters),
            'forced_parameters_are_membership_only':True, 'wire_order_verified':False,
            'source_preparation_complete':False, 'initial_factory_binding_applied':False,
            'reset_applied':False, 'before_save_applied':False, 'global_bridge_enabled':False,
            'raw_model_physically_encodable_verified':False, 'saved':False,
            'physical_device_verified':False, 'export_is_review_only':True}


class EdltGlobalPreparation:
    """Issue immutable observations and partial Project/category preamble state."""
    def __init__(self, spec):
        self.common = EdltLighting(spec); self.spec = spec; self._owner = object()
        self.last_evidence = None
        if len(spec.parameters) != 874: raise EdltError('Global preparation requires the complete 874-parameter profile')
        layout = self.common.codec.layout('Project')
        if (layout.parameter.type,layout.address,layout.array_size) != ('sixbit',0x23,8):
            raise EdltError('Unsupported original legacy Project layout')
        if any(name not in spec.parameters for names in CATEGORIES.values() for name in names):
            raise EdltError('Incomplete Global category specification')

    def _raw_input(self, values):
        if not isinstance(values,Mapping) or set(values) != set(self.spec.parameters):
            raise EdltError('Global preparation requires all 874 raw PP strings')
        if any(type(value) is not str or len(value)>8192 or any(ord(c)<32 or ord(c)==127 for c in value)
               for value in values.values()) or sum(map(len,values.values()))>262144:
            raise EdltError('Raw PP strings must be bounded and contain no control characters')
        for name,value in values.items():
            if self.spec.get(name).type not in ('string','sixbit') and not re.fullmatch(
                    r'(?:0[xX][0-9A-Fa-f]+|[0-9]+)(?: (?:0[xX][0-9A-Fa-f]+|[0-9]+))*',value):
                raise EdltError('Invalid raw numeric PP spelling: '+name)
        self.common.snapshot(values)
        return dict(values)

    def _issue(self, *args):
        origin = _Origin(self._owner); value = GlobalPreparation(*args,origin)
        origin.reference = weakref.ref(value)
        return value

    def _validate(self, value):
        if (type(value) is not GlobalPreparation or type(value._origin) is not _Origin or
                value._origin.owner is not self._owner or value._origin.reference is None or
                value._origin.reference() is not value):
            raise EdltError('Use an intact preparation issued by this engine')
        _state(value.project)
        if type(value.context) is not GlobalPreparationContext: raise EdltError('Invalid preparation context')
        value.context.__post_init__()
        self._raw_input(value.expected_raw)
        # The actual post-setter raw Project may exceed physical sixbit limits.
        # Validate everything else against the unchanged captured Project only.
        self._raw_input({**value.raw,'Project':value.expected_raw['Project']})
        if value.raw['Project'] != value.project.value: raise EdltError('Project sidecar differs from raw model projection')

    def begin(self, raw_parameters, *, context, dirty_parameters=(), initializing=False):
        if type(context) is not GlobalPreparationContext: raise EdltError('Use an exact GlobalPreparationContext')
        context.__post_init__(); raw = self._raw_input(raw_parameters)
        if type(initializing) is not bool: raise EdltError('Initializing must be an exact boolean')
        if (type(dirty_parameters) not in (tuple,list) or any(type(name) is not str or name not in raw for name in dirty_parameters)
                or len(dirty_parameters) != len(set(dirty_parameters))):
            raise EdltError('Dirty parameters must be unique known names')
        project = ProjectState.from_raw(raw['Project'],dirty='Project' in dirty_parameters,initializing=initializing)
        return self._issue(raw,{**raw,'Project':project.value},context,project,tuple(sorted(dirty_parameters)),
            tuple(raw),('raw-observation',),(),None,())

    def _project_phase(self, source, assignment, stage, *, destination=None, forced=()):
        dirty = set(source.dirty_parameters) | set(forced)
        if assignment.after.dirty: dirty.add('Project')
        return self._issue(source.expected_raw,{**source.raw,'Project':assignment.after.value},source.context,
            assignment.after,tuple(sorted(dirty)),source.parameter_order,source.stages+(stage,),
            source.project_assignments+(assignment,),destination,tuple(forced))

    def initialize_project(self, source):
        self._validate(source)
        if source.stages != ('raw-observation',): raise EdltError('Initial Project phase requires a fresh raw observation')
        assignment = initialize_project(source.project,source.context.form_project)
        return self._project_phase(source,assignment,'conditional-project-initialization')

    def project_preamble(self, source, *, destination, categories=()):
        self._validate(source)
        if 'project-and-category-preamble' in source.stages: raise EdltError('Preamble already modeled; start another explicit observation')
        match = _PATH.fullmatch(destination) if type(destination) is str else None
        old = _PATH.fullmatch(source.context.source)
        if not match or match.groups()[:2] != old.groups()[:2] or int(match[3])>255:
            raise EdltError('Destination must be a canonical unit in the same explicit project/network')
        if (type(categories) not in (tuple,list) or any(type(name) is not str or name not in CATEGORIES for name in categories)
                or len(categories) != len(set(categories))):
            raise EdltError('Select each known category at most once')
        forced = tuple(name for category,names in CATEGORIES.items() if category in categories for name in names)+('OverallCRC',)
        assignment = assign_project(source.project,source.context.cached_network_project)
        return self._project_phase(source,assignment,'project-and-category-preamble',destination=destination,forced=forced)

    def prepare_factory(self, raw_parameters, *, metadata, context, global_engine):
        """Compose the captured factory path, preserving original raw source.

        The scope is six complete captured source patterns, original parameter
        order and an empty initial dirty set. No original form or I/O executes.
        """
        return _prepare_factory(self, raw_parameters, metadata=metadata,
            context=context, global_engine=global_engine)

    def factory_context(self, raw_parameters, *, reset_editor, context, metadata,
                        dirty_parameters=()):
        """Issue inputs for a separately validated factory Reset transition.

        Issuance itself performs no load, Reset, binding, save or Global bridge.
        The Reset editor must compare its supplied call with this receipt.
        """
        from .edlt_reset import EdltResetControls
        from .edlt_lifecycle import EdltLifecycle
        from .edlt_application_cache import ApplicationCache
        if (type(self) is not EdltGlobalPreparation or type(reset_editor) is not EdltResetControls or
                type(reset_editor.lifecycle) is not EdltLifecycle or
                reset_editor.spec is not self.spec or
                reset_editor.lifecycle.spec is not self.spec or
                reset_editor.common is not reset_editor.lifecycle.common):
            raise EdltError('Factory context requires the exact Reset editor and shared specification')
        observed = self.begin(raw_parameters, context=context, dirty_parameters=dirty_parameters)
        cache = ApplicationCache.from_dict(metadata.as_dict() if isinstance(metadata, ApplicationCache) else metadata)
        signature = _factory_specification(self.spec)
        if reset_editor.specification_sha256 != signature:
            raise EdltError('Reset specification changed since editor construction')
        origin = _FactoryOrigin(self, reset_editor, reset_editor.lifecycle, self.spec, signature)
        result = GlobalFactoryContext(observed.expected_raw, observed.parameter_order,
            observed.context, cache, observed.dirty_parameters, signature, origin)
        origin.reference = weakref.ref(result)
        origin.content = _factory_content(result)
        return result


class _FactoryOrigin:
    def __init__(self, owner, editor, lifecycle, spec, signature):
        self.owner, self.editor, self.lifecycle = owner, editor, lifecycle
        self.spec, self.signature, self.reference, self.content = spec, signature, None, None


def _factory_specification(spec):
    import hashlib
    import json
    return hashlib.sha256(json.dumps([
        (name, parameter.type, dict(parameter.fields))
        for name, parameter in spec.parameters.items()
    ], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class GlobalFactoryContext:
    """Issued immutable inputs; not proof that a factory transition occurred."""
    expected_raw: Mapping
    parameter_order: tuple[str, ...]
    context: GlobalPreparationContext
    metadata: object
    dirty_parameters: tuple[str, ...]
    specification_sha256: str
    _origin: _FactoryOrigin = field(repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, 'expected_raw', MappingProxyType(dict(self.expected_raw)))

    def as_dict(self):
        return {'format':'cbus-edlt-global-factory-context-v1',
            'factory_context':'factory-global-reset-then-remove-global-tab-v1',
            'expected_raw':dict(self.expected_raw), 'parameter_order':list(self.parameter_order),
            'context':self.context.as_dict(), 'metadata':self.metadata.as_dict(),
            'dirty_parameters':list(self.dirty_parameters),
            'specification_sha256':self.specification_sha256,
            'factory_transition_executed':False, 'reset_applied':False,
            'global_bridge_enabled':False, 'saved':False, 'physical_device_verified':False,
            'cache_freshness_verified':False, 'export_is_review_only':True}


def _factory_content(context):
    import json
    return json.dumps(context.as_dict(), sort_keys=True, separators=(',', ':'), allow_nan=False)


def _validate_factory_context(context, reset_editor):
    """Validate issued identity, bound engine and intact inputs before use."""
    from .edlt_reset import EdltResetControls
    from .edlt_lifecycle import EdltLifecycle
    from .edlt_application_cache import ApplicationCache
    if (type(context) is not GlobalFactoryContext or type(context._origin) is not _FactoryOrigin or
            context._origin.reference is None or context._origin.reference() is not context):
        raise EdltError('Use an intact issued Global factory context')
    origin = context._origin
    if (type(reset_editor) is not EdltResetControls or reset_editor is not origin.editor or
            type(reset_editor.lifecycle) is not EdltLifecycle or reset_editor.lifecycle is not origin.lifecycle or
            type(origin.owner) is not EdltGlobalPreparation or origin.owner.spec is not origin.spec or
            reset_editor.spec is not origin.spec or reset_editor.lifecycle.spec is not origin.spec or
            reset_editor.common is not reset_editor.lifecycle.common or
            reset_editor.specification_sha256 != origin.signature or
            _factory_specification(origin.spec) != origin.signature):
        raise EdltError('Global factory context differs from its bound editor, lifecycle or specification')
    if type(context.context) is not GlobalPreparationContext or type(context.metadata) is not ApplicationCache:
        raise EdltError('Invalid Global factory identity or metadata context')
    context.context.__post_init__()
    origin.owner._raw_input(context.expected_raw)
    if (type(context.parameter_order) is not tuple or context.parameter_order != tuple(context.expected_raw) or
            type(context.dirty_parameters) is not tuple or
            any(type(name) is not str or name not in context.expected_raw for name in context.dirty_parameters) or
            context.dirty_parameters != tuple(sorted(set(context.dirty_parameters))) or
            type(context.specification_sha256) is not str or context.specification_sha256 != origin.signature):
        raise EdltError('Invalid Global factory parameter order, dirty fields or specification fingerprint')
    ApplicationCache.from_dict(context.metadata.as_dict())
    if _factory_content(context) != origin.content:
        raise EdltError('Global factory context differs from its issued raw/cache/identity inputs')
    return context


class _PreparedFactoryOrigin:
    def __init__(self, preparer, engine, reset, receipt, state, saved):
        self.preparer, self.engine, self.reset = preparer, engine, reset
        self.receipt, self.state, self.saved = receipt, state, saved
        self.reference, self.content = None, None


@dataclass(frozen=True)
class FactoryGlobalPreparation:
    """Issued deterministic factory/preworker composition, never a form or I/O."""
    expected_raw: Mapping
    expected: Mapping
    after_load: Mapping
    before_save: Mapping
    final: Mapping
    context: GlobalPreparationContext
    metadata: object
    parameter_order: tuple[str, ...]
    raw_phases: Mapping
    project_assignment: ProjectAssignment
    model_plan: str
    _origin: _PreparedFactoryOrigin = field(repr=False, compare=False)

    def __post_init__(self):
        for name in ('expected_raw', 'expected', 'after_load', 'before_save', 'final', 'raw_phases'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        import json
        from .edlt_global_programming import _values
        return {'format': 'cbus-edlt-global-factory-preparation-v1',
            'unit_type': 'KEYGL5', 'catalog_number': '5055EDL', 'firmware': '5.5.00',
            'expected_raw': dict(self.expected_raw), 'expected': _values(self.expected),
            'after_load': _values(self.after_load), 'before_save': _values(self.before_save),
            'final': _values(self.final), 'context': self.context.as_dict(),
            'metadata': self.metadata.as_dict(), 'parameter_order': list(self.parameter_order),
            'raw_phases': {name: value.as_dict() for name, value in self.raw_phases.items()},
            'project_assignment': self.project_assignment.as_dict(),
            'retained_model_save': json.loads(self.model_plan),
            'factory_model_preparation_applied': True, 'reset_applied': True,
            'global_tab_removed_after_reset': True, 'initial_model_load_count': 1,
            'reset_fresh_model_load_count': 1, 'third_load_applied': False,
            'full_form_executed': False, 'callbacks_executed': False, 'renderer_verified': False,
            'source_preparation': 'issued captured factory Reset, tab removal and explicit Project preworker',
            'raw_project_oem_projection': 'original Project retained only inside unchanged physical codec',
            'raw_model_physically_encodable_verified': False, 'physical_codec_relaxed': False,
            'physical_device_verified': False, 'cache_freshness_verified': False,
            'arbitrary_source_history_verified': False, 'initial_dirty_parameters': [],
            'forced_category_dirty_phase_applied': False, 'saved': False, 'export_is_review_only': True}


def _prepared_factory_content(value):
    import json
    return json.dumps(value.as_dict(), sort_keys=True, separators=(',', ':'), allow_nan=False)


def _validate_prepared_factory(value, engine):
    from .edlt_global_programming import EdltGlobalProgramming
    from .edlt_reset import _validate_factory_reset
    if (type(value) is not FactoryGlobalPreparation or type(value._origin) is not _PreparedFactoryOrigin
            or type(engine) is not EdltGlobalProgramming or value._origin.engine is not engine
            or value._origin.reference is None or value._origin.reference() is not value):
        raise EdltError('Use an intact factory preparation issued for this exact Global engine')
    origin = value._origin
    receipt = _validate_factory_context(origin.receipt, origin.reset)
    if (engine.lifecycle is not origin.reset.lifecycle or engine.spec is not origin.reset.spec
            or engine.common is not origin.reset.common or engine.codec is not origin.reset.codec
            or origin.preparer.spec is not engine.spec
            or _validate_factory_reset(engine.lifecycle, origin.state) is not receipt
            or origin.saved.state is not origin.state or value.metadata is not receipt.metadata
            or value.context is not receipt.context):
        raise EdltError('Factory preparation retained engine/model/cache identities changed')
    origin.preparer._raw_input(value.expected_raw)
    for snapshot in (value.expected, value.after_load, value.before_save, value.final):
        engine.snapshot(snapshot)
    if (dict(value.expected_raw) != dict(receipt.expected_raw)
            or value.parameter_order != receipt.parameter_order
            or _prepared_factory_content(value) != origin.content):
        raise EdltError('Factory preparation differs from its issued raw phases and source preconditions')
    return value


def _prepare_factory(preparer, raw_parameters, *, metadata, context, global_engine):
    import json
    from .edlt_global_programming import EdltGlobalProgramming
    from .edlt_reset import EdltResetControls, ResetPhase
    from .edlt_lifecycle import _error_text
    preparer.last_evidence = None
    stage = 'preflight'
    reset = None
    try:
        if (type(preparer) is not EdltGlobalPreparation or type(global_engine) is not EdltGlobalProgramming
                or global_engine.spec is not preparer.spec):
            raise EdltError('Factory preparation requires the exact shared Global engine and specification')
        raw = preparer._raw_input(raw_parameters)
        if tuple(raw) != tuple(preparer.spec.parameters):
            raise EdltError('Factory preparation requires the captured original complete parameter order')
        reset = EdltResetControls(preparer.spec, lifecycle=global_engine.lifecycle)
        receipt = preparer.factory_context(raw, reset_editor=reset, context=context, metadata=metadata)
        stage = 'factory_reset'
        state = reset.prepare_global_factory(raw, metadata=receipt.metadata, preparation_context=receipt)
        stage = 'project_preworker'
        assignment = assign_project(state.project_assignment.after, context.cached_network_project)
        def overlay(phase):
            tokens = dict(phase.tokens)
            tokens['Project'] = assignment.after.tokens
            dirty = set(phase.dirty_parameters)
            if assignment.after.dirty: dirty.add('Project')
            return ResetPhase(tokens, tuple(sorted(dirty)), phase.initializing)
        preworker = overlay(state.raw_phases['after-global-tab-removal'])
        stage = 'terminal_source_save'
        saved = reset.prepare_global_factory_save(state)
        phases = dict(state.raw_phases)
        phases['project-preworker'] = preworker
        phases['before-save'] = overlay(saved.phases['before-save'])
        phases['final'] = overlay(saved.phases['final'])
        model = saved.model_plan
        final = {**model.expected, **model.changes}
        origin = _PreparedFactoryOrigin(preparer, global_engine, reset, receipt, state, saved)
        value = FactoryGlobalPreparation(receipt.expected_raw, model.expected, model.after_load,
            model.before_save, final, receipt.context, receipt.metadata, receipt.parameter_order,
            phases, assignment, json.dumps(model.as_dict(), sort_keys=True, separators=(',', ':'), allow_nan=False), origin)
        origin.reference = weakref.ref(value)
        origin.content = _prepared_factory_content(value)
        _validate_prepared_factory(value, global_engine)
        preparer.last_evidence = {'format': 'cbus-edlt-global-factory-preparation-outcome-v1',
            'operation': 'prepare_factory', 'stage': 'prepared', 'complete': True,
            'saved': False, 'io_performed': False, 'physical_device_verified': False}
        return value
    except BaseException as error:
        evidence = {'format': 'cbus-edlt-global-factory-preparation-outcome-v1',
            'operation': 'prepare_factory', 'stage': stage, 'complete': False,
            'saved': False, 'io_performed': False, 'physical_device_verified': False,
            'cause': {'type': type(error).__name__, 'message': _error_text(error)}}
        if reset is not None and reset.last_evidence is not None:
            evidence['factory_reset_evidence'] = reset.last_evidence
        preparer.last_evidence = evidence
        try: error.edlt_global_preparation_evidence = evidence
        except BaseException: pass
        raise
