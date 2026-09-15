"""Static original thermostat scheduling selection; no original execution."""
from pathlib import Path
import hashlib
import json
import re
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

ROOT = Path('/Users/mitchell/source/cbus/toolkit-cli')
OUT = Path(__file__).resolve().parent
EXE = ROOT / 'research/vendor/toolkit/app/CBusToolkit.exe'
MAP = EXE.with_suffix('.map')
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
inputs = {str(p): digest(p) for p in (EXE, MAP, Path(__file__))}
assert inputs[str(EXE)] == '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
assert inputs[str(MAP)] == 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
pe = pefile.PE(str(EXE)); base = pe.OPTIONAL_HEADER.ImageBase
text_rva = next(s.VirtualAddress for s in pe.sections if s.Name.startswith(b'.text'))
symbols = {}
for line in MAP.read_text(encoding='cp1252').splitlines():
    match = re.fullmatch(r'\s*0001:([0-9A-F]+)\s+(\S+)\s*', line)
    if match:
        symbols.setdefault(base + text_rva + int(match[1], 16), []).append(match[2])
names = {name: address for address, entries in symbols.items() for name in entries}
selected = ['CIS_TcdThermostatScheduling.TcdThermostatScheduling.' + name for name in (
    'HandleCreateLevelsClick', 'RemoteScheduleGroupsSelected',
    'HandleRemoteScheduleEnableAfterChange', 'CreateRemoteScheduleLevels',
    'CreateRemoteScheduleEnableLevels', 'CreateRemoteScheduleDisableLevels',
    'CreateRemoteScheduleOverrideLevels')]
selected += ['CIS_TThermostat.TProgrammableThermostat.RemoteScheduleLevelsRequired',
             'CIS_TCommonCBus.TCBusNetwork.GetEnableControlApplication',
             'CIS_TThermostat.TZoneManagerService.GetRemoteScheduleOnGroup',
             'CIS_TThermostat.TZoneManagerService.GetRemoteScheduleOffGroup',
             'CIS_TThermostat.TZoneManagerService.GetRemoteScheduleOverrideGroup']
addresses = sorted(symbols); engine = Cs(CS_ARCH_X86, CS_MODE_32); rows = []
for index, name in enumerate(selected):
    address = names[name]; end = next(a for a in addresses if a > address)
    assert 0 < end - address < 65536
    raw = pe.get_data(address - base, end - address); lines = []; calls = []
    for instruction in engine.disasm(raw, address):
        suffix = ''
        if instruction.mnemonic == 'call':
            target = int(instruction.op_str, 16) if re.fullmatch(r'0x[0-9a-f]+', instruction.op_str) else None
            labels = list(dict.fromkeys(symbols.get(target, []))) if target else []
            calls.append({'site': hex(instruction.address), 'target': hex(target) if target else instruction.op_str, 'symbols': labels})
            if labels: suffix = ' ; ' + labels[0]
        lines.append(f'{instruction.address:08x}: {instruction.mnemonic} {instruction.op_str}{suffix}')
    filename = f'{index:02}-' + name.rsplit('.', 1)[-1] + '.asm'
    with (OUT / filename).open('x') as stream: stream.write('\n'.join(lines) + '\n')
    rows.append({'symbol': name, 'address': hex(address), 'end': hex(end),
                 'bytes_sha256': hashlib.sha256(raw).hexdigest(), 'disassembly': filename, 'calls': calls})
assert {p: digest(Path(p)) for p in inputs} == inputs
report = {'scope': 'Static original instruction inspection; no original execution, UI, backend or hardware calls',
          'inputs': inputs, 'inputs_unchanged': True, 'methods': rows}
with (OUT / 'report.json').open('x') as stream: stream.write(json.dumps(report, indent=2) + '\n')
print(json.dumps({'methods': len(rows), 'report_sha256': digest(OUT / 'report.json')}))
