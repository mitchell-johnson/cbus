"""Source-checked classic DLT indicator GUI bindings for a caller's event oracle.

Call ``gui_binding_facts(image)`` with an EXE/MAP-hash-verified _Toolkit image.
The helper independently checks its EXE hash and all consumed symbol addresses;
the caller must verify MAP_SHA256 because _Toolkit does not retain raw MAP bytes.
These are static source facts, not execution of the Delphi GUI or controller.
"""
from __future__ import annotations

import hashlib
import re
import struct

from project_documentor_static import EXE_SHA256, MAP_SHA256
from extract_toolkit_executable_surface import (Cursor, _read_component_header, _read_value,
                                                _text, parse_binary_dfm)


PREFIX = 'CIS_TcdDLTInputIndicators8.TcdDLTInputIndicators8.'
METHODS = {
    'setup_flash': (PREFIX + 'SetupFlashComponents', 0xFFAD64),
    'setup_events': (PREFIX + 'SetupNonFlashComponents', 0xFFB214),
    'update_nightlight': (PREFIX + 'UpdateNightlightEnabled', 0xFFBA74),
    'nightlight_change': (PREFIX + 'HandleNightlightEnableCheckboxChange', 0xFFBA5C),
    'nightlight_gate': ('CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.NightlightPropertyEnabled', 0xD087C4),
    'prepare_checkbox': ('CIS_FlashGUI.PrepareFlashCheckbox', 0xC0FC64),
    'prepare_slider': ('CIS_FlashGUI.PrepareFlashCxTrackBar', 0xC10BC8),
    'slider_constructor': ('cxTrackBar.TcxCustomTrackBarProperties.Create', 0xC07444),
    'slider_set_min': ('cxTrackBar.TcxCustomTrackBarProperties.SetMin', 0xC07C7C),
    'slider_visual_change': ('CIS_TfrmDLTInputIndicators8.TfrmDLTInputIndicators8.trkKeyPressBrightnessPropertiesChange', 0xFFA5F4),
    'set_visible': ('Controls.TControl.SetVisible', 0x6F61C0),
    'set_enabled': ('Controls.TControl.SetEnabled', 0x6F61F8),
    'control_constructor': ('Controls.TControl.Create', 0x6F4F00),
    'setup_form_for_unit': (PREFIX + 'SetupFormForUnit', 0xFFAD58),
    'set_checked': ('StdCtrls.TCustomCheckBox.SetChecked', 0x68A038),
    'set_state': ('StdCtrls.TCustomCheckBox.SetState', 0x68A04C),
    'checkbox_click': ('StdCtrls.TCustomCheckBox.Click', 0x68A004),
    'changed': ('Controls.TControl.Changed', 0x6F5E98),
    'click': ('Controls.TControl.Click', 0x6F7F98),
    'flash_changed': ('CIS_TFlashCheckBox.TFlashCheckBox.CMChanged', 0xAE8278),
    'flash_change': ('CIS_TFlashCheckBox.TFlashCheckBox.Change', 0xAE8248),
    'set_as_boolean': ('CIS_Handles.TFlashBooleanController.SetAsBoolean', 0x84F1F8),
    'boolean_apply': ('CIS_Handles.TFlashBooleanController.Apply', 0x84F0C4),
    'agent_load': ('CIS_TCBusDynamicLabelInputCGateAgent.TCBusDynamicLabelInputCGateAgent.AfterLoadProgrammingInformation', 0x121BF40),
    'agent_save': ('CIS_TCBusDynamicLabelInputCGateAgent.TCBusDynamicLabelInputCGateAgent.BeforeSaveProgrammingInformation', 0x121D16C),
}
FORM = 'CIS_TfrmDLTInputIndicators8..TfrmDLTInputIndicators8'
CHECKBOX = 'CIS_TFlashCheckBox..TFlashCheckBox'
CONTROLS = {
    0x2CC: 'EnableIndicatorPressed', 0x2D4: 'EnablePageFallback',
    0x308: None, 0x2E0: 'EnableNightLightOnKeys', 0x2E8: 'EnableNightlightOnToggle',
    0x2E4: 'FirstKeyThrowaway', 0x300: 'KeyPressBrightnessLevel',
    0x2D0: None, 0x30C: None,
}


