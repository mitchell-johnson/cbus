"""Toolkit ST7 light-level sensor (SENLL) dialog and forced save.

The Toolkit edits SENLL 2.x units with ``TddST7LightLevelSensor`` and the
``TCBusST7LightLevelSensorCGateAgent`` save: the multisensor save followed
by ``PrepareForcedParameters`` and a broadcast/indicator tail. A plan models
the admitted dialog controls and then that complete save, so the written PP
values are the values the Toolkit would leave after pressing OK. It edits an
existing PP session only: it never saves, transfers, or measures light. See
docs/sensors.md and docs/light-level-sensor-review.json.
"""
import copy
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
    'TimerHighByte': (136, 8, 8, 0, 0), 'TimerLowByte': (144, 8, 8, 0, 0),
    'PECLevelStore': (99, 1, 1, 3, 0),
    'StatusReportInterval': (66, 1, 8, 0, 0),
})
BITS = frozenset(('DisableIR', 'CorridorLinkActive', 'PECFunctionActive', 'PECFunctionIRActive',
                  'PIRFunctionIRActive', 'PIRLevelStore', 'PECLevelStore', 'PECEnablerGroupLogic', 'PIREnablerGroupLogic'))
POWER_UP = ('disabled', 'enabled', 'resume')
MAX_ON_OFF_CONTROLS = 64


def validate_on_off_controls(value):
    """Validate an ordered, caller-declared control history; no model state is imported."""
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_ON_OFF_CONTROLS:
        raise SensorError('on_off_controls must contain 1..64 application/group operations')
    result = []
    for operation in value:
        if not isinstance(operation, dict) or len(operation) != 1:
            raise SensorError('Each on/off control accepts exactly one application or group field')
        if 'application' in operation:
            choice = operation['application']
            if not isinstance(choice, str) or choice not in ('primary', 'secondary'):
                raise SensorError('On/off control application must be primary or secondary')
            result.append({'application': choice})
        elif 'group' in operation:
            result.append({'group': _integer(operation['group'], 'On/off control group', 0, 255)})
        else:
            raise SensorError('Each on/off control accepts exactly one application or group field')
    return result


