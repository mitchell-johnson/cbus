"""Toolkit ST7 light-level sensor (SENLL) dialog and forced save.

The Toolkit edits SENLL 2.x units with ``TddST7LightLevelSensor`` and the
``TCBusST7LightLevelSensorCGateAgent`` save: the multisensor save followed
by ``PrepareForcedParameters`` and a broadcast/indicator tail. A plan models
the admitted dialog controls and then that complete save, so the written PP
values are the values the Toolkit would leave after pressing OK. It edits an
existing PP session only: it never saves, transfers, or measures light. See
docs/sensors.md and docs/light-level-sensor-review.json.
"""
from dataclasses import dataclass, replace
from types import MappingProxyType

from .macros import _numbers
from .memory import MemoryCodec
from .sensors import (SensorApplyError, SensorError, _integer, _version, saved_margin, verify_native_schema)
from .sensors import margin_percent as loaded_margin_percent

# Toolkit registers TST7SENLL for SENLL 2.0.01..9 (numeric '.'-token order);
# C-Gate's catalogue selects SENLL_ST7.xml per band below. The intersection
# is admitted. SENLL 1.x (TSENLL) and SENLLA (TSENLLA) are other classes.
PROFILE = MappingProxyType({
    'unit_type': 'SENLL', 'toolkit_class': 'TST7SENLL', 'agent': 'TCBusST7LightLevelSensorCGateAgent',
    'catalog_numbers': ('5031PE', '5031PEWP', 'SLC5031PE', 'SLC5031PEWP,GY'),
    'bands': (('2.0.01', '2.0.99'), ('2.1.00', '2.1.99'), ('2.2.00', '2.2.99'), ('2.3.00', '2.3.99'),
              ('2.4.00', '2.4.99')),
    'spec_filename': 'SENLL_ST7.xml',
})
# TCBusST7LightLevelSensorCGateAgent.PrepareForcedParameters, unconditional,
# plus the multisensor save's PotentiometerBBankSwitchEnable.
FORCED = MappingProxyType({
    'PIRLightMovement': 0, 'PIRDarkMovement': 0, 'PIRDark': 0, 'DisableIR': 1, 'IRBankKeyOffset': 0,
    'CorridorLinkOfficeBlock': 0, 'CorridorLinkBlock': 0, 'CorridorLinkEnablerGroup': 255, 'CorridorLinkActive': 0,
    'BroadcastBlock': 4, 'PIREnablerGroup': 255, 'SingleJoinEnablerGroup': 255, 'SingleJoinEnablerControlGroup': 255,
    'DualJoinEnablerGroup': 255, 'DualJoinEnablerControlGroup': 255, 'PECFunctionActive': 1, 'PECFunctionBlock': 1,
    'PECFunctionIRKey': 0, 'PECFunctionIRActive': 0, 'PIRFunctionIRKey': 0, 'PIRFunctionIRActive': 0,
    'PIRLevelStore': 0, 'PECEnablerGroupLogic': 0, 'PIREnablerGroupLogic': 0, 'PotentiometerAFunction': 0,
    'PotentiometerBFunction': 0, 'PotentiometerATimerBlock': 0, 'PotentiometerBTimerBlock': 0,
    'PotentiometerBBankSwitchEnable': 0,
})
RAMP_RATE = (7, 7)            # RampRate is set to the string "0x7 0x7".
FORCED_LIGHT_LEVEL = (8,)     # SetArrayInteger(LightLevel, 8, 0)
# The agent also clears the programmable flag of these attributes, so the
# Toolkit never sends them and their stored values are preserved.
NOT_SENT = ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand', 'BlockAllocation', 'IndicatorFunction',
            'SceneKeySelector', 'PrimaryColour')
