"""Verify the source-only Toolkit 1.18 Diagnostics dialog command sequence.

Supply the original EXE and MAP explicitly. This never executes vendor code,
opens a project, accesses C-Gate, or inspects site data. It reports hashes,
selected pinned instructions and the short UI/command literals they load,
not proprietary instruction bytes.

    python research/unit_diagnostics_static.py --exe CBusToolkit.exe --map CBusToolkit.map
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

import capstone
import pefile


EXE_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
MAP_SHA256 = 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
_FORM = 'CIS_TfrmPingUnits.TfrmPingUnits.'
_AGENT = 'CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.'
METHODS = {
    _FORM + 'WizardPage1NextButtonClick': ('0xea2cc4', 'f84b4218751d6a06d7c77fc3ea14f1e30734c53432b61fea7c21a7fbfee4aa77'),
    _FORM + 'PopulateUnits': ('0xea335c', '5b306f308677571eb37de1ee026b6e064fcebc01c91613360319ecde72a4e186'),
    _FORM + 'ProcessResult': ('0xea3514', '4be3c679d7aa431773e2b7d0ce79a4602dd14ac963b63e163a595b62bfb0433c'),
    _FORM + 'ProcessSingleResult': ('0xea3608', 'e9f94a578f1db9b3320eba4893a70bfe04b6c438b71c36ebd91302d03dc4d105'),
    _FORM + 'AddUnscannedUnit': ('0xea3730', 'e64552fefcbbdef161c71f05cc683e340efba1dd12805d20302149c8a8cac865'),
    _FORM + 'GetVolts': ('0xea3900', '2f71dab16fda0df2fcba99f394583cd0b1d5514d694a2704e517fc8f5d134dcd'),
    _FORM + 'GetBurden': ('0xea39f0', 'b863f6ba7d2e9f0d9621e20d452d198231143ca112f924e657429e7fc6718907'),
    _FORM + 'GetClock': ('0xea3ae0', 'b6206be4d908aa67646bfc151e508da1fc686ac503b8119a85518ceb0e4fae39'),
    _FORM + 'UpdateUnitVolts': ('0xea3be0', '8cee5b45c293b34e2b6dace78dd455e94e1db8be6a475f2412dc0131a8771c3e'),
    _FORM + 'UpdateUnitBurden': ('0xea3d40', 'd130cb7d534c84d5f01cc6f60dd7a0bc06456a6c1e93d07d4f7a41880cb8467a'),
    _FORM + 'UpdateUnitClock': ('0xea3edc', 'ab565083c2ddac6dd05acca344ae7ccf926cf4d496cc53830d2a1898392654ed'),
    _FORM + 'AllUnitsFailed': ('0xea4078', '44778a69c5f4ca974ff08d82fa8c132c9291294bb00ec74b161b1a9824a575a8'),
    'CIS_TcgcNetPingU.TcgcNetPingU.GenerateCommandText': ('0xdcd928', '99686113aa44915e654a5bf912f1fd11c65a9a8bb1e7bb88e502f83bb93258ab'),
    'CIS_TcgcGetVoltage.TcgcGetVoltage.GenerateCommandText': ('0xcb2d34', 'f61a94234ac13300af710cfc138047428aa642fb653f3caf7a660127ab64ade3'),
    'CIS_TcgcGetVoltage.TcgcGetVoltage.GetVoltage': ('0xcb2dac', 'fb63f411c152bc03c2c45998db1e6c2f1e185f7033e21281587055a244b47efb'),
    _AGENT + 'AgentLoad': ('0xcb5d0c', '3534a0cc6d80ac4eab2fd362cd4b73fadf27721da56326bc8cc58f11df4088e5'),
    _AGENT + 'PhysicalUnitGetVoltage': ('0xcbed78', 'b0cb9ecb3fedccf272e8671bf9f31d1aba3c899ed954602bf33074ca24c4d7ef'),
    _AGENT + 'LoadBurden': ('0xcbefb8', '59f4a064965ec75361c8dafe021b0cd0597d2ed60dfbd458afddd72a098bcbb7'),
    _AGENT + 'LoadClockGenEnabled': ('0xcbf618', 'b388f6fabf01df57aa74e721bdc1d4ce0b385216ccabd0f2a2ec4ce7cd2826db'),
    'CIS_TcgcDoPsync.TcgcDoPsync.GenerateCommandText': ('0xcb3098', 'c30f70ca512b472d81c8aa883e71975163bec538f3f2545fd0a3e10b1ab3fa89'),
    'CIS_TcgcGet.TcgcGet.GenerateCommandText': ('0x846d24', '21064f208efcb9cf666e1007a31e79449f52ffffdbde9513ecb59139d7b573a1'),
    'CIS_TcgcPPGet.TcgcPPGet.GenerateCommandText': ('0xcb1c1c', '00e2ace19a2f145b85c5998c6fd95772307d1f81f5fb8cf3ba7583138fc6b4cd'),
    'CIS_TCommonCBus.TCBUSUnit.DisplayableNetVoltage': ('0xf33b88', '1d1f8a38956b15c738d165536d194d074a3514d75470024e0a635ad41117b232'),
}
# Instructions whose operands encode the recovered order and display rules.
MARKERS = {
    # Run: repopulate, reset Found to Not Found, PINGU, then optional passes.
    0xea2d10: ('call', '0xea335c'),
    0xea2d56: ('mov', 'eax, dword ptr [0x13c3c8c]'),
    0xea2dfd: ('call', '0xdcd8ac'),
    0xea2e37: ('call', '0x843860'),
    0xea2e48: ('call', '0xea3514'),
    0xea2e65: ('call', '0xea3900'),
    0xea2e82: ('call', '0xea39f0'),
    0xea2e9f: ('call', '0xea3ae0'),
    0xea316a: ('call', '0xea4078'),
    0xea3181: ('mov', 'edx, 0xeab'),
    # PINGU rows: listed database units become Unit Present; others are added.
    0xea36bb: ('mov', 'eax, 0xea2b18'),
    0xea36e9: ('call', '0xea3730'),
    0xea376c: ('mov', 'ecx, 0xea38d8'),
    0xea37ab: ('mov', 'eax, 0xea2b10'),
    # Each pass loads one agent verb for every database unit.
    0xea3964: ('mov', 'eax, 0xea39d8'),
    0xea3974: ('call', 'dword ptr [ebx + 0x88]'),
    0xea3a54: ('mov', 'eax, 0xea3ac8'),
    0xea3b44: ('mov', 'eax, 0xea3bb8'),
    # Display: values only for Unit Present rows, otherwise Unknown.
    0xea3c85: ('mov', 'eax, 0xea2b18'),
    0xea3ca2: ('call', 'dword ptr [ecx + 0xe8]'),
    0xea3cba: ('mov', 'ecx, 0xea3d30'),
    0xea3dfa: ('call', '0xf2ed30'),
    0xea3e03: ('mov', 'ecx, 0xea3ea0'),
    0xea3e17: ('mov', 'ecx, 0xea3ebc'),
    0xea3e2b: ('mov', 'ecx, 0xea3ecc'),
    0xea3f96: ('call', '0xf2ec20'),
    0xea40f0: ('mov', 'eax, dword ptr [0x13c3c8c]'),
    # Command text.
    0xdcd946: ('mov', 'edx, 0xdcd960'),
    0xcb2d43: ('push', '0xcb2d78'),
    0xcb2d51: ('push', '0xcb2d90'),
    0xcb30a7: ('push', '0xcb30dc'),
    0xcb30b5: ('push', '0xcb30f0'),
    0x846d33: ('push', '0x846d70'),
    0xcb1c5d: ('push', '0xcb1c98'),
    # NetVoltage parse: default -1.0, 20 characters after '=', negatives to 0.
    0xcb2dd3: ('mov', 'dword ptr [ebp - 0xc], 0x80000000'),
    0xcb2dda: ('mov', 'word ptr [ebp - 8], 0xbfff'),
    0xcb2e24: ('mov', 'ecx, 0x14'),
    0xcb2e34: ('call', '0x842214'),
    0xcbef26: ('call', '0xcb2dac'),
    0xcbef32: ('fcomp', 'dword ptr [0xcbefb4]'),
    # Agent verbs.
    0xcb64a8: ('mov', 'edx, 0xcb7040'),
    0xcb64bc: ('call', '0xcbed78'),
    0xcb64c8: ('mov', 'edx, 0xcb7064'),
    0xcb64dc: ('call', '0xcbefb8'),
    0xcb6508: ('mov', 'edx, 0xcb70bc'),
    0xcb651c: ('call', '0xcbf618'),
    # Burden: KEYGL5/SENTEMP4 skipped; Psync then BurdenActive == "yes".
    0xcbf041: ('mov', 'edx, 0xcbf308'),
    0xcbf060: ('mov', 'edx, 0xcbf324'),
    0xcbf076: ('call', '0xf30190'),
    0xcbf091: ('call', '0xcb3010'),
    0xcbf18d: ('mov', 'edx, 0xcbf344'),
    0xcbf293: ('mov', 'edx, 0xcbf36c'),
    # Clock: KEYGL5/SENTEMP4 skipped; PP lock/start/load/get/end/unlock.
    0xcbf687: ('mov', 'edx, 0xcbf77c'),
    0xcbf6a6: ('mov', 'edx, 0xcbf798'),
    0xcbf6cb: ('call', '0xcb9884'),
    0xcbf6d9: ('call', '0xcb9d54'),
    0xcbf6e7: ('call', '0xcba510'),
    0xcbf6f2: ('mov', 'ecx, 0xcbf7b8'),
    0xcbf6fc: ('call', '0xcbb0e0'),
    0xcbf70a: ('call', '0xcbbd24'),
    0xcbf714: ('call', '0xcbbf04'),
    0xcbf71c: ('mov', 'edx, 0xcbf7e4'),
    # Voltage display: firmware 1.00/wireless N/A; exactly 0 unknown; 0.0V.
    0xf33bb5: ('mov', 'edx, 0xf33c50'),
    0xf33bd5: ('mov', 'eax, 0xf2110c'),
    0xf33bea: ('fcomp', 'dword ptr [0xf33c5c]'),
    0xf33bf9: ('mov', 'eax, dword ptr [0x13c1f64]'),
    0xf33c18: ('mov', 'eax, 0xf33c6c'),
}
LITERALS = {
    0xdcd960: 'net pingu ', 0xcb2d78: 'get ', 0xcb2d90: '  NetVoltage',
    0xcb30dc: 'do ', 0xcb30f0: ' Psync', 0x846d70: 'get ', 0xcb1c98: 'pp get ',
    0xea39d8: 'NetVoltage', 0xea3ac8: 'LoadBurden', 0xea3bb8: 'LoadClockGenEnabled',
    0xcb7040: 'NetVoltage', 0xcb7064: 'LoadBurden', 0xcb70bc: 'LoadClockGenEnabled',
    0xea38d8: 'Unknown', 0xea3d30: 'Unknown', 0xea3ecc: 'Unknown', 0xea3ea0: 'Enabled', 0xea3ebc: '-',
    0xcbf308: 'KEYGL5', 0xcbf324: 'SENTEMP4', 0xcbf344: 'BurdenActive', 0xcbf36c: 'yes',
    0xcbf77c: 'KEYGL5', 0xcbf798: 'SENTEMP4', 0xcbf7b8: 'ClockGenEnable', 0xcbf7e4: '1',
    0xf33c50: '1.00', 0xf33c6c: '0.0V',
}
# TResStringRec address (or a pointer to one) -> (string id, English text).
RESOURCES = {
    0xea2b08: (62516, 'Ready to Run'), 0xea2b10: (62517, 'Rescan Network'),
    0xea2b18: (62518, 'Unit Present'), 0xf2110c: (62307, 'N/A'),
}
RESOURCE_POINTERS = {0x13c3c8c: (62325, 'Not Found'), 0x13c1f64: (64571, 'unknown')}
FLOAT_ZERO = (0xcbefb4, 0xf33c5c)
EXCEPTION_TABLES = {
    0xea2ee2: ['CIS_TCBusObject..ECGateObjectException', 'CIS_TCGateCommand..ECGateCommand',
               'CIS_TCBusObject..ECGateSessionAlreadyOpen', 'SysUtils..Exception'],
    0xcbee9e: ['CIS_TcgcGet..EcgcGetParameterNotFound', 'CIS_TcgcGet..EcgcGetBadObject',
               'CIS_TCGateCommand..ECGateCommandTimeOut', 'CIS_TcgcGet..EcgcGetUnitNotFound',
               'CIS_TcgcGet..EcgcGetNetworkNotFound'],
    0xcbf1b1: ['CIS_TcgcGet..EcgcGetParameterNotFound', 'CIS_TcgcGet..EcgcGetBadObject',
               'CIS_TcgcGet..EcgcGetNetworkNotFound', 'CIS_TcgcGet..EcgcGetUnitNotFound',
               'CIS_TcgcGet..EcgcGetApplicationNotFound', 'CIS_TCGateCommand..EcgcGetSyntaxError',
               'CIS_TcgcGet..EcgcAccessDenied', 'CIS_TcgcDoQSync..ECGateErrorPSyncUnitNotFound'],
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect(exe_path: Path, map_path: Path) -> dict:
    exe_raw, map_raw = exe_path.read_bytes(), map_path.read_bytes()
    if _sha(exe_raw) != EXE_SHA256 or _sha(map_raw) != MAP_SHA256:
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = pefile.PE(data=exe_raw, fast_load=True)
    image.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
    if image.FILE_HEADER.Machine != 0x14c:
        raise ValueError('Expected pinned x86 Toolkit image')
    base = image.OPTIONAL_HEADER.ImageBase

    def data(address, size):
        return image.get_data(address - base, size)

    segment_bases = {
        segment: base + next(section.VirtualAddress for section in image.sections
                             if section.Name.startswith(name))
        for segment, name in ((1, b'.text'), (2, b'.itext'))
    }
    symbols: dict[int, set[str]] = {}
    for line in map_raw.decode('ascii').splitlines():
        match = re.fullmatch(r'\s*000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*', line)
        if match:
            symbols.setdefault(int(match[2], 16) + segment_bases[int(match[1])], set()).add(match[3])
    starts = sorted(symbols)
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    spans = {}
    ranges = []
    for name, (start_hex, expected_sha) in METHODS.items():
        start = int(start_hex, 16)
        if name not in symbols.get(start, ()):
            raise ValueError('Missing exact original MAP symbol: ' + name)
        end = next((address for address in starts if address > start), None)
        if end is None or not 0 < end - start <= 32768:
            raise ValueError('Unbounded original method: ' + name)
        raw = data(start, end - start)
        if _sha(raw) != expected_sha:
            raise ValueError('Original method changed: ' + name)
        ranges.append((start, end))
        spans[name] = {'start': start_hex, 'end': hex(end), 'bytes': len(raw), 'sha256': expected_sha}
    # Delphi methods embed exception tables, so each marker is decoded at its
    # own pinned address inside a hashed span instead of by linear sweep.
    for address, expected in MARKERS.items():
        decoded = [(instruction.mnemonic, instruction.op_str)
                   for instruction in decoder.disasm(data(address, 16), address, count=1)]
        if not any(start <= address < end for start, end in ranges) or decoded != [expected]:
            raise ValueError(f'Original diagnostics instruction changed at {address:#x}')

    def unicode_literal(address):
        code_page, element, _reference, length = struct.unpack('<HHii', data(address - 12, 12))
        if element != 2 or not 0 < length < 256:
            raise ValueError(f'No Delphi UnicodeString literal at {address:#x}')
        return data(address, 2 * length).decode('utf-16-le')

    for address, text in LITERALS.items():
        if unicode_literal(address) != text:
            raise ValueError(f'Original literal changed at {address:#x}')
    strings = {}
    for entry in image.DIRECTORY_ENTRY_RESOURCE.entries:
        if entry.id == 6:
            for block in entry.directory.entries:
                for language in block.directory.entries:
                    table = image.get_data(language.data.struct.OffsetToData, language.data.struct.Size)
                    offset = 0
                    for index in range(16):
                        length = int.from_bytes(table[offset:offset + 2], 'little')
                        offset += 2
                        strings[(block.id - 1) * 16 + index] = table[offset:offset + 2 * length].decode('utf-16-le')
                        offset += 2 * length

    def resource(record):
        module, identifier = struct.unpack('<II', data(record, 8))
        if module <= base:
            raise ValueError(f'No TResStringRec at {record:#x}')
        return identifier, strings.get(identifier)

    for record, expected in RESOURCES.items():
        if resource(record) != expected:
            raise ValueError(f'Original resource string changed at {record:#x}')
    for pointer, expected in RESOURCE_POINTERS.items():
        if resource(struct.unpack('<I', data(pointer, 4))[0]) != expected:
            raise ValueError(f'Original resource string pointer changed at {pointer:#x}')
    for address in FLOAT_ZERO:
        if struct.unpack('<f', data(address, 4))[0] != 0.0:
            raise ValueError(f'Original voltage comparison constant changed at {address:#x}')
    names = {address: sorted(values) for address, values in symbols.items()}
    for table, expected in EXCEPTION_TABLES.items():
        count = struct.unpack('<I', data(table, 4))[0]
        classes = []
        for index in range(count):
            reference, _handler = struct.unpack('<II', data(table + 4 + 8 * index, 8))
            vmt = struct.unpack('<I', data(reference, 4))[0] - 0x58
            classes.append(next((name for name in names.get(vmt, ()) if '..' in name), None))
        if classes != expected:
            raise ValueError(f'Original exception table changed at {table:#x}')
    if _sha(exe_path.read_bytes()) != EXE_SHA256 or _sha(map_path.read_bytes()) != MAP_SHA256:
        raise ValueError('Original files changed during inspection')
    return {
        'format': 'cbus-toolkit-unit-diagnostics-static-v1',
        'original_exe_sha256': EXE_SHA256,
        'original_map_sha256': MAP_SHA256,
        'original_executed': False,
        'dialog': {'class': 'TfrmPingUnits', 'help_topics': [20132, 20136],
                   'entry': 'TfrmUnitsNode.actPingExecute -> TfrmPingUnits.SetNetwork'},
        'method_spans': spans,
        'verified_instructions': {hex(address): {'mnemonic': mnemonic, 'operands': operands}
                                  for address, (mnemonic, operands) in MARKERS.items()},
        'verified_literals': {hex(address): text for address, text in LITERALS.items()},
        'verified_resource_strings': {str(identifier): text for identifier, text in
                                      [*RESOURCES.values(), *RESOURCE_POINTERS.values()]},
        'verified_exception_tables': {hex(address): classes for address, classes in EXCEPTION_TABLES.items()},
        'recovered_sequence': [
            'Rebuild rows from the network unit manager (custom address-ascending order); '
            'Unit Found=Not Found, Voltage/Burden/Clock blank',
            'net pingu <network>; each listed database address -> Unit Present; each other '
            'address -> new row Unknown/Rescan Network with Unknown for every checked option',
            'Get Network Voltage: for every database unit, agent verb NetVoltage -> '
            'get <unit>  NetVoltage (skips wireless and non-units)',
            'Get Network Burden: for every database unit, agent verb LoadBurden -> '
            'KEYGL5/SENTEMP4 set no burden; otherwise do <unit> Psync then get <unit> BurdenActive; '
            '"yes" means enabled',
            'Get Network Clock: for every database unit, agent verb LoadClockGenEnabled -> '
            'KEYGL5/SENTEMP4 set clock disabled; otherwise PP lock/start/load/get ClockGenEnable/'
            'end/unlock; "1" means enabled',
            'If every row still reads Not Found, show error 0xEAB',
        ],
        'display_rules': {
            'values_only_for_unit_present': True,
            'absent_unit_value': 'Unknown',
            'voltage': 'firmware "1.00" or wireless network -> N/A; exactly 0 -> unknown; else FormatFloat 0.0V',
            'voltage_parse': 'text after "=" (20 characters) as float; default -1.0; negative -> 0',
            'burden_clock': 'Enabled or -',
            'per_unit_get_failures': ('Voltage and burden agent reads swallow the listed C-Gate '
                                      'exceptions, leaving the previous cached value'),
        },
        'limit': ('This verifies one pinned original source chain, not interactive Toolkit '
                  'execution, the exact PP session naming/load-all flags, error-dialog text '
                  'selection for IDs 0xEAB..0xEAD, or physical electrical measurements.'),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
