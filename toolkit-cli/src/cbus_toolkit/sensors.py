"""Toolkit ST7 multisensor occupancy setup for one verified device profile.

This edits an existing PP session. It does not save, transfer, calibrate a
physical sensor, or simulate optical/PIR behavior. See docs/sensors.md.
"""
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
import xml.etree.ElementTree as ET

from .macros import MICRO_FUNCTIONS, STAGES, _numbers
from .memory import MemoryCodec
from .programming import xml_text


class SensorError(ValueError):
    pass


class SensorApplyError(RuntimeError):
    def __init__(self, cause, attempted):
        self.cause, self.attempted = cause, tuple(attempted)
        self.details = {'attempted_parameters': list(self.attempted), 'saved': False, 'device_verified': False}
        super().__init__('Sensor setup stopped; PP changes may be partial and were not saved: ' + str(cause))


# JP, SR, LP, LR: literal Toolkit Help 10114/10115/17328/10116 event tables.
EVENTS = MappingProxyType({'day': (7, 0, 0, 0), 'night': (13, 7, 7, 0),
                           'any': (13, 7, 0, 7), 'sunset': (13, 15, 7, 15),
                           'disabled': (0, 0, 0, 0)})
EXPIRY = frozenset(('idle', 'off', 'down', 'ramp_off', 'recall1', 'recall2', 'ramp_recall1'))
PROFILE = ('SENPILL', '2.3.00', '5753PEIRL', 'SENPILL_ST7.xml')
# Address, count, bits, bit offset, byte skip. No distributed vendor catalog.
LAYOUTS = MappingProxyType({
    'JPCommand': (104, 8, 4, 4, 1), 'SRCommand': (104, 8, 4, 0, 1),
    'LPCommand': (105, 8, 4, 4, 1), 'LRCommand': (105, 8, 4, 0, 1),
    'PIRLightMovement': (50, 1, 8, 0, 0), 'PIRDarkMovement': (51, 1, 8, 0, 0),
    'PIRDark': (52, 1, 8, 0, 0), 'BlockAllocation': (54, 8, 8, 0, 0),
    'GroupAddress': (80, 8, 8, 0, 0), 'Application': (33, 2, 8, 0, 0),
    'SecondApplicationBlocks': (69, 1, 8, 0, 0), 'SceneKeySelector': (96, 8, 1, 7, 0),
    'TimerHighByte': (136, 8, 8, 0, 0), 'TimerLowByte': (144, 8, 8, 0, 0),
    'TimerExpiryCommand': (72, 8, 4, 0, 0), 'BlockBankSwitchActive': (72, 8, 1, 5, 0),
    'PECTargetLux': (27, 1, 8, 0, 0), 'PECMarginLux': (28, 1, 8, 0, 0),
    'PIREnablerGroup': (88, 1, 8, 0, 0), 'PIREnablerGroupLogic': (99, 1, 1, 6, 0),
    'SingleJoinEnablerGroup': (90, 1, 8, 0, 0), 'DualJoinEnablerGroup': (91, 1, 8, 0, 0),
    'PECFunctionActive': (96, 1, 1, 6, 0), 'PECFunctionBlock': (96, 1, 3, 3, 0),
    'BroadcastActive': (70, 1, 3, 5, 0), 'BroadcastBlock': (70, 1, 3, 0, 0),
    'PotentiometerAFunction': (101, 1, 2, 3, 0), 'PotentiometerBFunction': (101, 1, 2, 5, 0),
    'PotentiometerATimerBlock': (102, 1, 3, 3, 0), 'PotentiometerBTimerBlock': (103, 1, 3, 3, 0),
})
_BITS = frozenset(('PIREnablerGroupLogic', 'PECFunctionActive'))


def _integer(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise SensorError(f'{label} must be an integer in {minimum}..{maximum}')
    return value


@dataclass(frozen=True)
class SensorPlan:
    key: int | None
    event: str | None
    block: int | None
    expected: dict
    changes: dict
    shared_keys: tuple = ()

    def __post_init__(self):
        for name in ('expected', 'changes'):
            object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))

    def as_dict(self):
        return {'format': 'cbus-st7-sensor-plan-v1', 'unit_type': PROFILE[0], 'firmware': PROFILE[1],
                'catalog_number': PROFILE[2], 'spec_filename': PROFILE[3], 'key': self.key,
                'event': self.event, 'block': self.block, 'shared_keys': list(self.shared_keys),
                'expected': {k: list(v) for k, v in self.expected.items()},
                'changes': {k: list(v) for k, v in self.changes.items()}, 'saved': False,
                'device_verified': False}


