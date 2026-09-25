"""Bounded eDLT parent-form composition for Measurement and Percentage.

The original form constructs and binds many more controls than this module
edits.  This composition deliberately covers one Measurement panel and the
unit-wide proximity percentage control on the exact KEYGL5/5055EDL 5.5.00
profile.  It retains the loaded lifecycle models through BeforeSavePPData and
reports, rather than simulates, the source-pinned WinForms event boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltApplyError, EdltError, _field, _render
from .edlt_activation import EdltActivation, FIELDS as ACTIVATION_FIELDS
from .edlt_lifecycle import EdltLifecycle, LifecycleCache, _delta, _error_text, _json
from .edlt_measurement import EdltMeasurementWidget, MeasurementWidgetPlan
from .edlt_percentage import byte_to_percentage, percentage_to_byte


MEASUREMENT_OPTION_NAMES = (
    'page', 'position', 'device_id', 'channel', 'decimal_places',
    'gain_mantissa', 'gain_exponent', 'offset_mantissa', 'offset_exponent',
    'gain_value', 'offset_value', 'measurement_culture', 'page_mode',
    'prefix_text', 'prefix_index', 'suffix_text', 'suffix_index',
    'label_text', 'label_index', 'icon_index',
)
ACTIVATION_OPTION_NAMES = (
    'wake_mode', 'group', 'level_percent', 'action', 'activation_page',
    'ignore_first_key_press',
)


# These ordered records are source facts, not a claim that this Python module
# executed the original WinForms form.  The exact sources and hashes are kept
# in research/fixtures/edlt-parent-form-evidence.json.
ORIGINAL_INITIALIZATION_ORDER = (
    ('schedule BackgroundWorker.LoadUnitThreadMain', 'FrmBaseUnit.LoadUnit'),
    ('InitializeComponent', 'FrmBaseUnit.SetEDLTFrm'),
    ('bind base unit and network sources', 'FrmBaseUnit.SetEDLTFrm'),
    ('PopulateWidgetPanels', 'FrmBaseUnit.SetEDLTFrm'),
    ('SetUpControls', 'FrmBaseUnit.SetEDLTFrm'),
    ('SetupForm', 'FrmBaseUnit.SetEDLTFrm'),
)
ORIGINAL_LOAD_WORKER_ORDER = (
    ('ReadPPData', 'CBusBaseUnit.LoadUnit'),
    ('AfterLoadPPData', 'CBusBaseUnit.LoadUnit'),
    ('CreateUnitLogic', 'CBusBaseUnit.LoadUnit'),
    ('LoadSucceeded assignment', 'CBusBaseUnit.LoadUnit'),
    ('OnLoadCompleted', 'FrmBaseUnit.LoadUnit'),
)
ORIGINAL_SELECTION_BINDING_ORDER = (
    ('BaseWidget.SetWidgetData', 'FrmBaseUnit.ShowWidget'),
    ('BaseWidget.SetUpDataSource', 'BaseWidget.SetWidgetData'),
    ('MeasurementWidget.SetUpDataSource', 'MeasurementWidget.SetUpDataSource'),
)
PERCENTAGE_INITIALIZATION_ORDER = (
    ('construct NumUpDownPercentage and wire internal SelectAll handlers', 'FrmBaseUnit.InitializeComponent / NumUpDownPercentage constructor'),
    ('BeginInit', 'FrmBaseUnit.InitializeComponent'),
    ('bind PercentageValueAsByte to ProximityLevel', 'FrmBaseUnit.InitializeComponent'),
    ('assign PercentageValueAsByte=2', 'FrmBaseUnit.InitializeComponent'),
    ('assign NumericUpDown.Value=1', 'FrmBaseUnit.InitializeComponent'),
    ('EndInit', 'FrmBaseUnit.InitializeComponent'),
    ('assign bsMainUnit.DataSource to EDLTUnit', 'FrmBaseUnit.SetEDLTFrm'),
    ('binding reads loaded/current ProximityLevel', 'WinForms Binding'),
)
ORIGINAL_SAVE_ORDER = (
    'active control validation and default OnValidation binding write',
    'FrmBaseUnit.ValidateSerialNumber',
    'FrmBaseUnit.ValidateSceneWidgetConfig',
    'EDLTUnit.IsValid',
    'FrmBaseUnit.saveUnitDialogRequest',
    'FrmBaseUnit.SaveUnitThreadMain',
    'CBusBaseUnit.SaveUnit',
    'EDLTUnit.BeforeSavePPData',
    'configuration CRC calculation',
    'database persistence',
)
BINDING_FACTS = (
    ('Measurement.BigIconIndex', 'OnPropertyChanged'),
    ('Measurement.Precision', 'OnPropertyChanged'),
    ('Measurement.Channel', 'OnValidation'),
    ('Measurement.DeviceID', 'OnValidation'),
    ('Measurement.Prefix', 'OnValidation'),
    ('Measurement.Suffix', 'OnValidation'),
    ('Measurement.FunctionStatus', 'OnValidation'),
    ('Measurement.GainComposite', 'OnValidation; TextChanged, Enter, Validating handlers'),
    ('Measurement.OffsetComposite', 'OnValidation; TextChanged, Enter, Validating handlers'),
    ('ProximityMode', 'OnPropertyChanged'),
    ('ProximityActionSelector.SelectedValue -> ProximityLevel', 'OnValidation'),
    ('ProximityLevel.PercentageValueAsByte', 'OnValidation'),
)


def _mapping(value, *, name, allowed, required=()):
    if not isinstance(value, Mapping):
        raise EdltError(name + ' options must be a mapping')
    value = dict(value)
    unexpected = set(value) - set(allowed)
    missing = set(required) - set(value)
    if unexpected:
        raise EdltError(name + ' options contain unsupported fields: ' + ', '.join(sorted(unexpected)))
    if missing:
        raise EdltError(name + ' options require: ' + ', '.join(sorted(missing)))
    return value


@dataclass(frozen=True)
class ParentFormPlan:
    expected: Mapping
    after_load: Mapping
    after_controls: Mapping
    before_save: Mapping
    changes: Mapping
    metadata: LifecycleCache
    measurement: MeasurementWidgetPlan
    measurement_options: Mapping
    activation_options: Mapping
    activation_document: str
    evidence: str

    def __post_init__(self):
        for name in ('expected', 'after_load', 'after_controls', 'before_save',
                     'changes', 'measurement_options', 'activation_options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        final = {**self.expected, **self.changes}
        evidence = json.loads(self.evidence)
        activation = json.loads(self.activation_document)
        measurement = self.measurement.as_dict()
        measurement['composition_role'] = (
            'validated control record, static allocations and selected restore value')
        measurement['standalone_changes_applied_directly'] = False
        return {
            'format': 'cbus-edlt-parent-form-plan-v1',
            'scope': 'Measurement widget plus proximity Percentage control',
            'unit_type': 'KEYGL5', 'catalog_number': '5055EDL', 'firmware': '5.5.00',
            'phases': {
                'after_load': _delta(self.expected, self.after_load),
                'controls': _delta(self.after_load, self.after_controls),
                'before_save': _delta(self.after_controls, self.before_save),
                'crc': _delta(self.before_save, final),
            },
            'changes': {name: list(value) if isinstance(value, tuple) else value
                        for name, value in self.changes.items()},
            'measurement': measurement,
            'activation': activation,
            **evidence,
            'metadata_provenance': 'caller-supplied-cache',
            'database_metadata_created': False,
            'cache_freshness_verified': False,
            'native_parent_form_executed': False,
            'physical_device_verified': False,
            'saved': False,
        }


class EdltParentForm:
    """Compose the retained lifecycle with two source-pinned parent controls."""

    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.lifecycle = EdltLifecycle(spec, catalog_number=catalog_number, firmware=firmware)
        self.measurement_editor = EdltMeasurementWidget(
            spec, catalog_number=catalog_number, firmware=firmware)
        self.activation_editor = EdltActivation(
            spec, catalog_number=catalog_number, firmware=firmware)
        self.common = self.lifecycle.common
        self.spec, self.codec = self.common.spec, self.common.codec

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def plan(self, current, *, metadata, measurement, activation=None):
        measurement_options = _mapping(
            measurement, name='Measurement', allowed=MEASUREMENT_OPTION_NAMES,
            required=('page', 'position', 'device_id', 'channel'))
        activation_options = _mapping(
            {} if activation is None else activation, name='Activation',
            allowed=ACTIVATION_OPTION_NAMES)
        activation_options = {name: activation_options.get(name)
                              for name in ACTIVATION_OPTION_NAMES}

        cache = LifecycleCache.from_dict(
            metadata.as_dict() if isinstance(metadata, LifecycleCache) else metadata)
        loaded = self.lifecycle.load(current, metadata=cache)

        # Every supplied control is validated before the session can be
        # mutated.  Gain is resolved before Offset by Measurement.plan.
        measurement_plan = self.measurement_editor.plan(
            loaded.after_load, **measurement_options)
        values = dict(loaded.after_load)
        widget = measurement_plan.widget
        for offset, value in enumerate(measurement_plan.record):
            values[_field(widget, offset)] = (value,)
        if widget >= 6:
            values[f'Widget{widget}RestoreLevel'] = (measurement_plan.restore_level,)
        values['NavWidgetType'] = (1 if measurement_plan.page_mode == 'multiple' else 0,)
        allocation_fields = set()
        for allocation in measurement_plan.allocations.values():
            if allocation is not None:
                values.update(allocation.changes)
                allocation_fields.update(allocation.changes)
        after_measurement = dict(values)

        level_percent = activation_options['level_percent']
        level = None
        if level_percent is not None:
            try:
                level = percentage_to_byte(level_percent)
            except ValueError as error:
                raise EdltError(str(error)) from error
        activation_plan = self.activation_editor.plan(
            after_measurement,
            wake_mode=activation_options['wake_mode'],
            group=activation_options['group'], level=level,
            action=activation_options['action'],
            activation_page=activation_options['activation_page'],
            ignore_first_key_press=activation_options['ignore_first_key_press'])
        for parameter in set(ACTIVATION_FIELDS.values()):
            if parameter in activation_plan.changes:
                values[parameter] = activation_plan.changes[parameter]
        after_controls = dict(values)

        # Lifecycle.prepare_save owns retained scenes, MRA model identity and
        # every unrelated save hook.  Overlay only the validated controls on
        # its terminal projection, then repeat placement because a new
        # functional Measurement can move the serialized terminator.
        lifecycle_plan = self.lifecycle.prepare_save(loaded)
        terminal = dict(lifecycle_plan.before_save)
        terminal = self.common._place_record(
            terminal, widget, measurement_plan.record, normalize_mra=False)
        if widget >= 6:
            terminal[f'Widget{widget}RestoreLevel'] = (measurement_plan.restore_level,)
        terminal['NavWidgetType'] = after_controls['NavWidgetType']
        for parameter in allocation_fields:
            terminal[parameter] = after_controls[parameter]
        for parameter in set(ACTIVATION_FIELDS.values()):
            terminal[parameter] = after_controls[parameter]
        terminal['Application'] = (
            terminal['PrimaryApplication'][0], terminal['SecondaryApplication'][0])
        before_save = self.snapshot(terminal)
        final = dict(before_save)
        final.update(self.crcs(final))

        crc_fields = set(self.crcs(before_save))
        selected_fields = {_field(widget, offset) for offset in range(32)}
        if widget >= 6:
            selected_fields.add(f'Widget{widget}RestoreLevel')
        control_fields = (selected_fields | allocation_fields | {'NavWidgetType'} |
                          set(ACTIVATION_FIELDS.values()))
        terminator_fields = {
            name for number in range(6, 22)
            for name in (_field(number), f'Widget{number}RestoreLevel')
        }
        base_final = {**lifecycle_plan.expected, **lifecycle_plan.changes}
        composition_delta = {name for name in final if final[name] != base_final[name]}
        unexpected = composition_delta - control_fields - terminator_fields - crc_fields
        if unexpected:
            raise EdltError('Parent composition changed unrelated fields: ' + ', '.join(sorted(unexpected)))
        for name in after_controls:
            if name not in control_fields and after_controls[name] != loaded.after_load[name]:
                raise EdltError('Control phase changed unrelated field: ' + name)

        old_mode = loaded.after_load['ProximityMode'][0]
        new_mode = after_controls['ProximityMode'][0]
        old_value = loaded.after_load['ProximityLevel'][0]
        new_value = after_controls['ProximityLevel'][0]
        meaning = lambda mode: 'primary-event-level' if mode == 2 else (
            'trigger-action-selector' if mode == 3 else 'retained-hidden-value')
        percentage = {
            'input': level_percent,
            'raw_byte': level,
            'bound_raw_before': old_value,
            'bound_percentage_before': byte_to_percentage(old_value),
            'bound_raw_after': new_value,
            'bound_percentage_after': byte_to_percentage(new_value),
            'meaning_before': meaning(old_mode),
            'meaning_after': meaning(new_mode),
            'visible_after': new_mode == 2,
            'binding_update_mode': 'OnValidation',
            'conversion_before_mutation': True,
        }
        activation_document = activation_plan.as_dict()
        activation_document['percentage'] = percentage
        activation_document['composition_fields_applied'] = sorted(set(ACTIVATION_FIELDS.values()))
        activation_document['standalone_changes_applied_directly'] = False

        changes = {name: value for name, value in final.items()
                   if value != loaded.expected[name]}
        evidence = {
            'form_initialization': [
                {'order': index, 'event': event, 'source_method': source}
                for index, (event, source) in enumerate(ORIGINAL_INITIALIZATION_ORDER, 1)
            ],
            'load_worker': [
                {'order': index, 'event': event, 'source_method': source}
                for index, (event, source) in enumerate(ORIGINAL_LOAD_WORKER_ORDER, 1)
            ],
            'selection_binding': [
                {'order': index, 'event': event, 'source_method': source}
                for index, (event, source) in enumerate(ORIGINAL_SELECTION_BINDING_ORDER, 1)
            ],
            'percentage_initialization': [
                {'order': index, 'event': event, 'source_method': source}
                for index, (event, source) in enumerate(PERCENTAGE_INITIALIZATION_ORDER, 1)
            ],
            'initialization_concurrency': {
                'worker_scheduled_before_SetEDLTFrm': True,
                'worker_completion_relative_to_form_construction_fixed_by_source': False,
                'python_plan_order': 'complete retained AfterLoad model before deterministic control binding projection',
            },
            'bindings': [{'property': name, 'update_mode_and_events': mode}
                         for name, mode in BINDING_FACTS],
            'original_save_order': list(ORIGINAL_SAVE_ORDER),
            'cli_order': [
                'validate exact profile and complete source snapshot',
                'load retained model using explicit cache facts',
                'validate complete Measurement edit (Gain before Offset)',
                'convert and validate Percentage and activation visibility',
                'compose retained BeforeSavePPData projection',
                'calculate all five configuration CRCs',
                'verify canonical plan and stale source before writes',
                'write deterministic parameter sequence and verify full readback',
                'caller performs database SAVE after verified apply',
            ],
            'validation_boundary': {
                'original': 'Save validates the active WinForms control through CausesValidation, then serial/unit validators; source does not call ValidateChildren for every inactive control',
                'cli': 'all supplied controls and lifecycle facts are validated before the first PP write',
                'per_keystroke_focus_caret_dialogs_modelled': False,
            },
            'cross_control': percentage,
            'preservation': {
                'full_snapshot_parameters': len(final),
                'control_fields': sorted(control_fields),
                'composition_delta_from_unedited_lifecycle': sorted(composition_delta),
                'unrelated_parameters_preserved': len(final) - len(composition_delta),
                'unrelated_fields_equal_unedited_lifecycle': True,
                'retained_scene_models': True,
                'retained_mra_source': True,
            },
            'source_evidence_fixture': 'research/fixtures/edlt-parent-form-evidence.json',
            'original_source_sequence_pinned': True,
            'reused_original_measurement_probe': True,
            'reused_original_percentage_control_probe': True,
            'python_composition_verified': True,
            'winforms_focus_and_dialog_behavior_verified': False,
            'database_save_reload_verified_for_composition': False,
            'write_order': list(changes),
            'lifecycle': lifecycle_plan.as_dict(),
        }
        return ParentFormPlan(
            loaded.expected, loaded.after_load, after_controls, before_save,
            changes, cache, measurement_plan, measurement_plan.options,
            activation_options, _json(activation_document), _json(evidence))

    @staticmethod
    def _interrupted(error, plan, attempted, original_error=None):
        evidence = {**plan.as_dict(), 'verified': False, 'saved': False,
                    'attempted_parameters': list(attempted),
                    'pp_state_uncertain': bool(attempted), 'automatic_retries': 0}
        if original_error is not None:
            evidence['original_error'] = {
                'type': type(original_error).__name__,
                'error': _error_text(original_error),
            }
        error.edlt_parent_form_evidence = evidence

    def apply(self, session, plan):
        if (type(plan) is not ParentFormPlan or type(plan.metadata) is not LifecycleCache or
                type(plan.measurement) is not MeasurementWidgetPlan):
            raise EdltError('Use a plan returned by EdltParentForm.plan')
        for values in (plan.expected, plan.after_load, plan.after_controls,
                       plan.before_save, {**plan.expected, **plan.changes}):
            self.snapshot(values)
        try:
            canonical = self.plan(
                plan.expected, metadata=plan.metadata,
                measurement=plan.measurement_options,
                activation=plan.activation_options)
        except TypeError as error:
            raise EdltError('Invalid parent-form plan options') from error
        if canonical != plan or _json(canonical.as_dict()) != _json(plan.as_dict()):
            raise EdltError('Plan differs from its validated parent-form composition')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the parent-form plan was made')
        expected = {**plan.expected, **plan.changes}
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the parent-form plan')
        except (KeyboardInterrupt, SystemExit) as error:
            self._interrupted(error, plan, attempted)
            raise
        except Exception as error:
            rollback_errors = []
            try:
                for name in reversed(attempted):
                    if not getattr(session.programmer.client, 'connected', True):
                        rollback_errors.append(
                            'Connection lost; rollback stopped without recovery I/O; PP state is uncertain')
                        break
                    try:
                        session.set(name, _render(plan.expected[name]))
                    except Exception as rollback:
                        rollback_errors.append(_error_text(rollback))
                if getattr(session.programmer.client, 'connected', True):
                    try:
                        if self.snapshot(session.values()) != dict(plan.expected):
                            rollback_errors.append('Original PP values could not be verified')
                    except Exception as rollback:
                        rollback_errors.append(_error_text(rollback))
            except (KeyboardInterrupt, SystemExit) as interrupted:
                self._interrupted(interrupted, plan, attempted, error)
                interrupted.edlt_parent_form_evidence['rollback_errors'] = rollback_errors
                raise
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, *, metadata, measurement, activation=None):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(
            session.values(), metadata=metadata, measurement=measurement,
            activation=activation))