# Indicator radio -> IndicatorBlockAssignment[0]; AfterLoad reads 5 as the
# enable-group LED, 2 as the on/off LED and anything else as the level LED.
INDICATORS = MappingProxyType({'light_level': 1, 'on_off': 2, 'enable': 5})
# Dialog group combos bind Blocks[1], Blocks[2] and Blocks[4].
BLOCKS = MappingProxyType({'level_group': 1, 'on_off_group': 2, 'broadcast_group': 4})
ON_OFF_BLOCK, BROADCAST_BLOCK = 2, 4
MAX_TARGET = 200              # SetTargetLuxEditText clamps the target byte (2000 lux).
MAX_TARGET_LUX = 2000         # SetTargetLuxByteValue clamps entered lux.
LAYOUTS = MappingProxyType({
    'PIRLightMovement': (50, 1, 8, 0, 0), 'PIRDarkMovement': (51, 1, 8, 0, 0), 'PIRDark': (52, 1, 8, 0, 0),
    'DisableIR': (53, 1, 1, 2, 0), 'IRBankKeyOffset': (53, 1, 3, 4, 0),
    'CorridorLinkOfficeBlock': (68, 1, 3, 0, 0), 'CorridorLinkBlock': (68, 1, 3, 3, 0),
    'CorridorLinkActive': (68, 1, 1, 7, 0), 'CorridorLinkEnablerGroup': (92, 1, 8, 0, 0),
    'BroadcastBlock': (70, 1, 3, 0, 0), 'BroadcastActive': (70, 1, 3, 5, 0),
    'PIREnablerGroup': (88, 1, 8, 0, 0), 'PECEnablerGroup': (89, 1, 8, 0, 0),
    'SingleJoinEnablerGroup': (90, 1, 8, 0, 0), 'DualJoinEnablerGroup': (91, 1, 8, 0, 0),
    'SingleJoinEnablerControlGroup': (93, 1, 8, 0, 0), 'DualJoinEnablerControlGroup': (94, 1, 8, 0, 0),
    'PECFunctionBlock': (96, 1, 3, 3, 0), 'PECFunctionActive': (96, 1, 1, 6, 0),
    'PECFunctionIRKey': (97, 1, 3, 3, 0), 'PECFunctionIRActive': (97, 1, 1, 6, 0),
    'PIRFunctionIRKey': (98, 1, 3, 3, 0), 'PIRFunctionIRActive': (98, 1, 1, 6, 0),
    'PIRLevelStore': (99, 1, 1, 4, 0), 'PECEnablerGroupLogic': (99, 1, 1, 5, 0),
    'PIREnablerGroupLogic': (99, 1, 1, 6, 0),
    'PotentiometerAFunction': (101, 1, 2, 3, 0), 'PotentiometerBFunction': (101, 1, 2, 5, 0),
    'PotentiometerATimerBlock': (102, 1, 3, 3, 0), 'PotentiometerBTimerBlock': (103, 1, 3, 3, 0),
    'PotentiometerBBankSwitchEnable': (103, 1, 1, 6, 0),
    'RampRate': (64, 2, 8, 0, 0), 'LightLevel': (1, 10, 8, 0, 0), 'GroupAddress': (80, 8, 8, 0, 0),
    'Application': (33, 2, 8, 0, 0), 'SecondApplicationBlocks': (69, 1, 8, 0, 0),
    'PECTargetLux': (27, 1, 8, 0, 0), 'PECMarginLux': (28, 1, 8, 0, 0),
    'IndicatorBlockAssignment': (96, 8, 3, 0, 0),
})
BITS = frozenset(('DisableIR', 'CorridorLinkActive', 'PECFunctionActive', 'PECFunctionIRActive',
                  'PIRFunctionIRActive', 'PIRLevelStore', 'PECEnablerGroupLogic', 'PIREnablerGroupLogic'))


def profile_refusal(unit_type, firmware, catalog_number):
    """Return why a unit identity is outside the admitted SENLL profile, or None."""
    if unit_type != PROFILE['unit_type']:
        if unit_type == 'SENLLA':
            return 'SENLLA uses the Toolkit surface-mount class TSENLLA and the SENLLA layout'
        return 'Only SENLL ST7 light-level sensors use this workflow'
    version = _version(firmware)
    if version is None or not any(_version(low) <= version <= _version(high) for low, high in PROFILE['bands']):
        return (f'SENLL firmware {firmware} has no Toolkit TST7SENLL class and SENLL_ST7 catalogue band '
                '(SENLL 1.x uses TSENLL and SENLL.xml)')
    if catalog_number not in PROFILE['catalog_numbers']:
        return 'SENLL catalogue number must be one of ' + ', '.join(PROFILE['catalog_numbers'])
    return None


def check_profile(unit_type, firmware, catalog_number, *, subject='Unit identity'):
    reason = profile_refusal(unit_type, firmware, catalog_number)
    if reason is not None:
        raise SensorError(f'{subject} must be an admitted ST7 SENLL light-level sensor: {reason}')
    return (unit_type, firmware, catalog_number)


