"""Toolkit ST7 PIR sensor dialog and forced save for SENPIROA/SENPIRIA/SENPIRIB.

The Toolkit edits these units with its PIR class, not the SENPILL multisensor
class. Its save runs the multisensor save and then forces the occupancy masks,
potentiometers and every join, corridor, infrared and light-level field that
the PIR dialog hides. A plan here models the admitted dialog controls and then
that complete save, so the written PP values equal what the Toolkit would leave
after pressing OK. It edits an existing PP session only: it never saves,
transfers or simulates PIR behaviour. See docs/sensors.md and
docs/pir-sensor-review.json.
"""
from dataclasses import dataclass, replace
from types import MappingProxyType
import xml.etree.ElementTree as ET

from .macros import MICRO_FUNCTIONS, STAGES, _numbers
from .memory import MemoryCodec
from .programming import xml_text
from .sensors import (EVENTS, EXPIRY, SensorError, SensorApplyError, _integer, _version, margin_percent,
                      saved_margin)

# Toolkit registers TST7SENPIROA for SENPIROA and TST7SENPIRSS for SENPIRIA
# from 2.0.01 and for SENPIRIB 2.0.01..2.3.9 (numeric '.'-token order). C-Gate's
# catalogue selects these specifications per firmware band; only the
# intersection is admitted. SENPIRIB 2.3.10..2.3.99 has no Toolkit ST7 class
# and SENPIRIB 2.4 uses the SENPIRIC layout.
_ST7 = (('2.0.01', '2.0.99'), ('2.1.00', '2.1.99'), ('2.2.00', '2.2.99'), ('2.3.00', '2.3.99'))
PROFILES = MappingProxyType({
    'SENPIROA': {'toolkit_class': 'TST7SENPIROA', 'catalog_numbers': ('5750WPL', 'SLC5750WPL,GY'),
                 'bands': tuple((low, high, 'SENPIROA_ST7.xml') for low, high in _ST7)
                 + (('2.4.00', '2.4.99', 'SENPIROA_ST7_2.xml'),)},
    'SENPIRIA': {'toolkit_class': 'TST7SENPIRSS', 'catalog_numbers': ('5751L', 'SLC5751L,WE'),
                 'bands': tuple((low, high, 'SENPIRIA_ST7.xml') for low, high in _ST7)
                 + (('2.4.00', '2.4.99', 'SENPIRIA_ST7_2.xml'),)},
    'SENPIRIB': {'toolkit_class': 'TST7SENPIRSS', 'catalog_numbers': ('5753L', 'SLC5753L'),
                 'bands': tuple((low, high, 'SENPIRIB_ST7.xml') for low, high in _ST7[:3])
                 + (('2.3.00', '2.3.9', 'SENPIRIB_ST7.xml'),)},
})
KEYS = 4  # TST7SENPIRSS/TST7SENPIROA.MaximumKeyCount and PIR unit MaximumBlockCount.
# Fixed PIR key events: dialog templates 0x1F/0x20/0x22/0x21 use the same
# micro-function groups as the SENPILL events (docs/pir-sensor-review.json).
KEY_EVENTS = MappingProxyType({1: 'day', 2: 'night', 3: 'sunset', 4: 'any'})
POWER_UP = ('disabled', 'enabled', 'resume')
# TCBusST7PIRSensorCGateAgent.PrepareForcedParameters, unconditional.
FORCED = MappingProxyType({
    'PIRLightMovement': 9, 'PIRDarkMovement': 10, 'PIRDark': 4, 'IRBank': 0, 'DisableIR': 1,
    'IRBankKeyOffset': 0, 'CorridorLinkOfficeBlock': 0, 'CorridorLinkBlock': 0,
    'CorridorLinkEnablerGroup': 255, 'CorridorLinkActive': 0, 'BroadcastBlock': 0, 'IndicatorControl': 0,
    'PECEnablerGroup': 255, 'SingleJoinEnablerGroup': 255, 'SingleJoinEnablerControlGroup': 255,
    'DualJoinEnablerGroup': 255, 'DualJoinEnablerControlGroup': 255, 'ControlAppGroupAddress': 255,
    'PECFunctionBlock': 0, 'PECFunctionActive': 0, 'PECFunctionIRKey': 0, 'PECFunctionIRActive': 0,
    'PIRFunctionIRKey': 0, 'PIRFunctionIRActive': 0, 'PECLevelStore': 0, 'PECEnablerGroupLogic': 0,
    'PotentiometerAFunction': 1, 'PotentiometerBFunction': 0, 'PotentiometerATimerBlock': 0,
    'PotentiometerBTimerBlock': 0,
    # TCBusST7MultisensorCGateAgent.BeforeSaveProgrammingInformation, unconditional.
    'PotentiometerBBankSwitchEnable': 0,
})
FORCED_LIGHT_LEVEL = (4, 5, 6, 7, 9)  # SetArrayInteger(LightLevel, index, 0)
INDICATOR_DISABLED = (7, 0, 0, 0, 0, 0, 0, 0)
# Address, count, bits, bit offset, byte skip; checked against the spec and
# the native schema. No distributed vendor catalogue.
LAYOUTS = MappingProxyType({
    'JPCommand': (104, 8, 4, 4, 1), 'SRCommand': (104, 8, 4, 0, 1),
    'LPCommand': (105, 8, 4, 4, 1), 'LRCommand': (105, 8, 4, 0, 1),
    'PIRLightMovement': (50, 1, 8, 0, 0), 'PIRDarkMovement': (51, 1, 8, 0, 0), 'PIRDark': (52, 1, 8, 0, 0),
    'IRBank': (53, 1, 2, 0, 0), 'DisableIR': (53, 1, 1, 2, 0), 'IRBankKeyOffset': (53, 1, 3, 4, 0),
    'BlockAllocation': (54, 8, 8, 0, 0), 'GroupAddress': (80, 8, 8, 0, 0), 'Application': (33, 2, 8, 0, 0),
    'SecondApplicationBlocks': (69, 1, 8, 0, 0), 'SceneKeySelector': (96, 8, 1, 7, 0),
    'IndicatorBlockAssignment': (96, 8, 3, 0, 0),
    'TimerHighByte': (136, 8, 8, 0, 0), 'TimerLowByte': (144, 8, 8, 0, 0),
    'TimerExpiryCommand': (72, 8, 4, 0, 0),
    'CorridorLinkOfficeBlock': (68, 1, 3, 0, 0), 'CorridorLinkBlock': (68, 1, 3, 3, 0),
    'CorridorLinkActive': (68, 1, 1, 7, 0), 'BroadcastBlock': (70, 1, 3, 0, 0),
    'IndicatorControl': (70, 1, 2, 3, 0), 'BroadcastActive': (70, 1, 3, 5, 0),
    'PECTargetLux': (27, 1, 8, 0, 0), 'PECMarginLux': (28, 1, 8, 0, 0), 'LightLevel': (1, 10, 8, 0, 0),
    'PIREnablerGroup': (88, 1, 8, 0, 0), 'PECEnablerGroup': (89, 1, 8, 0, 0),
    'SingleJoinEnablerGroup': (90, 1, 8, 0, 0), 'DualJoinEnablerGroup': (91, 1, 8, 0, 0),
    'CorridorLinkEnablerGroup': (92, 1, 8, 0, 0), 'SingleJoinEnablerControlGroup': (93, 1, 8, 0, 0),
    'DualJoinEnablerControlGroup': (94, 1, 8, 0, 0), 'ControlAppGroupAddress': (95, 1, 8, 0, 0),
    'PECFunctionBlock': (96, 1, 3, 3, 0), 'PECFunctionActive': (96, 1, 1, 6, 0),
    'PECFunctionIRKey': (97, 1, 3, 3, 0), 'PECFunctionIRActive': (97, 1, 1, 6, 0),
    'PIRFunctionIRKey': (98, 1, 3, 3, 0), 'PIRFunctionIRActive': (98, 1, 1, 6, 0),
    'PECLevelStore': (99, 1, 1, 3, 0), 'PIRLevelStore': (99, 1, 1, 4, 0),
    'PECEnablerGroupLogic': (99, 1, 1, 5, 0), 'PIREnablerGroupLogic': (99, 1, 1, 6, 0),
    'PotentiometerAFunction': (101, 1, 2, 3, 0), 'PotentiometerBFunction': (101, 1, 2, 5, 0),
    'PotentiometerATimerBlock': (102, 1, 3, 3, 0), 'PotentiometerBTimerBlock': (103, 1, 3, 3, 0),
    'PotentiometerBBankSwitchEnable': (103, 1, 1, 6, 0),
})
BITS = frozenset(('DisableIR', 'CorridorLinkActive', 'PECFunctionActive', 'PECFunctionIRActive',
                  'PIRFunctionIRActive', 'PECLevelStore', 'PIRLevelStore', 'PECEnablerGroupLogic',
                  'PIREnablerGroupLogic'))


