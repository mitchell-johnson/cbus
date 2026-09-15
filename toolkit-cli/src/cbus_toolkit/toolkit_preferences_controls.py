"""Retained Toolkit 1.18 preference controls and explicit save assignments.

This model accepts canonical Java heap text, or an explicitly selected bounded
original numeric locale, and explicit stored values. It does
not construct VCL forms, infer installer defaults, restart C-Gate, or render the
address preview. Storage and controller actions are separate from this plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

DISPLAY_NAMES = ('tag_hex', 'tag_override', 'sort_applications', 'sort_groups', 'sort_levels')
# Original OK-handler getter order, including the two inverted checkboxes.
BOOLEAN_SETTINGS = (
    ('chkLoadChangePort', 'LoadChangePortDisable', True),
    ('chkApplicationLog', 'ApplicationLogDisable', True),
    ('chkAutoInvokeFunctionDialog', 'AutoInvokeMacroFunctionDialog', False),
    ('chkAutoInvokeUnitDialog', 'AutoInvokeDatabaseUnitDialog', False),
    ('chkSynchroniseFilters', 'SynchroniseFilters', False),
    ('chkFeedbackLog', 'FeedbackLog', False),
    ('rdbCloseProjects', 'CloseProjectsOnExit', False),
    ('chkShutdownCGate', 'CGateShutdownOnExit', False),
    ('rdbShutdownAsk', 'CGateShutdownOnExitAsk', False),
    ('chkAlwaysOpenClassic', 'UnitDialogAlwaysClassic', False),
    ('cbAllowLegacyApplications', 'AllowLegacyApplicationCreation', False),
    ('cbAllowUserDefinedApplications', 'AllowUserDefinedApplicationCreation', False),
    ('chkRememberProjMgrVisState', 'RememberProjectManagerVisibleState', False),
)
RADIO_GROUPS = (
    ('rdbDoNothing', 'rdbCloseProjects', 'rdbShutdownAsk'),
    ('rdbUnitRemember', 'rdbUnitSimple', 'rdbUnitAdvanced'),
    ('rdoTagNamesStandard', 'rdoTagNamesUseHex', 'rdoTagNamesUseValue'),
)
SORT_CONTROLS = {'rgSortApplications': 'sort_applications',
                 'rgSortGroups': 'sort_groups', 'rgSortLevels': 'sort_levels'}
BOOLEAN_CONTROLS = tuple(dict.fromkeys(
    [row[0] for row in BOOLEAN_SETTINGS] + [name for group in RADIO_GROUPS for name in group]))
SAVE_CONTROLS = tuple(dict.fromkeys(
    [row[0] for row in BOOLEAN_SETTINGS] + ['rdbUnitSimple', 'rdbUnitAdvanced',
    'cmbTemperatureUnit', 'cmbJavaHeapMax', 'spnFeedbackLogSize']))


def _integer(value, name):
    if type(value) is not int or not -2**31 <= value < 2**31:
        raise ValueError(f'{name} must be a signed 32-bit integer')
    return value


def _boolean(value, name):
    if type(value) is not bool:
        raise ValueError(f'{name} must be a boolean')
    return value


def _display(values):
    if not isinstance(values, Mapping) or set(values) != set(DISPLAY_NAMES):
        raise ValueError('All five display preferences are required')
    return {name: _boolean(values[name], name) for name in DISPLAY_NAMES}


def _values(values):
    from .toolkit_preferences_store import validate_values
    return validate_values(values)


def canonical_java_heap(text):
    """Validate the explicitly supported canonical decimal input range."""
    if not isinstance(text, str) or not text.isascii() or not text.isdecimal():
        raise ValueError('Java heap text must be canonical ASCII decimal (64 to 9999)')
    if not 2 <= len(text) <= 4 or str(int(text)) != text or not 64 <= int(text) <= 9999:
        raise ValueError('Java heap text must be canonical ASCII decimal (64 to 9999)')
    return int(text)


def _numeric_locale(value):
    if value is None: return None
    if type(value) is not tuple or value not in (('.', ','), (',', '.')):
        raise ValueError('Numeric locale must be an explicit dot/comma separator tuple')
    return value


def _heap_conversion(text, numeric_locale):
    if numeric_locale is None: return canonical_java_heap(text), None
    from .toolkit_numeric import parse_toolkit_integer
    if type(text) is not str: raise ValueError('Java heap input must be text')
    converted = parse_toolkit_integer(text, decimal_separator=numeric_locale[0],
                                     thousands_separator=numeric_locale[1])
    if not 64 <= converted.value <= 9999:
        raise ValueError('Converted Java heap size must be 64 to 9999')
    return converted.value, converted


@dataclass(frozen=True)
class PreferenceSavePlan:
    values: tuple[tuple[str, bool | int | str], ...]
    display_values: tuple[tuple[str, bool], ...]
    assignments: tuple[tuple[str, bool | int], ...]
    feedback_log_enabled: bool
    feedback_size_argument: int
    numeric_locale: tuple[str, str] | None = None
    heap_conversion: object = None

    def as_dict(self):
        result = {'format': 'cbus-toolkit-preferences-save-plan-v1',
                'values': dict(self.values), 'display_values': dict(self.display_values),
                'assignments': dict(self.assignments),
                'feedback_log_enabled': self.feedback_log_enabled,
                'feedback_size_argument': self.feedback_size_argument,
                'phase_order': ['display-save', 'preference-assignments', 'manager-save',
                                'feedback-controller-update', 'optional-controller-calls'],
                'storage_applied': False, 'controller_calls_executed': False,
                'full_form_verified': False}
        if self.numeric_locale is not None:
            result.update(numeric_locale=list(self.numeric_locale), heap_conversion=self.heap_conversion.as_dict())
        return result


def plan_preferences_save(values, controls, display_values, *, numeric_locale=None):
    """Project original OK-handler assignments from explicit getter values.

    Getter values may describe a retained form; no radio dispatch or SpinEdit
    exit event is invented. The convenience editor below provides constrained
    selection operations. All 21 settings outside this handler are preserved.
    """
    numeric_locale = _numeric_locale(numeric_locale)
    current = _values(values)
    display = _display(display_values)
    if not isinstance(controls, Mapping) or not set(SAVE_CONTROLS) <= set(controls):
        raise ValueError('Complete preference save-control getter values are required')
    permitted = set(BOOLEAN_CONTROLS) | set(SORT_CONTROLS) | {
        'cmbTemperatureUnit', 'cmbJavaHeapMax', 'spnFeedbackLogSize'}
    if set(controls) - permitted:
        raise ValueError('Unknown preference control')
    for name in set(controls) & set(BOOLEAN_CONTROLS):
        _boolean(controls[name], name)
    for name in set(controls) & set(SORT_CONTROLS):
        _integer(controls[name], name)
    heap, conversion = _heap_conversion(controls['cmbJavaHeapMax'], numeric_locale)
    feedback = _integer(controls['spnFeedbackLogSize'], 'Feedback log size')
    temperature = _integer(controls['cmbTemperatureUnit'], 'Temperature unit')
    assignments = {}
    for control, setting, inverted in BOOLEAN_SETTINGS:
        assignments[setting] = not controls[control] if inverted else controls[control]
    assignments.update(FeedbackLogSize=feedback, JavaHeapMin=32, JavaHeapMax=heap,
                       TemperatureUnit=temperature,
                       UnitDialogOverride=controls['rdbUnitSimple'] or controls['rdbUnitAdvanced'],
                       UnitDialogModeAdvanced=controls['rdbUnitAdvanced'])
    assert len(assignments) == 19
    after = {**current, **assignments}
    # The original 32-bit controller argument is the low dword of size * 1000.
    return PreferenceSavePlan(tuple(after.items()), tuple(display.items()),
                              tuple(assignments.items()), controls['chkFeedbackLog'],
                              (feedback * 1000) & 0xffffffff, numeric_locale, conversion)


class ToolkitPreferenceControls:
    """Explicit load and ordered operations for bounded preference controls."""
    def __init__(self, values, display_values, *, numeric_locale=None):
        self._numeric_locale = _numeric_locale(numeric_locale)
        self._source = _values(values)
        self._display = _display(display_values)
        self._controls = {name: False for name in BOOLEAN_CONTROLS}
        self._messages = []
        v, c = self._source, self._controls
        for control, setting, inverted in BOOLEAN_SETTINGS:
            c[control] = not v[setting] if inverted else v[setting]
        # FormShow chooses a single member, with Ask taking priority.
        for name in RADIO_GROUPS[0]: c[name] = False
        c['chkShutdownCGate'] = not v['CGateShutdownOnExitAsk'] and v['CGateShutdownOnExit']
        c['rdbShutdownAsk' if v['CGateShutdownOnExitAsk'] else
          'rdbCloseProjects' if v['CloseProjectsOnExit'] or v['CGateShutdownOnExit'] else
          'rdbDoNothing'] = True
        c['rdbUnitRemember' if not v['UnitDialogOverride'] else
          'rdbUnitAdvanced' if v['UnitDialogModeAdvanced'] else 'rdbUnitSimple'] = True
        c['cmbTemperatureUnit'] = v['TemperatureUnit']
        c['cmbJavaHeapMax'] = str(v['JavaHeapMax'])
        c['spnFeedbackLogSize'] = max(100, min(9900, v['FeedbackLogSize']))
        self._application_log_enabled = c['chkLoadChangePort']
        c['rdoTagNamesStandard' if not self._display['tag_override'] else
          'rdoTagNamesUseHex' if self._display['tag_hex'] else 'rdoTagNamesUseValue'] = True
        for control, setting in SORT_CONTROLS.items(): c[control] = int(self._display[setting])

    @property
    def controls(self): return MappingProxyType(self._controls.copy())

    @property
    def display_values(self): return MappingProxyType(self._display.copy())

    @property
    def address_preview(self):
        from .toolkit_preferences_preview import render_address_preview
        return render_address_preview(tag_hex=self._display['tag_hex'],
                                      tag_override=self._display['tag_override'])

    @property
    def application_log_enabled(self): return self._application_log_enabled

    @property
    def message_resource_ids(self): return tuple(self._messages)

    def _select(self, control):
        group = next(g for g in RADIO_GROUPS if control in g)
        for name in group: self._controls[name] = name == control

    def set_control(self, name, value):
        """Apply one user-selected control value; callers preserve operation order."""
        if name not in self._controls:
            raise ValueError(f'Unknown preference control: {name}')
        c = self._controls
        if name in BOOLEAN_CONTROLS:
            _boolean(value, name)
            if any(name in g for g in RADIO_GROUPS):
                if not value: raise ValueError('Select a radio option with true')
                self._select(name)
                if name in ('rdbDoNothing', 'rdbShutdownAsk'):
                    c['chkShutdownCGate'] = False
                if name in RADIO_GROUPS[2]:
                    self._display['tag_hex'] = name == 'rdoTagNamesUseHex'
                    self._display['tag_override'] = name != 'rdoTagNamesStandard'
            else:
                if name == 'chkApplicationLog' and not self._application_log_enabled:
                    raise ValueError('Application log control is disabled while the load change port is disabled')
                c[name] = value
                if name == 'chkLoadChangePort':
                    self._application_log_enabled = value
                    c['chkApplicationLog'] = value
                    if not value: self._messages.append(0xb054)
                elif name == 'chkShutdownCGate': self._select('rdbCloseProjects')
        elif name in SORT_CONTROLS:
            _integer(value, name)
            if value not in (0, 1): raise ValueError('Sort selection must be 0 or 1')
            c[name] = value
            self._display[SORT_CONTROLS[name]] = bool(value)
        elif name == 'cmbJavaHeapMax':
            _heap_conversion(value, self._numeric_locale)
            c[name] = value
        elif name == 'spnFeedbackLogSize':
            c[name] = max(100, min(9900, _integer(value, name)))
        else:
            _integer(value, name)
            if value not in (0, 1): raise ValueError('Temperature selection must be 0 or 1')
            c[name] = value
        return self

    def plan_save(self):
        return plan_preferences_save(self._source, self._controls, self._display,
                                     numeric_locale=self._numeric_locale)

    def as_dict(self):
        result = {'format': 'cbus-toolkit-preferences-controls-v1',
                'controls': dict(self.controls), 'display_values': dict(self.display_values),
                'application_log_enabled': self.application_log_enabled,
                'address_preview': self.address_preview,
                'message_resource_ids': list(self.message_resource_ids),
                'storage_applied': False, 'full_form_verified': False}
        if self._numeric_locale is not None:
            result['numeric_locale'] = list(self._numeric_locale)
        return result
