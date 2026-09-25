"""Ordered multi-control composition for one retained eDLT parent form.

Each operation is first validated by the accepted standalone control model.
Only its declared bound-control bytes enter the retained loaded model.  The
complete control state then passes once through the lifecycle's terminal save
normalization and CRC projection before any database write can occur.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltApplyError, EdltError, EdltLighting, _field, _render
from .edlt_activation import EdltActivation, FIELDS as ACTIVATION_FIELDS
from .edlt_lifecycle import EdltLifecycle, LifecycleCache, _delta, _error_text, _json
from .edlt_measurement import EdltMeasurementWidget
from .edlt_parent_form import (
    ACTIVATION_OPTION_NAMES, BINDING_FACTS, MEASUREMENT_OPTION_NAMES,
    ORIGINAL_INITIALIZATION_ORDER, ORIGINAL_LOAD_WORKER_ORDER,
    ORIGINAL_SAVE_ORDER, ORIGINAL_SELECTION_BINDING_ORDER,
    PERCENTAGE_INITIALIZATION_ORDER,
)
from .edlt_percentage import byte_to_percentage, percentage_to_byte


MAX_OPERATIONS = 22
MIN_OPERATIONS = 2
LIGHTING_OPTION_NAMES = (
    'page', 'position', 'group', 'mode', 'application', 'page_mode',
    'label_type', 'label_index', 'label_text', 'status_type', 'status_index',
    'status_text', 'ramp_seconds', 'restore_level',
)
CRC_FIELDS = (
    'OverallCRC', 'GlobalParameterCRC', 'WidgetsCRC', 'StaticTextCRC',
    'ScenesCheckSum',
)
_ACTIVATION_PARAMETERS = tuple(dict.fromkeys(ACTIVATION_FIELDS.values()))
ORIGINAL_LIGHTING_SELECTION_BINDING_ORDER = (
    ('BaseWidget.SetWidgetData', 'FrmBaseUnit.ShowWidget'),
    ('BaseWidget.SetUpDataSource', 'LightingWidget.SetUpDataSource'),
    ('assign LightingData source', 'LightingWidget.SetUpDataSource'),
    ('ResetBindings(false)', 'LightingWidget.SetUpDataSource'),
)
LIGHTING_BINDING_FACTS = (
    ('Lighting.RampRate', 'OnValidation'),
    ('Lighting.Offset', 'OnValidation'),
    ('Lighting.TargetLevel1', 'OnValidation'),
    ('Lighting.RampRateEditable visibility', 'Never'),
    ('Lighting.OffsetEditable visibility', 'Never'),
    ('Lighting.TargetLevel1Editable visibility', 'Never'),
)


def _operation(value):
    if not isinstance(value, Mapping):
        raise EdltError('Parent transaction operation must be a mapping')
    operation = value.get('op')
    shapes = {
        'measurement': (MEASUREMENT_OPTION_NAMES,
                        ('page', 'position', 'device_id', 'channel')),
        'lighting': (LIGHTING_OPTION_NAMES,
                     ('page', 'position', 'group', 'mode')),
        'activation': (ACTIVATION_OPTION_NAMES, ()),
    }
    if operation not in shapes:
        raise EdltError('Parent transaction op must be measurement, lighting or activation')
    allowed, required = shapes[operation]
    unexpected = set(value) - {'op', *allowed}
    missing = set(required) - set(value)
    if unexpected:
        raise EdltError(
            operation + ' operation contains unsupported fields: ' +
            ', '.join(sorted(unexpected)))
    if missing:
        raise EdltError(
            operation + ' operation requires: ' + ', '.join(sorted(missing)))
    # A canonical key order makes plan identity independent of JSON key order.
    return {'op': operation, **{name: value[name] for name in allowed if name in value}}


def normalize_operations(operations):
    if not isinstance(operations, (tuple, list)):
        raise EdltError('Parent transaction operations must be an array')
    if not MIN_OPERATIONS <= len(operations) <= MAX_OPERATIONS:
        raise EdltError(
            f'Parent transaction requires {MIN_OPERATIONS}..{MAX_OPERATIONS} operations')
    result = tuple(_operation(value) for value in operations)
    if not any(value['op'] in ('measurement', 'lighting') for value in result):
        raise EdltError('Parent transaction requires at least one widget operation')
    return result


def _candidate_widget(operation, values):
    """Return a valid-looking target for early duplicate ownership checks."""
    page, position = operation.get('page'), operation.get('position')
    if type(page) is not int or type(position) is not int:
        return None
    mode = operation.get('page_mode')
    if mode is None:
        nav = values['NavWidgetType'][0]
        mode = 'multiple' if nav == 1 else 'single'
    if mode not in ('single', 'multiple'):
        return None
    if operation['op'] == 'measurement' and page == 0:
        return position if 1 <= position <= 5 else None
    if page < 1 or position < 1:
        return None
    if mode == 'single':
        return 5 + position if page == 1 and position <= 5 else None
    return 6 + (page - 1) * 4 + position - 1 if page <= 4 and position <= 4 else None


def _meaning(mode):
    if mode == 2:
        return 'primary-event-level'
    if mode == 3:
        return 'trigger-action-selector'
    return 'retained-hidden-value'


def _terminal_lifecycle_fields(after_controls, before_save):
    """Fields owned by the retained BeforeSavePPData projection."""
    fields = {
        'Application', 'SceneCount', 'SceneBucket',
        *(f'Scene{index}StartAddress' for index in range(1, 9)),
    }
    for widget in range(1, 22):
        kind = before_save[_field(widget)][0]
        if widget >= 6:
            fields.update((_field(widget), f'Widget{widget}RestoreLevel'))
        if kind in (4, 7, 8, 9, 16):
            fields.add(_field(widget, 1))
        if kind == 2:
            fields.add(_field(widget, 12))
        if kind == 5:
            fields.add(_field(widget, 9))
        if kind in (4, 16):
            fields.add(_field(widget, 10))
    return {name for name in fields if after_controls[name] != before_save[name]}


@dataclass(frozen=True)
class ParentTransactionPlan:
    expected: Mapping
    after_load: Mapping
    after_controls: Mapping
    before_save: Mapping
    changes: Mapping
    metadata: LifecycleCache
    operations: tuple[Mapping, ...]
    operation_results: tuple[str, ...]
    evidence: str

    def __post_init__(self):
        for name in ('expected', 'after_load', 'after_controls', 'before_save',
                     'changes'):
            object.__setattr__(self, name,
                               MappingProxyType(dict(getattr(self, name))))
        object.__setattr__(self, 'operations', tuple(
            MappingProxyType(dict(value)) for value in self.operations))

    def as_dict(self):
        final = {**self.expected, **self.changes}
        return {
            'format': 'cbus-edlt-parent-transaction-plan-v1',
            'scope': 'ordered Measurement, Lighting and proximity activation controls',
            'unit_type': 'KEYGL5', 'catalog_number': '5055EDL',
            'firmware': '5.5.00',
            'operations': [dict(value) for value in self.operations],
            'operation_results': [json.loads(value)
                                  for value in self.operation_results],
            'phases': {
                'after_load': _delta(self.expected, self.after_load),
                'controls': _delta(self.after_load, self.after_controls),
                'before_save': _delta(self.after_controls, self.before_save),
                'crc': _delta(self.before_save, final),
            },
            'changes': {
                name: list(value) if isinstance(value, tuple) else value
                for name, value in self.changes.items()
            },
            **json.loads(self.evidence),
            'metadata_provenance': 'caller-supplied-cache',
            'database_metadata_created': False,
            'cache_freshness_verified': False,
            'native_parent_form_executed': False,
            'native_multi_edit_parent_form_executed': False,
            'physical_device_verified': False,
            'saved': False,
        }


class EdltParentTransaction:
    """Compose distinct bound controls into one database PP transaction."""

    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.lifecycle = EdltLifecycle(
            spec, catalog_number=catalog_number, firmware=firmware)
        self.measurement_editor = EdltMeasurementWidget(
            spec, catalog_number=catalog_number, firmware=firmware)
        self.lighting_editor = EdltLighting(
            spec, catalog_number=catalog_number, firmware=firmware)
        self.activation_editor = EdltActivation(
            spec, catalog_number=catalog_number, firmware=firmware)
        self.common = self.lifecycle.common
        self.spec, self.codec = self.common.spec, self.common.codec

    def snapshot(self, values):
        return self.common.snapshot(values)

    @staticmethod
    def operations(operations):
        return normalize_operations(operations)

    @staticmethod
    def _claim(owners, parameters, owner):
        duplicates = sorted(parameter for parameter in parameters
                            if parameter in owners)
        if duplicates:
            previous = owners[duplicates[0]]
            raise EdltError(
                'Duplicate or conflicting byte ownership between ' + previous +
                ' and ' + owner + ': ' + ', '.join(duplicates))
        owners.update((parameter, owner) for parameter in parameters)

    @staticmethod
    def _allocations(plan):
        if hasattr(plan, 'allocations'):
            return tuple(value for value in plan.allocations.values()
                         if value is not None)
        return tuple(value for value in
                     (plan.static_allocation, plan.status_allocation)
                     if value is not None)

    def plan(self, current, *, metadata, operations):
        operations = normalize_operations(operations)
        cache = LifecycleCache.from_dict(
            metadata.as_dict() if isinstance(metadata, LifecycleCache) else metadata)
        loaded = self.lifecycle.load(current, metadata=cache)
        control_values = dict(loaded.after_load)
        planning_values = dict(loaded.after_load)
        owners, slots, results, selected = {}, {}, [], []
        navigation_mode = None
        activation_seen = False
        validation_placement_projections = 0

        for number, operation in enumerate(operations, 1):
            kind = operation['op']
            owner = f'operation {number} ({kind})'
            options = {name: value for name, value in operation.items()
                       if name != 'op'}
            if kind in ('measurement', 'lighting'):
                candidate = _candidate_widget(operation, planning_values)
                if candidate is not None and candidate in slots:
                    raise EdltError(
                        f'Duplicate widget byte ownership for widget{candidate}: '
                        f'{slots[candidate]} and {owner}')
                editor = (self.measurement_editor if kind == 'measurement'
                          else self.lighting_editor)
                widget_plan = editor.plan(planning_values, **options)
                widget = widget_plan.widget
                if widget in slots:
                    raise EdltError(
                        f'Duplicate widget byte ownership for widget{widget}: '
                        f'{slots[widget]} and {owner}')
                if navigation_mode is None:
                    navigation_mode = widget_plan.page_mode
                    self._claim(owners, ('NavWidgetType',),
                                'transaction navigation constraint')
                elif navigation_mode != widget_plan.page_mode:
                    raise EdltError(
                        'Conflicting page-mode ownership: ' + navigation_mode +
                        ' and ' + widget_plan.page_mode)
                slots[widget] = owner
                record_fields = tuple(_field(widget, offset)
                                      for offset in range(32))
                claimed = list(record_fields)
                if widget >= 6:
                    claimed.append(f'Widget{widget}RestoreLevel')
                self._claim(owners, claimed, owner)
                for offset, value in enumerate(widget_plan.record):
                    control_values[_field(widget, offset)] = (value,)
                projected = {**widget_plan.expected, **widget_plan.changes}
                if widget >= 6:
                    control_values[f'Widget{widget}RestoreLevel'] = projected[
                        f'Widget{widget}RestoreLevel']
                allocation_fields = []
                for allocation in self._allocations(widget_plan):
                    self._claim(owners, allocation.changes, owner)
                    control_values.update(allocation.changes)
                    allocation_fields.extend(allocation.changes)
                control_values['NavWidgetType'] = (
                    1 if navigation_mode == 'multiple' else 0,)
                # Standalone planners serialize their own selected record.  A
                # normalized validation view lets the next distinct editor see
                # that model without making it the transaction's terminal save.
                planning_values = self.common._place_record(
                    control_values, widget, widget_plan.record,
                    normalize_mra=False)
                if widget >= 6:
                    planning_values[f'Widget{widget}RestoreLevel'] = \
                        control_values[f'Widget{widget}RestoreLevel']
                planning_values['NavWidgetType'] = control_values['NavWidgetType']
                validation_placement_projections += 1
                selected.append((widget, kind))
                document = widget_plan.as_dict()
                document.update({
                    'operation': number,
                    'composition_role': 'validated bound-control projection',
                    'owned_parameters': sorted(claimed + allocation_fields),
                    'standalone_changes_applied_directly': False,
                })
                results.append(_json(document))
                continue

            if activation_seen:
                raise EdltError(
                    'Duplicate or conflicting byte ownership: only one activation '
                    'operation may own the proximity controls')
            activation_seen = True
            self._claim(owners, _ACTIVATION_PARAMETERS, owner)
            percent = options.pop('level_percent', None)
            level = None
            if percent is not None:
                try:
                    level = percentage_to_byte(percent)
                except ValueError as error:
                    raise EdltError(str(error)) from error
            activation_plan = self.activation_editor.plan(
                planning_values, level=level, **options)
            projected = {**activation_plan.expected, **activation_plan.changes}
            before_mode = control_values['ProximityMode'][0]
            before_level = control_values['ProximityLevel'][0]
            for parameter in _ACTIVATION_PARAMETERS:
                control_values[parameter] = projected[parameter]
                planning_values[parameter] = projected[parameter]
            after_mode = control_values['ProximityMode'][0]
            after_level = control_values['ProximityLevel'][0]
            percentage = {
                'input': percent, 'raw_byte': level,
                'bound_raw_before': before_level,
                'bound_percentage_before': byte_to_percentage(before_level),
                'bound_raw_after': after_level,
                'bound_percentage_after': byte_to_percentage(after_level),
                'meaning_before': _meaning(before_mode),
                'meaning_after': _meaning(after_mode),
                'visible_after': after_mode == 2,
                'binding_update_mode': 'OnValidation',
                'conversion_before_mutation': True,
            }
            document = activation_plan.as_dict()
            document.update({
                'operation': number, 'percentage': percentage,
                'composition_role': 'validated parent binding projection',
                'owned_parameters': sorted(_ACTIVATION_PARAMETERS),
                'standalone_changes_applied_directly': False,
            })
            results.append(_json(document))

        after_controls = self.snapshot(control_values)
        changed_controls = {
            name for name in after_controls
            if after_controls[name] != loaded.after_load[name]
        }
        unexpected_controls = changed_controls - set(owners)
        if unexpected_controls:
            raise EdltError(
                'Control composition changed unowned fields: ' +
                ', '.join(sorted(unexpected_controls)))

        # This is the transaction's sole terminal save normalization and CRC
        # pass.  Standalone editor plans above are validation projections only.
        lifecycle_plan = self.lifecycle._prepare_composed_save(
            loaded, after_controls)
        before_save = lifecycle_plan.before_save
        final = {**lifecycle_plan.expected, **lifecycle_plan.changes}
        lifecycle_document = lifecycle_plan.as_dict()
        calculated_crc_fields = lifecycle_document.get('crc_fields_calculated', ())
        if set(calculated_crc_fields) != set(CRC_FIELDS):
            raise EdltError('Terminal transaction did not calculate exactly five CRC fields')
        crc_delta = {
            name for name in final if final[name] != before_save[name]
        }
        if not crc_delta <= set(CRC_FIELDS):
            raise EdltError('Terminal CRC calculation changed a non-CRC field')
        terminal_delta = {
            name for name in before_save
            if before_save[name] != after_controls[name]
        }
        lifecycle_fields = _terminal_lifecycle_fields(after_controls, before_save)
        unexpected_terminal = terminal_delta - lifecycle_fields
        if unexpected_terminal:
            raise EdltError(
                'Terminal lifecycle changed an unrelated field: ' +
                ', '.join(sorted(unexpected_terminal)))

        evidence = {
            'form_initialization': [
                {'order': index, 'event': event, 'source_method': source}
                for index, (event, source) in
                enumerate(ORIGINAL_INITIALIZATION_ORDER, 1)
            ],
            'load_worker': [
                {'order': index, 'event': event, 'source_method': source}
                for index, (event, source) in
                enumerate(ORIGINAL_LOAD_WORKER_ORDER, 1)
            ],
            'selection_binding': [
                {'order': index, 'event': event, 'source_method': source}
                for index, (event, source) in
                enumerate(ORIGINAL_SELECTION_BINDING_ORDER, 1)
            ],
            'lighting_selection_binding': [
                {'order': index, 'event': event, 'source_method': source}
                for index, (event, source) in
                enumerate(ORIGINAL_LIGHTING_SELECTION_BINDING_ORDER, 1)
            ],
            'percentage_initialization': [
                {'order': index, 'event': event, 'source_method': source}
                for index, (event, source) in
                enumerate(PERCENTAGE_INITIALIZATION_ORDER, 1)
            ],
            'bindings': [
                {'property': name, 'update_mode_and_events': mode}
                for name, mode in BINDING_FACTS
            ],
            'lighting_bindings': [
                {'property': name, 'update_mode': mode}
                for name, mode in LIGHTING_BINDING_FACTS
            ],
            'original_save_order': list(ORIGINAL_SAVE_ORDER),
            'transaction_order': [
                'validate exact profile, complete snapshot, lifecycle cache and operation grammar',
                'load one retained parent model',
                'validate ordered distinct control projections and byte ownership',
                'enter every validated control into the retained model',
                'run one terminal BeforeSavePPData normalization and five-CRC calculation',
                'verify canonical plan and stale source before one parameter-write pass',
                'verify one complete PP readback; rollback once in reverse write order on failure',
                'caller performs one database SAVE after verified apply',
            ],
            'transaction_guards': {
                'minimum_operations': MIN_OPERATIONS,
                'maximum_operations': MAX_OPERATIONS,
                'distinct_widget_slots': sorted(slots),
                'navigation_mode': navigation_mode,
                'activation_operations': int(activation_seen),
                'duplicate_or_conflicting_byte_ownership_rejected': True,
                'all_controls_validated_before_first_pp_write': True,
            },
            'execution_counts': {
                'retained_load_models': 1,
                'standalone_validation_placement_projections':
                    validation_placement_projections,
                'terminal_normalization_passes': 1,
                'terminal_crc_passes': 1,
                'apply_parameter_write_passes': 1,
                'full_readback_passes': 1,
                'database_save_calls_by_apply': 0,
                'database_save_calls_per_successful_non_dry_run': 1,
                'database_save_calls_for_offline_or_dry_run': 0,
            },
            'ownership': {
                'parameters': [
                    {'parameter': parameter, 'owner': owner}
                    for parameter, owner in sorted(owners.items())
                ],
                'navigation_is_one_reconciled_parent_constraint': True,
                'crc_fields_owned_by_terminal_serializer': list(CRC_FIELDS),
            },
            'preservation': {
                'full_snapshot_parameters': len(final),
                'control_fields_changed': sorted(changed_controls),
                'unowned_control_fields_preserved_exactly': True,
                'terminal_lifecycle_fields_changed': sorted(terminal_delta),
                'terminal_changes_owned_by_retained_lifecycle': True,
                'selected_widget_slots': [
                    {'widget': widget, 'type': kind}
                    for widget, kind in selected
                ],
                'retained_scene_models': True,
                'retained_mra_source': True,
                'untouched_widget_and_parent_fields_preserved': True,
            },
            'source_evidence_fixture':
                'research/fixtures/edlt-parent-transaction-evidence.json',
            'original_source_sequence_pinned': True,
            'reused_original_measurement_probe': True,
            'reused_original_lighting_probe': True,
            'reused_original_percentage_control_probe': True,
            'python_multi_edit_composition_verified': True,
            'native_database_multi_edit_verified': False,
            'winforms_multi_selection_and_dialog_behavior_verified': False,
            'write_order': list(lifecycle_plan.changes),
            'lifecycle': lifecycle_document,
        }
        return ParentTransactionPlan(
            loaded.expected, loaded.after_load, after_controls, before_save,
            lifecycle_plan.changes, cache, operations, tuple(results),
            _json(evidence))

    @staticmethod
    def _interrupted(error, plan, attempted, original_error=None):
        evidence = {
            **plan.as_dict(), 'verified': False, 'saved': False,
            'attempted_parameters': list(attempted),
            'pp_state_uncertain': bool(attempted), 'automatic_retries': 0,
        }
        if original_error is not None:
            evidence['original_error'] = {
                'type': type(original_error).__name__,
                'error': _error_text(original_error),
            }
        error.edlt_parent_transaction_evidence = evidence

    def apply(self, session, plan):
        if (type(plan) is not ParentTransactionPlan or
                type(plan.metadata) is not LifecycleCache):
            raise EdltError('Use a plan returned by EdltParentTransaction.plan')
        for values in (plan.expected, plan.after_load, plan.after_controls,
                       plan.before_save, {**plan.expected, **plan.changes}):
            self.snapshot(values)
        try:
            canonical = self.plan(
                plan.expected, metadata=plan.metadata,
                operations=plan.operations)
        except TypeError as error:
            raise EdltError('Invalid parent transaction plan options') from error
        if canonical != plan or _json(canonical.as_dict()) != _json(plan.as_dict()):
            raise EdltError('Plan differs from its validated parent transaction')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the parent transaction was made')
        expected = {**plan.expected, **plan.changes}
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            readback = session.values()
            if self.snapshot(readback) != expected:
                raise EdltError('Native PP readback differs from the parent transaction')
        except (KeyboardInterrupt, SystemExit) as error:
            self._interrupted(error, plan, attempted)
            raise
        except Exception as error:
            rollback_errors = []
            try:
                for name in reversed(attempted):
                    if not getattr(session.programmer.client, 'connected', True):
                        rollback_errors.append(
                            'Connection lost; rollback stopped without recovery I/O; '
                            'PP state is uncertain')
                        break
                    try:
                        session.set(name, _render(plan.expected[name]))
                    except Exception as rollback:
                        rollback_errors.append(_error_text(rollback))
                if getattr(session.programmer.client, 'connected', True):
                    try:
                        if self.snapshot(session.values()) != dict(plan.expected):
                            rollback_errors.append(
                                'Original PP values could not be verified')
                    except Exception as rollback:
                        rollback_errors.append(_error_text(rollback))
            except (KeyboardInterrupt, SystemExit) as interrupted:
                self._interrupted(interrupted, plan, attempted, error)
                interrupted.edlt_parent_transaction_evidence[
                    'rollback_errors'] = rollback_errors
                raise
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True, 'parameters': readback}

    def configure(self, session, *, metadata, operations):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(
            session.values(), metadata=metadata, operations=operations))
