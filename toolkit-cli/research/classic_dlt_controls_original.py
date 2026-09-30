"""Recover classic DLT dynamic-update controls from pinned Toolkit instructions.

The EXE/MAP and decoded I_DLT.xml remain private inputs. Output contains only
hashes, identifiers, offsets, derived rules and synthetic emulator observations.
Unicorn executes the original load/save inversion fragments and the complete
SaveEnableDynamicLabelsOnly body; boolean attribute storage, Delphi Variant
helpers, unit lookup and every programming/network operation are fixture hooks.
No C-Gate, native Windows process, project or physical unit is accessed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX as EAX, UC_X86_REG_EBP as EBP,
                               UC_X86_REG_ECX as ECX, UC_X86_REG_EDX as EDX,
                               UC_X86_REG_EIP as EIP, UC_X86_REG_ESP as ESP)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit  # noqa: E402
from classic_dlt_language_original import language_facts  # noqa: E402

FORMAT = 'cbus-classic-dlt-controls-original-v1'
AGENT_NAME = 'CIS_TCBusDynamicLabelInputCGateAgent.TCBusDynamicLabelInputCGateAgent.'
UNIT_NAME = 'CIS_TCBusDynamicLabelInputUnit.TCBusDynamicLabelInputUnit.'
BASE_NAME = 'CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.'
METHOD_NAMES = {
    'agent_constructor': AGENT_NAME + 'InternalCreate',
    'unit_constructor': UNIT_NAME + 'InternalCreate',
    'getter': UNIT_NAME + 'GetBlockDynamicUpdates',
    'setter': UNIT_NAME + 'SetBlockDynamicUpdates',
    'load': AGENT_NAME + 'AfterLoadProgrammingInformation',
    'save': AGENT_NAME + 'BeforeSaveProgrammingInformation',
    'dedicated_save': AGENT_NAME + 'SaveEnableDynamicLabelsOnly',
    'agent_save': AGENT_NAME + 'AgentSave',
    'base_save': BASE_NAME + 'SaveProgrammingInformation',
    'checkbox_change': 'CIS_TddKEYL5.TddKEYL5.HandleBlockDynamicUpdatesChange',
    'wizard_save': 'CIS_TfrmDLTBlockDynamicUpdates.TfrmDLTBlockDynamicUpdates.SetUnitProgramming',
}
FRAGMENTS = {'load': (0x121C106, 0x121C128), 'save': (0x121D3A0, 0x121D400)}
FRAME, STACK = 0x20008000, 0x20006000
AGENT, UNIT, PP_ATTRIBUTE, PROPERTY = 0x30001000, 0x30002000, 0x30003000, 0x30004000
VMT, GET_BOOLEAN, SET_VALUE, RETURN = 0x30005000, 0x30006000, 0x30006100, 0x3000F000


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ClassicControlsProbe(_Toolkit):
    def __init__(self, executable: Path, symbols: Path):
        exe, mapping = executable.read_bytes(), symbols.read_bytes()
        if sha(exe) != EXE_SHA256 or sha(mapping) != MAP_SHA256:
            raise ValueError('Expected pinned Toolkit 1.18.0.2754 executable and MAP')
        super().__init__(exe, mapping)
        self.methods = {key: self.method(name) for key, name in METHOD_NAMES.items()}
        self.memory = self.pe.get_memory_mapped_image()

    def span(self, start: int, stop: int) -> dict:
        return {'start': hex(start), 'stop': hex(stop),
                'sha256': sha(self.pe.get_data(start - self.base, stop - start))}

    def bindings(self, key: str) -> dict[str, str]:
        current, result = None, {}
        for address, mnemonic, operands in self.methods[key]['instructions']:
            if mnemonic == 'push' and address in self.methods[key]['literal_at']:
                current = self.methods[key]['literal_at'][address]
            match = re.fullmatch(r'dword ptr \[edx \+ (0x[0-9a-f]+)\], eax', operands)
            if mnemonic == 'mov' and match and current:
                result[current] = match[1]
                current = None
        return result

    def static_facts(self, spec: Path) -> dict:
        spec_raw = spec.read_bytes()
        expected = json.loads((Path(__file__).parent / 'fixtures/dlt-profile-facts.json').read_text())
        if sha(spec_raw) != expected['specifications']['I_DLT.xml']['sha256']:
            raise ValueError('Decoded I_DLT.xml differs from pinned DLT profile facts')
        parameter = next(p for p in ET.fromstring(spec_raw[spec_raw.index(b'<'):]).iter('Param')
                         if p.findtext('Name') == 'EnableDynamicLabels')
        signature = {key: parameter.findtext(key) for key in ('Name', 'Type', 'Address', 'BitAddress', 'DefaultValue')}
        assert signature == {'Name': 'EnableDynamicLabels', 'Type': 'bit', 'Address': '$3E',
                             'BitAddress': '6', 'DefaultValue': '1'}
        assert self.bindings('agent_constructor')['EnableDynamicLabels'] == '0x200'
        assert self.bindings('unit_constructor')['BlockDynamicUpdates'] == '0x2dc'
        required = {
            'load': [('mov', 'eax, dword ptr [eax + 0x200]'), ('xor', 'al, 1')],
            'save': [('cmp', 'byte ptr [eax + 0xc0], 0'), ('xor', 'dl, 1'), ('mov', 'dl, 1')],
            'getter': [('mov', 'eax, dword ptr [eax + 0x2dc]')],
            'setter': [('mov', 'eax, dword ptr [eax + 0x2dc]')],
            'base_save': [('mov', 'byte ptr [edx + 0xc0], al')],
        }
        for key, markers in required.items():
            pairs = [(m, op) for _, m, op in self.methods[key]['instructions']]
            assert all(marker in pairs for marker in markers), key
        # Pin the base-class Database verb -> flag assignment as one contiguous source range.
        instructions = [row for row in self.methods['base_save']['instructions'] if 0xCBDC9F <= row[0] < 0xCBDCBC]
        assert self.literal(int(instructions[3][2].split(', ')[1], 16)) == 'Database'
        assert instructions[-3][1:] == ('call', hex(self.by_name['CIS_TCustomFlashObject.TFlashAgent.IsInVerbs']))
        assert instructions[-1][1:] == ('mov', 'byte ptr [edx + 0xc0], al')
        return {
            'source': {'executable_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256,
                       'I_DLT.xml_sha256': sha(spec_raw)},
            'methods': {key: {'symbol': METHOD_NAMES[key], **self.span(m['start'], m['end'])}
                        for key, m in self.methods.items()},
            'fragments': {key: self.span(*value) for key, value in FRAGMENTS.items()},
            'database_flag_binding': self.span(0xCBDC9F, 0xCBDCBC),
            'parameter': {'name': 'EnableDynamicLabels', 'address': 62, 'bit': 6, 'default': 1},
            'attribute_fields': {'EnableDynamicLabels': 'agent+0x200', 'BlockDynamicUpdates': 'unit+0x2dc'},
            'rules': {
                'load': 'BlockDynamicUpdates = not EnableDynamicLabels',
                'database_save': 'EnableDynamicLabels = not BlockDynamicUpdates',
                'network_initial_save': 'EnableDynamicLabels = true before label programming',
                'database_flag': 'agent+0xc0 = IsInVerbs("Database") in base SaveProgrammingInformation',
                'dedicated_save': 'If BlockDynamicUpdates is true, set EnableDynamicLabels to 0 and save; otherwise no operation',
                'dedicated_session': 'Reuse an active session; otherwise Lock, Start, Load, SetOne, Save, End, Unlock',
                'agent_save_exclusions': ['Database', 'AlignUnit', 'DBReaddress'],
                'checkbox_change': 'Unit+0x16e is assigned not BlockDynamicUpdates; form label colours are refreshed',
            },
        }

    def _machine(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(self.base, (len(self.memory) + 4095) & ~4095)
        u.mem_write(self.base, self.memory)
        for address, size in ((0, 4096), (0x20000000, 0x10000), (0x30000000, 0x10000)):
            u.mem_map(address, size)
        put = lambda address, value: u.mem_write(address, struct.pack('<I', value))
        put(FRAME - 4, AGENT)
        put(AGENT + 0x200, PP_ATTRIBUTE)
        put(UNIT + 0x2DC, PROPERTY)
        for attribute in (PP_ATTRIBUTE, PROPERTY):
            put(attribute, VMT)
        put(VMT + 0x88, GET_BOOLEAN)
        put(VMT + 0x7C, SET_VALUE)
        self.allowed = [FRAGMENTS['load'], FRAGMENTS['save']]
        self.allowed.extend((self.methods[k]['start'], self.methods[k]['end'])
                            for k in ('getter', 'setter', 'dedicated_save'))
        operations = {self.by_name[BASE_NAME + 'ParameterProgramming' + name]: (name, cleanup)
                      for name, cleanup in [('Lock', 0), ('Start', 4), ('Load', 4), ('SetOne', 4),
                                            ('Save', 4), ('End', 4), ('Unlock', 0)]}

        def read_int(address):
            return struct.unpack('<I', u.mem_read(address, 4))[0]

        def ret(value=None, cleanup=0):
            stack = u.reg_read(ESP)
            if value is not None:
                u.reg_write(EAX, value)
            u.reg_write(EIP, read_int(stack))
            u.reg_write(ESP, stack + 4 + cleanup)

        def hook(_machine, address, _size, _data):
            if address == RETURN:
                u.emu_stop()
            elif address == self.by_name[AGENT_NAME + 'GetDLTUnit']:
                ret(UNIT)
            elif address == GET_BOOLEAN:
                ret(self.values[u.reg_read(EAX)])
            elif address == SET_VALUE:
                self.values[u.reg_read(EAX)] = read_int(u.reg_read(EDX) + 8)
                ret()
            elif address == self.by_name['Variants.@VarFromBool']:
                put(u.reg_read(EAX) + 8, int(bool(u.reg_read(EDX) & 255)))
                ret()
            elif address == self.by_name['Variants.@VarClr']:
                ret()
            elif address == self.by_name['CIS_TCommonCBus.TCBUSUnit.GetIsInProgrammingSession']:
                ret(int(self.in_session))
            elif address in operations:
                name, cleanup = operations[address]
                record = {'operation': name}
                if name == 'SetOne':
                    record.update(parameter=self.literal(u.reg_read(ECX)),
                                  value=self.literal(read_int(u.reg_read(ESP) + 4)),
                                  database=bool(u.reg_read(EDX) & 255))
                if name == 'Save':
                    record.update(timeout_ms=read_int(u.reg_read(ESP) + 4),
                                  database=bool(u.reg_read(EDX) & 255),
                                  flag=bool(u.reg_read(ECX) & 255))
                self.calls.append(record)
                ret(cleanup=cleanup)
            elif not any(start <= address < stop for start, stop in self.allowed):
                raise AssertionError(f'Unexpected original execution at {address:#x}')
        u.hook_add(UC_HOOK_CODE, hook)
        return u

    def run(self, kind: str, *, enabled=False, blocked=False, database=True, in_session=False):
        if not hasattr(self, 'machine'):
            self.machine = self._machine()
        u = self.machine
        self.values = {PP_ATTRIBUTE: int(enabled), PROPERTY: int(blocked)}
        self.calls, self.in_session = [], in_session
        u.mem_write(AGENT + 0xC0, bytes([int(database)]))
        u.reg_write(EBP, FRAME)
        u.reg_write(ESP, STACK)
        u.reg_write(EAX, AGENT)
        u.mem_write(STACK, struct.pack('<I', RETURN))
        if kind == 'dedicated_save':
            start, stop = self.methods[kind]['start'], RETURN
        else:
            start, stop = FRAGMENTS[kind]
        u.emu_start(start, stop, count=1000)
        assert u.reg_read(EIP) == stop, f'{kind} failed to complete'
        return {'enabled': bool(self.values[PP_ATTRIBUTE]), 'blocked': bool(self.values[PROPERTY]),
                'calls': self.calls}

    def observations(self):
        rows = []
        for enabled in (False, True):
            result = self.run('load', enabled=enabled)
            assert result['blocked'] is not enabled
            rows.append({'operation': 'load', 'input_enabled': enabled, 'result': result})
        for database in (False, True):
            for blocked in (False, True):
                result = self.run('save', database=database, blocked=blocked)
                assert result['enabled'] == (not blocked if database else True)
                rows.append({'operation': 'save', 'database': database, 'input_blocked': blocked, 'result': result})
        for in_session in (False, True):
            for blocked in (False, True):
                result = self.run('dedicated_save', in_session=in_session, blocked=blocked)
                expected = (['SetOne', 'Save'] if in_session else ['Lock', 'Start', 'Load', 'SetOne', 'Save', 'End', 'Unlock']) if blocked else []
                assert [call['operation'] for call in result['calls']] == expected
                if blocked:
                    assert next(c for c in result['calls'] if c['operation'] == 'SetOne') == {
                        'operation': 'SetOne', 'parameter': 'EnableDynamicLabels', 'value': '0', 'database': False}
                    assert next(c for c in result['calls'] if c['operation'] == 'Save') == {
                        'operation': 'Save', 'timeout_ms': 30000, 'database': False, 'flag': True}
                rows.append({'operation': 'dedicated_save', 'in_session': in_session, 'input_blocked': blocked, 'result': result})
        return rows


def inspect(executable: Path, symbols: Path, specification: Path) -> dict:
    probe = ClassicControlsProbe(executable, symbols)
    return {'format': FORMAT, **probe.static_facts(specification), 'observations': probe.observations(),
            'language_and_global_controls': language_facts(probe),
            'boundary': 'Original x86 instructions with synthetic boolean storage and hooked external calls; no full form, native C-Gate, database persistence or physical acceptance.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--specification', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.executable, args.map, args.specification)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'format': FORMAT, 'observations': len(report['observations']), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
