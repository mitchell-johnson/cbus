"""Verify additional output report classes, loaders and native base-only exits.

Reads pinned vendor files only; no original process or generated-page capture.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit
from csv_factory_registry_static import source_registry
from cbus_toolkit import project_documentation_outputs as model
from cbus_toolkit.toolkit_database_csv_registry import REGISTRATIONS

BODY = 'CIS_TOutputDocumentor.TOutputDocumentor.DocumentHTML'
BASE = 'CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.'
DIN = 'CIS_TDinRailOutputCGateAgent.TDinRailOutputCGateAgent.'


def inspect(exe: Path, map_file: Path) -> dict:
    raw, symbols = exe.read_bytes(), map_file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Toolkit(raw, symbols)
    wanted = set(model.DIRECT_CHANNELS) | set(model.NCC_TYPES)
    rows = [row for row in source_registry(exe, map_file, ())['registrations'] if row['unit_type'] in wanted]
    actual = [(r['unit_type'], r['firmware_min'], r['firmware_max'], r['class'], r['agent'] or '') for r in rows]
    expected = [row[:5] for row in REGISTRATIONS if row[0] in wanted]
    checks = {'native_factory_matches_runtime_registry': actual == expected}
    methods = {}

    def method(name):
        if name not in methods:
            methods[name] = image.method(name)
        return methods[name]

    def has(name, address, mnemonic, operands):
        return (address, mnemonic, operands) in method(name)['instructions']

    def count(name):
        values = [int(op.rsplit(', ', 1)[1], 0) for _, m, op in method(name)['instructions']
                  if m == 'mov' and re.fullmatch(r'dword ptr \[ebp - 8\], (0x[0-9a-f]+|[0-9]+)', op)]
        if len(values) != 1:
            raise ValueError('Not a constant count: ' + name)
        return values[0]

    recovered = []
    for row in rows:
        symbol = next(name for name in image.by_name if name.endswith('..' + row['class']))
        ancestry = image.ancestry(symbol)
        if row['unit_type'] in model.DIRECT_CHANNELS:
            kind = row['unit_type']
            checks[kind + ':agent_and_class'] = row['agent'] == 'TDinRailOutputCGateAgent' and 'TCBusDimmerUnit' in ancestry
            checks[kind + ':channel_count'] = count(image.slot(symbol, 0x188)) == model.DIRECT_CHANNELS[kind]
            checks[kind + ':logic_count'] = count(image.slot(symbol, 0x18c)) == 4
            slots = [image.slot(symbol, offset).rsplit('.', 2)[-2] for offset in (0x128, 0x12c, 0x130)]
            checks[kind + ':group_usage_slots'] = slots == ['TCBUSUnit', 'TCBusDimmerUnit', 'TCBusDimmerUnit']
            recovered.append({**row, 'ancestry': ancestry, 'report_channels': model.DIRECT_CHANNELS[kind],
                              'report_channel_indices': list(range(model.DIRECT_CHANNELS[kind]))})
        elif row['class'] == 'TNCCOutputUnit':
            checks[row['unit_type'] + ':ncc_base_only'] = 'TCBusDimmerUnit' not in ancestry
            recovered.append({**row, 'ancestry': ancestry, 'report_body': 'base_only'})
    checks['documentor_calls_base_before_type_check'] = has(BODY, 0xd247f9, 'call', hex(image.by_name['CIS_TProjectDocumentor.TUnitTypeDocumentor.DocumentHTML']))
    checks['documentor_requires_dimmer_class'] = has(BODY, 0xd24801, 'mov', 'edx, dword ptr [0xd29670]') and image.by_name['CIS_TCBusDimmerUnit..TCBusDimmerUnit'] == 0xd29670 and has(BODY, 0xd2480e, 'je', '0xd24bfe')
    checks['nondimmer_exit_no_extra_lines'] = has(BODY, 0xd24bfe, 'xor', 'eax, eax')
    checks['din_creation_calls_basic'] = has(DIN + 'InternalCreate', 0x122f422, 'call', hex(image.by_name[BASE + 'InternalCreate']))
    checks['din_load_calls_basic'] = has(DIN + 'AfterLoadProgrammingInformation', 0x122f6cb, 'call', hex(image.by_name[BASE + 'AfterLoadProgrammingInformation']))
    create, load = BASE + 'InternalCreate', BASE + 'AfterLoadProgrammingInformation'
    for index, field in enumerate(('LogicGA13Associations', 'LogicGA14Associations', 'LogicGA15Associations', 'LogicGA16Associations', 'LogicFunction')):
        offset = 0x104 + index * 4
        checks[field + ':pp_field'] = field in method(create)['literals'] and has(create, 0x122cdf6 + index * 0x26, 'mov', f'dword ptr [edx + {hex(offset)}], eax')
        checks[field + ':load_same_channel_index'] = has(load, 0x122d609 + index * 0x52, 'mov', f'eax, dword ptr [eax + {hex(offset)}]') and has(load, 0x122d629 + index * 0x52, 'mov', 'edx, dword ptr [ebp - 8]')
    checks['group_pp_field'] = 'GroupAddress' in method(create)['literals'] and has(create, 0x122ceb4, 'mov', 'dword ptr [edx + 0x11c], eax')
    checks['channel_group_direct_index'] = has(load, 0x122d79c, 'mov', 'eax, dword ptr [eax + 0x11c]') and has(load, 0x122d7bf, 'mov', 'edx, dword ptr [ebp - 8]')
    checks['logic_group_index_plus_twelve'] = has(load, 0x122d921, 'mov', 'eax, dword ptr [eax + 0x11c]') and has(load, 0x122d942, 'add', 'edx, 0xc')
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise ValueError('Output source checks failed: ' + ', '.join(failed))
    return {
        'format': 'cbus-project-documentor-outputs-static-v1',
        'exe_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256,
        'original_executed': False, 'original_generated_page_comparison': 'not_obtained',
        'model_module_sha256': hashlib.sha256(Path(model.__file__).read_bytes()).hexdigest(),
        'checks': checks, 'profiles': recovered,
        'methods': {name: {'start': hex(m['start']), 'end': hex(m['end']), 'sha256': m['sha256']}
                    for name, m in sorted(methods.items())},
        'limits': ['No programming editor admission is added.',
                   'Additional channel profiles require an explicit matching native firmware identity and all consumed PP arrays.',
                   'NCC body-only behavior is the native documentor class check; NCC group/action dependencies remain separately bounded.',
                   'Earlier DIMDD classes, special marshalling and remaining output agents are not newly projected.',
                   'This is static source evidence, not an original page, visual or printing comparison.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.exe, args.map)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f"Verified {len(report['checks'])} output documentor checks")


if __name__ == '__main__':
    main()
