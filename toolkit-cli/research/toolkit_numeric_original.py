"""Original x86 JCL numeric instructions with explicit runtime fixtures.

The PE is hash checked; no production parser is imported. Original filtering,
StrToFloat, FPower10 and TRUNC run unchanged. Delphi managed strings, ASCII
character classification and locale globals are fixtures. Optional UI validation
uses fixture text/dialog calls, not actual GUI bindings. x87 exception delivery
is outside the emulator claim, even with the original unmasked control word.
"""
from pathlib import Path
import hashlib, struct
import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX,
                              UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_FPCW, UC_X86_REG_EBP)

ALLOWED = ((0xddf684, 0xddf7d0), (0x782c2c, 0x782c4c), (0x78299c, 0x782c1b),
           (0x781598, 0x78164d), (0x7821c0, 0x7821f3), (0x782354, 0x7823dc),
           (0x7818a0, 0x7818fd), (0x61d424, 0x61d45f), (0x61cfe8, 0x61d04b),
           (0x61ced4, 0x61cfe8), (0x605dc8, 0x605e79), (0x604edc, 0x604efe))
HOOKS = {0x6f62a0, 0x7d9d00, 0x60891c, 0x608978, 0x609488, 0x608cb0, 0x609480,
         0x6089b0, 0x608e08, 0x608d48, 0x608914, 0x6078f4, 0x607df0, 0x6075cc,
         0x618540}

def _execute(IMAGE, BASE, value, decimal='.', thousands=',', control_word=0x37f, validation=False):
    assert type(value) is str and value.isascii() and len(value) <= 64 and '\0' not in value
    assert decimal in '.,' and thousands in '.,' and decimal != thousands
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(BASE, (len(IMAGE)+4095)&~4095); u.mem_write(BASE, IMAGE)
    for address, size in ((0, 4096), (0x10000000, 0x200000), (0x20000000, 0x40000), (0x30000000, 4096)):
        u.mem_map(address, size)
    heap = 0x10000000; trace = []; converted = []; float_inputs = []; messages = []; extended = []
    def alloc(size):
        nonlocal heap
        address = heap; heap = (heap+size+7)&~7; return address
    def get(address): return struct.unpack('<I', u.mem_read(address, 4))[0]
    def put(address, value): u.mem_write(address, struct.pack('<I', value&0xffffffff))
    def string(value, *, ansi=False):
        raw = value.encode('ascii' if ansi else 'utf-16-le')
        address = alloc(len(raw)+14)
        u.mem_write(address, struct.pack('<HHII', 0 if ansi else 1200, 1 if ansi else 2, 0xffffffff,
                    len(raw) if ansi else len(raw)//2)+raw+(b'\0' if ansi else b'\0\0'))
        return address+12
    def read(address, *, ansi=False):
        if not address: return ''
        length = get(address-4); assert length <= 4096
        return bytes(u.mem_read(address, length if ansi else length*2)).decode('ascii' if ansi else 'utf-16-le')
    form = alloc(0x600); control = alloc(0x100); put(form+0x488, control)
    # Pointer slots and C runtime decimal separator are original globals.
    u.mem_write(get(0x13c3f54), decimal.encode('utf-16-le'))
    u.mem_write(get(0x13c3ab8), thousands.encode('utf-16-le'))
    u.mem_write(0x13c9ecc, decimal.encode('ascii'))
    for char in range(128): u.mem_write(0x142c644+char*2, struct.pack('<H', 4 if 48<=char<=57 else 0))
    put(get(0x13c394c), alloc(0x100))
    empty_wide, empty_ansi = string(''), string('', ansi=True)
    def hook(_u, address, size, _data):
        eax, edx, ecx, esp = (u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX, UC_X86_REG_ESP))
        if address not in HOOKS:
            assert any(start<=address<end for start,end in ALLOWED), ('unexpected original execution', hex(address))
            if address == 0x782c48: converted.append(eax if eax<2**31 else eax-2**32)
            if address == 0x782bef: extended.append(bytes(u.mem_read(u.reg_read(UC_X86_REG_EBP)-0x10,10)).hex())
            if address == 0x61d424: float_inputs.append(read(eax))
            return
        pop = 4
        if address == 0x6f62a0:
            assert eax == control; put(edx, string(value)); trace.append('get-text')
        elif address == 0x7d9d00:
            assert edx in (0x2bff, 0x2c00); messages.append(edx); pop += 4; trace.append('display-error-fixture')
        elif address in (0x60891c, 0x608914, 0x6075cc):
            pass
        elif address == 0x608978:
            put(eax, string(read(edx)))
        elif address in (0x609488, 0x609480):
            u.reg_write(UC_X86_REG_EAX, get(eax))
        elif address == 0x608cb0:
            assert edx <= 4096
            old = read(get(eax)); put(eax, string(old[:edx].ljust(edx, '\0')))
        elif address == 0x6089b0:
            u.reg_write(UC_X86_REG_EAX, eax or empty_wide)
        elif address == 0x608e08:
            put(eax, string(read(edx)+read(ecx)))
        elif address == 0x608d48:
            put(eax, string(read(get(eax))+read(edx)))
        elif address == 0x6078f4:
            assert ecx == 0
            # Original caller passes a NUL-terminated wide string.
            put(eax, string(read(edx), ansi=True))
        elif address == 0x607df0:
            u.reg_write(UC_X86_REG_EAX, eax or empty_ansi)
        elif address == 0x618540:
            raise ValueError('Original StrToFloat reached its conversion-error path')
        else: raise AssertionError(hex(address))
        u.reg_write(UC_X86_REG_EIP, get(esp)); u.reg_write(UC_X86_REG_ESP, esp+pop)
    u.hook_add(UC_HOOK_CODE, hook)
    stack = 0x20030000; put(stack, 0x30000000)
    u.reg_write(UC_X86_REG_ESP, stack); u.reg_write(UC_X86_REG_EAX, form if validation else string(value)); u.reg_write(UC_X86_REG_FPCW, control_word)
    u.emu_start(0xddf684 if validation else 0x782c2c, 0x30000000, timeout=3000000, count=100000)
    assert u.reg_read(UC_X86_REG_EIP) == 0x30000000
    return {'input': value, 'decimal_separator': decimal, 'thousands_separator': thousands,
            'control_word': control_word, 'validation': validation, 'return_value': u.reg_read(UC_X86_REG_EAX), 'extended80_hex': extended, 'converted_integers': converted,
            'original_float_inputs': float_inputs, 'error_message_ids': messages, 'gui_stub_trace': trace}


EXE_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'


class NumericOriginalProbe:
    def __init__(self, executable):
        data = Path(executable).read_bytes()
        if hashlib.sha256(data).hexdigest() != EXE_SHA256:
            raise ValueError('original Toolkit executable hash does not match')
        pe = pefile.PE(data=data)
        self.image = pe.get_memory_mapped_image()
        self.base = pe.OPTIONAL_HEADER.ImageBase

    def run(self, value, *, decimal='.', thousands=',', control_word=0x37f):
        return _execute(self.image, self.base, value, decimal, thousands, control_word)

    def validate(self, value, *, decimal='.', thousands=','):
        return _execute(self.image, self.base, value, decimal, thousands, validation=True)

    def powers(self):
        return [{'power': power, 'hex': self.image[address-self.base:address-self.base+10].hex()}
                for power, address in [(n, 0x605e83 + 10*n) for n in range(32)] + [(32, 0x605fc3)]]
