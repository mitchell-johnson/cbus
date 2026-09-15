"""Source-grounded Neo-core physical key presets for explicit tested profiles.

The shared macro factory uses the same nibble event codes as classic keys.
Neo-core devices have eight blocks, a secondary-application mask, and a scene
selector bit which Toolkit clears when writing an ordinary key function.
"""
from dataclasses import dataclass
from types import MappingProxyType
import xml.etree.ElementTree as ET

from .macros import MacroApplyError, MacroError, MICRO_FUNCTIONS, PRESETS, STAGES, _int, _numbers
from .memory import MemoryCodec
from .programming import xml_text


PROFILES = MappingProxyType({
    'KEYE.xml': ('KEYE1', 1, 'C-Bus 30M mech'),
    'KEYM4.xml': ('KEYM4', 4, 'Neo'),
    'KEYA3.xml': ('KEYA3', 3, 'Reflection'),
    'KEYB4.xml': ('KEYB4', 4, 'Saturn'),
})
# address, array length, bit width, starting bit, byte skip between entries
LAYOUTS = MappingProxyType({
    'JPCommand': (0x68, 8, 4, 4, 1), 'SRCommand': (0x68, 8, 4, 0, 1),
    'LPCommand': (0x69, 8, 4, 4, 1), 'LRCommand': (0x69, 8, 4, 0, 1),
    'BlockAllocation': (0x36, 8, 8, 0, 0), 'GroupAddress': (0x50, 9, 8, 0, 0),
    'Application': (0x21, 2, 8, 0, 0), 'SecondApplicationBlocks': (0x45, 1, 8, 0, 0),
    'TimerHighByte': (0x88, 8, 8, 0, 0), 'TimerLowByte': (0x90, 8, 8, 0, 0),
    'TimerExpiryCommand': (0x48, 8, 4, 0, 0),
    'LightLevelStore1': (0x78, 8, 8, 0, 0), 'LightLevelStore2': (0x80, 8, 8, 0, 0),
    'SceneKeySelector': (0x60, 8, 1, 7, 0), 'IndicatorBlockAssignment': (0x60, 8, 3, 0, 0),
})
EXPIRY = frozenset(('idle', 'off', 'down', 'ramp_off', 'recall1', 'recall2', 'ramp_recall1'))


@dataclass(frozen=True)
class ExtendedKeyPlan:
    unit_type: str
    spec_filename: str
    key: int
    preset: str
    block: int | None
    expected: dict
    changes: dict
    shared_keys: tuple = ()

    def __post_init__(self):
        for name in ('expected', 'changes'):
            object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))

    def as_dict(self):
        return {'format': 'cbus-neo-key-plan-v1', 'unit_type': self.unit_type,
                'spec_filename': self.spec_filename, 'key': self.key, 'preset': PRESETS[self.preset].as_dict(),
                'block': self.block, 'shared_keys': list(self.shared_keys),
                'expected': {k: list(v) for k, v in self.expected.items()},
                'changes': {k: list(v) for k, v in self.changes.items()}, 'saved': False}


