"""Verify the source-only Toolkit 1.18 report-manager unit-order chain.

Supply the original EXE and MAP explicitly. This never executes vendor code,
opens a project, accesses C-Gate, or inspects site data. It reports hashes and
selected pinned instructions, not proprietary instruction bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

import capstone
import pefile


EXE_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
MAP_SHA256 = 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
METHODS = {
    'CIS_TCommonCBus.TCBusNetwork.InternalCreate':
        ('0xf299b0', 'a36bfe4c44ea8cf2e3b6fbbdc60ba816885eea6547f19e6de22b8ba66a4f0912'),
    'CIS_TCBusObject.TCGateObjectManager.SetSortStyleCustomAddressAsc':
        ('0xf48850', '3330851a47529c9fc524358e61092edb4ad19601c69bfc38f4c7dc810b7d406b'),
    'CIS_TCBusObject.TCGateObjectManager.CustomSortAddressAsc':
        ('0xf4825c', 'b5bd0358ec5d6c19a91107df4a3969458b4a7ad4f03bf43c61e1bf1508aec565'),
    'CIS_TCustomFlashObject.TFlashObjectReferenceCollection.SetSortStyle':
        ('0x7e9978', 'db6638575da006b04c97fb19c7dd4bf8e108c5a6a60bd4ee1751a41ae457d19d'),
    'CIS_TCustomFlashObject.TFlashObjectReferenceCollection.Append':
        ('0x7e84ac', 'efb8b52181bf7c3850a8692720016f9dd76b785be74c9d23e7b9e6947fca72f3'),
    'CIS_TCommonCBus.TCBUSUnitManager.GetItem':
        ('0xf2e08c', '5be213223b99148af3b77d88550577c76601c4365e1b4626287b162828c028fd'),
    'CIS_TCommonCBus.TCBUSUnitManager.AsCSV':
        ('0xf306bc', '5c50d7859b4651db79cee62c5c92219e9ca7388431fe6bd3b5d43572c9634d8a'),
    'CIS_TfrmUnitsNode.TfrmUnitsNode.actProduceDocumentationExecute':
        ('0xeb6488', '115ccc4b7eed6c1f95f594b1f7aec5d85acb7a047f1bc31c12e369945d88c5c7'),
}
MARKERS = {
    # Network +0xd8 is constructed as TCBUSUnitManager and sorted before use.
    0xf29a41: ('mov', 'eax, dword ptr [0xf21358]'),
    0xf29a4e: ('mov', 'dword ptr [edx + 0xd8], eax'),
    0xf29a7c: ('mov', 'eax, dword ptr [eax + 0xd8]'),
    0xf29a82: ('call', '0xf48850'),
    # The setter selects custom sort and the collection inserts/sorts accordingly.
    0xf48860: ('mov', 'dword ptr [edx + 0x60], 0xf4825c'),
    0xf48867: ('mov', 'dl, 3'),
    0xf4886c: ('call', '0x7e9978'),
    0x7e998a: ('mov', 'byte ptr [edx + 0x59], al'),
    0x7e99a5: ('call', '0x7e99b0'),
    0x7e859e: ('cmp', 'byte ptr [eax + 0x59], 0'),
    0x7e85aa: ('call', '0x7e9b30'),
    0x7e85ce: ('call', '0x643784'),
    # Custom comparator subtracts integer C-Gate addresses for units.
    0xf482a7: ('call', '0xf47a10'),
    0xf482b1: ('call', '0xf47a10'),
    0xf482b6: ('sub', 'ebx, eax'),
    0xf482bb: ('mov', 'dword ptr [eax], ebx'),
    # The GUI passes the same manager to AsCSV, which walks GetItem indices.
    0xeb6587: ('mov', 'eax, dword ptr [eax + 0xd8]'),
    0xeb6593: ('call', '0xf306bc'),
    0xf3074a: ('call', 'dword ptr [edx + 0x58]'),
    0xf30774: ('call', '0xf2e08c'),
    0xf30bb8: ('inc', 'dword ptr [ebp - 0x10]'),
    0xf30bbe: ('jne', '0xf30761'),
    0xf2e09e: ('call', '0x7e8f74'),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect(exe_path: Path, map_path: Path) -> dict:
    exe_raw, map_raw = exe_path.read_bytes(), map_path.read_bytes()
    if _sha(exe_raw) != EXE_SHA256 or _sha(map_raw) != MAP_SHA256:
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = pefile.PE(data=exe_raw, fast_load=True)
    if image.FILE_HEADER.Machine != 0x14c:
        raise ValueError('Expected pinned x86 Toolkit image')
    base = image.OPTIONAL_HEADER.ImageBase
    segment_bases = {
        segment: base + next(section.VirtualAddress for section in image.sections
                             if section.Name.startswith(name))
        for segment, name in ((1, b'.text'), (2, b'.itext'))
    }
    symbols: dict[int, set[str]] = {}
    for line in map_raw.decode('ascii').splitlines():
        match = re.fullmatch(r'\s*000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*', line)
        if match:
            address = int(match[2], 16) + segment_bases[int(match[1])]
            symbols.setdefault(address, set()).add(match[3])
    starts = sorted(symbols)
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    found: dict[int, tuple[str, str]] = {}
    spans = {}
    for name, (start_hex, expected_sha) in METHODS.items():
        start = int(start_hex, 16)
        if name not in symbols.get(start, ()):
            raise ValueError('Missing exact original MAP symbol: ' + name)
        end = next((address for address in starts if address > start), None)
        if end is None or not 0 < end - start <= 32768:
            raise ValueError('Unbounded original method: ' + name)
        raw = image.get_data(start - base, end - start)
        if _sha(raw) != expected_sha:
            raise ValueError('Original method changed: ' + name)
        found.update({instruction.address: (instruction.mnemonic, instruction.op_str)
                      for instruction in decoder.disasm(raw, start)})
        spans[name] = {'start': start_hex, 'end': hex(end),
                       'bytes': len(raw), 'sha256': expected_sha}
    for address, expected in MARKERS.items():
        if found.get(address) != expected:
            raise ValueError(f'Original report-manager instruction changed at {address:#x}')
    if _sha(exe_path.read_bytes()) != EXE_SHA256 or _sha(map_path.read_bytes()) != MAP_SHA256:
        raise ValueError('Original files changed during inspection')
    return {
        'format': 'cbus-toolkit-csv-manager-order-static-v1',
        'original_exe_sha256': EXE_SHA256,
        'original_map_sha256': MAP_SHA256,
        'original_executed': False,
        'method_spans': spans,
        'verified_instructions': {hex(address): {'mnemonic': mnemonic, 'operands': operands}
                                  for address, (mnemonic, operands) in MARKERS.items()},
        'source_conclusion': ('The selected network constructs its unit manager at +0xd8 '
                              'with custom integer-address-ascending sort. The report action '
                              'passes that manager to AsCSV, which enumerates GetItem indices.'),
        'limit': ('This verifies one pinned original source chain, not cold project loading, '
                  'interactive Toolkit execution, project-wide network order, or physical devices.'),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
