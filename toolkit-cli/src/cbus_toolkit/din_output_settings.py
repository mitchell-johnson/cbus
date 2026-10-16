"""Toolkit DIN relay/dimmer Logic, Turn On, Recovery and Restrike settings.

This edits an existing native PP session for the admitted DIN output profiles
(firmware 2.7.00). It reproduces the Toolkit 1.18 ``TfrmCBusDimmer`` control
bindings and the ``TBasicDinRailOutputCGateAgent`` save rules that apply to
those controls. It does not save, transfer, or verify physical outputs.
Programmable logic-engine code (PICED) is outside this editor. See
docs/din-output-settings.md.
"""
from dataclasses import dataclass, replace
from fractions import Fraction
import re
from types import MappingProxyType
import xml.etree.ElementTree as ET

from .macros import _numbers
from .memory import MemoryCodec
from .programming import xml_text


class DinSettingsError(ValueError):
    pass


class DinSettingsApplyError(RuntimeError):
    def __init__(self, cause, attempted):
        self.cause, self.attempted = cause, tuple(attempted)
        self.details = {'attempted_parameters': list(self.attempted), 'saved': False, 'device_verified': False}
        super().__init__('DIN output setup stopped; PP changes may be partial and were not saved: ' + str(cause))


FIRMWARE = '2.7.00'
# Logic-engine code editing (PICED) is external software, not the DIN Logic tab.
LOGIC_ENGINE_BOUNDARY = 'external'
PLAN_FORMAT = 'cbus-din-output-settings-plan-v1'
TOOLKIT_SAVE_PLAN_FORMAT = 'cbus-din-output-settings-plan-v2'


@dataclass(frozen=True)
class Profile:
    unit_type: str
    spec_filename: str
    channels: int
    relay: bool
    interlock: bool
    indices: tuple = ()

    def __post_init__(self):
        if not self.indices:
            object.__setattr__(self, 'indices', tuple(range(self.channels)))


# Toolkit GetMaxChannels, IsRelay (+0x20c) and HasChannelInterlock (+0x21c)
# per registered class. C-Gate selects the spec file for firmware 2.7.00.
# TRELDN8 is registered with TMarshallingBoxCGateAgent, whose load/save maps
# dialog channel c to PP array index (1, 2, 3, 4, 7, 8, 9, 10)[c - 1].
RELDN8_INDICES = (1, 2, 3, 4, 7, 8, 9, 10)
PROFILES = MappingProxyType({p.unit_type: p for p in (
    Profile('RELDN4', 'RELDN4.xml', 4, True, True),
    Profile('RELDN8', 'RELDN8.xml', 8, True, False, RELDN8_INDICES),
    Profile('RELDN8B', 'RELDN8.xml', 8, True, True),
    Profile('RELDN12', 'RELDN12.xml', 12, True, True),
    Profile('DIMDN4', 'DIMDN4.xml', 4, False, False),
    Profile('DIMDN4F', 'DIMDN4.xml', 4, False, False),
    Profile('DIMDN8', 'DIMDN8.xml', 8, False, False),
    Profile('DIMDN8F', 'DIMDN8.xml', 8, False, False),
)})
REFUSED = MappingProxyType({
    'RELDN8SP': ('Toolkit TRELDN8SP has nine channels and a special group-marshalling agent; '
                 'its dialog semantics are not admitted'),
    'RELAY4': 'RELAY4 uses the older LogicGA0-5 / LogicFunctionAndPowerUpDelay layout (TfrmCBus1Relay)',
    'DIMMER4': 'DIMMER4 uses the older TfrmCBus1Relay layout',
})
# Address, count, bit size, bit offset, byte skip, type.
_COMMON = {
    'InterLockingChannel': (48, 1, 8, 0, 0, 'int'), 'LogicLevelStoreEnable': (65, 4, 1, 4, 0, 'bit'),
    'RestrikeDelay': (66, 1, 8, 0, 0, 'int'), 'GroupAddress': (80, 16, 8, 0, 0, 'int'),
    'LightLevel': (0, 16, 8, 0, 0, 'int'),
}


def _arrays(count, max_address, max_count):
    rows = dict(_COMMON)
    for bit, name in enumerate(('LogicGA13Associations', 'LogicGA14Associations',
                                'LogicGA15Associations', 'LogicGA16Associations')):
        rows[name] = (50, count, 1, bit, 0, 'int')
    rows.update({'RestrikeChannel': (50, count, 1, 6, 0, 'int'), 'LogicFunction': (50, count, 1, 7, 0, 'int'),
                 'LevelStoreEnable': (64, count, 1, 0, 0, 'bit'), 'PowerUpDelay': (68, count, 8, 0, 0, 'int'),
                 'MinDimmingLevel': (96, count, 8, 0, 0, 'int'),
                 'MaxDimmingLevel': (max_address, max_count, 8, 0, 0, 'int')})
    return MappingProxyType(rows)