class ExtendedKeys:
    def __init__(self, spec):
        self.spec = spec
        profile = PROFILES.get(spec.filename)
        if profile is None or profile[0] != spec.unit_type:
            raise MacroError('Select a supported explicit Neo-core profile: ' + ', '.join(PROFILES))
        self.unit_type, self.key_count, self.family = profile
        self.codec = MemoryCodec(spec)
        for name, expected in LAYOUTS.items():
            layout = self.codec.layout(name)
            shape = (layout.address, layout.array_size, layout.bit_size, layout.bit_address, layout.array_skip)
            if layout.parameter.type != 'int' or shape != expected:
                raise MacroError('Unsupported Neo-core parameter layout: ' + name)

    def _snapshot(self, values):
        result = {}
        for name in LAYOUTS:
            if name not in values:
                raise MacroError('Current PP values are missing ' + name)
            parsed = _numbers(values[name])
            valid = self.spec.get(name).validate_value(list(parsed))
            if not valid['valid']:
                raise MacroError(f'Invalid current {name}: ' + '; '.join(valid['errors']))
            result[name] = parsed
        return result

    def plan(self, current, *, key, preset, group=None, block=None, application=None,
             timer_seconds=None, expiry='off', recall1=None, recall2=None,
             indicator_block=None, allow_shared_block=False):
        key = _int(key, 'Key')
        if not 1 <= key <= self.key_count:
            raise MacroError(f'{self.unit_type} has {self.key_count} supported physical key(s)')
        if preset not in PRESETS:
            raise MacroError('Unknown standard wired preset')
        if application not in (None, 'primary', 'secondary'):
            raise MacroError('Application selection must be primary or secondary')
        if not isinstance(allow_shared_block, bool):
            raise MacroError('allow_shared_block must be boolean')
        original = self._snapshot(current)
        updates = {name: list(values) for name, values in original.items()}
        for name, code in zip(STAGES, PRESETS[preset].codes):
            updates[name][key - 1] = code
        # TCoreNeoInputCGateAgent.SetKeyValues ordinary-key branch explicitly
        # writes zero to SceneKeySelector before serializing all four stages.
        updates['SceneKeySelector'][key - 1] = 0
        selected, shared = None, ()
        needs_block = preset == 'timer' or any(value is not None for value in (group, block, application, timer_seconds, recall1, recall2))
        if needs_block:
            if block is None:
                mask = original['BlockAllocation'][key - 1]
                if not mask or mask & (mask - 1):
                    raise MacroError('Specify block 1..8 for a missing or multiple-block assignment')
                block = mask.bit_length()
            block = _int(block, 'Block')
            if not 1 <= block <= 8:
                raise MacroError('Neo-core blocks are numbered 1..8')
            selected, mask = block, 1 << (block - 1)
            shared = tuple(i + 1 for i, assigned in enumerate(original['BlockAllocation']) if i != key - 1 and assigned & mask)
            modifies_block = any(value is not None for value in (group, application, timer_seconds, recall1, recall2))
            if modifies_block and shared and not allow_shared_block:
                raise MacroError(f'Block {block} is also assigned to keys {shared}; select a separate block or explicitly allow the shared edit')
            updates['BlockAllocation'][key - 1] = mask
            if application is not None:
                updates['SecondApplicationBlocks'][0] = ((original['SecondApplicationBlocks'][0] | mask) if application == 'secondary' else (original['SecondApplicationBlocks'][0] & ~mask))
            if group is not None or application is not None:
                app_index = int(bool(updates['SecondApplicationBlocks'][0] & mask))
                if not 48 <= original['Application'][app_index] <= 95:
                    raise MacroError('Selected block application must be Lighting Type 48..95')
            if group is not None:
                group = _int(group, 'Group')
                if not 0 <= group <= 254:
                    raise MacroError('Group must be 0..254;255 is unassigned')
                updates['GroupAddress'][block - 1] = group
            if timer_seconds is not None:
                timer_seconds = _int(timer_seconds, 'Timer seconds')
                if not 0 <= timer_seconds <= 65535 or expiry not in EXPIRY:
                    raise MacroError('Use timer seconds 0..65535 and a supported expiry function')
                updates['TimerHighByte'][block - 1] = timer_seconds >> 8
                updates['TimerLowByte'][block - 1] = timer_seconds & 255
                updates['TimerExpiryCommand'][block - 1] = MICRO_FUNCTIONS[expiry]
            elif preset == 'timer' and original['TimerHighByte'][block - 1] == original['TimerLowByte'][block - 1] == 0:
                raise MacroError('Selected timer is disabled; supply timer_seconds')
            for name, value in (('LightLevelStore1', recall1), ('LightLevelStore2', recall2)):
                if value is not None:
                    value = _int(value, 'Recall level')
                    if not 0 <= value <= 255:
                        raise MacroError('Recall levels must be 0..255')
                    updates[name][block - 1] = value
        if indicator_block is not None:
            indicator_block = _int(indicator_block, 'Indicator block')
            if not 1 <= indicator_block <= 8:
                raise MacroError('Indicator block must be in 1..8')
            updates['IndicatorBlockAssignment'][key - 1] = indicator_block - 1
        changes = {name: tuple(values) for name, values in updates.items() if tuple(values) != original[name]}
        self.codec.encode_many(changes)
        return ExtendedKeyPlan(self.unit_type, self.spec.filename, key, preset, selected, original, changes, shared)

    def _verify_session(self, session):
        if session.unit_type != self.unit_type:
            raise MacroError('Native session unit type differs from the Neo-core plan')
        document = xml_text(session.info('*'))
        if '<!DOCTYPE' in document.upper() or '<!ENTITY' in document.upper():
            raise MacroError('Unsupported native schema declarations')
        try:
            root = ET.fromstring(document)
        except ET.ParseError as error:
            raise MacroError('Invalid native parameter schema') from error
        fields = {}
        for param in root.iter():
            if param.tag.rsplit('}', 1)[-1] == 'Param':
                row = {child.tag.rsplit('}', 1)[-1]: child.text or '' for child in param}
                if row.get('Name') in fields:
                    raise MacroError('Duplicate native parameter schema')
                fields[row.get('Name')] = row
        for name in LAYOUTS:
            native = fields.get(name, {})
            local = self.spec.get(name).fields
            if native.get('Type', '').lower() != 'int':
                raise MacroError('Native parameter type mismatch: ' + name)
            for field, default in (('Address', None), ('ArraySize', '1'), ('BitSize', '8'), ('BitAddress', '0'), ('ArraySkip', '0')):
                if _numbers(native.get(field, default)) != _numbers(local.get(field, default)):
                    raise MacroError(f'Native parameter layout mismatch: {name}/{field}')

    def apply(self, session, plan):
        if not isinstance(plan, ExtendedKeyPlan) or (plan.unit_type, plan.spec_filename) != (self.unit_type, self.spec.filename):
            raise MacroError('Plan profile differs from the programmer')
        if set(plan.expected) != set(LAYOUTS) or any(name not in LAYOUTS for name in plan.changes):
            raise MacroError('Plan contains fields outside the supported workflow')
        self.codec.encode_many(plan.changes)
        self._verify_session(session)
        if self._snapshot(session.values()) != dict(plan.expected):
            raise MacroError('PP parameters changed since this plan was created')
        attempted = []
        try:
            for name, values in plan.changes.items():
                attempted.append(name)
                session.set(name, ' '.join(str(value) for value in values))
            expected = dict(plan.expected)
            expected.update(plan.changes)
            if self._snapshot(session.values()) != expected:
                raise MacroError('Native key readback differs from the plan')
        except Exception as error:
            rollback_errors = []
            for name in reversed(attempted):
                try:
                    session.set(name, ' '.join(str(value) for value in plan.expected[name]))
                except Exception as rollback:
                    rollback_errors.append(str(rollback))
            try:
                if self._snapshot(session.values()) != dict(plan.expected):
                    rollback_errors.append('Original parameters were not restored')
            except Exception as rollback:
                rollback_errors.append(str(rollback))
            raise MacroApplyError(error, rollback_errors) from error
        return {**plan.as_dict(), 'verified': True, 'device_verified': False}

    def configure(self, session, **options):
        return self.apply(session, self.plan(session.values(), **options))
