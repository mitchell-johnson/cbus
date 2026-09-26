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
from .edlt_colours import EdltColours, FIELDS as COLOUR_FIELDS
from .edlt_display import EdltDisplaySettings
from .edlt_enable import EdltEnableWidget
from .edlt_fan import EdltFanWidget
from .edlt_general import EdltGeneralSettings
from .edlt_hvac import EdltHVACTemperatureWidget
from .edlt_lifecycle import EdltLifecycle, LifecycleCache, _delta, _error_text, _json
from .edlt_measurement import EdltMeasurementWidget
from .edlt_multilevel import EdltMultiLevelWidget
from .edlt_navigation import EdltNavigation
from .edlt_page_control import EdltPageControl
from .edlt_parent_form import (
    ACTIVATION_OPTION_NAMES, BINDING_FACTS, MEASUREMENT_OPTION_NAMES,
    ORIGINAL_INITIALIZATION_ORDER, ORIGINAL_LOAD_WORKER_ORDER,
    ORIGINAL_SAVE_ORDER, ORIGINAL_SELECTION_BINDING_ORDER,
    PERCENTAGE_INITIALIZATION_ORDER,
)
from .edlt_percentage import byte_to_percentage, percentage_to_byte
from .edlt_quick_status import EdltQuickStatus, FIELDS as QUICK_STATUS_FIELDS
from .edlt_room_courtesy import EdltRoomCourtesyWidget
from .edlt_scene import EdltSceneWidget
from .edlt_shutter import EdltShutterWidget
from .edlt_standby import EdltStandby
from .edlt_time_date import EdltTimeDateWidget
from .edlt_timer import EdltTimerWidget


MAX_OPERATIONS = 22
MIN_OPERATIONS = 2
LIGHTING_OPTION_NAMES = (
    'page', 'position', 'group', 'mode', 'application', 'page_mode',
    'label_type', 'label_index', 'label_text', 'status_type', 'status_index',
    'status_text', 'ramp_seconds', 'restore_level',
)
ENABLE_OPTION_NAMES = (
    'page', 'position', 'variable', 'level', 'page_mode', 'label_type',
    'label_index', 'label_text', 'status_type', 'status_index', 'status_text',
)
FAN_OPTION_NAMES = (
    'page', 'position', 'group', 'application', 'speeds', 'low_threshold',
    'high_threshold', 'page_mode', 'label_type', 'label_index', 'label_text',
    'off_text', 'low_text', 'medium_text', 'high_text', 'off_index',
    'low_index', 'medium_index', 'high_index',
)
HVAC_OPTION_NAMES = (
    'page', 'position', 'group', 'zone', 'decimal_places', 'units',
    'icon_index', 'page_mode', 'label_text', 'label_index',
)
MULTILEVEL_OPTION_NAMES = (
    'page', 'position', 'group', 'application', 'levels', 'low_threshold',
    'high_threshold', 'page_mode', 'label_type', 'label_index', 'label_text',
    'off_text', 'low_text', 'medium_text', 'high_text', 'off_index',
    'low_index', 'medium_index', 'high_index',
)
ROOM_COURTESY_OPTION_NAMES = (
    'page', 'position', 'group', 'application', 'mode', 'off_colour',
    'on_colour', 'page_mode', 'label_type', 'label_index', 'label_text',
    'status_type', 'status_index', 'status_text',
)
SCENE_OPTION_NAMES = (
    'page', 'position', 'scene', 'page_mode', 'label_type', 'label_index',
    'status_type', 'status_index', 'status_text', 'mode', 'ramp_seconds',
    'offset', 'scenes', 'cycle_variant',
)
SHUTTER_OPTION_NAMES = (
    'page', 'position', 'group', 'application', 'mode', 'preset_left',
    'preset_right', 'page_mode', 'label_type', 'label_index', 'label_text',
    'status_type', 'status_index', 'status_text',
)
TIME_DATE_OPTION_NAMES = (
    'page', 'position', 'slices', 'display', 'page_mode', 'date_format',
    'time_format', 'leading_zero',
)
TIMER_OPTION_NAMES = (
    'page', 'position', 'group', 'application', 'duration_seconds',
    'target_level', 'expiry_level', 'ramp_seconds', 'page_mode', 'label_type',
    'label_index', 'label_text', 'status_type', 'status_index', 'status_text',
)
GENERAL_OPTION_NAMES = (
    'long_press_ms', 'debounce_ms', 'status_report_seconds',
    'tools_page_locked', 'power_restore',
)
DISPLAY_OPTION_NAMES = ('large_text', 'big_icons', 'timer_flash', 'fan_level_wrap')
STANDBY_OPTION_NAMES = (
    'enabled', 'after_seconds', 'destination', 'nightlight_user_keys',
    'nightlight_page_key', 'nightlight_colour',
)
COLOUR_OPTION_NAMES = tuple(COLOUR_FIELDS)
NAVIGATION_OPTION_NAMES = (
    'page_mode', 'variant', 'temperature_source', 'device_or_group',
    'channel_or_zone', 'dynamic_group', 'page_names', 'page_name_indices',
    'metadata',
)
QUICK_STATUS_OPTION_NAMES = (
    'mode', 'group', 'low_threshold', 'high_threshold', 'low_colour',
    'middle_colour', 'high_colour',
)
PAGE_CONTROL_OPTION_NAMES = ('group',)