LAYOUTS = MappingProxyType({
    'RELDN4.xml': _arrays(4, 104, 4), 'DIMDN4.xml': _arrays(4, 104, 4),
    'RELDN8.xml': _arrays(12, 108, 4), 'RELDN12.xml': _arrays(12, 108, 4),
    'DIMDN8.xml': _arrays(8, 104, 8),
})
FIELDS = tuple(LAYOUTS['DIMDN8.xml'])
LOGIC_ASSOCIATIONS = ('LogicGA13Associations', 'LogicGA14Associations',
                      'LogicGA15Associations', 'LogicGA16Associations')
LOGIC_GROUP_INDEX = 12  # GroupAddress/LightLevel indexes 12..15 hold logic groups 1..4.
# rgLogic item index: relays And/Or, dimmers Min/Max.
LOGIC_FUNCTIONS = MappingProxyType({True: ('and', 'or'), False: ('min', 'max')})
RESTRIKE_DELAY = (1, 254)       # trkRestrikeDelay raw Min/Max, UseRawValues=true
RECOVERY_DELAY = (5, 255)       # trkRecoveryDelay raw Min/Max, UseRawValues=true


def percent_to_level(percent):
    """Original CIS_CBus.PercentToLevel (0x7f2aa0): percent*255 div 100."""
    percent = _integer(percent, 'Percent', 0, 100)
    return percent * 255 // 100


def level_to_percent(level):
    """Original CIS_CBus.LevelToPercent (0x7f2ac8): (level+2)*100 div 255."""
    level = _integer(level, 'Level', 0, 255)
    return (level + 2) * 100 // 255


def logic_group_level(percent):
    """Original OnRecoveryLevelChange Round(percent * 2.55) (0xef6e5a).

    The x87 product of the 2.55 extended constant rounds to the exact decimal
    product for 0..100, so Delphi's round-half-even applies to percent*255/100.
    """
    percent = _integer(percent, 'Percent', 0, 100)
    return round(Fraction(percent * 255, 100))


def recovery_delay_seconds(raw):
    """TfrmCBusDimmerRecovery.FormatTimeShort (0xef1460) display seconds."""
    return raw if raw < 60 else 60 + (raw - 60) * 10


