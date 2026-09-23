"""Original eDLT preset-level controls on an unchanged, loaded widget model.

The bounded composition keeps LifecyclePlan's resolved scene state. It never
feeds an after-load PP snapshot back through the original load cycle.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltError, EdltApplyError, _field, _int, _render
from .edlt_lifecycle import EdltLifecycle, LifecycleCache, LifecycleMetadataError, _delta, _json

FORMAT = 'cbus-edlt-restore-cache-v1'
_RESTORE_TYPES = frozenset((2, 3, 4, 5, 16))


def _name(value):
    if not isinstance(value, str) or len(value) > 1024:
        raise EdltError('Cached display name must be a string of at most1024 characters')
    return value


def _error_text(error):
    try: return str(error)[:1024]
    except BaseException: return '<unprintable ' + type(error).__name__ + '>'


@dataclass(frozen=True)
class RestoreLevelCache:
    lifecycle: LifecycleCache
    applications: tuple[tuple[int, str], ...]
    groups: tuple[tuple[int, int, str], ...]

    def __post_init__(self):
        if type(self.lifecycle) is not LifecycleCache:
            raise EdltError('Restore cache requires lifecycle facts')
        for rows, width, limit in ((self.applications, 2, 256), (self.groups, 3, 512)):
            if not isinstance(rows, tuple) or len(rows) > limit:
                raise EdltError('Invalid restore name cache size')
            for row in rows:
                if not isinstance(row, tuple) or len(row) != width:
                    raise EdltError('Invalid restore name cache record')
                for address in row[:-1]: _int(address, 'Cached address')
                _name(row[-1])
                if row[0] not in self.lifecycle.applications:
                    raise EdltError('Named application is absent from lifecycle cache')
            if len({row[:-1] for row in rows}) != len(rows):
                raise EdltError('Duplicate restore cache address')
        for application, group, name in self.groups:
            fact = self.lifecycle.find(application, group)
            if fact is None or not fact.exists:
                raise EdltError('Named group must be explicitly present in lifecycle cache')

    @classmethod
    def from_dict(cls, document):
        if not isinstance(document, Mapping) or set(document) != {'format', 'lifecycle', 'applications', 'groups'} or document['format'] != FORMAT:
            raise EdltError('Invalid restore cache format or fields')
        records = []
        for key, fields, limit in (('applications', ('application', 'name'), 256),
                                   ('groups', ('application', 'group', 'name'), 512)):
            rows = document[key]
            if not isinstance(rows, (list, tuple)) or len(rows) > limit:
                raise EdltError('Invalid restore name cache size')
            if any(not isinstance(row, Mapping) or set(row) != set(fields) for row in rows):
                raise EdltError('Invalid restore name cache fields')
            records.append(tuple(tuple(row[field] for field in fields) for row in rows))
        return cls(LifecycleCache.from_dict(document['lifecycle']), *records)

    def as_dict(self):
        return {'format': FORMAT, 'lifecycle': self.lifecycle.as_dict(),
                'applications': [dict(application=a, name=n) for a, n in self.applications],
                'groups': [dict(application=a, group=g, name=n) for a, g, n in self.groups]}


@dataclass(frozen=True)
class RestoreLevelsPlan:
    expected: Mapping
    after_load: Mapping
    after_controls: Mapping
    before_save: Mapping
    changes: Mapping
    metadata: RestoreLevelCache
    options: Mapping
    evidence: str

    def __post_init__(self):
        for name in ('expected', 'after_load', 'after_controls', 'before_save', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        final = {**self.expected, **self.changes}
        return {'format': 'cbus-edlt-restore-levels-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00',
                'phases': {'after_load': _delta(self.expected, self.after_load),
                           'controls': _delta(self.after_load, self.after_controls),
                           'before_save': _delta(self.after_controls, self.before_save),
                           'crc': _delta(self.before_save, final)},
                'changes': {k: list(v) if isinstance(v, tuple) else v for k, v in self.changes.items()},
                **json.loads(self.evidence), 'metadata_provenance': 'caller-supplied-cache',
                'database_metadata_created': False, 'cache_freshness_verified': False,
                'full_form_initialization_verified': False, 'physical_device_verified': False, 'saved': False}


class EdltRestoreLevels:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.lifecycle = EdltLifecycle(spec, catalog_number=catalog_number, firmware=firmware)
        self.common = self.lifecycle.common
        self.spec, self.codec = self.common.spec, self.common.codec
        try: layout = self.codec.layout('EnableLevelStore')
        except (ValueError, KeyError) as error: raise EdltError('Unsupported restore mode layout') from error
        if (layout.address, layout.parameter.type, layout.bit_address, layout.bit_size,
                layout.array_size, layout.array_skip) != (0x116, 'bit', 1, 1, 1, 0):
            raise EdltError('Unsupported restore mode layout')

    def snapshot(self, values): return self.common.snapshot(values)
    def crcs(self, values): return self.common.crcs(values)

    def plan(self, current, *, metadata, widget=None, level=None, synchronise=False,
             restore_mode=None, page_mode=None):
        if (widget is None) != (level is None):
            raise EdltError('A preset edit requires both widget and level')
        if widget is not None: _int(widget, 'Preset widget', 6, 21); _int(level, 'Preset level')
        if type(synchronise) is not bool: raise EdltError('synchronise must be boolean')
        if synchronise and widget is None: raise EdltError('Synchronise requires a preset edit')
        if restore_mode not in (None, 'preset', 'previous'): raise EdltError('Unknown restore mode')
        if page_mode not in (None, 'single', 'multiple'): raise EdltError('Unknown page mode')
        cache = RestoreLevelCache.from_dict(metadata.as_dict() if isinstance(metadata, RestoreLevelCache) else metadata)
        base = self.lifecycle.plan(current, metadata=cache.lifecycle)
        values = dict(base.after_load)
        application_names = dict(cache.applications)
        group_names = {(a, g): n for a, g, n in cache.groups}
        names, consumed = {}, []
        # Binding inspects all16 functional widgets; refresh additionally visits
        # standby widgets. Positive facts avoid getter-driven group/label edits,
        # which are outside this deliberately narrow composition.
        for number in range(1, 22):
            if values[_field(number)][0] not in _RESTORE_TYPES:
                names[number] = ''; continue
            application = values['SecondaryApplication'][0] if values[_field(number, 1)][0] & 128 else values['PrimaryApplication'][0]
            group = values[_field(number, 6)][0]
            fact = cache.lifecycle.find(application, group)
            if fact is None or not fact.exists:
                raise LifecycleMetadataError('Preset controls require an explicitly present cached group',
                    {'application': application, 'group': group, 'widget': number,
                     'reason': 'Absent-group getter normalization is not implemented by this editor'}, original_stage='controls')
            if group == 255:
                names[number] = ''; continue
            if application not in application_names or (application, group) not in group_names:
                raise LifecycleMetadataError('Preset controls require exact cached display names',
                    {'application': application, 'group': group, 'widget': number,
                     'field': 'display_name'}, original_stage='controls')
            names[number] = application_names[application] + ' | ' + group_names[application, group]
            consumed.append(dict(widget=number, application=application, group=group, display_name=names[number]))
        if values['NavWidgetType'][0] > 1: values['NavWidgetType'] = (0,)
        if page_mode is not None: values['NavWidgetType'] = (int(page_mode == 'multiple'),)
        if restore_mode is not None: values['EnableLevelStore'] = (int(restore_mode == 'previous'),)
        preset = values['EnableLevelStore'] == (0,)
        limit = 21 if values['NavWidgetType'] == (1,) else 10
        controls, seen = [], set()
        for number in range(6, 22):
            name = names[number]
            controls.append(dict(widget=number, group_name=name, visible=preset and number <= limit and bool(name) and name not in seen))
            seen.add(name)
        targets = []
        if widget is not None:
            if not controls[widget - 6]['visible']:
                raise EdltError('Preset widget is hidden or previous-level restore is selected')
            if values[f'Widget{widget}RestoreLevel'] != (level,):
                targets = [n for n in range(6, 22) if synchronise or names[n] == names[widget]]
                for number in targets: values[f'Widget{number}RestoreLevel'] = (level,)
        after_controls = dict(values)
        # Only these fields commute with BeforeSave. In particular, preserve its
        # separately resolved scene objects, MRA source and type-change resets.
        final = dict(base.before_save)
        final['NavWidgetType'] = values['NavWidgetType']
        final['EnableLevelStore'] = values['EnableLevelStore']
        for number in range(6, 22):
            if base.after_load[_field(number)] == base.before_save[_field(number)]:
                final[f'Widget{number}RestoreLevel'] = values[f'Widget{number}RestoreLevel']
        before_save = dict(final); final.update(self.crcs(final))
        for control in controls:
            number = control['widget']
            control.update(level_after_controls=values[f'Widget{number}RestoreLevel'][0],
                           level_before_save=before_save[f'Widget{number}RestoreLevel'][0])
        options = dict(widget=widget, level=level, synchronise=synchronise, restore_mode=restore_mode, page_mode=page_mode)
        evidence = dict(controls=controls, control_count=16, changed_event_fired=bool(targets),
                        event_target_widgets=targets, display_name_facts=consumed,
                        synchronization_scope='all16constructedcontrols' if synchronise else 'exactdisplaystring',
                        lifecycle=base.as_dict(), model_edit_scope='preset controls on unchanged loaded widgets')
        return RestoreLevelsPlan(base.expected, base.after_load, after_controls, before_save,
            {k: v for k, v in final.items() if v != base.expected[k]}, cache, options, _json(evidence))

    @staticmethod
    def _interrupted(error, plan, attempted, original_error=None):
        evidence = {**plan.as_dict(), 'verified': False, 'saved': False,
                    'attempted_parameters': list(attempted), 'pp_state_uncertain': bool(attempted), 'automatic_retries': 0}
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': _error_text(original_error)}
        error.edlt_restore_levels_evidence = evidence

    def apply(self, session, plan):
        if type(plan) is not RestoreLevelsPlan or type(plan.metadata) is not RestoreLevelCache:
            raise EdltError('Use a preset plan returned by EdltRestoreLevels.plan')
        try: canonical = self.plan(plan.expected, metadata=plan.metadata, **plan.options)
        except TypeError as error: raise EdltError('Invalid preset plan options') from error
        if canonical != plan or _json(canonical.as_dict()) != _json(plan.as_dict()):
            raise EdltError('Plan differs from its validated preset controls')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the preset plan was made')
        expected = {**plan.expected, **plan.changes}; attempted = []
        try:
            for name, value in plan.changes.items(): attempted.append(name); session.set(name, _render(value))
            if self.snapshot(session.values()) != expected: raise EdltError('Native PP readback differs from the preset plan')
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
                interrupted.edlt_restore_levels_evidence['rollback_errors'] = rollback_errors; raise
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, **options):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), **options))
