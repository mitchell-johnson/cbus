"""Recover the Toolkit 1.18 ST7 PIR sensor dialog and save from the EXE/MAP.

Static analysis only: it disassembles the pinned original CBusToolkit.exe with
its MAP symbols and parses DFM resources, and executes no vendor code. The
receipt holds method digests, parameter names, integer constants, control
component names and derived rules. It contains no unit specification content,
help text or UI captions. Keep the vendor inputs outside Git.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sensor_profile_review import EXE_SHA256, MAP_SHA256, Toolkit, digest  # noqa: E402

AGENT = 'CIS_TCBusST7SensorCGateAgent.TCBusST7PIRSensorCGateAgent.'
MULTI = 'CIS_TCBusST7SensorCGateAgent.TCBusST7MultisensorCGateAgent.'
UNIT = 'CIS_TCBusST7SensorUnit.TCBusST7PIRSensorUnit.'
DIALOG = 'CIS_TddST7Sensors.TddST7PIRSensor.'
KEYCLASS = {'TST7SENPIRSS': 'CIS_TSENPIRSS.TST7SENPIRSS.', 'TST7SENPIROA': 'CIS_TSENPIRSS.TST7SENPIROA.'}
HANDLERS = ('HandleDayMoveChange', 'HandleNightMoveChange', 'HandleSunsetChange', 'HandleAnyMoveChange')
# Delphi 32-bit VMT: field table at -0x44 (the review helper reads -0x38/-0x30).
VMT_FIELD_TABLE = -0x44


class Review(Toolkit):
    def disasm(self, name):
        code, span = self.code(name)
        return code, span

    def members(self, agent_symbol):
        result = super().members(agent_symbol)
        # TCoreKeyInputCGateAgent.CreateEEPROMLevelAttributes creates the
        # LightIndex/LightLevel/LightLevelStore attributes outside InternalCreate.
        code, _ = self.code('CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.CreateEEPROMLevelAttributes')
        text = None
        for ins in code:
            if ins.mnemonic == 'push' and re.fullmatch(r'0x[0-9a-f]{6,8}', ins.op_str):
                text = self.literal(int(ins.op_str, 16))
            match = re.fullmatch(r'dword ptr \[edx \+ (0x[0-9a-f]+)\], eax', ins.op_str)
            if ins.mnemonic == 'mov' and match and text:
                result.setdefault(int(match[1], 16), text)
                text = None
        return result

    def constant(self, name, *, byte=False):
        code, _ = self.code(name)
        pattern = r'byte ptr \[ebp - 5\], (0x[0-9a-f]+|\d+)' if byte else r'dword ptr \[ebp - 8\], (0x[0-9a-f]+|\d+)'
        values = [int(re.fullmatch(pattern, ins.op_str)[1], 0) for ins in code
                  if ins.mnemonic == 'mov' and re.fullmatch(pattern, ins.op_str)]
        if len(values) != 1:
            raise ValueError('Unexpected constant method shape: ' + name)
        return bool(values[0]) if byte else values[0]

    def fields(self, class_symbol):
        out, vmt = {}, self.names[class_symbol] + 0x58
        while vmt:
            table = self.u32(vmt + VMT_FIELD_TABLE)
            if table:
                count, position = struct.unpack('<H', self.raw(table, 2))[0], table + 6
                for _ in range(count):
                    offset, length = self.u32(position), self.raw(position + 6, 1)[0]
                    out.setdefault(offset, self.raw(position + 7, length).decode('ascii'))
                    position += 7 + length
            parent = self.u32(vmt - 0x30)
            vmt = self.u32(parent) if parent else 0
        return out

    def forced(self, members):
        code, span = self.code(AGENT + 'PrepareForcedParameters')
        rows, value, index = [], None, None
        for position, ins in enumerate(code):
            if ins.mnemonic == 'mov' and re.fullmatch(r'edx, (0x[0-9a-f]+|\d+)|dl, [01]', ins.op_str):
                value = int(ins.op_str.split(', ')[1], 0)
            elif ins.mnemonic == 'xor' and ins.op_str in ('edx, edx', 'dl, dl'):
                value = 0
            elif ins.mnemonic == 'xor' and ins.op_str == 'ecx, ecx':
                index = 0
            member = re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', ins.op_str)
            if ins.mnemonic != 'mov' or not member or position + 1 >= len(code):
                continue
            name, following = members[int(member[1], 16)], code[position + 1]
            helper = self.symbols.get(self.target(following) or 0, '')
            if following.op_str == 'ecx, dword ptr [eax]':
                rows.append({'parameter': name, 'value': value, 'write': 'SetValue'})
            elif helper.endswith('.SetArrayInteger'):
                rows.append({'parameter': name, 'index': value, 'value': index, 'write': 'SetArrayInteger'})
            elif following.op_str == 'byte ptr [eax + 0x58], 0':
                rows.append({'parameter': name, 'programmable': False})
        return rows, span

    def before_save(self, members):
        code, span = self.code(AGENT + 'BeforeSaveProgrammingInformation')
        calls = [self.symbols[self.target(i)] for i in code if i.mnemonic == 'call' and self.target(i) in self.symbols]
        unit_flag = [int(m[1], 16) for i in code for m in [re.fullmatch(r'byte ptr \[eax \+ (0x[0-9a-f]+)\], 0', i.op_str)]
                     if i.mnemonic == 'cmp' and m]
        values = [self.literal(int(i.op_str.split(', ')[1], 16)) for i in code
                  if i.mnemonic == 'mov' and re.fullmatch(r'edx, 0x[0-9a-f]{6,8}', i.op_str)]
        written = [members[int(m[1], 16)] for i in code for m in [re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', i.op_str)]
                   if i.mnemonic == 'mov' and m]
        load, load_span = self.code(AGENT + 'AfterLoadProgrammingInformation')
        compared = [int(i.op_str.split(', ')[1], 0) for i in load if i.mnemonic == 'cmp' and i.op_str.startswith('eax, ')]
        loaded = [members[int(m[1], 16)] for i in load for m in [re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', i.op_str)]
                  if i.mnemonic == 'mov' and m]
        setter = [f'{m.split(".")[1]}.{m.split(".")[2]}' for m in self.symbols.values()
                  if m.endswith('HandleDisableIndicatorOnChange') and 'KeyInputBlocks4' in m]
        if len(unit_flag) != 1 or len(values) != 1 or written != ['IndicatorBlockAssignment'] or compared != [7]:
            raise ValueError('Unexpected PIR save/load shape')
        return {'calls': calls, 'sha256': span, 'after_load_sha256': load_span,
                'conditional_write': {'parameter': written[0], 'value': [int(v, 0) for v in values[0].split()],
                                      'unit_flag_offset': hex(unit_flag[0]),
                                      'flag_loaded_from': f'{loaded[0]}[0] == {compared[0]}',
                                      'flag_edited_by': setter}}

    def multisensor_save(self, members):
        code, span = self.code(MULTI + 'BeforeSaveProgrammingInformation')
        constants, broadcast = [], []
        for position, ins in enumerate(code):
            member = re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', ins.op_str)
            if ins.mnemonic != 'mov' or not member:
                continue
            name = members.get(int(member[1], 16))
            window = code[max(0, position - 6):position]
            calls = [self.symbols.get(self.target(i) or 0, '') for i in window if i.mnemonic == 'call']
            if name == 'BroadcastActive':
                ints = [int(i.op_str.split(', ')[1], 0) if i.mnemonic == 'mov' else 0 for i in window
                        if (i.mnemonic == 'mov' and re.fullmatch(r'edx, \d+', i.op_str)) or i.op_str == 'edx, edx']
                broadcast.extend(ints)
            elif calls and calls[-1].endswith('@VarFromBool') and not any('Get' in c for c in calls):
                flags = [i for i in window if i.op_str in ('edx, edx', 'dl, 1')]
                constants.append({'parameter': name, 'value': int(bool(flags and flags[-1].op_str == 'dl, 1'))})
        margin = [struct.unpack('<f', self.raw(int(m[1], 16), 4))[0] for i in code
                  for m in [re.fullmatch(r'dword ptr \[(0x[0-9a-f]+)\]', i.op_str)] if i.mnemonic in ('fdiv', 'fmul') and m]
        load, load_span = self.code(MULTI + 'AfterLoadProgrammingInformation')
        load_margin = [struct.unpack('<f', self.raw(int(m[1], 16), 4))[0] for i in load
                       for m in [re.fullmatch(r'dword ptr \[(0x[0-9a-f]+)\]', i.op_str)] if i.mnemonic == 'fmul' and m]
        bounds = [int(i.op_str.split(', ')[1], 0) for i in load if i.mnemonic == 'cmp' and re.fullmatch(r'eax, 7', i.op_str)]
        if broadcast != [4, 0] or margin != [100.0] or load_margin != [100.0] or bounds != [7]:
            raise ValueError('Unexpected multisensor save/load arithmetic')
        return {'sha256': span, 'after_load_sha256': load_span, 'unconditional_writes': constants,
                'broadcast_active': {'loaded_active_when': '1 <= BroadcastActive <= 6', 'saved_active': 4, 'saved_inactive': 0},
                'margin': {'loaded_percent': 'ROUND(ext(PECMarginLux / PECTargetLux) * 100.0), 0 when target is 0',
                           'saved_margin': 'ROUND(PECTargetLux * ext(percent / 100.0))',
                           'round': 'System.@ROUND, x87 extended precision, ties to even'}}

    def power_fail(self, members):
        save, save_span = self.code('CIS_TCBusST7SensorCGateAgent.SavePowerFail')
        load, load_span = self.code('CIS_TCBusST7SensorCGateAgent.LoadPowerFail')
        index = [int(i.op_str.split(', ')[1], 0) for i in save
                 if i.mnemonic == 'mov' and re.fullmatch(r'edx, \d+', i.op_str)]
        if 8 not in index or 9 not in [int(i.op_str.split(', ')[1], 0) for i in load
                                       if i.mnemonic == 'mov' and re.fullmatch(r'edx, \d+', i.op_str)]:
            raise ValueError('Unexpected power-fail shape')
        return {'save_sha256': save_span, 'load_sha256': load_span, 'occupancy_level_index': 8,
                'states': ['disabled', 'enabled', 'resume'],
                'load': 'PIRLevelStore -> resume; else disabled when (LightLevel[8] == 255) == PIREnablerGroupLogic, otherwise enabled',
                'save': 'resume -> PIRLevelStore=1, LightLevel[8] kept; disabled -> LightLevel[8]=255 if PIREnablerGroupLogic else 0; '
                        'enabled -> LightLevel[8]=0 if PIREnablerGroupLogic else 255; both clear PIRLevelStore'}

    def templates(self):
        rows = {}
        for key, handler in enumerate(HANDLERS, 1):
            code, span = self.code(DIALOG + handler)
            items = {int(i.op_str.split(', ')[1], 0) for i in code if i.mnemonic == 'mov' and re.fullmatch(r'edx, [1-3]', i.op_str)}
            items |= {0 for i in code if i.mnemonic == 'xor' and i.op_str == 'edx, edx'}
            template = {int(i.op_str.split(', ')[1], 0) for i in code if i.mnemonic == 'mov' and re.fullmatch(r'dl, 0x[0-9a-f]+', i.op_str)}
            message = {int(i.op_str.split(', ')[1], 0) for i in code if i.mnemonic == 'mov' and re.fullmatch(r'edx, 0x5208', i.op_str)}
            if items != {key - 1} or len(template) != 1 or message != {0x5208}:
                raise ValueError('Unexpected PIR key handler shape: ' + handler)
            rows[key] = {'handler': handler, 'template': hex(template.pop()), 'sha256': span, 'prompt_message': hex(0x5208)}
        init, _ = self.code('CIS_TKeyMacroFunction.InitialiseKeyMacroFunctionFactory')
        groups, dl = {}, None
        for position, ins in enumerate(init):
            if ins.mnemonic == 'mov' and re.fullmatch(r'byte ptr \[ebp - 8\], 0x[0-9a-f]+', ins.op_str):
                group = int(ins.op_str.split(', ')[1], 0)
            if ins.mnemonic == 'mov' and re.fullmatch(r'dl, 0x[0-9a-f]+', ins.op_str):
                dl = int(ins.op_str.split(', ')[1], 0)
            if ins.mnemonic == 'call' and self.symbols.get(self.target(ins) or 0, '').endswith('.RegisterTemplate') and dl is not None:
                groups.setdefault(dl, group)
        stage, _ = self.code('CIS_TKeyMicroFunctionGroup.InitialiseKeyMicroFunctionGroupFactory')
        micro, pushes = {}, []
        for ins in stage:
            if ins.mnemonic == 'push' and re.fullmatch(r'0x[0-9a-f]+|\d+', ins.op_str):
                pushes.append(int(ins.op_str, 0))
            elif ins.mnemonic == 'mov' and re.fullmatch(r'dl, 0x[0-9a-f]+', ins.op_str):
                dl = int(ins.op_str.split(', ')[1], 0)
            elif ins.mnemonic == 'call' and self.symbols.get(self.target(ins) or 0, '').endswith('.RegisterKeyMicroFunctionGroup'):
                # Seven stack arguments pushed in declaration order; the
                # second through fifth are the JP, SR, LP and LR stages.
                if len(pushes) >= 7:
                    micro[dl] = pushes[-7:][1:5]
                pushes = []
        for row in rows.values():
            group = groups[int(row['template'], 16)]
            row.update({'micro_function_group': hex(group), 'jp_sr_lp_lr': micro[group]})
        return rows

    def defaults(self):
        code, span = self.code(UNIT + 'ApplyMicroFunctionDefaults')
        stages, split, value, key, branch = {}, None, None, None, 'common'
        for position, ins in enumerate(code):
            if ins.mnemonic == 'mov' and re.fullmatch(r'edx, 0x[0-9a-f]{6,8}', ins.op_str):
                split = self.literal(int(ins.op_str.split(', ')[1], 16))
                branch = 'at_least'
            elif ins.mnemonic == 'jmp' and branch == 'at_least':
                branch = 'below'
            if ins.mnemonic == 'mov' and re.fullmatch(r'dl, 0x[0-9a-f]+|dl, \d+', ins.op_str) and position + 1 < len(code) \
                    and code[position + 1].mnemonic == 'call' and self.symbols.get(self.target(code[position + 1]) or 0, '').endswith('GetKeyMicroFunction'):
                value = int(ins.op_str.split(', ')[1], 0)
            elif ins.mnemonic == 'xor' and ins.op_str == 'edx, edx' and position + 1 < len(code) \
                    and self.symbols.get(self.target(code[position + 1]) or 0, '').endswith('GetKeyMicroFunction'):
                value = 0
            elif ins.mnemonic == 'mov' and re.fullmatch(r'edx, [1-3]', ins.op_str):
                key = int(ins.op_str.split(', ')[1])
            elif ins.mnemonic == 'xor' and ins.op_str == 'edx, edx' and position + 3 < len(code) \
                    and 'GetItem' in self.symbols.get(self.target(code[position + 3]) or 0, ''):
                key = 0
            if ins.mnemonic == 'call' and self.symbols.get(self.target(ins) or 0, '').endswith('.SetMicroFunction'):
                previous = next(i for i in reversed(code[:position]) if i.mnemonic != 'pop')
                stage = 0 if previous.op_str == 'edx, edx' else int(previous.op_str.split(', ')[1], 0)
                stages.setdefault((branch if key == 3 else 'common'), {}).setdefault(key + 1, [0, 0, 0, 0])[stage] = value
        return {'sha256': span, 'firmware_split': split, 'keys': {str(k): v for k, v in stages['common'].items()},
                'key4_firmware_at_least_split': stages['at_least'][4], 'key4_firmware_below_split': stages['below'][4],
                'note': 'Defaults/reset only; the dialog applies the fixed key templates instead.'}

    def dialog(self):
        code, span = self.code(DIALOG + 'Initialise')
        form = self.fields('CIS_TfrmSENPILL..TfrmSENPILL')
        hidden = []
        for position, ins in enumerate(code):
            match = re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', ins.op_str)
            if ins.mnemonic == 'mov' and match and position + 2 < len(code) \
                    and self.symbols.get(self.target(code[position + 2]) or 0, '').endswith('SetTabVisible'):
                hidden.append(form[int(match[1], 16)])
        disabled = sorted(int(code[p - 1].op_str.split(', ')[1]) + 1 for p, ins in enumerate(code)
                          if ins.mnemonic == 'call' and self.symbols.get(self.target(ins) or 0, '').endswith('SetKeyColumnEnabled'))
        compare = [self.symbols[self.target(i)] for i in code if i.mnemonic == 'call' and self.target(i) in self.symbols
                   and self.symbols[self.target(i)].endswith(('CompareBlocks', 'SetDayMovementSameAsNight'))]
        empty = [name for name in ('InitialiseSubFormLightLevel', 'InitialiseSubFormBankSwitch', 'InitialiseSubFormEnvironment')
                 if not any(i.mnemonic == 'call' for i in self.code(DIALOG + name)[0])]
        copy, copy_span = self.code(UNIT + 'RefreshDayMovementFromNightMovement')
        order = [int(i.op_str.split(', ')[1]) if i.op_str.startswith('edx, ') and i.op_str != 'edx, edx' else 0
                 for i in copy if i.mnemonic in ('mov', 'xor') and re.fullmatch(r'edx, (edx|\d)', i.op_str)]
        if order != [0, 1]:
            raise ValueError('Unexpected block-copy shape')
        return {'initialise_sha256': span, 'hidden_tabs': sorted(hidden), 'empty_subforms': empty,
                'disabled_block_grid_key_columns': disabled, 'link_calls': compare,
                'motion_in_darkness_link': {'checkbox_initial': 'InputKeys[0].CompareBlocks(InputKeys[1])',
                                            'copy': 'InputKeys[1].CopyBlocks(InputKeys[0]) on link and on every key-1 change',
                                            'sha256': copy_span}}

    def unit(self):
        limits = {'MaximumBlockCount': self.constant(UNIT + 'MaximumBlockCount'),
                  'MaximumIndicatorCount': self.constant(UNIT + 'MaximumIndicatorCount'),
                  'IsCorridorLinkingSupported': self.constant(UNIT + 'IsCorridorLinkingSupported', byte=True),
                  'IsInfraredNECSupported': self.constant(UNIT + 'IsInfraredNECSupported', byte=True)}
        classes = {}
        for name, prefix in KEYCLASS.items():
            classes[name] = {'MaximumKeyCount': self.constant(prefix + 'MaximumKeyCount'),
                             'GetMaximumVirtualKeyCount': self.constant(prefix + 'GetMaximumVirtualKeyCount'),
                             'IsJoinModeSupported': self.constant(prefix + 'IsJoinModeSupported', byte=True),
                             'IsDualJoinModeSupported': self.constant(prefix + 'IsDualJoinModeSupported', byte=True)}
        override, _ = self.code(UNIT + 'RefreshMacroFunctionOverrides')
        fixed = any(self.symbols.get(self.target(i) or 0, '').endswith('SetMacroFunctionSENPIROverride') for i in override)
        return {**limits, 'classes': classes, 'macro_function_fixed_on_every_key': fixed}

    def attribute_flags(self):
        code, span = self.code('CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.ParameterProgrammingSetSingle')
        checks = [i.op_str for i in code if i.mnemonic == 'cmp' and re.fullmatch(r'byte ptr \[eax \+ 0x(58|38)\], 0', i.op_str)]
        if checks != ['byte ptr [eax + 0x58], 0', 'byte ptr [eax + 0x38], 0']:
            raise ValueError('Unexpected PP SET gate')
        return {'sha256': span, 'rule': 'PP SET is sent only for attributes with +0x58 (programmable) and +0x38 (changed) set',
                'string_array_setvalue': 'TStringAttribute.SetValue stores the variant text, so an integer 0 is sent as "0"'}


def review(exe_path, map_path):
    toolkit = Review(Path(exe_path), Path(map_path))
    members = toolkit.members('CIS_TCBusST7SensorCGateAgent..TCBusST7PIRSensorCGateAgent')
    forced, forced_span = toolkit.forced(members)
    return {
        'format': 'cbus-pir-sensor-review-v1',
        'original_execution': False,
        'inputs': {'CBusToolkit.exe': EXE_SHA256, 'CBusToolkit.map': MAP_SHA256},
        'save': {'pir_before_save': toolkit.before_save(members),
                 'prepare_forced_parameters': {'sha256': forced_span, 'writes': forced},
                 'multisensor_before_save': toolkit.multisensor_save(members),
                 'power_fail': toolkit.power_fail(members),
                 'pp_set_gate': toolkit.attribute_flags()},
        'unit': toolkit.unit(),
        'key_templates': toolkit.templates(),
        'micro_function_defaults': toolkit.defaults(),
        'dialog': toolkit.dialog(),
        'limits': [
            'Static EXE/MAP/DFM analysis only; no Toolkit dialog or save was executed.',
            'Base Neo/NeoPro key, block, timer and scale serialization is assumed to round-trip loaded values; '
            'only the save steps named here are source-recovered.',
            'The C-Gate effect of a one-value array write (SceneKeySelector "0") is established natively, not statically.',
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