WIDGET_OPERATION_NAMES = (
    'measurement', 'lighting', 'enable', 'fan', 'hvac', 'multilevel',
    'room-courtesy', 'scene', 'shutter', 'time-date', 'timer',
)
SETTING_OPERATION_NAMES = (
    'activation', 'general', 'display', 'standby', 'colours', 'navigation',
    'quick-status', 'page-control',
)
SUPPORTED_OPERATION_NAMES = WIDGET_OPERATION_NAMES + SETTING_OPERATION_NAMES

_OPERATION_SHAPES = {
    'measurement': (MEASUREMENT_OPTION_NAMES, ('page', 'position', 'device_id', 'channel')),
    'lighting': (LIGHTING_OPTION_NAMES, ('page', 'position', 'group', 'mode')),
    'enable': (ENABLE_OPTION_NAMES, ('page', 'position', 'variable', 'level')),
    'fan': (FAN_OPTION_NAMES, ('page', 'position', 'group')),
    'hvac': (HVAC_OPTION_NAMES, ('page', 'position', 'group')),
    'multilevel': (MULTILEVEL_OPTION_NAMES, ('page', 'position', 'group')),
    'room-courtesy': (ROOM_COURTESY_OPTION_NAMES, ('page', 'position', 'group')),
    'scene': (SCENE_OPTION_NAMES, ('page', 'position')),
    'shutter': (SHUTTER_OPTION_NAMES, ('page', 'position', 'group')),
    'time-date': (TIME_DATE_OPTION_NAMES, ('page', 'position')),
    'timer': (TIMER_OPTION_NAMES, ('page', 'position', 'group')),
    'activation': (ACTIVATION_OPTION_NAMES, ()),
    'general': (GENERAL_OPTION_NAMES, ()),
    'display': (DISPLAY_OPTION_NAMES, ()),
    'standby': (STANDBY_OPTION_NAMES, ()),
    'colours': (COLOUR_OPTION_NAMES, ()),
    'navigation': (NAVIGATION_OPTION_NAMES, ()),
    'quick-status': (QUICK_STATUS_OPTION_NAMES, ()),
    'page-control': (PAGE_CONTROL_OPTION_NAMES, ()),
}

_SETTING_FIELDS = {
    'general': ('LongPressTime', 'DebounceTime', 'StatusRequestInterval',
                'ToolsPageLocked', 'EnableLevelStore'),
    'display': ('FontStyle', 'UseBigIcon', 'EnableTimerFlash',
                'EnableFanControlLevelWrap'),
    'standby': ('ActivityDuration', 'TimeoutPage', 'EnableNightlightUserKey',
                'EnableNightlightPageKey', 'NightlightColour'),
    'colours': tuple(COLOUR_FIELDS.values()),
    'navigation': ('NavWidgetType', 'NavWidgetVariant', 'TemperatureApplication',
                   'NavDevIDZoneGroup', 'NavChannelZoneNumber', 'DynamicGroup',
                   *(f'PageNameIndex{page}' for page in range(1, 5))),
    'quick-status': tuple(QUICK_STATUS_FIELDS.values()),
    'page-control': ('KeySetsEnableGroup',),
}

