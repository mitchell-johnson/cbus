"""Execute the original Toolkit C-Bus level/percent routines with Unicorn.

``CIS_CBus.PercentToLevel`` (0x7f2aa0) and ``CIS_CBus.LevelToPercent``
(0x7f2ac8) are the two conversions used by ``TFlashCxTrackBar`` and
``TFlashCxVertTrackBar`` when ``UseRawValues = false``; the DIN relay/dimmer
Turn On/Min-Max, Recovery and Logic Recovery sliders bind that way. Both are
leaf register routines, so the emulator admits only their own instructions.

``TfrmCBusDimmer.OnRecoveryLevelChange`` separately copies a channel's
recovery percentage to logic groups sharing the channel's group with an x87
``Round(percent * 2.55)`` (0xef6e5a..0xef6e6a, extended constant at 0xef6e84,
``System.@ROUND`` at 0x604ed0). That fragment runs under the Delphi default
control word 0x1332 with only those instructions admitted.
The executable is hash-checked; no production converter is imported.

Run with the exact executable to regenerate the frozen vectors::

    python research/din_output_levels_original.py --executable CBusToolkit.exe \
        --output research/fixtures/din-output-level-original-vectors.json
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
PERCENT_TO_LEVEL = 0x7f2aa0
LEVEL_TO_PERCENT = 0x7f2ac8
# Each routine ends with a near RET; nothing else may execute.
ALLOWED = {PERCENT_TO_LEVEL: ((0x7f2aa0, 0x7f2ac5),), LEVEL_TO_PERCENT: ((0x7f2ac8, 0x7f2aec),)}
LOGIC_ROUND = (0xef6e5a, 0xef6e6a)
LOGIC_ROUND_ALLOWED = ((0xef6e5a, 0xef6e6a), (0x604ed0, 0x604eda))
LOGIC_ROUND_CONSTANT = (0xef6e84, '33333333333333a30040')
DELPHI_CONTROL_WORD = 0x1332
RETURN = 0x30000000
# Original call sites that pass these routines their argument.
CALL_SITES = {
    'TFlashCxTrackBar.ControllerValueChange': (0xc09b95, 'LevelToPercent'),
    'TFlashCxTrackBarProperties.DoChanged/vertical': (0xc09f85, 'PercentToLevel'),
    'TFlashCxTrackBarProperties.DoChanged/horizontal': (0xc09fdc, 'PercentToLevel'),
    'TFlashCxVertTrackBar.ControllerValueChange': (0xc0a0a9, 'LevelToPercent'),
}


class DinLevelOriginalProbe:
    def __init__(self, executable):
        data = Path(executable).read_bytes()
        if hashlib.sha256(data).hexdigest() != EXE_SHA256:
            raise ValueError('original Toolkit executable hash does not match')
        pe = pefile.PE(data=data)
        self.image = pe.get_memory_mapped_image()
        self.base = pe.OPTIONAL_HEADER.ImageBase
        for label, (site, name) in CALL_SITES.items():
            raw = self.image[site - self.base:site - self.base + 5]
            target = site + 5 + struct.unpack('<i', raw[1:])[0]
            expected = PERCENT_TO_LEVEL if name == 'PercentToLevel' else LEVEL_TO_PERCENT
            if raw[0] != 0xe8 or target != expected:
                raise ValueError('original call site changed: ' + label)

    def _run(self, entry, value):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(self.base, (len(self.image) + 4095) & ~4095)
        u.mem_write(self.base, self.image)
        u.mem_map(0x20000000, 0x10000)
        u.mem_map(RETURN, 4096)
        executed = []

        def hook(_u, address, _size, _data):
            if not any(start <= address < end for start, end in ALLOWED[entry]):
                raise AssertionError(f'unexpected original execution at {address:#x}')
            executed.append(address)
        u.hook_add(UC_HOOK_CODE, hook)
        stack = 0x20008000
        u.mem_write(stack, struct.pack('<I', RETURN))
        u.reg_write(UC_X86_REG_ESP, stack)
        u.reg_write(UC_X86_REG_EAX, value & 0xffffffff)
        u.emu_start(entry, RETURN, count=64)
        if u.reg_read(UC_X86_REG_EIP) != RETURN:
            raise AssertionError('original routine did not return')
        result = u.reg_read(UC_X86_REG_EAX)
        return (result - (1 << 32) if result & 0x80000000 else result), len(executed)

    def logic_round(self, percent):
        start, stop = LOGIC_ROUND
        address, constant = LOGIC_ROUND_CONSTANT
        if self.image[address - self.base:address - self.base + 10].hex() != constant:
            raise ValueError('original 2.55 extended constant changed')
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(self.base, (len(self.image) + 4095) & ~4095)
        u.mem_write(self.base, self.image)
        u.mem_map(0x20000000, 0x10000)

        def hook(_u, address, _size, _data):
            if not any(a <= address < b for a, b in LOGIC_ROUND_ALLOWED):
                raise AssertionError(f'unexpected original execution at {address:#x}')
        u.hook_add(UC_HOOK_CODE, hook)
        frame = 0x20008000
        u.reg_write(UC_X86_REG_EBP, frame)
        u.reg_write(UC_X86_REG_ESP, frame - 0x100)
        u.mem_write(frame - 0x1c, struct.pack('<i', percent))  # GetVertPosition result
        u.reg_write(UC_X86_REG_FPCW, DELPHI_CONTROL_WORD)
        u.emu_start(start, stop, count=32)
        if u.reg_read(UC_X86_REG_EIP) != stop:
            raise AssertionError('original fragment did not complete')
        return u.reg_read(UC_X86_REG_EAX)

    def percent_to_level(self, percent):
        return self._run(PERCENT_TO_LEVEL, percent)[0]

    def level_to_percent(self, level):
        return self._run(LEVEL_TO_PERCENT, level)[0]

    def vectors(self):
        rows = []
        for percent in range(0, 101):
            rows.append({'routine': 'PercentToLevel', 'input': percent,
                         'output': self.percent_to_level(percent)})
        for level in range(0, 256):
            rows.append({'routine': 'LevelToPercent', 'input': level,
                         'output': self.level_to_percent(level)})
        for percent in range(0, 101):
            rows.append({'routine': 'LogicGroupRound255', 'input': percent,
                         'output': self.logic_round(percent)})
        return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    probe = DinLevelOriginalProbe(args.executable)
    source = Path(__file__).read_bytes()
    document = {
        'format': 'cbus-din-output-level-original-vectors-v1',
        'executable_sha256': EXE_SHA256,
        'probe_sha256': hashlib.sha256(source).hexdigest(),
        'routines': {'PercentToLevel': hex(PERCENT_TO_LEVEL), 'LevelToPercent': hex(LEVEL_TO_PERCENT),
                     'LogicGroupRound255': hex(LOGIC_ROUND[0])},
        'control_word': hex(DELPHI_CONTROL_WORD),
        'call_sites': {label: hex(site) for label, (site, _) in CALL_SITES.items()},
        'boundary': ('Direct original-instruction execution of the two leaf routines and the '
                     'Round(percent*2.55) fragment. VCL trackbar positioning, event dispatch, '
                     'rendering and user input are not executed.'),
        'rows': probe.vectors(),
    }
    args.output.write_text(json.dumps(document, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
