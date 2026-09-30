"""Pin the thermostat's disabled remote-control PP save projection.

This reads the original EXE/MAP. It does not execute vendor instructions or
claim that a complete form, group graph, or GUI event lifecycle was replayed.
The independent byte-domain examples below project the checked source branches;
they never import the production thermostat implementation.
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
from thermostat_settings_temperature_static import _attribute_definitions  # noqa: E402

AGENT = 'CIS_TCBusThermostatCGateAgent.'
BASE = AGENT + 'TCBusThermostatCGateAgent.'
PROGRAMMABLE = AGENT + 'TCBusProgrammableThermostatCGateAgent.'
MODEL = 'CIS_TThermostat.'
ZONE = MODEL + 'TZoneManagerService.'
UI = MODEL + 'TAdvancedUIService.'
INTEGER = 'CIS_TIntegerAttribute.TIntegerAttribute.'
LOAD = 'AfterLoadProgrammingInformation'
SAVE = 'BeforeSaveProgrammingInformation'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inspect(exe: Path, map_path: Path) -> dict:
    exe_raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    if (_sha(exe_raw), _sha(map_raw)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Image(exe_raw, map_raw)
    walker = _Walker(image)
    methods, checks = {}, {}

    def method(name):
        if name not in methods:
            methods[name] = walker.listing(name)
        return methods[name][0]

    def markers(name, entries):
        rows = {a: (m, op) for a, m, op, _n in method(name)}
        for address, mnemonic, operands in entries:
            checks[hex(address)] = rows.get(address) == (mnemonic, operands)

    definitions = {}
    for prefix in (BASE, PROGRAMMABLE, ZONE):
        definitions[prefix] = _attribute_definitions(image, method(prefix + 'InternalCreate'))
    slots = {'RemoteSetbackControlSource': 0x150, 'RemoteSetbackOnGroup': 0x154,
             'RemoteSetbackOffGroup': 0x158, 'RemoteScheduleOnGroup': 0x170,
             'RemoteScheduleOffGroup': 0x174, 'RemoteScheduleOverrideGroup': 0x178,
             'RemoteScheduleEnable': 0x17c, 'EvapProgramEnabled': 0x2a8,
             'NonEvapProgramEnabled': 0x2ac}
    for field, slot in slots.items():
        owner = PROGRAMMABLE if field in ('EvapProgramEnabled', 'NonEvapProgramEnabled') else BASE
        definition = definitions[owner][field]
        checks[field + '_pp_attribute'] = (
            definition['slot'] == slot
            and definition['class'] == 'CIS_TCGateAttribute..TIntegerCGateAttribute')
    checks['source_model_plain_integer'] = definitions[ZONE]['RemoteSetbackControlSource'] == {
        'slot': 0xc8, 'class': 'CIS_TIntegerAttribute..TIntegerAttribute', 'create': 0xfdd61a}
    checks['schedule_model_boolean'] = definitions[ZONE]['RemoteScheduleEnable']['class'] == (
        'CIS_TBooleanAttribute..TBooleanAttribute')
    markers(ZONE + 'SetRemoteSetbackControlSource', (
        (0xfdfe2f, 'call', '0x62f294'),
        (0xfdfe3a, 'mov', 'eax, dword ptr [eax + 0xc8]'),
        (0xfdfe42, 'call', 'dword ptr [ecx + 0x7c]')))
    markers(ZONE + 'GetRemoteSetbackControlSource', (
        (0xfdea84, 'mov', 'eax, dword ptr [eax + 0xc8]'),))
    for suffix in ('InternalCreate', 'AfterConstruction', 'HookEvents'):
        rows = method(ZONE + suffix)
        checks['source_no_bounds_or_beforechange_' + suffix] = not any(
            '.SetMin' in note or '.SetMax' in note
            or ('0xc8]' in op and suffix != 'InternalCreate')
            for _a, _m, op, note in rows)
    vmt = walker.dword(0x850574)
    checks['model_integer_vmt_value_setter'] = walker.dword(vmt + 0x7c) == image.by_name[INTEGER + 'SetValue']
    checks['model_integer_vmt_integer_setter'] = walker.dword(vmt + 0xa4) == image.by_name[INTEGER + 'SetAsInteger']
    markers(INTEGER + 'SetValue', ((0x850adf, 'call', 'dword ptr [ecx + 0xa4]'),))
    markers(INTEGER + 'SetAsInteger', (
        (0x850943, 'cmp', 'eax, dword ptr [edx + 0x54]'),
        (0x850946, 'je', '0x8509c3'),
        (0x8509de, 'mov', 'dword ptr [eax + 0x70], edx')))
    method(INTEGER + 'InternalCreate')

    markers(BASE + LOAD, (
        (0x128e90b, 'mov', 'eax, dword ptr [eax + 0x150]'),
        (0x128e928, 'call', '0xfdfe08'),
        (0x128e93f, 'cmp', 'eax, 2'), (0x128e942, 'jne', '0x128e9d9'),
        (0x128e967, 'call', '0xf2b134'), (0x128e972, 'mov', 'cl, 1'),
        (0x128e975, 'call', '0xf28b68'), (0x128e9ad, 'call', '0xf2b134'),
        (0x128e9b8, 'mov', 'cl, 1'), (0x128e9bb, 'call', '0xf28b68'),
        (0x128e9eb, 'dec', 'eax'), (0x128e9ec, 'jne', '0x128ea7c'),
        (0x128ea0e, 'call', 'dword ptr [edx + 0xb0]'),
        (0x128ea1a, 'mov', 'cl, 1'), (0x128ea1d, 'call', '0xf28b68'),
        (0x128ea52, 'call', 'dword ptr [edx + 0xb0]'),
        (0x128ea5e, 'mov', 'cl, 1'), (0x128ea61, 'call', '0xf28b68'),
        (0x128ea89, 'xor', 'edx, edx'), (0x128ea8b, 'call', '0xfdfe8c'),
        (0x128ea9d, 'xor', 'edx, edx'), (0x128ea9f, 'call', '0xfdfe68')))
    markers(BASE + SAVE, (
        (0x1294d61, 'mov', 'eax, dword ptr [eax + 0x150]'),
        (0x1294d7e, 'test', 'eax, eax'), (0x1294d80, 'jle', '0x1294df8'),
        (0x1294d8f, 'call', '0xfdeac0'), (0x1294d94, 'call', '0xf47a10'),
        (0x1294dc9, 'call', '0xfdea9c'), (0x1294dce, 'call', '0xf47a10'),
        (0x1294dfe, 'mov', 'edx, 0x1e'),
        (0x1294e13, 'mov', 'eax, dword ptr [eax + 0x154]'),
        (0x1294e1b, 'call', 'dword ptr [ecx + 0x7c]'),
        (0x1294e24, 'mov', 'edx, 0x1f'),
        (0x1294e39, 'mov', 'eax, dword ptr [eax + 0x158]'),
        (0x1294e41, 'call', 'dword ptr [ecx + 0x7c]')))
    address_getter = 'CIS_TCBusObject.TCGateObject.GetAddressAsInteger'
    markers(address_getter, ((0xf47a1c, 'mov', 'eax, dword ptr [eax + 0x80]'),))
    checks['address_getter_has_no_nil_guard'] = not any(
        m in ('test', 'cmp') for _a, m, _op, _n in method(address_getter))

    markers(PROGRAMMABLE + LOAD, (
        (0x129978c, 'mov', 'eax, dword ptr [eax + 0x2a8]'),
        (0x129979a, 'dec', 'eax'), (0x129979b, 'jle', '0x12997ba'),
        (0x12997a0, 'xor', 'edx, edx'),
        (0x12997af, 'mov', 'eax, dword ptr [eax + 0x2a8]'),
        (0x12997bd, 'mov', 'eax, dword ptr [eax + 0x2ac]'),
        (0x12997cb, 'dec', 'eax'), (0x12997cc, 'jle', '0x12997ee'),
        (0x12997d1, 'mov', 'edx, 1'),
        (0x12997e3, 'mov', 'eax, dword ptr [eax + 0x2ac]'),
        (0x1299877, 'setg', 'al'), (0x1299889, 'call', '0xfdd1e8'),
        (0x12998a1, 'setg', 'al'), (0x12998b3, 'call', '0xfdd244'),
        (0x12998c5, 'call', '0xfdd1a0'), (0x12998cc, 'jne', '0x12998e8'),
        (0x12998db, 'call', '0xfdd1c4'), (0x12998e2, 'jne', '0x12998e8'),
        (0x12998e4, 'xor', 'eax, eax'), (0x12998e8, 'mov', 'al, 1'),
        (0x12998f9, 'call', '0xfe0064'), (0x1299912, 'je', '0x12999ef'),
        (0x1299937, 'call', '0xf2b134'), (0x1299942, 'mov', 'cl, 1'),
        (0x1299945, 'call', '0xf28b68'), (0x1299988, 'mov', 'cl, 1'),
        (0x129998b, 'call', '0xf28b68'), (0x12999ce, 'mov', 'cl, 1'),
        (0x12999d1, 'call', '0xf28b68'),
        (0x1299a07, 'xor', 'ecx, ecx'), (0x1299a09, 'mov', 'edx, 0xff'),
        (0x1299a0e, 'call', '0xf28b68'),
        (0x1299a3f, 'xor', 'ecx, ecx'), (0x1299a41, 'mov', 'edx, 0xff'),
        (0x1299a46, 'call', '0xf28b68'),
        (0x1299a77, 'xor', 'ecx, ecx'), (0x1299a79, 'mov', 'edx, 0xff'),
        (0x1299a7e, 'call', '0xf28b68'),
        (0x129953a, 'call', 'dword ptr [edx + 0x80]'),
        (0x1299abe, 'call', 'dword ptr [edx + 0x7c]')))
    checks['load_never_reads_raw_remote_schedule_enable'] = not any(
        '[eax + 0x17c]' in op for _a, _m, op, _n in method(PROGRAMMABLE + LOAD))
    ui_vmt = 0xfd8d38
    checks['advanced_ui_load_unhooks_program_flag_handlers'] = (
        walker.dword(ui_vmt + 0x80) == image.by_name[UI + 'UnhookEvents'])
    checks['advanced_ui_final_call_only_rehooks_handlers'] = (
        walker.dword(ui_vmt + 0x7c) == image.by_name[UI + 'HookEvents'])
    for name in ('HookEvents', 'UnhookEvents'):
        checks['advanced_ui_' + name + '_no_calls'] = not any(
            m == 'call' for _a, m, _op, _n in method(UI + name))
    method(UI + 'HandleEvapProgramEnabledAfterChange')
    method(MODEL + 'TProgrammableThermostat.AfterConstruction')
    handler = method(MODEL + 'TProgrammableThermostat.HandleEvapProgramEnableChange')
    checks['intrinsic_program_flag_handler_only_sets_remote_enable'] = {
        note for _a, m, _op, note in handler if m == 'call' and '.Set' in note
    } == {ZONE + 'SetRemoteScheduleEnable'}
    markers(PROGRAMMABLE + SAVE, (
        (0x1299fb7, 'call', '0xfdffd4'), (0x1299fbe, 'jne', '0x1299ff0'),
        (0x1299fcd, 'call', '0xfdd1a0'), (0x1299fd4, 'jne', '0x1299ff0'),
        (0x1299fe3, 'call', '0xfdd1c4'), (0x1299fea, 'je', '0x129a0c9'),
        (0x1299ff6, 'mov', 'edx, 1'),
        (0x129a00b, 'mov', 'eax, dword ptr [eax + 0x17c]'),
        (0x129a028, 'call', '0xf47a10'), (0x129a062, 'call', '0xf47a10'),
        (0x129a09c, 'call', '0xf47a10'),
        (0x129a0cf, 'xor', 'edx, edx'),
        (0x129a0e1, 'mov', 'eax, dword ptr [eax + 0x17c]'),
        (0x129a0f2, 'mov', 'edx, 0x20'),
        (0x129a107, 'mov', 'eax, dword ptr [eax + 0x170]'),
        (0x129a10f, 'call', 'dword ptr [ecx + 0x7c]'),
        (0x129a118, 'mov', 'edx, 0x21'),
        (0x129a12d, 'mov', 'eax, dword ptr [eax + 0x174]'),
        (0x129a135, 'call', 'dword ptr [ecx + 0x7c]'),
        (0x129a13e, 'mov', 'edx, 0x22'),
        (0x129a153, 'mov', 'eax, dword ptr [eax + 0x178]'),
        (0x129a15b, 'call', 'dword ptr [ecx + 0x7c]')))
    if failed := [name for name, ok in checks.items() if not ok]:
        raise ValueError('Remote save source checks failed: ' + ', '.join(failed))
    if (_sha(exe.read_bytes()), _sha(map_path.read_bytes())) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original source changed during inspection')
    return {
        'format': 'cbus-thermostat-remote-save-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed_this_run': False, 'physical_devices_accessed': False,
        'production_implementation_used': False,
        'checks': dict(sorted(checks.items())),
        'routines': {name: {'address': hex(image.by_name[name]), 'sha256': data[2]}
                     for name, data in sorted(methods.items())},
        'pp_attribute_slots': {field: hex(slot) for field, slot in slots.items()},
        'remote_setback_byte_domains': [
            {'raw': 0, 'load_group_references': None, 'save_groups': [30, 31],
             'dependent_pp_writes_need_group_inventory': False},
            {'raw': 1, 'load_application': 'unit.ApplicationObject from ApplicationNumber',
             'load_group_create': True, 'save_groups': 'loaded object addresses'},
            {'raw': 2, 'load_application': 203, 'load_group_create': True,
             'save_groups': 'loaded object addresses'},
            {'raw_range': [3, 255], 'load_group_references': None,
             'save_groups': 'dereferences nil; no safe original fresh-save projection'}],
        'schedule_flag_byte_domains': {
            'EvapProgramEnabled': 'raw == 1', 'NonEvapProgramEnabled': 'raw > 0',
            'RemoteScheduleEnable': 'raw ignored; model = normalized Evap OR NonEvap',
            'before_save_enable': 'model RemoteScheduleEnable OR Evap OR NonEvap',
            'disabled_group_load': {'application': 203, 'address': 255, 'create': False},
            'disabled_pp_save': {'RemoteScheduleEnable': 0, 'RemoteScheduleOnGroup': 32,
                                 'RemoteScheduleOffGroup': 33, 'RemoteScheduleOverrideGroup': 34},
            'enabled_group_load': {'application': 203, 'addresses': 'PP group values', 'create': True},
            'enabled_pp_save': 'RemoteScheduleEnable=1; groups use loaded object addresses'},
        'independent_source_branch_examples': [
            {'raw_flags': [evap, non_evap], 'raw_remote_enable': raw_enable,
             'loaded_flags': [int(evap == 1), int(non_evap > 0)],
             'saved_remote_enable': int(evap == 1 or non_evap > 0),
             'disabled_group_writes': [32, 33, 34] if evap != 1 and non_evap == 0 else None}
            for evap, non_evap, raw_enable in (
                (0, 0, 0), (0, 0, 1), (0, 0, 255), (2, 0, 255), (255, 0, 1),
                (1, 0, 0), (0, 1, 0), (0, 2, 0), (255, 255, 0))],
        'limits': [
            'Fresh scalar/model projection only; no intervening GUI edits or callbacks are simulated.',
            'AfterLoad detaches and reattaches the intrinsic program-flag handlers; the reattachment '
            'does not invoke them. Their handler only recomputes the same OR. The final '
            'RemoteSchedule attribute Changed call can notify subscribers, whose arbitrary effects '
            'are not covered by this static projection.',
            'The disabled branches overwrite untouched group PP bytes with decimal30/31 or32/33/34, '
            'not255. These branch outputs do not dereference group objects.',
            'Enabled address preservation is conditional on successful original application/group '
            'resolution; the load may create missing objects. No inventory-free complete load is claimed.',
            'RemoteSetbackControlSource is a plain integer with no branch clamp to0..2. '
            'Raw3..255 takes nil load references and a positive-source save dereference.',
            'Programmable disabled loading still calls GetEnableControlApplication and may create '
            'application203. PP-only projection does not reproduce those model side effects.',
            'Decoded unit specification prose labels sources1/2 oppositely to the pinned executable; '
            'the application routing recorded here follows executable branches.',
            'Original instruction execution, original form/dialog enable rules, native persistence, '
            'hardware behavior and full Toolkit parity remain outside this static receipt.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
