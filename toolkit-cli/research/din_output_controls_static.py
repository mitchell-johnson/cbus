#!/usr/bin/env python3
"""Verify retained DIN controls provenance by reading PE/MAP bytes only.

This never loads the executable as code or runs an original instruction.
The output is a verification receipt, not a native GUI acceptance claim.
"""
import argparse
import hashlib
import json
from pathlib import Path

from extract_toolkit_executable_surface import Cursor, _read_component_header, _read_value, _text
from project_documentor_static import _Toolkit


ANNEX = Path(__file__).with_name('fixtures') / 'din-output-controls-source-review.json'


def verify(executable, map_file):
    receipt = json.loads(ANNEX.read_text())
    exe, mapping = Path(executable).read_bytes(), Path(map_file).read_bytes()
    for kind, raw in (('exe', exe), ('map', mapping)):
        if hashlib.sha256(raw).hexdigest() != receipt[f'toolkit_{kind}_sha256']:
            raise ValueError(f'Unpinned Toolkit {kind} bytes')
    image = _Toolkit(exe, mapping)
    for method in receipt['methods']:
        start, end = int(method['start'], 16), int(method['end'], 16)
        if image.by_name[method['name']] != start or next(a for a in image.starts if a > start) != end:
            raise ValueError('Method span changed: ' + method['name'])
        raw = image.pe.get_data(start - image.base, end - start)
        if hashlib.sha256(raw).hexdigest() != method['sha256']:
            raise ValueError('Method bytes changed: ' + method['name'])
    for row in receipt['vmt_slots']:
        if image.slot(row['class_name'], int(row['offset'], 16)) != row['symbol']:
            raise ValueError('Virtual dispatch changed: ' + row['class_name'])
    for row in receipt['literals']:
        address = int(row['address'], 16)
        length = image.dword(address - 4)
        if image.pe.get_data(address - image.base, length * 2).decode('utf-16le') != row['value']:
            raise ValueError('Selector text changed')
    constant = receipt['delay_stagger']
    if image.pe.get_data(int(constant['va'], 16) - image.base, 10).hex() != constant['extended_hex']:
        raise ValueError('Delay extended constant changed')
    resources = {}
    for kind in image.pe.DIRECTORY_ENTRY_RESOURCE.entries:
        for name in kind.directory.entries:
            if name.name is not None:
                leaf = name.directory.entries[0].data.struct
                resources[str(name.name)] = image.pe.get_data(leaf.OffsetToData, leaf.Size)
    for form in receipt['forms']:
        raw = resources[form['name']]
        if len(raw) != form['byte_length'] or hashlib.sha256(raw).hexdigest() != form['sha256']:
            raise ValueError('Form bytes changed: ' + form['name'])
        cursor, controls = Cursor(raw, 4), {}

        def visit(parent='', depth=0):
            class_name, name = _read_component_header(cursor, version=raw[3] - ord('0'))
            properties = {}
            while cursor.peek_u8() != 0:
                key = _text(cursor.short_bytes())
                properties[key] = _read_value(cursor, depth=depth + 1)
            cursor.u8()
            path = parent + '/' + name
            controls[path] = class_name, properties
            while cursor.peek_u8() != 0:
                visit(path, depth + 1)
            cursor.u8()

        visit()
        if cursor.remaining:
            raise ValueError('Unread DFM bytes')
        for row in form['controls']:
            class_name, properties = controls[row['path']]
            if class_name != row['class_name'] or any(properties.get(key) != value for key, value in row['properties'].items()):
                raise ValueError('DFM binding changed: ' + row['path'])
            if row['name'] in ('chkSyncTurnOn', 'chkSyncRecovery') and any(
                    key in properties for key in ('Checked', 'State', 'OnClick')):
                raise ValueError('Sync initialization is no longer the DFM default')
    return {'format': 'cbus-din-output-controls-static-verification-v1', 'verified': True,
            'toolkit_exe_sha256': receipt['toolkit_exe_sha256'],
            'toolkit_map_sha256': receipt['toolkit_map_sha256'],
            'methods_checked': len(receipt['methods']), 'forms_checked': len(receipt['forms']),
            'vmt_slots_checked': len(receipt['vmt_slots']),
            'original_code_executed': False, 'native_server_executed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', required=True, type=Path)
    parser.add_argument('--map', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = json.dumps(verify(args.exe, args.map), indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