def profile(unit_type, firmware, catalog_number):
    """Return (reason, spec_filename); reason is None for an admitted identity."""
    admitted = PROFILES.get(unit_type)
    if admitted is None:
        if unit_type == 'SENPILL':
            return 'SENPILL uses the Toolkit multisensor class; use cbus_toolkit.sensors', None
        return 'Only SENPIROA, SENPIRIA and SENPIRIB ST7 PIR sensors use this workflow', None
    version = _version(firmware)
    spec = next((name for low, high, name in admitted['bands']
                 if version is not None and _version(low) <= version <= _version(high)), None)
    if spec is None:
        return (f'{unit_type} firmware {firmware} has no admitted Toolkit ST7 PIR class and catalogue '
                'specification (SENPIRIB 2.3.10..2.3.99 is unregistered; SENPIRIB 2.4 uses SENPIRIC)'), None
    if catalog_number not in admitted['catalog_numbers']:
        return f'{unit_type} catalogue number must be one of {", ".join(admitted["catalog_numbers"])}', spec
    return None, spec


def check_profile(unit_type, firmware, catalog_number, *, subject='Unit identity'):
    reason, spec = profile(unit_type, firmware, catalog_number)
    if reason is not None:
        raise SensorError(f'{subject} must be an admitted ST7 PIR sensor: {reason}')
    return (unit_type, firmware, catalog_number), spec


