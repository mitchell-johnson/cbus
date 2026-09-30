"""Source-pinned, read-only recovery of classic DLT delivery command builders.

``delivery_command_facts(image)`` consumes an already EXE/MAP-verified ``_Toolkit``
image.  It independently checks the executable hash and every consumed MAP method
address; _Toolkit does not retain the raw MAP, so the caller must verify its hash.
No server, device, file mutation, command execution or vendor byte export occurs.
This describes the original Delphi code, not physical delivery acceptance.
"""
from __future__ import annotations

import hashlib

from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit


METHODS = {
    'CIS_TGroupLanguageFlavourCGateAgent.TGroupLanguageFlavourCGateAgent.AgentSave': 0x1211A50,
    'CIS_TGroupLanguageFlavourCGateAgent.TGroupLanguageFlavourCGateAgent.CommandApplicationLabel': 0x1211BDC,
    'CIS_TGroupLanguageFlavourCGateAgent.TGroupLanguageFlavourCGateAgent.GetApplicationTypeString': 0x1211DB0,
    'CIS_TGroupLanguageFlavourCGateAgent.TGroupLanguageFlavourCGateAgent.GetLevelString': 0x1211EA8,
    'CIS_TGroupLanguageFlavourCGateAgent.TGroupLanguageFlavourCGateAgent.GetDynamicDataString': 0x1211F04,
    'CIS_TGroupLanguageFlavourCGateAgent.TGroupLanguageFlavourCGateAgent.GetFontDynamicDataString': 0x1211FE0,
    'CIS_TGroupLanguageFlavourCGateAgent.TGroupLanguageFlavourCGateAgent.GetTextDataString': 0x12120C8,
    'CIS_TGroupLanguageFlavourCGateAgent.TGroupLanguageFlavourCGateAgent.ContainUnicode': 0x12120F0,
    'CIS_TGroupLanguageFlavourCGateAgent.TGroupLanguageFlavourCGateAgent.BroadcastDLTLabel': 0x121214C,
    'CIS_TGroupLanguageFlavourCGateAgent.TGroupLanguageFlavourCGateAgent.GetProjectPrefix': 0x1212864,
    'CIS_TCGateDLTAgent.TCGateDLTAgent.CommandApplicationLabel': 0x120DFF8,
    'CIS_TcgcApplicationLabel.TcgcApplicationLabel.GenerateCommandText': 0x120D868,
    'CIS_TcgcApplicationLabel.TcgcApplicationLabel.OnProcessResults': 0x120D9E0,
    'CIS_TCBusDynamicLabelInputCGateAgent.TCBusDynamicLabelInputCGateAgent.CommandClearLabel': 0x121E274,
    'CIS_TcgcLabelClear.TcgcLabelClear.GenerateCommandText': 0x121B12C,
    'CIS_TcgcLabelClear.TcgcLabelClear.OnProcessResults': 0x121B2C4,
    'CIS_TGroupLanguage.TGroupLanguageFlavour.InternalCreate': 0xF3657C,
    'CIS_TGroupLanguage.TGroupLanguageFlavour.GetDLTDynamicData': 0xF367E8,
    'CIS_TDLTGraphic.IsDLTFontTagValue': 0x856FBC,
    'CIS_TDLTGraphic.GetImageIDFromFontTagValue': 0x856FE0,
    'CIS_TCBusObject.TCGateObject.GetOIDAsCGateID': 0xF47A58,
    'CIS_TCBusObject.TCGateObject.GetAddressAsCGateID': 0xF47BF0,
    'CIS_TCommonCBus.TCBUSUnit.GetApplicationObject': 0xF2EBC0,
}


def _has(method: dict, *pairs: tuple[str, str]) -> None:
    actual = [row[1:] for row in method['instructions']]
    assert all(pair in actual for pair in pairs), (hex(method['start']), pairs)


def _at(method: dict, address: int, mnemonic: str, operands: str) -> None:
    assert (address, mnemonic, operands) in method['instructions'], (
        hex(method['start']), hex(address), mnemonic, operands)


def _calls(image: _Toolkit, method: dict, *symbols: str) -> None:
    calls = iter(operands for _, mnemonic, operands in method['instructions'] if mnemonic == 'call')
    for symbol in symbols:
        expected = {hex(address) for address, names in image.symbols.items() if symbol in names}
        assert expected and any(operand in expected for operand in calls), (hex(method['start']), symbol)


