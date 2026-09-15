"""Fresh unchanged x86 thermostat arithmetic in a confined instruction engine.

Only the declared original methods, their three arithmetic helpers and the
owned ABI wrapper execute. No original initialization or external API runs.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import struct
import sys

import capstone
import pefile
import unicorn
from unicorn.unicorn_py3 import unicorn as unicorn_core
from unicorn.x86_const import (
    UC_X86_REG_EAX as EAX, UC_X86_REG_EDX as EDX, UC_X86_REG_ECX as ECX,
    UC_X86_REG_EBX as EBX, UC_X86_REG_ESI as ESI, UC_X86_REG_EDI as EDI,
    UC_X86_REG_EBP as EBP, UC_X86_REG_ESP as ESP, UC_X86_REG_EIP as EIP,
    UC_X86_REG_FPCW as FPCW, UC_X86_REG_FPSW as FPSW, UC_X86_REG_FPTAG as FPTAG,
)

EXE_SHA = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
METHODS = (
    ('CGate16thDegreeToQuarterDegreeTempOffset', 0x128fe90, 0x128ff04),
    ('CGateTempToHalfDegreesTempOffset', 0x128fde0, 0x128fe3c),
    ('CGateTempToTempOffset', 0x128fc90, 0x128fcec),
    ('CGateTempToTempOffsetWithShift', 0x128fbc4, 0x128fc34),
    ('CGateTempToUnitTemp', 0x128fafc, 0x128fb64),
    ('CGateTempToWholeDegreesTemp', 0x128fd40, 0x128fd94),
    ('HalfDegreesTempOffsetToCGateTemp', 0x128fe3c, 0x128fe90),
    ('QuarterDegreesTempOffsetToCGateTemp', 0x128ff04, 0x128ff9c),
    ('SimpleCGateTempToUnitTemp', 0x128fa7c, 0x128fabc),
    ('SimpleUnitTempToCGateTemp', 0x128fabc, 0x128fafc),
    ('TempOffsetToCGateTemp', 0x128fcec, 0x128fd40),
    ('TempOffsetWithShiftToCGateTemp', 0x128fc34, 0x128fc90),
    ('UnitTempToCGateTemp', 0x128fb64, 0x128fbc4),
    ('WholeDegreesTempToCGateTemp', 0x128fd94, 0x128fde0),
)
HELPERS = ((0x604ed0, 0x604eda), (0x7b6c38, 0x7b6c5a), (0x7b6c6c, 0x7b6c90), (0x604df8, 0x604e07))
LIBRARIES = {
    '016084c6e70d929249a2abb22f1afda95095294e6cd70f509964ffc54006bf94',
    '7207c8e3d7a63118fb0bca73e01816797fd51b1d8a39a4cbc7abfd562ee59c85',
}


def require(value, message):
    if not value: raise ValueError(message)


def read(path, maximum):
    with owned_stream(path, 'rb') as stream: raw = stream.read(maximum + 1)
    require(0 < len(raw) <= maximum, 'Input byte bound')
    return raw


@contextmanager
def owned_stream(path, mode):
    stream = Path(path).open(mode); first = None
    try:
        yield stream
    except BaseException as error:
        first = error
        raise
    finally:
        try: stream.close()
        except BaseException:
            if first is None: raise


def stub(entry):
    word = lambda value: struct.pack('<I', value)
    state = 0x10004000
    return (bytes.fromhex('558bec535657dd35') + word(state) + b'\xb8' + word(0x1332)
            + b'\xb9' + word(0x604df8) + bytes.fromhex('ffd18b5508b8') + word(0x10002000)
            + b'\xb9' + word(entry) + bytes.fromhex('ffd1a3') + word(state + 0x104)
            + bytes.fromhex('d93d') + word(state + 0x100) + bytes.fromhex('dd25') + word(state)
            + b'\xa1' + word(state + 0x104) + bytes.fromhex('5f5e5b5dc3'))


def execute(input_path, output_path, executable):
    data = read(input_path, 2 * 1024 * 1024)
    plan = json.loads(data)
    methods = [{'name': name, 'start': start, 'end': end} for name, start, end in METHODS]
    require(plan['methods'] == methods and len(plan['rows']) == 28840, 'Exact matrix shape')
    for row in plan['rows']:
        require(type(row) is list and len(row) == 4, 'Case row shape')
        index, fahrenheit, value, expected = row
        require(type(index) is int and 0 <= index < 14 and type(fahrenheit) is bool
                and type(value) is int and -(1 << 31) <= value < (1 << 31)
                and type(expected) is int and -(1 << 31) <= expected < (1 << 31), 'Case domain')
    raw = read(executable, 20518992)
    require(hashlib.sha256(raw).hexdigest() == EXE_SHA, 'Exact original executable pin')
    native = [Path(unicorn_core.uclib._name).resolve(), Path(capstone._cs._name).resolve()]
    actual = {hashlib.sha256(p.read_bytes()).hexdigest() for p in native}
    require(actual == LIBRARIES, 'Actual loaded instruction-engine libraries')
    out = Path(output_path); out.mkdir()
    pe = pefile.PE(data=raw); image = pe.get_memory_mapped_image(); base = pe.OPTIONAL_HEADER.ImageBase
    require(base == 0x600000 and pe.FILE_HEADER.Machine == 0x14c, 'Pinned image shape')
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    # Delphi stores floating constants between RET and the next method. Decode
    # only an actually reached instruction, against immutable original bytes;
    # interpreting the constant pools as linear code invents privileged opcodes.
    instructions = {}
    ranges = [(a, b) for _, a, b in METHODS] + list(HELPERS)
    u = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
    u.mem_map(base, (len(image) + 4095) & ~4095); u.mem_write(base, image)
    for address, size in ((0x10000000, 0x20000), (0x20000000, 0x20000), (0x30000000, 0x2000)):
        u.mem_map(address, size)
    def put(address, value): u.mem_write(address, struct.pack('<I', value & 0xffffffff))
    put(0x13c3ac8, 0x10000100); put(0x10000100, 0x10001000)
    wrappers = {}; visited = set()
    def guard(machine, address, size, _):
        expected = instructions.get(address, wrappers.get(address))
        if expected is None:
            spans = [(a, b) for a, b in ranges if a <= address and address + size <= b]
            require(len(spans) == 1, 'Instruction outside declared original methods')
            encoded = pe.get_data(address - base, size)
            decoded = list(decoder.disasm(encoded, address, count=1))
            require(len(decoded) == 1 and decoded[0].size == size, 'Original instruction decoding')
            require(decoded[0].mnemonic not in ('int', 'syscall', 'sysenter', 'in', 'out'), 'External instruction excluded')
            expected = bytes(decoded[0].bytes); instructions[address] = expected
        require(expected is not None and len(expected) == size and bytes(machine.mem_read(address, size)) == expected,
                'Unexpected or modified instruction at ' + hex(address))
        visited.add(address)
    def writes(machine, access, address, size, value, _):
        require(any(a <= address and address + size <= b for a, b in
                    ((0x20000000, 0x20020000), (0x10004000, 0x10004200), (0x13a1024, 0x13a1026))),
                'Write outside owned fixture state')
    u.hook_add(unicorn.UC_HOOK_CODE, guard); u.hook_add(unicorn.UC_HOOK_MEM_WRITE, writes)
    rows = []; previous = None
    with owned_stream(out / 'partial-rows.jsonl', 'x') as transcript:
        for index, fahrenheit, value, expected in plan['rows']:
            if index != previous:
                wrapper = stub(METHODS[index][1]); u.mem_write(0x30001000, wrapper)
                wrappers = {item.address: bytes(item.bytes) for item in decoder.disasm(wrapper, 0x30001000)}
                require(sum(map(len, wrappers.values())) == len(wrapper), 'Complete owned wrapper')
                u.ctl_remove_cache(0x30001000, 0x30001080); previous = index
            u.mem_write(0x10001020, bytes([fahrenheit]))
            saved = {EBX: 0x12345678, ESI: 0x87654321, EDI: 0xABCDEF01, EBP: 0x13579BDF}
            for reg, content in saved.items(): u.reg_write(reg, content)
            for reg in (EAX, EDX, ECX): u.reg_write(reg, 0)
            u.reg_write(FPCW, 0x027f); u.reg_write(FPSW, 0); u.reg_write(FPTAG, 0xffff)
            u.reg_write(ESP, 0x20010000); put(0x20010000, 0x30000000); put(0x20010004, value)
            u.emu_start(0x30001000, 0x30000000, timeout=100000, count=1000)
            require(u.reg_read(EIP) == 0x30000000 and u.reg_read(ESP) == 0x20010004, 'Wrapper return/stack')
            require(all(u.reg_read(reg) == content for reg, content in saved.items()), 'Caller integer state')
            require((u.reg_read(FPCW), u.reg_read(FPSW), u.reg_read(FPTAG)) == (0x027f, 0, 0xffff), 'Caller x87 state')
            require(struct.unpack('<H', u.mem_read(0x10004100, 2))[0] == 0x1332, 'Original x87 control word')
            result = u.reg_read(EAX); result = result - (1 << 32) if result & (1 << 31) else result
            row = [index, fahrenheit, value, result]
            transcript.write(json.dumps(row) + '\n'); transcript.flush()
            require(result == expected, 'Original result differs at case ' + str(len(rows)))
            rows.append(row)
    require(read(input_path, 2 * 1024 * 1024) == data and read(executable, 20518992) == raw, 'Input changed')
    require({hashlib.sha256(p.read_bytes()).hexdigest() for p in native} == actual, 'Native library changed')
    report = {'passed': True, 'cases': len(rows), 'rows': rows, 'methods': methods,
              'actual_libraries': sorted(actual), 'actual_library_paths': list(map(str, native)),
              'caller_state_preserved': True, 'unapproved_writes': 0,
              'instruction_addresses': list(map(hex, sorted(visited))), 'scope': __doc__}
    with owned_stream(out / 'report.json', 'x') as stream: json.dump(report, stream)
    print(json.dumps({'passed': True, 'cases': len(rows)}))


if __name__ == '__main__': execute(*sys.argv[1:])