def power_up_state(level, logic, store):
    """LoadPowerFail: 0 disabled, 1 enabled, 2 resume previous state."""
    if store:
        return 2
    return 0 if (level == 255) == bool(logic) else 1


@dataclass(frozen=True)
class PIRPlan:
    unit_type: str | None
    spec_filename: str
    keys: tuple
    expected: dict
    changes: dict
    dialog: dict
    identity: tuple | None = None

    def __post_init__(self):
        for name in ('expected', 'changes'):
            object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))
        object.__setattr__(self, 'dialog', MappingProxyType(dict(self.dialog)))

    def as_dict(self):
        unit_type, firmware, catalog_number = self.identity or (self.unit_type, None, None)
        return {'format': 'cbus-st7-pir-sensor-plan-v1', 'unit_type': unit_type, 'firmware': firmware,
                'catalog_number': catalog_number, 'spec_filename': self.spec_filename,
                'toolkit_class': PROFILES[unit_type]['toolkit_class'] if unit_type in PROFILES else None,
                'keys': list(self.keys), 'dialog': dict(self.dialog),
                'forced_by_toolkit_save': sorted(FORCED) + ['LightLevel', 'SceneKeySelector'],
                'expected': {k: list(v) for k, v in self.expected.items()},
                'changes': {k: list(v) for k, v in self.changes.items()},
                'saved': False, 'device_verified': False}


