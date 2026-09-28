"""Pin the distinct RELDN8B and RELDN8SP CSV load paths to Toolkit 1.18.

Reads the original vendor EXE/MAP locally. Only a derived review and a
synthetic RELDN8B fixture are committed; the original is never executed here.
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
AREA_GETTER = 0xD1EF60
DIMMER_INTERACTION = 0xD2BF94
DIN_AGENT = 0x122C6A4
MARSHALLING_AGENT = 0x12430CC
BASE_GROUP_LOADER = 0x122DD40
SPECIAL_GROUP_LOADER = 0x1244D0C

PROFILES = (
    # Unit type, class, class address, literal, class registration,
    # type-string agent registration, class-based agent registration.
    ('RELDN8B', 'TRELDN8B', 0x122B4D8, 0x13985F4, 0x1398515, 0x1398578,
     0x13988E4, DIN_AGENT, 0x122BA90, 8),
    ('RELDN8SP', 'TRELDN8SP', 0x122B294, 0x1398610, 0x1398536, 0x1398599,
     0x1398BF8, MARSHALLING_AGENT, DIMMER_INTERACTION, 9),
)
METHODS = {
    0x122BA90: 'CIS_TRELDN8.TRELDN8B.IsInteractionGroup',
    0x122B900: 'CIS_TRELDN8.TRELDN8SP.GetMaxChannels',
    BASE_GROUP_LOADER: 'CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.LoadGroups',
    SPECIAL_GROUP_LOADER: 'CIS_TMarshallingBoxCGateAgent.TMarshallingBoxCGateAgent.LoadGroups',
}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def source_review(exe_path, map_path, fixture_path):
    exe_bytes, map_bytes = exe_path.read_bytes(), map_path.read_bytes()
    if _sha(exe_bytes) != EXE_SHA256 or _sha(map_bytes) != MAP_SHA256:
        raise ValueError('Toolkit EXE/MAP digest differs from the pinned original')
    image = pefile.PE(data=exe_bytes, fast_load=True)
    base = image.OPTIONAL_HEADER.ImageBase
    segments = {
        index: next(base + section.VirtualAddress for section in image.sections
                    if section.Name.startswith(name))
        for index, name in ((1, b'.text'), (2, b'.itext'))
    }
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

    for address, name in METHODS.items():
        symbol(address, name)
    symbol(0x122B4D8, 'CIS_TRELDN8..TRELDN8B')
    symbol(0x122B294, 'CIS_TRELDN8..TRELDN8SP')
    symbol(DIN_AGENT, 'CIS_TDinRailOutputCGateAgent..TDinRailOutputCGateAgent')
    symbol(MARSHALLING_AGENT,
           'CIS_TMarshallingBoxCGateAgent..TMarshallingBoxCGateAgent')
    symbol(AREA_GETTER,
           'CIS_TCBusDINRailOutputUnit.TCBusDINRailOutputUnit.GetAreaIfAvailable')
    symbol(DIMMER_INTERACTION,
           'CIS_TCBusDimmerUnit.TCBusDimmerUnit.IsInteractionGroup')

    registrations = []
    for (kind, selected, klass, literal, unit_at, type_agent_at,
         class_agent_at, agent, interaction, channels) in PROFILES:
        if raw(literal, len(kind) * 2 + 2) != kind.encode('utf-16le') + b'\0\0':
            raise ValueError('Original unit-type literal mismatch: ' + kind)
        instruction(unit_at, b'\x8b\x0d' + struct.pack('<I', klass)
                    + b'\xba' + struct.pack('<I', literal))
        instruction(type_agent_at, b'\x8b\x0d' + struct.pack('<I', 0xD24694)
                    + b'\xba' + struct.pack('<I', literal))
        instruction(class_agent_at, b'\x8b\x0d' + struct.pack('<I', agent)
                    + b'\x8b\x15' + struct.pack('<I', klass))
        for offset, expected in ((0xEC, AREA_GETTER), (0x10C, interaction)):
            if pointer(klass + 0x58 + offset) != expected:
                raise ValueError(f'{kind} report VMT differs at {offset:#x}')
        getter = 0x122B900 if kind == 'RELDN8SP' else 0x122B71C
        if pointer(klass + 0x58 + 0x188) != getter:
            raise ValueError(f'{kind} channel getter differs')
        instruction(getter, bytes.fromhex('558bec83c4f88945fcc745f8')
                    + struct.pack('<I', channels))
        registrations.append({
            'unit_type': kind, 'selected_class': selected,
            'firmware_min': '0', 'firmware_max': '9',
            'class_address': hex(klass), 'unit_registration': hex(unit_at),
            'type_agent_registration': hex(type_agent_at),
            'class_agent_registration': hex(class_agent_at),
            'class_agent': ('TDinRailOutputCGateAgent' if agent == DIN_AGENT
                            else 'TMarshallingBoxCGateAgent'),
            'area_getter': hex(AREA_GETTER),
            'interaction_predicate': hex(interaction),
            'max_channels_getter': hex(getter), 'max_channels': channels,
        })
    for address, value in ((0x13985B8, '0'), (0x13985C8, '9')):
        instruction(address, value.encode('utf-16le') + b'\0\0')
    # B uses an unsigned slot < 8 predicate, independently of its inherited
    # eight-channel getter. SP inherits the generic slot < max-channel test.
    instruction(0x122BA90, bytes.fromhex(
        '558bec83c4f48955f88945fc8b45f883e8080f92c08845f78a45f78be55dc3'))
    # The special agent first calls the 16-slot DIN loader, then conditionally
    # appends another run of channel groups; its index skips 5 and 6.
    call(0x1244D2E, BASE_GROUP_LOADER)
    instruction(0x1244E5A, bytes.fromhex('837df8057507'))
    instruction(0x1244E60, bytes.fromhex('c745f807000000'))
    instruction(0x1244E6A, bytes.fromhex('837df80c'))
    instruction(0x1244E52, bytes.fromhex('8b08ff5168'))

    starts = sorted(symbols)
    methods = {}
    for address, name in METHODS.items():
        end = next(value for value in starts if value > address)
        if end - address > 32768:
            raise ValueError('Original method span exceeds static bound')
        methods[name] = {'start': hex(address), 'end': hex(end),
                         'bytes_sha256': _sha(raw(address, end - address))}

    fixture = fixture_path.read_bytes()
    root = ET.fromstring(fixture)
    network = root.find('./Project/Network')
    unit = None if network is None else network.find('Unit')
    if (root.tag != 'Installation' or root.findtext('./Project/Address') != 'CSVTEST'
            or network is None or network.findtext('Address') != '254'
            or len(network.findall('Unit')) != 1 or unit is None
            or unit.findtext('UnitType') != 'RELDN8B'
            or unit.findtext('FirmwareVersion') != '2.7.00'):
        raise ValueError('Synthetic fixture is not the admitted RELDN8B project')
    params = {node.get('Name'): node.get('Value') for node in unit.findall('PP')}
    if (len(params) != 3 or params.get('Application') != '56 255'
            or params.get('AreaGroupAddress') != '255'
            or len(params.get('GroupAddress', '').split()) != 16):
        raise ValueError('Synthetic RELDN8B leaves the bounded profile')

    return {
        'format': 'cbus-toolkit-database-csv-reldn8-variants-profile-review-v1',
        'original_execution': False,
        'original_inputs': {'CBusToolkit.exe': EXE_SHA256,
                            'CBusToolkit.map': MAP_SHA256},
        'registrations': registrations, 'source_method_spans': methods,
        'static_facts': {
            'reldn8b': 'The DIN output agent loads 16 ordered primary-application groups; its separate predicate exposes slots 0 through 7.',
            'reldn8sp': 'The marshalling-box agent calls the DIN 16-slot loader and can append nine further groups (up to 25 associations); its inherited predicate exposes slots 0 through 8.',
        },
        'synthetic_fixture': {'path': 'research/fixtures/' + fixture_path.name,
                              'sha256': _sha(fixture), 'site_data': False},
        'limits': [
            'Only RELDN8B firmware 2.7.00 with Area255, unused secondary application and 16 resolved stored primary groups is admitted.',
            'RELDN8SP is not projected: its conditional additional groups exceed the existing 16-association cached schema and need their own complete native profile.',
            'The original GUI CSV report and cold native database load were not run on this synthetic fixture.',
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
