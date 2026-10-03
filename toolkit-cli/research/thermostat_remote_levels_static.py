"""Check optional thermostat remote Level creation without executing originals.

The pinned EXE/MAP are static inputs only. The output includes hashes, method
bounds, checked branches and semantic facts, never vendor instruction bytes
or private paths. This extends the remote-reference source receipt with the
accepted or declined optional parent-prompt branches.
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


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inspect(exe: Path, map_path: Path) -> dict:
    original, map_raw = exe.read_bytes(), map_path.read_bytes()
    if (_sha(original), _sha(map_raw)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Pinned original EXE/MAP hashes differ')
    image = _Image(original, map_raw)
    walker = _Walker(image)
    T = 'CIS_TThermostat.'
    S = 'CIS_TcdThermostatScheduling.TcdThermostatScheduling.'
    C = 'CIS_TCommonCBus.'
    P = 'CIS_TddThermostat.'
    method_names = [
        T+'TThermostat.RemoteSetbackLevelsRequired',
        T+'TThermostat.CreateRemoteSetbackLevels', T+'TThermostat.CreateLevels',
        T+'TProgrammableThermostat.RemoteScheduleLevelsRequired',
        T+'ZoneLevelsExist', T+'LevelToZones',
        S+'CreateRemoteScheduleLevels', S+'CreateRemoteScheduleEnableLevels',
        S+'CreateRemoteScheduleDisableLevels', S+'CreateRemoteScheduleOverrideLevels',
        S+'CreateLevels', C+'TLevelManager.FindLevelByAddress', C+'TLevelManager.Add',
        C+'TLevel.SetValue', C+'TLevel.InternalCreate', C+'TCBusGroup.IsUnused',
        C+'TProject.BeginSaveLock', C+'TProject.EndSaveLock',
        P+'TddThermostat.ValidateProgramming', P+'TddProgrammableThermostat.ValidateProgramming',
        'CIS_TLevelCGateAgent.TLevelCGateAgent.AgentSave',
    ]
    methods = {}
    for name in method_names:
        rows, _, digest = walker.listing(name)
        start = image.by_name[name]
        methods[name] = {'address': hex(start), 'end': hex(next(a for a in image.starts if a > start)),
                         'sha256': digest, 'rows': rows}
    checks = {}
    def at(name, entries):
        rows = {a: (m, op) for a, m, op, _ in methods[name]['rows']}
        for address, mnemonic, operand in entries:
            checks[hex(address)] = rows.get(address) == (mnemonic, operand)

    at(T+'TThermostat.CreateLevels', [
        (0xfeb175, 'call', '0xf2d370'), (0xfeb188, 'mov', 'dword ptr [ebp - 0x10], 1'),
        (0xfeb18f, 'push', '0'), (0xfeb19a, 'xor', 'ecx, ecx'),
        (0xfeb19f, 'call', '0xf2742c'), (0xfeb1ab, 'jne', '0xfeb215'),
        (0xfeb1ad, 'push', '0'), (0xfeb1b8, 'mov', 'cl, 1'),
        (0xfeb1bd, 'call', '0xf2742c'), (0xfeb1c5, 'push', '0xfeb2fc'),
        (0xfeb1d8, 'call', '0xfda610'), (0xfeb20e, 'call', 'dword ptr [edx + 0x7c]'),
        (0xfeb218, 'cmp', 'dword ptr [ebp - 0x10], 0x20'),
        (0xfeb226, 'je', '0xfeb24c'), (0xfeb246, 'call', 'dword ptr [ebx + 0x80]'),
        (0xfeb274, 'call', '0xf2d384')])
    at(T+'TThermostat.CreateRemoteSetbackLevels', [
        (0xfea8ab, 'call', '0xfdeac0'), (0xfea8b2, 'je', '0xfea8e6'),
        (0xfea8c1, 'call', '0xf27e14'), (0xfea8c8, 'jne', '0xfea8e6'),
        (0xfea8d9, 'mov', 'ecx, 0xfea938'), (0xfea8e1, 'call', '0xfeb130'),
        (0xfea8ee, 'call', '0xfdea9c'), (0xfea8f5, 'je', '0xfea929'),
        (0xfea904, 'call', '0xf27e14'), (0xfea90b, 'jne', '0xfea929'),
        (0xfea91c, 'mov', 'ecx, 0xfea954'), (0xfea924, 'call', '0xfeb130')])
    at(T+'ZoneLevelsExist', [
        (0xfda7cb, 'mov', 'dword ptr [ebp - 0xc], 1'),
        (0xfda7d4, 'xor', 'ecx, ecx'), (0xfda7e2, 'call', '0xf2742c'),
        (0xfda7e9, 'je', '0xfda7f8'), (0xfda7ee, 'cmp', 'dword ptr [ebp - 0xc], 0x20')])
    at(C+'TCBusGroup.IsUnused', [(0xf27e25, 'cmp', 'eax, 0xff')])
    at(C+'TLevelManager.FindLevelByAddress', [
        (0xf27492, 'call', '0xf47a10'), (0xf27497, 'cmp', 'eax, dword ptr [ebp - 8]'),
        (0xf274aa, 'jmp', '0xf275ba'), (0xf274c5, 'je', '0xf275ba'),
        (0xf274ce, 'call', '0xf2724c'), (0xf274dc, 'call', '0xf47d64'),
        (0xf274e7, 'call', '0xf26e44'), (0xf274f0, 'je', '0xf2753c'),
        (0xf27540, 'mov', 'eax, 0xf2764c'),
        (0xf27589, 'call', 'dword ptr [edx + 0x7c]'),
        (0xf275b4, 'call', 'dword ptr [ebx + 0x80]')])
    at(S+'CreateLevels', [
        (0x113098c, 'call', '0xf2d370'),
        (0x113099f, 'mov', 'dword ptr [ebp - 0x10], 1'),
        (0x11309b6, 'call', '0xf2742c'), (0x11309c2, 'jne', '0x1130a2c'),
        (0x11309d4, 'call', '0xf2742c'), (0x11309dc, 'push', '0x1130b18'),
        (0x11309ef, 'call', '0xfda610'),
        (0x1130a2f, 'cmp', 'dword ptr [ebp - 0x10], 0x20'),
        (0x1130a91, 'call', '0xf2d384')])
    at(S+'CreateRemoteScheduleLevels', [
        (0x113077f, 'call', '0xfe0040'), (0x1130798, 'call', '0xf27e14'),
        (0x11307a4, 'call', '0x113086c'), (0x11307b4, 'call', '0xfe001c'),
        (0x11307cd, 'call', '0xf27e14'), (0x11307d9, 'call', '0x11308b4'),
        (0x11307e9, 'call', '0xfdfff8'), (0x1130802, 'call', '0xf27e14'),
        (0x113080e, 'call', '0x11308fc')])
    at(P+'TddThermostat.ValidateProgramming', [
        (0x113250e, 'je', '0x1132642'), (0x1132528, 'jle', '0x1132642'),
        (0x1132536, 'call', '0xfecbcc'), (0x113253d, 'je', '0x1132642'),
        (0x1132551, 'mov', 'edx, 0xa80'), (0x1132556, 'call', '0x7d9d00'),
        (0x113255b, 'dec', 'eax'), (0x113255c, 'jne', '0x1132642'),
        (0x11325d0, 'call', '0xfea89c'), (0x1132633, 'mov', 'edx, 0x4e82')])
    at(P+'TddProgrammableThermostat.ValidateProgramming', [
        (0x11334cc, 'call', '0x11320c0'), (0x11334d8, 'je', '0x113361e'),
        (0x11334e1, 'call', '0x1133350'), (0x1133532, 'call', '0x11333b4'),
        (0x1133583, 'call', '0x1133434'), (0x11335db, 'call', '0xfdffd4'),
        (0x11335e2, 'je', '0x113361e'), (0x11335ec, 'call', '0xfed2d4'),
        (0x11335f3, 'je', '0x113361e'), (0x1133603, 'mov', 'edx, 0xa7f'),
        (0x1133608, 'call', '0x7d9d00'), (0x113360d, 'dec', 'eax'),
        (0x113360e, 'jne', '0x113361e'), (0x1133619, 'call', '0x1130704')])
    literals = {
        0xfea938:'Enable', 0xfea954:'Disable', 0xfeb2fc:'Setbk ', 0xfeb318:' ',
        0xfeb328:'ProjectSave', 0x1130b18:'Sched ', 0x1130b34:' ', 0x1130b44:'ProjectSave',
        0x11308a4:'Enable', 0x11308ec:'Disable', 0x1130934:'Overrd',
        0xf27608:'Action Selector', 0xf27634:'%s %d', 0xf2764c:'Level',
        0xf27664:'ProjectSave', 0xfda714:'Zone:', 0xfda72c:'Zones:',
        0xfda748:'unsw,', 0xfda760:'1,', 0xfda774:'2,', 0xfda788:'3,', 0xfda79c:'4,',
        0x1213be4:'Level', 0x1213bfc:'Address', 0x1213c18:'TagsDLT', 0x1213c6c:'Value',
    }
    for address, expected in literals.items():
        checks['literal@'+hex(address)] = image.literal(address) == expected

    at(T+'TThermostat.RemoteSetbackLevelsRequired', [
        (0xfecbe1, 'call', '0xfdea78'), (0xfecbe8, 'je', '0xfecc70'),
        (0xfecc22, 'call', '0xfda7a4'), (0xfecc30, 'jne', '0xfecc70'),
        (0xfecc66, 'call', '0xfda7a4')])
    at(T+'TProgrammableThermostat.RemoteScheduleLevelsRequired', [
        (0xfed2e9, 'call', '0xfdffd4'), (0xfed2f0, 'je', '0xfed3bc'),
        (0xfed32a, 'call', '0xfda7a4'), (0xfed338, 'jne', '0xfed378'),
        (0xfed36e, 'call', '0xfda7a4'), (0xfed37c, 'jne', '0xfed3bc'),
        (0xfed3b2, 'call', '0xfda7a4')])
    at(S+'CreateRemoteScheduleEnableLevels', [(0x1130885, 'mov', 'ecx, 0x11308a4')])
    at(S+'CreateRemoteScheduleDisableLevels', [(0x11308cd, 'mov', 'ecx, 0x11308ec')])
    at(S+'CreateRemoteScheduleOverrideLevels', [(0x1130915, 'mov', 'ecx, 0x1130934')])
    at(C+'TProject.BeginSaveLock', [(0xf2d37a, 'inc', 'dword ptr [eax + 0xc8]')])
    at(C+'TProject.EndSaveLock', [
        (0xf2d3b1, 'dec', 'dword ptr [eax + 0xc8]'), (0xf2d3c1, 'jne', '0xf2d3f1'),
        (0xf2d3cd, 'je', '0xf2d3f1'), (0xf2d3e1, 'call', 'dword ptr [ebx + 0x80]')])
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError('Remote Level source differs: ' + ', '.join(failures))
    if (_sha(exe.read_bytes()), _sha(map_path.read_bytes())) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original inputs changed during inspection')
    return {
        'format': 'cbus-thermostat-remote-levels-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False, 'physical_io': False,
        'checks': {name: True for name in sorted(checks)},
        'method_spans': {name: {key: value for key, value in item.items() if key != 'rows'}
                         for name, item in sorted(methods.items())},
        'contract': {
            'parent_order': ['base validation', 'optional setback levels', 'remaining base validation',
                             'derived schedule validation', 'optional schedule levels'],
            'setback_prompt': {'dialog_id': 2688, 'source_gate': 'positive remote setback source',
                               'required_gate': 'first nonunused role lacking any address1..31',
                               'accepted_result': 1, 'declined_result': 'any other result'},
            'schedule_prompt': {'dialog_id': 2687, 'source_gate': 'derived remote schedule enable',
                                'required_gate': 'first nonunused role lacking any address1..31',
                                'accepted_result': 1, 'declined_result': 'any other result'},
            'decline_effect': 'skip optional additions; preserve current validation result',
            'level_role_order': ['setback_on', 'setback_off', 'schedule_on', 'schedule_off', 'schedule_override'],
            'role_labels': ['Setbk Enable', 'Setbk Disable', 'Sched Enable', 'Sched Disable', 'Sched Overrd'],
            'level_addresses': list(range(1, 32)), 'created_value': 'equal to Address',
            'level_tag': 'role label + one space + LevelToZones(Address)',
            'zone_bits': {'1': 'unsw', '2': '1', '4': '2', '8': '3', '16': '4'},
            'zone_tag_examples': {'1': 'Zone:unsw', '2': 'Zone:1', '3': 'Zones:unsw,1',
                                  '31': 'Zones:unsw,1,2,3,4'},
            'present_address': 'return same first matching object without changing Value, tag, order or metadata',
            'absent_address_order': ['Add', 'Address=N', 'Value=N', 'TagName=Level N',
                                     'level StorageSave', 'project save request',
                                     'TagName=final role and zones label', 'level StorageSave'],
            'role_save_lock': 'BeginSaveLock before loop; project request if additions; EndSaveLock after loop',
            'group255': 'skip predicates and creation; preserve all stored metadata and existing levels',
            'group0': 'real actionable group',
            'source1_lighting': 'same Level helpers and labels as source2; use resolved ApplicationNumber identity',
            'basic_family': 'setback only; programmable schedule prompt absent',
            'full_preflight': 'owned transaction policy; does not reproduce original invalid-form partial mutations',
            'one_owning_save': 'owned storage projection; never compose native scheduling apply with settings apply',
        },
        'limits': [
            'Composes the existing source-pinned raw candidate load/save and scoped remote validation.',
            'No complete original parent validation, GUI prompt display, control binding or callbacks are claimed.',
            'Original base prompt may create levels before later base or derived validation fails.',
            'Original level and project StorageSave requests are not atomic native wire acceptance.',
            'Owned materialization and failure handling must retain separate PP and target-project save boundaries.',
            'Delphi exception unwinding and original error-dialog recovery are not reproduced.',
            'Original native Level agent can create TagsDLT; XML spelling/empty normalization is a separate backend contract.',
            'Rows beyond returns can include inline data; only checked reachable instructions support semantic claims.',
            'No original instructions, emulator, GUI, native endpoint or hardware executed by this reproducer.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
