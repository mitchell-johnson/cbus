"""Pin thermostat template group phases and remaining allocation boundaries.

Read the explicitly supplied original EXE/MAP; execute no vendor code. The
report records addresses, hashes, recovered rules and checks, never binary
instruction bytes. This receipt distinguishes the template relay-load skip
implemented by the replay from the allocator/rename behavior still omitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402
from thermostat_post_load_static import (AGENT, PLANT, _Walker, _assignments,  # noqa: E402
                                         _case_table, _normal_update)

PARENT = 'CIS_TddThermostat.TddThermostat.'
CHILD = 'CIS_TcdThermostatTemplates.TcdThermostatTemplates.'
MANAGER = 'CIS_TCommonCBus.TCBusGroupManager.'
STANDARD = 'CIS_TStandardCBusApplications.'
METHODS = (
    PARENT + 'InitialiseSubForms', PARENT + 'HandleBeforeLoadTemplate',
    PARENT + 'HandleLoadTemplate', CHILD + 'HandleBtnLoadClick',
    AGENT + 'AfterLoadProgrammingInformation', PLANT + 'CreateAndRenameGroup',
    PLANT + 'GetGroup', PLANT + 'FindExistingGroup', 'CIS_TThermostat.GetNewGroup',
    MANAGER + 'GetNextAvailableAddress', MANAGER + 'GetMaximumPossibleAddress',
    MANAGER + 'GroupByAddress', 'CIS_TCommonCBus.TCBUSApplication.GetHasReservedGroupAddress255',
    STANDARD + 'CIS_TStandardCBusApplications',
    STANDARD + 'TStandardCBusApplication.Create',
    STANDARD + 'TStandardCBusApplications.GetGroupName',
    STANDARD + 'TStandardCBusApplications.GetStandardCBusApplication',
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inspect(exe: Path, map_path: Path) -> dict:
    exe_raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    if (_sha(exe_raw), _sha(map_raw)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image, checks = _Image(exe_raw, map_raw), {}
    walker = _Walker(image)
    methods = {name: walker.listing(name) for name in METHODS}
    rows = {name: {a: (m, op, note) for a, m, op, note in data[0]}
            for name, data in methods.items()}

    def instruction(name, address, mnemonic, operands):
        return rows[name].get(address, ())[:2] == (mnemonic, operands)

    def at(name, address, mnemonic, operands):
        checks[hex(address)] = instruction(name, address, mnemonic, operands)

    at(PARENT + 'InitialiseSubForms', 0x1132c2b, 'mov', 'dword ptr [eax + 0x40], 0x1132fc4')
    at(PARENT + 'InitialiseSubForms', 0x1132c3e, 'mov', 'dword ptr [eax + 0x38], 0x1132ff8')
    at(PARENT + 'HandleBeforeLoadTemplate', 0x1132fd8, 'mov', 'byte ptr [eax + 0x1e0], 1')
    at(PARENT + 'HandleLoadTemplate', 0x113301c, 'mov', 'byte ptr [eax + 0x1e0], 0')
    for address, operands in ((0x111d32b, 'dword ptr [ebx + 0x40]'),
                              (0x111d39a, 'dword ptr [ebx + 0x88]'),
                              (0x111d461, '0xfe3a7c'),
                              (0x111d4fa, 'dword ptr [ebx + 0x38]')):
        at(CHILD + 'HandleBtnLoadClick', address, 'call', operands)
    at(AGENT + 'AfterLoadProgrammingInformation', 0x128f64d, 'cmp', 'byte ptr [eax + 0x1e0], 0')
    at(AGENT + 'AfterLoadProgrammingInformation', 0x128f654, 'jne', '0x128f7ae')
    skipped = [note for a, m, _op, note in methods[AGENT + 'AfterLoadProgrammingInformation'][0]
               if 0x128f65a <= a < 0x128f7ae and m == 'call']
    checks['template_skips_exactly_five_relay_loads'] = (
        skipped.count(MANAGER + 'GroupByAddress') == 5
        and [name for name in skipped if 'SetInternalRelay' in name]
        == [PLANT + f'SetInternalRelay{n}Group' for n in range(1, 6)])
    loaded = methods[AGENT + 'AfterLoadProgrammingInformation'][0]
    output_calls = [j for j, (_a, m, _op, note) in enumerate(loaded)
                    if m == 'call' and 'GetDefault' in note and 'OutputGroupForPlantType' in note]
    checks['afterload_disables_all_fourteen_group_new_overrides'] = (
        len(output_calls) == 14 and all(loaded[j - 2][1:3] == ('xor', 'ecx, ecx')
                                      and loaded[j - 1][1:3] == ('pop', 'edx') for j in output_calls))
    update, update_digest, _ = _case_table(walker, PLANT + 'UpdateParametersForPlantType', _assignments)
    normalized = _normal_update(update)
    relay_assignments = {
        str(plant): {name or '<default>': [attribute for attribute, _value in actions
                                          if attribute.startswith('InternalRelay')]
                    for name, actions in branches.items()}
        for plant, branches in normalized.items()}
    checks['every_plant_branch_assigns_all_five_relays'] = all(
        names == [f'InternalRelay{n}' for n in range(1, 6)]
        for branches in relay_assignments.values() for names in branches.values())

    at(PLANT + 'CreateAndRenameGroup', 0xfe2865, 'cmp', 'byte ptr [eax + 0x1e0], 0')
    at(PLANT + 'CreateAndRenameGroup', 0xfe286c, 'je', '0xfe28a8')
    at(PLANT + 'CreateAndRenameGroup', 0xfe288a, 'call', '0xfe2afc')
    at(PLANT + 'CreateAndRenameGroup', 0xfe289a, 'jne', '0xfe29ee')
    at(PLANT + 'CreateAndRenameGroup', 0xfe29e9, 'call', '0xf47880')
    at(PLANT + 'GetGroup', 0xfe3491, 'call', '0xfe2f3c')
    new = 'CIS_TThermostat.GetNewGroup'
    checks['correct_overload_selected'] = image.by_name[new] == 0xfe2f3c
    for address, mnemonic, operands in (
        (0xfe2fa8, 'dec', 'eax'), (0xfe2fd2, 'call', '0xf28954'),
        (0xfe3001, 'call', '0x6094d4'), (0xfe3007, 'jne', '0xfe3127'),
        (0xfe3015, 'inc', 'eax'), (0xfe3016, 'cmp', 'eax, 0xfe'),
        (0xfe3043, 'call', '0xf28b68'), (0xfe304a, 'jne', '0xfe3111'),
        (0xfe3111, 'inc', 'dword ptr [ebp - 0xc]'),
        (0xfe3114, 'cmp', 'dword ptr [ebp - 0xc], 0xff'),
        (0xfe3127, 'dec', 'dword ptr [ebp - 8]'),
        (0xfe3158, 'call', '0xf289fc')):
        at(new, address, mnemonic, operands)
    for address, mnemonic, operands in (
        (0xf28a1b, 'xor', 'eax, eax'), (0xf28a28, 'call', '0xf28ae4'),
        (0xf28a38, 'inc', 'dword ptr [ebp - 0xc]'), (0xf28a44, 'call', '0xf28a58')):
        at(MANAGER + 'GetNextAvailableAddress', address, mnemonic, operands)
    at(MANAGER + 'GetMaximumPossibleAddress', 0xf28a69, 'call', '0xf261dc')
    at(MANAGER + 'GetMaximumPossibleAddress', 0xf28a72, 'mov', 'dword ptr [ebp - 8], 0xfe')
    at('CIS_TCommonCBus.TCBUSApplication.GetHasReservedGroupAddress255',
       0xf261e5, 'mov', 'byte ptr [ebp - 5], 1')
    at(MANAGER + 'GroupByAddress', 0xf28c32, 'call', '0x85b2c4')
    at(MANAGER + 'GroupByAddress', 0xf28c58, 'call', '0x61b6e8')
    checks['default_group_format'] = image.literal(0xf28ce4) == '%s %d'
    checks['default_group_name'] = image.resource(walker.dword(0x13c1d14)) == 'Group'
    # Initialization registers an application, then overrides its singular
    # group name. Other registrations retain Create's Group resource string.
    names, app, resource = {}, None, None
    for _a, m, op, note in methods[STANDARD + 'CIS_TStandardCBusApplications'][0]:
        match = re.fullmatch(r'edx, (0x[0-9a-f]+)', op)
        if m == 'mov' and match:
            app = int(match[1], 16)
        if note.startswith('RES:'):
            resource = note[4:]
        if m == 'call' and note == STANDARD + 'TStandardCBusApplication.SetGroupName':
            names[app] = resource
    checks['default_group_name_overrides'] = names == {
        172: 'Communication Group', 192: 'Media Link Group',
        202: 'Trigger Group', 203: 'Enable Network Variable'}
    failures = sorted(name for name, ok in checks.items() if not ok)
    if failures:
        raise ValueError('Original thermostat group contract differs: ' + ', '.join(failures))
    if (_sha(exe.read_bytes()), _sha(map_path.read_bytes())) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original files changed during inspection')
    return {
        'format': 'cbus-toolkit-thermostat-group-allocation-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False,
        'method_spans': {name: {'start': hex(image.by_name[name]),
                                'end': hex(next(a for a in image.starts if a > image.by_name[name])),
                                'sha256': data[2]} for name, data in methods.items()},
        'update_parameters_sha256': update_digest,
        'checks': {name: True for name in sorted(checks)},
        'relay_assignments_by_plant_branch': relay_assignments,
        'template_phase': {
            'load_template_flag_offset': '0x1e0',
            'set_before_pp_load': True, 'cleared_after_plant_update': True,
            'relay_afterload_skipped': True, 'all_five_relays_assigned_by_plant_update': True,
            'afterload_group_new_override': False,
            'implemented_slice': 'Skip unreachable relay AfterLoad reads, creations and refusals.'},
        'recovered_not_implemented': {
            'create_and_rename': 'While the template flag is true, prefer an existing autogenerated '
                                 'tag before retaining/renaming the supplied-address group.',
            'get_new_group': 'First reuse exact autogenerated tag (case-insensitive). Otherwise walk '
                             'the group-manager collection in reverse. For each same-prefix group, '
                             'take first free address above it through 254. If none succeeds, take '
                             'the lowest free address from 0 through 254; fail when full.',
            'find_existing_group': 'First case-insensitive tag match in forward manager order.',
            'relay_default_name': {'fallback': 'Group', 'overrides': names, 'format': '%s %d',
                                   'applicable_phase': 'Ordinary AfterLoad only, not Load Template.'}},
        'remaining_boundaries': [
            'GetNewGroup and duplicate tag resolution need original manager order; DBGETXML order '
            'is not asserted to equal that order.',
            'An order-independent allocator slice is possible only if all eligible prefix starting '
            'points produce the same first-free candidate, or none produces one before fallback.',
            'Fresh installation 9 remains refused: stale relay loading is skipped, but W2 requests '
            'default group 5 already used by Y. Prefix groups 5,3,6,2 allow candidates 7,4,7,4.',
            'Existing-prefix rename/reuse composition and general ordinary AfterLoad group side '
            'effects remain unreplayed; no original GUI or physical thermostat was executed.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
