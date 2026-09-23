"""Explicit original eDLT model and global application-control phases.

This module retains the loaded model throughout an edit sequence. Dependent
widget panels, SceneManager and group getters are separate operations and are
not implicitly invoked by these two application controls.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
from types import MappingProxyType
from typing import Mapping
import weakref

from .edlt import EdltError, EdltApplyError, _field, _int, _render
from .edlt_application_cache import ApplicationCache
from .edlt_lifecycle import EdltLifecycle, LoadedEdlt, LifecycleMetadataError, _delta, _json, _error_text

_SELECTED_APPLICATION_TYPES = frozenset((2, 3, 4, 5, 15, 16))
MAX_APPLICATION_EDITS = 64


class ApplicationApplyError(EdltApplyError):
    """Retain the original failure even if its string conversion raises."""
    def __init__(self, cause, rollback_errors, attempted_parameters=()):
        self.cause, self.rollback_errors = cause, tuple(rollback_errors)
        self.attempted_parameters, self.saved = tuple(attempted_parameters), False
        try:
            cleanup = getattr(cause, 'cgate_cleanup_errors', None)
            if cleanup is not None: self.cgate_cleanup_errors = cleanup
        except BaseException: pass
        self.details = self.as_dict()
        RuntimeError.__init__(self, 'Application edit failed; ' +
            ('rollback had errors' if rollback_errors else 'original PP values were restored') + ': ' + _error_text(cause))

    def as_dict(self):
        result = {'error': _error_text(self.cause), 'attempted_parameters': list(self.attempted_parameters),
            'rollback_errors': list(self.rollback_errors), 'saved': False, 'rollback_verified': not self.rollback_errors}
        if hasattr(self, 'cgate_cleanup_errors'): result['cgate_cleanup_errors'] = self.cgate_cleanup_errors
        return result


@dataclass(frozen=True)
class ApplicationEdit:
    field: str
    address: int

    def __post_init__(self):
        if self.field not in ('primary', 'secondary'):
            raise EdltError('Application field must be primary or secondary')
        _int(self.address, 'Application address')

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping) or set(value) != {'field', 'address'}:
            raise EdltError('Application edit requires exactly field and address')
        return cls(value['field'], value['address'])

    def as_dict(self): return {'field': self.field, 'address': self.address}


@dataclass(frozen=True)
class ApplicationPhase:
    name: str
    values: Mapping

    def __post_init__(self):
        object.__setattr__(self, 'values', MappingProxyType(dict(self.values)))


class _Origin:
    def __init__(self, owner):
        self.owner, self.reference = owner, None


@dataclass(frozen=True)
class ApplicationState:
    """Issued, immutable model state; diagnostics do not resolve any groups."""
    loaded: LoadedEdlt
    cache: ApplicationCache
    values: Mapping
    prepared: bool
    bound: bool
    validated: bool
    edits: tuple[ApplicationEdit, ...]
    phases: tuple[ApplicationPhase, ...]
    wrapper_change_count: int
    _origin: _Origin = field(repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, 'values', MappingProxyType(dict(self.values)))

    def as_dict(self):
        primary = self.values['PrimaryApplication'][0]
        secondary = self.values['SecondaryApplication'][0]
        choices = self.cache.application_choices(primary=primary, secondary=secondary)
        return {'format': 'cbus-edlt-application-state-v1',
            'primary': primary, 'secondary': secondary,
            'phase': self.phases[-1].name, 'prepared': self.prepared,
            'bound_controls': ['PrimaryApplication', 'SecondaryApplication'] if self.bound else [],
            'validated': self.validated,
            'choices': {role: [row.as_dict() for row in rows] for role, rows in choices.items()},
            'selected': {role: value if any(row.address == value for row in choices[role]) else None
                         for role, value in (('primary', primary), ('secondary', secondary))} if self.bound else {},
            'primary_secondary_names': ([] if not self.prepared else
                [{'selector': 0, 'name': '(P) ' + self.cache.find_application(primary).formatted_display}] +
                ([] if secondary == 255 else [{'selector': 1,
                  'name': '(S) ' + self.cache.find_application(secondary).formatted_display}])),
            'edits': [edit.as_dict() for edit in self.edits],
            'wrapper_change_count': self.wrapper_change_count,
            'phases': [{'name': phase.name, 'changes': _delta(self.loaded.expected, phase.values)}
                       for phase in self.phases],
            'scene_objects': [scene.as_dict() for scene in self.loaded.scenes],
            'dependency_getters_invoked': False, 'metadata_created': False,
            'full_form_initialization_verified': False, 'physical_device_verified': False,
            'model_state_resumption_supported': False, 'saved': False}


@dataclass(frozen=True)
class ApplicationsPlan:
    expected: Mapping
    after_load: Mapping
    after_controls: Mapping
    before_save: Mapping
    changes: Mapping
    cache: ApplicationCache
    edits: tuple[ApplicationEdit, ...]
    evidence: str

    def __post_init__(self):
        for name in ('expected', 'after_load', 'after_controls', 'before_save', 'changes'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-applications-plan-v1', 'unit_type': 'KEYGL5',
            'catalog_number': '5055EDL', 'firmware': '5.5.00',
            'edits': [edit.as_dict() for edit in self.edits],
            'phases': {'after_load': _delta(self.expected, self.after_load),
                       'after_controls': _delta(self.after_load, self.after_controls),
                       'before_save': _delta(self.after_controls, self.before_save),
                       'crc': _delta(self.before_save, {**self.expected, **self.changes})},
            'changes': {name: list(value) if isinstance(value, tuple) else value for name, value in self.changes.items()},
            **json.loads(self.evidence), 'cache_provenance': 'caller-supplied-cache',
            'cache_freshness_verified': False, 'metadata_created': False,
            'dependency_getters_invoked': False, 'physical_device_verified': False,
            'full_form_initialization_verified': False, 'saved': False}


class EdltApplications:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.lifecycle = EdltLifecycle(spec, catalog_number=catalog_number, firmware=firmware)
        self.common = self.lifecycle.common
        self.spec, self.codec = self.lifecycle.spec, self.lifecycle.codec
        self._owner = object()
        self.last_evidence = None
        for name, address, size in (('PrimaryApplication', 272, 1), ('SecondaryApplication', 273, 1), ('Application', 33, 2)):
            layout = self.codec.layout(name)
            if (layout.address, layout.array_size, layout.parameter.type, layout.bit_size,
                    layout.bit_address, layout.array_skip) != (address, size, 'int', 8, 0, 0):
                raise EdltError('Unsupported application layout: ' + name)

    def snapshot(self, values): return self.lifecycle.snapshot(values)

    def _check(self, state):
        if (type(state) is not ApplicationState or type(state._origin) is not _Origin or
                state._origin.owner is not self._owner or state._origin.reference is None or
                state._origin.reference() is not state):
            raise EdltError('Use an intact application state issued by this EdltApplications instance')

    def _issue(self, loaded, cache, values, prepared, bound, validated, edits, phases, count):
        origin = _Origin(self._owner)
        state = ApplicationState(loaded, cache, values, prepared, bound, validated, edits, phases, count, origin)
        origin.reference = weakref.ref(state)
        return state

    def _next(self, state, name, *, values=None, prepared=None, bound=None, validated=None, edit=None, changed=False):
        self._check(state)
        values = state.values if values is None else values
        return self._issue(state.loaded, state.cache, values,
            state.prepared if prepared is None else prepared,
            state.bound if bound is None else bound,
            state.validated if validated is None else validated,
            state.edits if edit is None else (*state.edits, edit),
            (*state.phases, ApplicationPhase(name, values)), state.wrapper_change_count + int(changed))

    def load(self, current, *, cache):
        cache = ApplicationCache.from_dict(cache.as_dict() if type(cache) is ApplicationCache else cache)
        original = self.snapshot(current)
        # Completeness belongs to the caller's explicit cache contract, and
        # must not be inferred from the lifecycle's smaller set of facts.
        cache.application_choices(primary=original['PrimaryApplication'][0], secondary=original['SecondaryApplication'][0])
        loaded = self.lifecycle.load(original, metadata=cache.lifecycle)
        return self._issue(loaded, cache, loaded.after_load, False, False, False, (),
                           (ApplicationPhase('after_load', loaded.after_load),), 0)

    @staticmethod
    def _require_pair(state, values):
        for role in ('primary', 'secondary'):
            address = values[role.title() + 'Application'][0]
            if role == 'secondary' and address == 255: continue
            if state.cache.find_application(address) is None:
                raise LifecycleMetadataError('Required named application is missing: ' + str(address),
                    {'application': address, 'role': role}, original_stage='populate-primsec')

    def prepare_applications(self, state):
        self._check(state)
        if state.prepared: raise EdltError('Application lists have already been prepared')
        self._require_pair(state, state.values)
        return self._next(state, 'prepare_applications', prepared=True)

    def bind_global_applications(self, state):
        self._check(state)
        if not state.prepared or state.bound:
            raise EdltError('Prepare application lists once before binding the global controls')
        # These two bindings read application PP wrappers only. In particular
        # a missing selection is not assigned a replacement application.
        return self._next(state, 'bind_global_applications', bound=True)

    def commit_application(self, state, *, field, address):
        self._check(state)
        edit = ApplicationEdit(field, address)
        if not state.prepared or not state.bound:
            raise EdltError('Bind the global application controls before committing a selection')
        if state.validated:
            raise EdltError('Application validation is terminal; prepare the save from this state')
        if len(state.edits) >= MAX_APPLICATION_EDITS:
            raise EdltError('Application sequences are limited to 64 selections')
        choices = state.cache.application_choices(primary=state.values['PrimaryApplication'][0],
                                                   secondary=state.values['SecondaryApplication'][0])
        if not any(row.address == address for row in choices[field]):
            raise EdltError('Requested ' + field + ' application is unavailable in the current control list')
        name = field.title() + 'Application'
        values = dict(state.values); changed = values[name] != (address,)
        values[name] = (address,)
        if changed:
            self._require_pair(state, values)
            # Original wrapper notification invokes CheckIfGroupsExist. Its
            # GetGroup reads raw byte6, whereas GroupAddress is a different,
            # potentially mutating getter used by dependent control panels.
            for widget in state.loaded.widgets:
                kind = widget.stored_type
                if kind not in _SELECTED_APPLICATION_TYPES and kind != 14: continue
                key = _field(widget.slot, 1); control = values[key][0]
                if kind != 14 and control & 128 and values['SecondaryApplication'] == (255,):
                    control &= 127; values[key] = (control,)
                application = 203 if kind == 14 else (values['SecondaryApplication'][0] if control & 128
                                                     else values['PrimaryApplication'][0])
                group = values[_field(widget.slot, 6)][0]
                if state.cache.group_presence(application, group) is None:
                    raise LifecycleMetadataError('Unknown cached widget group after application selection',
                        {'application': application, 'group': group, 'widget': widget.slot}, original_stage='application-callback')
        return self._next(state, 'commit_application', values=values, edit=edit, changed=changed, validated=False)

    def validate_bound_controls(self, state):
        self._check(state)
        if not state.bound: raise EdltError('No global application controls are bound')
        if state.validated: raise EdltError('Global application controls have already been validated')
        return self._next(state, 'validate_bound_controls', validated=True)

    def prepare_save(self, state):
        self._check(state)
        if not state.bound or not state.validated:
            raise EdltError('Validate the global application controls before preparing their save')
        # Existing no-edit save serializes the same retained scenes/static
        # strings and cached MRA globals. Application changes only alter the
        # application pair and app-group selector bit; model families survive.
        # Keep original SetForcedValues' lower seven bits, including its
        # Fan/MultiLevel status5/index reset, and recompute every CRC afterward.
        baseline = self.lifecycle.prepare_save(state.loaded)
        values = dict(baseline.before_save)
        values['PrimaryApplication'] = state.values['PrimaryApplication']
        values['SecondaryApplication'] = state.values['SecondaryApplication']
        values['Application'] = (values['PrimaryApplication'][0], values['SecondaryApplication'][0])
        for widget in state.loaded.widgets:
            if widget.stored_type not in _SELECTED_APPLICATION_TYPES: continue
            if values[_field(widget.slot)] != (widget.stored_type,):
                raise EdltError('Application save requires unchanged retained widget types')
            name = _field(widget.slot, 1)
            values[name] = ((values[name][0] & 127) | (state.values[name][0] & 128),)
        before_save = self.snapshot(values); values.update(self.lifecycle.crcs(before_save))
        evidence = {'control_state': state.as_dict(), 'lifecycle': baseline.as_dict(),
            'save_composition': 'retained lifecycle models; application pair and selector bit7; fresh configuration CRCs'}
        return ApplicationsPlan(state.loaded.expected, state.loaded.after_load, state.values, before_save,
            {name: value for name, value in values.items() if value != state.loaded.expected[name]},
            state.cache, state.edits, _json(evidence))

    @staticmethod
    def _edits(edits):
        if not isinstance(edits, (list, tuple)) or len(edits) > MAX_APPLICATION_EDITS:
            raise EdltError('Provide an ordered sequence of at most 64 application selections')
        return tuple(edit if type(edit) is ApplicationEdit else ApplicationEdit.from_dict(edit) for edit in edits)

    def plan(self, current, *, cache, edits=()):
        edits = self._edits(edits)
        state = self.bind_global_applications(self.prepare_applications(self.load(current, cache=cache)))
        for edit in edits: state = self.commit_application(state, field=edit.field, address=edit.address)
        return self.prepare_save(self.validate_bound_controls(state))

    def _interrupted(self, error, plan, attempted, original_error=None):
        evidence = {'verified': False, 'saved': False, 'attempted_parameters': list(attempted),
                    'pp_state_uncertain': bool(attempted), 'automatic_retries': 0}
        try: evidence = {**plan.as_dict(), **evidence}
        except BaseException as secondary:
            evidence.update(evidence_export_complete=False, evidence_error=_error_text(secondary))
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': _error_text(original_error)}
        try:
            cleanup = getattr(original_error if original_error is not None else error, 'cgate_cleanup_errors', None)
            if cleanup is not None: evidence['cgate_cleanup_errors'] = cleanup
        except BaseException: pass
        self.last_evidence = evidence
        try: error.edlt_applications_evidence = evidence
        except BaseException: pass
        return evidence

    def apply(self, session, plan):
        self.last_evidence = None
        if type(plan) is not ApplicationsPlan or type(plan.cache) is not ApplicationCache:
            raise EdltError('Use an application plan returned by EdltApplications.plan')
        for values in (plan.expected, plan.after_load, plan.after_controls, plan.before_save,
                       {**plan.expected, **plan.changes}): self.snapshot(values)
        canonical = self.plan(plan.expected, cache=plan.cache, edits=plan.edits)
        if canonical != plan or _json(canonical.as_dict()) != _json(plan.as_dict()):
            raise EdltError('Application plan differs from its canonical control sequence')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the application plan was made')
        expected = {**plan.expected, **plan.changes}; attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name); session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the application plan')
        except (KeyboardInterrupt, SystemExit) as error:
            self._interrupted(error, plan, attempted); raise
        except Exception as error:
            rollback_errors = []
            try:
                for name in reversed(attempted):
                    if not getattr(session.programmer.client, 'connected', True):
                        rollback_errors.append('Connection lost; rollback stopped without recovery I/O; PP state is uncertain'); break
                    try: session.set(name, _render(plan.expected[name]))
                    except Exception as rollback: rollback_errors.append(_error_text(rollback))
                if getattr(session.programmer.client, 'connected', True):
                    try:
                        if self.snapshot(session.values()) != dict(plan.expected):
                            rollback_errors.append('Original PP values could not be verified')
                    except Exception as rollback: rollback_errors.append(_error_text(rollback))
            except (KeyboardInterrupt, SystemExit) as interrupted:
                evidence = self._interrupted(interrupted, plan, attempted, error)
                evidence['rollback_errors'] = rollback_errors; raise
            wrapped = ApplicationApplyError(error, rollback_errors, attempted)
            self._interrupted(wrapped, plan, attempted, error)
            raise wrapped from error
        self.last_evidence = {**plan.as_dict(), 'verified': True}
        return self.last_evidence

    def configure(self, session, *, cache, edits=()):
        edits = self._edits(edits)
        cache = ApplicationCache.from_dict(cache.as_dict() if type(cache) is ApplicationCache else cache)
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), cache=cache, edits=edits))