def target_byte(lux):
    """CIS_CBus.Lux2550ToByte for the dialog's 0..2000 lux entry: Ceil(lux / 10)."""
    lux = _integer(lux, 'Target lux', 0, MAX_TARGET_LUX)
    return -(-lux // 10)


def indicator_state(assignment):
    """AfterLoad: IndicatorBlockAssignment[0] 5 -> enable, 2 -> on_off, else light_level."""
    return {5: 'enable', 2: 'on_off'}.get(assignment, 'light_level')


@dataclass(frozen=True)
class LightLevelPlan:
    expected: dict
    changes: dict
    dialog: dict
    identity: tuple | None = None

    def __post_init__(self):
        for name in ('expected', 'changes'):
            object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))
        object.__setattr__(self, 'dialog', MappingProxyType(dict(self.dialog)))

    def as_dict(self):
        firmware, catalog_number = self.identity[1:] if self.identity else (None, None)
        return {'format': 'cbus-st7-light-level-sensor-plan-v1', 'unit_type': PROFILE['unit_type'],
                'firmware': firmware, 'catalog_number': catalog_number, 'spec_filename': PROFILE['spec_filename'],
                'toolkit_class': PROFILE['toolkit_class'], 'dialog': dict(self.dialog),
                'forced_by_toolkit_save': sorted(FORCED) + ['BroadcastActive', 'IndicatorBlockAssignment',
                                                            'LightLevel', 'RampRate'],
                'not_sent_by_toolkit': list(NOT_SENT),
                'expected': {k: list(v) for k, v in self.expected.items()},
                'changes': {k: list(v) for k, v in self.changes.items()},
                'saved': False, 'device_verified': False}