def _has(method, *pairs):
    actual = [(m, op) for _, m, op in method['instructions']]
    assert all(pair in actual for pair in pairs), (hex(method['start']), pairs)


def _calls(image, method, *symbols):
    calls = iter(op for _, m, op in method['instructions'] if m == 'call')
    for name in symbols:
        targets = {hex(address) for address, names in image.symbols.items() if name in names}
        assert targets and any(op in targets for op in calls), name


def _fields(image):
    address = image.dword(image.vmt(FORM) - 0x44)
    data = image.pe.get_data(address - image.base, 4096)
    count = struct.unpack_from('<H', data)[0]
    assert count == 48
    cursor, result = 6, {}
    for _ in range(count):
        offset, _type = struct.unpack_from('<IH', data, cursor)
        length = data[cursor + 6]
        name = data[cursor + 7:cursor + 7 + length].decode('latin1')
        cursor += 7 + length
        if offset in CONTROLS:
            result[offset] = name
    assert set(result) == set(CONTROLS)
    return result


def _dynamic(image, symbol, code):
    vmt = image.vmt(symbol)
    while vmt:
        address = image.dword(vmt - 0x3C)
        if address:
            data = image.pe.get_data(address - image.base, 4096)
            count = struct.unpack_from('<H', data)[0]
            for index in range(count):
                if struct.unpack_from('<H', data, 2 + index * 2)[0] == code:
                    target = struct.unpack_from('<I', data, 2 + count * 2 + index * 4)[0]
                    return {'class': image.class_name(vmt), 'dispatch_id': hex(code),
                            'target': sorted(image.symbols[target])[0], 'target_address': hex(target)}
        parent = image.dword(vmt - 0x30)
        vmt = image.dword(parent) if parent else 0
    raise AssertionError(f'Missing checkbox dispatch {code:#x}')


def _properties(raw, selected_names):
    cursor = Cursor(raw, 4)
    selected_properties = {'Enabled', 'Visible', 'Position', 'Properties.Min', 'Properties.Max',
                           'Properties.Frequency', 'Properties.OnChange', 'UseRawValues',
                           'FlashController.UpdateMode'}
    result = {}

    def visit(depth=0):
        _class, name = _read_component_header(cursor, version=raw[3] - ord('0'))
        properties = {}
        while cursor.peek_u8() != 0:
            key = _text(cursor.short_bytes())
            value = _read_value(cursor, depth=depth + 1)
            if key in selected_properties:
                properties[key] = value
        cursor.u8()
        if name in selected_names:
            result[name] = properties
        while cursor.peek_u8() != 0:
            visit(depth + 1)
        cursor.u8()
    visit()
    assert cursor.remaining == 0
    return result


