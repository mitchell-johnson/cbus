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
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

import pefile

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
        block_prefix = 'CIS_TInputKey.TInputBlock.'
        collision, collision_span = self.code(block_prefix + 'RefreshBlockApplicationFromBlockSecondary')
        collision_calls = [self.call_name(i) for i in collision if i.mnemonic == 'call' and self.call_name(i)]
        if (not all(name in collision_calls for name in ('CIS_TInputKey.TInputKey.AddBlock',
                                                         'CIS_TInputKey.TInputKey.RemoveBlock',
                                                         block_prefix + 'SetGroup'))
                or not any(i.mnemonic == 'mov' and i.op_str == 'edx, 0xff' for i in collision)):
            raise ValueError('Unexpected native application-collision key/group reassignment')
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
                'application_collision': {'sha256': collision_span, 'calls': collision_calls,
                    'native_behavior': 'a matching destination block receives shared key allocations; '
                                       'the switched block group is cleared to 255',
                    'portable_behavior': 'refuse before PP mutation; key-block reassignment is not modelled'},
                'exclusion_rule': ('A group combo omits groups other than 255 that another block or the maintenance '
                                   'enable group already uses, except its own current value; the enable combo '
                                   'omits groups used by any block.')}

    def broadcast_and_power_fail(self):
        """Pin the selected broadcast block, timer writer and inherited save order."""
        names = {
            'broadcast_dialog': DIALOG + 'HandleBroadcastBlockExtensionClick',
            'timer_dialog_save': 'CIS_TfrmBlockTimer.TfrmBlockTimer.GetValues',
            'timer_bytes_save': 'CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.SaveTimerHighAndLowBytes',
            'power_fail_load': 'CIS_TCBusST7SensorCGateAgent.LoadPowerFail',
            'power_fail_save': 'CIS_TCBusST7SensorCGateAgent.SavePowerFail',
            'multisensor_save': 'CIS_TCBusST7SensorCGateAgent.TCBusST7MultisensorCGateAgent.BeforeSaveProgrammingInformation',
            'light_level_save': AGENT + 'BeforeSaveProgrammingInformation',
            'timer_change': 'CIS_TInputKey.TInputBlock.HandleTimerAfterChange',
            'timer_minimum_change': 'CIS_TInputKey.TInputBlock.HandleTimerMinAfterChange',
            'timer_read': 'CIS_TInputKey.TInputBlock.GetTimer',
            'timer_minimum_read': 'CIS_TInputKey.TInputBlock.GetTimerMin',
            'timer_write': 'CIS_TInputKey.TInputBlock.SetTimer',
            'timer_dialog_limits': 'CIS_TfrmBlockTimer.TfrmBlockTimer.SetValue_ExpiryTime',
            'timer_dialog_encode': 'CIS_TfrmBlockTimer.TfrmBlockTimer.EncodeExpiryTime',
            'timer_seconds_encode': 'CIS_Dates.EncodeCBusTime',
        }
        methods = {}
        for key, name in names.items():
            code, span = self.code(name)
            methods[key] = {'sha256': span, 'calls': [self.call_name(i) for i in code
                                                   if i.mnemonic == 'call' and self.call_name(i)]}
        broadcast, _ = self.code(names['broadcast_dialog'])
        blocks = [broadcast[p - 1].op_str for p, i in enumerate(broadcast)
                  if self.call_name(i).endswith('TInputBlockCollection.GetItem')]
        required = ('TfrmBlockTimer.SetBlock', 'TfrmBlockTimer.DisableTimerSubFunctions',
                    'TfrmBlockTimer.DisableTimerFunctions', 'TfrmBlockTimer.Execute')
        calls = methods['broadcast_dialog']['calls']
        if blocks != ['edx, 4'] or not all(any(c.endswith(suffix) for c in calls) for suffix in required):
            raise ValueError('Unexpected broadcast interval dialog contract')
        if self.agent[0x204] != 'PECLevelStore' or self.agent[0x1f0] != 'PECEnablerGroupLogic':
            raise ValueError('Unexpected power-fail agent members')
        light_calls = methods['light_level_save']['calls']
        if light_calls.index(names['multisensor_save']) >= light_calls.index(AGENT + 'PrepareForcedParameters'):
            raise ValueError('Unexpected inherited/forced save order')
        if not any(c.endswith('SavePowerFail') for c in methods['multisensor_save']['calls']):
            raise ValueError('Missing inherited power-fail save')
        for key in ('timer_change', 'timer_minimum_change'):
            body, _ = self.code(names[key])
            calls = methods[key]['calls']
            if (calls != [names['timer_read'], names['timer_minimum_read'], names['timer_minimum_read'],
                          names['timer_write']] or not any(i.mnemonic == 'cmp' and i.op_str == 'bx, ax' for i in body)
                    or not any(i.mnemonic == 'jae' for i in body)):
                raise ValueError('Unexpected loaded broadcast timer minimum clamp')
        limits, _ = self.code(names['timer_dialog_limits'])
        maximum = next(p for p, i in enumerate(limits)
                       if i.mnemonic == 'call' and self.call_name(i).endswith('SetMaxTime'))
        if ([i.op_str for i in limits[:maximum] if i.mnemonic == 'mov' and i.op_str in
             ('cx, 0xf', 'dx, 0xc', 'ax, 0x12')] != ['cx, 0xf', 'dx, 0xc', 'ax, 0x12']
                or not any(c.endswith('SetMinTime') for c in methods['timer_dialog_limits']['calls'])):
            raise ValueError('Unexpected timer dialog maximum 18:12:15')
        encode, _ = self.code(names['timer_seconds_encode'])
        if (sum(i.mnemonic == 'imul' and i.op_str.endswith(', 0x3c') for i in encode) != 3
                or not any(i.mnemonic == 'cmp' and i.op_str == 'dword ptr [ebp - 0xc], 0xffff' for i in encode)
                or not any(i.mnemonic == 'ja' for i in encode)
                or names['timer_seconds_encode'] not in methods['timer_dialog_encode']['calls']):
            raise ValueError('Unexpected unsigned 16-bit seconds encoding')
        return {'methods': methods,
                'broadcast': {'block_index': 4, 'minimum_seconds': 10, 'maximum_seconds': 65535,
                              'expiry_and_key_functions_editable': False,
                              'parameters': ['TimerHighByte[4]', 'TimerLowByte[4]'],
                              'loaded_timer_rule': 'max(10, TimerHighByte[4]*256 + TimerLowByte[4])',
                              'maximum_time': [18, 12, 15]},
                'power_fail': {'states': ['disabled', 'enabled', 'resume'], 'light_level_index': 9,
                               'store_parameter': 'PECLevelStore', 'polarity_parameter': 'PECEnablerGroupLogic',
                               'load': 'resume if store; otherwise disabled when (level == 255) equals polarity',
                               'save': 'resume sets store; other states clear store and save 0/255 using loaded polarity',
                               'forced_save_afterwards': 'PECEnablerGroupLogic=0; LightLevel[8]=0; PIRLevelStore=0',
                               'reloaded_state_can_differ': True}}

    def global_status_interval(self):
        """Pin the SENLL Global selector, its enabling rules and native PP property."""
        global_ = 'CIS_TcdLearnUnitGlobal.TcdLearnUnitGlobal.'
        input_ = 'CIS_TCBusInputUnit.TCBusInputUnit.'
        agent = 'CIS_TCBusInputUnitCGateAgent.TCBusInputUnitCGateAgent.'
        names = {
            'senll_global_construct': DIALOG + 'InitialiseSubFormGlobals',
            'global_initialise': global_ + 'Initialise',
            'global_setup': global_ + 'SetupNonFlashComponents',
            'global_populate': global_ + 'PopulateNonFlashComponents',
            'global_change': global_ + 'HandleStatusReportComboChange',
            'integer_to_text': 'CIS_ICBusInputUnit.StatusReportIntegerToString',
            'text_to_integer': 'CIS_ICBusInputUnit.StatusReportStringToInteger',
            'unit_get': input_ + 'GetStatusReportInterval',
            'unit_set': input_ + 'SetStatusReportInterval',
            'agent_create': agent + 'CreateAttributeStatusReportInterval',
            'agent_load': agent + 'LoadStatusReportInterval',
            'agent_save': agent + 'SaveStatusReportInterval',
            'input_save': agent + 'BeforeSaveProgrammingInformation',
            'learn_mode_enabled': KEYS + 'LearnModePropertiesEnabled',
        }
        bodies, methods = {}, {}
        for key, name in names.items():
            code, span = self.code(name)
            bodies[key] = code
            methods[key] = {'sha256': span, 'calls': [self.call_name(i) for i in code
                                                   if i.mnemonic == 'call' and self.call_name(i)]}
        # The Global constructor uses TfrmLearnUnitGlobal, not the distinct
        # general input-unit Global form or embedded learn-mode child frame.
        frame = self.u32(0xfb1774)
        frame_symbol = self.symbols[frame - 0x58]
        controls = self.fields(frame_symbol)
        if (self.class_name(frame - 0x58) != 'TfrmLearnUnitGlobal'
                or controls[0x29c] != 'cmbStatusReportInterval'
                or methods['senll_global_construct']['calls'][-1] != names['global_initialise']
                or self.symbols[self.u32(self.names['CIS_TSENLL..TST7SENLL'] + 0x58 + 0x160)]
                   != names['learn_mode_enabled']
                or self.constant(names['learn_mode_enabled'], byte=True) is not False):
            raise ValueError('Unexpected SENLL Global constructor/learn-mode capability')
        setup = bodies['global_setup']
        required = [('mov', 'byte ptr [ebp - 5], 3'), ('inc', 'byte ptr [ebp - 5]'),
                    ('cmp', 'byte ptr [ebp - 5], 0'), ('call', 'dword ptr [edx + 0x160]')]
        hidden = [controls[int(MEMBER.fullmatch(setup[p - 2].op_str)[1], 16)] for p, i in enumerate(setup)
                  if i.mnemonic == 'call' and self.call_name(i).endswith('SetVisible')]
        if (not all(any((i.mnemonic, i.op_str) == pair for i in setup) for pair in required)
                or hidden != ['frmUnitGlobalLearnModeNEW1', 'grpLearnMode']
                or methods['global_change']['calls'][:3] != ['Controls.TControl.GetText', names['text_to_integer'],
                                                           names['unit_set']]
                or names['integer_to_text'] not in methods['global_setup']['calls']
                or names['unit_get'] not in methods['global_populate']['calls']):
            raise ValueError('Unexpected Global integer selector/change contract')
        if (self.agent[0xf4] != 'StatusReportInterval' or self.literal(0xcc650c) != 'StatusReportInterval'
                or names['unit_set'] not in methods['agent_load']['calls']
                or names['unit_get'] not in methods['agent_save']['calls']
                or names['agent_save'] not in methods['input_save']['calls']):
            raise ValueError('Unexpected StatusReportInterval PP property mapping')
        formatted = bodies['integer_to_text']
        if not any(i.mnemonic == 'cmp' and i.op_str == 'dword ptr [ebp - 4], 3' for i in formatted):
            raise ValueError('Unexpected Global interval display minimum')
        # Resolve the exact original ResourceString used as the number suffix.
        # Keep only its identity/hash and derived unit in the sanitized receipt.
        resource = self.u32(self.u32(0x13c1b3c) + 4)
        self.image.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
        suffixes = []
        for group in self.image.DIRECTORY_ENTRY_RESOURCE.entries:
            if group.id != 6:
                continue
            for block in group.directory.entries:
                if block.id != resource // 16 + 1:
                    continue
                for language in block.directory.entries:
                    raw = self.image.get_data(language.data.struct.OffsetToData, language.data.struct.Size)
                    offset = 0
                    for index in range(16):
                        length = struct.unpack_from('<H', raw, offset)[0]
                        offset += 2
                        value = raw[offset:offset + 2 * length]
                        offset += 2 * length
                        if index == resource % 16:
                            suffixes.append(value)
        if len(suffixes) != 1 or suffixes[0].decode('utf-16le') != ' secs':
            raise ValueError('Unexpected source-pinned status interval display unit')
        return {'methods': methods, 'frame': self.class_name(frame - 0x58),
                'status_report_interval': {'control': controls[0x29c], 'parameter': 'StatusReportInterval',
                                           'minimum': 3, 'maximum': 255, 'unit': 'seconds', 'conversion': 'native integer',
                                           'resource_string_id': resource,
                                           'resource_string_utf16le_sha256': hashlib.sha256(suffixes[0]).hexdigest(),
                                           'loaded_display_minimum': 3,
                                           'loaded_below_minimum_writeback_verified': False},
                'learn_mode_controls_visible': False, 'status_interval_control_hidden_by_learn_mode': False,
                'hidden_controls': hidden, 'original_gui_execution': False}


