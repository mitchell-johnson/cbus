"""Live inherited SENLLA Unit attributes and mandatory prekey callbacks.

This internal owner executes the retained scalar/string setters on the same
Unit manager used by applications, blocks and keys. Project persistence and
source metadata notifications belong to ``senlla_project_bridge``.
"""
from dataclasses import dataclass
from copy import deepcopy

from .senlla_inputs import SCHEMA, SENLLAInputSnapshot, _value
from .senlla_lifecycle import BooleanAttribute, FlashAttribute
from .senlla_prekey import PrekeyOwnerRequest, SENLLAPrekey
from .senlla_scalars import NON_SENT_PARAMETERS, ScalarSaveMetadata
from .sensors import SensorError


@dataclass
class StringChange:
    previous: str
    proposed: str
    changed: bool


class UnitStringAttribute(FlashAttribute):
    """Native TStringAttribute route; mutable BeforeChange precedes Begin.

    UTF-16 maximum zero disables length validation. Equal strings return
    without updates unless the callback changes the native changed flag.
    """
    def __init__(self, manager, value='', *, maximum=0, before_change=None, **kwargs):
        if type(value) is not str or type(maximum) is not int or maximum < 0:
            raise SensorError('Unit string attribute requires text and a nonnegative maximum')
        if before_change is not None and not callable(before_change):
            raise SensorError('String BeforeChange requires a callable')
        self.maximum = maximum
        self.before_change = before_change
        if maximum and len(value.encode('utf-16le', errors='surrogatepass')) // 2 > maximum:
            raise SensorError('Unit string exceeds its native UTF-16 maximum')
        super().__init__(manager, value, **kwargs)

    @property
    def value(self):
        self.resolve_change()
        return self._value

    def set(self, value):
        if type(value) is not str:
            raise SensorError('Unit string attribute requires text')
        # Delphi @UStrEqual compares UTF-16 code units, including explicit
        # surrogate pairs; Python's scalar-string equality is different.
        changed = (self._value.encode('utf-16le', errors='surrogatepass') !=
                   value.encode('utf-16le', errors='surrogatepass'))
        decision = StringChange(self._value, value, changed)
        if self.before_change is not None:
            self._record('before')
            self.before_change(self, decision)
        if type(decision.changed) is not bool or type(decision.proposed) is not str:
            raise SensorError('String BeforeChange requires text and a Boolean changed flag')
        if not decision.changed:
            return
        count = len(decision.proposed.encode('utf-16le', errors='surrogatepass')) // 2
        if self.maximum and count > self.maximum:
            raise SensorError('Unit string exceeds its native UTF-16 maximum')
        self.begin_update()
        try:
            self._value = decision.proposed
            self._record('assign')
        finally:
            self.end_update()


class UnitEnumAttribute(FlashAttribute):
    """Native enumeration ordinal route; no Integer BeforeChange callback."""
    def __init__(self, manager, *, maximum, **kwargs):
        if type(maximum) is not int or maximum < 0:
            raise SensorError('Unit enum requires a nonnegative integer maximum')
        self.maximum = maximum
        super().__init__(manager, 0, **kwargs)

    @property
    def value(self):
        self.resolve_change()
        return self._value

    def set(self, value):
        if type(value) is not int:
            raise SensorError('Unit enum requires an integer ordinal')
        if value == self._value:
            return
        if not 0 <= value <= self.maximum:
            raise SensorError('Unit enum ordinal is outside its native bounds')
        self.begin_update()
        try:
            self._value = value
            self._record('assign')
        finally:
            self.end_update()


