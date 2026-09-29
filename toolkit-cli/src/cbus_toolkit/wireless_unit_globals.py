"""Wireless Neo retrofit (WRM) unit globals: learn flags, house code and key masks.

This edits an existing native PP session for the admitted WRM input/output
units at firmware 2.0.0..2.4.99 (``<type>_2.xml``). The Learn Mode group of
Toolkit 1.18 ``TfrmWirelessUnitGlobalLearn`` is reproduced exactly. The
house code and the key-mask words are not editable Toolkit controls: the
Wireless Networking box shows the house code read-only and the agent's
``SaveKeyMask`` rewrites the masks on every save. They are offered as
explicit spec-level edits and are reported as such. No radio learn, join or
house-code transfer is performed. See docs/wireless.md.
"""
from dataclasses import dataclass, replace
import re
from types import MappingProxyType

from .macros import _numbers
from .memory import MemoryCodec
from .unitspec import version_matches
from .wireless_gateway import verify_native_schema


class WirelessGlobalsError(ValueError):
    pass


class WirelessGlobalsApplyError(RuntimeError):
    def __init__(self, cause, attempted):
        self.cause, self.attempted = cause, tuple(attempted)
        self.details = {'attempted_parameters': list(self.attempted), 'saved': False, 'device_verified': False}
        super().__init__('Wireless unit globals stopped; PP changes may be partial and were not saved: ' + str(cause))


PLAN_FORMAT = 'cbus-wireless-unit-globals-plan-v1'
VIEW_FORMAT = 'cbus-wireless-unit-globals-v1'
# Toolkit registers TWRM<type> (TCBusWirelessInputUnit) for firmware 2.0.0..9;
# the C-Gate catalogue selects <type>_2.xml for 2.0.0..2.4.99.
FIRMWARE_RANGE = ('2.0.0', '2.4.99')
UNIT_TYPES = ('WRM2D1', 'WRM2R1', 'WRM4D1', 'WRM4D2', 'WRM4R1', 'WRM4R2', 'WRM8D1', 'WRM8D2', 'WRM8R1', 'WRM8R2')
REFUSED = MappingProxyType({
    **{t: f'{t} is a TnmWRDX EZ unit with a different Toolkit class and specification'
       for t in ('WRM1R1EZ', 'WRM2D1EZ', 'WRM2R2EZ', 'WRM4D2EZ')},
})
LEARN_MODES = ('off', 'current', 'any')
# Address, count, bit size, bit offset, array skip, type.
LAYOUT = MappingProxyType({
    'HouseCode': (0x16, 4, 8, 0, 0, 'int'),
    'LearnAllowed': (0x2F, 1, 1, 0, 0, 'bit'),
    'LearnMasterMode': (0x2F, 1, 1, 1, 0, 'bit'),
    'LearnNetworkAllowed': (0x2F, 1, 1, 2, 0, 'bit'),
    'LearnedFlag': (0x2F, 1, 1, 7, 0, 'bit'),
    'KeyMaskAllowed': (0x44, 1, 8, 0, 0, 'int'),
    'KeyMaskSave': (0x45, 1, 8, 0, 0, 'int'),
    'KeyCurrentMask': (0x46, 1, 16, 0, 0, 'int'),
    **{f'KeyEnableMask{n}': (0x46 + 2 * n, 1, 16, 0, 0, 'int') for n in range(1, 5)},
})
FIELDS = tuple(LAYOUT)
TOOLKIT_CONTROLS = ('LearnAllowed', 'LearnMasterMode', 'LearnNetworkAllowed', 'LearnedFlag')
# Edits outside a Toolkit dialog control; a Toolkit save rewrites the masks.
BEYOND_DIALOG = ('HouseCode', 'KeyMaskAllowed', 'KeyMaskSave', 'KeyEnableMask1', 'KeyEnableMask2',
                 'KeyEnableMask3', 'KeyEnableMask4')


def _version(value):
    return value if isinstance(value, str) and re.fullmatch(r'[0-9]{1,4}(\.[0-9]{1,4}){1,3}', value) else None


def spec_filename(unit_type):
    return f'{unit_type}_2.xml'


def profile_refusal(unit_type, firmware):
    if unit_type not in UNIT_TYPES:
        return REFUSED.get(unit_type, 'Only WRM2/4/8 D/R Neo retrofit wireless units use this workflow')
    version = _version(firmware)
    if version is None or not version_matches(version, *FIRMWARE_RANGE):
        return (f'{unit_type} firmware outside {FIRMWARE_RANGE[0]}..{FIRMWARE_RANGE[1]} uses another Toolkit '
                'class or specification')
    return None


def check_profile(unit_type, firmware, catalog_number=None, *, subject='Unit identity'):
    reason = profile_refusal(unit_type, firmware)
    if reason is not None:
        raise WirelessGlobalsError(f'{subject} must be an admitted WRM unit at firmware {FIRMWARE_RANGE[0]}..'
                                   f'{FIRMWARE_RANGE[1]}: {reason}')
    return (unit_type, firmware, catalog_number)


