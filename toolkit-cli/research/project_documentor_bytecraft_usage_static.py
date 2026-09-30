"""Verify the bounded old DIMPR12 output slice without vendor execution."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from project_documentor_static import EXE_SHA256, MAP_SHA256, UNIT_FACTORY, _Toolkit
from key_preset_families import Image, agent_registrations

OUTPUT = 'CIS_TCBusBytecraftDimmerUnit.TBytecraftUnit.DescribeOutputGroupDependencyAdvanced'
LOAD = 'CIS_TDIMPR12CGateAgent.TDIMPR12CGateAgent.AfterLoadProgrammingInformation'
COUNT = 'CIS_TDIMPR12.TDIMPR12.GetMaxChannels'
LOGIC = 'CIS_TCBusBytecraftDimmerUnit.TBytecraftUnit.GetLogicGroups'
BASE = 'CIS_TCommonCBus.TCBUSUnit.DescribeOutputGroupDependencyAdvanced'
CLASS = 'CIS_TDIMPR12..TDIMPR12'
AGENT = 'CIS_TDIMPR12CGateAgent..TDIMPR12CGateAgent'
ASSESSMENT = Path(__file__).parent / 'experiments/2026-09-30/project-documentor-bytecraft-assessment.json'


def inspect(executable, mapping):
    raw, symbols = executable.read_bytes(), mapping.read_bytes()
    if (hashlib.sha256(raw).hexdigest(), hashlib.sha256(symbols).hexdigest()) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Toolkit(raw, symbols)
    assessment = json.loads(ASSESSMENT.read_text())
    methods = {name: image.method(name) for name in (OUTPUT, LOAD, COUNT, LOGIC, BASE)}
    def has(name, address, op, args):
        return (address, op, args) in methods[name]['instructions']
    rows = [row for row in image.registrations(UNIT_FACTORY)[0] if row[0] == 'DIMPR12']
    checks = {
        'exact_old_and_l1_registrations': rows == [('DIMPR12', CLASS, '0', '1.9.02'),
            ('DIMPR12', 'CIS_TDIMPR12L1..TDIMPR12L1', '1.9.03', '9')],
        'exact_old_agent': agent_registrations(Image(executable, mapping)).get(CLASS) == [AGENT],
        'output_vmt': image.slot(CLASS, 0x12c) == OUTPUT,
        'count_vmt': image.slot(CLASS, 0x188) == COUNT,
        'twelve_channels': has(COUNT, 0x1014639, 'mov', 'dword ptr [ebp - 8], 0xc'),
        'no_logic_vmt': image.slot(CLASS, 0x194) == LOGIC,
        'no_logic_collection': has(LOGIC, 0xd39a61, 'xor', 'eax, eax'),
        'empty_inherited_output': has(BASE, 0xf2eeae, 'xor', 'edx, edx'),
        'inherited_output_first': has(OUTPUT, 0xd39ed5, 'call', hex(methods[BASE]['start'])),
        'channel_identity_compare': has(OUTPUT, 0xd39f0e, 'cmp', 'eax, dword ptr [ebp - 8]'),
        'one_based_channel': has(OUTPUT, 0xd39f2f, 'inc', 'edx'),
        'channel_order': has(OUTPUT, 0xd39f56, 'inc', 'dword ptr [ebp - 0x14]'),
        'pipe_separator': methods[OUTPUT]['literal_at'].get(0xd39f44) == '|',
        'loader_group_attribute': has(LOAD, 0x1246816, 'mov', 'eax, dword ptr [eax + 0x104]'),
        'loader_primary_application': has(LOAD, 0x124684e, 'call', 'dword ptr [edx + 0xb0]'),
        'loader_add_group': has(LOAD, 0x124685a, 'mov', 'cl, 1'),
        'retained_output_span': methods[OUTPUT]['sha256'] == assessment['methods'][OUTPUT]['sha256'],
        'retained_loader_span': methods[LOAD]['sha256'] == assessment['methods'][LOAD]['sha256'],
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError('Bytecraft output source differs: ' + ', '.join(failed))
    return {'format': 'cbus-project-documentor-bytecraft-usage-static-v1', 'exe_sha256': EXE_SHA256,
        'map_sha256': MAP_SHA256, 'checks': checks, 'registrations': rows, 'agent': AGENT,
        'methods': {name: {key: hex(row[key]) if key in ('start', 'end') else row[key]
                    for key in ('start', 'end', 'sha256')} for name, row in methods.items()},
        'original_loader_execution': 'not_executed', 'original_generated_page_comparison': 'not_obtained',
        'boundary': 'Old DIMPR12 output dependencies only. Static source proof; no vendor execution.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--map-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(inspect(args.executable, args.map_file), indent=2) + '\n')


if __name__ == '__main__':
    main()
