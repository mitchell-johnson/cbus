"""Check the native thermostat remote-reference source without executing it.

Inputs are the pinned original EXE/MAP. Output contains source hashes, method
bounds, checked branches and short semantic facts, never vendor instruction
bytes or local paths. This is the Delphi thermostat graph, not the managed
eDLT CBusLogicModel graph. No emulator, original process or endpoint is used.
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
from thermostat_post_load_static import _Walker  # noqa: E402

BASE = 'CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent.'
PROGRAM = 'CIS_TCBusThermostatCGateAgent.TCBusProgrammableThermostatCGateAgent.'
COMMON = 'CIS_TCommonCBus.'
APPS = COMMON + 'TCBUSApplicationManager.'
GROUPS = COMMON + 'TCBusGroupManager.'
NETWORK = COMMON + 'TCBusNetwork.'
APP = COMMON + 'TCBUSApplication.'
PARENT = 'CIS_TddThermostat.TddThermostat.'
PROGRAM_PARENT = 'CIS_TddThermostat.TddProgrammableThermostat.'
CATALOGUE = 'CIS_TStandardCBusApplications.'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inspect(exe: Path, map_path: Path, spec_dir: Path | None = None) -> dict:
    raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    if (_sha(raw), _sha(map_raw)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Pinned original EXE/MAP hashes differ')
    image = _Image(raw, map_raw)
    walker, methods, checks = _Walker(image), {}, {}

    def method(name, address=None):
        # Overloaded Delphi local functions share a MAP name. Bind the actual
        # call target, not whichever spelling the MAP parser indexed first.
        key = name if address is None else name + '@' + hex(address)
        if key not in methods:
            previous = image.by_name[name]
            if address is not None:
                image.by_name[name] = address
            try:
                rows, _tables, digest = walker.listing(name)
                start = image.by_name[name]
                methods[key] = (rows, {'start': hex(start), 'end': hex(next(
                    a for a in image.starts if a > start)), 'sha256': digest})
            finally:
                image.by_name[name] = previous
        return methods[key][0]

    def at(name, entries):
        rows = {a: (m, op) for a, m, op, _note in method(name)}
        for address, mnemonic, operand in entries:
            checks[hex(address)] = rows.get(address) == (mnemonic, operand)

    def calls(name, address=None):
        return [note for _a, m, _op, note in method(name, address) if m == 'call' and note]

    at(BASE + 'AfterLoadProgrammingInformation', (
        (0x128e4bc, 'mov', 'eax, dword ptr [eax + 0xf8]'),
        (0x128e4d9, 'call', '0xfdbb7c'),
        (0x128e515, 'mov', 'cl, 1'), (0x128e518, 'call', '0xf264fc'),
        (0x128e527, 'call', '0xf30014'),
        (0x128e93f, 'cmp', 'eax, 2'), (0x128e942, 'jne', '0x128e9d9'),
        (0x128e967, 'call', '0xf2b134'), (0x128e972, 'mov', 'cl, 1'),
        (0x128e975, 'call', '0xf28b68'), (0x128e9ad, 'call', '0xf2b134'),
        (0x128e9b8, 'mov', 'cl, 1'), (0x128e9bb, 'call', '0xf28b68'),
        (0x128e9eb, 'dec', 'eax'), (0x128e9ec, 'jne', '0x128ea7c'),
        (0x128ea0e, 'call', 'dword ptr [edx + 0xb0]'),
        (0x128ea1d, 'call', '0xf28b68'),
        (0x128ea52, 'call', 'dword ptr [edx + 0xb0]'),
        (0x128ea61, 'call', '0xf28b68'),
        (0x128ea89, 'xor', 'edx, edx'), (0x128ea8b, 'call', '0xfdfe8c'),
        (0x128ea9d, 'xor', 'edx, edx'), (0x128ea9f, 'call', '0xfdfe68')))
    at(PROGRAM + 'AfterLoadProgrammingInformation', (
        (0x12994f5, 'call', '0x128e06c'),
        (0x129979a, 'dec', 'eax'), (0x129979b, 'jle', '0x12997ba'),
        (0x12997a0, 'xor', 'edx, edx'),
        (0x12997cb, 'dec', 'eax'), (0x12997cc, 'jle', '0x12997ee'),
        (0x12998c5, 'call', '0xfdd1a0'), (0x12998db, 'call', '0xfdd1c4'),
        (0x12998f9, 'call', '0xfe0064'), (0x1299912, 'je', '0x12999ef'),
        (0x1299937, 'call', '0xf2b134'), (0x1299945, 'call', '0xf28b68'),
        (0x129997d, 'call', '0xf2b134'), (0x129998b, 'call', '0xf28b68'),
        (0x12999c3, 'call', '0xf2b134'), (0x12999d1, 'call', '0xf28b68'),
        (0x1299a07, 'xor', 'ecx, ecx'), (0x1299a0e, 'call', '0xf28b68'),
        (0x1299a3f, 'xor', 'ecx, ecx'), (0x1299a46, 'call', '0xf28b68'),
        (0x1299a77, 'xor', 'ecx, ecx'), (0x1299a7e, 'call', '0xf28b68')))
    checks['raw_schedule_enable_not_read_on_load'] = not any(
        '0x17c]' in op for _a, _m, op, _n in method(PROGRAM + 'AfterLoadProgrammingInformation'))
    at(NETWORK + 'GetEnableControlApplication', ((0xf2b13d, 'mov', 'edx, 0xcb'),))
    checks['enable_application_unconditional_check_then_find'] = calls(
        NETWORK + 'FindOrCreateApplicationByAddress') == [
            APPS + 'CheckAndCreate', APPS + 'FindApplicationByAddress']
    at(APPS + 'CheckAndCreate', ((0xf264c4, 'mov', 'cl, 1'),))
    at(APPS + 'FindApplicationByAddress', ((0xf264e4, 'xor', 'ecx, ecx'),))
    at(APPS + 'ApplicationByAddress', (
        (0xf2656f, 'call', '0xf26878'), (0xf265b6, 'call', '0xf26410'),
        (0xf2657b, 'jne', '0xf2661e'), (0xf26585, 'jne', '0xf2661e'),
        (0xf2658e, 'cmp', 'byte ptr [eax + 0x88], 0'),
        (0xf2659e, 'mov', 'byte ptr [eax + 0x88], 1'),
        (0xf265c4, 'call', '0xf47d64'), (0xf265d6, 'call', '0x85adc4'),
        (0xf265f4, 'call', 'dword ptr [ecx + 0x7c]'),
        (0xf265fc, 'call', 'dword ptr [edx + 0x7c]')))
    at(GROUPS + 'GroupByAddress', (
        (0xf28b9c, 'call', '0xf28d10'), (0xf28bce, 'call', '0xf288f0'),
        (0xf28ba8, 'jne', '0xf28c91'), (0xf28bb2, 'je', '0xf28c91'),
        (0xf28bc0, 'cmp', 'eax, 0x100'), (0xf28bc5, 'jge', '0xf28c91'),
        (0xf28bdc, 'call', '0xf47d64'), (0xf28c32, 'call', '0x85b2c4'),
        (0xf28c58, 'call', '0x61b6e8'),
        (0xf28c8b, 'call', 'dword ptr [ebx + 0x80]')))
    for name in (APPS + 'ApplicationByAddressExclude', APPS + 'Add', GROUPS + 'GroupByAddressExclude',
                 GROUPS + 'Add', APP + 'InternalCreate', GROUPS + 'Create',
                 'CIS_TCBusGroupCGateAgent.TCBusGroupCGateAgent.AgentSave'):
        method(name)
    checks['group_format'] = image.literal(0xf28ce4) == '%s %d'
    checks['group_save_verb'] = image.literal(0xf28cfc) == 'GroupSave'
    checks['unused_name'] = image.resource(walker.dword(0x13c1ca8)) == '<Unused>'
    checks['default_group_name'] = image.resource(walker.dword(0x13c1d14)) == 'Group'
    checks['group_command_kind'] = image.literal(0x1210fe8) == 'Group'
    at('CIS_TCBusGroupCGateAgent.TCBusGroupCGateAgent.CreateGroup', (
        (0x1210f84, 'mov', 'ecx, 0x1210fe8'), (0x1210f8c, 'call', '0xcac698')))

    names, app, resource = {}, None, None
    for _a, m, op, note in method(CATALOGUE + 'CIS_TStandardCBusApplications'):
        match = re.fullmatch(r'edx, (0x[0-9a-f]+)', op)
        if m == 'mov' and match:
            app = int(match[1], 16)
        if note.startswith('RES:'):
            resource = note[4:]
        if m == 'call' and note == CATALOGUE + 'TStandardCBusApplication.SetGroupName':
            names[app] = resource
    checks['catalogue_group_overrides'] = names == {172: 'Communication Group', 192: 'Media Link Group',
                                                  202: 'Trigger Group', 203: 'Enable Network Variable'}
    checks['enable_application_name'] = image.resource(0x85a9f8) == 'Enable Control'
    method(CATALOGUE + 'TStandardCBusApplications.GetGroupName')
    at(CATALOGUE + 'TStandardCBusApplication.Create', (
        (0x85aef4, 'mov', 'eax, dword ptr [0x13c1d14]'),
        (0x85af04, 'call', '0x85afa0')))

    # Native construction/loading does not run managed CBusApplication.ReadXmlData.
    # The actual application overload only adapts XML child collection wrappers.
    at(APP + 'ProcessAndLoadFromXMLString', ((0xf2607a, 'call', '0xf25964'),
                                            (0xf26086, 'call', '0x7eb588')))
    preprocess = method(COMMON + 'PreProcessXML', 0xf25964)
    checks['native_xml_preprocessor_no_group_creator'] = not any(
        GROUPS + 'GroupByAddress' in n or GROUPS + 'Add' in n for _a, _m, _op, n in preprocess)
    at(APPS + 'CheckAllHaveUnusedGroup', (
        (0xf2647e, 'mov', 'edx, 0xff'), (0xf26483, 'call', '0xf28a8c'),
        (0xf2649d, 'mov', 'cl, 1'), (0xf2649f, 'mov', 'edx, 0xff'),
        (0xf264a4, 'call', '0xf28b68')))
    at(NETWORK + 'CheckStandardConfiguration', ((0xf2aa9d, 'call', '0xf2644c'),))

    at(PARENT + 'SameGroups', (
        (0x1131b22, 'je', '0x1131b53'), (0x1131b33, 'cmp', 'eax, dword ptr [edx + ecx*4]'),
        (0x1131b36, 'jne', '0x1131b53'), (0x1131b46, 'cmp', 'eax, 0xff'),
        (0x1131b4b, 'je', '0x1131b53'), (0x1131b4d, 'mov', 'byte ptr [ebp - 0xd], 0')))
    at(PARENT + 'ValidateRemoteSetbackGroupsNotUnused', (
        (0x1131dc5, 'je', '0x1131e33'), (0x1131df4, 'cmp', 'eax, 0xff'),
        (0x1131df9, 'jne', '0x1131e33'), (0x1131e28, 'cmp', 'eax, 0xff'),
        (0x1131e2d, 'jne', '0x1131e33'), (0x1131e2f, 'xor', 'eax, eax')))
    at(PROGRAM_PARENT + 'ValidateRemoteScheduleGroupsNotUnused', (
        (0x11333d1, 'je', '0x1133428'), (0x11333ec, 'jne', '0x1133424'),
        (0x1133407, 'jne', '0x1133424'), (0x1133422, 'je', '0x1133428'),
        (0x1133424, 'xor', 'eax, eax')))
    for name in (PARENT + 'ValidateRemoteSetbackGroups', PROGRAM_PARENT + 'ValidateRemoteScheduleGroups',
                 PROGRAM_PARENT + 'ValidateRemoteScheduleAndRemoteSetbackGroups'):
        checks[name + '_identity_validator'] = PARENT + 'SameGroups' in calls(name)
    at(PARENT + 'ValidateProgramming', ((0x11323ae, 'call', '0x1131d58'),
        (0x1132437, 'call', '0x1131da8'), (0x113255b, 'dec', 'eax'),
        (0x113255c, 'jne', '0x1132642')))
    at(PROGRAM_PARENT + 'ValidateProgramming', ((0x11334e1, 'call', '0x1133350'),
        (0x1133532, 'call', '0x11333b4'), (0x1133583, 'call', '0x1133434'),
        (0x113360d, 'dec', 'eax'), (0x113360e, 'jne', '0x113361e')))
    at(BASE + 'BeforeSaveProgrammingInformation', (
        (0x1294d80, 'jle', '0x1294df8'), (0x1294d94, 'call', '0xf47a10'),
        (0x1294dce, 'call', '0xf47a10'), (0x1294dfe, 'mov', 'edx, 0x1e'),
        (0x1294e24, 'mov', 'edx, 0x1f')))
    at(PROGRAM + 'BeforeSaveProgrammingInformation', (
        (0x1299bbc, 'call', '0x129471c'),
        (0x1299fb7, 'call', '0xfdffd4'), (0x1299fcd, 'call', '0xfdd1a0'),
        (0x1299fe3, 'call', '0xfdd1c4'), (0x1299fea, 'je', '0x129a0c9'),
        (0x129a028, 'call', '0xf47a10'), (0x129a062, 'call', '0xf47a10'),
        (0x129a09c, 'call', '0xf47a10'), (0x129a0f2, 'mov', 'edx, 0x20'),
        (0x129a118, 'mov', 'edx, 0x21'), (0x129a13e, 'mov', 'edx, 0x22')))

    aliases = {}
    for unit, parent in (('PC_TSA', 'TProgrammableThermostat'), ('PC_TSA5', 'TProgrammableThermostat'),
                         ('PC_TSB', 'TBasicThermostat'), ('PC_TSB5', 'TBasicThermostat')):
        vmt = walker.dword(image.by_name['CIS_TThermostat..T' + unit])
        chain = []
        while vmt:
            pointer = walker.dword(vmt - 56)
            length = image.pe.get_data(pointer - image.base, 1)[0]
            chain.append(image.pe.get_data(pointer - image.base + 1, length).decode('ascii'))
            pointer = walker.dword(vmt - 48)
            vmt = walker.dword(pointer) if pointer else 0
        checks[unit + '_family'] = parent in chain
        aliases[unit] = chain
    for name in ('TThermostat', 'TBasicThermostat', 'TProgrammableThermostat'):
        vmt = walker.dword(image.by_name['CIS_TThermostat..' + name])
        checks[name + '_application_getter'] = walker.dword(vmt + 0xb0) == 0xf2ebc0
    for address in (0xf2338c, 0xf23cd4):
        vmt = walker.dword(address)
        checks[hex(address) + '_storage_save_slots'] = (
            walker.dword(vmt + 0x7c), walker.dword(vmt + 0x80)) == (0x7f405c, 0x7f409c)

    specs = None
    if spec_dir is not None:
        from cbus_toolkit.unitspec import UnitSpecStore
        store = UnitSpecStore(spec_dir)
        specs = {}
        pins = {
            'THERMOSTAT.xml': '780c4a9abd7640e46c21258f29cb970f4e78460154229d0d5901a0355506b367',
            'THERMOSTATA.xml': '3ae197382370fe23efb4c61476c4cb09ac3b0ee74a7f4f1feca1afb04fa326ed',
            'THERMOSTATB.xml': 'fe7cfeae5c9d16873adeeb0b9dcd6cb4ac34f3d1b8eb2b2c57236111316f4b74',
        }
        for filename, digest in pins.items():
            if _sha((spec_dir / filename).read_bytes()) != digest:
                raise ValueError('Pinned decoded specification differs: ' + filename)
        for filename in ('THERMOSTATA.xml', 'THERMOSTATB.xml'):
            spec = store.load(filename)
            checks[filename + '_type'] = spec.unit_type == filename.removesuffix('.xml')
            checks[filename + '_firmware_bounds'] = (spec.metadata.get('MinVersion'),
                                                     spec.metadata.get('MaxVersion')) == ('0', '9')
            parameters = {}
            fields = ['ApplicationNumber', 'RemoteSetbackControlSource', 'RemoteSetbackOnGroup',
                      'RemoteSetbackOffGroup', 'RemoteScheduleEnable', 'RemoteScheduleOnGroup',
                      'RemoteScheduleOffGroup', 'RemoteScheduleOverrideGroup']
            if filename == 'THERMOSTATA.xml':
                fields += ['EvapProgramEnabled', 'NonEvapProgramEnabled']
            for name in fields:
                parameter = spec.parameters[name]
                checks[filename + ':' + name + '_byte_shape'] = (
                    parameter.type, parameter.array_size, parameter.bit_size) == ('int', 1, 8)
                parameters[name] = {'address': parameter.address, 'type': parameter.type,
                                    'count': parameter.array_size, 'bits': parameter.bit_size}
            specs[filename] = {'sha256': pins[filename], 'type': spec.unit_type,
                               'sources': {name: pins[name] for name in spec.sources},
                               'minimum_version': spec.metadata['MinVersion'],
                               'maximum_version': spec.metadata['MaxVersion'], 'parameters': parameters}
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError('Remote-reference source differs: ' + ', '.join(failures))
    if (_sha(exe.read_bytes()), _sha(map_path.read_bytes())) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original inputs changed during inspection')
    return {
        'format': 'cbus-thermostat-remote-references-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False, 'physical_io': False,
        'checks': {name: True for name in sorted(checks)},
        'method_spans': {name: item[1] for name, item in sorted(methods.items())},
        'alias_class_chains': aliases,
        'decoded_specifications': specs,
        'contract': {
            'source1_application': 'ApplicationNumber, not generic Application array or fixed56',
            'source2_and_schedule_application': 203,
            'role_lookup_order': ['setback_on', 'setback_off', 'schedule_on', 'schedule_off', 'schedule_override'],
            'enable_application_getter': 'unconditional check/create followed by lookup; no bAdd preference',
            'existing_reference': 'same object; no rename/save',
            'new_application203_name': 'Enable Control',
            'new_group_name_lighting48_95': 'Group N',
            'new_group_name203': 'Enable Network Variable N',
            'new_group255_name': '<Unused>', 'creation_command_kind': 'Group',
            'serialized_child_kind': 'separate database/backend contract; command kind does not prove XML spelling',
            'native255': 'real group; create-enabled lookup creates/saves if missing; disabled lookup does not create',
            'schedule_enable': 'OR of normalized Evap and NonEvap; raw RemoteScheduleEnable ignored',
            'setback_eligibility': 'at least one non255; two non255 roles must have distinct identity',
            'enabled_schedule_eligibility': 'all three non255 and all five remote non255 identities distinct',
            'identity': 'same address in different application is distinct',
            'optional_levels': 'declined creation prompt preserves validation success; existing levels unchanged',
            'graph_only_policy': 'owned CLI policy: zero PP saves, one target project save',
            'no_op_policy': 'only when both PP delta and planned graph additions are empty',
        },
        'limits': [
            'Raw candidate edits precede one bounded remote agent load/save projection, not GUI controls.',
            'Remote validation is a subset; no complete parent form or unrelated AfterLoad graph is claimed.',
            'Native Delphi groups differ from managed eDLT virtual unused groups.',
            'Firmware must satisfy the selected caller-supplied decoded specification and exact family alias.',
            'Decoded source1/2 description labels are reversed; actual agent branches are authoritative.',
            'THERMOSTATB contains schedule PP fields but its basic class does not execute programmable projection.',
            'Object StorageSave order is static evidence, not an atomic native C-Gate transaction receipt.',
            'No original instructions, emulator, GUI, native endpoint or hardware executed by this reproducer.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--spec-dir', type=Path, help='Optionally check pinned original decoded base specifications')
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map, args.spec_dir), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
