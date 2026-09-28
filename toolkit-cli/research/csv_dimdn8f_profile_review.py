"""Pin the bounded DIMDN8F CSV profile to Toolkit 1.18 EXE/MAP bytes.

Reads the original vendor files locally; never executes them or copies them
into the repository. Only the derived JSON review is committed.
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
    0x1398060: 'CIS_TDIMDN8.CIS_TDIMDN8',
    0x13987E0: 'CIS_TDinRailOutputCGateAgent.CIS_TDinRailOutputCGateAgent',
    0x12298B0: 'CIS_TDIMDN8.TDIMDN8.GetMaxChannels',
    0xD2BF94: 'CIS_TCBusDimmerUnit.TCBusDimmerUnit.IsInteractionGroup',
    0xD1EF60: 'CIS_TCBusDINRailOutputUnit.TCBusDINRailOutputUnit.GetAreaIfAvailable',
    0x122DD40: 'CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.LoadGroups',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source_review(exe_path, map_path, fixture_path):
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

    def instruction(address, expected):
        if raw(address, len(expected)) != expected:
            raise ValueError(f'Original instruction mismatch at {address:#x}')

    def literal(address, value):
        if raw(address, len(value) * 2 + 2) != value.encode('utf-16le') + b'\0\0':
            raise ValueError(f'Original literal mismatch at {address:#x}')

    for address, name in METHODS.items():
        symbol(address, name)
    symbol(0x122942C, 'CIS_TDIMDN8..TDIMDN8')
    symbol(0x122966C, 'CIS_TDIMDN8..TDIMDN8F')
    symbol(0x122C6A4, 'CIS_TDinRailOutputCGateAgent..TDinRailOutputCGateAgent')
    for address, value in ((0x1398108, '0'), (0x1398118, '9'),
                           (0x1398128, 'DIMDN8'), (0x1398144, 'DIMDN8F')):
        literal(address, value)

    # Both factory registrations have the same firmware bounds. The second
    # class pointer and literal belong to DIMDN8F, not the DIMDN8 registration.
    for address, expected in (
        (0x1398088, bytes.fromhex('8b0d2c942201')),
        (0x139808E, bytes.fromhex('ba28813901')),
        (0x1398093, bytes.fromhex('e8c42a88ff')),
        (0x13980A9, bytes.fromhex('8b0d6c962201')),
        (0x13980AF, bytes.fromhex('ba44813901')),
        (0x13980B4, bytes.fromhex('e8a32a88ff')),
        (0x1398824, bytes.fromhex('8b0da4c62201')),
        (0x139882A, bytes.fromhex('8b152c942201')),
        (0x139883C, bytes.fromhex('8b0da4c62201')),
        (0x1398842, bytes.fromhex('8b156c962201')),
    ):
        instruction(address, expected)

    dim_vmt, frost_vmt = 0x122942C + 0x58, 0x122966C + 0x58
    # The report methods are inherited unchanged. The class data after
    # 0x1b0 contains names/metadata and is intentionally excluded.
    for offset in range(0x80, 0x1B0, 4):
        if pointer(dim_vmt + offset) != pointer(frost_vmt + offset):
            raise ValueError(f'DIMDN8F report VMT differs at {offset:#x}')
    report_slots = {0xEC: 0xD1EF60, 0x10C: 0xD2BF94,
                    0x188: 0x12298B0}
    for offset, expected in report_slots.items():
        if pointer(frost_vmt + offset) != expected:
            raise ValueError(f'DIMDN8F report slot differs at {offset:#x}')

    starts = sorted(symbols)
    methods = {}
    for address, name in METHODS.items():
        end = next(value for value in starts if value > address)
        if end - address > 32768:
            raise ValueError('Original method span exceeds static bound')
        methods[name] = {'start': hex(address), 'end': hex(end),
                         'bytes_sha256': digest(raw(address, end - address))}

    fixture = fixture_path.read_bytes()
    root = ET.fromstring(fixture)
    unit = root.find('./Project/Network/Unit')
    if (unit is None or unit.findtext('UnitType') != 'DIMDN8F'
            or unit.findtext('FirmwareVersion') != '2.7.00'):
        raise ValueError('Synthetic fixture is not the admitted DIMDN8F profile')
    parameters = {node.get('Name'): node.get('Value') for node in unit.findall('PP')}
    if (len(parameters) != 3 or parameters.get('Application') != '56 255'
            or parameters.get('AreaGroupAddress') != '255'
            or parameters.get('GroupAddress') !=
            '8 1 8 4 3 2 7 6 16 15 14 13 12 11 10 9'):
        raise ValueError('Synthetic fixture no longer covers pinned associations')

    return {
        'format': 'cbus-toolkit-database-csv-dimdn8f-profile-review-v1',
        'original_execution': False,
        'original_inputs': {'CBusToolkit.exe': EXE_SHA256,
                            'CBusToolkit.map': MAP_SHA256},
        'source_method_spans': methods,
        'registration': {'unit_type': 'DIMDN8F', 'firmware_min': '0',
                         'firmware_max': '9', 'selected_class': 'TDIMDN8F',
                         'factory_callsite': '0x13980b4',
                         'agent_class': 'TDinRailOutputCGateAgent',
                         'agent_registration_callsite': '0x1398848'},
        'unit_vmt': {'address': hex(frost_vmt),
                     'report_slots_match_dimdn8': True,
                     'area_getter': hex(report_slots[0xEC]),
                     'interaction_predicate': hex(report_slots[0x10C]),
                     'max_channels': hex(report_slots[0x188])},
        'static_facts': {
            'groups': 'The shared DIN output agent loads and appends all 16 stored primary-application group associations in order.',
            'area': 'The inherited DIN output Area getter resolves AreaGroupAddress in the primary application.',
            'interaction': 'The inherited dimmer predicate compares the zero-based slot to GetMaxChannels, which returns eight.',
        },
        'synthetic_fixture': {'path': 'research/fixtures/' + fixture_path.name,
                              'sha256': digest(fixture), 'site_data': False},
        'limits': [
            'Original EXE/MAP static review and synthetic projection only; the original GUI CSV report was not run on this fixture.',
            'Cold native database loading of DIMDN8F firmware 2.7.00 was not executed.',
            'Only the existing Area255, resolved primary application, unused secondary application, 16-slot 2.7.00 shape is admitted.',
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
