#!/usr/bin/env python3
"""Verify Neo indicator evidence by reading pinned EXE/MAP and optional specs.

No original instructions, native services, or device operations are executed.
Only hashes, identifiers, numeric layouts, and control defaults are reported.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from pathlib import Path
import struct
import sys

from extract_toolkit_executable_surface import Cursor, _read_component_header, _read_value, _text
from pir_sensor_review import Review

ANNEX = Path(__file__).with_name('fixtures') / 'neo-indicator-editor-source-review.json'


def verify(executable: Path, map_file: Path, unit_spec_dir: Path | None = None) -> dict:
    receipt = json.loads(ANNEX.read_text())
    review = Review(Path(executable), Path(map_file))
    for kind, path in (('exe', executable), ('map', map_file)):
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != receipt[f'toolkit_{kind}_sha256']:
            raise ValueError(f'Unpinned Toolkit {kind} bytes')
    for method in receipt['methods']:
        start = review.names[method['name']]
        end = review.starts[bisect.bisect_right(review.starts, start)]
        if (hex(start), hex(end)) != (method['start'], method['end']):
            raise ValueError('Method span changed: ' + method['name'])
        if hashlib.sha256(review.raw(start, end - start)).hexdigest() != method['sha256']:
            raise ValueError('Method bytes changed: ' + method['name'])
    for row in receipt['vmt_slots']:
        pointer = review.u32(review.names[row['class_symbol']] + 0x58 + int(row['offset'], 16))
        if review.symbols[pointer] != row['symbol']:
            raise ValueError('Virtual dispatch changed: ' + row['class_symbol'])
    slot_meaning = {0x190: 'physical_leds', 0x194: 'runtime_keys', 0x1a8: 'brightness_enabled',
                    0x1ac: 'indicator_function_enabled', 0x1ec: 'nightlight_enabled', 0x1f0: 'pro',
                    0x1f4: 'classic', 0x1f8: 'keyc', 0x1fc: 'decorator', 0x200: 'standard',
                    0x204: 'reflection', 0x208: 'saturn', 0x214: 'bc'}
    for profile in receipt['profiles']:
        cls = profile['registration']['class_symbol']
        for slot, label in slot_meaning.items():
            symbol = review.symbols[review.u32(review.names[cls] + 0x58 + slot)]
            if review.constant(symbol, byte=slot not in (0x190, 0x194)) != profile[label]:
                raise ValueError('Profile constant changed: ' + profile['unit_type'])
    for row in receipt['literals']:
        if review.literal(int(row['address'], 16)) != row['value']:
            raise ValueError('Binding selector changed')
    review.image.parse_data_directories(directories=[2])
    resources = {}
    strings = {}
    for kind in review.image.DIRECTORY_ENTRY_RESOURCE.entries:
        for name in kind.directory.entries:
            leaf = name.directory.entries[0].data.struct
            raw = review.image.get_data(leaf.OffsetToData, leaf.Size)
            if name.name is not None:
                resources[str(name.name)] = raw
            if kind.id == 6:
                cursor = 0
                for index in range(16):
                    length = struct.unpack_from('<H', raw, cursor)[0]
                    cursor += 2
                    strings[(name.id - 1) * 16 + index] = raw[cursor:cursor + length * 2].decode('utf-16le')
                    cursor += length * 2
    for address, row in receipt['colour_resources'].items():
        if review.u32(int(address, 16) + 4) != row['id'] or strings[row['id']] != row['caption']:
            raise ValueError('Colour resource changed')
    for form in receipt['forms']:
        raw = resources[form['name']]
        if len(raw) != form['byte_length'] or hashlib.sha256(raw).hexdigest() != form['sha256']:
            raise ValueError('DFM bytes changed')
        cursor, controls = Cursor(raw, 4), {}

        def visit(parent: str = '', depth: int = 0) -> None:
            cls, name = _read_component_header(cursor, version=raw[3] - ord('0'))
            properties = {}
            while cursor.peek_u8():
                key = _text(cursor.short_bytes())
                properties[key] = _read_value(cursor, depth=depth + 1)
            cursor.u8()
            path = parent + '/' + name
            controls[path] = cls, properties
            while cursor.peek_u8():
                visit(path, depth + 1)
            cursor.u8()

        visit()
        if cursor.remaining:
            raise ValueError('Unread DFM bytes')
        for row in form['controls']:
            cls, properties = controls[row['path']]
            if cls != row['class_name'] or any(properties.get(k) != v for k, v in row['properties'].items()):
                raise ValueError('DFM control changed: ' + row['path'])
            if any(k in properties for k in row['absent_properties']):
                raise ValueError('DFM default changed: ' + row['path'])
    specs_checked = 0
    if unit_spec_dir is not None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        from cbus_toolkit.unitspec import UnitSpecStore, _integer
        directory = Path(unit_spec_dir)
        store = UnitSpecStore(directory)
        for row in receipt['decoded_spec_layouts']:
            if hashlib.sha256((directory / row['filename']).read_bytes()).hexdigest() != row['sha256']:
                raise ValueError('Decoded specification digest changed: ' + row['filename'])
            spec = store.load(row['filename'])
            if spec.unit_type != row['unit_type']:
                raise ValueError('Specification identity changed')
            for name, expected in row['layouts'].items():
                p = spec.get(name)
                actual = {'type': p.type, 'address': p.address, 'count': p.array_size,
                          'bits': 1 if p.type == 'bit' else p.bit_size,
                          'bit_offset': _integer(p.fields.get('BitAddress') or '0'),
                          'skip': _integer(p.fields.get('ArraySkip') or '0')}
                if actual != expected:
                    raise ValueError('Decoded layout changed: ' + row['filename'] + ':' + name)
            for name, expected in row['field_defaults'].items():
                if _integer(spec.get(name).default) != expected:
                    raise ValueError('Decoded default changed: ' + name)
            specs_checked += 1
    return {'format': 'cbus-neo-indicator-editor-static-verification-v1', 'verified': True,
            'toolkit_exe_sha256': receipt['toolkit_exe_sha256'],
            'toolkit_map_sha256': receipt['toolkit_map_sha256'],
            'methods_checked': len(receipt['methods']), 'vmt_slots_checked': len(receipt['vmt_slots']),
            'profiles_checked': len(receipt['profiles']), 'forms_checked': len(receipt['forms']),
            'decoded_specs_checked': specs_checked, 'original_code_executed': False,
            'native_server_executed': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', required=True, type=Path)
    parser.add_argument('--map', required=True, type=Path)
    parser.add_argument('--unit-spec-dir', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(verify(args.exe, args.map, args.unit_spec_dir), indent=2) + '\n'
    if args.output:
        args.output.write_text(result)
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
