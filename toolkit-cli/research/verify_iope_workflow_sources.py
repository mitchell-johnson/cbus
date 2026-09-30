#!/usr/bin/env python3
"""Verify IOPE source receipts against private originals without executing them."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re


def verify(executable, unitspecs):
    import pefile
    root = Path(__file__).resolve().parent / 'fixtures'
    data = executable.read_bytes()
    mapping = executable.with_suffix('.map').read_bytes()
    image = pefile.PE(data=data)
    base = image.OPTIONAL_HEADER.ImageBase
    segments = {i: base + next(s.VirtualAddress for s in image.sections if s.Name.startswith(name))
                for i, name in ((1, b'.text'), (2, b'.itext'))}
    symbols, addresses = {}, set()
    for line in mapping.decode('ascii').splitlines():
        match = re.match(r'^\s+000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*$', line)
        if match:
            address = segments[int(match[1])] + int(match[2], 16)
            symbols.setdefault(match[3], set()).add(address)
            # Keep every address: overloaded names can occupy several ranges.
            addresses.add(address)
    starts = sorted(addresses)
    resources = {}
    for kind in image.DIRECTORY_ENTRY_RESOURCE.entries:
        if not hasattr(kind, 'directory'):
            continue
        for named in kind.directory.entries:
            if named.name:
                for locale in named.directory.entries:
                    blob = locale.data.struct
                    resources.setdefault(str(named.name), set()).add(
                        hashlib.sha256(image.get_data(blob.OffsetToData, blob.Size)).hexdigest())
    results = []
    for filename in ('iope-environment-source-review.json', 'iope-output-source-review.json',
                     'iope-logic-source-review.json', 'iope-join-recovery-source-review.json',
                     'iope-block-timer-source-review.json', 'iope-input-functions-source-review.json',
                     'iope-join-groups-source-review.json', 'iope-scene-selectors-source-review.json',
                     'iope-template-transaction-source-review.json', 'iope-scene-levels-source-review.json'):
        receipt = json.loads((root / filename).read_text())
        if hashlib.sha256(data).hexdigest() != receipt['toolkit_exe_sha256']:
            raise ValueError('Toolkit executable differs from ' + filename)
        if hashlib.sha256(mapping).hexdigest() != receipt['toolkit_map_sha256']:
            raise ValueError('Toolkit MAP differs from ' + filename)
        for method in receipt['methods']:
            start, end = int(method['start'], 16), int(method['end'], 16)
            if start not in symbols.get(method['name'], ()) or starts[starts.index(start) + 1] != end:
                raise ValueError('Original MAP method bounds differ: ' + method['name'])
            actual = hashlib.sha256(image.get_data(start - base, end - start)).hexdigest()
            if actual != method['sha256']:
                raise ValueError('Original method bytes differ: ' + method['name'])
        for method in receipt.get('next_recovery_ranges', []):
            start, end = int(method['start'], 16), int(method['end'], 16)
            if start not in symbols.get(method['name'], ()) or starts[starts.index(start) + 1] != end:
                raise ValueError('Next recovery MAP bounds differ: ' + method['name'])
        for record in receipt.get('raw_ranges', []) + receipt.get('strings', []):
            start, size = int(record['start'], 16), record['size']
            if type(size) is not int or size < 1:
                raise ValueError('Invalid original data range in ' + filename)
            blob = image.get_data(start - base, size)
            if len(blob) != size or hashlib.sha256(blob).hexdigest() != record['sha256']:
                raise ValueError('Original data bytes differ: ' + record.get('label', record['start']))
            if 'value' in record and blob.decode('utf-16-le') != record['value']:
                raise ValueError('Original literal differs: ' + record['start'])
        for name, digest in receipt['unitspec_sha256'].items():
            if hashlib.sha256((unitspecs / name).read_bytes()).hexdigest() != digest:
                raise ValueError('UnitSpec differs: ' + name)
        for name, digest in receipt.get('form_resource_sha256', {}).items():
            if resources.get(name) != {digest}:
                raise ValueError('Original form resource differs: ' + name)
        results.append({'receipt': filename, 'methods_verified': len(receipt['methods']),
                        'unitspecs_verified': len(receipt['unitspec_sha256']),
                        'form_resources_verified': len(receipt.get('form_resource_sha256', {})),
                        'data_ranges_verified': len(receipt.get('raw_ranges', [])),
                        'literals_verified': len(receipt.get('strings', [])),
                        'next_recovery_bounds_verified': len(receipt.get('next_recovery_ranges', []))})
    return {'format': 'cbus-iope-workflow-source-verification-v1', 'passed': True,
            'original_code_executed': False, 'receipts': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--unitspec-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.exe, args.unitspec_dir), indent=2))


if __name__ == '__main__':
    main()
