"""Pin four bounded DIN output CSV profiles to Toolkit 1.18 EXE/MAP bytes.

Reads the original vendor files locally without executing or copying them into
the repository. Only the derived review and synthetic fixture are committed.
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
AGENT_CLASS = 0xD24694
AREA_GETTER = 0xD1EF60
INTERACTION_PREDICATE = 0xD2BF94
GROUP_LOADER = 0x122DD40

# unit type, selected class, class VMT base, literal, registration instruction,
# corresponding agent registration instruction, max-channel getter, channel count
PROFILES = (
    ('DIMDN4', 'TDIMDN4', 0x1228E0C, 0x1398034, 0x1397F94, 0x1397FD6, 0x1229290, 4),
    ('DIMDN4F', 'TDIMDN4F', 0x122904C, 0x1398050, 0x1397FB5, 0x1397FF7, 0x1229290, 4),
    ('RELDN4', 'TRELDN4', 0x122A8AC, 0x13984BC, 0x139845C, 0x139847D, 0x122AE88, 4),
    ('RELDN8', 'TRELDN8', 0x122B054, 0x13985D8, 0x13984F4, 0x1398557, 0x122B71C, 8),
)
METHODS = {
    0x1397F6C: 'CIS_TDIMDN4.CIS_TDIMDN4',
    0x1398438: 'CIS_TRELDN4.CIS_TRELDN4',
    0x13984CC: 'CIS_TRELDN8.CIS_TRELDN8',
    0x1229290: 'CIS_TDIMDN4.TDIMDN4.GetMaxChannels',
    0x122AE88: 'CIS_TRELDN4.TRELDN4.GetMaxChannels',
    0x122B71C: 'CIS_TRELDN8.TRELDN8.GetMaxChannels',
    AREA_GETTER: 'CIS_TCBusDINRailOutputUnit.TCBusDINRailOutputUnit.GetAreaIfAvailable',
    INTERACTION_PREDICATE: 'CIS_TCBusDimmerUnit.TCBusDimmerUnit.IsInteractionGroup',
    GROUP_LOADER: 'CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.LoadGroups',
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
        result = image.get_data(address - base, length)
        if len(result) != length:
            raise ValueError('Original PE read ended early')
        return result

    def pointer(address):
        return struct.unpack('<I', raw(address, 4))[0]

    def symbol(address, expected):
        if expected not in symbols.get(address, ()):
            raise ValueError(f'MAP symbol mismatch at {address:#x}: {expected}')

    def instruction(address, expected):
        if raw(address, len(expected)) != expected:
            raise ValueError(f'Original instruction mismatch at {address:#x}')

    for address, name in METHODS.items():
        symbol(address, name)
    for address, name in (
        (0x1228E0C, 'CIS_TDIMDN4..TDIMDN4'),
        (0x122904C, 'CIS_TDIMDN4..TDIMDN4F'),
        (0x122A8AC, 'CIS_TRELDN4..TRELDN4'),
        (0x122B054, 'CIS_TRELDN8..TRELDN8'),
        (0x122C6A4, 'CIS_TDinRailOutputCGateAgent..TDinRailOutputCGateAgent'),
    ):
        symbol(address, name)

    registrations = []
    for kind, selected_class, class_address, literal_address, register_at, agent_at, getter, channels in PROFILES:
        if raw(literal_address, len(kind) * 2 + 2) != kind.encode('utf-16le') + b'\0\0':
            raise ValueError('Original unit-type literal mismatch: ' + kind)
        instruction(register_at, b'\x8b\x0d' + struct.pack('<I', class_address)
                    + b'\xba' + struct.pack('<I', literal_address))
        instruction(agent_at, b'\x8b\x0d' + struct.pack('<I', AGENT_CLASS)
                    + b'\xba' + struct.pack('<I', literal_address))
        # The factory receives the literal firmware bounds "0" and "9".
        bounds = ((0x1398014, 0x1398024) if kind.startswith('DIMDN') else
                  (0x139849C, 0x13984AC) if kind == 'RELDN4' else
                  (0x13985B8, 0x13985C8))
        instruction(register_at - 0x11, b'\x68' + struct.pack('<I', bounds[0]))
        instruction(register_at - 0x0C, b'\x68' + struct.pack('<I', bounds[1]))
        for address, value in zip(bounds, ('0', '9')):
            if raw(address, len(value) * 2 + 2) != value.encode('utf-16le') + b'\0\0':
                raise ValueError('Original firmware bound literal differs')
        vmt = class_address + 0x58
        for offset, expected in ((0xEC, AREA_GETTER),
                                 (0x10C, INTERACTION_PREDICATE),
                                 (0x188, getter)):
            if pointer(vmt + offset) != expected:
                raise ValueError(f'{kind} report VMT differs at {offset:#x}')
        instruction(getter, bytes.fromhex('558bec83c4f88945fcc745f8')
                    + struct.pack('<I', channels))
        registrations.append({
            'unit_type': kind, 'selected_class': selected_class,
            'firmware_min': '0', 'firmware_max': '9',
            'class_address': hex(class_address), 'unit_registration': hex(register_at),
            'agent_registration': hex(agent_at),
            'area_getter': hex(AREA_GETTER),
            'interaction_predicate': hex(INTERACTION_PREDICATE),
            'max_channels_getter': hex(getter), 'max_channels': channels,
        })

    base_vmt = 0x1228E0C + 0x58
    frost_vmt = 0x122904C + 0x58
    for offset in range(0x80, 0x1B0, 4):
        if pointer(base_vmt + offset) != pointer(frost_vmt + offset):
            raise ValueError(f'DIMDN4F report VMT differs at {offset:#x}')

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
    project = root.find('./Project')
    network = root.find('./Project/Network')
    units = [] if network is None else network.findall('Unit')
    if (root.tag != 'Installation' or project is None or network is None
            or project.findtext('Address') != 'CSVTEST'
            or network.findtext('Address') != '254'
            or len(units) != 4
            or {unit.findtext('UnitType') for unit in units} != {row[0] for row in PROFILES}
            or {unit.findtext('Address') for unit in units} != {'4', '5', '6', '7'}):
        raise ValueError('Synthetic fixture is not the admitted four-profile project')
    for unit in units:
        parameters = {node.get('Name'): node.get('Value') for node in unit.findall('PP')}
        if (unit.findtext('FirmwareVersion') != '2.7.00' or len(parameters) != 3
                or parameters.get('Application') != '56 255'
                or parameters.get('AreaGroupAddress') != '255'
                or len(parameters.get('GroupAddress', '').split()) != 16):
            raise ValueError('Synthetic unit leaves the bounded DIN profile')

    return {
        'format': 'cbus-toolkit-database-csv-din4-rel4-rel8-profile-review-v1',
        'original_execution': False,
        'original_inputs': {'CBusToolkit.exe': EXE_SHA256,
                            'CBusToolkit.map': MAP_SHA256},
        'source_method_spans': methods,
        'registrations': registrations,
        'unit_vmt': {'dimdn4f_report_slots_match_dimdn4': True,
                     'shared_agent_class': 'TDinRailOutputCGateAgent',
                     'shared_group_loader': hex(GROUP_LOADER)},
        'static_facts': {
            'groups': 'The shared DIN output agent loads and appends all 16 stored primary-application group associations in order.',
            'area': 'The inherited DIN output Area getter resolves AreaGroupAddress in the primary application.',
            'interaction': 'The inherited dimmer predicate compares the zero-based slot to GetMaxChannels: four for DIMDN4/DIMDN4F/RELDN4 and eight for RELDN8.',
        },
        'synthetic_fixture': {'path': 'research/fixtures/' + fixture_path.name,
                              'sha256': digest(fixture), 'site_data': False},
        'limits': [
            'Original EXE/MAP static review and synthetic projection only; the original GUI CSV report was not run on this fixture.',
            'Cold native database loading of these exact 2.7.00 records was not executed.',
            'Only existing Area255, resolved primary application, unused secondary application and 16 stored group slots are admitted.',
            'The read-only adapter rejects missing groups that the original create=true path may create.',
            'RELDN8B and RELDN8SP have separate classes and are not included.',
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