class SENLLAInheritedOwner:
    """Actual inherited dispatcher attached before the first PP load setter.

    The bridge resolves CURRENT project/database objects and confirms source
    lookups on this runtime. Late NeoPro IR setters and Global initialization
    are separate explicit phases for the complete owning orchestrator.
    """
    def __init__(self, snapshot, bridge, *, parameter_read=None, defer_smart_observers=False):
        from .senlla_project_bridge import SENLLAProjectBridge
        if not isinstance(snapshot, SENLLAInputSnapshot) or not isinstance(bridge, SENLLAProjectBridge):
            raise SensorError('Inherited owner requires the guarded snapshot and actual project bridge')
        if parameter_read is not None and not callable(parameter_read):
            raise SensorError('Inherited CURRENT parameter reader must be callable or None')
        self.snapshot = SENLLAInputSnapshot(snapshot.identity, snapshot.expected)
        self.bridge = bridge
        self.parameter_read = parameter_read
        self.prekey = SENLLAPrekey(self.snapshot, source_dispatch=bridge.dispatch,
                                  inherited_dispatch=self.dispatch,
                                  defer_smart_observers=defer_smart_observers)
        self.runtime = self.prekey.runtime
        bridge.bind(self.runtime, self.snapshot)
        manager = self.runtime.unit_manager
        self.attributes = {}
        for name in ('Project', 'CBusUnitName'):
            self.attributes[name] = UnitStringAttribute(manager, name='unit.' + name,
                                                       trace=self.runtime._trace)
        for name, maximum in (('DebounceTime', 63), ('LongPressTime', 63),
                              ('RampRate1', 15), ('RampRate2', 15),
                              ('InfraredBank', 3), ('InfraredBankP', 3)):
            self.attributes[name] = UnitEnumAttribute(manager, maximum=maximum,
                                                     name='unit.' + name, trace=self.runtime._trace)
        for name in ('EEPROMLevelStore', 'InfraredClipsal', 'InfraredNEC',
                     'LearnMode', 'LearnAnyApplication', 'LearnedFlag', 'LearnedFlagCopy'):
            self.attributes[name] = BooleanAttribute(manager, False, name='unit.' + name,
                                                     trace=self.runtime._trace)
        self.attributes['StatusReportInterval'] = self.prekey.status_report_interval
        self.tag_name = UnitStringAttribute(manager, bridge.unit_record()['TagName'], maximum=32,
                         name='unit.TagName', trace=self.runtime._trace,
                         after_change=lambda _: bridge.unit_tag_name_changed(self))
        self._requests = []
        self._neopro_ir_loaded = False
        self.global_initialized = False

    def register_unit_attribute(self, name, attribute):
        """Attach another source-owned phase's actual SAME Unit attribute.

        The phase owner supplies its constructor value and exact handlers.
        Registration does not set values, publish, or infer callbacks.
        """
        if type(name) is not str or not name or name in self.attributes:
            raise SensorError('Unit attribute registration requires a new nonempty name')
        if (not isinstance(attribute, FlashAttribute)
                or attribute.manager is not self.runtime.unit_manager):
            raise SensorError('Unit attribute must use the SAME owning Unit manager')
        self.attributes[name] = attribute
        return attribute

    def unit_attribute(self, name):
        if type(name) is not str or name not in self.attributes:
            raise SensorError('Unit attribute has not been source-registered')
        return self.attributes[name]

    def _set(self, name, value, source):
        self.runtime._event('inherited_unit_setter', field=name, value=value, source=source)
        self.attributes[name].set(value)

    def _read(self, name, source):
        """One current agent getter, detached before the following setter.

        The historical component profile reads the bound raw snapshot. A full
        owner supplies the actual current agent-cache read at this source site.
        Guarded field admission remains a component boundary, not a claim that
        the native cache getter validates unsigned physical-memory layouts.
        """
        value = (self.parameter_read(name, source, self.runtime)
                 if self.parameter_read is not None else self.snapshot.expected[name])
        if SCHEMA[name][0] != 'sixbit' and (not isinstance(value, (list, tuple))
                or any(type(item) is not int for item in value)):
            raise SensorError('CURRENT inherited parameter requires exact unsigned integers: ' + name)
        value = _value(name, value)
        self.runtime._event('inherited_parameter_read', field=name, source=source,
                            value=deepcopy(value))
        return value

    def dispatch(self, request, prekey):
        if type(request) is not PrekeyOwnerRequest or prekey is not self.prekey:
            raise SensorError('Inherited request belongs to another owning Unit')
        expected = {
            'base_agent_after_load': '0xcbe66d',
            'unit_metadata_after_applications': '0xcbe6f2',
            'learn_after_inherited_unit': '0xcc5d43',
            'core_scalars_before_blocks': '0xcc861f',
        }
        if expected.get(request.operation) != request.source or request.operation in self._requests:
            raise SensorError('Inherited request is out of source order or repeated')
        if tuple(expected)[len(self._requests)] != request.operation:
            raise SensorError('Inherited request is out of source order')
        self._requests.append(request.operation)
        if request.operation == 'base_agent_after_load':
            # cac4d4 has no body; this is a source-proven empty inherited call.
            self.runtime._event('source_empty_base_agent_after_load', source='0xcac4d4')
        elif request.operation == 'unit_metadata_after_applications':
            self._set('Project', self._read('Project', '0xcbe700').upper(), '0xcbe71b')
            self._set('CBusUnitName', self._read('UnitName', '0xcbe72e'), '0xcbe73e')
            # Canonical SENLLA VMTc4 resolves f347c4, literal false. No
            # physical/secondary-firmware branch is visited by this class.
            self.runtime._event('secondary_firmware_properties_disabled', source='0xf347c4')
        elif request.operation == 'learn_after_inherited_unit':
            # SENLLA VMT160 false skips the three inverted PP setters and
            # fourth learned copy; preserve their constructor false values.
            self.runtime._event('learn_properties_disabled', source='0x1216ecc')
        else:
            self._set('DebounceTime', self._read('DebounceTime', '0xcc862a')[0], '0xcc8651')
            self.runtime._event('indicator_brightness_properties_disabled', source='0xcc8655')
            self._set('LongPressTime', self._read('LongPressTime', '0xcc8666')[0], '0xcc868d')
            self._set('EEPROMLevelStore', bool(self._read('EEPROMLevelStore', '0xcc7a0a')[0]), '0xcc7a1a')
            for index, (read_source, source) in enumerate((('0xcc86a6', '0xcc86d4'),
                                                         ('0xcc86e7', '0xcc8718'))):
                value = self._read('RampRate', read_source)[index]
                value = value if value <= 15 else 1 if value == 255 else 15
                self._set('RampRate' + str(index + 1), value, source)
            # Core bank is a different attribute/ordinal from late NeoPro.
            self._set('InfraredBank', (1, 2, 3, 0)[self._read('IRBank', '0xcc80a8')[0]], '0xcc80c0')

    def set_late_scalar(self, name, value, *, source):
        if name not in ('InfraredBankP', 'InfraredClipsal', 'InfraredNEC'):
            raise SensorError('Late inherited setter requires a NeoPro infrared attribute')
        if type(source) is not str or not source:
            raise SensorError('Late inherited setter requires its source position')
        self._set(name, value, source)

    def load_neopro_infrared(self):
        """Execute only the ced19a..ced238 IR prefix at the caller's phase."""
        if self._neopro_ir_loaded:
            raise SensorError('NeoPro infrared load cannot be replayed')
        self.set_late_scalar('InfraredBankP', self._read('IRBank', '0xced1a0')[0], source='0xced1b5')
        self.set_late_scalar('InfraredClipsal', not bool(self._read('DisableIR', '0xced1c8')[0]), source='0xced1e5')
        self.set_late_scalar('InfraredNEC', not bool(self._read('DisableIRNEC', '0xced1f8')[0]), source='0xced215')
        self._neopro_ir_loaded = True

    def initialize_global(self):
        """Separate fresh Global status selector phase on the same attribute."""
        current = self.attributes['StatusReportInterval'].value
        self._set('StatusReportInterval', max(current, 3), 'Global.StatusSelector.Initialize')
        self.global_initialized = True

    def metadata(self):
        current = self.bridge.metadata()
        return ScalarSaveMetadata(current['project_tag_name'], current['unit_address'],
                                  self.attributes['CBusUnitName'].value)

    def scalar_parameters(self):
        """Read current eleven fields; the caller owns their native save order."""
        if not self._neopro_ir_loaded:
            raise SensorError('Final scalar capture requires the late NeoPro infrared load')
        a, metadata = self.attributes, self.metadata()
        return {
            'Project': metadata.project_tag_name.upper(),
            'UnitName': metadata.unit_name.upper(),
            'UnitAddress': [metadata.unit_address],
            'DebounceTime': [a['DebounceTime'].value],
            'LongPressTime': [a['LongPressTime'].value],
            'EEPROMLevelStore': [int(a['EEPROMLevelStore'].value)],
            'RampRate': [a['RampRate1'].value, a['RampRate2'].value],
            'IRBank': [a['InfraredBankP'].value],
            'DisableIR': [int(not a['InfraredClipsal'].value)],
            'DisableIRNEC': [int(not a['InfraredNEC'].value)],
            'StatusReportInterval': [a['StatusReportInterval'].value],
        }

    def non_sent_parameters(self):
        return {name: list(self.snapshot.expected[name]) for name in NON_SENT_PARAMETERS}

    def snapshot_state(self):
        return deepcopy(dict(inherited_requests=self._requests,
                             current_attributes={name: value._value for name, value in self.attributes.items()},
                             tag_name=self.tag_name._value,
                             neopro_ir_loaded=self._neopro_ir_loaded,
                             global_initialized=self.global_initialized,
                             complete_toolkit_save=False, original_execution=False))
