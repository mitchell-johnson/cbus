"""Inspect thermostat application migration without executing original code.

This pins the migration core, not the complete parent/control lifecycle. The
separate callback, selector and Windows character-table dependencies must be
closed before these findings can establish an executable history contract.
No vendor bytes, private paths or site data are emitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402
from thermostat_post_load_static import _Walker  # noqa: E402

THERMOSTAT = 'CIS_TThermostat.'
GROUPS = 'CIS_TCommonCBus.TCBusGroupManager.'
DECISION = 'CIS_TddThermostat.TddThermostat.HandleUnitDecisionCreateApplicationGroups'
METHODS = (
    THERMOSTAT + 'TThermostat.ApplicationChanged',
    THERMOSTAT + 'TThermostat.RefreshThermostatGroups',
    THERMOSTAT + 'CheckGroupsMissing',
    THERMOSTAT + 'UpdateGroup',
    THERMOSTAT + 'UpdateInternalRelayGroup',
    GROUPS + 'NewGroupWithAddressAfter',
    GROUPS + 'GroupByTagName',
    GROUPS + 'GroupByTagNameExclude',
    'CIS_TCommonCBus.TCBusGroup.HasDefaultTagName',
    DECISION,
)
ROLES = (
    'CoolActivation', 'CoolStage1', 'CoolStage2', 'CoolStage3',
    'CoolFanLow', 'CoolFanMedium', 'CoolFanHigh',
    'HeatActivation', 'HeatStage1', 'HeatStage2', 'HeatStage3',
    'HeatFanLow', 'HeatFanMedium', 'HeatFanHigh',
    'DamperZone1', 'DamperZone2', 'DamperZone3', 'DamperZone4',
)

# These checkpoints bind the decisive branches as well as their call targets.
# The complete method spans are hashed separately below.
POINTS = {
    0xfeb47a: ('cmp', 'word ptr [eax + 0x1ca], 0'),
    0xfeb487: ('cmp', 'byte ptr [eax + 0x1e3], 0'),
    0xfeb4a8: ('call', '0xfec798'),
    0xfeb4c5: ('mov', 'byte ptr [eax + 0x1e3], 1'),
    0xfeb4d7: ('mov', 'byte ptr [eax + 0x1e3], 0'),
    0xfec7a7: ('cmp', 'byte ptr [eax + 0x1e0], 0'),
    0xfec7b7: ('cmp', 'byte ptr [eax + 0xdf], 0'),
    0xfec7c4: ('mov', 'byte ptr [ebp - 5], 1'),
    0xfec7c9: ('call', '0xfeb4e4'),
    0xfec80e: ('call', 'dword ptr [ebx + 0x1d0]'),
    0xfec821: ('call', '0xf2d370'),
    0xfec83c: ('call', '0xfdea78'),
    0xfec841: ('dec', 'eax'),
    0xfec842: ('jne', '0xfec890'),
    0xfecb64: ('call', '0xf2d384'),
    0x1133226: ('mov', 'byte ptr [eax], 1'),
    0xfebe58: ('mov', 'byte ptr [ebp - 5], dl'),
    0xfebe5b: ('mov', 'dword ptr [ebp - 4], eax'),
    0xfebe71: ('call', 'dword ptr [edx + 0xa4]'),
    0xfebe77: ('mov', 'dword ptr [ebp - 0x10], eax'),
    0xfebe7e: ('je', '0xfec729'),
    0xfebe8c: ('cmp', 'eax, 0xff'),
    0xfebe91: ('je', '0xfec704'),
    0xfebec1: ('call', '0xf28d7c'),
    0xfebec8: ('je', '0xfebf10'),
    0xfebeca: ('mov', 'eax, dword ptr [ebp - 0x10]'),
    0xfebecf: ('call', 'dword ptr [edx + 0xa0]'),
    0xfebed7: ('jne', '0xfebf10'),
    0xfebf03: ('call', '0xf28d7c'),
    0xfebf0b: ('jmp', '0xfec74c'),
    0xfebf21: ('cmp', 'eax, dword ptr [ebp - 4]'),
    0xfec24c: ('call', '0xfe2a74'),
    0xfec254: ('push', '0xfec794'),
    0xfec264: ('call', '0x608eec'),
    0xfec282: ('call', '0xf28d7c'),
    0xfec28e: ('jne', '0xfec74c'),
    0xfec2a8: ('mov', 'edx, 1'),
    0xfec2ad: ('call', '0xf28dd4'),
    0xfec2b5: ('cmp', 'byte ptr [ebp - 5], 0'),
    0xfec2b9: ('je', '0xfec6d4'),
    0xfec2e9: ('mov', 'cl, 1'),
    0xfec6e9: ('mov', 'eax, dword ptr [ebp - 0x10]'),
    0xfec6ec: ('call', '0xf47a10'),
    0xfec6f6: ('mov', 'cl, byte ptr [eax - 5]'),
    0xfec6fa: ('call', '0xf28b68'),
    0xfec718: ('mov', 'cl, 1'),
    0xfec71a: ('mov', 'edx, 0xff'),
    0xfec71f: ('call', '0xf28b68'),
    0xfec73d: ('mov', 'cl, 1'),
    0xfec73f: ('mov', 'edx, 0xff'),
    0xfec744: ('call', '0xf28b68'),
    0xfec750: ('mov', 'edx, dword ptr [ebp - 0xc]'),
    0xfec753: ('mov', 'eax, dword ptr [ebp - 0x10]'),
    0xfec756: ('call', '0xfebd50'),
    0xfebd60: ('je', '0xfebe41'),
    0xfebd6e: ('cmp', 'eax, 0xff'),
    0xfebd73: ('je', '0xfebe41'),
    0xfebd89: ('cmp', 'eax, dword ptr [ebp - 4]'),
    0xf28de2: ('mov', 'dword ptr [ebp - 0xc], eax'),
    0xf28de8: ('cmp', 'eax, 0xfe'),
    0xf28dfa: ('call', '0xf28b68'),
    0xf28e03: ('mov', 'cl, 1'),
    0xf28e0b: ('call', '0xf28b68'),
    0xf28e13: ('jmp', '0xf28e21'),
    0xf28e15: ('inc', 'dword ptr [ebp - 0x10]'),
    0xf28e18: ('cmp', 'dword ptr [ebp - 0x10], 0xff'),
    0xf28e1f: ('jne', '0xf28df2'),
    0xf28e66: ('call', '0x6186e4'),
    0xf28ece: ('call', '0x6186e4'),
    0xf28ed9: ('call', '0x6090ac'),
    0xf28eee: ('jmp', '0xf28ef8'),
    0xf27d64: ('call', '0x6094d4'),
    0xf27d69: ('dec', 'eax'),
    0xf27db6: ('add', 'edx, 2'),
    0xf27db9: ('mov', 'ecx, 0x64'),
    0xf27dc1: ('call', '0x609114'),
    0xf27dc9: ('call', '0x781350'),
}


def inspect(exe: Path, map_path: Path):
    raw, mapping = exe.read_bytes(), map_path.read_bytes()
    digest = lambda value: hashlib.sha256(value).hexdigest()
    if (digest(raw), digest(mapping)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Expected the pinned Toolkit executable and map')
    image = _Image(raw, mapping)
    walker = _Walker(image)
    methods, listings, instructions = {}, {}, {}
    for symbol in METHODS:
        rows, _tables, span_digest = walker.listing(symbol)
        start = image.by_name[symbol]
        end = next(address for address in image.starts if address > start)
        methods[symbol] = {'start': hex(start), 'end': hex(end), 'sha256': span_digest}
        listings[symbol] = rows
        instructions.update({address: (mnemonic, operand) for address, mnemonic, operand, _ in rows})
    checks = {hex(address): instructions.get(address) == value for address, value in POINTS.items()}
    refresh = listings[THERMOSTAT + 'TThermostat.RefreshThermostatGroups']
    setters = [note.rsplit('.', 1)[-1] for _, mnemonic, _, note in refresh
               if mnemonic == 'call' and '.Set' in note]
    checks['migration_setter_order'] = setters == [
        'SetRemoteSetbackOnGroup', 'SetRemoteSetbackOffGroup',
        *['Set' + role + 'OutputGroup' for role in ROLES]]
    checks['migration_update_calls'] = sum(m == 'call' and p == '0xfebe48'
                                         for _, m, p, _ in refresh) == 20
    checks['no_independent_relay_or_schedule_assignment'] = not any(
        'InternalRelay' in name or 'Schedule' in name for name in setters)
    relays = listings[THERMOSTAT + 'UpdateInternalRelayGroup']
    checks['relay_updates_one_through_five'] = [note.rsplit('.', 1)[-1]
        for _, mnemonic, _, note in relays if mnemonic == 'call' and '.SetInternalRelay' in note] == [
            'SetInternalRelay' + str(i) + 'Group' for i in range(1, 6)]
    checks['relay_updates_compare_identity'] = sum(m == 'cmp' and p == 'eax, dword ptr [ebp - 4]'
                                                 for _, m, p, _ in relays) == 5
    missing = listings[THERMOSTAT + 'CheckGroupsMissing']
    checks['missing_check_25_numeric_lookups'] = sum(m == 'call' and p == '0xf28b68'
                                                   for _, m, p, _ in missing) == 25
    checks['missing_check_25_create_false'] = sum(m == 'xor' and p == 'ecx, ecx'
                                                for _, m, p, _ in missing) == 25
    if not all(checks.values()):
        raise ValueError('Application migration source differs: ' + ', '.join(
            key for key, value in checks.items() if not value))
    if (digest(exe.read_bytes()), digest(map_path.read_bytes())) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original source inputs changed during inspection')
    return {
        'format': 'cbus-thermostat-application-change-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False, 'native_vendor_executed': False, 'physical_io': False,
        'checks': dict(sorted(checks.items())), 'method_spans': methods,
        'core_rules': {
            'order': ['source1_setback_on', 'source1_setback_off', *ROLES],
            'group_argument': 'Reference attribute identity; resolve the old Group separately.',
            'old_tag_reuse': 'First ASCII-UpperCase match, provided the old Group is not default-named.',
            'old_tag_default_name_dependency': 'The old Group classifier is consumed only when an old-tag match exists; nested role default getters can also classify a newly allocated Group.',
            'generated_name': 'Prefix plus one space plus attribute-specific role label; setback label is empty.',
            'first_free_allocation': {'minimum': 1, 'maximum': 254, 'exhausted': None},
            'setback_allocation': 'Keep the provisional group, then resolve the old numeric address.',
            'relay_update': 'Immediately replace every current relay identity equal to the old non-unused Group.',
            'nil_or_unused': 'Resolve a real destination Group255 with creation enabled.',
            'parent_missing_group_decision': 'Unconditional true; no operator question.',
        },
        'boundary': {
            'implementation_complete': False,
            'callback_multiplicity_and_initialized_toggle': 'Requires the parent/controller chain.',
            'selector_and_dialog_rebinding': 'Requires list/current-object and Add/Edit callbacks.',
            'first_match_order': 'Requires the manager preference and insertion/timer chain.',
            'jcl_digit_table': 'Windows C1_DIGIT data and DecimalSeparator are external dependencies.',
            'original_fault_prefixes_replayed': False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