def _integer(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise DinSettingsError(f'{label} must be an integer in {minimum}..{maximum}')
    return value


def _flag(value, label):
    if not isinstance(value, bool):
        raise DinSettingsError(f'{label} must be boolean')
    return value


def _version(value):
    return value if isinstance(value, str) and re.fullmatch(r'[0-9]{1,4}(\.[0-9]{1,4}){1,3}', value) else None


def profile_refusal(unit_type, firmware):
    """Return why a unit identity is outside the admitted DIN profiles, or None."""
    if unit_type not in PROFILES:
        return REFUSED.get(unit_type, 'Only RELDN4/8/8B/12 and DIMDN4/4F/8/8F use this workflow')
    if _version(firmware) != FIRMWARE:
        return f'{unit_type} firmware other than {FIRMWARE} has not been reviewed for this workflow'
    return None


def check_profile(unit_type, firmware, catalog_number=None, *, subject='Unit identity'):
    reason = profile_refusal(unit_type, firmware)
    if reason is not None:
        raise DinSettingsError(f'{subject} must be an admitted DIN relay/dimmer at firmware {FIRMWARE}: {reason}')
    return (unit_type, firmware, catalog_number)


@dataclass(frozen=True)
class DinPlan:
    unit_type: str
    channel: int | None
    logic_group: int | None
    expected: dict
    changes: dict
    derived: tuple = ()
    identity: tuple | None = None
    toolkit_save: bool = False
    pre_save_changes: dict | None = None
    save_normalization: dict | None = None

    def __post_init__(self):
        if type(self.toolkit_save) is not bool:
            raise DinSettingsError('toolkit_save must be boolean')
        for name in ('expected', 'changes'):
            object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in getattr(self, name).items()}))
        for name in ('pre_save_changes', 'save_normalization'):
            value = getattr(self, name)
            if self.toolkit_save and value is None:
                raise DinSettingsError('Toolkit save plans require ' + name)
            if not self.toolkit_save and value is not None:
                raise DinSettingsError('Targeted plans cannot contain Toolkit save metadata')
            if value is not None:
                object.__setattr__(self, name, MappingProxyType({k: tuple(v) for k, v in value.items()}))

    def as_dict(self):
        profile = PROFILES[self.unit_type]
        firmware, catalog_number = self.identity[1:] if self.identity else (None, None)
        result = {'format': TOOLKIT_SAVE_PLAN_FORMAT if self.toolkit_save else PLAN_FORMAT,
                'unit_type': self.unit_type, 'firmware': firmware,
                'catalog_number': catalog_number, 'firmware_admitted': FIRMWARE,
                'spec_filename': profile.spec_filename, 'channels': profile.channels,
                'channel': self.channel, 'logic_group': self.logic_group, 'derived': list(self.derived),
                'expected': {k: list(v) for k, v in self.expected.items()},
                'changes': {k: list(v) for k, v in self.changes.items()},
                'saved': False, 'device_verified': False}
        if self.toolkit_save:
            result.update(toolkit_save=True, normalization_passes=1,
                          pre_save_changes={k: list(v) for k, v in self.pre_save_changes.items()},
                          save_normalization={k: list(v) for k, v in self.save_normalization.items()})
        return result

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get('format') not in (PLAN_FORMAT, TOOLKIT_SAVE_PLAN_FORMAT):
            raise DinSettingsError('Expected a DIN output settings v1 or v2 plan document')
        toolkit_save = data.get('toolkit_save', False)
        if type(toolkit_save) is not bool:
            raise DinSettingsError('toolkit_save must be boolean')
        if toolkit_save != (data['format'] == TOOLKIT_SAVE_PLAN_FORMAT):
            raise DinSettingsError('Toolkit save requires a v2 plan with toolkit_save=true')
        unit_type = data.get('unit_type')
        if unit_type not in PROFILES:
            raise DinSettingsError('Plan unit type is not admitted')
        try:
            expected = {str(k): tuple(v) for k, v in data['expected'].items()}
            changes = {str(k): tuple(v) for k, v in data['changes'].items()}
        except (KeyError, AttributeError, TypeError) as error:
            raise DinSettingsError('Plan requires expected and changes mappings') from error
        firmware = data.get('firmware')
        identity = None if firmware is None else check_profile(unit_type, firmware, data.get('catalog_number'))
        pre_save_changes, save_normalization = None, None
        if toolkit_save:
            if type(data.get('normalization_passes')) is not int or data['normalization_passes'] != 1:
                raise DinSettingsError('Toolkit save plans require exactly one normalization pass')
            pre_save_changes = _strict_plan_values(data.get('pre_save_changes'), unit_type, 'pre_save_changes')
            save_normalization = _strict_plan_values(data.get('save_normalization'), unit_type, 'save_normalization')
            expected = _strict_plan_values(expected, unit_type, 'expected', complete=True)
            changes = _strict_plan_values(changes, unit_type, 'changes')
        elif any(name in data for name in ('pre_save_changes', 'save_normalization', 'normalization_passes')):
            raise DinSettingsError('Targeted plans cannot contain Toolkit save metadata')
        return cls(unit_type, data.get('channel'), data.get('logic_group'), expected, changes,
                   tuple(data.get('derived') or ()), identity, toolkit_save,
                   pre_save_changes, save_normalization)


def _strict_plan_values(values, unit_type, label, *, complete=False):
    """Canonical v2 documents contain exact integer arrays, never coercible values."""
    if not isinstance(values, (dict, MappingProxyType)):
        raise DinSettingsError('Toolkit save plan requires a ' + label + ' mapping')
    layout = LAYOUTS[PROFILES[unit_type].spec_filename]
    if (complete and set(values) != set(FIELDS)) or any(name not in FIELDS for name in values):
        raise DinSettingsError('Toolkit save plan has invalid ' + label + ' fields')
    result = {}
    for name, row in values.items():
        count, bits = layout[name][1:3]
        if (not isinstance(row, (tuple, list)) or len(row) != count
                or any(type(value) is not int or not 0 <= value < 1 << bits for value in row)):
            raise DinSettingsError('Toolkit save plan has invalid ' + label + ' array: ' + name)
        result[name] = tuple(row)
    return result


