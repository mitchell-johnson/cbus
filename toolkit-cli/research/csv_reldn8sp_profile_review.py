"""Review the RELDN8SP CSV group reload against pinned Toolkit EXE/MAP bytes.

This reads original files locally and commits only derived facts and a synthetic
fixture. It does not execute the original Toolkit or read a site database.
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
BASE_LOADER = 0x122DD40
SP_LOADER = 0x1244D0C
GROUP_MANAGER_CLASS = 0xF23E10
REPORT = 0xF306BC
SELECTED_INDICES = (1, 2, 3, 4, 7, 8, 9, 10, 11)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def source_review(exe_path: Path, map_path: Path, fixture_path: Path):
    exe_bytes, map_bytes = exe_path.read_bytes(), map_path.read_bytes()
    if _sha(exe_bytes) != EXE_SHA256 or _sha(map_bytes) != MAP_SHA256:
        raise ValueError('Toolkit EXE/MAP digest differs from the pinned original')
    image = pefile.PE(data=exe_bytes, fast_load=True)
    base = image.OPTIONAL_HEADER.ImageBase
    segments = {index: next(base + section.VirtualAddress for section in image.sections
                            if section.Name.startswith(name))
                for index, name in ((1, b'.text'), (2, b'.itext'))}
    symbols = {}
    for line in map_bytes.decode('ascii').splitlines():
        match = re.match(r'^\s+000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*$', line)
        if match:
            address = int(match[2], 16) + segments[int(match[1])]
            symbols.setdefault(address, set()).add(match[3])

    def raw(address, length):
        result = image.get_data(address - base, length)
        if len(result) != length:
            raise ValueError('Original PE read ended early')
        return result

    def pointer(address):
        return struct.unpack('<I', raw(address, 4))[0]

    def symbol(address, name):
        if name not in symbols.get(address, ()):
            raise ValueError(f'MAP symbol mismatch at {address:#x}: {name}')

    def instruction(address, expected):
        if raw(address, len(expected)) != expected:
            raise ValueError(f'Original instruction mismatch at {address:#x}')

    def call(address, target):
        if raw(address, 1) != b'\xe8' or address + 5 + struct.unpack('<i', raw(address + 1, 4))[0] != target:
            raise ValueError(f'Original call mismatch at {address:#x}')

    for address, name in (
        (BASE_LOADER, 'CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.LoadGroups'),
        (SP_LOADER, 'CIS_TMarshallingBoxCGateAgent.TMarshallingBoxCGateAgent.LoadGroups'),
        (GROUP_MANAGER_CLASS, 'CIS_TCommonCBus..TCBusGroupManager'),
        (REPORT, 'CIS_TCommonCBus.TCBUSUnitManager.AsCSV'),
        (0x122B294, 'CIS_TRELDN8..TRELDN8SP'),
        (0x7E8B98, 'CIS_TCustomFlashObject.TFlashObjectReferenceCollection.Clear'),
        (0x7E9FD0, 'CIS_TCustomFlashObject.TFlashObjectCollection.Append'),
        (0x7E8F50, 'CIS_TCustomFlashObject.TFlashObjectReferenceCollection.GetCount'),
        (0xF28954, 'CIS_TCommonCBus.TCBusGroupManager.GetItem'),
    ):
        symbol(address, name)
    if pointer(0x122B294 + 0x28) != 0x122B054:
        raise ValueError('RELDN8SP is no longer derived from TRELDN8')
    if pointer(GROUP_MANAGER_CLASS) != GROUP_MANAGER_CLASS + 0x58:
        raise ValueError('Group-manager VMT base moved')
    vmt = GROUP_MANAGER_CLASS + 0x58
    for offset, expected in ((0x58, 0x7E8F50), (0x68, 0x7E9FD0),
                             (0x6C, 0x7E8B98)):
        if pointer(vmt + offset) != expected:
            raise ValueError(f'Group-manager VMT changed at {offset:#x}')

    call(0x1244D2E, BASE_LOADER)
    # The special pass is reached for TRELDN8 descendants when the unit's
    # 0x170 byte is zero and its application object is present. It clears the
    # list populated by the base pass, then appends the nine selected groups.
    instruction(0x1244D52, bytes.fromhex('8b1554b02201'))
    instruction(0x1244DA0, bytes.fromhex('8b10ff526c'))
    instruction(0x1244E52, bytes.fromhex('8b08ff5168'))
    instruction(0x1244E5A, bytes.fromhex('837df8057507'))
    instruction(0x1244E60, bytes.fromhex('c745f807000000'))
    instruction(0x1244E6A, bytes.fromhex('837df80c'))
    # The report asks the rebuilt manager for its count and items, capped by
    # its 16 group columns; it does not inspect the initial DIN list directly.
    instruction(0xF307DB, bytes.fromhex('8b80d00000008b10ff5258'))
    call(0xF3081C, 0xF28954)
    instruction(0xF3085C, bytes.fromhex('837dec10'))

    starts = sorted(symbols)
    spans = {}
    for address in (BASE_LOADER, SP_LOADER, REPORT):
        end = next(value for value in starts if value > address)
        if end - address > 32768:
            raise ValueError('Original method span exceeds static bound')
        spans[next(iter(symbols[address]))] = {
            'start': hex(address), 'end': hex(end),
            'bytes_sha256': _sha(raw(address, end - address)),
        }

    fixture_bytes = fixture_path.read_bytes()
    root = ET.fromstring(fixture_bytes)
    unit = root.find('./Project/Network/Unit')
    if (root.tag != 'Installation' or root.findtext('./Project/Address') != 'CSVTEST'
            or root.findtext('./Project/Network/Address') != '254' or unit is None
            or len(root.findall('./Project/Network/Unit')) != 1
            or unit.findtext('UnitType') != 'RELDN8SP'
            or unit.findtext('FirmwareVersion') != '2.7.00'):
        raise ValueError('Synthetic fixture is not the admitted RELDN8SP project')
    params = {node.get('Name'): node.get('Value') for node in unit.findall('PP')}
    if (len(params) != 3 or params.get('Application') != '56 255'
            or params.get('AreaGroupAddress') != '255'
            or len(params.get('GroupAddress', '').split()) != 16):
        raise ValueError('Synthetic fixture leaves the bounded stored profile')

    return {
        'format': 'cbus-toolkit-database-csv-reldn8sp-profile-review-v1',
        'original_execution': False,
        'original_inputs': {'CBusToolkit.exe': EXE_SHA256,
                            'CBusToolkit.map': MAP_SHA256},
        'source_method_spans': spans,
        'loader': {
            'unit_class': 'TRELDN8SP', 'agent': 'TMarshallingBoxCGateAgent',
            'base_stored_group_count': 16,
            'second_pass_stored_indices_zero_based': list(SELECTED_INDICES),
            'association_operations': 25,
            'group_manager_clear_between_passes': True,
            'final_group_manager_count': 9,
            'csv_visible_group_count': 9,
            'group_manager_vmt': {'get_count': '0x7e8f50',
                                  'append': '0x7e9fd0', 'clear': '0x7e8b98'},
        },
        'synthetic_fixture': {
            'path': 'research/fixtures/' + fixture_path.name,
            'sha256': _sha(fixture_bytes), 'site_data': False,
        },
        'limits': [
            'The 25 entries are two ordered load phases, not 25 final CSV groups: the second pass clears and rebuilds the unit group manager.',
            'The bounded 2.7.00 projection admits a resolved primary application, unused secondary application, existing Area255 and all 16 stored GroupAddress references.',
            'Original GUI CSV execution and a cold native database load on this synthetic fixture have not been performed.',
            'The read-only adapter rejects missing groups that the original create=true lookup may create.',
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
    args.output.write_text(json.dumps(source_review(args.exe, args.map, args.fixture),
                                      indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
