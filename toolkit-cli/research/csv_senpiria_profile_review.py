"""Pin the bounded SENPIRIA CSV projection to Toolkit 1.18 EXE/MAP bytes.

This reads vendor files locally and executes no vendor instructions. Keep the
vendor files outside Git; only the derived JSON review belongs in the repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from xml.etree import ElementTree as ET

import pefile


EXE_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
MAP_SHA256 = 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
METHODS = {
    0x1385328: 'CIS_TSENPIRSS.CIS_TSENPIRSS',
    0x138569C: 'CIS_TCBusST7SensorCGateAgent.CIS_TCBusST7SensorCGateAgent',
    0xCF80A0: 'CIS_TCBusST7SensorCGateAgent.TCBusST7PIRSensorCGateAgent.AgentLoad',
    0xCF4CB8: 'CIS_TCBusST7SensorCGateAgent.TCBusST7MultisensorCGateAgent.AgentLoad',
    0xCEBBE4: 'CIS_TCBusNeoInputCGateAgent.TCBusNeoInputCGateAgent.AgentLoad',
    0xcecbbc: 'CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.LoadUnitGroupAddresses',
    0xcc7bf0: 'CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.LoadGroups',
    0xcc75e4: 'CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.GetBlockGroup',
    0xc9d34c: 'CIS_TCBusInputUnit.TCBusInputUnit.GetAreaIfAvailable',
    0xd08700: 'CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.IsInteractionGroup',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pinned_source(exe_path, map_path):
    exe_bytes, map_bytes = exe_path.read_bytes(), map_path.read_bytes()
    if digest(exe_bytes) != EXE_SHA256 or digest(map_bytes) != MAP_SHA256:
        raise ValueError('Toolkit EXE/MAP digest differs from the pinned original')
    image = pefile.PE(data=exe_bytes, fast_load=True)
    base = image.OPTIONAL_HEADER.ImageBase
    segment_bases = {
        index: next(base + section.VirtualAddress for section in image.sections
                    if section.Name.startswith(name))
        for index, name in ((1, b'.text'), (2, b'.itext'))
    }
    symbols = {}
    for line in map_bytes.decode('ascii').splitlines():
        match = re.match(r'^\s+000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*$', line)
        if match:
            address = int(match[2], 16) + segment_bases[int(match[1])]
            symbols.setdefault(address, set()).add(match[3])
    return image, base, symbols


def source_review(exe_path, map_path, fixture_path):
    image, base, symbols = pinned_source(exe_path, map_path)

    def raw(address, length):
        value = image.get_data(address - base, length)
        if len(value) != length:
            raise ValueError('Original PE read ended early')
        return value

    def pointer(address):
        return struct.unpack('<I', raw(address, 4))[0]

    def symbol(address, expected):
        if expected not in symbols.get(address, ()):
            raise ValueError(f'MAP symbol mismatch at {address:#x}: {expected}')

    def literal(address, value):
        encoded = value.encode('utf-16le') + b'\x00\x00'
        if raw(address, len(encoded)) != encoded:
            raise ValueError(f'Original string mismatch at {address:#x}')

    for address, name in METHODS.items():
        symbol(address, name)
    for address, value in ((0x13855EC, 'SENPIRIA'), (0x138562C, '2.0.01'),
                           (0x1385648, '9')):
        literal(address, value)
    symbol(0xCEF2B8, 'CIS_TSENPIRSS..TST7SENPIRSS')
    symbol(0xCEF5E8, 'CIS_TSENPIRSS..TST7SENPIROA')
    symbol(0xCF3E10, 'CIS_TCBusST7SensorCGateAgent..TCBusST7PIRSensorCGateAgent')

    # One exact SENPIRIA registration takes 2.0.01..9 and the ST7 class.
    for address, expected in (
        (0x1385468, bytes.fromhex('682c563801')),
        (0x138546D, bytes.fromhex('6848563801')),
        (0x1385479, bytes.fromhex('8b0db8f2ce00')),
        (0x138547F, bytes.fromhex('baec553801')),
        (0x1385484, bytes.fromhex('e8d35689ff')),
        (0x13856DC, bytes.fromhex('8b0d103ecf00')),
        (0x13856E2, bytes.fromhex('8b15b8f2ce00')),
    ):
        if raw(address, len(expected)) != expected:
            raise ValueError(f'Original registration mismatch at {address:#x}')

    unit_vmt, agent_vmt, comparison_vmt = 0xCEF2B8 + 0x58, 0xCF3E10 + 0x58, 0xCEF5E8 + 0x58
    unit_slots = {0xEC: 0xC9D34C, 0x10C: 0xD08700}
    agent_slots = {0x94: 0xCF80A0, 0xD4: 0xCC7BF0, 0xE8: 0xCB82B4,
                   0xF4: 0xCECbbc}
    for offset, expected in unit_slots.items():
        if pointer(unit_vmt + offset) != expected or pointer(comparison_vmt + offset) != expected:
            raise ValueError(f'Original sensor unit VMT mismatch at {offset:#x}')
    for offset, expected in agent_slots.items():
        if pointer(agent_vmt + offset) != expected:
            raise ValueError(f'Original sensor agent VMT mismatch at {offset:#x}')
    class_specific_slots = {0x190: (0xCEFFA8, 0xCF0018),
                            0x194: (0xCEFF50, 0xCEFFC0),
                            0x198: (0xCEFF90, 0xCF0000)}
    for offset in range(0x80, 0x1D0, 4):
        actual = pointer(unit_vmt + offset), pointer(comparison_vmt + offset)
        if offset in class_specific_slots:
            if actual != class_specific_slots[offset] or raw(actual[0], 20) != raw(actual[1], 20):
                raise ValueError(f'Original sensor class override differs at {offset:#x}')
        elif actual[0] != actual[1]:
            raise ValueError(f'Original sensor VMTs differ unexpectedly at {offset:#x}')

    starts = sorted(symbols)
    methods = {}
    for address, name in METHODS.items():
        end = next(value for value in starts if value > address)
        if end - address > 32768:
            raise ValueError('Original method span exceeds the static bound')
        methods[name] = {'start': hex(address), 'end': hex(end),
                         'bytes_sha256': digest(raw(address, end - address))}

    fixture = fixture_path.read_bytes()
    root = ET.fromstring(fixture)
    unit = root.find('./Project/Network/Unit')
    if (unit is None or unit.findtext('UnitType') != 'SENPIRIA'
            or unit.findtext('FirmwareVersion') != '2.4.00'):
        raise ValueError('Synthetic fixture is not the admitted SENPIRIA profile')
    parameters = {node.get('Name'): node.get('Value') for node in unit.findall('PP')}
    if (parameters.get('Application') != '56 57'
            or parameters.get('SecondApplicationBlocks') != '85'
            or parameters.get('GroupAddress') != '1 2 3 4 5 6 7 8'):
        raise ValueError('Synthetic fixture no longer covers the pinned associations')

    return {
        'format': 'cbus-toolkit-database-csv-senpiria-profile-review-v1',
        'original_execution': False,
        'original_inputs': {'CBusToolkit.exe': EXE_SHA256, 'CBusToolkit.map': MAP_SHA256},
        'source_method_spans': methods,
        'registration': {
            'unit_type': 'SENPIRIA', 'firmware_min': '2.0.01', 'firmware_max': '9',
            'selected_class': 'TST7SENPIRSS', 'factory_callsite': '0x1385484',
            'agent_class': 'TCBusST7PIRSensorCGateAgent',
            'agent_registration_initializer': '0x138569c',
        },
        'unit_vmt': {'address': hex(unit_vmt),
                     'area_getter': hex(unit_slots[0xEC]),
                     'interaction_predicate': hex(unit_slots[0x10C]),
                     'same_area_and_interaction_as_tst7senpiroa': True,
                     'functional_slot_comparison': '0x80..0x1cc: all inherited pointers identical; three class-specific key/virtual-key/indicator methods have identical first 20 bytes'},
        'agent_vmt': {'address': hex(agent_vmt),
                      'agent_load': hex(agent_slots[0x94]),
                      'load_groups': hex(agent_slots[0xD4]),
                      'secondary_application_lookup': hex(agent_slots[0xE8]),
                      'load_unit_group_addresses': hex(agent_slots[0xF4])},
        'static_facts': {
            'area': 'The inherited input-unit getter resolves AreaGroupAddress in the primary application on each call.',
            'groups': 'The inherited core loader resolves ordered input-block groups and appends each non-nil group; the bounded fixture admits exactly eight stored slots.',
            'secondary_application': 'The inherited Neo loader reads SecondApplicationBlocks; the core block getter resolves masked slots in Application2 and the others in Application1.',
            'interaction': 'The inherited Neo predicate exposes zero-based slots 0 through 7; later report columns are unavailable.',
        },
        'synthetic_fixture': {'path': 'research/fixtures/' + fixture_path.name,
                              'sha256': digest(fixture), 'site_data': False},
        'limits': [
            'Static original EXE/MAP analysis and synthetic projection only; the original GUI report was not run on this fixture.',
            'Factory startup registration and cold native database loading were inferred from pinned source, not executed.',
            'Only SENPIRIA firmware 2.4.00 with eight stored groups, existing Area255 and selected groups is admitted.',
            'The read-only adapter rejects missing groups that the original create=true path may create.',
            'No native C-Gate, CNI, database mutation or physical device was used.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    review = source_review(args.exe, args.map, args.fixture)
    args.output.write_text(json.dumps(review, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
