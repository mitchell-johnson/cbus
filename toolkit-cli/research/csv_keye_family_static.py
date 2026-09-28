"""Verify the eight TKEYEx factory registrations in pinned Toolkit 1.18 files.

This reads PE data and a MAP file. It never loads or executes vendor code.
The resulting receipt contains only hashes, symbol names and registration facts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

import pefile


EXE_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
MAP_SHA256 = 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
INITIALIZER = (0x138B62C, 0x138B944,
               '9ed37986c37b80f17984116549404eed795fd7da89f1572397792c32d46bb889')
FACTORY_CLASS = 0xEA8CFC
REGISTER_METHOD = 0xC1AB5C
REGISTRATIONS = (
    ('KEYE1', 0x138B880, 0x138B65F),
    ('KEYE2', 0x138B898, 0x138B680),
    ('KEYE3', 0x138B8B0, 0x138B6A1),
    ('KEYE4', 0x138B8C8, 0x138B6C2),
    ('KEYEIR1', 0x138B8E0, 0x138B6E3),
    ('KEYEIR2', 0x138B8FC, 0x138B704),
    ('KEYEIR3', 0x138B918, 0x138B725),
    ('KEYEIR4', 0x138B934, 0x138B746),
)


def review(executable: Path, map_file: Path) -> dict[str, object]:
    raw_exe = executable.read_bytes()
    raw_map = map_file.read_bytes()
    if hashlib.sha256(raw_exe).hexdigest() != EXE_SHA256:
        raise ValueError('Toolkit executable hash mismatch')
    if hashlib.sha256(raw_map).hexdigest() != MAP_SHA256:
        raise ValueError('Toolkit MAP hash mismatch')
    image = pefile.PE(data=raw_exe, fast_load=True)
    base = image.OPTIONAL_HEADER.ImageBase
    map_text = raw_map.decode('ascii')
    text_section = next(section for section in image.sections
                        if section.Name.startswith(b'.text'))
    itext_section = next(section for section in image.sections
                         if section.Name.startswith(b'.itext'))
    symbol_addresses = {}
    for line in map_text.splitlines():
        match = re.fullmatch(r'\s+000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*', line)
        if match:
            section = text_section if match[1] == '1' else itext_section
            va = base + section.VirtualAddress + int(match[2], 16)
            symbol_addresses.setdefault(match[3], set()).add(va)
    for name, expected in (
        ('CIS_TKEYEx..TKEYEx', FACTORY_CLASS),
        ('CIS_TKEYEx.CIS_TKEYEx', INITIALIZER[0]),
        ('CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType', REGISTER_METHOD),
    ):
        if expected not in symbol_addresses.get(name, ()):
            raise ValueError('Missing pinned MAP symbol: ' + name)
    start, end, expected_digest = INITIALIZER
    initializer = image.get_data(start - base, end - start)
    if hashlib.sha256(initializer).hexdigest() != expected_digest:
        raise ValueError('TKEYEx initializer bytes changed')

    result = []
    for unit_type, string_va, call_va in REGISTRATIONS:
        encoded = (unit_type + '\0').encode('utf-16-le')
        if image.get_data(string_va - base, len(encoded)) != encoded:
            raise ValueError('TKEYEx registration string mismatch: ' + unit_type)
        prefix = image.get_data(call_va - base - 11, 11)
        expected_prefix = (b'\x8b\x0d' + struct.pack('<I', FACTORY_CLASS) +
                           b'\xba' + struct.pack('<I', string_va))
        if prefix != expected_prefix:
            raise ValueError('TKEYEx factory/class/string callsite changed: ' + unit_type)
        instruction = image.get_data(call_va - base, 5)
        if (instruction[:1] != b'\xe8' or
                call_va + 5 + struct.unpack('<i', instruction[1:])[0] != REGISTER_METHOD):
            raise ValueError('TKEYEx factory registration target changed: ' + unit_type)
        result.append({'unit_type': unit_type, 'type_string_va': hex(string_va),
                       'registration_call_va': hex(call_va), 'selected_class': 'TKEYEx'})

    return {
        'format': 'cbus-toolkit-database-csv-keye-family-static-v1',
        'original_executable_sha256': EXE_SHA256,
        'original_map_sha256': MAP_SHA256,
        'original_code_executed': False,
        'initializer_va': hex(start),
        'initializer_bytes_sha256': expected_digest,
        'registrations': result,
        'basis': ('Each pinned initializer call passes the same TKEYEx class pointer '
                  'and one of eight exact unit-type strings to RegisterUnitType. '
                  'The inherited group/Area behavior is separately pinned in '
                  'csv-keye-profile-review.json and csv-keye-secondary-application-review.json.'),
        'limits': ('This verifies static factory registration, not a cold native load '
                   'or original GUI report for KEYE4/KEYEIR1-4. The CLI admits only '
                   'complete firmware 2.5.00 nine-slot snapshots with existing groups.'),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', required=True, type=Path)
    parser.add_argument('--map', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = review(args.exe, args.map)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