def gui_binding_facts(image):
    assert hashlib.sha256(image.raw).hexdigest() == EXE_SHA256
    methods = {}
    for key, (name, start) in METHODS.items():
        assert image.by_name.get(name) == start, ('Unexpected GUI source symbol', name)
        methods[key] = image.method(name)
    field_names = _fields(image)
    resources = [entry for kind in image.pe.DIRECTORY_ENTRY_RESOURCE.entries
                 for entry in kind.directory.entries if str(entry.name) == 'TFRMDLTINPUTINDICATORS8']
    assert len(resources) == 1 and len(resources[0].directory.entries) == 1
    leaf = resources[0].directory.entries[0].data.struct
    raw_dfm = image.pe.get_data(leaf.OffsetToData, leaf.Size)
    dfm = parse_binary_dfm(raw_dfm)
    components = {row['name']: row for row in dfm['components']}
    properties = _properties(raw_dfm, set(field_names.values()))
    setup = methods['setup_flash']
    controls = {}
    for offset, expression in CONTROLS.items():
        name = field_names[offset]
        row = {'offset': hex(offset), **components[name], 'expression': expression,
               'dfm_properties': properties[name]}
        if expression:
            indices = [i for i, instruction in enumerate(setup['instructions'])
                       if setup['literal_at'].get(instruction[0]) == expression]
            assert len(indices) == 1, expression
            index = indices[0]
            assert setup['instructions'][index - 1][1:] == ('mov', f'eax, dword ptr [eax + {hex(offset)}]')
            if components[name]['class'] in ('TFlashCheckBox', 'TFlashCxTrackBar'):
                prepare = 'prepare_checkbox' if components[name]['class'] == 'TFlashCheckBox' else 'prepare_slider'
                assert setup['instructions'][index + 1][1:] == ('call', hex(METHODS[prepare][1]))
                # Each call pushes nil representation, root-as-list=false,
                # then immediate=true before loading the three register arguments.
                pushes = setup['instructions'][index - 9:index - 6]
                assert [entry[1:] for entry in pushes[1:]] == [('push', '0'), ('push', '1')]
                assert pushes[0][1] == 'push'
                if prepare == 'prepare_checkbox':
                    assert pushes[0][2] == '0'
                else:
                    assert setup['literal_at'][pushes[0][0]] == '0'
                row['immediate'] = True
            row['binding_address'] = hex(setup['instructions'][index][0])
        controls[hex(offset)] = row
    selected = None
    for address, mnemonic, operands in methods['setup_events']['instructions']:
        match = re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', operands)
        if mnemonic == 'mov' and match and int(match[1], 16) in CONTROLS:
            selected = hex(int(match[1], 16))
        event = re.fullmatch(r'dword ptr \[eax \+ (0x110|0x288)\], (0x[0-9a-f]+)', operands)
        if mnemonic == 'mov' and event and selected is not None:
            controls[selected]['event'] = {'slot': event[1], 'handler': sorted(image.symbols[int(event[2], 16)])[0],
                                           'binding_address': hex(address)}
            selected = None
    assert controls['0x2e0']['event']['handler'] == METHODS['nightlight_change'][0]
    assert controls['0x2e8']['event']['handler'] == METHODS['nightlight_change'][0]
    assert 'event' not in controls['0x2e4']
    slider = controls['0x300']['dfm_properties']
    assert slider['Properties.Max'] == 15 and slider['Position'] == 15 and slider['UseRawValues'] is True
    assert slider['FlashController.UpdateMode'] == 'umExit' and 'Properties.Min' not in slider
    assert slider['Properties.OnChange'] == 'trkKeyPressBrightnessPropertiesChange'
    _has(methods['slider_constructor'], ('xor', 'edx, edx'), ('mov', 'dword ptr [eax + 0xa4], edx'))
    _has(methods['slider_set_min'], ('mov', 'dword ptr [edx + 0xa4], eax'))
    _has(methods['prepare_slider'], ('mov', 'dl, byte ptr [ebp + 8]'), ('mov', 'byte ptr [eax + 0x58], dl'))
    _calls(image, methods['slider_visual_change'], 'cxTrackBar.TcxCustomTrackBar.GetPosition',
           'CIS_CBus.KeyPressBrightnessToPercent', 'SysUtils.IntToStr', 'Controls.TControl.SetText')
    _has(methods['set_visible'], ('mov', 'byte ptr [edi + 0x59], bl'))
    _has(methods['set_enabled'], ('mov', 'byte ptr [eax + 0x5a], dl'), ('mov', 'edx, 0xb00c'))
    _has(methods['control_constructor'], ('mov', 'byte ptr [ebx + 0x59], 1'))
    assert not any(m == 'call' for _, m, _ in methods['setup_form_for_unit']['instructions'])
    for offset in ('0x2e0', '0x2e8'):
        assert 'Visible' not in controls[offset]['dfm_properties']
        assert controls[offset]['dfm_properties']['Enabled'] is False
    gate = image.slot('CIS_TCBusDynamicLabelInputUnit..TCBusDynamicLabelInputUnit', 0x1EC)
    assert gate == METHODS['nightlight_gate'][0]
    _has(methods['nightlight_gate'], ('mov', 'byte ptr [ebp - 5], 1'))
    _calls(image, methods['nightlight_change'], METHODS['update_nightlight'][0])
    _has(methods['update_nightlight'], ('call', 'dword ptr [edx + 0x1ec]'),
         ('cmp', 'byte ptr [eax + 0x59], 0'), ('mov', 'eax, dword ptr [eax + 0x2e0]'),
         ('mov', 'eax, dword ptr [eax + 0x2e8]'), ('mov', 'eax, dword ptr [eax + 0x2e4]'),
         ('mov', 'eax, dword ptr [eax + 0x30c]'), ('call', 'dword ptr [ecx + 0xf0]'))
    for slot, target in ((0xEC, 'StdCtrls.TCustomCheckBox.GetChecked'),
                         (0xF0, METHODS['set_checked'][0]), (0x74, 'Controls.TControl.SetEnabled'),
                         (0xF8, METHODS['flash_change'][0])):
        assert image.slot(CHECKBOX, slot) == target
    click_dispatch = _dynamic(image, CHECKBOX, 0xFFEC)
    changed_dispatch = _dynamic(image, CHECKBOX, 0xB037)
    assert click_dispatch['target'] == METHODS['checkbox_click'][0]
    assert changed_dispatch['target'] == METHODS['flash_changed'][0]
    _has(methods['set_state'], ('cmp', 'dl, byte ptr [ebx + 0x27a]'),
         ('mov', 'byte ptr [ebx + 0x27a], dl'), ('cmp', 'byte ptr [ebx + 0x270], 0'), ('mov', 'si, 0xffec'))
    _calls(image, methods['checkbox_click'], METHODS['changed'][0], METHODS['click'][0])
    _has(methods['changed'], ('mov', 'edx, 0xb037'))
    _has(methods['flash_changed'], ('cmp', 'byte ptr [eax + 0x285], 0'), ('call', 'dword ptr [edx + 0xf8]'))
    _calls(image, methods['flash_change'], METHODS['set_as_boolean'][0],
           'CIS_TFlashCheckBox.TFlashCheckBox.UpdateEnableState')
    _has(methods['set_as_boolean'], ('cmp', 'byte ptr [eax + 0x4c], 0'),
         ('cmp', 'byte ptr [eax + 0x58], 1'), ('call', 'dword ptr [edx + 0x10]'))
    assert image.slot('CIS_Handles..TFlashBooleanController', 0x10) == METHODS['boolean_apply'][0]
    _calls(image, methods['boolean_apply'], 'CIS_Handles.TFlashExpressionController.GetActive',
           'CIS_Handles.TFlashExpressionController.GetUpdateLocked', 'Variants.@VarFromBool')
    _has(methods['boolean_apply'], ('call', 'dword ptr [ecx + 0x7c]'))
    for key, start, stop, pp_offset, accessor in (
            ('agent_load', 0x121C01D, 0x121C03D, 0x1E0, 'SetEnableNightlightOnToggle'),
            ('agent_load', 0x121C03D, 0x121C05D, 0x1E4, 'SetEnableNightlightOnKeys'),
            ('agent_save', 0x121D242, 0x121D26A, 0x1E0, 'GetEnableNightlightOnToggle'),
            ('agent_save', 0x121D26A, 0x121D292, 0x1E4, 'GetEnableNightlightOnKeys')):
        rows = [row for row in methods[key]['instructions'] if start <= row[0] < stop]
        assert ('mov', f'eax, dword ptr [eax + {hex(pp_offset)}]') in [row[1:] for row in rows]
        target = image.by_name['CIS_TCBusDynamicLabelInputUnit.TCBusDynamicLabelInputUnit.' + accessor]
        assert ('call', hex(target)) in [row[1:] for row in rows]
        assert not any(m in ('xor', 'not') for _, m, _ in rows)
    return {
        'source_sha256': {'CBusToolkit.exe': EXE_SHA256, 'CBusToolkit.map': MAP_SHA256},
        'methods': {key: {'symbol': METHODS[key][0], 'start': hex(method['start']),
                          'stop': hex(method['end']), 'sha256': method['sha256']}
                    for key, method in methods.items()},
        'form_resource': {'name': 'TFRMDLTINPUTINDICATORS8', 'size': len(raw_dfm),
                          'sha256': hashlib.sha256(raw_dfm).hexdigest()},
        'controls': controls,
        'dispatch': {'click': click_dispatch, 'changed': changed_dispatch},
        'nightlight': {
            'unit_gate': 'TCBusDynamicLabelInputUnit VMT+0x1ec inherits NightlightPropertyEnabled=true',
            'enabled': '(nightKeys.Visible and nightKeys.Checked) or (nightToggle.Visible and nightToggle.Checked)',
            'condition_uses_visibility_not_enabled': {'visible_field': 'control+0x59', 'enabled_field': 'control+0x5a'},
            'initial_visibility': 'Both checkboxes inherit Visible=true from TControl.Create; neither DFM overrides Visible and SetupFormForUnit is empty',
            'when_disabled': 'If FirstKeyThrowaway checkbox is checked, SetChecked(false) before setting its Enabled=false',
            'final_enabled_targets': ['FirstKeyThrowaway checkbox', 'lblNightlightNote'],
            'flags_not_cleared': ['EnableNightlightOnKeys', 'EnableNightlightOnToggle'],
            'pp_mapping': {'EnableNightlightOnKeys': 'EnableNightlightOnUserKeys',
                           'EnableNightlightOnToggle': 'EnableNightlightOnToggleKey'},
            'pp_polarity': 'Both flags load and save directly without inversion',
        },
        'checkbox_contract': {
            'unchanged_state': 'No property write and no click callback',
            'changed_state_order': ['store Checked', 'update native window if allocated',
                'unless ClicksDisabled: Changed/CMChanged',
                'Flash Change writes bound Boolean before UpdateEnableState',
                'Control Click invokes assigned OnClick'],
            'admitted_controller_state': 'Initialized active immediate binding, unlocked controller, no update/reentry guard or action override',
            'write_guards': ['control ClicksDisabled=0', 'control CMChanged reentry guard=0',
                             'controller updating=false', 'controller active=true', 'controller update-locked=false'],
            'programmatic_set_ignores_enabled': True,
            'set_enabled_direct_operation': 'Store Enabled at control+0x5a and emit CM_ENABLEDCHANGED; no direct Checked/property write',
        },
        'pressed_brightness_slider': {'minimum': 0, 'maximum': 15, 'use_raw_values': True,
            'minimum_basis': 'Inherited properties constructor initializes Min field+0xa4 to zero; DFM does not override it',
            'maximum_basis': 'DFM Properties.Max=15',
            'update_mode': 'SetupFlashComponents passes immediate=1 to PrepareFlashCxTrackBar, overriding initial DFM umExit',
            'visual_change': 'Properties.OnChange displays KeyPressBrightnessToPercent(Position) plus percent sign on form+0x2d0'},
        'boundary': 'Static original-code and DFM/RTTI evidence. Normal active unlocked Flash callbacks are a caller-controlled emulation boundary; no complete Windows GUI execution, PP save or physical acceptance.',
    }
