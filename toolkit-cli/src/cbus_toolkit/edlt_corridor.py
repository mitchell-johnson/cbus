"""Original eDLT Corridor controls composed with one immutable lifecycle load.

The four Corridor fields commute with the unchanged model's BeforeSave. This
module does not bind widget controls, edit applications, create metadata or save
physical devices. Timer display and stored model seconds are intentionally
separate: the original changed-value setter clamps its16-bit field to a byte.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltError, EdltApplyError, _field, _int, _render
from .edlt_application_cache import ApplicationCache
from .edlt_lifecycle import EdltLifecycle, LifecycleMetadataError, _delta, _json

FIELDS = MappingProxyType({'link_group': 'CorridorLinkingLinkGroup',
    'office_group': 'CorridorLinkingOfficeGroup', 'corridor_group': 'CorridorLinkingCorridorGroup',
    'seconds': 'CorridorLinkingCorridorTime'})
_ROLES = ('link_group', 'office_group', 'corridor_group')
_GROUP_FAMILIES = frozenset(('LightingData', 'ShutterRelayData', 'FanControllerData',
    'TimerData', 'EnableData', 'RCPData', 'MultiLevelData'))
MAX_EDITS = 64


def _error_text(error):
    try: return str(error)[:1024]
    except BaseException: return '<unprintable ' + type(error).__name__ + '>'


class CorridorApplyError(EdltApplyError):
    """Keep the command failure when rendering its message also fails."""
    def __init__(self, cause, rollback_errors=(), attempted_parameters=()):
        self.cause, self.rollback_errors = cause, tuple(rollback_errors)
        self.attempted_parameters, self.saved = tuple(attempted_parameters), False
        self.details = self.as_dict()
        RuntimeError.__init__(self, 'Corridor edit failed; ' +
            ('rollback had errors' if rollback_errors else 'original PP values were restored') + ': ' + _error_text(cause))

    def as_dict(self):
        return {'error': _error_text(self.cause), 'attempted_parameters': list(self.attempted_parameters),
            'rollback_errors': list(self.rollback_errors), 'saved': False,
            'rollback_verified': not self.rollback_errors}


@dataclass(frozen=True)
class CorridorEdit:
    field: str
    value: int

    def __post_init__(self):
        if type(self.field) is not str or self.field not in FIELDS:
            raise EdltError('Corridor field must be link_group, office_group, corridor_group or seconds')
        _int(self.value, 'Requested ' + self.field, 0, 65535 if self.field == 'seconds' else 255)

    @classmethod
    def from_dict(cls, row):
        if not isinstance(row, Mapping) or set(row) != {'field', 'value'}:
            raise EdltError('Invalid Corridor edit fields')
        return cls(row['field'], row['value'])

    def as_dict(self): return {'field': self.field, 'value': self.value}


class CorridorSelectionError(EdltError):
    def __init__(self, details):
        super().__init__('Requested Corridor group is unavailable or its control is disabled')
        self.details = details

    def as_dict(self): return {'error': str(self), 'stage': 'selection', **self.details}


class CorridorConflictError(EdltError):
    def __init__(self, details):
        super().__init__('Corridor Link group is also used by a key function')
        self.details = details

    def as_dict(self): return {'error': str(self), 'stage': 'validation', **self.details}


@dataclass(frozen=True)
class CorridorPlan:
    expected: Mapping
    after_load: Mapping
    after_controls: Mapping
    before_save: Mapping
    changes: Mapping
    cache: ApplicationCache
    edits: tuple[CorridorEdit, ...]
    evidence: str

    def __post_init__(self):
        for name in ('expected', 'after_load', 'after_controls', 'before_save', 'changes'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        final = {**self.expected, **self.changes}
        return {'format': 'cbus-edlt-corridor-plan-v1', 'unit_type': 'KEYGL5',
            'catalog_number': '5055EDL', 'firmware': '5.5.00', 'edits': [e.as_dict() for e in self.edits],
            'phases': {'after_load': _delta(self.expected, self.after_load),
                       'controls': _delta(self.after_load, self.after_controls),
                       'before_save': _delta(self.after_controls, self.before_save),
                       'crc': _delta(self.before_save, final)},
            'changes': {k: list(v) if isinstance(v, tuple) else v for k, v in self.changes.items()},
            **json.loads(self.evidence), 'applies_to_whole_unit': True,
            'metadata_provenance': 'caller-supplied-cache', 'database_metadata_created': False,
            'cache_freshness_verified': False, 'full_form_initialization_verified': False,
            'physical_device_verified': False, 'saved': False}


class EdltCorridor:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.lifecycle = EdltLifecycle(spec, catalog_number=catalog_number, firmware=firmware)
        self.common = self.lifecycle.common
        self.spec, self.codec = self.common.spec, self.common.codec
        self.last_evidence = None
        for field, address, size in (('link_group', 0x132, 8), ('office_group', 0x133, 8),
                                     ('seconds', 0x134, 16), ('corridor_group', 0x136, 8)):
            name = FIELDS[field]
            try: layout = self.codec.layout(name)
            except (ValueError, KeyError) as error: raise EdltError('Unsupported Corridor layout: ' + name) from error
            if (layout.address, layout.parameter.type, layout.bit_address, layout.bit_size,
                    layout.array_size, layout.array_skip) != (address, 'int', 0, size, 1, 0):
                raise EdltError('Unsupported Corridor layout: ' + name)

    def snapshot(self, values): return self.common.snapshot(values)
    def crcs(self, values): return self.common.crcs(values)

    def requirements(self, current):
        values = self.snapshot(current)
        return {'format': 'cbus-edlt-corridor-requirements-v1',
            'lifecycle': self.lifecycle.requirements(values).as_dict(),
            'effective_primary_application': self.lifecycle._primary(values),
            'complete_ordered_primary_group_list_required': True,
            'retained_key_function_group_facts_required': True,
            'metadata_creation_supported': False,
            'raw_corridor': {key: values[name][0] for key, name in FIELDS.items()}}

    def plan(self, current, *, cache, edits=()):
        if not isinstance(edits, (tuple, list)) or len(edits) > MAX_EDITS:
            raise EdltError('Corridor edits must be an ordered sequence of at most64 actions')
        actions = tuple(CorridorEdit.from_dict(e.as_dict() if type(e) is CorridorEdit else e) for e in edits)
        cache = ApplicationCache.from_dict(cache.as_dict() if type(cache) is ApplicationCache else cache)
        loaded = self.lifecycle.load(current, metadata=cache.lifecycle)
        base = self.lifecycle.prepare_save(loaded)
        primary = loaded.after_load['PrimaryApplication'][0]
        if cache.find_application(primary) is None:
            raise LifecycleMetadataError('Corridor controls require a named primary application',
                {'application': primary}, original_stage='controls')
        # Enforce completeness before any modeled binding/getter side effect.
        cache.group_choices(primary)
        values = dict(loaded.after_load)
        raw = {key: values[name][0] for key, name in FIELDS.items()}
        initial = dict(raw); stages = []; consumed = []
        def choices(role):
            return cache.group_choices(primary, exclude=tuple(raw[other] for other in _ROLES if other != role),
                                       placeholder='<Disabled>' if role == 'link_group' else '<Unused>')
        def view(role):
            available = choices(role); selected = raw[role] if any(c.address == raw[role] for c in available) else None
            return {'stored': raw[role], 'selected': selected,
                'enabled': role == 'link_group' or raw['link_group'] != 255,
                'choices': [item.as_dict() for item in available]}
        displayed = 60  # Original designer value before the form's Show binding.
        def record(stage, requested=None):
            row = {'stage': stage, 'roles': {role: view(role) for role in _ROLES},
                'timer': {'stored_seconds': raw['seconds'], 'displayed_seconds': displayed,
                          'enabled': True, 'display_equals_stored': displayed == raw['seconds']}}
            if requested is not None: row['requested'] = requested.as_dict()
            stages.append(row)
        record('before_show')
        # The actual control bindings read PPAttributeDataSourceLogic values at
        # Show. Missing cache objects differ from merely filtered-out duplicates.
        for role in ('corridor_group', 'office_group', 'link_group'):
            number = raw[role]
            if number == 255: continue
            presence = cache.group_presence(primary, number)
            if presence is None:
                raise LifecycleMetadataError('Unknown Corridor group presence',
                    {'application': primary, 'group': number}, original_stage='controls')
            consumed.append({'role': role, 'application': primary, 'group': number, 'exists': presence})
            if not presence: raw[role] = 255
        displayed = min(64800, max(60, raw['seconds']))
        record('shown')
        for index, edit in enumerate(actions, 1):
            if edit.field == 'seconds': displayed = min(64800, max(60, edit.value))
            else:
                control = view(edit.field)
                if not control['enabled'] or edit.value not in {row['address'] for row in control['choices']}:
                    raise CorridorSelectionError({'edit_index': index, 'edit': edit.as_dict(), 'control': control,
                                                   'completed_stages': stages, 'programming_attempted': False})
                raw[edit.field] = edit.value
            record('edit_' + str(index), edit)
        # Original TimerValue is OnValidation. The model early return precedes
        # the nested ValueAsInt byte clamp; the visible control is not re-read.
        if raw['seconds'] != displayed: raw['seconds'] = min(255, max(0, displayed))
        record('validated')
        key_groups = []
        for widget in loaded.widgets:
            if widget.model_family not in _GROUP_FAMILIES: continue
            slot = widget.slot
            app = 203 if widget.model_family == 'EnableData' else (
                values['SecondaryApplication'][0] if values[_field(slot, 1)][0] & 128 else primary)
            number = values[_field(slot, 6)][0]
            fact = loaded.metadata.find(app, number)
            if fact is None:
                raise LifecycleMetadataError('Unknown key-function group presence',
                    {'application': app, 'group': number, 'widget': slot}, original_stage='validation')
            presence = cache.group_presence(app, number)
            if presence is None or presence != fact.exists:
                raise LifecycleMetadataError('Key-function group cache facts disagree',
                    {'application': app, 'group': number, 'widget': slot}, original_stage='validation')
            if presence: key_groups.append({'widget': slot, 'model_family': widget.model_family, 'application': app, 'group': number})
        conflicts = [row for row in key_groups if raw['link_group'] != 255 and row['application'] == primary and row['group'] == raw['link_group']]
        if conflicts:
            raise CorridorConflictError({'link_group': raw['link_group'], 'primary_application': primary,
                'conflicts': conflicts, 'key_function_groups': key_groups, 'completed_stages': stages,
                'programming_attempted': False})
        values.update({name: (raw[key],) for key, name in FIELDS.items()})
        final = dict(base.before_save)
        final.update({name: values[name] for name in FIELDS.values()})
        before_save = dict(final); final.update(self.crcs(final))
        evidence = {'primary_application': primary, 'initial_corridor': initial, 'corridor': raw,
            'controls': stages[-1]['roles'], 'timer': stages[-1]['timer'], 'control_stages': stages,
            'key_function_groups': key_groups, 'corridor_validation_accepted': True,
            'corridor_group_facts': consumed, 'lifecycle': base.as_dict(),
            'model_edit_scope': 'ordered Corridor controls on unchanged loaded models; private Corridor validation',
            'widget_control_bindings_invoked': False, 'metadata_creation_policy': 'disabled',
            'full_unit_validation_performed': False}
        return CorridorPlan(base.expected, base.after_load, values, before_save,
            {name: value for name, value in final.items() if value != base.expected[name]}, cache, actions, _json(evidence))

    def _interrupted(self, error, plan, attempted, original_error=None):
        try: evidence = {**plan.as_dict(), 'verified': False, 'saved': False,
            'attempted_parameters': list(attempted), 'pp_state_uncertain': bool(attempted), 'automatic_retries': 0}
        except BaseException as secondary:
            evidence = {'verified': False, 'saved': False, 'attempted_parameters': list(attempted),
                        'evidence_export_complete': False, 'evidence_error': _error_text(secondary)}
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': _error_text(original_error)}
        self.last_evidence = evidence
        try: error.edlt_corridor_evidence = evidence
        except BaseException: pass
        return evidence

    def apply(self, session, plan):
        self.last_evidence = None
        if type(plan) is not CorridorPlan or type(plan.cache) is not ApplicationCache:
            raise EdltError('Use a Corridor plan returned by EdltCorridor.plan')
        # Python equality treats False and 0 as equal. Validate every supplied
        # phase against the schema before canonical equality can accept it.
        for values in (plan.expected, plan.after_load, plan.after_controls,
                       plan.before_save, {**plan.expected, **plan.changes}):
            self.snapshot(values)
        canonical = self.plan(plan.expected, cache=plan.cache, edits=plan.edits)
        if canonical != plan or _json(canonical.as_dict()) != _json(plan.as_dict()):
            raise EdltError('Plan differs from its validated Corridor controls')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the Corridor plan was made')
        expected = {**plan.expected, **plan.changes}; attempted = []
        try:
            for name, value in plan.changes.items(): attempted.append(name); session.set(name, _render(value))
            if self.snapshot(session.values()) != expected: raise EdltError('Native PP readback differs from the Corridor plan')
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
                        if self.snapshot(session.values()) != dict(plan.expected): rollback_errors.append('Original PP values could not be verified')
                    except Exception as rollback: rollback_errors.append(_error_text(rollback))
            except (KeyboardInterrupt, SystemExit) as interrupted:
                self._interrupted(interrupted, plan, attempted, error)
                self.last_evidence['rollback_errors'] = rollback_errors; raise
            wrapped = CorridorApplyError(error, rollback_errors, attempted)
            self._interrupted(wrapped, plan, attempted, error)
            if hasattr(error, 'cgate_cleanup_errors'): wrapped.cgate_cleanup_errors = error.cgate_cleanup_errors
            raise wrapped from error
        self.last_evidence = {**plan.as_dict(), 'verified': True}
        return self.last_evidence

    def configure(self, session, *, cache, edits=()):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), cache=cache, edits=edits))
