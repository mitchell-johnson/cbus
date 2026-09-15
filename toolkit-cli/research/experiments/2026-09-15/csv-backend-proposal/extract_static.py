"""Reproducible, source-only bounded projection disassembly; executes no vendor code."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

import capstone
import pefile

BASE = Path(__file__).resolve().parent
EXE = Path('/Users/mitchell/source/cbus/toolkit-cli/research/vendor/toolkit/app/CBusToolkit.exe')
MAP = EXE.with_suffix('.map')
PINS = {EXE: '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab',
        MAP: 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', help='New direct child of this owned research directory')
    parser.add_argument('addresses', nargs='+', type=lambda text: int(text, 0))
    args = parser.parse_args()
    output = Path(args.output)
    if output.parent.resolve() != BASE or output.exists() or output.is_symlink():
        raise ValueError('output must be a new direct owned child')
    source = {}
    for path, expected in PINS.items():
        source[path] = path.read_bytes()
        if hashlib.sha256(source[path]).hexdigest() != expected:
            raise ValueError(f'original source hash mismatch: {path.name}')
    image = pefile.PE(data=source[EXE], fast_load=True)
    symbols = {}
    segment_bases = {1: next(image.OPTIONAL_HEADER.ImageBase+s.VirtualAddress for s in image.sections if s.Name.startswith(b'.text')), 2: next(image.OPTIONAL_HEADER.ImageBase+s.VirtualAddress for s in image.sections if s.Name.startswith(b'.itext'))}
    for line in source[MAP].decode('ascii').splitlines():
        match = re.match(r'^\s+000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*$', line)
        if match:
            symbols.setdefault(int(match[2],16)+segment_bases[int(match[1])],set()).add(match[3])
    starts = sorted(symbols)
    addresses = tuple(args.addresses)
    if not 1 <= len(addresses) <= 32 or len(set(addresses)) != len(addresses):
        raise ValueError('one to 32 distinct exact method starts required')
    spans = []
    for address in addresses:
        if address not in symbols:
            raise ValueError(f'unknown exact method start: {address:#x}')
        end = next(value for value in starts if value > address)
        if end - address > 32768:
            raise ValueError('method span exceeds static bound')
        spans.append((address, end))
    output.mkdir()
    disassembler = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    report = {'original_execution': False, 'scope': 'bounded .text/.itext PE disassembly with exact MAP symbol annotations; spans may include trailing inline data' ,
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'original_inputs': {str(path): digest for path, digest in PINS.items()}, 'methods': []}
    for address, end in spans:
        data = image.get_data(address - image.OPTIONAL_HEADER.ImageBase, end-address)
        lines = []
        for instruction in disassembler.disasm(data, address):
            annotation = ''
            if instruction.mnemonic in ('call', 'jmp') and re.fullmatch(r'0x[0-9a-f]+', instruction.op_str):
                target = int(instruction.op_str, 16)
                if target in symbols:
                    annotation = ' ; ' + ' | '.join(sorted(symbols[target]))
            lines.append(f'{instruction.address:08x}: {instruction.bytes.hex():<24} {instruction.mnemonic} {instruction.op_str}{annotation}')
        path = output / f'{address:08x}.asm'
        path.write_text('\n'.join(lines)+'\n', encoding='utf-8')
        report['methods'].append({'start': hex(address), 'end': hex(end), 'symbols': sorted(symbols[address]),
                                  'bytes_sha256': hashlib.sha256(data).hexdigest(), 'file': path.name,
                                  'file_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    if any(path.read_bytes() != data for path, data in source.items()):
        raise RuntimeError('original source changed during static extraction')
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
