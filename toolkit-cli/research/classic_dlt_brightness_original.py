"""Original classic DLT duration, pressed brightness and nightlight PP mapping.

Runs bounded original x86 agent fragments and model accessors with synthetic
attribute storage and Delphi Variant helpers. No GUI, C-Gate or device executes.
Private executable/specification bytes are never included in the report.
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
import struct
import sys
import xml.etree.ElementTree as ET

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX as EAX, UC_X86_REG_EBP as EBP,
                               UC_X86_REG_EDX as EDX, UC_X86_REG_EIP as EIP,
                               UC_X86_REG_ESP as ESP)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classic_dlt_controls_original import (AGENT_NAME, UNIT_NAME, EXE_SHA256,
                                            MAP_SHA256, ClassicControlsProbe, sha)  # noqa: E402

FORMAT = 'cbus-classic-dlt-brightness-original-v1'
CORE_AGENT = 'CIS_TCoreNeoInputCGateAgent.TCoreNeoInputCGateAgent.'
NEO_UNIT = 'CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.'
DLT_CLASS = 'CIS_TCBusDynamicLabelInputUnit..TCBusDynamicLabelInputUnit'
CORE_SPEC_SHA = '5a26c87fe11a87208815436e00e07ad46e1b65981adab9c93e743a3e1c763af7'
FRAGMENTS = {
    'core_load': (0xCCB251, 0xCCB2F9),
    'core_save': (0xCCC53B, 0xCCC6B7),
    'dlt_load': (0x121BF65, 0x121C05D),
    'dlt_save': (0x121D195, 0x121D292),
}
PP_FIELDS = {'EnableNightlight': 0x164, 'EnableNightlightControl': 0x168,
             'FirstKeyThrowAway': 0x170, 'IndicatorPressedLevel': 0x174,
             'TimerDuration': 0x178, 'EnablePageFallback': 0x1D8,
             'EnableIndicatorPressedLevel': 0x1DC, 'EnableNightlightOnToggleKey': 0x1E0,
             'EnableNightlightOnUserKeys': 0x1E4}
MODEL_FIELDS = {'EnableNightlightControl': 0x21C, 'FirstKeyThrowAway': 0x220,
                'KeyPressBrightnessDuration': 0x228, 'KeyPressBrightnessLevel': 0x22C,
                'NightlightEnabled': 0x238, 'NightlightForced': 0x23C,
                'EnablePageFallback': 0x2B8, 'EnableIndicatorPressed': 0x2BC,
                'EnableNightlightOnToggle': 0x2C0, 'EnableNightlightOnKeys': 0x2C4}
BIT_FIELDS = {'EnableNightlight': 0, 'EnablePageFallback': 2,
              'EnableIndicatorPressedLevel': 3, 'FirstKeyThrowAway': 4,
              'EnableNightlightOnUserKeys': 5, 'EnableNightlightOnToggleKey': 6,
              'EnableNightlightControl': 7}
METHODS = {
    'core_constructor': CORE_AGENT + 'InternalCreate',
    'neo_constructor': NEO_UNIT + 'InternalCreate',
    'dlt_constructor': UNIT_NAME + 'InternalCreate',
    'agent_constructor': AGENT_NAME + 'InternalCreate',
    'core_load': CORE_AGENT + 'AfterLoadProgrammingInformation',
    'core_save': CORE_AGENT + 'BeforeSaveProgrammingInformation',
    'dlt_load': AGENT_NAME + 'AfterLoadProgrammingInformation',
    'dlt_save': AGENT_NAME + 'BeforeSaveProgrammingInformation',
}
for _prefix, _properties in ((NEO_UNIT, ('KeyPressBrightnessDuration', 'KeyPressBrightnessLevel',
                                        'NightlightEnabled', 'NightlightForced', 'EnableNightlightControl')),
                             (UNIT_NAME, ('EnablePageFallback', 'EnableIndicatorPressed',
                                          'EnableNightlightOnToggle', 'EnableNightlightOnKeys'))):
    for _property, _action in itertools.product(_properties, ('Get', 'Set')):
        if _action == 'Get' and _property == 'NightlightForced':
            continue
        METHODS[_action + _property] = _prefix + _action + _property

FRAME, STACK, AGENT, UNIT = 0x20008000, 0x20006000, 0x30001000, 0x30002000
VMT, GET_VALUE, GET_SCALAR, SET_VALUE = 0x3000A000, 0x3000B000, 0x3000B100, 0x3000B200


def digest(rows):
    return sha(json.dumps(rows, separators=(',', ':'), sort_keys=True).encode())


class BrightnessProbe(ClassicControlsProbe):
    def __init__(self, executable: Path, symbols: Path):
        super().__init__(executable, symbols)
        self.methods = {key: self.method(name) for key, name in METHODS.items()}
        self.family = {offset: self.method(self.slot(DLT_CLASS, offset))
                       for offset in (0x1F4, 0x20C, 0x210)}

    def static_facts(self, specification_directory: Path):
        pinned = json.loads((Path(__file__).parent / 'fixtures/dlt-profile-facts.json').read_text())
        layouts, specs = {}, {}
        for filename, expected in (('I_NEOCORE.xml', CORE_SPEC_SHA),
                                   ('I_DLT.xml', pinned['specifications']['I_DLT.xml']['sha256'])):
            raw = (specification_directory / filename).read_bytes()
            assert sha(raw) == expected, filename
            specs[filename] = expected
            for parameter in ET.fromstring(raw[raw.index(b'<'):]).iter('Param'):
                name = parameter.findtext('Name')
                if name in PP_FIELDS:
                    layouts[name] = {key: parameter.findtext(key) for key in
                                     ('Type', 'Address', 'BitAddress', 'BitSize', 'MinValue',
                                      'MaxValue', 'DefaultValue', 'Protection')
                                     if parameter.findtext(key) is not None}
        for name, bit in BIT_FIELDS.items():
            assert layouts[name]['Address'] == '$34'
            assert layouts[name]['BitAddress'] == str(bit)
        for name, bit in (('TimerDuration', 0), ('IndicatorPressedLevel', 4)):
            assert layouts[name] == {'Type': 'int', 'Address': '$33', 'BitAddress': str(bit),
                                     'BitSize': '4', 'MinValue': '$00', 'MaxValue': '$0F',
                                     'DefaultValue': '$0F', 'Protection': 'checksum'}
        agent_bindings = self.bindings('core_constructor') | self.bindings('agent_constructor')
        model_bindings = self.bindings('neo_constructor') | self.bindings('dlt_constructor')
        assert all(agent_bindings[name] == hex(offset) for name, offset in PP_FIELDS.items())
        assert all(model_bindings[name] == hex(offset) for name, offset in MODEL_FIELDS.items())
        assert ('mov', 'byte ptr [ebp - 5], 1') in [(m, op) for _, m, op in self.family[0x210]['instructions']]
        for offset in (0x1F4, 0x20C):
            assert ('mov', 'byte ptr [ebp - 5], 0') in [(m, op) for _, m, op in self.family[offset]['instructions']]
        return {
            'source': {'executable_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256,
                       'specification_sha256': specs},
            'methods': {key: {'symbol': METHODS[key], **self.span(m['start'], m['end'])}
                        for key, m in self.methods.items()},
            'fragments': {key: self.span(*value) for key, value in FRAGMENTS.items()},
            'family_slots': {hex(offset): {'symbol': self.slot(DLT_CLASS, offset),
                                          **self.span(m['start'], m['end'])}
                             for offset, m in self.family.items()},
            'parameter_layouts': layouts,
            'agent_fields': {name: hex(offset) for name, offset in PP_FIELDS.items()},
            'model_fields': {name: hex(offset) for name, offset in MODEL_FIELDS.items()},
            'rules': {
                'duration_and_pressed_level': 'Raw low/high nibbles copy directly to model integers and back; no arithmetic or clipping in these accessors',
                'load_fallback_and_pressed': 'Each PP flag AND KeyPressBrightnessDuration > 0',
                'load_nightlight': 'NightlightEnabled=true; NightlightForced=not EnableNightlight; control, user keys and toggle key flags copy directly',
                'save_nightlight': 'EnableNightlight is explicitly programmable and forced false; control and both key flags copy current model values unconditionally',
                'first_key': 'FirstKeyThrowAway copies directly both ways for DLT; GUI availability/clearing is separate',
                'save_model_flags': 'Current page fallback and pressed-enable model booleans copy directly without a duration gate at save',
                'boundary': 'These agent fragments do not initialize or run GUI checkbox events; GUI canonicalization is a separate receipt',
            },
        }

    def _machine(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(self.base, (len(self.memory) + 4095) & ~4095)
        u.mem_write(self.base, self.memory)
        for address in (0, 0x20000000, 0x30000000):
            u.mem_map(address, 0x10000)
        put = lambda address, value: u.mem_write(address, struct.pack('<I', value))
        put(FRAME - 4, AGENT)
        put(UNIT, self.vmt(DLT_CLASS))
        self.pp_attributes, self.model_attributes = {}, {}
        for fields, owner, start, target in ((PP_FIELDS, AGENT, 0x30004000, self.pp_attributes),
                                            (MODEL_FIELDS, UNIT, 0x30006000, self.model_attributes)):
            for index, (name, offset) in enumerate(fields.items()):
                attribute = start + index * 0x100
                target[name] = attribute
                put(owner + offset, attribute)
                put(attribute, VMT)
        for offset, target in ((0x74, GET_VALUE), (0x88, GET_SCALAR),
                               (0x94, GET_SCALAR), (0x7C, SET_VALUE)):
            put(VMT + offset, target)
        allowed = list(FRAGMENTS.values())
        allowed.extend((method['start'], method['end']) for key, method in self.methods.items()
                       if key.startswith(('Get', 'Set')))
        allowed.extend((method['start'], method['end']) for method in self.family.values())
        lookups = {self.by_name[CORE_AGENT + 'CBusUnit'], self.by_name[AGENT_NAME + 'GetDLTUnit']}

        def read(address):
            return struct.unpack('<I', u.mem_read(address, 4))[0]

        def ret(value=None):
            stack = u.reg_read(ESP)
            if value is not None:
                u.reg_write(EAX, value)
            u.reg_write(EIP, read(stack))
            u.reg_write(ESP, stack + 4)

        def hook(_u, address, _size, _data):
            if address in lookups:
                ret(UNIT)
            elif address == GET_SCALAR:
                ret(self.values[u.reg_read(EAX)])
            elif address == GET_VALUE:
                put(u.reg_read(EDX) + 8, self.values[u.reg_read(EAX)])
                ret()
            elif address == SET_VALUE:
                self.values[u.reg_read(EAX)] = read(u.reg_read(EDX) + 8)
                ret()
            elif address == self.by_name['Variants.@VarFromBool']:
                put(u.reg_read(EAX) + 8, int(bool(u.reg_read(EDX) & 255)))
                ret()
            elif address == self.by_name['Variants.@VarFromInt']:
                put(u.reg_read(EAX) + 8, u.reg_read(EDX))
                ret()
            elif address == self.by_name['Variants.@VarNot']:
                put(u.reg_read(EAX) + 8, int(not read(u.reg_read(EAX) + 8)))
                ret()
            elif address == self.by_name['Variants.@VarToBool']:
                ret(int(bool(read(u.reg_read(EAX) + 8))))
            elif address == self.by_name['Variants.@VarClr']:
                ret()
            elif not any(start <= address < stop for start, stop in allowed):
                raise AssertionError(f'Unexpected original execution at {address:#x}')
        u.hook_add(UC_HOOK_CODE, hook)
        return u

    def run(self, raw33, raw34):
        if not hasattr(self, 'machine'):
            self.machine = self._machine()
        u = self.machine
        self.values = {attribute: 0 for attribute in
                       (*self.pp_attributes.values(), *self.model_attributes.values())}
        self.values[self.pp_attributes['TimerDuration']] = raw33 & 15
        self.values[self.pp_attributes['IndicatorPressedLevel']] = raw33 >> 4
        for name, bit in BIT_FIELDS.items():
            self.values[self.pp_attributes[name]] = (raw34 >> bit) & 1
        model = None
        for phase in ('core_load', 'dlt_load', 'core_save', 'dlt_save'):
            u.reg_write(EBP, FRAME)
            u.reg_write(ESP, STACK)
            start, stop = FRAGMENTS[phase]
            u.emu_start(start, stop, count=3000)
            assert u.reg_read(EIP) == stop, phase
            if phase == 'dlt_load':
                model = {name: self.values[attribute] for name, attribute in self.model_attributes.items()}
        pp = {name: self.values[attribute] for name, attribute in self.pp_attributes.items()}
        saved33 = pp['TimerDuration'] | pp['IndicatorPressedLevel'] << 4
        saved34 = raw34 & 2  # DisableTimerFlash is outside these fragments.
        for name, bit in BIT_FIELDS.items():
            saved34 |= pp[name] << bit
        assert all(u.mem_read(self.pp_attributes[name] + 0x58, 1) == b'\x01'
                   for name in ('TimerDuration', 'IndicatorPressedLevel', 'EnableNightlight', 'EnableNightlightControl'))
        return {'byte33': raw33, 'byte34': raw34, 'loaded': model,
                'saved_byte33': saved33, 'saved_byte34': saved34}

    def observations(self):
        rows = [self.run(raw33, 0xFD) for raw33 in range(256)]
        rows.extend(self.run((15 << 4) | duration, raw34)
                    for duration, raw34 in itertools.product((0, 1, 2, 15), range(256)))
        for row in rows:
            duration, pressed = row['byte33'] & 15, row['byte33'] >> 4
            assert row['loaded']['KeyPressBrightnessDuration'] == duration
            assert row['loaded']['KeyPressBrightnessLevel'] == pressed
            assert row['loaded']['NightlightEnabled'] == 1
            assert row['loaded']['NightlightForced'] == (not bool(row['byte34'] & 1))
            assert row['saved_byte33'] == row['byte33']
            assert row['saved_byte34'] == row['byte34'] & (0xF2 if duration == 0 else 0xFE)
        selected = [row for row in rows[256:] if row['byte34'] in (0, 1, 0xFC, 0xFD, 0xFF)]
        return {'cases': len(rows), 'cases_sha256': digest(rows),
                'numeric_cases': 256, 'flag_cases': 1024, 'selected': selected}


def inspect(executable: Path, symbols: Path, specification_directory: Path):
    probe = BrightnessProbe(executable, symbols)
    return {'format': FORMAT, **probe.static_facts(specification_directory),
            'observations': probe.observations(),
            'boundary': 'Original bounded agent and model instructions with synthetic attributes and Variant helpers; no full GUI, native C-Gate, project persistence or hardware acceptance.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--specifications', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.executable, args.map, args.specifications)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'format': FORMAT, 'cases': report['observations']['cases'], 'output': str(args.output)}))


if __name__ == '__main__':
    main()
