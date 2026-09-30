"""Original classic application-LABEL response predicates and state precedence.

The parser, HasResponse, StringContainsAll and SetCompleted instructions execute.
Delphi string primitives and exception allocation/storage are synthetic hooks.
The exception hook models the source-pinned state1 assignment without invoking
the original logger, socket processor or exception machinery. No transport runs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (UC_X86_REG_EAX as EAX, UC_X86_REG_ECX as ECX,
                               UC_X86_REG_EDX as EDX, UC_X86_REG_EIP as EIP,
                               UC_X86_REG_ESP as ESP)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classic_dlt_controls_original import ClassicControlsProbe  # noqa: E402
from project_documentor_static import EXE_SHA256, MAP_SHA256  # noqa: E402

FORMAT = 'cbus-classic-dlt-broadcast-results-original-v1'
COMMAND, EXCEPTION, STACK, RETURN = 0x30001000, 0x30002000, 0x20008000, 0x3000F000
METHODS = {
    'parser': 'CIS_TcgcApplicationLabel.TcgcApplicationLabel.OnProcessResults',
    'base_parser': 'CIS_TCGateCommand.TCGateCommand.OnProcessResults',
    'has_response': 'CIS_TCGateCommand.TCGateCommand.HasResponse',
    'contains_all': 'CIS_Strings.StringContainsAll',
    'complete': 'CIS_TCGateCommand.TCGateCommand.SetCompleted',
    'exception': 'CIS_TCGateCommand.TCGateCommand.SetRealExceptionToRaise',
    'generator': 'CIS_TcgcApplicationLabel.TcgcApplicationLabel.GenerateCommandText',
    'flavour_adapter': 'CIS_TGroupLanguageFlavourCGateAgent.TGroupLanguageFlavourCGateAgent.CommandApplicationLabel',
    'generic_adapter': 'CIS_TCGateDLTAgent.TCGateDLTAgent.CommandApplicationLabel',
    'oid': 'CIS_TCBusObject.TCGateObject.GetOIDAsCGateID',
    'address': 'CIS_TCBusObject.TCGateObject.GetAddressAsCGateID',
    'constructor': 'CIS_TCGateCommand.TCGateCommand.Create',
    'internal_create': 'CIS_TCGateCommand.TCGateCommand.InternalCreate',
    'set_timeout': 'CIS_TCGateCommand.TCGateCommand.SetTimeOut',
}
ADDRESSES = (0x120D9E0, 0x843C74, 0x843CEC, 0x7B78F4, 0x843DE4,
             0x843E5C, 0x120D868, 0x1211BDC, 0x120DFF8, 0xF47A58, 0xF47BF0,
             0x8435DC, 0x843D84, 0x84404C)


class ResultsProbe:
    def __init__(self, image):
        assert hashlib.sha256(image.raw).hexdigest() == EXE_SHA256
        self.image = image
        self.methods = {}
        for (key, symbol), address in zip(METHODS.items(), ADDRESSES):
            assert image.by_name.get(symbol) == address
            self.methods[key] = image.method(symbol)

    def static_facts(self):
        def require(key, *pairs):
            actual = [row[1:] for row in self.methods[key]['instructions']]
            assert all(pair in actual for pair in pairs), key
        require('has_response', ('dec', 'eax'), ('sete', 'byte ptr [ebp - 0xd]'))
        require('contains_all', ('call', '0x61b404'), ('mov', 'byte ptr [ebp - 0xd], 0'))
        require('complete', ('cmp', 'byte ptr [eax + 0x18], 1'),
                ('mov', 'byte ptr [eax + 0x18], 3'))
        require('exception', ('mov', 'byte ptr [eax + 0x18], 1'),
                ('mov', 'dword ptr [eax + 0x40], edx'))
        assert {'200 OK', '400', 'Syntax Error', '408', 'Operation failed',
                'System Exception', 'Send failed', '402', 'Operation not supported',
                'bad object'} <= set(self.methods['parser']['literals'])
        require('generator', ('mov', 'edx, 0xe'), ('mov', 'edx, 0x7530'))
        require('flavour_adapter', ('add', 'eax, 0xa8'), ('call', 'dword ptr [ecx + 0xac]'))
        require('oid', ('call', hex(self.methods['address']['start'])))
        require('address', ('call', '0xf47c7c'), ('call', 'dword ptr [ecx + 0x90]'))
        require('constructor', ('mov', 'dword ptr [eax + 0x38], 0x4e20'))
        require('set_timeout', ('mov', 'dword ptr [edx + 0x38], eax'))
        assert self.image.slot('CIS_TcgcApplicationLabel..TcgcApplicationLabel', 0x10) == METHODS['internal_create']
        assert self.methods['internal_create']['instructions'] == [
            (0x843D84, 'push', 'ebp'), (0x843D85, 'mov', 'ebp, esp'),
            (0x843D87, 'push', 'ecx'), (0x843D88, 'mov', 'dword ptr [ebp - 4], eax'),
            (0x843D8B, 'pop', 'ecx'), (0x843D8C, 'pop', 'ebp'),
            (0x843D8D, 'ret', ''), (0x843D8E, 'mov', 'eax, eax')]
        return {
            'source_sha256': {'CBusToolkit.exe': EXE_SHA256, 'CBusToolkit.map': MAP_SHA256},
            'methods': {key: {'symbol': METHODS[key], 'start': hex(method['start']),
                             'end': hex(method['end']), 'sha256': method['sha256']}
                        for key, method in self.methods.items()},
            'rules': {
                'success': 'Case-sensitive prefix200 OK (Pos==1), without a token-boundary check',
                'error_order': [['400', 'Syntax Error'], ['408', 'Operation failed', 'System Exception'],
                                ['408', 'Operation failed', 'Send failed'], ['402', 'Operation not supported']],
                'errors': 'Each pattern requires all case-sensitive substrings anywhere in the response; all matching branches run in order and later exceptions replace earlier ones',
                'bad_object': 'Case-insensitive substring bad object attempts completion; completion never overwrites error state1',
                'state': 'SetRealExceptionToRaise stores error state1; SetCompleted(true) sets complete3 only when current state is not1; unrecognized responses leave state unchanged',
                'response_scope': 'One callback string per invocation; ordered callbacks retain command state. Transport framing/timeouts are outside this probe',
                'target': 'Flavour adapter prepends optional //project/ to supplied application CGateID; GetOIDAsCGateID returns !OID when nonblank, otherwise virtual address. No numeric-path normalization occurs in generator',
                'generator': 'ApplicationType LABEL Target Language Group Level [Flavour plus space] Type Data; exact TEXT mode quotes through TagStringToCgateString, other payloads copied unchanged; DYNAMIC flag selects30000ms timeout',
                'timeout_ms': {'ordinary': 20000, 'DYNAMIC': 30000,
                               'basis': 'Base constructor writes20000; inherited InternalCreate is a no-op; DYNAMIC generation overrides with30000'},
                'portable_boundary': 'A conservative portable assessment must distinguish exact positive receipt from legacy bad-object completion and prefix quirks; it must not imply rendering or persistence',
            },
        }

    def _machine(self):
        image = self.image
        memory = image.pe.get_memory_mapped_image()
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(image.base, (len(memory) + 4095) & ~4095)
        u.mem_write(image.base, memory)
        for base in (0, 0x20000000, 0x30000000):
            u.mem_map(base, 0x10000)
        put = lambda address, value: u.mem_write(address, struct.pack('<I', value))

        def read(address):
            return struct.unpack('<I', u.mem_read(address, 4))[0]

        def string(address):
            return bytes(u.mem_read(address, read(address - 4) * 2)).decode('utf-16-le') if address else ''

        def allocate(value):
            if not value:
                return 0
            raw, address = value.encode('utf-16-le'), self.next_string + 8
            assert address + len(raw) + 2 < 0x3000E000
            put(address - 4, len(raw) // 2)
            u.mem_write(address, raw + b'\0\0')
            self.next_string = (address + len(raw) + 5) & ~3
            return address
        self.allocate = allocate

        def ret(value=None, cleanup=0):
            stack = u.reg_read(ESP)
            if value is not None:
                u.reg_write(EAX, value)
            u.reg_write(EIP, read(stack))
            u.reg_write(ESP, stack + 4 + cleanup)

        noops = {image.by_name[name] for name in
                 ('System.@UStrAddRef', 'System.@UStrClr', 'System.@UStrArrayClr')}
        allowed = [(self.methods[key]['start'], self.methods[key]['end'])
                   for key in ('parser', 'base_parser', 'has_response', 'contains_all', 'complete')]

        def hook(_u, address, _size, _data):
            if address == RETURN:
                u.emu_stop()
            elif address in noops:
                ret()
            elif address == 0x6094D4:  # Unicode overload; MAP has several Pos symbols.
                needle, haystack = string(u.reg_read(EAX)), string(u.reg_read(EDX))
                ret(haystack.find(needle) + 1 if needle else 0)
            elif address == 0x61B404:
                source, needle = u.reg_read(EAX), string(u.reg_read(EDX))
                index = string(source).find(needle)
                ret(0 if index < 0 else source + index * 2)
            elif address == 0x6187AC:
                put(u.reg_read(EDX), allocate(string(u.reg_read(EAX)).lower()))
                ret()
            elif address == image.by_name['CIS_Strings.StringSubstringAfter']:
                value, token = string(u.reg_read(EAX)), string(u.reg_read(EDX))
                put(read(u.reg_read(ESP) + 4), allocate(value.partition(token)[2]))
                ret(cleanup=8)
            elif address == image.by_name['System.@UStrCat3']:
                put(u.reg_read(EAX), allocate(string(u.reg_read(EDX)) + string(u.reg_read(ECX))))
                ret()
            elif address == image.by_name['SysUtils.Exception.Create']:
                self.allocated_exception = {'class': image.class_name(u.reg_read(EAX)),
                                            'message': string(u.reg_read(ECX))}
                ret(EXCEPTION)
            elif address == self.methods['exception']['start']:
                assert u.reg_read(EDX) == EXCEPTION
                u.mem_write(COMMAND + 0x18, b'\x01')
                self.exception = dict(self.allocated_exception)
                self.exception_history.append(self.exception)
                ret()
            elif not any(start <= address < stop for start, stop in allowed):
                raise AssertionError(f'Unexpected original execution at {address:#x}')
        u.hook_add(UC_HOOK_CODE, hook)
        return u

    def run(self, lines):
        if not hasattr(self, 'machine'):
            self.machine = self._machine()
        u = self.machine
        self.exception, self.exception_history, steps = None, [], []
        u.mem_write(COMMAND + 0x18, b'\x00')
        for line in lines:
            self.next_string = 0x30003000
            response = self.allocate(line)
            u.mem_write(STACK, struct.pack('<II', RETURN, 0))
            u.reg_write(ESP, STACK)
            u.reg_write(EAX, COMMAND)
            u.reg_write(EDX, 0)
            u.reg_write(ECX, response)
            u.emu_start(self.methods['parser']['start'], RETURN, count=10000)
            assert u.reg_read(EIP) == RETURN
            state = {0: 'pending', 1: 'error', 3: 'completed'}[u.mem_read(COMMAND + 0x18, 1)[0]]
            steps.append({'line': line, 'state': state, 'exception': self.exception})
        return {'responses': lines, 'steps': steps, 'exception_history': self.exception_history}

    def observations(self):
        cases = [['200 OK'], ['200 OKextra'], ['200 ok'], ['x200 OK'], [' 200 OK'],
                 ['bad object'], ['401 BAD OBJECT'], ['400 Syntax Error details'],
                 ['x400x Syntax Error details'], ['400 syntax error'],
                 ['408 Operation failed System Exception'], ['408 Operation failed Send failed'],
                 ['408 Operation failed'], ['402 Operation not supported'],
                 ['402 Operation Not Supported'], ['500 failure'], ['100 Continue'],
                 ['200 OK', '408 Operation failed Send failed'],
                 ['408 Operation failed Send failed', '200 OK'],
                 ['400 Syntax Error bad object'], ['400 Syntax Error', 'bad object'],
                 ['bad object', '402 Operation not supported'], ['bad object', '500 failure'],
                 ['400 Syntax Error 408 Operation failed System Exception Send failed 402 Operation not supported'],
                 ['402 Operation not supported', '400 Syntax Error later']]
        return [self.run(lines) for lines in cases]


def results_facts(image):
    probe = ResultsProbe(image)
    return {'format': FORMAT, **probe.static_facts(), 'observations': probe.observations(),
            'boundary': 'Original parser/predicate/completion instructions; synthetic string primitives and exception-state hook. No transport, CommandExecute, exception delivery, timeout or hardware execution.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = results_facts(ClassicControlsProbe(args.executable, args.map))
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'format': FORMAT, 'cases': len(report['observations'])}))


if __name__ == '__main__':
    main()