def house_code_text(values):
    """FourByteArrayToHexStr: Format('%2.2x%2.2x%2.2x%2.2x', [b3, b2, b1, b0])."""
    return ''.join(f'{int(v):02x}' for v in reversed(tuple(values)))


def house_code_bytes(text):
    """HexStrToFourByteArray for an exact 8-digit Toolkit display string."""
    if not isinstance(text, str) or not re.fullmatch(r'[0-9A-Fa-f]{8}', text):
        raise WirelessGlobalsError('House code must be exactly eight hexadecimal digits')
    return tuple(int(text[i:i + 2], 16) for i in (6, 4, 2, 0))


def _flag(value, label):
    if not isinstance(value, bool):
        raise WirelessGlobalsError(f'{label} must be boolean')
    return value


def _word(value, label, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise WirelessGlobalsError(f'{label} must be an integer in 0..{maximum}')
    return value


@dataclass(frozen=True)
class WirelessGlobalsPlan:
    unit_type: str
    expected: dict
    changes: dict
    beyond_dialog: tuple = ()
    identity: tuple | None = None

    def __post_init__(self):
        for name in ('expected', 'changes'):
            object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))

    def as_dict(self):
        firmware, catalog_number = self.identity[1:] if self.identity else (None, None)
        return {'format': PLAN_FORMAT, 'unit_type': self.unit_type, 'firmware': firmware,
                'catalog_number': catalog_number, 'firmware_admitted': list(FIRMWARE_RANGE),
                'spec_filename': spec_filename(self.unit_type), 'beyond_dialog': list(self.beyond_dialog),
                'expected': {k: list(v) for k, v in self.expected.items()},
                'changes': {k: list(v) for k, v in self.changes.items()},
                'saved': False, 'device_verified': False}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get('format') != PLAN_FORMAT:
            raise WirelessGlobalsError('Expected a ' + PLAN_FORMAT + ' document')
        unit_type = data.get('unit_type')
        if unit_type not in UNIT_TYPES:
            raise WirelessGlobalsError('Plan unit type is not admitted')
        try:
            expected = {str(k): tuple(v) for k, v in data['expected'].items()}
            changes = {str(k): tuple(v) for k, v in data['changes'].items()}
        except (KeyError, AttributeError, TypeError) as error:
            raise WirelessGlobalsError('Plan requires expected and changes mappings') from error
        firmware = data.get('firmware')
        identity = None if firmware is None else check_profile(unit_type, firmware, data.get('catalog_number'))
        return cls(unit_type, expected, changes, tuple(data.get('beyond_dialog') or ()), identity)