def delivery_command_facts(image: _Toolkit) -> dict:
    """Return sanitized source facts; caller first verifies the full MAP hash."""
    assert hashlib.sha256(image.raw).hexdigest() == EXE_SHA256, 'Unexpected Toolkit executable'
    methods = {}
    for symbol, start in METHODS.items():
        assert image.by_name.get(symbol) == start, ('Unexpected Toolkit MAP symbol', symbol)
        methods[symbol.rsplit('.', 1)[-1] if symbol.startswith('CIS_TDLTGraphic.')
                else '.'.join(symbol.split('.')[-2:])] = image.method(symbol)
    get = methods.__getitem__
    prefix = 'CIS_TGroupLanguageFlavourCGateAgent.TGroupLanguageFlavourCGateAgent.'
    save = get('TGroupLanguageFlavourCGateAgent.AgentSave')
    assert 'SaveDLTLabel' in save['literals']
    _calls(image, save, 'CIS_TCustomFlashObject.TFlashAgent.IsInVerbs', prefix + 'BroadcastDLTLabel')
    broadcast = get('TGroupLanguageFlavourCGateAgent.BroadcastDLTLabel')
    _at(broadcast, 0x1212174, 'cmp', 'byte ptr [eax + 0xc4], 0')
    _at(broadcast, 0x121217B, 'jne', '0x1212689')
    _at(broadcast, 0x1212190, 'je', '0x1212689')
    assert {'00', 'ICON', 'DYNAMIC', 'F', '<Default>', '0', '10', 'Invalid Flavour value'} <= set(broadcast['literals'])
    _calls(image, broadcast, prefix + 'GetTextDataString', prefix + 'GetDynamicDataString',
           prefix + 'GetFontDynamicDataString')
    # Type switch: zero -> 00, one -> ICON, two/three -> DYNAMIC; fallback -> 00.
    for address, literal in ((0x12121BB, '00'), (0x12121CA, 'ICON'),
                             (0x12121D9, 'DYNAMIC'), (0x12121E8, 'DYNAMIC'),
                             (0x12121F7, '00')):
        assert broadcast['literal_at'][address] == literal
    _has(broadcast, ('dec', 'eax'), ('cmp', 'eax, 4'), ('jl', '0x1212298'),
         ('jle', '0x12122ac'), ('mov', 'edx, 2'))
    # Empty and exact <Default> text use type 0/data10; this branch exits after marking.
    _at(broadcast, 0x1212309, 'je', '0x1212333')
    _at(broadcast, 0x121232D, 'jne', '0x12123c1')
    assert broadcast['literal_at'][0x1212378] == '0'
    assert broadcast['literal_at'][0x121237D] == '10'
    _at(broadcast, 0x12123B5, 'mov', 'byte ptr [eax + 0xc4], 1')
    _at(broadcast, 0x12123BC, 'jmp', '0x1212689')
    # The first14 UTF-16 code units are converted, but the Unicode check uses
    # the original untruncated string and skips to the broadcast mark on true.
    _at(broadcast, 0x12123F1, 'cmp', 'dword ptr [ebp - 0x2c], 0xe')
    _at(broadcast, 0x12123F7, 'mov', 'dword ptr [ebp - 0x30], 0xe')
    _at(broadcast, 0x121241D, 'movzx', 'eax, word ptr [eax + edx*2 - 2]')
    _at(broadcast, 0x1212425, 'mov', 'edx, 2')
    _at(broadcast, 0x1212460, 'mov', 'edx, dword ptr [ebp - 0x1c]')
    _at(broadcast, 0x121246D, 'jne', '0x1212565')
    _at(broadcast, 0x121256D, 'mov', 'byte ptr [eax + 0xc4], 1')
    _calls(image, broadcast, 'SysUtils.IntToHex', prefix + 'ContainUnicode',
           prefix + 'CommandApplicationLabel', prefix + 'CommandApplicationLabel',
           'CIS_TDLTGraphic.IsDLTFontTagValue', 'CIS_TDLTGraphic.GetImageIDFromFontTagValue',
           prefix + 'CommandApplicationLabel')
    assert broadcast['literal_at'][0x121263C] == 'ICON'
    unicode = get('TGroupLanguageFlavourCGateAgent.ContainUnicode')
    _at(unicode, 0x121212E, 'cmp', 'word ptr [eax + edx*2 - 2], 0xff')
    _at(unicode, 0x1212135, 'jbe', '0x121213d')
    _at(unicode, 0x1212137, 'mov', 'byte ptr [ebp - 9], 1')
    _calls(image, get('TGroupLanguageFlavourCGateAgent.GetTextDataString'),
           'CIS_TGroupLanguage.TGroupLanguageFlavour.GetDLTTag',
           'CIS_TLanguageTag.TLanguageTag.GetTagValue')
    for method_name in ('GetDynamicDataString', 'GetFontDynamicDataString'):
        dynamic = get('TGroupLanguageFlavourCGateAgent.' + method_name)
        _has(dynamic, ('mov', 'eax, dword ptr [eax + 0xc0]'), ('mov', 'eax, 0x10'),
             ('mov', 'eax, 0xa'), ('mov', 'edx, 9'))
        assert [dynamic['literal_at'][va] for va, mn, _ in dynamic['instructions']
                if mn == 'push' and va in dynamic['literal_at']] == [' '] * 4
        _calls(image, dynamic, 'CIS_TLanguageTag.TLanguageTag.GetTagValue',
               'CIS_TGroupLanguage.TGroupLanguageFlavour.GetDLTDynamicData', 'System.@UStrCatN')
    _calls(image, get('TGroupLanguageFlavourCGateAgent.GetFontDynamicDataString'),
           'CIS_TDLTGraphic.GetImageIDFromFontTagValue')
    _has(get('TGroupLanguageFlavour.InternalCreate'), ('mov', 'dword ptr [eax + 0xc0], 0x40'))
    _has(get('TGroupLanguageFlavour.GetDLTDynamicData'), ('mov', 'eax, dword ptr [eax + 0xbc]'))
    _has(get('IsDLTFontTagValue'), ('mov', 'ax, 0x2c'), ('cmp', 'eax, 9'))
    _calls(image, get('GetImageIDFromFontTagValue'), 'System.Pos', 'System.@UStrCopy')
    assert ',' in get('GetImageIDFromFontTagValue')['literals']
    level = get('TGroupLanguageFlavourCGateAgent.GetLevelString')
    assert '-' in level['literals']
    _calls(image, level, prefix + 'ParentIsLevel', prefix + 'GetLevel',
           'CIS_TCBusObject.TCGateObject.GetAddressAsInteger', 'SysUtils.IntToStr')
    app_type = get('TGroupLanguageFlavourCGateAgent.GetApplicationTypeString')
    assert {'ENABLE', 'TRIGGER', 'LIGHTING'} <= set(app_type['literals'])
    _calls(image, app_type, 'CIS_TCommonCBus.TCBusNetwork.GetEnableControlApplication',
           'CIS_TCommonCBus.TCBusNetwork.GetTriggerControlApplication')
    assert {'//', '/'} <= set(get('TGroupLanguageFlavourCGateAgent.GetProjectPrefix')['literals'])
    _calls(image, get('TCGateObject.GetOIDAsCGateID'), 'CIS_TCBusObject.TCGateObject.GetAddressAsCGateID')
    assert '!' in get('TCGateObject.GetAddressAsCGateID')['literals']
    assert image.slot('CIS_TGroupLanguageFlavourCGateAgent..TGroupLanguageFlavourCGateAgent', 0xAC) == prefix + 'GetProjectPrefix'
    flavour_command = get('TGroupLanguageFlavourCGateAgent.CommandApplicationLabel')
    _has(flavour_command, ('mov', 'dword ptr [ebp - 0x14], 1'),
         ('mov', 'dword ptr [ebp - 0x14], eax'), ('call', 'dword ptr [ecx + 0xac]'),
         ('add', 'eax, 0xa8'))
    generic_command = get('TCGateDLTAgent.CommandApplicationLabel')
    assert ('add', 'eax, 0xa8') not in [row[1:] for row in generic_command['instructions']]
    generator = get('TcgcApplicationLabel.GenerateCommandText')
    assert {' LABEL ', ' ', 'TEXT'} <= set(generator['literals'])
    _calls(image, generator, 'CIS_Strings.TagStringToCgateString', 'System.@UStrCatN',
           'CIS_TCGateCommand.TCGateCommand.SetTimeOut')
    _has(generator, ('mov', 'edx, 0xe'), ('mov', 'edx, 0x7530'))
    assert {'200 OK', '400', 'Syntax Error', '408', 'Operation failed',
            'System Exception', 'Send failed', '402', 'Operation not supported',
            'bad object'} <= set(get('TcgcApplicationLabel.OnProcessResults')['literals'])
    clear = get('TCBusDynamicLabelInputCGateAgent.CommandClearLabel')
    _at(clear, 0x121E280, 'cmp', 'dword ptr [ebp - 8], 0')
    _at(clear, 0x121E284, 'je', '0x121e331')
    _has(clear, ('mov', 'dword ptr [edx + 0x98], eax'),
         ('mov', 'dword ptr [edx + 0x94], eax'), ('mov', 'dword ptr [edx + 0x90], eax'),
         ('mov', 'dword ptr [eax + 0x9c], edx'))
    assert image.slot('CIS_TCBusDynamicLabelInputUnit..TCBusDynamicLabelInputUnit', 0xB0) == 'CIS_TCommonCBus.TCBUSUnit.GetApplicationObject'
    clear_generator = get('TcgcLabelClear.GenerateCommandText')
    assert {'label clear %d/%d %d %d', 'label clear %d/%d %d'} <= set(clear_generator['literals'])
    _has(clear_generator, ('cmp', 'dword ptr [eax + 0x9c], 1'),
         ('cmp', 'dword ptr [eax + 0x9c], 8'), ('jl', '0x121b1d1'), ('jg', '0x121b1d1'))
    assert {'400', 'Syntax Error', '402', 'Operation not supported', '200 OK'} <= set(get('TcgcLabelClear.OnProcessResults')['literals'])
    return {
        'source_sha256': {'CBusToolkit.exe': EXE_SHA256, 'CBusToolkit.map': MAP_SHA256},
        'methods': [{'symbol': symbol, 'start': hex(image.method(symbol)['start']),
                     'end': hex(image.method(symbol)['end']), 'sha256': image.method(symbol)['sha256']}
                    for symbol in METHODS],
        'findings': {
            'call_chain': ['AgentSave(SaveDLTLabel)', 'BroadcastDLTLabel',
                           'TGroupLanguageFlavourCGateAgent.CommandApplicationLabel',
                           'TcgcApplicationLabel.GenerateCommandText', 'CommandExecute'],
            'early_return': ['GroupLanguageFlavour+0xC4 already true', 'group absent'],
            'flavour': {'asserted_range': [1, 4], 'command_token': 'F' + '<flavour minus 1>'},
            'application_type': 'ENABLE for network enable-control application; TRIGGER for trigger-control application; LIGHTING otherwise',
            'level': 'decimal level address when parent is a level and level exists; otherwise -',
            'target': 'optional //project/ prefix plus application.GetOIDAsCGateID(): !OID when nonblank; otherwise virtual address',
            'command': '<application-type> LABEL <target> <language-id> <group-address> <level-or--> F<flavour-1> <type> <data>',
            'generic_dlt_agent': 'same command object but no flavour token and no extra project-prefix concatenation in that method',
            'tag_type_dispatch': {'0': '00/text', '1': 'ICON/TagValue',
                                  '2': 'DYNAMIC/GetDynamicDataString', '3': 'DYNAMIC/GetFontDynamicDataString',
                                  'other': '00/TagValue'},
            'text': {
                'source': 'DLTTag.TagValue, no text transformation in GetTextDataString',
                'empty_or_exact_default': {'matches': ['', '<Default>'], 'type': '0', 'data': '10'},
                'maximum_code_units': 14, 'encoding': 'uppercase IntToHex(UTF16 code unit, minimum digits=2), concatenated',
                'unicode_guard': 'if any code unit in original untruncated value exceeds255, suppress LABEL command',
                'suppressed_still_marked_broadcast': True,
                'literal_text_mode': 'TcgcApplicationLabel also supports TEXT through TagStringToCgateString; BroadcastDLTLabel uses 00 instead',
            },
            'dynamic': {
                'payload': '<image-id> <GroupLanguageFlavour+0xC0 decimal> 16 10 <DLTDynamicData>',
                'field_c0_constructor_default': 64,
                'image_id': 'TagValue for dynamic type2; substring before first comma for font type3',
                'data_dependency': 'existing DLTDynamicData string attribute at object+0xBC; this builder does not render graphics',
                'followup': 'after DYNAMIC succeeds, mark broadcast then send same address/flavour with ICON and image-id',
                'followup_image_id': 'substring before first comma when TagValue contains exactly9 commas, otherwise complete TagValue',
                'command_timeout_ms': 30000,
            },
            'completion': 'mark+0xC4 after initial command, or after suppressing Unicode text; dynamic ICON follows the mark; one command attempt, no effective retry loop',
            'clear': {
                'call_chain': ['TCBusDynamicLabelInputCGateAgent.CommandClearLabel', 'TcgcLabelClear.GenerateCommandText', 'CommandExecute'],
                'line_zero': 'skip command', 'line_1_to_8': 'label clear <network-address>/<unit-application-address> <unit-address> <line>',
                'other_nonzero_line': 'label clear <network-address>/<unit-application-address> <unit-address>',
                'addresses': 'network from unit.GetNetwork; application from unit.GetApplicationObject; unit.GetAddressAsInteger; decimal integers',
            },
            'responses': {
                'application_label': '200 OK completes; bad object (case insensitive substring) also marks complete;400 Syntax Error,408 Operation failed with System Exception or Send failed,402 Operation not supported raise mapped exceptions',
                'label_clear': '200 OK completes;400 Syntax Error and402 Operation not supported raise mapped exceptions',
            },
            'limit': 'Static original-code evidence only; no actual C-Gate command delivery, no hardware action, no device readback, no graphic generation and no full original GUI execution.',
        },
    }