PANEL_BINDING_SOURCES = {
    'measurement': 'MeasurementWidget.cs', 'lighting': 'LightingWidget.cs',
    'enable': 'EnableWidget.cs', 'fan': 'FanControlWidget.cs',
    'hvac': 'HVACTempWidget.cs', 'multilevel': 'MultiLevelWidget2.cs',
    'room-courtesy': 'RCAWidget.cs', 'scene': 'SceneWidget.cs',
    'shutter': 'ShutterRelayWidget.cs', 'time-date': 'TimeDateWidget2.cs',
    'timer': 'TimerWidget.cs', 'navigation': 'PageWidget.cs',
    'activation': 'FrmBaseUnit.cs', 'general': 'FrmBaseUnit.cs',
    'display': 'FrmBaseUnit.cs', 'standby': 'FrmBaseUnit.cs',
    'colours': 'FrmBaseUnit.cs', 'quick-status': 'FrmBaseUnit.cs',
    'page-control': 'FrmBaseUnit.cs',
}
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
    if operation not in _OPERATION_SHAPES:
        raise EdltError(
            'Parent transaction op must be one of: ' +
            ', '.join(SUPPORTED_OPERATION_NAMES))
    allowed, required = _OPERATION_SHAPES[operation]
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
    if not any(value['op'] in WIDGET_OPERATION_NAMES for value in result):
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
    if operation['op'] in ('measurement', 'hvac', 'time-date') and page == 0:
        return position if 1 <= position <= 5 else None
    if page < 1 or position < 1:
        return None
    if mode == 'single':
        return 5 + position if page == 1 and position <= 5 else None
    return 6 + (page - 1) * 4 + position - 1 if page <= 4 and position <= 4 else None


def _effective_primary(values):
    return 56 if values['PrimaryApplication'] == (255,) else values['PrimaryApplication'][0]


def _selected_application(values, record, kind):
    if kind == 'enable':
        return 203
    if kind == 'hvac':
        return 172
    if kind in ('lighting', 'fan', 'multilevel', 'room-courtesy',
                'shutter', 'timer'):
        if record[1] & 128:
            secondary = values['SecondaryApplication'][0]
            if secondary == 255:
                raise EdltError(kind + ' operation requires a configured secondary application')
            return secondary
        return _effective_primary(values)
    return None


def _static_changes(plan, projected):
    return {
        name: projected[name]
        for name in plan.changes
        if name.startswith('StaticTextString')
    }


_DYNAMIC_FIELD_OFFSETS = {
    'lighting': {'label': 13, 'status': 14},
    'enable': {'label': 11, 'status': 12},
    'fan': {'label': 9},
    'multilevel': {'label': 9},
    'room-courtesy': {'label': 8, 'status': 9},
    'scene': {'label': 11, 'status': 12},
    'shutter': {'label': 10, 'status': 11},
    'timer': {'label': 17, 'status': 18},
}


