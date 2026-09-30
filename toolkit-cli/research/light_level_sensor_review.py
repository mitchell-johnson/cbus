"""Recover the Toolkit 1.18 ST7 light-level (SENLL) dialog and save from the EXE/MAP.

Static analysis only: it disassembles the pinned original CBusToolkit.exe with
its MAP symbols and executes no vendor code. The receipt holds method digests,
parameter names, integer constants, control component names, flash binding
expressions and derived rules. It contains no unit specification content,
help text or UI captions. Keep the vendor inputs outside Git. The margin
arithmetic shared with the other ST7 agents is executed separately by
research/sensor_margin_original.py.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pir_sensor_review import Review  # noqa: E402
from sensor_profile_review import EXE_SHA256, MAP_SHA256  # noqa: E402

AGENT_CLASS = 'CIS_TCBusST7SensorCGateAgent..TCBusST7LightLevelSensorCGateAgent'
AGENT = 'CIS_TCBusST7SensorCGateAgent.TCBusST7LightLevelSensorCGateAgent.'
UNIT = 'CIS_TCBusST7SensorUnit.TCBusST7LightLevelSensorUnit.'
KEYS = 'CIS_TSENLL.TST7SENLL.'
DIALOG = 'CIS_TddST7Sensors.TddST7LightLevelSensor.'
SUBFORM = 'CIS_TfrmMultisensorSENLLInputKeys..TfrmMultisensorSENLLInputKeys'
FORM = 'CIS_TfrmSENPILL..TfrmSENPILL'
MEMBER = re.compile(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]')


class LightLevelReview(Review):
    def __init__(self, exe, map_):
        super().__init__(exe, map_)
        self.agent = self.members(AGENT_CLASS)
        self.controls = self.fields(SUBFORM)

    def call_name(self, ins):
        return self.symbols.get(self.target(ins) or 0, '')

    def string(self, operand):
        try:
            return self.literal(int(operand, 16))
        except ValueError:
            return None

    def forced(self):
        """PrepareForcedParameters writes, in order."""
        code, span = self.code(AGENT + 'PrepareForcedParameters')
        rows, value, text = [], None, None
        for position, ins in enumerate(code):
            if ins.mnemonic == 'mov' and re.fullmatch(r'edx, 0x[0-9a-f]{6,8}', ins.op_str):
                text = self.string(ins.op_str.split(', ')[1])
            elif ins.mnemonic == 'mov' and re.fullmatch(r'edx, (0x[0-9a-f]+|\d+)|dl, [01]', ins.op_str):
                value = int(ins.op_str.split(', ')[1], 0)
            elif ins.mnemonic == 'xor' and ins.op_str in ('edx, edx', 'dl, dl'):
                value = 0
            member = MEMBER.fullmatch(ins.op_str)
            if ins.mnemonic != 'mov' or not member or position + 2 >= len(code):
                continue
            name, following = self.agent[int(member[1], 16)], code[position + 1:position + 3]
            if following[0].op_str == 'byte ptr [eax + 0x58], 0':
                rows.append({'parameter': name, 'programmable': False})
            elif following[1].op_str == 'dword ptr [ecx + 0x30]' and text:
                rows.append({'parameter': name, 'value': [int(v, 0) for v in text.split()], 'write': 'SetAsString'})
                text = None
            elif following[1].op_str == 'dword ptr [ecx + 0x7c]':
                rows.append({'parameter': name, 'value': value, 'write': 'SetValue'})
            elif self.call_name(following[1]).endswith('.SetArrayInteger') or any(
                    self.call_name(i).endswith('.SetArrayInteger') for i in code[position:position + 3]):
                index = next(int(i.op_str.split(', ')[1], 0) for i in reversed(code[:position + 3])
                             if i.mnemonic == 'mov' and i.op_str.startswith('edx, '))
                rows.append({'parameter': name, 'index': index, 'value': 0, 'write': 'SetArrayInteger'})
        return rows, span

    def before_save(self):
        code, span = self.code(AGENT + 'BeforeSaveProgrammingInformation')
        calls = [self.call_name(i) for i in code if i.mnemonic == 'call' and self.call_name(i)]
        block = [int(code[p - 1].op_str.split(', ')[1], 0) for p, i in enumerate(code)
                 if self.call_name(i).endswith('TInputBlockCollection.GetItem')]
        assignments, flag = [], None
        for ins in code:
            match = re.fullmatch(r'byte ptr \[eax \+ 0x348\], (\d+)', ins.op_str)
            if ins.mnemonic == 'cmp' and match:
                flag = int(match[1])
            if ins.mnemonic == 'mov' and re.fullmatch(r'edx, 0x[0-9a-f]{6,8}', ins.op_str):
                text = self.string(ins.op_str.split(', ')[1])
                if text:
                    assignments.append({'unit_flag': flag, 'value': [int(v, 0) for v in text.split()]})
                    flag = None
        load, load_span = self.code(AGENT + 'AfterLoadProgrammingInformation')
        loaded, compared = [], None
        for ins in load:
            if ins.mnemonic == 'cmp' and ins.op_str.startswith('eax, '):
                compared = int(ins.op_str.split(', ')[1], 0)
            match = re.fullmatch(r'byte ptr \[eax \+ 0x348\], (\d+)', ins.op_str)
            if ins.mnemonic == 'mov' and match:
                loaded.append({'IndicatorBlockAssignment[0]': compared, 'unit_flag': int(match[1])})
                compared = None
        broadcast = [i for i in code if i.mnemonic == 'mov' and MEMBER.fullmatch(i.op_str)
                     and self.agent.get(int(MEMBER.fullmatch(i.op_str)[1], 16)) == 'BroadcastActive']
        if block != [4] or len(broadcast) != 2 or len(assignments) != 4 or len(loaded) != 3:
            raise ValueError('Unexpected SENLL save/load shape')
        return {'sha256': span, 'after_load_sha256': load_span, 'calls': calls,
                'broadcast_active': {'block_index': block[0], 'group_unused': 0, 'group_used': 1},
                'indicator_block_assignment': assignments, 'indicator_loaded': loaded}

    def constant(self, name, *, byte=False):
        code, _ = self.code(name)
        if not byte and [i.op_str for i in code[4:6]] == ['eax, eax', 'dword ptr [ebp - 8], eax']:
            return 0
        value = super().constant(name, byte=byte)
        return value - (1 << 32) if not byte and value & 0x80000000 else value

    def unit(self):
        timer, _ = self.code(UNIT + 'InternalCreate')
        item = next(p for p, i in enumerate(timer) if self.call_name(i).endswith('TInputBlockCollection.GetItem'))
        block = next(int(i.op_str.split(', ')[1], 0) for i in reversed(timer[:item]) if i.op_str.startswith('edx, '))
        minimum = next(int(i.op_str.split(', ')[1], 0) for i in timer if i.op_str.startswith('dx, '))
        return {'MaximumKeyCount': self.constant(KEYS + 'MaximumKeyCount'),
                'GetMaximumVirtualKeyCount': self.constant(KEYS + 'GetMaximumVirtualKeyCount'),
                'MaximumIndicatorCount': self.constant(KEYS + 'MaximumIndicatorCount'),
                'IsJoinModeSupported': self.constant(KEYS + 'IsJoinModeSupported', byte=True),
                'IsDualJoinModeSupported': self.constant(KEYS + 'IsDualJoinModeSupported', byte=True),
                'IsCorridorLinkingSupported': self.constant(UNIT + 'IsCorridorLinkingSupported', byte=True),
                'IsInfraredNECSupported': self.constant(UNIT + 'IsInfraredNECSupported', byte=True),
                'HasApplication2': self.constant(UNIT + 'HasApplication2', byte=True),
                'broadcast_block_timer_min_seconds': {'block_index': block, 'seconds': minimum}}

    def bindings(self, method):
        """Control -> flash expression for each PrepareFlashCx* helper call."""
        code, span = self.code(DIALOG + method)
        rows, strings, control = [], [], None
        for ins in code:
            if ins.mnemonic in ('push', 'mov') and re.search(r'0x[0-9a-f]{6,8}$', ins.op_str):
                text = self.string(ins.op_str.split(', ')[-1])
                if text and text not in ('Groups', '0'):
                    strings.append(text)
            field = re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', ins.op_str)
            if field and int(field[1], 16) in self.controls:
                control = self.controls[int(field[1], 16)]
            if ins.mnemonic == 'call' and 'PrepareFlashCx' in self.call_name(ins):
                if not strings or control is None:
                    raise ValueError('Unexpected flash binding shape in ' + method)
                rows.append({'control': control, 'expression': strings[-1],
                             'helper': self.call_name(ins).rsplit('.', 1)[1]})
                strings, control = [], None
        return rows, span

    def dialog(self):
        code, span = self.code(DIALOG + 'Initialise')
        form = self.fields(FORM)
        hidden = sorted(form[int(MEMBER.fullmatch(code[p - 2].op_str)[1], 16)] for p, i in enumerate(code)
                        if self.call_name(i).endswith('SetTabVisible'))
        mode, mode_span = self.bindings('InitialiseFormMode')
        app, app_span = self.bindings('RefreshAppStateChange')
        radio, radio_span = self.code(DIALOG + 'HandleSENLLIndicatorOnClick')
        indicators, control = {}, None
        for ins in radio:
            field = re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', ins.op_str)
            if field and int(field[1], 16) in self.controls:
                control = self.controls[int(field[1], 16)]
            match = re.fullmatch(r'byte ptr \[eax \+ 0x348\], (\d+)', ins.op_str)
            if ins.mnemonic == 'mov' and match:
                indicators[control] = int(match[1])
        switch, switch_span = self.code(DIALOG + 'HandleAppStateChange')
        toggled = [int(switch[p - 1].op_str.split(', ')[1], 0) for p, i in enumerate(switch)
                   if self.call_name(i).endswith('TInputBlockCollection.GetItem')]
        edit, edit_span = self.code(DIALOG + 'SetTargetLuxEditText')
        byte, byte_span = self.code(DIALOG + 'SetTargetLuxByteValue')
        clamp = [int(i.op_str.split(', ')[1], 0) for i in edit if i.mnemonic == 'cmp']
        lux_clamp = [int(i.op_str.split(', ')[1], 0) for i in byte if i.mnemonic == 'cmp']
        convert, convert_span = self.code('CIS_CBus.Lux2550ToByte')
        divisor = [struct.unpack('<f', self.raw(int(m[1], 16), 4))[0] for i in convert
                   for m in [re.fullmatch(r'dword ptr \[(0x[0-9a-f]+)\]', i.op_str)] if i.mnemonic == 'fdiv' and m]
        rounding = [self.call_name(i) for i in convert if i.mnemonic == 'call']
        exclusions = {}
        for handler in ('HandleSENLLGroupComboOnIncludeItem', 'HandleSENLLEnableGroupOnIncludeItem'):
            body, body_span = self.code(DIALOG + handler)
            exclusions[handler] = {'sha256': body_span, 'compares': sorted({self.call_name(i).rsplit('.', 1)[1]
                                   for i in body if i.mnemonic == 'call' and self.call_name(i)})}
        if (hidden != ['tsBankSwitch', 'tsBlocks', 'tsEnvironment', 'tsIndicators', 'tsKeyFunctions',
                       'tsLightLevel', 'tsOccupancy', 'tsScenes'] or clamp != [200] or lux_clamp != [2000]
                or divisor != [10.0] or rounding != ['Math.Ceil'] or toggled != [2, 2]):
            raise ValueError('Unexpected SENLL dialog shape')
        return {'initialise_sha256': span, 'hidden_tabs': hidden,
                'bindings': mode + app, 'bindings_sha256': {'InitialiseFormMode': mode_span,
                                                            'RefreshAppStateChange': app_span},
                'indicator_radio_unit_flag': indicators, 'indicator_sha256': radio_span,
                'on_off_application_switch': {'block_index': toggled[0], 'sha256': switch_span,
                                              'rule': 'toggles Blocks[2].SecondaryApplication; RefreshAppStateChange '
                                                      'clears it and disables the switch when the unit has no '
                                                      'application 2 or its address is 255'},
                'target': {'edit_text_byte_clamp': clamp[0], 'edit_text_sha256': edit_span,
                           'entered_lux_clamp': lux_clamp[0], 'entered_lux_sha256': byte_span,
                           'lux_to_byte': 'Math.Ceil(lux / 10.0) for 0..2550', 'lux_to_byte_sha256': convert_span},
                'group_combo_exclusions': exclusions,
                'exclusion_rule': ('A group combo omits groups other than 255 that another block or the maintenance '
                                   'enable group already uses, except its own current value; the enable combo '
                                   'omits groups used by any block.')}


def review(exe_path, map_path):
    toolkit = LightLevelReview(Path(exe_path), Path(map_path))
    forced, forced_span = toolkit.forced()
    return {
        'format': 'cbus-light-level-sensor-review-v1',
        'original_execution': False,
        'inputs': {'CBusToolkit.exe': EXE_SHA256, 'CBusToolkit.map': MAP_SHA256},
        'save': {'prepare_forced_parameters': {'sha256': forced_span, 'writes': forced},
                 'light_level_before_save': toolkit.before_save(),
                 'margin': 'Inherited multisensor AfterLoad/BeforeSave; see research/fixtures/'
                           'sensor-margin-original-vectors.json'},
        'unit': toolkit.unit(),
        'dialog': toolkit.dialog(),
        'limits': [
            'Static EXE/MAP analysis only; no Toolkit dialog or save was executed.',
            'Base Neo/NeoPro block, timer and bank serialization is assumed to round-trip loaded values; '
            'only the save steps named here are source-recovered.',
            'The broadcast interval (block 5 timer), Global and Power Fail tabs and ambient light '
            'reading are not modelled.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(review(args.exe, args.map), indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
