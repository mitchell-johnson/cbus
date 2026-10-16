"""Internal inherited SENLLA scalar projection from a complete raw snapshot.

This owns eleven baseline fields. It neither replays the complete fresh form
nor composes keys, applications, blocks, occupancy, banks or Scenes into a save.
Final metadata comes from the actual owning objects, rather than PP inference.
"""
from dataclasses import dataclass, replace
from types import MappingProxyType

from .memory import encode_sixbit
from .senlla_inputs import SCHEMA, SENLLAInputSnapshot
from .sensors import SensorError


# Names and ownership derived from senlla-baseline-scalars-source.json. Every
# required field is explicitly classified; delegated fields are not preserved
# by assumption or included in this component's writable projection.
_CLASSES = {
    'preserved_scalar_round_trip': (
        'DebounceTime', 'LongPressTime', 'EEPROMLevelStore', 'IRBank',
        'DisableIR', 'DisableIRNEC'),
    'scalar_normalization': ('RampRate', 'StatusReportInterval'),
    'owning_metadata': ('Project', 'UnitName', 'UnitAddress'),
    'non_sent_or_protected': (
        'CUSTYPE', 'EEPROM Checksum', 'EEPROMCheckSumActive', 'EEPROMChecksumAlarm',
        'KeyDisableInverted', 'LearnAnyApp', 'LearnMode', 'LearnedFlag', 'PatchEnable',
        'RetardationIndex', 'SceneCycleSelector', 'SceneToggleSelector', 'SerialNo'),
    'application_group_delegated': (
        'Application', 'AreaGroupAddress', 'GroupAddress', 'ControlAppGroupAddress',
        'SecondApplicationBlocks', 'CorridorLinkActive', 'CorridorLinkBlock',
        'CorridorLinkEnablerGroup', 'CorridorLinkOfficeBlock', 'SingleJoinEnablerGroup',
        'SingleJoinEnablerControlGroup', 'DualJoinEnablerGroup', 'DualJoinEnablerControlGroup'),
    'eight_key_delegated': (
        'BlockAllocation', 'JPCommand', 'SRCommand', 'LPCommand', 'LRCommand',
        'IndicatorBlockAssignment', 'SceneKeySelector'),
    'block_and_power_delegated': (
        'LightIndex', 'LightLevel', 'LightLevelStore1', 'LightLevelStore2',
        'TimerHighByte', 'TimerLowByte', 'TimerExpiryCommand'),
    'scene_delegated': ('SceneTable', 'SceneTablePointer'),
    'st7_surface_occupancy_bank_delegated': (
        'BankSwitchGroupLevelStore', 'BankSwitchGroupUsed', 'BankSwitchThresholdBehaviour',
        'BankSwitchThresholdGroup', 'BlockBankSwitchActive', 'BlockGroupLogic',
        'BroadcastActive', 'BroadcastBlock', 'IRBankKeyOffset', 'IndicatorControl',
        'LightLevelMarginGroup', 'LightLevelMarginGroupLevelStore', 'LightLevelTargetGroup',
        'LightLevelTargetGroupLevelStore', 'PECEnablerGroup', 'PECEnablerGroupLogic',
        'PECFunctionActive', 'PECFunctionBlock', 'PECFunctionIRActive', 'PECFunctionIRKey',
        'PECLevelStore', 'PECMarginLux', 'PECScaleFactor', 'PECTargetLux', 'PIRDark',
        'PIRDarkMovement', 'PIREnablerGroup', 'PIREnablerGroupLogic', 'PIRFunctionIRActive',
        'PIRFunctionIRKey', 'PIRLevelStore', 'PIRLightMovement', 'PotentiometerAFunction',
        'PotentiometerATimerBlock', 'PotentiometerBBankSwitchEnable', 'PotentiometerBFunction',
        'PotentiometerBTimerBlock', 'PowerUpBankSwitchGroupLevel', 'PowerUpMarginGroupLevel',
        'PowerUpTargetGroupLevel'),
}
CLASSIFICATION = MappingProxyType({
    name: category for category, names in _CLASSES.items() for name in names
})
if (len(CLASSIFICATION) != sum(map(len, _CLASSES.values()))
        or set(CLASSIFICATION) != set(SCHEMA)):
    raise AssertionError('SENLLA scalar ownership must classify exactly 93 fields once')
SCALAR_PARAMETERS = tuple(name for category in (
    'preserved_scalar_round_trip', 'scalar_normalization', 'owning_metadata')
    for name in _CLASSES[category])
NON_SENT_PARAMETERS = _CLASSES['non_sent_or_protected']


def _metadata_text(value, name):
    try:
        encode_sixbit(value)
    except (TypeError, ValueError):
        raise SensorError(name + ' requires at most eight representable ASCII characters') from None
    return value


