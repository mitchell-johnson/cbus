"""Replay the pinned original per-flavour classic DLT broadcast routine.

Original branch, formatting, Unicode scan, dynamic/font composition and font-ID
instructions run in Unicorn. Object getters, Delphi string primitives and the
outgoing command boundary are synthetic hooks. Injected command failures stop
at the call boundary; Delphi exception unwinding and transport do not execute.
No executable bytes, vendor data, real project or physical I/O are exported.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX as EAX, UC_X86_REG_EBP as EBP,
                               UC_X86_REG_ECX as ECX, UC_X86_REG_EDX as EDX,
                               UC_X86_REG_EFLAGS as EFLAGS, UC_X86_REG_EIP as EIP,
                               UC_X86_REG_ESP as ESP)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classic_dlt_controls_original import (EXE_SHA256, MAP_SHA256,
                                            ClassicControlsProbe)  # noqa: E402

FORMAT = 'cbus-classic-dlt-broadcast-original-v1'
AGENT, FLAVOUR, TAG, GROUP, APPLICATION, LANGUAGE, LANGUAGE_TYPE = (
    0x30001000, 0x30002000, 0x30003000, 0x30004000,
    0x30005000, 0x30006000, 0x30007000)
STACK, RETURN = 0x20008000, 0x3000F000
PREFIX = 'CIS_TGroupLanguageFlavourCGateAgent.TGroupLanguageFlavourCGateAgent.'
FLAVOUR_PREFIX = 'CIS_TGroupLanguage.TGroupLanguageFlavour.'
METHODS = {
    'broadcast': PREFIX + 'BroadcastDLTLabel',
    'text': PREFIX + 'GetTextDataString',
    'dynamic': PREFIX + 'GetDynamicDataString',
    'font': PREFIX + 'GetFontDynamicDataString',
    'unicode': PREFIX + 'ContainUnicode',
    'font_predicate': 'CIS_TDLTGraphic.IsDLTFontTagValue',
    'font_image_id': 'CIS_TDLTGraphic.GetImageIDFromFontTagValue',
    'comma_count': 'CIS_Strings.CountCharsInString',
}


class BroadcastProbe(ClassicControlsProbe):
    def __init__(self, executable: Path, symbols: Path):
        super().__init__(executable, symbols)
        self.methods = {name: self.method(symbol) for name, symbol in METHODS.items()}

    def source_facts(self):
        return {
            'source': {'executable_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256},
            'methods': {name: {'symbol': METHODS[name], **self.span(m['start'], m['end'])}
                        for name, m in self.methods.items()},
            'boundary': {
                'original_instructions_executed': list(METHODS),
                'synthetic_hooks': ['object getters and explicit object identities',
                                    'Delphi string primitive operations and integer formatting',
                                    'CommandApplicationLabel argument capture'],
                'failure_injection': 'Stop at selected CommandApplicationLabel entry; does not execute Delphi exception unwinding',
                'command_builder_executed': False,
                'native_cgate_executed': False,
                'full_original_dialog_executed': False,
                'physical_io': False,
            },
        }

    def _machine(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(self.base, (len(self.memory) + 4095) & ~4095)
        u.mem_write(self.base, self.memory)
        u.mem_map(0, 4096)
        u.mem_map(0x20000000, 0x10000)
        u.mem_map(0x30000000, 0x100000)

        def put(address, value):
            u.mem_write(address, struct.pack('<I', value & 0xFFFFFFFF))

        def read(address):
            return struct.unpack('<I', u.mem_read(address, 4))[0]

        def string(address):
            return (bytes(u.mem_read(address, read(address - 4) * 2))
                    .decode('utf-16-le', 'surrogatepass') if address else '')

        def allocate(value):
            if not value:
                return 0
            raw = value.encode('utf-16-le', 'surrogatepass')
            target = self.heap + 12
            assert target + len(raw) + 2 < 0x30100000
            u.mem_write(target - 12, struct.pack('<III', 1200, 0xFFFFFFFF, len(raw) // 2))
            u.mem_write(target, raw + b'\0\0')
            self.heap = (target + len(raw) + 5) & ~3
            return target

        def ret(value=None, cleanup=0):
            stack = u.reg_read(ESP)
            if value is not None:
                u.reg_write(EAX, value)
            u.reg_write(EIP, read(stack))
            u.reg_write(ESP, stack + 4 + cleanup)

        def return_string(value):
            put(u.reg_read(EDX), allocate(value))
            ret()

        getters = {
            self.by_name[PREFIX + 'GroupLanguageFlavour']: FLAVOUR,
            self.by_name[PREFIX + 'GroupLanguage']: LANGUAGE,
            self.by_name[FLAVOUR_PREFIX + 'GetDLTTag']: TAG,
            self.by_name['CIS_TGroupLanguage.TGroupLanguage.GetLanguageType']: LANGUAGE_TYPE,
            self.by_name['CIS_TCommonCBus.TCBusGroup.GetApplication']: APPLICATION,
        }
        allowed = [(m['start'], m['end']) for m in self.methods.values()]

        def hook(_u, address, _size, _data):
            if any(start <= address < stop for start, stop in allowed):
                self.instructions += 1
            if address == RETURN:
                u.emu_stop()
            elif address in getters:
                ret(getters[address])
            elif address == self.by_name[PREFIX + 'GetGroup']:
                ret(GROUP if self.input['group_present'] else 0)
            elif address == self.by_name['CIS_TLanguageTag.TLanguageTag.GetTagType']:
                ret(self.input['tag_type'])
            elif address == self.by_name['CIS_TLanguageTag.TLanguageTag.GetTagValue']:
                return_string(self.input['value'])
            elif address == self.by_name[FLAVOUR_PREFIX + 'GetDLTDynamicData']:
                return_string(self.input['dynamic_data'])
            elif address == self.by_name[FLAVOUR_PREFIX + 'GetFlavour']:
                ret(self.input['variant'])
            elif address == self.by_name['CIS_TLanguageType.TLanguageType.GetIdentifier']:
                ret(self.input['language'])
            elif address == self.by_name['CIS_TCBusObject.TCGateObject.GetAddressAsInteger']:
                assert u.reg_read(EAX) == GROUP
                ret(self.input['group'])
            elif address == self.by_name[PREFIX + 'GetApplicationTypeString']:
                return_string(self.input['application_type'])
            elif address == self.by_name[PREFIX + 'GetLevelString']:
                return_string('-' if self.input['level'] is None else str(self.input['level']))
            elif address == self.by_name['CIS_TCBusObject.TCGateObject.GetOIDAsCGateID']:
                assert u.reg_read(EAX) == APPLICATION
                return_string(self.input['application_id'])
            elif address in {self.by_name['System.@UStrLAsg'], self.by_name['System.@UStrAsg']}:
                put(u.reg_read(EAX), u.reg_read(EDX))
                ret()
            elif address == self.by_name['System.@UStrCat3']:
                put(u.reg_read(EAX), allocate(string(u.reg_read(EDX)) + string(u.reg_read(ECX))))
                ret()
            elif address == self.by_name['System.@UStrCat']:
                put(u.reg_read(EAX), allocate(string(read(u.reg_read(EAX))) + string(u.reg_read(EDX))))
                ret()
            elif address == self.by_name['System.@UStrCatN']:
                count, stack = u.reg_read(EDX), u.reg_read(ESP)
                value = ''.join(string(read(stack + 4 * i)) for i in range(count, 0, -1))
                put(u.reg_read(EAX), allocate(value))
                ret(cleanup=count * 4)
            elif address == self.by_name['System.@UStrEqual']:
                equal = string(u.reg_read(EAX)) == string(u.reg_read(EDX))
                u.reg_write(EFLAGS, (u.reg_read(EFLAGS) & ~0x40) | (0x40 if equal else 0))
                ret()
            elif 'SysUtils.IntToStr' in self.symbols.get(address, set()):
                value = u.reg_read(EAX)
                return_string(str(value if value < 0x80000000 else value - 0x100000000))
            elif 'SysUtils.IntToHex' in self.symbols.get(address, set()):
                put(u.reg_read(ECX), allocate(f'{u.reg_read(EAX):0{u.reg_read(EDX)}X}'))
                ret()
            elif 'System.Pos' in self.symbols.get(address, set()):
                ret(string(u.reg_read(EDX)).find(string(u.reg_read(EAX))) + 1)
            elif address == self.by_name['System.@UStrCopy']:
                raw = string(u.reg_read(EAX)).encode('utf-16-le', 'surrogatepass')
                start, count = u.reg_read(EDX), u.reg_read(ECX)
                count = count if count < 0x80000000 else 0
                value = raw[max(start - 1, 0) * 2:(max(start - 1, 0) + count) * 2]
                put(read(u.reg_read(ESP) + 4), allocate(value.decode('utf-16-le', 'surrogatepass')))
                ret(cleanup=4)
            elif address == self.by_name['System.@UStrArrayClr']:
                ret()
            elif address == self.by_name[PREFIX + 'CommandApplicationLabel']:
                stack = u.reg_read(ESP)
                args = [string(read(stack + 4 * i)) for i in range(6, 0, -1)]
                self.commands.append({
                    'application_type': string(u.reg_read(EDX)),
                    'application_id': string(u.reg_read(ECX)),
                    **dict(zip(('language', 'group', 'level', 'variant', 'type', 'data'), args)),
                    'broadcast_marked_at_entry': bool(u.mem_read(FLAVOUR + 0xC4, 1)[0]),
                })
                if len(self.commands) == self.input['fail_command']:
                    self.stopped_at_failure = True
                    u.emu_stop()
                else:
                    ret(cleanup=24)
            elif address == self.by_name['System.@Assert']:
                self.assertion = string(u.reg_read(EAX))
                u.emu_stop()
            elif not any(start <= address < stop for start, stop in allowed):
                raise AssertionError(f'Unexpected original execution at {address:#x}')

        u.hook_add(UC_HOOK_CODE, hook)
        return u

    def run(self, value, *, tag_type=0, variant=1, language=1, group=20,
            level=None, application_type='LIGHTING', application_id='254/56',
            dynamic_data='', image_size=64, already_broadcast=False,
            group_present=True, fail_command=0):
        if not hasattr(self, 'machine'):
            self.machine = self._machine()
        self.input = {
            'value': value, 'tag_type': tag_type, 'variant': variant, 'language': language,
            'group': group, 'level': level, 'application_type': application_type,
            'application_id': application_id, 'dynamic_data': dynamic_data,
            'image_size': image_size, 'already_broadcast': already_broadcast,
            'group_present': group_present, 'fail_command': fail_command,
        }
        self.heap, self.commands, self.instructions = 0x30010000, [], 0
        self.assertion, self.stopped_at_failure = None, False
        u = self.machine
        u.mem_write(FLAVOUR + 0xC0, struct.pack('<I', image_size))
        u.mem_write(FLAVOUR + 0xC4, bytes([int(already_broadcast)]))
        u.mem_write(STACK, struct.pack('<I', RETURN))
        u.reg_write(EAX, AGENT)
        u.reg_write(ESP, STACK)
        u.reg_write(EBP, 0)
        u.reg_write(EFLAGS, 2)
        u.emu_start(self.methods['broadcast']['start'], RETURN, count=10000)
        assert u.reg_read(EIP) == RETURN or self.assertion or self.stopped_at_failure
        return {'input': self.input, 'result': {
            'commands': self.commands,
            'broadcast_marked': bool(u.mem_read(FLAVOUR + 0xC4, 1)[0]),
            'completed_routine': u.reg_read(EIP) == RETURN,
            'stopped_at_command_failure': self.stopped_at_failure,
            'assertion': self.assertion,
            'original_instructions': self.instructions,
        }}

    def observations(self):
        rows = []
        for variant in range(1, 5):
            for value in ('', '<Default>', 'Kitchen', 'Café', '\u00ff', '01234567890123456789',
                          '01234567890123漢', '😀'):
                rows.append(self.run(value, variant=variant))
            rows.append(self.run('5', tag_type=1, variant=variant, language=202))
            rows.append(self.run('100', tag_type=2, variant=variant, language=64,
                                 dynamic_data='00' * 128))
            rows.append(self.run('101,Face,12,0,0,0,0,0,0,Text', tag_type=3,
                                 variant=variant, language=64, dynamic_data='A5' * 128))
        for tag_type, value, data in ((0, 'Kitchen', ''), (1, '5', ''),
                                     (2, '100', '00' * 128),
                                     (3, '101,Face,12,0,0,0,0,0,0,Text', 'A5' * 128)):
            rows.append(self.run(value, tag_type=tag_type, dynamic_data=data, already_broadcast=True))
            rows.append(self.run(value, tag_type=tag_type, dynamic_data=data, group_present=False))
            rows.append(self.run(value, tag_type=tag_type, dynamic_data=data, fail_command=1))
            if tag_type in (2, 3):
                rows.append(self.run(value, tag_type=tag_type, dynamic_data=data, fail_command=2))
        rows.extend([
            self.run('Trigger', application_type='TRIGGER', application_id='!1234', language=2, group=7, level=42),
            self.run('Enable', application_type='ENABLE', application_id='254/203', language=3, group=8),
            self.run('100,a,b,c,d,e,f,g,h,i', tag_type=2, dynamic_data='55' * 128),
            self.run('101,Face,12', tag_type=3, dynamic_data='AA' * 128),
            self.run('Kitchen', variant=0), self.run('Kitchen', variant=5),
        ])
        return rows


def inspect(executable: Path, symbols: Path) -> dict:
    probe = BroadcastProbe(executable, symbols)
    return {'format': FORMAT, **probe.source_facts(), 'observations': probe.observations()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--map', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = inspect(args.executable, args.map)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'format': FORMAT, 'cases': len(report['observations']),
                      'original_instructions': sum(row['result']['original_instructions'] for row in report['observations'])}))


if __name__ == '__main__':
    main()