class PIRSensor:
    def __init__(self, spec):
        known = {name for admitted in PROFILES.values() for *_, name in admitted['bands']}
        if spec.unit_type not in PROFILES or spec.filename not in known:
            raise SensorError('Use a SENPIROA/SENPIRIA/SENPIRIB _ST7 or _ST7_2 specification')
        self.spec, self.codec = spec, MemoryCodec(spec)
        for name, expected in LAYOUTS.items():
            layout = self.codec.layout(name)
            actual = (layout.address, layout.array_size, layout.bit_size, layout.bit_address, layout.array_skip)
            if actual != expected or layout.parameter.type != ('bit' if name in BITS else 'int'):
                raise SensorError('Unsupported PIR sensor parameter layout: ' + name)

    def snapshot(self, current):
        result = {}
        for name in LAYOUTS:
            if name not in current:
                raise SensorError('Missing current PIR sensor parameter: ' + name)
            values = _numbers(current[name])
            if not self.spec.get(name).validate_value(list(values))['valid']:
                raise SensorError('Invalid current PIR sensor parameter: ' + name)
            result[name] = values
        return result

    def plan(self, current, *, keys=None, restore_functions=None, darkness_same_as_light=None,
             enable_group=None, enabled_when=None, power_up=None, allow_shared_block=False, identity=None):
        """Plan PIR dialog edits followed by the complete Toolkit PIR save.

        ``keys`` maps key 1..4 (Motion in Light, Motion in Darkness, Sunset,
        Any Motion) to optional ``block`` (1..4), ``group`` (0..254, 255 for
        none), ``timer_seconds`` and ``expiry``. With no options the plan is
        the Toolkit's OK/save of an unchanged dialog.
        """
        spec_filename = self.spec.filename
        if identity is not None:
            if not isinstance(identity, tuple) or len(identity) != 3:
                raise SensorError('Identity must be (unit_type, firmware, catalog_number)')
            identity, spec_filename = check_profile(*identity)
            if identity[0] != self.spec.unit_type or spec_filename != self.spec.filename:
                raise SensorError(f'{identity[0]} {identity[1]} uses {spec_filename}, not {self.spec.filename}')
        if not isinstance(allow_shared_block, bool):
            raise SensorError('allow_shared_block must be boolean')
        for label, value in (('restore_functions', restore_functions), ('darkness_same_as_light', darkness_same_as_light)):
            if value is not None and not isinstance(value, bool):
                raise SensorError(label + ' must be boolean')
        keys = {} if keys is None else keys
        if not isinstance(keys, dict) or any(isinstance(k, bool) or k not in KEY_EVENTS for k in keys):
            raise SensorError('PIR keys must be a mapping from key 1..4')
        original = self.snapshot(current)
        updates = {name: list(values) for name, values in original.items()}
        # Dialog state loaded by the Toolkit before any edit.
        linked = original['BlockAllocation'][0] == original['BlockAllocation'][1]
        state = power_up_state(original['LightLevel'][8], original['PIREnablerGroupLogic'][0], original['PIRLevelStore'][0])
        percent = margin_percent(original['PECTargetLux'][0], original['PECMarginLux'][0])
        if darkness_same_as_light is not None:
            linked = darkness_same_as_light
        if linked:
            updates['BlockAllocation'][1] = updates['BlockAllocation'][0]
        edited = set()
        for key, options in sorted(keys.items()):
            if not isinstance(options, dict) or set(options) - {'block', 'group', 'timer_seconds', 'expiry'}:
                raise SensorError('Key options are block, group, timer_seconds and expiry')
            if key == 2 and linked and 'block' in options:
                raise SensorError('Motion in Darkness follows Motion in Light while darkness_same_as_light is set')
            expiry = options.get('expiry', 'off')
            if expiry not in EXPIRY:
                raise SensorError('Unsupported timer expiry function')
            if 'timer_seconds' not in options and 'expiry' in options:
                raise SensorError('Expiry selection requires timer_seconds')
            block = options.get('block')
            if block is None:
                assigned = updates['BlockAllocation'][key - 1]
                if not assigned or assigned & (assigned - 1) or assigned >= 1 << KEYS:
                    raise SensorError(f'Specify block 1..{KEYS} for key {key}: its allocation is not one PIR block')
                block = assigned.bit_length()
            block = _integer(block, 'Block', 1, KEYS)
            mask, index = 1 << (block - 1), block - 1
            updates['BlockAllocation'][key - 1] = mask
            if linked and key == 1:
                updates['BlockAllocation'][1] = mask
            sharing = tuple(i + 1 for i, assigned in enumerate(updates['BlockAllocation'])
                            if i != key - 1 and assigned & mask and not (linked and {i + 1, key} == {1, 2}))
            if sharing and ('group' in options or 'timer_seconds' in options) and not allow_shared_block:
                raise SensorError(f'Block {block} is shared by keys {sharing}; allow the shared edit explicitly')
            if 'group' in options:
                updates['GroupAddress'][index] = _integer(options['group'], 'Group', 0, 255)
            if updates['GroupAddress'][index] != 255:
                app_index = int(bool(original['SecondApplicationBlocks'][0] & mask))
                if not 48 <= original['Application'][app_index] <= 95:
                    raise SensorError('A PIR key group requires a Lighting Type application in 48..95')
            if 'timer_seconds' in options:
                seconds = _integer(options['timer_seconds'], 'Timer seconds', 0, 65535)
                updates['TimerHighByte'][index], updates['TimerLowByte'][index] = divmod(seconds, 256)
                updates['TimerExpiryCommand'][index] = MICRO_FUNCTIONS[expiry]
            edited.add(key)
        if linked:
            updates['BlockAllocation'][1] = updates['BlockAllocation'][0]
        if updates['BlockAllocation'][1] != original['BlockAllocation'][1]:
            edited.add(2)  # The link changes InputKeys[1], which fires its template check.
        mismatched = sorted(key for key in edited
                            if tuple(original[name][key - 1] for name in STAGES) != EVENTS[KEY_EVENTS[key]])
        if mismatched and restore_functions is None:
            raise SensorError(f'Keys {mismatched} have functions other than their fixed PIR event; '
                              'choose restore_functions=True or False as the Toolkit prompt requires')
        if restore_functions:
            for key in mismatched:
                for name, code in zip(STAGES, EVENTS[KEY_EVENTS[key]]):
                    updates[name][key - 1] = code
        if enable_group is not None:
            updates['PIREnablerGroup'][0] = _integer(enable_group, 'Occupancy enable group', 0, 255)
            if enable_group != 255 and not 48 <= original['Application'][0] <= 95:
                raise SensorError('Occupancy enable group requires a primary Lighting Type application')
        if enabled_when is not None:
            if enabled_when not in ('on', 'off'):
                raise SensorError('enabled_when must be on or off')
            if updates['PIREnablerGroup'][0] == 255:
                raise SensorError('Enable polarity requires an assigned occupancy enable group')
            updates['PIREnablerGroupLogic'][0] = int(enabled_when == 'off')
        if power_up is not None:
            if power_up not in POWER_UP:
                raise SensorError('power_up must be disabled, enabled or resume')
            state = POWER_UP.index(power_up)
        self._toolkit_save(original, updates, state, percent)
        if updates['PECMarginLux'][0] > 255:
            raise SensorError(f'The Toolkit save turns the stored margin into {updates["PECMarginLux"][0]}, '
                              'outside the native margin byte')
        changes = {name: tuple(values) for name, values in updates.items() if tuple(values) != original[name]}
        self.codec.encode_many(changes)
        dialog = {'darkness_same_as_light': linked, 'power_up': POWER_UP[state], 'margin_percent': percent,
                  'indicator_disabled': original['IndicatorBlockAssignment'][0] == 7,
                  'restored_functions': mismatched if restore_functions else [],
                  'kept_custom_functions': mismatched if restore_functions is False else []}
        return PIRPlan(self.spec.unit_type, spec_filename, tuple(sorted(edited)), original, changes, dialog, identity)

    @staticmethod
    def _toolkit_save(original, updates, state, percent):
        # Multisensor BeforeSave: broadcast, margin and power fail round-trips.
        updates['BroadcastActive'][0] = 4 if 1 <= original['BroadcastActive'][0] <= 6 else 0
        updates['PECMarginLux'][0] = saved_margin(updates['PECTargetLux'][0], percent)
        logic = updates['PIREnablerGroupLogic'][0]
        if state == 2:
            updates['PIRLevelStore'][0] = 1
        else:
            updates['PIRLevelStore'][0] = 0
            updates['LightLevel'][8] = 255 if (state == 0) == bool(logic) else 0
        # PIR PrepareForcedParameters and the conditional indicator write.
        for name, value in FORCED.items():
            updates[name][0] = value
        for index in FORCED_LIGHT_LEVEL:
            updates['LightLevel'][index] = 0
        # The forced value is the one-element string "0"; native C-Gate
        # changes only element 0 of the eight-element array.
        updates['SceneKeySelector'][0] = 0
        if original['IndicatorBlockAssignment'][0] == 7:
            updates['IndicatorBlockAssignment'] = list(INDICATOR_DISABLED)

    def _verify_profile(self, session):
        identity, spec = check_profile(session.unit_type, session.firmware, session.catalog_number,
                                       subject='Native session')
        if spec != self.spec.filename:
            raise SensorError(f'Native session {identity[0]} {identity[1]} uses {spec}, not {self.spec.filename}')
        return identity

    def _verify_session(self, session):
        document = xml_text(session.info('*'))
        if '<!DOCTYPE' in document.upper() or '<!ENTITY' in document.upper():
            raise SensorError('Unsupported native schema declarations')
        try:
            root = ET.fromstring(document)
        except ET.ParseError as error:
            raise SensorError('Invalid native parameter schema') from error
        fields = {}
        for param in root.iter():
            if param.tag.rsplit('}', 1)[-1] == 'Param':
                row = {child.tag.rsplit('}', 1)[-1]: child.text or '' for child in param}
                if row.get('Name') in fields:
                    raise SensorError('Duplicate native parameter schema')
                fields[row.get('Name')] = row
        for name in LAYOUTS:
            native, local = fields.get(name, {}), self.spec.get(name).fields
            if native.get('Type', '').lower() != local.get('Type', '').lower():
                raise SensorError('Native parameter type mismatch: ' + name)
            for field, default in (('Address', None), ('ArraySize', '1'), ('BitSize', '1' if name in BITS else '8'),
                                   ('BitAddress', '0'), ('ArraySkip', '0')):
                if _numbers(native.get(field, default)) != _numbers(local.get(field, default)):
                    raise SensorError(f'Native parameter layout mismatch: {name}/{field}')

    def apply(self, session, plan):
        if not isinstance(plan, PIRPlan) or set(plan.expected) != set(LAYOUTS) or any(n not in LAYOUTS for n in plan.changes):
            raise SensorError('Plan contains fields outside the PIR sensor workflow')
        self.codec.encode_many(plan.changes)
        identity = self._verify_profile(session)
        if plan.identity is not None and plan.identity != identity:
            raise SensorError('Plan was created for another unit type, firmware or catalogue number')
        self._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise SensorError('PP parameters changed since the PIR sensor plan was created')
        attempted = []
        try:
            for name, values in plan.changes.items():
                attempted.append(name)
                session.set(name, ' '.join(map(str, values)))
            expected = dict(plan.expected)
            expected.update(plan.changes)
            if self.snapshot(session.values()) != expected:
                raise SensorError('Native PIR sensor readback differs from the plan')
        except (RuntimeError, OSError, ValueError) as error:
            # No recovery I/O after an uncertain write; the PP session stays unsaved.
            raise SensorApplyError(error, attempted) from error
        return {**replace(plan, identity=identity).as_dict(), 'verified': True}

    def configure(self, session, **options):
        identity = self._verify_profile(session)
        return self.apply(session, self.plan(session.values(), identity=identity, **options))


__all__ = ['FORCED', 'KEY_EVENTS', 'LAYOUTS', 'PIRPlan', 'PIRSensor', 'POWER_UP', 'PROFILES',
           'check_profile', 'margin_percent', 'power_up_state', 'profile', 'saved_margin']
