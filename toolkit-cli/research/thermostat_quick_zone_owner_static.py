"""Re-pin the source metadata for the fresh quick-zone owner as data only.

The fixture contains reviewed source contracts and method hashes, never vendor
instruction bodies. This helper verifies exact input and MAP-bound spans; it
does not execute the original image, a GUI, a planner, or an instruction emulator.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import _Image


def inspect(exe, map_path, fixture_path):
    fixture = json.loads(fixture_path.read_text())
    exe_raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    actual = (hashlib.sha256(exe_raw).hexdigest(), hashlib.sha256(map_raw).hexdigest())
    pins = fixture['original_inputs']
    if actual != (pins['exe_sha256'], pins['map_sha256']):
        raise ValueError('Pinned original source mismatch')
    image = _Image(exe_raw, map_raw)
    for span in fixture['method_spans']:
        start, end = int(span['start'], 16), int(span['end'], 16)
        if span['symbol'] not in image.symbols.get(start, set()) or not start < end:
            raise ValueError('Exact source MAP span mismatch: ' + span['symbol'])
        body = image.pe.get_data(start - image.base, end - start)
        if len(body) != end - start or hashlib.sha256(body).hexdigest() != span['sha256']:
            raise ValueError('Exact source body metadata mismatch: ' + span['symbol'])
    return {'schema': 'cbus-thermostat-quick-zone-owner-repin-v1',
        'span_count': len(fixture['method_spans']), 'passed': True,
        'fixture_sha256': hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        'original_execution': False, 'product_execution': False,
        'semantic_scope': 'Reviewed facts remain qualified by the source fixture; this run re-pins bytes/MAP only'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', dest='map_path', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, default=Path(__file__).resolve().parent / 'fixtures/thermostat-quick-zone-owner-source.json')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result = inspect(args.exe, args.map_path, args.fixture)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