class WirelessGlobalsEditor:
    def __init__(self, spec, unit_type=None):
        unit_type = spec.unit_type if unit_type is None else unit_type
        if unit_type not in UNIT_TYPES:
            raise WirelessGlobalsError(REFUSED.get(unit_type, 'Only admitted WRM wireless units use this workflow'))
        if spec.filename != spec_filename(unit_type):
            raise WirelessGlobalsError(f'Use {spec_filename(unit_type)} for {unit_type}')
        self.unit_type, self.spec, self.codec = unit_type, spec, MemoryCodec(spec)
        for name, expected in LAYOUT.items():
            try:
                layout = self.codec.layout(name)
            except Exception as error:  # noqa: BLE001 - any spec defect is a refusal
                raise WirelessGlobalsError('Unsupported wireless unit parameter layout: ' + name) from error
            actual = (layout.address, layout.array_size, layout.bit_size, layout.bit_address,
                      layout.array_skip, layout.parameter.type)
            if actual != expected:
                raise WirelessGlobalsError('Unsupported wireless unit parameter layout: ' + name)

    def snapshot(self, current):
        result = {}
        for name in FIELDS:
            if name not in current:
                raise WirelessGlobalsError('Missing current wireless unit parameter: ' + name)
            try:
                values = _numbers(current[name])
            except ValueError as error:
                raise WirelessGlobalsError('Invalid current wireless unit parameter: ' + name) from error
            if not self.spec.get(name).validate_value(list(values))['valid']:
                raise WirelessGlobalsError('Invalid current wireless unit parameter: ' + name)
            result[name] = values
        return result

    def show(self, current):
        v = {name: values if len(values) > 1 else values[0] for name, values in self.snapshot(current).items()}
        allowed, master = bool(v['LearnAllowed']), bool(v['LearnMasterMode'])
        masks = [v[f'KeyEnableMask{n}'] for n in range(1, 5)]
        return {'format': VIEW_FORMAT, 'unit_type': self.unit_type, 'spec_filename': spec_filename(self.unit_type),
                'learn': {'mode': ('any' if master else 'current') if allowed else 'off',
                          'allow_learn_mode': allowed, 'any_application': master,
                          'application_choice_enabled': allowed,
                          'network_learn': bool(v['LearnNetworkAllowed']),
                          'learned': bool(v['LearnedFlag']),
                          'label': 'Unit Has Learned: ' + ('Yes' if v['LearnedFlag'] else 'No'),
                          'reset_enabled': bool(v['LearnedFlag'])},
                'house_code': {'text': house_code_text(v['HouseCode']), 'bytes': list(v['HouseCode']),
                               'toolkit_control': 'read-only'},
                'key_masks': {'allowed': v['KeyMaskAllowed'], 'save': v['KeyMaskSave'],
                              'current': v['KeyCurrentMask'], 'enable': masks, 'toolkit_control': False,
                              # SaveKeyMask writes Allowed/Save 0 and every enable mask 0xFFFF.
                              'toolkit_save_rewrites': bool(v['KeyMaskAllowed'] or v['KeyMaskSave']
                                                            or any(m != 0xFFFF for m in masks))}}

    def plan(self, current, *, learn_mode=None, network_learn=None, reset_learned=False, house_code=None,
             key_enable_masks=None, key_mask_allowed=None, key_mask_save=None, identity=None):
        if identity is not None:
            if not isinstance(identity, tuple) or len(identity) != 3:
                raise WirelessGlobalsError('Identity must be (unit_type, firmware, catalog_number)')
            identity = check_profile(*identity)
            if identity[0] != self.unit_type:
                raise WirelessGlobalsError('Identity unit type differs from the selected profile')
        original = self.snapshot(current)
        updates = {name: list(values) for name, values in original.items()}
        if learn_mode is not None:
            if learn_mode not in LEARN_MODES:
                raise WirelessGlobalsError('Learn mode must be ' + ', '.join(LEARN_MODES))
            # chkAllowLearnModeClick: unchecked clears both bits; checked sets
            # LearnAllowed and copies rdoAnyApplication to LearnMasterMode.
            updates['LearnAllowed'][0] = int(learn_mode != 'off')
            updates['LearnMasterMode'][0] = int(learn_mode == 'any')
        if network_learn is not None:
            updates['LearnNetworkAllowed'][0] = int(_flag(network_learn, 'Network learn'))
        if _flag(reset_learned, 'Reset learned'):
            if not updates['LearnedFlag'][0]:
                # HandleLearnedFlagValueChange enables Reset only while LearnedFlag is set.
                raise WirelessGlobalsError('Toolkit disables Reset until the unit has learned')
            updates['LearnedFlag'][0] = 0
        if house_code is not None:
            updates['HouseCode'] = list(house_code_bytes(house_code))
        for n, value in dict(key_enable_masks or {}).items():
            if isinstance(n, bool) or n not in (1, 2, 3, 4):
                raise WirelessGlobalsError('Key enable mask index must be 1..4')
            updates[f'KeyEnableMask{n}'][0] = _word(value, f'Key enable mask {n}', 0xFFFF)
        if key_mask_allowed is not None:
            updates['KeyMaskAllowed'][0] = _word(key_mask_allowed, 'Key mask allowed', 0xFF)
        if key_mask_save is not None:
            updates['KeyMaskSave'][0] = _word(key_mask_save, 'Key mask save', 0xFF)
        changes = {name: tuple(values) for name, values in updates.items() if tuple(values) != original[name]}
        self.codec.encode_many(changes)
        beyond = tuple(name for name in BEYOND_DIALOG if name in changes)
        return WirelessGlobalsPlan(self.unit_type, original, changes, beyond, identity)

    def _verify_profile(self, session):
        identity = check_profile(session.unit_type, session.firmware, getattr(session, 'catalog_number', None),
                                 subject='Native session')
        if identity[0] != self.unit_type:
            raise WirelessGlobalsError('Native session unit type differs from the selected profile')
        return identity

    def _verify_session(self, session):
        verify_native_schema(session, self.spec, FIELDS, WirelessGlobalsError)

    def apply(self, session, plan):
        if (not isinstance(plan, WirelessGlobalsPlan) or plan.unit_type != self.unit_type
                or set(plan.expected) != set(FIELDS) or any(name not in FIELDS for name in plan.changes)):
            raise WirelessGlobalsError('Plan contains fields or a unit type outside this wireless workflow')
        self.codec.encode_many(plan.changes)
        identity = self._verify_profile(session)
        if plan.identity is not None and plan.identity[:2] != identity[:2]:
            raise WirelessGlobalsError('Plan was created for another unit type or firmware')
        self._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise WirelessGlobalsError('PP parameters changed since the wireless unit plan was created')
        attempted = []
        try:
            for name in FIELDS:
                if name in plan.changes:
                    attempted.append(name)
                    session.set(name, ' '.join(map(str, plan.changes[name])))
            expected = dict(plan.expected)
            expected.update(plan.changes)
            if self.snapshot(session.values()) != expected:
                raise WirelessGlobalsError('Native wireless unit readback differs from the plan')
        except (RuntimeError, OSError, ValueError) as error:
            raise WirelessGlobalsApplyError(error, attempted) from error
        return {**replace(plan, identity=identity).as_dict(), 'verified': True}

    def configure(self, session, **options):
        identity = self._verify_profile(session)
        return self.apply(session, self.plan(session.values(), identity=identity, **options))