def review(exe_path, map_path):
    toolkit = LightLevelReview(Path(exe_path), Path(map_path))
    forced, forced_span = toolkit.forced()
    return {
        'format': 'cbus-light-level-sensor-review-v3',
        'original_execution': False,
        'inputs': {'CBusToolkit.exe': EXE_SHA256, 'CBusToolkit.map': MAP_SHA256},
        'save': {'prepare_forced_parameters': {'sha256': forced_span, 'writes': forced},
                 'light_level_before_save': toolkit.before_save(),
                 'margin': 'Inherited multisensor AfterLoad/BeforeSave; see research/fixtures/'
                           'sensor-margin-original-vectors.json'},
        'unit': toolkit.unit(),
        'dialog': toolkit.dialog(),
        'broadcast_and_power_fail': toolkit.broadcast_and_power_fail(),
        'global_status_interval': toolkit.global_status_interval(),
        'limits': [
            'Static EXE/MAP analysis only; no Toolkit dialog or save was executed.',
            'Base Neo/NeoPro block, timer and bank serialization is assumed to round-trip loaded values; '
            'only the save steps named here are source-recovered.',
            'Ambient light reading is not modelled. Global status-report interval edits are source-pinned; '
            'stored interval values below 3 require an explicit admitted selection because original '
            'Global initialization callback writeback is unverified. The broadcast timer and '
            'light-level Power Fail state have source-pinned parameter behavior; GUI execution '
            'and physical timing/power-failure behavior are not established.',
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