def _dynamic_requests(kind, record):
    """Return every effective text/icon binding that consumes metadata."""
    offsets = _DYNAMIC_FIELD_OFFSETS.get(kind, {})
    result = []
    for display in ('label', 'status'):
        if display not in offsets:
            continue
        code = ((record[1] >> 4) & 7) if display == 'label' else record[1] & 15
        dynamic_codes = {1: False, 2: True} if display == 'label' else {
            6: False, 7: True,
        }
        if code in dynamic_codes:
            result.append((display, record[offsets[display]],
                           dynamic_codes[code]))
    return tuple(result)


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
            'scope': ('ordered non-MRA widget panels and direct unit settings '
                      'through one retained parent save'),
            'unit_type': 'KEYGL5', 'catalog_number': '5055EDL',
            'firmware': '5.5.00',
            'operations': [dict(value) for value in self.operations],
            'supported_operation_types': list(SUPPORTED_OPERATION_NAMES),
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
        self._profile = (spec, catalog_number, firmware)
        self._extended_editors = {}
        self.common = self.lifecycle.common
        self.spec, self.codec = self.common.spec, self.common.codec

    def snapshot(self, values):
        return self.common.snapshot(values)

    def _editor(self, kind):
        """Construct an extended panel editor only when its operation is used.

        Older retained synthetic fixtures intentionally contain only the
        Measurement/Lighting/activation schema. Lazy construction preserves
        that compatibility while each selected extended panel still validates
        every one of its exact KEYGL5 layouts before planning.
        """
        if kind in self._extended_editors:
            return self._extended_editors[kind]
        classes = {
            'enable': EdltEnableWidget, 'fan': EdltFanWidget,
            'hvac': EdltHVACTemperatureWidget,
            'multilevel': EdltMultiLevelWidget,
            'room-courtesy': EdltRoomCourtesyWidget,
            'scene': EdltSceneWidget, 'shutter': EdltShutterWidget,
            'time-date': EdltTimeDateWidget, 'timer': EdltTimerWidget,
            'general': EdltGeneralSettings, 'display': EdltDisplaySettings,
            'standby': EdltStandby, 'colours': EdltColours,
            'navigation': EdltNavigation, 'quick-status': EdltQuickStatus,
            'page-control': EdltPageControl,
        }
        spec, catalog_number, firmware = self._profile
        editor = classes[kind](
            spec, catalog_number=catalog_number, firmware=firmware)
        self._extended_editors[kind] = editor
        return editor

    @staticmethod
    def operations(operations):
        return normalize_operations(operations)

    @staticmethod
    def _claim(owners, parameters, owner):
        duplicates = sorted(parameter for parameter in parameters
                            if parameter in owners and owners[parameter] != owner)
        if duplicates:
            previous = owners[duplicates[0]]
            raise EdltError(
                'Duplicate or conflicting byte ownership between ' + previous +
                ' and ' + owner + ': ' + ', '.join(duplicates))
        owners.update((parameter, owner) for parameter in parameters)

    @staticmethod
    def _require_group(cache, application, group, reason):
        if application not in cache.applications:
            raise EdltError(
                f'{reason} requires cached application {application}')
        row = cache.find(application, group)
        if row is None:
            raise EdltError(
                f'{reason} requires explicit cached group evidence for '
                f'application {application} group {group}')
        if not row.exists:
            raise EdltError(
                f'{reason} requires an existing group: application '
                f'{application} group {group}')
        return {
            'application': application, 'group': group, 'exists': True,
            'reason': reason,
        }

    @classmethod
    def _require_dynamic(cls, cache, application, group, index,
                         expected_icon, reason):
        cls._require_group(cache, application, group, reason)
        row = cache.find(application, group)
        if not row.dynamic_images_known or row.dynamic_images is None:
            raise EdltError(
                f'{reason} requires explicit cached dynamic image evidence for '
                f'application {application} group {group}')
        if index >= len(row.dynamic_images):
            raise EdltError(
                f'{reason} indexes outside cached dynamic image evidence for '
                f'application {application} group {group}')
        actual_icon = row.dynamic_images[index]
        if expected_icon is not None and actual_icon != expected_icon:
            actual = 'dynamic-icon' if actual_icon else 'dynamic-text'
            wanted = 'dynamic-icon' if expected_icon else 'dynamic-text'
            raise EdltError(
                f'{reason} requested {wanted}, but cached network metadata '
                f'resolves variant {index} as {actual}')
        return {
            'application': application, 'group': group,
            'field': 'dynamic_images', 'variant': index,
            'is_icon': actual_icon, 'reason': reason,
        }

    @staticmethod
    def _allocations(plan):
        if hasattr(plan, 'allocations'):
            return tuple(value for value in plan.allocations.values()
                         if value is not None)
        return tuple(value for value in
                     (plan.static_allocation, plan.status_allocation)
                     if value is not None)

    @staticmethod
    def _navigation_metadata(cache, application):
        """Project the parent cache into the standalone selector contract."""
        return {
            'format': 'cbus-edlt-navigation-metadata-v1',
            'groups': [
                {
                    'application': row.application,
                    'group': row.group,
                    'dynamic_variants': list(range(len(row.dynamic_images)))
                    if (row.group != 255 and row.dynamic_images_known
                        and row.dynamic_images is not None)
                    else [],
                }
                for row in cache.groups
                if row.application == application and row.exists
            ],
        }

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
        setting_panels = set()
        metadata_dependencies = []
        validation_placement_projections = 0
        widget_editors = {
            'measurement': self.measurement_editor,
            'lighting': self.lighting_editor,
        }

        for number, operation in enumerate(operations, 1):
            kind = operation['op']
            owner = f'operation {number} ({kind})'
            options = {name: value for name, value in operation.items()
                       if name != 'op'}
            if kind in WIDGET_OPERATION_NAMES:
                candidate = _candidate_widget(operation, planning_values)
                if candidate is not None and candidate in slots:
                    raise EdltError(
                        f'Duplicate widget byte ownership for widget{candidate}: '
                        f'{slots[candidate]} and {owner}')
                editor = widget_editors.get(kind) or self._editor(kind)
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
                records = {widget: widget_plan.record}
                adjacent = getattr(widget_plan, 'adjacent_widget', None)
                adjacent_record = getattr(widget_plan, 'adjacent_after', None)
                if adjacent is not None and adjacent_record is not None:
                    records[adjacent] = adjacent_record
                for record_widget in records:
                    if record_widget in slots:
                        raise EdltError(
                            f'Duplicate widget byte ownership for widget{record_widget}: '
                            f'{slots[record_widget]} and {owner}')
                    slots[record_widget] = owner
                claimed = [
                    _field(record_widget, offset)
                    for record_widget in records for offset in range(32)
                ]
                for record_widget in records:
                    if record_widget >= 6:
                        claimed.append(f'Widget{record_widget}RestoreLevel')
                self._claim(owners, claimed, owner)
                projected = {**widget_plan.expected, **widget_plan.changes}
                for record_widget, record in records.items():
                    for offset, value in enumerate(record):
                        control_values[_field(record_widget, offset)] = (value,)
                    if record_widget >= 6:
                        control_values[f'Widget{record_widget}RestoreLevel'] = projected[
                            f'Widget{record_widget}RestoreLevel']
                allocations = _static_changes(widget_plan, projected)
                self._claim(owners, allocations, owner)
                control_values.update(allocations)
                extra_fields = []
                if kind == 'time-date':
                    for parameter in ('DateFormat', 'TimeFormat',
                                      'TimeDateLeadingZero'):
                        if projected[parameter] != planning_values[parameter]:
                            self._claim(owners, (parameter,), owner)
                            control_values[parameter] = projected[parameter]
                            extra_fields.append(parameter)
                application = _selected_application(control_values,
                                                    widget_plan.record, kind)
                if application is not None:
                    group = (operation['variable'] if kind == 'enable'
                             else operation['group'])
                    metadata_dependencies.append(self._require_group(
                        cache, application, group,
                        f'operation {number} {kind} control binding'))
                    for display, index, expected_icon in _dynamic_requests(
                            kind, widget_plan.record):
                        metadata_dependencies.append(self._require_dynamic(
                            cache, application, group, index, expected_icon,
                            f'operation {number} {kind} dynamic {display} binding'))
                elif kind == 'scene':
                    references = widget_plan.cycle_references or (
                        widget_plan.reference,)
                    for display, index, expected_icon in _dynamic_requests(
                            kind, widget_plan.record):
                        for reference in references:
                            if reference is None or reference.trigger_group is None:
                                raise EdltError(
                                    f'operation {number} scene dynamic {display} '
                                    'binding requires an assigned trigger group')
                            metadata_dependencies.append(self._require_dynamic(
                                cache, 202, reference.trigger_group, index,
                                expected_icon,
                                f'operation {number} scene dynamic {display} binding'))
                control_values['NavWidgetType'] = (
                    1 if navigation_mode == 'multiple' else 0,)
                # Standalone planners serialize their own selected record.  A
                # normalized validation view lets the next distinct editor see
                # that model without making it the transaction's terminal save.
                planning_values = self.common._place_record(
                    control_values, widget, widget_plan.record,
                    normalize_mra=False)
                for record_widget in records:
                    if record_widget >= 6:
                        planning_values[f'Widget{record_widget}RestoreLevel'] = \
                            control_values[f'Widget{record_widget}RestoreLevel']
                planning_values['NavWidgetType'] = control_values['NavWidgetType']
                for parameter in (*allocations, *extra_fields):
                    planning_values[parameter] = control_values[parameter]
                validation_placement_projections += 1
                selected.append((widget, kind))
                document = widget_plan.as_dict()
                document.update({
                    'operation': number,
                    'composition_role': 'validated bound-control projection',
                    'owned_parameters': sorted(claimed + list(allocations) +
                                               extra_fields),
                    'reserved_widget_slots': sorted(records),
                    'parent_panel_binding': {
                        'selection_order': [
                            'ShowWidget', 'BaseWidget.SetWidgetData',
                            'BaseWidget.SetUpDataSource',
                            'assign selected widget data source',
                            'ResetBindings(false)',
                        ],
                        'source': PANEL_BINDING_SOURCES[kind],
                        'standalone_dependency_validation_reused': True,
                    },
                    'standalone_changes_applied_directly': False,
                })
                results.append(_json(document))
                continue

            if kind == 'activation':
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
                if after_mode in (2, 3) and projected['ProximityGroup'] != (255,):
                    application = (202 if after_mode == 3
                                   else _effective_primary(projected))
                    metadata_dependencies.append(self._require_group(
                        cache, application, projected['ProximityGroup'][0],
                        f'operation {number} activation event binding'))
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
                    'parent_panel_binding': {
                        'source': PANEL_BINDING_SOURCES[kind],
                        'standalone_dependency_validation_reused': True,
                    },
                    'standalone_changes_applied_directly': False,
                })
                results.append(_json(document))
                continue

            if kind in setting_panels:
                raise EdltError(
                    f'Duplicate or conflicting byte ownership: only one {kind} '
                    'operation may own that settings panel')
            setting_panels.add(kind)
            if kind == 'navigation' and options.get('metadata') is None:
                options['metadata'] = self._navigation_metadata(
                    cache, _effective_primary(planning_values))
            settings_plan = self._editor(kind).plan(planning_values, **options)
            projected = {**settings_plan.expected, **settings_plan.changes}
            fields = list(_SETTING_FIELDS[kind])
            if kind == 'navigation':
                mode = settings_plan.page_mode
                if navigation_mode is None:
                    navigation_mode = mode
                    self._claim(owners, ('NavWidgetType',),
                                'transaction navigation constraint')
                elif navigation_mode != mode:
                    raise EdltError(
                        'Conflicting page-mode ownership: ' + navigation_mode +
                        ' and ' + mode)
                control_values['NavWidgetType'] = (
                    1 if navigation_mode == 'multiple' else 0,)
                fields.remove('NavWidgetType')
            self._claim(owners, fields, owner)
            for parameter in fields:
                control_values[parameter] = projected[parameter]
            allocations = _static_changes(settings_plan, projected)
            self._claim(owners, allocations, owner)
            control_values.update(allocations)

            primary = _effective_primary(projected)
            if kind == 'colours':
                for option_name, parameter in COLOUR_FIELDS.items():
                    if not option_name.endswith('_group'):
                        continue
                    group = projected[parameter][0]
                    if group != 255:
                        metadata_dependencies.append(self._require_group(
                            cache, primary, group,
                            f'operation {number} colours {option_name} binding'))
            elif kind == 'navigation':
                variant = projected['NavWidgetVariant'][0]
                if (variant in (3, 4) and
                        projected['TemperatureApplication'] == (1,) and
                        projected['NavDevIDZoneGroup'] != (255,)):
                    metadata_dependencies.append(self._require_group(
                        cache, 172, projected['NavDevIDZoneGroup'][0],
                        f'operation {number} navigation HVAC binding'))
                if variant in (5, 7) and projected['DynamicGroup'] != (255,):
                    group = projected['DynamicGroup'][0]
                    metadata_dependencies.append(self._require_group(
                        cache, primary, group,
                        f'operation {number} navigation dynamic binding'))
                    indices = ((0,) if variant == 5 else tuple(dict.fromkeys(
                        projected[f'PageNameIndex{page}'][0]
                        for page in range(1, 5))))
                    for index in indices:
                        metadata_dependencies.append(self._require_dynamic(
                            cache, primary, group, index, None,
                            f'operation {number} navigation dynamic binding'))
            elif kind == 'quick-status' and projected['QuickStatusGroup'] != (255,):
                metadata_dependencies.append(self._require_group(
                    cache, primary, projected['QuickStatusGroup'][0],
                    f'operation {number} Quick Status binding'))
            elif kind == 'page-control' and projected['KeySetsEnableGroup'] != (255,):
                metadata_dependencies.append(self._require_group(
                    cache, 203, projected['KeySetsEnableGroup'][0],
                    f'operation {number} Page Control binding'))
            for parameter in (*fields, *allocations):
                planning_values[parameter] = control_values[parameter]
            planning_values['NavWidgetType'] = control_values['NavWidgetType']
            document = settings_plan.as_dict()
            document.update({
                'operation': number,
                'composition_role': 'validated parent settings projection',
                'owned_parameters': sorted(fields + list(allocations)),
                'parent_panel_binding': {
                    'source': PANEL_BINDING_SOURCES[kind],
                    'standalone_dependency_validation_reused': True,
                },
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
                'settings_panels': sorted(setting_panels),
                'supported_operation_types': list(SUPPORTED_OPERATION_NAMES),
                'duplicate_or_conflicting_byte_ownership_rejected': True,
                'all_controls_validated_before_first_pp_write': True,
                'operation_group_dependencies_verified_before_first_pp_write': True,
            },
            'operation_metadata_dependencies': metadata_dependencies,
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
            'extended_panel_evidence_fixture':
                'research/fixtures/edlt-parent-panels-evidence.json',
            'original_source_sequence_pinned': True,
            'reused_original_measurement_probe': True,
            'reused_original_lighting_probe': True,
            'reused_original_percentage_control_probe': True,
            'reused_standalone_panel_acceptance': sorted(
                {operation['op'] for operation in operations}),
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
