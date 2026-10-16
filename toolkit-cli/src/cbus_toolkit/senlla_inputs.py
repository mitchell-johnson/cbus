"""Internal SENLLA complete PP input guard, without a save or programming API.

The schema contains derived names, types and effective numeric layouts only.
It admits the 93 required fields for later owning lifecycle composition. Extra
provider fields are outside this snapshot and are neither validated nor owned.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .macros import _numbers
from .memory import MemoryCodec, encode_sixbit
from .senlla_surface import check_profile
from .sensors import SensorError


# Numeric facts from senlla-inherited-scalars-source.json; no vendor defaults,
# descriptions or definition blobs. Row: type, address, count, bits, bit, skip.
SCHEMA = MappingProxyType({
    'Application': ('int', 33, 2, 8, 0, 0),
    'AreaGroupAddress': ('int', 67, 1, 8, 0, 0),
    'BankSwitchGroupLevelStore': ('bit', 22, 1, 1, 2, 0),
    'BankSwitchGroupUsed': ('int', 72, 8, 1, 6, 0),
    'BankSwitchThresholdBehaviour': ('int', 22, 1, 2, 4, 0),
    'BankSwitchThresholdGroup': ('int', 21, 1, 8, 0, 0),
    'BlockAllocation': ('int', 54, 8, 8, 0, 0),
    'BlockBankSwitchActive': ('int', 72, 8, 1, 5, 0),
    'BlockGroupLogic': ('int', 72, 8, 1, 4, 0),
    'BroadcastActive': ('int', 70, 1, 3, 5, 0),
    'BroadcastBlock': ('int', 70, 1, 3, 0, 0),
    'CUSTYPE': ('int', 247, 8, 8, 0, 0),
    'ControlAppGroupAddress': ('int', 95, 1, 8, 0, 0),
    'CorridorLinkActive': ('bit', 68, 1, 1, 7, 0),
    'CorridorLinkBlock': ('int', 68, 1, 3, 3, 0),
    'CorridorLinkEnablerGroup': ('int', 92, 1, 8, 0, 0),
    'CorridorLinkOfficeBlock': ('int', 68, 1, 3, 0, 0),
    'DebounceTime': ('int', 48, 1, 6, 0, 0),
    'DisableIR': ('bit', 53, 1, 1, 2, 0),
    'DisableIRNEC': ('bit', 53, 1, 1, 3, 0),
    'DualJoinEnablerControlGroup': ('int', 94, 1, 8, 0, 0),
    'DualJoinEnablerGroup': ('int', 91, 1, 8, 0, 0),
    'EEPROM Checksum': ('int', 31, 1, 8, 0, 0),
    'EEPROMCheckSumActive': ('int', 30, 1, 8, 0, 0),
    'EEPROMChecksumAlarm': ('bit', 62, 1, 1, 7, 0),
    'EEPROMLevelStore': ('bit', 62, 1, 1, 1, 0),
    'GroupAddress': ('int', 80, 8, 8, 0, 0),
    'IRBank': ('int', 53, 1, 2, 0, 0),
    'IRBankKeyOffset': ('int', 53, 1, 3, 4, 0),
    'IndicatorBlockAssignment': ('int', 96, 8, 3, 0, 0),
    'IndicatorControl': ('int', 70, 1, 2, 3, 0),
    'JPCommand': ('int', 104, 8, 4, 4, 1),
    'KeyDisableInverted': ('bit', 62, 1, 1, 2, 0),
    'LPCommand': ('int', 105, 8, 4, 4, 1),
    'LRCommand': ('int', 105, 8, 4, 0, 1),
    'LearnAnyApp': ('bit', 62, 1, 1, 4, 0),
    'LearnMode': ('bit', 62, 1, 1, 3, 0),
    'LearnedFlag': ('bit', 62, 1, 1, 5, 0),
    'LightIndex': ('int', 0, 1, 8, 0, 0),
    'LightLevel': ('int', 1, 10, 8, 0, 0),
    'LightLevelMarginGroup': ('int', 20, 1, 8, 0, 0),
    'LightLevelMarginGroupLevelStore': ('bit', 22, 1, 1, 1, 0),
    'LightLevelStore1': ('int', 120, 8, 8, 0, 0),
    'LightLevelStore2': ('int', 128, 8, 8, 0, 0),
    'LightLevelTargetGroup': ('int', 19, 1, 8, 0, 0),
    'LightLevelTargetGroupLevelStore': ('bit', 22, 1, 1, 0, 0),
    'LongPressTime': ('int', 49, 1, 6, 0, 0),
    'PECEnablerGroup': ('int', 89, 1, 8, 0, 0),
    'PECEnablerGroupLogic': ('bit', 99, 1, 1, 5, 0),
    'PECFunctionActive': ('bit', 96, 1, 1, 6, 0),
    'PECFunctionBlock': ('int', 96, 1, 3, 3, 0),
    'PECFunctionIRActive': ('bit', 97, 1, 1, 6, 0),
    'PECFunctionIRKey': ('int', 97, 1, 3, 3, 0),
    'PECLevelStore': ('bit', 99, 1, 1, 3, 0),
    'PECMarginLux': ('int', 28, 1, 8, 0, 0),
    'PECScaleFactor': ('int', 29, 1, 8, 0, 0),
    'PECTargetLux': ('int', 27, 1, 8, 0, 0),
    'PIRDark': ('int', 52, 1, 8, 0, 0),
    'PIRDarkMovement': ('int', 51, 1, 8, 0, 0),
    'PIREnablerGroup': ('int', 88, 1, 8, 0, 0),
    'PIREnablerGroupLogic': ('bit', 99, 1, 1, 6, 0),
    'PIRFunctionIRActive': ('bit', 98, 1, 1, 6, 0),
    'PIRFunctionIRKey': ('int', 98, 1, 3, 3, 0),
    'PIRLevelStore': ('bit', 99, 1, 1, 4, 0),
    'PIRLightMovement': ('int', 50, 1, 8, 0, 0),
    'PatchEnable': ('int', 160, 2, 8, 0, 0),
    'PotentiometerAFunction': ('int', 101, 1, 2, 3, 0),
    'PotentiometerATimerBlock': ('int', 102, 1, 3, 3, 0),
    'PotentiometerBBankSwitchEnable': ('int', 103, 1, 1, 6, 0),
    'PotentiometerBFunction': ('int', 101, 1, 2, 5, 0),
    'PotentiometerBTimerBlock': ('int', 103, 1, 3, 3, 0),
    'PowerUpBankSwitchGroupLevel': ('int', 18, 1, 8, 0, 0),
    'PowerUpMarginGroupLevel': ('int', 17, 1, 8, 0, 0),
    'PowerUpTargetGroupLevel': ('int', 16, 1, 8, 0, 0),
    'Project': ('sixbit', 35, 8, 8, 0, 0),
    'RampRate': ('int', 64, 2, 8, 0, 0),
    'RetardationIndex': ('int', 71, 1, 8, 0, 0),
    'SRCommand': ('int', 104, 8, 4, 0, 1),
    'SceneCycleSelector': ('bit', 62, 1, 1, 6, 0),
    'SceneKeySelector': ('int', 96, 8, 1, 7, 0),
    'SceneTable': ('int', 162, 80, 8, 0, 0),
    'SceneTablePointer': ('int', 152, 8, 8, 0, 0),
    'SceneToggleSelector': ('bit', 62, 1, 1, 0, 0),
    'SecondApplicationBlocks': ('int', 69, 1, 8, 0, 0),
    'SerialNo': ('int', 243, 4, 8, 0, 0),
    'SingleJoinEnablerControlGroup': ('int', 93, 1, 8, 0, 0),
    'SingleJoinEnablerGroup': ('int', 90, 1, 8, 0, 0),
    'StatusReportInterval': ('int', 66, 1, 8, 0, 0),
    'TimerExpiryCommand': ('int', 72, 8, 4, 0, 0),
    'TimerHighByte': ('int', 136, 8, 8, 0, 0),
    'TimerLowByte': ('int', 144, 8, 8, 0, 0),
    'UnitAddress': ('int', 32, 1, 8, 0, 0),
    'UnitName': ('sixbit', 42, 8, 8, 0, 0),
})


def _identity(identity):
    if not isinstance(identity, tuple) or len(identity) != 3:
        raise SensorError('Identity must be (unit_type, firmware, catalog_number)')
    return check_profile(*identity)


def _value(name, raw):
    kind, _address, count, bits, _bit, _skip = SCHEMA[name]
    try:
        if kind == 'sixbit':
            # Validate representability, preserving the supplied lexical text.
            # In particular, non-ASCII uppercasing cannot enter a PP snapshot.
            encode_sixbit(raw)
            return raw
        values = _numbers(raw)
    except (TypeError, ValueError):
        raise SensorError('Invalid SENLLA input parameter: ' + name) from None
    if len(values) != count or any(not 0 <= number < (1 << bits) for number in values):
        raise SensorError('Invalid unsigned SENLLA input parameter: ' + name)
    return values


@dataclass(frozen=True)
class SENLLAInputSnapshot:
    """Immutable, complete raw PP binding; it carries no normal-save result."""
    identity: tuple
    expected: Mapping

    def __post_init__(self):
        object.__setattr__(self, 'identity', _identity(self.identity))
        if not isinstance(self.expected, Mapping) or set(self.expected) != set(SCHEMA):
            raise SensorError('SENLLA input snapshot requires exactly 93 parameters')
        object.__setattr__(self, 'expected', MappingProxyType({
            name: _value(name, self.expected[name]) for name in SCHEMA
        }))

    def parameters(self):
        """Return detached full input values, without any writable projection."""
        return {name: value if isinstance(value, str) else list(value)
                for name, value in self.expected.items()}

    def as_dict(self):
        return {
            'format': 'cbus-senlla-input-snapshot-v1',
            'unit_type': self.identity[0], 'firmware': self.identity[1],
            'catalog_number': self.identity[2], 'spec_filename': 'SENLLA.xml',
            'toolkit_class': 'TSENLLA', 'runtime_input_key_count': 8,
            'consumed_parameter_count': len(SCHEMA), 'expected': self.parameters(),
            'read_only': True, 'complete_toolkit_save': False, 'saved': False,
            'original_execution': False, 'physical_acceptance': False,
        }


class SENLLAInputs:
    """Validate the canonical complete schema and snapshot its required fields."""
    def __init__(self, spec):
        self.spec, self.codec = spec, MemoryCodec(spec)
        self._verify_schema()

    def _verify_schema(self):
        if self.spec.filename != 'SENLLA.xml' or self.spec.unit_type != 'SENLLA':
            raise SensorError('Use canonical SENLLA.xml / SENLLA for the complete input schema')
        for name, expected in SCHEMA.items():
            try:
                parameter = self.spec.get(name)
                layout = self.codec.layout(name)
                # Native Typebit packing ignores declared BitSize and ArraySkip,
                # including omitted metadata whose declared BitSize defaults8.
                actual = (parameter.type, layout.address, layout.array_size, layout.bit_size,
                          layout.bit_address, 0 if parameter.type == 'bit' else layout.array_skip)
                valid = parameter.name == name and actual == expected
            except (KeyError, TypeError, ValueError):
                valid = False
            if not valid:
                raise SensorError('Unsupported SENLLA input parameter layout: ' + name)

    def snapshot(self, current, *, identity):
        identity = _identity(identity)
        self._verify_schema()
        if not isinstance(current, Mapping):
            raise SensorError('SENLLA input snapshot requires a current PP mapping')
        expected = {}
        for name in SCHEMA:
            if name not in current:
                raise SensorError('Missing SENLLA input parameter: ' + name)
            value = _value(name, current[name])
            candidate = value if isinstance(value, str) else list(value)
            if not self.spec.validate_value(name, candidate)['valid']:
                raise SensorError('Invalid SENLLA input parameter: ' + name)
            expected[name] = value
        return SENLLAInputSnapshot(identity, expected)
