"""Execute the original Toolkit ST7 light-level margin arithmetic with Unicorn.

``TCBusST7MultisensorCGateAgent.AfterLoadProgrammingInformation`` converts
the stored margin byte to the dialog percentage (0xcf49ee..0xcf4a1f):
``ROUND(ext(PECMarginLux / PECTargetLux) * 100.0)``; a zero target skips the
fragment and loads 0%. ``BeforeSaveProgrammingInformation`` converts it back
(0xcf5704..0xcf5743): ``ROUND(PECTargetLux * ext(percent / 100.0))``. Both
are x87 sequences ending in ``System.@ROUND`` (0x604ed0). The SENPILL, PIR
and SENLL agents all inherit these two methods.

Only the fragments' own instructions and ``System.@ROUND`` run. The unit
getters they call (``MultisensorUnit``, ``GetLightLevelTargetLux``) and the
attribute ``GetValue`` virtual are fixtures returning the input byte. The
fragments run under the Delphi default control word 0x1332 (64-bit precision,
round to nearest). The executable is hash-checked; no production converter
is imported.

Regenerate the frozen vectors with the exact executable::

    python research/sensor_margin_original.py --executable CBusToolkit.exe \\
        --output research/fixtures/sensor-margin-original-vectors.json
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EIP, UC_X86_REG_ESP,
                              UC_X86_REG_FPCW)

EXE_SHA256 = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
DELPHI_CONTROL_WORD = 0x1332
ROUND = (0x604ed0, 0x604eda)
# (start, stop) of each fragment; stop is the instruction after System.@ROUND.
LOAD = (0xcf49ee, 0xcf4a1f)
SAVE = (0xcf5704, 0xcf5743)
# float32 100.0 operands of the fdiv/fmul instructions.
CONSTANTS = {0xcf4cb4: '0000c842', 0xcf5ae0: '0000c842'}
MULTISENSOR_UNIT = 0xcf7b20      # TCBusST7MultisensorCGateAgent.MultisensorUnit
GET_TARGET_LUX = 0xcfb288        # TCBusST7MultisensorUnit.GetLightLevelTargetLux
FRAME, STACK, FIXTURE = 0x20008000, 0x20007000, 0x30000000
AGENT, ATTRIBUTE, VMT, GET_VALUE, UNIT = (FIXTURE + 0x100, FIXTURE + 0x200, FIXTURE + 0x300,
                                         FIXTURE + 0x800, FIXTURE + 0x900)


class MarginOriginalProbe:
    def __init__(self, executable):
        data = Path(executable).read_bytes()
        if hashlib.sha256(data).hexdigest() != EXE_SHA256:
            raise ValueError('original Toolkit executable hash does not match')
        pe = pefile.PE(data=data)
        self.image = pe.get_memory_mapped_image()
        self.base = pe.OPTIONAL_HEADER.ImageBase
        for address, expected in CONSTANTS.items():
            if self.raw(address, 4).hex() != expected:
                raise ValueError(f'original 100.0 constant changed at {address:#x}')
        self.fragment_sha256 = {name: hashlib.sha256(self.raw(start, stop - start)).hexdigest()
                                for name, (start, stop) in (('load', LOAD), ('save', SAVE))}

    def raw(self, address, length):
        return bytes(self.image[address - self.base:address - self.base + length])

    def _machine(self):
        """One emulator reused for every run; each run rewrites registers and fixture results."""
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(self.base, (len(self.image) + 4095) & ~4095)
        u.mem_write(self.base, self.image)
        u.mem_map(0x20000000, 0x10000)
        u.mem_map(FIXTURE, 0x1000)
        u.mem_write(FRAME - 4, struct.pack('<I', AGENT))
        u.mem_write(AGENT + 0x224, struct.pack('<I', ATTRIBUTE))   # PECTargetLux attribute
        u.mem_write(ATTRIBUTE, struct.pack('<I', VMT))
        u.mem_write(VMT + 0x94, struct.pack('<I', GET_VALUE))      # TCGateAttribute.GetValue
        self.stubs, self.allowed = {}, ()

        def hook(_u, address, _size, _data):
            if address in self.stubs:
                esp = u.reg_read(UC_X86_REG_ESP)
                u.reg_write(UC_X86_REG_EAX, self.stubs[address])
                u.reg_write(UC_X86_REG_EIP, struct.unpack('<I', u.mem_read(esp, 4))[0])
                u.reg_write(UC_X86_REG_ESP, esp + 4)
            elif not any(start <= address < stop for start, stop in self.allowed):
                raise AssertionError(f'unexpected original execution at {address:#x}')
        u.hook_add(UC_HOOK_CODE, hook)
        return u

    def _run(self, fragment, target, value):
        start, stop = fragment
        if not hasattr(self, 'machine'):
            self.machine = self._machine()
        u = self.machine
        self.stubs = {GET_VALUE: target, GET_TARGET_LUX: target, MULTISENSOR_UNIT: UNIT}
        self.allowed = (fragment, ROUND)
        u.reg_write(UC_X86_REG_EBP, FRAME)
        u.reg_write(UC_X86_REG_ESP, STACK)
        u.reg_write(UC_X86_REG_FPCW, DELPHI_CONTROL_WORD)
        u.reg_write(UC_X86_REG_EAX, value)
        u.emu_start(start, stop, count=64)
        if u.reg_read(UC_X86_REG_EIP) != stop:
            raise AssertionError('original fragment did not complete')
        result = u.reg_read(UC_X86_REG_EAX)
        return result - (1 << 32) if result & 0x80000000 else result

    def loaded_percent(self, target, margin):
        """AfterLoad: the original skips the fragment and loads 0 for target 0."""
        return 0 if target == 0 else self._run(LOAD, target, margin)

    def saved_margin(self, target, percent):
        return self._run(SAVE, target, percent)

    def vectors(self):
        loaded = [[self.loaded_percent(t, m) for m in range(256)] for t in range(256)]
        return {
            'saved_margin': [[self.saved_margin(t, p) for p in range(101)] for t in range(256)],
            'loaded_percent': loaded,
            'round_trip_margin': [[self.saved_margin(t, loaded[t][m]) for m in range(256)] for t in range(256)],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    probe = MarginOriginalProbe(args.executable)
    tables = probe.vectors()
    header = {
        'format': 'cbus-sensor-margin-original-vectors-v1',
        'executable_sha256': EXE_SHA256,
        'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'fragments': {'load': [hex(v) for v in LOAD], 'save': [hex(v) for v in SAVE], 'round': hex(ROUND[0])},
        'fragment_sha256': probe.fragment_sha256,
        'control_word': hex(DELPHI_CONTROL_WORD),
        'domain': {'saved_margin': 'saved_margin[target][percent], target 0..255, percent 0..100',
                   'loaded_percent': 'loaded_percent[target][margin], target and margin 0..255',
                   'round_trip_margin': 'saved_margin(target, loaded_percent[target][margin])'},
        'boundary': ('Direct original-instruction execution of the AfterLoad and BeforeSave margin '
                     'fragments and System.@ROUND with fixture getters. Dialog widgets, attribute '
                     'storage and C-Gate are not executed.'),
    }
    # One table row per line keeps the frozen file reviewable.
    lines = [json.dumps(header, indent=1)[:-2] + ',']
    for index, (name, table) in enumerate(tables.items()):
        rows = ',\n  '.join(json.dumps(row, separators=(',', ':')) for row in table)
        lines.append(f' "{name}": [\n  {rows}\n ]' + (',' if index < len(tables) - 1 else ''))
    args.output.write_text('\n'.join(lines) + '\n}\n', encoding='utf-8')


if __name__ == '__main__':
    main()