class _OnOffGraph:
    """Fresh SENLL's eight blocks and zero keys, with source-ordered callbacks.

    A (application, address) pair denotes an already established group object.
    The admitted raw block and selected hidden getters establish non-unused
    objects. Other source inventories and creation decisions are outside this
    profile, so explicit histories cannot invent missing destination objects.
    """

    def __init__(self, original, updates):
        self.original, self.updates = original, updates
        self.applications = original['Application']
        if (not 48 <= self.applications[0] <= 95 or
                self.applications[1] != 255 and not 48 <= self.applications[1] <= 95):
            raise SensorError('Explicit SENLL controls require primary Lighting 48..95 and secondary Lighting 48..95 or 255')
        mask = original['SecondApplicationBlocks'][0]
        self.groups = [(self.applications[int(bool(mask & (1 << index)))], address)
                       for index, address in enumerate(original['GroupAddress'])]
        self.known = set(self.groups)
        self.hidden = {}
        self.journal = {'format': 'cbus-senll-control-history-v1', 'explicit': True,
                        'initialization_profile': 'fresh_zero_key_callbacks',
                        'metadata_profile': 'raw_blocks_and_selected_hidden_getters',
                        'unmodelled_group_inventories': ['AreaGroupAddress', 'SceneTable/SceneTablePointer'],
                        'source_group_callbacks_modelled': True,
                        'phase_order': ['raw_applications_bits_groups', 'secondary_application_refresh',
                                        'hidden_group_load', 'on_off_controls', 'flat_dialog_edits', 'forced_save'],
                        'input_key_count': 0, 'block_allocation_mutated': False,
                        'original_execution': False, 'physical_acceptance': False,
                        'load': [], 'controls': [], 'unverified_group_lookups': [],
                        'forced_save_last': True}
        # GetBlockApplications loads all eight bits before GetBlockGroup; after
        # EndUpdate, Application2ObjectRefresh clears TRUE bits in index order.
        if self.applications[1] == 255:
            for index in range(8):
                if mask & (1 << index):
                    self.journal['load'].append(self._switch(index, False, hidden=False))
        primary = self.applications[0]
        if original['SingleJoinEnablerControlGroup'][0] != 255 or original['DualJoinEnablerControlGroup'][0] != 255:
            join = (203, original['SingleJoinEnablerControlGroup'][0])
            dual_join = (203, original['DualJoinEnablerControlGroup'][0])
        elif original['SingleJoinEnablerGroup'][0] != 255 or original['DualJoinEnablerGroup'][0] != 255:
            join = (primary, original['SingleJoinEnablerGroup'][0])
            dual_join = (primary, original['DualJoinEnablerGroup'][0])
        else:
            join = (255, 255)
            dual_join = (255, 255)
        # Corridor is loaded from primary even when inactive/unsupported.
        self.hidden = {'pec': (primary, original['PECEnablerGroup'][0]),
                       'corridor': (primary, original['CorridorLinkEnablerGroup'][0]), 'join': join}
        self.known.update(self.hidden.values())
        # AfterLoad performs both create-enabled Join getters in the selected
        # branch. Only the single Join object participates in the callback.
        self.known.add(dual_join)
        # The unconditional occupancy enable getter runs even though this
        # class has zero occupancy keys. It does not reserve a callback group.
        pir_enable = (primary, original['PIREnablerGroup'][0])
        self.known.add(pir_enable)
        self.journal['hidden_groups_after_load'] = {name: list(key) for name, key in self.hidden.items()}
        self.journal['dual_join_group_after_load'] = list(dual_join)
        self.journal['pir_enable_group_after_load'] = list(pir_enable)
        self.journal['initialized'] = self.view()

    def view(self):
        return {'groups': [list(key) for key in self.groups],
                'second_application_blocks': self.updates['SecondApplicationBlocks'][0]}

    def _set_group(self, index, key, *, hidden):
        if self.groups[index] == key:
            return []
        self.groups[index] = key
        self.updates['GroupAddress'][index] = key[1]
        matches = [name for name, reserved in self.hidden.items() if key == reserved] if hidden and key[1] != 255 else []
        if matches:
            self.groups[index] = (key[0], 255)
            self.updates['GroupAddress'][index] = 255
        return matches

    def _switch(self, index, secondary, *, hidden):
        before = self.view()
        bit = 1 << index
        changed = bool(self.updates['SecondApplicationBlocks'][0] & bit) != secondary
        row = {'block_index': index, 'application': 'secondary' if secondary else 'primary',
               'secondary_changed': changed, 'before': before, 'scan': [], 'collision_block_index': None,
               'hidden_group_callbacks': []}
        if changed:
            target = self.applications[int(secondary)]
            if secondary:
                self.updates['SecondApplicationBlocks'][0] |= bit
            else:
                self.updates['SecondApplicationBlocks'][0] &= ~bit
            # Re-read the switched group's address at every iteration. Clearing
            # it on the first match makes all later comparisons use address255.
            for other in range(8):
                if other == index or self.groups[other][1] == 255:
                    continue
                row['scan'].append(other)
                candidate = (target, self.groups[index][1])
                if candidate == self.groups[other]:
                    row['collision_block_index'] = other
                    self._set_group(index, (target, 255), hidden=hidden)
            address = self.groups[index][1]
            destination = (target, address)
            if address != 255 and destination not in self.known:
                raise SensorError('SENLL destination group is not established by the admitted source getters; '
                                  'additional metadata or creation/decline decision is unsupported')
            row['hidden_group_callbacks'] = self._set_group(index, destination, hidden=hidden)
        row['after'] = self.view()
        return row

    def offered(self):
        current = self.groups[ON_OFF_BLOCK]
        excluded = {key[1] for index, key in enumerate(self.groups)
                    if index != ON_OFF_BLOCK and key[0] == current[0] and key[1] != 255}
        if self.hidden['pec'][0] == current[0] and self.hidden['pec'][1] != 255:
            excluded.add(self.hidden['pec'][1])
        # Toolkit always keeps the combo's current object, even a duplicate.
        excluded.discard(current[1])
        known = {key[1] for key in self.known if key[0] == current[0]}
        known.add(255)
        return sorted(known - excluded), sorted(excluded)

    def run(self, controls):
        for operation in controls:
            offered, excluded = self.offered()
            if 'application' in operation:
                secondary = operation['application'] == 'secondary'
                if secondary and self.applications[1] == 255:
                    raise SensorError('The secondary application is not set, so the on/off switch is disabled')
                row = self._switch(ON_OFF_BLOCK, secondary, hidden=True)
            else:
                address = operation['group']
                if address in excluded:
                    raise SensorError(f'On/off group {address} is excluded by another block or the maintenance enable group')
                if address not in offered:
                    raise SensorError('SENLL destination group is not established by the admitted source getters; '
                                      'additional metadata or creation/decline decision is unsupported')
                before = self.view()
                key = (self.groups[ON_OFF_BLOCK][0], address)
                callbacks = self._set_group(ON_OFF_BLOCK, key, hidden=True)
                row = {'block_index': ON_OFF_BLOCK, 'group': address, 'before': before, 'after': self.view(),
                       'hidden_group_callbacks': callbacks}
            row['requested'] = dict(operation)
            row['offered_before'], row['excluded_before'] = offered, excluded
            row['offered_after'], row['excluded_after'] = self.offered()
            self.journal['controls'].append(row)
        self.journal['before_forced_save'] = self.view()
        return self.journal


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
    control_history: dict | None = None

    def __post_init__(self):
        for name in ('expected', 'changes'):
            object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))
        object.__setattr__(self, 'dialog', MappingProxyType(dict(self.dialog)))
        if self.control_history is not None:
            object.__setattr__(self, 'control_history', MappingProxyType(copy.deepcopy(dict(self.control_history))))

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
                'control_history': copy.deepcopy(dict(self.control_history)) if self.control_history is not None else None,
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
             margin_percent=None, broadcast_interval_seconds=None, power_up=None,
             status_report_interval=None, identity=None, on_off_controls=None):
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
        if on_off_controls is not None and any(value is not None for value in
                (on_off_application, on_off_group, level_group, broadcast_group, enable_group)):
            raise SensorError('Explicit on_off_controls cannot be mixed with flat application/group edits')
        controls = [] if on_off_controls is None else validate_on_off_controls(on_off_controls)
        original = self.snapshot(current)
        updates = {name: list(values) for name, values in original.items()}
        history = None if on_off_controls is None else _OnOffGraph(original, updates).run(controls)
        # The SENLL Global frame's native integer selector lists 3..255.
        # Its formatter labels these values in seconds; there is no time-byte
        # conversion. Values below 3 display as 3, but the initialization
        # callback's writeback has not been executed in the original GUI.
        status_interval = original['StatusReportInterval'][0]
        if status_report_interval is not None:
            status_interval = _integer(status_report_interval, 'Status report interval', 3, 255)
        elif status_interval < 3:
            raise SensorError('Stored StatusReportInterval below 3 has an unverified Global initialization writeback; '
                              'supply status_report_interval in 3..255 explicitly')
        updates['StatusReportInterval'][0] = status_interval
        # Dialog state loaded by the Toolkit before any edit.
        applications = original['Application']
        secondary_available = applications[1] != 255
        on_off_mask = 1 << ON_OFF_BLOCK
        # RefreshAppStateChange drops the secondary application when the unit has none.
        secondary = bool(updates['SecondApplicationBlocks'][0] & on_off_mask) and secondary_available
        percent = loaded_margin_percent(original['PECTargetLux'][0], original['PECMarginLux'][0])
        target = min(original['PECTargetLux'][0], MAX_TARGET)
        state = indicator_state(original['IndicatorBlockAssignment'][0])
        from .pir_sensors import power_up_state
        loaded_power_up = power_up_state(original['LightLevel'][9], original['PECEnablerGroupLogic'][0],
                                        original['PECLevelStore'][0])
        requested_power_up = loaded_power_up
        if power_up is not None:
            if power_up not in POWER_UP:
                raise SensorError('power_up must be disabled, enabled or resume')
            requested_power_up = POWER_UP.index(power_up)
        # The inherited multisensor SavePowerFail runs before the SENLL forced
        # save clears PECEnablerGroupLogic. Preserve that original order, even
        # when it changes the state subsequently displayed by the dialog.
        if requested_power_up == 2:
            updates['PECLevelStore'][0] = 1
        else:
            updates['PECLevelStore'][0] = 0
            updates['LightLevel'][9] = 255 if bool(requested_power_up) != bool(original['PECEnablerGroupLogic'][0]) else 0
        # InternalCreate sets block 5's TimerMin=10. Both timer/minimum change
        # handlers clamp the loaded timer, so an unchanged OK also writes 10
        # for a stored interval below the minimum.
        interval = max(10, original['TimerHighByte'][BROADCAST_BLOCK] * 256 + original['TimerLowByte'][BROADCAST_BLOCK])
        if broadcast_interval_seconds is not None:
            interval = _integer(broadcast_interval_seconds, 'Broadcast interval seconds', 10, 65535)
        updates['TimerHighByte'][BROADCAST_BLOCK], updates['TimerLowByte'][BROADCAST_BLOCK] = divmod(interval, 256)
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
                  'secondary_application_available': secondary_available,
                  'status_report_interval': status_interval,
                  'status_report_interval_unit': 'seconds',
                  'broadcast_interval_seconds': updates['TimerHighByte'][BROADCAST_BLOCK] * 256 + updates['TimerLowByte'][BROADCAST_BLOCK],
                  'power_up_loaded': POWER_UP[loaded_power_up], 'power_up': POWER_UP[requested_power_up],
                  'power_up_after_reload': POWER_UP[power_up_state(updates['LightLevel'][9], updates['PECEnablerGroupLogic'][0],
                                                                updates['PECLevelStore'][0])]}
        return LightLevelPlan(original, changes, dialog, identity, history)

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
        # TInputBlock.RefreshBlockApplicationFromBlockSecondary detects a
        # destination block collision, migrates shared key allocations to that
        # block and clears this block's group. This dialog plan does not yet
        # model those key-allocation callbacks. Refuse both an implicit retained
        # group and an explicit same-group selection before changing PP state.
        index = ON_OFF_BLOCK
        if (after[index][0] != before[index][0] and after[index][1] != 255
                and any(i != index and key == after[index] for i, key in after.items())):
            raise SensorError('The on/off application change reaches a group already used by another block; '
                              'legacy flat key-block reassignment remains refused; '
                              'use explicit ordered on_off_controls / --on-off-control for the zero-key SENLL callbacks')
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
