"""Execute pinned PIR appendix wrappers and inherited Classic action instructions.

Fixture hooks replace the inherited key body, Delphi strings, class/attribute
accessors and display helpers. This is bounded instruction execution only: no
original PP loader, generated full page, GUI, project or device runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX as EAX, UC_X86_REG_EDX as EDX
from unicorn.x86_const import UC_X86_REG_ECX as ECX, UC_X86_REG_EIP as EIP, UC_X86_REG_ESP as ESP

from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256
from project_documentor_pir_static import BODIES
from project_documentor_neo_usage_original import OriginalNeoActionSelectorProbe, METHODS as ACTIONS, cases


def inspect(executable, mapping):
    exe, symbols = executable.read_bytes(), mapping.read_bytes()
    if hashlib.sha256(exe).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
        raise ValueError('Original Toolkit EXE/MAP hash mismatch')
    image = _Toolkit(exe, symbols)
    memory = image.pe.get_memory_mapped_image()
    observations, methods = [], {}
    for st7, name in enumerate(BODIES):
        method = image.method(name)
        methods[name] = {'start': hex(method['start']), 'end': hex(method['end']), 'sha256': method['sha256']}
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 4096)
        u.mem_map(image.base, (len(memory) + 4095) & ~4095)
        u.mem_write(image.base, memory)
        u.mem_map(0x30000000, 0x20000)
        stack, unit, writer, vmt, add, stop = (0x30008000, 0x30001000, 0x30002000,
                                             0x30003000, 0x30004000, 0x30005000)
        group, arena = 0x30006000, 0x30010000
        put = lambda address, value: u.mem_write(address, struct.pack('<I', value))
        get = lambda address: struct.unpack('<I', u.mem_read(address, 4))[0]
        def read_string(address):
            return '' if not address else bytes(u.mem_read(address, get(address - 4) * 2)).decode('utf-16le')
        def write_string(destination, value):
            nonlocal arena
            encoded = value.encode('utf-16le')
            address = arena + 12
            arena += (len(encoded) + 31) & ~15
            u.mem_write(address - 12, struct.pack('<HHiI', 1200, 2, -1, len(value)) + encoded + b'\0\0')
            put(destination, address)
        put(writer, vmt)
        put(vmt + 0x38, add)
        inherited = image.by_name['CIS_TClassicKeyInputDocumentor.TClassicKeyInputDocumentor.DocumentHTML']
        owner = ('CIS_TCBusST7SensorUnit.TCBusST7MultisensorUnit.GetOccupancyEnableGroup' if st7
                 else 'CIS_TCBusPirSensorInputUnit.TCBusPirSensorInputUnit.GetEnableGroup')
        get_group, get_off = image.by_name[owner], image.by_name[owner + 'Off']
        state = {}
        def ret(value=0, args=0):
            sp = u.reg_read(ESP)
            u.reg_write(EAX, value)
            u.reg_write(EIP, get(sp))
            u.reg_write(ESP, sp + 4 + args * 4)
        def hook(_u, address, _size, _data):
            a, d = u.reg_read(EAX), u.reg_read(EDX)
            if address == stop:
                u.emu_stop()
            elif address == inherited:
                assert d == writer and u.reg_read(ECX) == unit
                state['calls'].append('inherited_classic_body')
                state['lines'].append('<synthetic inherited body>')
                ret()
            elif address == image.by_name['System.@IsClass']:
                state['calls'].append('class_test')
                ret(int(state['class_match']))
            elif address == get_group:
                assert a == unit
                ret(group)
            elif address == get_off:
                state['calls'].append('polarity')
                ret(int(state['off']))
            elif address == image.by_name['CIS_TCommonCBus.TCBusGroup.IsUnused']:
                assert a == group
                ret(int(state['unused']))
            elif address == image.by_name['CIS_TDocumentorCommon.DisplayHTMLGroup']:
                assert a == group
                write_string(d, '<fixture group>')
                ret()
            elif address == image.by_name['System.@UStrCatN']:
                sp = u.reg_read(ESP)
                strings = [read_string(get(sp + 4 + i * 4)) for i in range(d)]
                write_string(a, ''.join(reversed(strings)))
                ret(args=d)
            elif address == image.by_name['System.@UStrArrayClr']:
                ret()
            elif address == add:
                assert a == writer
                state['lines'].append(read_string(d))
                ret()
            elif not method['start'] <= address < method['end']:
                raise AssertionError(f'Unexpected original execution at {address:#x}')
        u.hook_add(UC_HOOK_CODE, hook)
        for class_match, unused, off in ((False, False, False), (False, True, True),
                                         (True, True, False), (True, True, True),
                                         (True, False, False), (True, False, True)):
            state.clear()
            state.update(st7=bool(st7), class_match=class_match, unused=unused, off=off, calls=[], lines=[])
            put(stack, stop)
            u.reg_write(ESP, stack)
            u.reg_write(EAX, 0x30007000)
            u.reg_write(EDX, writer)
            u.reg_write(ECX, unit)
            u.emu_start(method['start'], stop, count=500)
            if u.reg_read(EIP) != stop:
                raise AssertionError('Original PIR wrapper did not return')
            observations.append(dict(state))
    probe = OriginalNeoActionSelectorProbe(executable, mapping, ACTIONS[0])
    actions = [{**case, 'html': probe.run(case)} for case in cases()]
    methods[ACTIONS[0]] = {'start': hex(probe.method['start']), 'end': hex(probe.method['end']),
                          'sha256': probe.method['sha256']}
    return {'format': 'cbus-project-documentor-pir-original-v1', 'exe_sha256': EXE_SHA256,
        'map_sha256': MAP_SHA256, 'methods': methods, 'appendix_cases': observations, 'action_cases': actions,
        'original_generated_page_comparison': 'not_obtained', 'original_loader_execution': 'not_executed',
        'boundary': 'Original appendix wrappers and inherited Classic action instructions with synthetic string, collection, group display, inherited body and attribute hooks; no GUI, native loader, full original page or hardware.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--map-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = inspect(args.executable, args.map_file)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'appendix_cases': len(result['appendix_cases']), 'action_cases': len(result['action_cases'])}))


if __name__ == '__main__':
    main()