class DinOutputEditor:
    def __init__(self, spec, unit_type=None):
        unit_type = spec.unit_type if unit_type is None else unit_type
        if unit_type not in PROFILES:
            raise DinSettingsError(REFUSED.get(unit_type, 'Only admitted DIN relay/dimmer types use this workflow'))
        self.profile = PROFILES[unit_type]
        if spec.filename != self.profile.spec_filename:
            raise DinSettingsError(f'Use {self.profile.spec_filename} for {unit_type} {FIRMWARE}')
        self.spec, self.codec = spec, MemoryCodec(spec)
        self.layout = LAYOUTS[spec.filename]
        for name, expected in self.layout.items():
            layout = self.codec.layout(name)
            actual = (layout.address, layout.array_size, layout.bit_size, layout.bit_address,
                      layout.array_skip, layout.parameter.type)
            if actual != expected:
                raise DinSettingsError('Unsupported DIN parameter layout: ' + name)

    @property
    def unit_type(self):
        return self.profile.unit_type

    def snapshot(self, current):
        result = {}
        for name in FIELDS:
            if name not in current:
                raise DinSettingsError('Missing current DIN parameter: ' + name)
            values = _numbers(current[name])
            if not self.spec.get(name).validate_value(list(values))['valid']:
                raise DinSettingsError('Invalid current DIN parameter: ' + name)
            result[name] = values
        return result

    # ---- read model -------------------------------------------------
    def show(self, current):
        """Project the stored values the way the Toolkit tabs display them."""
        values, p = self.snapshot(current), self.profile
        names = LOGIC_FUNCTIONS[p.relay]
        channels = []
        for c, i in enumerate(p.indices):
            store = bool(values['LevelStoreEnable'][i])
            level = values['LightLevel'][i]
            row = {'channel': c + 1, 'pp_index': i,
                   'logic_groups': [g + 1 for g, n in enumerate(LOGIC_ASSOCIATIONS) if values[n][i]],
                   'logic_function': names[values['LogicFunction'][i]],
                   'min_level': values['MinDimmingLevel'][i],
                   'min_percent': level_to_percent(values['MinDimmingLevel'][i]),
                   'level_store': store, 'recovery_level': level,
                   'recovery_percent': None if store else level_to_percent(level)}
            if not p.relay:
                delay = values['PowerUpDelay'][i]
                row.update(max_level=values['MaxDimmingLevel'][i],
                           max_percent=level_to_percent(values['MaxDimmingLevel'][i]),
                           recovery_delay=delay, recovery_delay_seconds=recovery_delay_seconds(delay))
            else:
                row['restrike'] = bool(values['RestrikeChannel'][i])
            # RELDN8's later marshalling save replaces the base forced 255
            # with the retained channel-model level.
            row['toolkit_save_rewrites_recovery_level'] = p.unit_type != 'RELDN8' and store and level != 255
            channels.append(row)
        logic = []
        for g in range(4):
            level = values['LightLevel'][LOGIC_GROUP_INDEX + g]
            logic.append({'logic_group': g + 1, 'group_address': values['GroupAddress'][LOGIC_GROUP_INDEX + g],
                          'level_store': bool(values['LogicLevelStoreEnable'][g]),
                          'recovery_level': level, 'recovery_percent': level_to_percent(level)})
        result = {'format': 'cbus-din-output-settings-v1', 'unit_type': p.unit_type,
                  'spec_filename': p.spec_filename, 'relay': p.relay, 'channels': channels,
                  'logic_groups': logic}
        raw = values['InterLockingChannel'][0]
        if p.relay:
            delay = values['RestrikeDelay'][0]
            result['restrike_delay'] = {'raw': delay, 'seconds': delay * 10,
                                        'toolkit_range': RESTRIKE_DELAY[0] <= delay <= RESTRIKE_DELAY[1]}
        if p.interlock:
            # Relay AfterLoadProgrammingInformation keeps raw & 7 above 7.
            limit, index = min(p.channels, 8), raw & 7 if raw > 7 else raw
            result['interlock'] = {'raw': raw, 'toolkit_index': index,
                                   'channels': 0 if index == 0 else index + 1 if index < limit else None}
        else:
            result['interlock'] = {'raw': raw, 'channels': None, 'toolkit_control': False}
        return result

    # ---- plan -------------------------------------------------------
    def plan(self, current, *, channel=None, logic_groups=None, logic_function=None,
             min_level=None, min_percent=None, max_level=None, max_percent=None,
             recovery_level=None, recovery_percent=None, level_store=None, recovery_delay=None,
             restrike=None, interlock=None, restrike_delay=None, logic_group=None,
             logic_group_address=None, logic_recovery_level=None, logic_recovery_percent=None,
             logic_level_store=None, identity=None, toolkit_save=False):
        """Plan one channel's tab edits plus optional unit and logic-group settings.

        Percent inputs use the original PercentToLevel conversion and the
        Min/Max slider coupling; ``*_level`` inputs write raw bytes.
        ``toolkit_save`` additionally projects one source-pinned agent save
        over the owned fields. It does not execute the whole original dialog.
        """
        if type(toolkit_save) is not bool:
            raise DinSettingsError('toolkit_save must be boolean')
        p = self.profile
        if identity is not None:
            if not isinstance(identity, tuple) or len(identity) != 3:
                raise DinSettingsError('Identity must be (unit_type, firmware, catalog_number)')
            identity = check_profile(*identity)
            if identity[0] != p.unit_type:
                raise DinSettingsError('Identity unit type differs from the selected profile')
        channel_options = {'logic_groups': logic_groups, 'logic_function': logic_function,
                           'min_level': min_level, 'min_percent': min_percent, 'max_level': max_level,
                           'max_percent': max_percent, 'recovery_level': recovery_level,
                           'recovery_percent': recovery_percent, 'level_store': level_store,
                           'recovery_delay': recovery_delay, 'restrike': restrike}
        logic_options = {'logic_group_address': logic_group_address, 'logic_recovery_level': logic_recovery_level,
                         'logic_recovery_percent': logic_recovery_percent, 'logic_level_store': logic_level_store}
        used = {k for k, v in channel_options.items() if v is not None}
        if used and channel is None:
            raise DinSettingsError('Channel settings require a channel')
        if channel is not None:
            channel = _integer(channel, 'Channel', 1, p.channels)
        logic_used = {k for k, v in logic_options.items() if v is not None}
        if logic_used and logic_group is None:
            raise DinSettingsError('Logic recovery and group settings require a logic group')
        if logic_group is not None:
            logic_group = _integer(logic_group, 'Logic group', 1, 4)
        for pair in (('min_level', 'min_percent'), ('max_level', 'max_percent'),
                     ('recovery_level', 'recovery_percent')):
            if all(channel_options[name] is not None for name in pair):
                raise DinSettingsError(f'Use either {pair[0]} or {pair[1]}')
        if logic_recovery_level is not None and logic_recovery_percent is not None:
            raise DinSettingsError('Use either logic_recovery_level or logic_recovery_percent')
        if p.relay and (max_level is not None or max_percent is not None):
            raise DinSettingsError('The relay Turn On tab binds only the minimum threshold; MaxDimmingLevel is not a relay control')
        if not p.relay and (restrike is not None or restrike_delay is not None):
            raise DinSettingsError('Restrike settings exist only on relay units')
        if interlock is not None and not p.interlock:
            raise DinSettingsError(f'Toolkit hides the interlock control for {p.unit_type}')

        original = self.snapshot(current)
        updates = {name: list(values) for name, values in original.items()}
        derived = []
        i = None if channel is None else p.indices[channel - 1]
        if logic_groups is not None:
            try:
                selected = set(logic_groups)
            except TypeError as error:
                raise DinSettingsError('Logic groups must be a collection of 1..4') from error
            for group in selected:
                _integer(group, 'Logic group association', 1, 4)
            for g, name in enumerate(LOGIC_ASSOCIATIONS):
                updates[name][i] = int(g + 1 in selected)
        if logic_function is not None:
            names = LOGIC_FUNCTIONS[p.relay]
            if logic_function not in names:
                raise DinSettingsError('Logic function must be ' + ' or '.join(names))
            # OnLogicControlsChange enables rgLogic only while an association is ticked.
            if not any(updates[name][i] for name in LOGIC_ASSOCIATIONS):
                raise DinSettingsError('Toolkit disables the logic function until a logic group is associated')
            updates['LogicFunction'][i] = names.index(logic_function)
        self._turn_on(updates, i, min_level, min_percent, max_level, max_percent, derived)
        if level_store is not None or recovery_level is not None or recovery_percent is not None or recovery_delay is not None:
            self._recovery(updates, i, level_store, recovery_level, recovery_percent, recovery_delay, derived)
        if restrike is not None:
            updates['RestrikeChannel'][i] = int(_flag(restrike, 'Restrike'))
        if restrike_delay is not None:
            # RestrikeChanged enables the delay slider only when a channel restrikes.
            if not any(updates['RestrikeChannel'][j] for j in p.indices):
                raise DinSettingsError('Toolkit disables the restrike delay until a channel has restrike enabled')
            updates['RestrikeDelay'][0] = _integer(restrike_delay, 'Restrike delay', *RESTRIKE_DELAY)
        if interlock is not None:
            limit = min(p.channels, 8)
            if isinstance(interlock, bool) or not isinstance(interlock, int) or interlock not in (0, *range(2, limit + 1)):
                raise DinSettingsError(f'Interlock channel count must be 0 or 2..{limit}')
            # TFlashListComboBox UseIndex: items "0","2".."N" store their index.
            updates['InterLockingChannel'][0] = 0 if interlock == 0 else interlock - 1
        if logic_group is not None:
            self._logic_group(updates, logic_group - 1, logic_group_address, logic_recovery_level,
                              logic_recovery_percent, logic_level_store)
        pre_save_changes, save_normalization = None, None
        if toolkit_save:
            pre_save_changes = self._difference(original, updates)
            normalized = self._toolkit_save(updates)
            save_normalization = self._difference(updates, normalized)
            updates = normalized
        # TddCBusDimmer.ValidateProgramming/UnusedGroupInLogic refuses to save a
        # channel associated with a logic group that has no group address.
        for g, name in enumerate(LOGIC_ASSOCIATIONS):
            if updates['GroupAddress'][LOGIC_GROUP_INDEX + g] == 255 and any(updates[name][j] for j in p.indices):
                raise DinSettingsError(f'Logic group {g + 1} is associated with a channel but has no group address')
        changes = self._difference(original, updates)
        self.codec.encode_many(changes)
        return DinPlan(p.unit_type, channel, logic_group, original, changes, tuple(dict.fromkeys(derived)),
                       identity, toolkit_save, pre_save_changes, save_normalization)

    @staticmethod
    def _difference(before, after):
        return {name: tuple(values) for name, values in after.items()
                if tuple(values) != tuple(before[name])}

    def _toolkit_save(self, current):
        """One owned-field load/save projection; see din-output-save-source-review.json.

        The normal DIN agent pads only GroupAddress/LightLevel to twelve
        channel positions. Short native PP arrays retain the old tail. The
        RELDN8 marshalling override rebuilds the mapped fields after its base
        call, including raw levels even when level store is set. Max levels
        keep the base agent's dialog order and are truncated by the four-slot
        schema. This projection is intentionally not an iterative fixed point.
        """
        values = _strict_plan_values(current, self.unit_type, 'pre-save', complete=True)
        result = {name: list(row) for name, row in values.items()}
        p = self.profile
        if p.unit_type == 'RELDN8':
            # AddEmptyGroup writes three holes, then eight channel objects.
            # The final string has eleven tokens. Other per-channel fields
            # retain their original twelfth value under native PP SET.
            holes = (0, 5, 6)
            marshalled = (*LOGIC_ASSOCIATIONS, 'LogicFunction', 'RestrikeChannel',
                          'LevelStoreEnable', 'PowerUpDelay', 'MinDimmingLevel', 'LightLevel')
            for name in marshalled:
                for index in holes:
                    result[name][index] = 0
            for index in (*holes, 11):
                result['GroupAddress'][index] = 255
            result['LightLevel'][11] = 0
            # AfterLoad maps 1,2,3,4,... and uses zero for absent max entries;
            # BeforeSave emits that model order, truncated to four PP tokens.
            result['MaxDimmingLevel'] = [values['MaxDimmingLevel'][index]
                                        if index < len(values['MaxDimmingLevel']) else 0
                                        for index in p.indices[:4]]
        else:
            for index in p.indices:
                if values['LevelStoreEnable'][index]:
                    result['LightLevel'][index] = 255
            for index in range(p.channels, LOGIC_GROUP_INDEX):
                result['GroupAddress'][index] = 255
                result['LightLevel'][index] = 0
        if p.relay:
            result['InterLockingChannel'][0] &= 7
        return result

    def _verify_toolkit_save_plan(self, plan):
        """Replay a v2 projection before session access, including its receipts."""
        expected = _strict_plan_values(plan.expected, self.unit_type, 'expected', complete=True)
        changes = _strict_plan_values(plan.changes, self.unit_type, 'changes')
        requested = _strict_plan_values(plan.pre_save_changes, self.unit_type, 'pre_save_changes')
        normalization = _strict_plan_values(plan.save_normalization, self.unit_type, 'save_normalization')
        before_save = dict(expected, **requested)
        if requested != self._difference(expected, before_save):
            raise DinSettingsError('Toolkit save plan pre_save_changes are not canonical')
        final = self._toolkit_save(before_save)
        if (changes != self._difference(expected, final)
                or normalization != self._difference(before_save, final)):
            raise DinSettingsError('Toolkit save plan differs from its one-pass normalization')
        # The whole save still has the original unused-logic-group guard;
        # a caller cannot bypass it with a serialized plan.
        for group, name in enumerate(LOGIC_ASSOCIATIONS):
            if final['GroupAddress'][LOGIC_GROUP_INDEX + group] == 255 and any(
                    final[name][index] for index in self.profile.indices):
                raise DinSettingsError(f'Logic group {group + 1} is associated with a channel but has no group address')

    def _sharing(self, updates, group, *, channel=None, logic_group=None):
        """Channels and logic groups that Toolkit couples through a used group."""
        if group == 255:
            return (), ()
        channels = tuple(j for j in self.profile.indices
                         if j != channel and updates['GroupAddress'][j] == group)
        logic = tuple(g for g in range(4) if g != logic_group
                      and updates['GroupAddress'][LOGIC_GROUP_INDEX + g] == group)
        return channels, logic

    def _recovery(self, updates, i, level_store, recovery_level, recovery_percent, recovery_delay, derived):
        if recovery_delay is not None:
            if self.profile.relay:
                raise DinSettingsError('The relay Recovery tab hides the delay slider; PowerUpDelay is not a relay control')
            updates['PowerUpDelay'][i] = _integer(recovery_delay, 'Recovery delay', *RECOVERY_DELAY)
        if level_store is None and recovery_level is None and recovery_percent is None:
            return
        channels, logic = self._sharing(updates, updates['GroupAddress'][i], channel=i)
        if level_store is not None:
            if channels or logic:
                # OnLevelStoreEnableChange copies the checkbox to every channel and
                # logic group on the same group; that cascade is not admitted here.
                raise DinSettingsError('Auto Level Store on a group shared by other channels or logic groups is not admitted')
            updates['LevelStoreEnable'][i] = int(_flag(level_store, 'Level store'))
            if level_store and updates['LightLevel'][i] != 255:
                # chkLevelStoreEnableClick sets the slider to 100 % and
                # BeforeSaveProgrammingInformation writes "255 " for the channel.
                updates['LightLevel'][i] = 255
                derived.append('LightLevel')
        if recovery_level is None and recovery_percent is None:
            return
        if updates['LevelStoreEnable'][i]:
            raise DinSettingsError('Auto Level Store is enabled; Toolkit disables the recovery level slider')
        if recovery_level is not None:
            if channels or logic:
                raise DinSettingsError('A raw recovery level cannot reproduce Toolkit group coupling; use a percentage')
            updates['LightLevel'][i] = _integer(recovery_level, 'Recovery level', 0, 255)
            return
        percent = _integer(recovery_percent, 'Recovery percent', 0, 100)
        updates['LightLevel'][i] = percent_to_level(percent)
        # OnRecoveryLevelChange: enabled sliders on the same group follow, and
        # logic groups on that group take Round(percent * 2.55).
        for j in channels:
            if not updates['LevelStoreEnable'][j]:
                updates['LightLevel'][j] = percent_to_level(percent)
                derived.append(f'LightLevel[{j}]')
        for g in logic:
            updates['LightLevel'][LOGIC_GROUP_INDEX + g] = logic_group_level(percent)
            derived.append(f'LightLevel[{LOGIC_GROUP_INDEX + g}]')

    def _logic_group(self, updates, g, address, level, percent, store):
        index = LOGIC_GROUP_INDEX + g
        if address is not None:
            # EnableLogicGroups enables the group box only while a channel uses it.
            if not any(updates[LOGIC_ASSOCIATIONS[g]][j] for j in self.profile.indices):
                raise DinSettingsError('Toolkit disables a logic group selector until a channel is associated with it')
            updates['GroupAddress'][index] = _integer(address, 'Logic group address', 0, 255)
        if store is None and level is None and percent is None:
            return
        channels, logic = self._sharing(updates, updates['GroupAddress'][index], logic_group=g)
        if channels or logic:
            # OnLogicRecoveryLevelChange/OnLogicLevelStoreEnableChange re-propagate
            # through channel sliders; that re-entrant cascade is not admitted.
            raise DinSettingsError('Logic recovery on a group shared by channels or other logic groups is not admitted')
        if store is not None:
            updates['LogicLevelStoreEnable'][g] = int(_flag(store, 'Logic level store'))
        if level is not None or percent is not None:
            if updates['LogicLevelStoreEnable'][g]:
                raise DinSettingsError('Logic Auto Level Store is enabled; Toolkit disables the logic level slider')
            updates['LightLevel'][index] = (_integer(level, 'Logic recovery level', 0, 255)
                                            if level is not None else percent_to_level(percent))

    def _turn_on(self, updates, i, min_level, min_percent, max_level, max_percent, derived):
        mins, maxes = updates['MinDimmingLevel'], updates['MaxDimmingLevel']
        if min_percent is not None:
            minimum = _integer(min_percent, 'Minimum percent', 0, 100)
            mins[i] = percent_to_level(minimum)
            # trkMinPropertiesChange: a dimmer's max slider moves to min+1.
            if not self.profile.relay and level_to_percent(maxes[i]) <= minimum:
                maxes[i] = percent_to_level(min(minimum + 1, 100))
                derived.append('MaxDimmingLevel')
        elif min_level is not None:
            mins[i] = _integer(min_level, 'Minimum level', 0, 255)
        if max_percent is not None:
            maximum = _integer(max_percent, 'Maximum percent', 0, 100)
            maxes[i] = percent_to_level(maximum)
            # trkMaxPropertiesChange: the min slider moves to max-1.
            if level_to_percent(mins[i]) >= maximum:
                mins[i] = percent_to_level(max(maximum - 1, 0))
                derived.append('MinDimmingLevel')
        elif max_level is not None:
            maxes[i] = _integer(max_level, 'Maximum level', 0, 255)
        if (min_level is not None or max_level is not None) and not self.profile.relay and mins[i] > maxes[i]:
            raise DinSettingsError('Raw minimum level exceeds the maximum level')

    # ---- apply ------------------------------------------------------
    def control_plan(self, current, operations, *, identity=None, toolkit_save=False):
        """Plan a bounded ordered slider history; see din_output_controls."""
        from .din_output_controls import control_plan
        return control_plan(self, current, operations, identity=identity, toolkit_save=toolkit_save)

    def _verify_profile(self, session):
        identity = check_profile(session.unit_type, session.firmware, session.catalog_number,
                                 subject='Native session')
        if identity[0] != self.profile.unit_type:
            raise DinSettingsError('Native session unit type differs from the selected profile')
        return identity

    def _verify_session(self, session, *, strict_width=False):
        document = xml_text(session.info('*'))
        if '<!DOCTYPE' in document.upper() or '<!ENTITY' in document.upper():
            raise DinSettingsError('Unsupported native schema declarations')
        try:
            root = ET.fromstring(document)
        except ET.ParseError as error:
            raise DinSettingsError('Invalid native parameter schema') from error
        fields = {}
        for param in root.iter():
            if param.tag.rsplit('}', 1)[-1] == 'Param':
                row = {child.tag.rsplit('}', 1)[-1]: child.text or '' for child in param}
                if row.get('Name') in fields:
                    raise DinSettingsError('Duplicate native parameter schema')
                fields[row.get('Name')] = row
        for name in FIELDS:
            native, local = fields.get(name, {}), self.spec.get(name).fields
            if native.get('Type', '').lower() != local.get('Type', '').lower():
                raise DinSettingsError('Native parameter type mismatch: ' + name)
            for field, default in (('Address', None), ('ArraySize', '1'), ('BitAddress', '0'), ('ArraySkip', '0')):
                if _numbers(native.get(field, default)) != _numbers(local.get(field, default)):
                    raise DinSettingsError(f'Native parameter layout mismatch: {name}/{field}')
            if strict_width and local.get('Type', '').lower() != 'bit':
                if _numbers(native.get('BitSize', '8')) != _numbers(local.get('BitSize', '8')):
                    raise DinSettingsError(f'Native parameter layout mismatch: {name}/BitSize')

    def apply(self, session, plan, *, _strict_width=False):
        from .din_output_controls import DinControlPlan, apply_controls
        if isinstance(plan, DinControlPlan):
            return apply_controls(self, session, plan)
        if (not isinstance(plan, DinPlan) or plan.unit_type != self.profile.unit_type
                or set(plan.expected) != set(FIELDS) or any(name not in FIELDS for name in plan.changes)):
            raise DinSettingsError('Plan contains fields or a unit type outside this DIN workflow')
        if plan.toolkit_save:
            self._verify_toolkit_save_plan(plan)
        self.codec.encode_many(plan.changes)
        identity = self._verify_profile(session)
        if plan.identity is not None and plan.identity[:2] != identity[:2]:
            raise DinSettingsError('Plan was created for another unit type or firmware')
        self._verify_session(session, strict_width=plan.toolkit_save or _strict_width)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise DinSettingsError('PP parameters changed since the DIN settings plan was created')
        attempted = []
        try:
            for name, values in plan.changes.items():
                attempted.append(name)
                session.set(name, ' '.join(map(str, values)))
            expected = dict(plan.expected)
            expected.update(plan.changes)
            if self.snapshot(session.values()) != expected:
                raise DinSettingsError('Native DIN readback differs from the plan')
        except (RuntimeError, OSError, ValueError) as error:
            # Never issue recovery I/O after an uncertain transport or partial
            # PP error; the unsaved session can be inspected or discarded.
            raise DinSettingsApplyError(error, attempted) from error
        return {**replace(plan, identity=identity).as_dict(), 'verified': True}

    def configure(self, session, **options):
        identity = self._verify_profile(session)
        return self.apply(session, self.plan(session.values(), identity=identity, **options))
