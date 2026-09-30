"""Execute pinned classic DLT display load/save fragments with synthetic storage.

The original x86 fragments, indicator conversions and unit property accessors
execute in Unicorn. Only object lookup, attribute storage and Delphi Variant
primitives are fixture hooks. EXE/MAP and decoded I_DLT.xml are private inputs;
the report contains hashes, source locations, derived facts and synthetic
observations, never vendor instruction bytes. No Windows process, C-Gate or
physical unit is accessed, and complete form execution is not claimed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
import xml.etree.ElementTree as ET

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX as EAX, UC_X86_REG_EBP as EBP,
                               UC_X86_REG_ECX as ECX, UC_X86_REG_EDX as EDX,
                               UC_X86_REG_EIP as EIP, UC_X86_REG_ESP as ESP)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classic_dlt_controls_original import (AGENT_NAME, UNIT_NAME, ClassicControlsProbe,
                                           EXE_SHA256, MAP_SHA256, sha)  # noqa: E402

FORMAT = 'cbus-classic-dlt-display-original-v1'
FRAGMENTS = {
    'indicator_load': (0x121C05D, 0x121C082),
    'invert_load': (0x121C0A4, 0x121C0C4),
    'clock_load': (0x121C0C4, 0x121C0E6),
    'indicator_save': (0x121D292, 0x121D2C1),
    'invert_save': (0x121D2F2, 0x121D320),
    'clock_save': (0x121D320, 0x121D351),
}
METHODS = {
    'integer_to_mode': ('CIS_TCBusDynamicLabelInputUnit.IntegerToCBusDynamicIndicatorMode', 0xCE45F0),
    'mode_to_integer': ('CIS_TCBusDynamicLabelInputUnit.CBusDynamicIndicatorModeToInteger', 0xCE4630),
    'indicator_get': (UNIT_NAME + 'GetIndicatorMode', 0xCE4B84),
    'indicator_set': (UNIT_NAME + 'SetIndicatorMode', 0xCE5098),
    'invert_get': (UNIT_NAME + 'GetInvertDisplay', 0xCE4BE0),
    'invert_set': (UNIT_NAME + 'SetInvertDisplay', 0xCE4ECC),
    'clock_get': (UNIT_NAME + 'GetShowClock', 0xCE4C2C),
    'clock_set': (UNIT_NAME + 'SetShowClock', 0xCE4F28),
    'checkbox_bindings': ('CIS_TcdDLTInputIndicators8.TcdDLTInputIndicators8.SetupFlashComponents', 0xFFAD64),
    'indicator_radio': ('CIS_TcdDLTInputIndicators8.TcdDLTInputIndicators8.HandleIndicatorOverrideRadioChange', 0xFFB81C),
}
FIELDS = {
    'indicator': ('IndicatorMode', 'IndicatorMode', 0x1E8, 0x2C8),
    'invert': ('InvertDisplay', 'InvertDisplay', 0x1F0, 0x2D0),
    'clock': ('HideClock', 'ShowClock', 0x1F4, 0x2D4),
}
FRAME, STACK, AGENT, UNIT = 0x20008000, 0x20006000, 0x30001000, 0x30002000
PP, PROPERTY, VMT = 0x30003000, 0x30004000, 0x30005000
GET_BOOL, GET_INT, GET_VARIANT, SET_VARIANT, RETURN = (
    0x30006000, 0x30006100, 0x30006200, 0x30006300, 0x3000F000)


class ClassicDisplayProbe(ClassicControlsProbe):
    def __init__(self, executable: Path, symbols: Path):
        super().__init__(executable, symbols)
        self.display_methods = {}
        for key, (name, start) in METHODS.items():
            if self.by_name.get(name) != start:
                raise ValueError('Unexpected original display method address: ' + name)
            self.display_methods[key] = self.method(name)

    def static_facts(self, specification: Path) -> dict:
        raw = specification.read_bytes()
        profiles = json.loads((Path(__file__).parent / 'fixtures/dlt-profile-facts.json').read_text())
        if sha(raw) != profiles['specifications']['I_DLT.xml']['sha256']:
            raise ValueError('Decoded I_DLT.xml differs from pinned DLT profile facts')
        params = {p.findtext('Name'): p for p in ET.fromstring(raw[raw.index(b'<'):]).iter('Param')}
        expected = {
            'IndicatorMode': {'Type': 'int', 'Address': '$35', 'BitAddress': '0', 'BitSize': '2', 'DefaultValue': '1'},
            'InvertDisplay': {'Type': 'bit', 'Address': '$35', 'BitAddress': '4', 'BitSize': None, 'DefaultValue': '0'},
            'HideClock': {'Type': 'bit', 'Address': '$35', 'BitAddress': '5', 'BitSize': None, 'DefaultValue': '0'},
        }
        for name, fields in expected.items():
            assert {field: params[name].findtext(field) for field in fields} == fields, name
        agent_bindings, unit_bindings = self.bindings('agent_constructor'), self.bindings('unit_constructor')
        for pp_name, property_name, agent_offset, unit_offset in FIELDS.values():
            assert agent_bindings[pp_name] == hex(agent_offset), pp_name
            assert unit_bindings[property_name] == hex(unit_offset), property_name
        setup = self.display_methods['checkbox_bindings']
        checkbox_facts = []
        for name, offset in (('InvertDisplay', 0x2B8), ('ShowClock', 0x2BC)):
            rows = setup['instructions']
            indices = [i for i, row in enumerate(rows) if setup['literal_at'].get(row[0]) == name]
            assert len(indices) == 1
            index = indices[0]
            assert rows[index - 1][1:] == ('mov', f'eax, dword ptr [eax + {hex(offset)}]')
            assert rows[index + 1][1:] == ('call', hex(self.by_name['CIS_FlashGUI.PrepareFlashCheckbox']))
            checkbox_facts.append({'property': name, 'form_control_offset': hex(offset),
                                   'binding_address': hex(rows[index][0]),
                                   'binding_call': 'CIS_FlashGUI.PrepareFlashCheckbox'})
        radio = self.display_methods['indicator_radio']['instructions']
        assignments = [(m, op) for _, m, op in radio if (m, op) in (
            ('mov', 'dl, 2'), ('xor', 'edx, edx'), ('mov', 'dl, 1'))]
        assert assignments == [('mov', 'dl, 2'), ('xor', 'edx, edx'), ('mov', 'dl, 1')]
        assert sum((m, op) == ('call', hex(METHODS['indicator_set'][1])) for _, m, op in radio) == 3
        return {
            'source': {'executable_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256,
                       'I_DLT.xml_sha256': sha(raw)},
            'methods': {key: {'symbol': METHODS[key][0], **self.span(method['start'], method['end'])}
                        for key, method in self.display_methods.items()},
            'constructor_methods': {key: {'symbol': self.methods[key]['name'] if 'name' in self.methods[key]
                                         else (AGENT_NAME if key == 'agent_constructor' else UNIT_NAME) + 'InternalCreate',
                                         **self.span(self.methods[key]['start'], self.methods[key]['end'])}
                                    for key in ('agent_constructor', 'unit_constructor')},
            'fragments': {key: self.span(*span) for key, span in FRAGMENTS.items()},
            'parameters': {name: {'address': 53, 'bit': int(fields['BitAddress']),
                                  'width': int(fields['BitSize'] or '1'), 'default': int(fields['DefaultValue'])}
                           for name, fields in expected.items()},
            'attribute_fields': {pp_name: {'agent_offset': hex(agent_offset),
                                           'unit_property': property_name, 'unit_offset': hex(unit_offset)}
                                 for pp_name, property_name, agent_offset, unit_offset in FIELDS.values()},
            'checkbox_bindings': checkbox_facts,
            'rules': {
                'indicator_load': {'0': 'off', '1': 'normal', '2': 'on', '3': 'on'},
                'indicator_save': {'off': 0, 'normal': 1, 'on': 2},
                'invert_display': 'InvertDisplay loads and saves without inversion',
                'show_clock': 'ShowClock = not HideClock on load; HideClock = not ShowClock on save',
                'indicator_radio': 'First checked radio selects on (enum 2); second selects off (enum 0); otherwise normal (enum 1)',
            },
        }

    def _display_machine(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(self.base, (len(self.memory) + 4095) & ~4095)
        u.mem_write(self.base, self.memory)
        for address, size in ((0, 4096), (0x20000000, 0x10000), (0x30000000, 0x10000)):
            u.mem_map(address, size)

        def put(address, value):
            u.mem_write(address, struct.pack('<I', value & 0xFFFFFFFF))

        def read(address):
            return struct.unpack('<I', u.mem_read(address, 4))[0]

        put(FRAME - 4, AGENT)
        self.storage = {}
        for index, (control, (_, _, agent_offset, unit_offset)) in enumerate(FIELDS.items()):
            pp, attribute = PP + index * 0x100, PROPERTY + index * 0x100
            self.storage[control] = (pp, attribute)
            put(AGENT + agent_offset, pp)
            put(UNIT + unit_offset, attribute)
            put(pp, VMT)
            put(attribute, VMT)
        for offset, target in ((0x88, GET_BOOL), (0x94, GET_INT), (0x74, GET_VARIANT), (0x7C, SET_VARIANT)):
            put(VMT + offset, target)
        allowed = list(FRAGMENTS.values()) + [(method['start'], method['end'])
            for key, method in self.display_methods.items() if key not in ('checkbox_bindings', 'indicator_radio')]

        def ret(value=None):
            stack = u.reg_read(ESP)
            if value is not None:
                u.reg_write(EAX, value & 0xFFFFFFFF)
            u.reg_write(EIP, read(stack))
            u.reg_write(ESP, stack + 4)

        def hook(_machine, address, _size, _data):
            if address == RETURN:
                u.emu_stop()
            elif address == self.by_name[AGENT_NAME + 'GetDLTUnit']:
                assert u.reg_read(EAX) == AGENT
                ret(UNIT)
            elif address in (GET_BOOL, GET_INT):
                ret(self.values[u.reg_read(EAX)])
            elif address == GET_VARIANT:
                put(u.reg_read(EDX) + 8, self.values[u.reg_read(EAX)])
                ret()
            elif address == SET_VARIANT:
                attribute = u.reg_read(EAX)
                assert attribute in self.values
                self.values[attribute] = read(u.reg_read(EDX) + 8)
                ret()
            elif address == self.by_name['Variants.@VarFromInt']:
                put(u.reg_read(EAX) + 8, u.reg_read(EDX))
                ret()
            elif address == self.by_name['Variants.@VarFromBool']:
                put(u.reg_read(EAX) + 8, int(bool(u.reg_read(EDX) & 255)))
                ret()
            elif address == self.by_name['Variants.@VarToInteger']:
                ret(read(u.reg_read(EAX) + 8))
            elif address == self.by_name['Variants.@VarClr']:
                ret()
            elif any(start <= address < stop for start, stop in allowed):
                self.instruction_count += 1
            else:
                raise AssertionError(f'Unexpected original display execution at {address:#x}')
        u.hook_add(UC_HOOK_CODE, hook)
        return u

    def _execute(self, start, stop, value=0):
        if not hasattr(self, 'display_machine'):
            self.display_machine = self._display_machine()
        u = self.display_machine
        self.instruction_count = 0
        for register, initial in ((EBP, FRAME), (ESP, STACK), (EAX, value & 0xFFFFFFFF), (EDX, 0), (ECX, 0)):
            u.reg_write(register, initial)
        u.mem_write(STACK, struct.pack('<I', RETURN))
        u.emu_start(start, stop, count=2000)
        assert u.reg_read(EIP) == stop, 'Original display instructions failed to complete'
        return u.reg_read(EAX)

    def run(self, control, operation, value):
        if not hasattr(self, 'display_machine'):
            self.display_machine = self._display_machine()
        pp, attribute = self.storage[control]
        self.values = {address: 165 for pair in self.storage.values() for address in pair}
        source, target = (pp, attribute) if operation == 'load' else (attribute, pp)
        self.values[source] = int(value)
        before = dict(self.values)
        self._execute(*FRAGMENTS[f'{control}_{operation}'], value=AGENT)
        assert all(self.values[address] == initial for address, initial in before.items() if address != target)
        output = self.values[target]
        if control != 'indicator':
            assert output in (0, 1)
            output = bool(output)
        return {'control': control, 'operation': operation, 'input': value, 'output': output,
                'other_attributes_preserved': True, 'original_instruction_count': self.instruction_count}

    def observations(self):
        rows = []
        for raw in range(4):
            row = self.run('indicator', 'load', raw)
            assert row['output'] == (0, 1, 2, 2)[raw]
            rows.append(row)
        for mode in range(3):
            row = self.run('indicator', 'save', mode)
            assert row['output'] == mode
            rows.append(row)
        for control in ('invert', 'clock'):
            for operation in ('load', 'save'):
                for value in (False, True):
                    row = self.run(control, operation, value)
                    assert row['output'] is (value if control == 'invert' else not value)
                    rows.append(row)
        return rows

    def conversions(self):
        rows = []
        for method, inputs in (
                ('integer_to_mode', (-2147483648, -1, 0, 1, 2, 3, 4, 255, 256, 2147483647)),
                ('mode_to_integer', range(256))):
            results = []
            for value in inputs:
                output = self._execute(self.display_methods[method]['start'], RETURN, value)
                if method == 'integer_to_mode':
                    output &= 255  # Original return type is a byte-sized enum.
                    expected = {0: 0, 1: 1, 2: 2, 3: 2}.get(value, 1)
                else:
                    expected = value if value in (0, 1, 2) else 1
                assert output == expected, (method, value, output)
                results.append([value, output])
            rows.append({'method': method, 'case_count': len(results),
                         'cases_sha256': sha(json.dumps(results, separators=(',', ':')).encode()),
                         'inputs': list(inputs) if method == 'integer_to_mode' else 'all enum bytes 0..255',
                         'rule': '0 -> 0; 1 -> 1; 2,3 -> 2; other -> 1' if method == 'integer_to_mode'
                                 else '0 -> 0; 1 -> 1; 2 -> 2; other -> 1'})
        return rows


def inspect(executable: Path, symbols: Path, specification: Path) -> dict:
    probe = ClassicDisplayProbe(executable, symbols)
    facts = probe.static_facts(specification)
    return {'format': FORMAT, **facts, 'observations': probe.observations(),
            'conversion_checks': probe.conversions(), 'passed': True,
            'original_full_form_executed': False, 'physical_hardware_verified': False,
            'boundary': 'Original x86 load/save fragments, conversion methods and property accessors with synthetic attribute storage and Delphi Variant hooks; no full GUI, native C-Gate, database persistence, display rendering or physical acceptance.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--specification', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.executable, args.map, args.specification)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'format': FORMAT, 'observations': len(report['observations']),
                      'conversion_cases': sum(row['case_count'] for row in report['conversion_checks']),
                      'output': str(args.output)}))


if __name__ == '__main__':
    main()