class LightLevelSensor:
    def __init__(self, spec):
        # SENLL_ST7.xml declares the SENPILL type; the catalogue selects it for SENLL.
        if spec.filename != PROFILE['spec_filename']:
            raise SensorError('Use SENLL_ST7.xml for SENLL 2.0.01..2.4.99')
        self.spec, self.codec = spec, MemoryCodec(spec)
        for name, expected in LAYOUTS.items():
            layout = self.codec.layout(name)
            actual = (layout.address, layout.array_size, layout.bit_size, layout.bit_address, layout.array_skip)
            if actual != expected or layout.parameter.type != ('bit' if name in BITS else 'int'):
                raise SensorError('Unsupported light-level sensor parameter layout: ' + name)

    def snapshot(self, current):
        result = {}
        for name in LAYOUTS:
            if name not in current:
                raise SensorError('Missing current light-level sensor parameter: ' + name)
            values = _numbers(current[name])
            if not self.spec.get(name).validate_value(list(values))['valid']:
                raise SensorError('Invalid current light-level sensor parameter: ' + name)
            result[name] = values
        return result

    def plan(self, current, *, level_group=None, on_off_group=None, on_off_application=None,
             broadcast_group=None, enable_group=None, indicator=None, target_lux=None,
             margin_percent=None, identity=None):
        """Plan SENLL dialog edits followed by the complete Toolkit save.

        Groups are 0..254, or 255 for none. ``on_off_application`` is
        ``primary`` or ``secondary``; ``indicator`` is ``light_level``,
        ``on_off`` or ``enable``. With no options the plan is the Toolkit's
        OK/save of an unchanged dialog.
        """
        if identity is not None:
            if not isinstance(identity, tuple) or len(identity) != 3:
                raise SensorError('Identity must be (unit_type, firmware, catalog_number)')
            identity = check_profile(*identity)
        original = self.snapshot(current)
        updates = {name: list(values) for name, values in original.items()}
        # Dialog state loaded by the Toolkit before any edit.
        applications = original['Application']
        secondary_available = applications[1] != 255
        on_off_mask = 1 << ON_OFF_BLOCK
        # RefreshAppStateChange drops the secondary application when the unit has none.
        secondary = bool(original['SecondApplicationBlocks'][0] & on_off_mask) and secondary_available
        percent = loaded_margin_percent(original['PECTargetLux'][0], original['PECMarginLux'][0])
        target = min(original['PECTargetLux'][0], MAX_TARGET)
        state = indicator_state(original['IndicatorBlockAssignment'][0])
        edits = {}
        for label, value in (('level_group', level_group), ('on_off_group', on_off_group),
                             ('broadcast_group', broadcast_group)):
            if value is not None:
                edits[label] = _integer(value, label.replace('_', ' ').capitalize(), 0, 255)
                updates['GroupAddress'][BLOCKS[label]] = edits[label]
        if on_off_application is not None:
            if on_off_application not in ('primary', 'secondary'):
                raise SensorError('on_off_application must be primary or secondary')
            if on_off_application == 'secondary' and not secondary_available:
                raise SensorError('The secondary application is not set, so the on/off group uses the primary one')
            secondary = on_off_application == 'secondary'
        if secondary:
            updates['SecondApplicationBlocks'][0] |= on_off_mask
        else:
            updates['SecondApplicationBlocks'][0] &= ~on_off_mask
        if enable_group is not None:
            updates['PECEnablerGroup'][0] = _integer(enable_group, 'Enable group', 0, 255)
        if indicator is not None:
            if indicator not in INDICATORS:
                raise SensorError('indicator must be light_level, on_off or enable')
            state = indicator
        if target_lux is not None:
            target = target_byte(target_lux)
        if margin_percent is not None:
            percent = _integer(margin_percent, 'Margin percent', 0, 100)
        self._check_groups(original, updates, edits, enable_group)
        self._toolkit_save(original, updates, target, percent, state)
        if updates['PECMarginLux'][0] > 255:
            raise SensorError(f'The loaded {percent}% margin at target byte {target} exceeds the native margin byte; '
                              'supply margin_percent')
        changes = {name: tuple(values) for name, values in updates.items() if tuple(values) != original[name]}
        self.codec.encode_many(changes)
        dialog = {'indicator': state, 'target_lux': target * 10, 'target_clamped': original['PECTargetLux'][0] > MAX_TARGET,
                  'margin_percent': percent, 'on_off_application': 'secondary' if secondary else 'primary',
                  'secondary_application_available': secondary_available}
        return LightLevelPlan(original, changes, dialog, identity)

    @staticmethod
    def _check_groups(original, updates, edits, enable_group):
        """The dialog combos exclude groups already used by a block or the enable group.

        Groups are compared as (application, address) objects. A combo always
        lists its own current group, so an unchanged selection is accepted.
        """
        applications = original['Application']

        def keys(state):
            second = state['SecondApplicationBlocks'][0]
            return {i: (applications[1 if second & (1 << i) else 0], state['GroupAddress'][i]) for i in range(8)}
        before, after = keys(original), keys(updates)
        enable = (applications[0], updates['PECEnablerGroup'][0])
        for label, value in edits.items():
            index = BLOCKS[label]
            if value == 255 or after[index] == before[index]:
                continue
            if after[index][0] == 255:
                raise SensorError(f'{label} needs an assigned application for block {index + 1}')
            if any(i != index and key == after[index] for i, key in after.items()) or enable == after[index]:
                raise SensorError(f'Group {value} is already used by another block or the enable group')
        if enable_group is not None and enable_group not in (255, original['PECEnablerGroup'][0]):
            if applications[0] == 255:
                raise SensorError('The enable group needs an assigned primary application')
            if enable in after.values():
                raise SensorError(f'Enable group {enable_group} is already used by a block')

    @staticmethod
    def _toolkit_save(original, updates, target, percent, state):
        # Multisensor BeforeSave: target byte and the x87 margin round trip.
        updates['PECTargetLux'][0] = target
        updates['PECMarginLux'][0] = saved_margin(target, percent)
        # Light-level PrepareForcedParameters.
        for name, value in FORCED.items():
            updates[name][0] = value
        updates['RampRate'] = list(RAMP_RATE)
        for index in FORCED_LIGHT_LEVEL:
            updates['LightLevel'][index] = 0
        # Light-level BeforeSave tail.
        updates['BroadcastActive'][0] = int(updates['GroupAddress'][BROADCAST_BLOCK] != 255)
        updates['IndicatorBlockAssignment'] = [INDICATORS[state]] + [0] * 7

    def _verify_profile(self, session):
        return check_profile(session.unit_type, session.firmware, session.catalog_number, subject='Native session')

    def apply(self, session, plan):
        if not isinstance(plan, LightLevelPlan) or set(plan.expected) != set(LAYOUTS) or any(
                n not in LAYOUTS for n in plan.changes):
            raise SensorError('Plan contains fields outside the light-level sensor workflow')
        self.codec.encode_many(plan.changes)
        identity = self._verify_profile(session)
        if plan.identity is not None and plan.identity != identity:
            raise SensorError('Plan was created for another unit firmware or catalogue number')
        verify_native_schema(session, self.spec, LAYOUTS, BITS)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise SensorError('PP parameters changed since the light-level sensor plan was created')
        attempted = []
        try:
            for name, values in plan.changes.items():
                attempted.append(name)
                session.set(name, ' '.join(map(str, values)))
            expected = dict(plan.expected)
            expected.update(plan.changes)
            if self.snapshot(session.values()) != expected:
                raise SensorError('Native light-level sensor readback differs from the plan')
        except (RuntimeError, OSError, ValueError) as error:
            # No recovery I/O after an uncertain write; the PP session stays unsaved.
            raise SensorApplyError(error, attempted) from error
        return {**replace(plan, identity=identity).as_dict(), 'verified': True}

    def configure(self, session, **options):
        identity = self._verify_profile(session)
        return self.apply(session, self.plan(session.values(), identity=identity, **options))


__all__ = ['FORCED', 'INDICATORS', 'LAYOUTS', 'LightLevelPlan', 'LightLevelSensor', 'NOT_SENT', 'PROFILE',
           'check_profile', 'indicator_state', 'profile_refusal', 'target_byte']
