"""Verify pinned source data for thermostat default-name equality.

The original EXE/MAP are read as data only. No vendor instructions, software,
provider, service or hardware run. Reports contain bounded method hashes and
semantic checks, with no input paths, instruction listings or vendor bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402

METHOD_PINS = {
    'CIS_TThermostat.TPlantControlService.FindExistingGroup':
        ('0xfe2afc', '0xfe2be4', 'b375c529b20d7d4bdcf23c94e14b660eae67fe67fbdf31e31c172d8173bc8087'),
    'SysUtils.LowerCase':
        ('0x6187ac', '0x618824', 'a673244ff7f84d8f63b2ad8c2d29b56a0c89489c85b2b1e0876378e75b6259ce'),
    'SysUtils.LowerCaseFromAnsiString':
        ('0x61875c', '0x6187ac', 'b4640869f66a5c2091be6745558069deefb057e79f0baa9b34e044795dac22a2'),
    'SysUtils.UpperCase':
        ('0x6186e4', '0x61875c', '31d49e2c60709181dfc1e9cf67b3f0aeed856589842419b8ba2a7b8fc7205753'),
    'System.@UStrEqual':
        ('0x6090ac', '0x609114', '6af8d82e87766e21661a77b583dcdbcf966b8d7420d2d0bbc56913bd54b4ba25'),
}
OUTPUT = Path(__file__).resolve().parent / 'fixtures/thermostat-output-default-ascii-source.json'
TABLE = Path(__file__).resolve().parent / 'fixtures/thermostat-output-groups-source-review.json'
TABLE_SHA256 = 'e74a356b9467f03b6f796652199149a9c978033577b0b074b366f7f3dfd596f3'


def inspect(exe_path: Path, map_path: Path, *, table_path: Path = TABLE) -> dict:
    """Read exact source data and emit only the bounded sanitized facts."""
    exe, mapping = exe_path.read_bytes(), map_path.read_bytes()
    if (hashlib.sha256(exe).hexdigest() != EXE_SHA256
            or hashlib.sha256(mapping).hexdigest() != MAP_SHA256):
        raise ValueError('Original source-data hashes do not match the pinned profile')
    table_raw = table_path.read_bytes()
    if hashlib.sha256(table_raw).hexdigest() != TABLE_SHA256:
        raise ValueError('Default-table source receipt changed')
    image = _Image(exe, mapping)
    methods = {name: image.method(name) for name in METHOD_PINS}
    for name, (start, end, digest) in METHOD_PINS.items():
        row = methods[name]
        if (hex(row['start']), hex(row['end']), row['sha256']) != (start, end, digest):
            raise ValueError('Pinned dependency span changed: ' + name)

    def has(name: str, address: int, mnemonic: str, operand: str) -> bool:
        return (address, mnemonic, operand) in methods[name]['instructions']

    caller, lower, fallback, upper, equal = METHOD_PINS
    checks = {
        'caller_folds_existing': has(caller, 0xfe2b8b, 'call', '0x6187ac'),
        'caller_folds_requested': has(caller, 0xfe2b9a, 'call', '0x6187ac'),
        'caller_exact_string_equality': has(caller, 0xfe2ba3, 'call', '0x6090ac'),
        'LowerCase_ASCII_A_base': has(lower, 0x618803, 'add', 'esi, -0x41'),
        'LowerCase_26_codepoint_range': has(lower, 0x618806, 'sub', 'si, 0x1a'),
        'LowerCase_skip_outside_range': has(lower, 0x61880a, 'jae', '0x618810'),
        'LowerCase_set_bit32_only_in_range': has(lower, 0x61880c, 'or', 'ax, 0x20'),
        'LowerCase_fallback_ASCII_A_base': has(fallback, 0x61878c, 'add', 'ecx, -0x41'),
        'LowerCase_fallback_26_codepoint_range': has(fallback, 0x61878f, 'sub', 'cx, 0x1a'),
        'LowerCase_fallback_skip_outside_range': has(fallback, 0x618793, 'jae', '0x61879f'),
        'LowerCase_fallback_set_bit32_only_in_range': has(fallback, 0x618798, 'or', 'cx, 0x20'),
        'UpperCase_ASCII_a_base': has(upper, 0x61873b, 'add', 'esi, -0x61'),
        'UpperCase_xor_bit32': has(upper, 0x618744, 'xor', 'ax, 0x20'),
        'UTF16_equality_length_exact': has(equal, 0x6090c3, 'cmp', 'ecx, dword ptr [edx - 4]'),
        'UTF16_equality_contents_exact': has(equal, 0x6090d4, 'cmp', 'ebx, dword ptr [ecx + edx]'),
    }
    if not all(checks.values()):
        raise ValueError('ASCII comparison source checkpoint failed')
    table = json.loads(table_raw)
    if methods[caller]['sha256'] != table['method_spans'][caller]['sha256']:
        raise ValueError('Caller proof is not the admitted output-group source receipt')
    rows = [row for family in table['default_labels'].values()
            for values in family.values() for row in values]
    labels = [row['label'] for row in rows if row['label'] is not None]
    if not (len(rows) == 174 and len(labels) == 48 and all(s.isascii() for s in labels)
            and len(table['damper_labels']) == 4
            and all(s.isascii() for s in table['damper_labels'].values())):
        raise ValueError('Default-name table is outside the pinned ASCII profile')
    return {
        'format': 'cbus-thermostat-output-default-ascii-static-v1',
        'original_executed': False, 'source_data_read_only': True,
        'physical_io': False, 'vendor_instructions_executed': False,
        'original_input_hashes': {'EXE': EXE_SHA256, 'MAP': MAP_SHA256},
        'default_table_receipt_sha256': TABLE_SHA256,
        'methods': {name: {'address': hex(row['start']), 'end': hex(row['end']),
                           'sha256': row['sha256']} for name, row in methods.items()},
        'checks': checks,
        'table': {'default_rows': 174, 'non_None_labels': 48,
                  'all_actual_default_labels_ASCII': True, 'damper_labels': 4},
        'contract': 'ASCII A..Z folding followed by exact string equality. NonASCII code units remain unchanged. Shared ASCII _upper has identical equality classes.',
        'scope': {'missing_reference_lookup_only': True,
                  'application_migration_implemented': False,
                  'arbitrary_Unicode_generated_defaults_admitted': False},
        'limits': ['No native/original GUI execution or manager sort order proof.',
                   'UTF16 source name profile; no culture casefold or caller-defined Unicode generated defaults.'],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result = inspect(args.exe, args.map)
    value = (json.dumps(result, indent=2, sort_keys=True) + '\n').encode()
    if args.check:
        if args.output.read_bytes() != value:
            raise SystemExit('Published ASCII default source receipt differs')
    else:
        args.output.write_bytes(value)
    print(json.dumps({'output': args.output.name, 'sha256': hashlib.sha256(value).hexdigest(),
                      'bytes': len(value), 'method_spans': len(result['methods']),
                      'checks': len(result['checks']), 'original_executed': False}))


if __name__ == '__main__':
    main()
