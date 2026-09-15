"""Read-only exact Toolkit level-name and project-lock dependency inspection."""
from pathlib import Path
import hashlib
import json
import re
import struct
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

ROOT = Path('/Users/mitchell/source/cbus/toolkit-cli')
OUT = Path(__file__).resolve().parent
EXE = ROOT / 'research/vendor/toolkit/app/CBusToolkit.exe'
MAP = EXE.with_suffix('.map')
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
inputs = {str(p): digest(p) for p in (EXE, MAP, Path(__file__), ROOT / 'src/cbus_toolkit/native.py')}
assert inputs[str(EXE)] == '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
pe = pefile.PE(str(EXE))
base = pe.OPTIONAL_HEADER.ImageBase
text_rva = next(s.VirtualAddress for s in pe.sections if s.Name.startswith(b'.text'))
symbols = {}
for line in MAP.read_text(encoding='cp1252').splitlines():
    match = re.fullmatch(r'\s*0001:([0-9A-F]+)\s+(\S+)\s*', line)
    if match:
        symbols.setdefault(base + text_rva + int(match[1], 16), []).append(match[2])
names = {name: address for address, entries in symbols.items() for name in entries}
selected = [name for name in names if name.startswith('CIS_TThermostatCommon.TZones.')]
selected += ['CIS_TThermostat.LevelToZones', 'CIS_TThermostatCommon.IntegerToZones',
             'CIS_TThermostatCommon.ZonesToInteger', 'CIS_TCommonCBus.TProject.BeginSaveLock',
             'CIS_TCommonCBus.TProject.EndSaveLock', 'CIS_TCommonCBus.TLevelManager.FindLevelByAddress']
addresses = sorted(symbols)
engine = Cs(CS_ARCH_X86, CS_MODE_32)
rows = []
for index, name in enumerate(selected):
    address = names[name]
    end = next(a for a in addresses if a > address)
    assert 0 < end - address < 65536
    raw = pe.get_data(address - base, end - address)
    lines, calls = [], []
    for instruction in engine.disasm(raw, address):
        suffix = ''
        if instruction.mnemonic == 'call':
            target = int(instruction.op_str, 16) if re.fullmatch(r'0x[0-9a-f]+', instruction.op_str) else None
            labels = list(dict.fromkeys(symbols.get(target, []))) if target else []
            calls.append({'site': hex(instruction.address), 'target': hex(target) if target else instruction.op_str, 'symbols': labels})
            if labels:
                suffix = ' ; ' + labels[0]
        lines.append(f'{instruction.address:08x}: {instruction.mnemonic} {instruction.op_str}{suffix}')
    filename = f'{index:02}-' + name.rsplit('.', 1)[-1] + '.asm'
    with (OUT / filename).open('x') as stream:
        stream.write('\n'.join(lines) + '\n')
    rows.append({'symbol': name, 'address': hex(address), 'end': hex(end),
                 'bytes_sha256': hashlib.sha256(raw).hexdigest(), 'disassembly': filename, 'calls': calls})
strings = []
for address in (0x11308a4, 0x11308ec, 0x1130934, 0x1130b18, 0x1130b34, 0x1130b44, 0x1130b68):
    header = pe.get_data(address - base - 12, 12)
    code_page, element_size, reference_count, length = struct.unpack('<HHiI', header)
    assert code_page == 1200 and element_size == 2 and 0 < length < 4096
    raw = pe.get_data(address - base, length * 2)
    strings.append({'address': hex(address), 'header_hex': header.hex(), 'length': length,
                    'value': raw.decode('utf-16-le'), 'bytes_sha256': hashlib.sha256(raw).hexdigest()})
assert {p: digest(Path(p)) for p in inputs} == inputs
report = {'scope': 'Static exact original instruction and literal inspection only; no original execution or backend mutation',
          'inputs': inputs, 'inputs_unchanged': True, 'methods': rows, 'strings': strings}
with (OUT / 'report.json').open('x') as stream:
    stream.write(json.dumps(report, indent=2) + '\n')
print(json.dumps({'methods': len(rows), 'strings': strings, 'report_sha256': digest(OUT / 'report.json')}))