@dataclass(frozen=True)
class ScalarSaveMetadata:
    """Actual save-time Project.TagName, selected unit.Address and CBusUnitName.

    Project.Name and the loaded unit.Project property are different sources.
    Supplying final context does not prove fresh UnitName cleaning or UI casing.
    """
    project_tag_name: str
    unit_address: int
    unit_name: str

    def __post_init__(self):
        _metadata_text(self.project_tag_name, 'Project.TagName')
        _metadata_text(self.unit_name, 'Unit.CBusUnitName')
        if type(self.unit_address) is not int or not 0 <= self.unit_address <= 255:
            raise SensorError('Unit.Address requires an unsigned byte')

    def as_dict(self):
        return {'project_tag_name': self.project_tag_name,
                'unit_address': self.unit_address, 'unit_name': self.unit_name}


def _ramp_ordinal(raw):
    # IntegerToCBusRampRate; output is an ordinal, not a duration in seconds.
    return raw if raw <= 15 else 1 if raw == 255 else 15


@dataclass(frozen=True)
class InheritedScalarState:
    snapshot: SENLLAInputSnapshot
    global_initialized: bool = False

    def __post_init__(self):
        if not isinstance(self.snapshot, SENLLAInputSnapshot):
            raise SensorError('Inherited scalars require a complete SENLLA input snapshot')
        # Revalidate and detach even when the caller constructed the snapshot.
        object.__setattr__(self, 'snapshot', SENLLAInputSnapshot(
            self.snapshot.identity, self.snapshot.expected))
        if type(self.global_initialized) is not bool:
            raise SensorError('Global initialization phase requires a Boolean')

    @property
    def loaded_scalars(self):
        raw = self.snapshot.expected
        return MappingProxyType({
            'DebounceTime': raw['DebounceTime'][0],
            'LongPressTime': raw['LongPressTime'][0],
            'RampRate': tuple(map(_ramp_ordinal, raw['RampRate'])),
            'EEPROMLevelStore': bool(raw['EEPROMLevelStore'][0]),
            'IRBank': raw['IRBank'][0],
            'InfraredClipsalEnabled': not bool(raw['DisableIR'][0]),
            'InfraredNECEnabled': not bool(raw['DisableIRNEC'][0]),
            'StatusReportInterval': raw['StatusReportInterval'][0],
        })

    @property
    def current_scalars(self):
        current = dict(self.loaded_scalars)
        if self.global_initialized:
            current['StatusReportInterval'] = max(current['StatusReportInterval'], 3)
        return MappingProxyType(current)

    def initialize_global(self):
        """Apply the separate fresh ST7 Global selector initialization phase."""
        return self if self.global_initialized else replace(self, global_initialized=True)

    def non_sent_parameters(self):
        """Detached raw baseline for fields this normal agent does not PPSET.

        This is not a prediction of device-maintained bytes after persistence.
        """
        return {name: list(self.snapshot.expected[name]) for name in NON_SENT_PARAMETERS}

    def parameters(self, *, metadata):
        """Project exactly eleven fields using explicit final owning metadata."""
        if not isinstance(metadata, ScalarSaveMetadata):
            raise SensorError('Supply explicit final ScalarSaveMetadata')
        metadata = ScalarSaveMetadata(metadata.project_tag_name, metadata.unit_address,
                                      metadata.unit_name)
        current = self.current_scalars
        return {
            'Project': metadata.project_tag_name.upper(),
            'UnitName': metadata.unit_name.upper(),
            'UnitAddress': [metadata.unit_address],
            'DebounceTime': [current['DebounceTime']],
            'LongPressTime': [current['LongPressTime']],
            'RampRate': list(current['RampRate']),
            'EEPROMLevelStore': [int(current['EEPROMLevelStore'])],
            'IRBank': [current['IRBank']],
            'DisableIR': [int(not current['InfraredClipsalEnabled'])],
            'DisableIRNEC': [int(not current['InfraredNECEnabled'])],
            'StatusReportInterval': [current['StatusReportInterval']],
        }

    def as_dict(self, *, metadata):
        loaded, current = dict(self.loaded_scalars), dict(self.current_scalars)
        loaded['RampRate'], current['RampRate'] = list(loaded['RampRate']), list(current['RampRate'])
        initialization = [] if not self.global_initialized else [{
            'phase': 'global_status_initialization',
            'raw': loaded['StatusReportInterval'],
            'initialized': current['StatusReportInterval'],
        }]
        parameters = self.parameters(metadata=metadata)
        return {
            'format': 'cbus-senlla-inherited-scalars-v1',
            'identity': list(self.snapshot.identity),
            'expected': self.snapshot.parameters(),
            'loaded_scalars': loaded, 'current_scalars': current,
            'global_initialization': initialization,
            'final_owning_metadata': metadata.as_dict(),
            'parameters': parameters, 'non_sent_parameters': self.non_sent_parameters(),
            'projected_parameter_count': len(parameters),
            'complete_toolkit_save': False, 'saved': False,
            'original_execution': False, 'physical_acceptance': False,
        }


def load_inherited_scalars(snapshot):
    """Load baseline scalar state without initializing Global or saving a unit."""
    return InheritedScalarState(snapshot)