class Multisensor:
    def __init__(self, spec):
        if (spec.unit_type, spec.filename) != (PROFILE[0], PROFILE[3]):
            raise SensorError('Use SENPILL_ST7.xml for SENPILL 2.3.00 / 5753PEIRL')
        self.spec, self.codec = spec, MemoryCodec(spec)
        for name, expected in LAYOUTS.items():
            layout = self.codec.layout(name)
            actual = (layout.address, layout.array_size, layout.bit_size, layout.bit_address, layout.array_skip)
            if actual != expected or layout.parameter.type != ('bit' if name in _BITS else 'int'):
                raise SensorError('Unsupported sensor parameter layout: ' + name)

    def snapshot(self, current):
        result = {}
        for name in LAYOUTS:
            if name not in current:
                raise SensorError('Missing current sensor parameter: ' + name)
            values = _numbers(current[name])
            validation = self.spec.get(name).validate_value(list(values))
            if not validation['valid']:
                raise SensorError('Invalid current sensor parameter: ' + name)
            result[name] = values
        return result

    def plan(self, current, *, key=None, event=None, block=None, group=None,
             timer_seconds=None, expiry='off', target_lux=None, margin_percent=None,
             enable_group=None, enabled_when=None, allow_shared_block=False,
             disable_potentiometer_override=False):
        """Plan an exclusive sensor event per key plus optional global settings.

        Day/night share a timer only when their key block masks select the same
        block. Target lux uses exact 10-lux steps; percentage is converted to a
        native margin byte using Toolkit's round-to-even arithmetic.
        """
        for value in (allow_shared_block, disable_potentiometer_override):
            if not isinstance(value, bool):
                raise SensorError('Shared-block and potentiometer options must be boolean')
        if (key is None) != (event is None):
            raise SensorError('Supply both key and event, or neither for global settings')
        if event is not None and event not in EVENTS:
            raise SensorError('Event must be day, night, any, sunset or disabled')
        if expiry not in EXPIRY:
            raise SensorError('Unsupported timer expiry function')
        if timer_seconds is None and expiry != 'off':
            raise SensorError('Expiry selection requires timer_seconds')
        if key is None and any(v is not None for v in (block, group, timer_seconds)):
            raise SensorError('Block, group and timer settings require a key/event')
        original = self.snapshot(current)
        updates = {name: list(values) for name, values in original.items()}
        selected, shared = None, ()
        if key is not None:
            key = _integer(key, 'Virtual key', 1, 8)
            if original['SingleJoinEnablerGroup'] != (255,) or original['DualJoinEnablerGroup'] != (255,):
                raise SensorError('Join-mode occupancy setup is outside this verified workflow')
            bit = 1 << (key - 1)
            for name, enabled in (('PIRLightMovement', event in ('day', 'any')),
                                  ('PIRDarkMovement', event in ('night', 'any')),
                                  ('PIRDark', event == 'sunset')):
                updates[name][0] = original[name][0] | bit if enabled else original[name][0] & ~bit
            for name, code in zip(STAGES, EVENTS[event]):
                updates[name][key - 1] = code
            updates['SceneKeySelector'][key - 1] = 0
            if event != 'disabled' or any(v is not None for v in (block, group, timer_seconds)):
                if block is None:
                    assigned = original['BlockAllocation'][key - 1]
                    if not assigned or assigned & (assigned - 1):
                        raise SensorError('Specify block 1..8 for an unassigned or multiple-block key')
                    block = assigned.bit_length()
                selected = _integer(block, 'Block', 1, 8)
                mask, index = 1 << (block - 1), block - 1
                shared = tuple(i + 1 for i, assigned in enumerate(original['BlockAllocation'])
                               if i != key - 1 and assigned & mask)
                if shared and any(v is not None for v in (group, timer_seconds)) and not allow_shared_block:
                    raise SensorError(f'Block {block} is shared by keys {shared}; allow the shared edit explicitly')
                app_index = int(bool(original['SecondApplicationBlocks'][0] & mask))
                if not 48 <= original['Application'][app_index] <= 95:
                    raise SensorError('Sensor event requires a Lighting Type application in 48..95')
                if original['BroadcastActive'][0] not in (0, 7) and original['BroadcastBlock'][0] == index:
                    raise SensorError('Selected block is used by light-level broadcasting')
                if original['PECFunctionActive'][0] and original['PECFunctionBlock'][0] == index:
                    raise SensorError('Selected block is used by light-level maintenance')
                updates['BlockAllocation'][key - 1] = mask
                if event != 'disabled':
                    updates['BlockBankSwitchActive'][index] = 0
                if group is not None:
                    updates['GroupAddress'][index] = _integer(group, 'Group', 0, 254)
                if event != 'disabled' and updates['GroupAddress'][index] == 255:
                    raise SensorError('Assign a Lighting group before enabling the sensor event')
                if timer_seconds is not None:
                    seconds = _integer(timer_seconds, 'Timer seconds', 0, 65535)
                    updates['TimerHighByte'][index], updates['TimerLowByte'][index] = divmod(seconds, 256)
                    updates['TimerExpiryCommand'][index] = MICRO_FUNCTIONS[expiry]
                for pot in ('A', 'B'):
                    if timer_seconds is not None and original[f'Potentiometer{pot}Function'][0] == 2 and original[f'Potentiometer{pot}TimerBlock'][0] == index:
                        if not disable_potentiometer_override:
                            raise SensorError('Timer is controlled by a potentiometer; explicitly disable its override')
                        updates[f'Potentiometer{pot}Function'][0] = 0
        if target_lux is not None:
            target_lux = _integer(target_lux, 'Target lux', 0, 2550)
            if target_lux % 10:
                raise SensorError('Target lux must use exact 10-lux steps')
            if margin_percent is None:
                raise SensorError('Supply margin_percent with target_lux to define its hysteresis')
            updates['PECTargetLux'][0] = target_lux // 10
        if margin_percent is not None:
            margin_percent = _integer(margin_percent, 'Margin percent', 0, 100)
            updates['PECMarginLux'][0] = round(Fraction(updates['PECTargetLux'][0] * margin_percent, 100))
        if target_lux is not None or margin_percent is not None:
            for pot in ('A', 'B'):
                if original[f'Potentiometer{pot}Function'][0] == 1:
                    if not disable_potentiometer_override:
                        raise SensorError('Light threshold is controlled by a potentiometer; explicitly disable its override')
                    updates[f'Potentiometer{pot}Function'][0] = 0
        if enable_group is not None:
            updates['PIREnablerGroup'][0] = _integer(enable_group, 'Occupancy enable group', 0, 255)
            if enable_group != 255 and not 48 <= original['Application'][0] <= 95:
                raise SensorError('Occupancy enable group requires a primary Lighting Type application')
        if enabled_when is not None:
            if enabled_when not in ('on', 'off'):
                raise SensorError('enabled_when must be on or off')
            if updates['PIREnablerGroup'][0] == 255:
                raise SensorError('Enable polarity requires an assigned occupancy enable group')
            if not 48 <= original['Application'][0] <= 95:
                raise SensorError('Occupancy enable group requires a primary Lighting Type application')
            updates['PIREnablerGroupLogic'][0] = int(enabled_when == 'off')
        changes = {name: tuple(values) for name, values in updates.items() if tuple(values) != original[name]}
        self.codec.encode_many(changes)
        return SensorPlan(key, event, selected, original, changes, shared)

    def _verify_profile(self, session):
        if (session.unit_type, session.firmware, session.catalog_number) != PROFILE[:3]:
            raise SensorError('Native session must be SENPILL 2.3.00 / 5753PEIRL')

    def _verify_session(self, session):
        self._verify_profile(session)
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
            for field, default in (('Address', None), ('ArraySize', '1'), ('BitSize', '1' if name in _BITS else '8'), ('BitAddress', '0'), ('ArraySkip', '0')):
                if _numbers(native.get(field, default)) != _numbers(local.get(field, default)):
                    raise SensorError(f'Native parameter layout mismatch: {name}/{field}')

    def apply(self, session, plan):
        if not isinstance(plan, SensorPlan) or set(plan.expected) != set(LAYOUTS) or any(name not in LAYOUTS for name in plan.changes):
            raise SensorError('Plan contains fields outside the sensor workflow')
        self.codec.encode_many(plan.changes)
        self._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise SensorError('PP parameters changed since the sensor plan was created')
        attempted = []
        try:
            for name, values in plan.changes.items():
                attempted.append(name)
                session.set(name, ' '.join(map(str, values)))
            expected = dict(plan.expected)
            expected.update(plan.changes)
            if self.snapshot(session.values()) != expected:
                raise SensorError('Native sensor readback differs from the plan')
        except (RuntimeError, OSError, ValueError) as error:
            # Never issue recovery I/O after an uncertain transport or partial
            # PP error. The caller can inspect/reload the unsaved PP session.
            raise SensorApplyError(error, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, **options):
        self._verify_profile(session)
        return self.apply(session, self.plan(session.values(), **options))
