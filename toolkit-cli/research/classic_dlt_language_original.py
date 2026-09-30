"""Read-only classic DLT language and Global-control source extraction.

``language_facts(image)`` accepts the caller's ``_Toolkit`` image after the caller
has verified both EXE_SHA256 and MAP_SHA256.  _Toolkit does not retain the raw MAP;
this helper checks the executable itself and the exact addresses of every symbol
it consumes.  No source path, vendor bytes, instructions, project data or network
operation is included in the result.  The returned descriptions are guarded by
instruction/literal/call-shape assertions, not loaded from a recorded fixture.
"""
from __future__ import annotations

import hashlib
import re

from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit


METHODS = {
    'CIS_TddKEYL5.TddKEYL5.HandleLanguageChange': 0x10018C8,
    'CIS_TddKEYL5.TddKEYL5.UpdateDLTLabelCombo': 0x10000E8,
    'CIS_TddKEYL5.TddKEYL5.InitialiseDLTLabelCombo': 0xFFFF90,
    'CIS_TcdUnitGlobal.TcdUnitGlobal.Initialise': 0xF5E580,
    'CIS_TcdUnitGlobal.TcdUnitGlobal.SetupFlashComponents': 0xF5E74C,
    'CIS_TcdUnitGlobal.TcdUnitGlobal.InitialiseLanguageCombo': 0xF5E708,
    'CIS_TcdUnitGlobal.TcdUnitGlobal.InitLanguageCombo': 0xF5F39C,
    'CIS_TcdUnitGlobal.TcdUnitGlobal.HandleLanguageComboEnter': 0xF602D0,
    'CIS_TcdUnitGlobal.TcdUnitGlobal.HandleLanguageComboChange': 0xF60190,
    'CIS_TcdUnitGlobal.TcdUnitGlobal.HandleLanguageChange': 0xF60078,
    'CIS_TcdUnitGlobal.TcdUnitGlobal.HandleAfterButtonLanguageEditClick': 0xF5FE1C,
    'CIS_TCommonCBus.TCBusNetwork.InitialiseLanguages': 0xF2B864,
    'CIS_TCommonCBus.TCBusNetwork.FinaliseLanguages': 0xF2B9CC,
    'CIS_TLanguageType.TLanguageTypeFactory.GetDefaultLanguageType': 0x854314,
    'CIS_TCBusNetworkCGateAgent.TCBusNetworkCGateAgent.AgentSave': 0xD83068,
    'CIS_TCBusNetworkCGateAgent.TCBusNetworkCGateAgent.SetNetworkWideLanguageLibremente': 0xD86E50,
    'CIS_TCBusApplicationCGateAgent.TCBusApplicationCGateAgent.AgentSave': 0x120E3A4,
    'CIS_TCBusApplicationCGateAgent.TCBusApplicationCGateAgent.BroadcastDLTLanguageForApplication': 0x120E63C,
    'CIS_TNetworkLanguageTypeCGateAgent.TNetworkLanguageTypeCGateAgent.AgentSave': 0x120FBC4,
    'CIS_TCGateDLTAgent.TCGateDLTAgent.CommandApplicationLabel': 0x120DFF8,
    'CIS_TcgcApplicationLabel.TcgcApplicationLabel.GenerateCommandText': 0x120D868,
    'CIS_TLanguageType.InitialiseLanguageTypeFactory': 0x852BA0,
}


def _has(method: dict, *pairs: tuple[str, str]) -> None:
    actual = [(mnemonic, operands) for _, mnemonic, operands in method['instructions']]
    assert all(pair in actual for pair in pairs), (hex(method['start']), pairs)


def _calls(image: _Toolkit, method: dict, *names: str) -> None:
    """Require the named calls in order; unrelated calls may intervene."""
    calls = iter(operands for _, mnemonic, operands in method['instructions'] if mnemonic == 'call')
    for name in names:
        addresses = {hex(address) for address, symbols in image.symbols.items() if name in symbols}
        assert addresses and any(operand in addresses for operand in calls), (hex(method['start']), name)


def _literal_row(method: dict, literal: str) -> tuple[int, int]:
    matches = [(index, row[0]) for index, row in enumerate(method['instructions'])
               if method['literal_at'].get(row[0]) == literal]
    assert len(matches) == 1, (hex(method['start']), literal, matches)
    return matches[0]


def _language_table(image: _Toolkit, method: dict) -> list[dict]:
    register = hex(image.by_name['CIS_TLanguageType.TLanguageTypeFactory.RegisterLanguageType'])
    identifier, description, rows = None, None, []
    for address, mnemonic, operands in method['instructions']:
        if mnemonic == 'mov' and operands.startswith('ecx, '):
            description = method['literal_at'].get(address)
        if mnemonic == 'mov' and operands.startswith('edx, '):
            assert re.fullmatch(r'edx, (?:0x[0-9a-f]+|[0-9]+)', operands)
            identifier = int(operands[5:], 0)
        if (mnemonic, operands) == ('xor', 'edx, edx'):
            identifier = 0
        if (mnemonic, operands) == ('call', register):
            assert isinstance(identifier, int) and isinstance(description, str)
            rows.append({'identifier': identifier, 'description': description})
            identifier, description = None, None
    assert [row['identifier'] for row in rows] == [*range(15), *range(64, 117), 202]
    assert rows[:2] == [{'identifier': 0, 'description': '<None>'},
                        {'identifier': 1, 'description': 'English'}]
    assert rows[-1] == {'identifier': 202, 'description': 'Chinese'}
    return rows


def language_facts(image: _Toolkit) -> dict:
    """Extract sanitized language facts from an already MAP-hash-verified image."""
    assert hashlib.sha256(image.raw).hexdigest() == EXE_SHA256, 'Unexpected Toolkit executable'
    methods = {}
    for name, start in METHODS.items():
        assert image.by_name.get(name) == start, ('Unexpected Toolkit MAP symbol', name)
        methods['.'.join(name.split('.')[-2:])] = image.method(name)
    get = methods.__getitem__
    setup = get('TcdUnitGlobal.SetupFlashComponents')
    index, binding_va = _literal_row(setup, 'BlockDynamicUpdates')
    control_match = re.fullmatch(r'eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]', setup['instructions'][index - 1][2])
    assert control_match and control_match[1] == '0x2e8'
    binding_call = setup['instructions'][index + 1]
    assert binding_call[1:] == ('call', hex(image.by_name['CIS_FlashGUI.PrepareFlashCheckbox']))
    class_symbol = 'CIS_TCBusDynamicLabelInputUnit..TCBusDynamicLabelInputUnit'
    class_pointer = image.by_name[class_symbol]
    assert ('mov', f'edx, dword ptr [{hex(class_pointer)}]') in [row[1:] for row in setup['instructions'][index - 20:index]]
    vmt = image.dword(class_pointer)
    assert image.class_name(vmt) == 'TCBusDynamicLabelInputUnit'
    for offset, handler in ((0x570, 'HandleAfterButtonLanguageEditClick'),
                            (0x4E8, 'HandleLanguageComboChange'), (0x200, 'HandleLanguageComboEnter')):
        _has(setup, ('mov', f'dword ptr [eax + {hex(offset)}], {hex(get("TcdUnitGlobal." + handler)["start"])}'))
    _has(setup, ('mov', 'eax, dword ptr [eax + 0x328]'))
    combo = get('TcdUnitGlobal.InitLanguageCombo')
    assert 'LanguageTypes' in combo['literals'] and 'LanguageTypeDefault' in combo['literals']
    _calls(image, combo, 'CIS_FlashGUI.PrepareFlashCxActionComboBox')
    _calls(image, get('TcdUnitGlobal.Initialise'), 'CIS_TCommonCBus.TCBUSUnit.GetNetwork',
           'CIS_Handles.TFlashObjectLink.SetFlashObject')
    _has(get('TcdUnitGlobal.HandleLanguageComboEnter'), ('cmp', 'dword ptr [eax + 0x38], 0'),
         ('mov', 'dword ptr [edx + 0x38], eax'))
    change = get('TcdUnitGlobal.HandleLanguageComboChange')
    assert 'SetNetworkLanguage' in change['literals']
    _has(change, ('mov', 'dword ptr [edx + 0x164], eax'), ('mov', 'dword ptr [edx + 0x38], eax'))
    _calls(image, change, 'CIS_TCommonCBus.TCBusNetwork.GetLanguageTypeDefault',
           'CIS_TCommonCBus.TCBusNetwork.FinaliseLanguages')
    key_update = get('TddKEYL5.UpdateDLTLabelCombo')
    _calls(image, key_update, 'CIS_TInputKey.TInputKey.GetIsSceneModifyKey',
           'CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.GetControlAppGroup',
           'CIS_TInputKey.TInputKey.GetIsSceneKey',
           'CIS_TInputKeyExtensionNeo.TInputKeyExtensionNeo.GetSceneTriggerLevel',
           'CIS_TInputKey.TInputKey.GetPrimaryDLTGroup')
    assert 'GroupLanguageFlavours' in key_update['literals']
    assert 'ExtensionNeo.LabelFlavour' in get('TddKEYL5.InitialiseDLTLabelCombo')['literals']
    _calls(image, get('TddKEYL5.HandleLanguageChange'), 'CIS_TddKEYL5.TddKEYL5.InitialiseDLTLabelCombo')
    _has(get('TddKEYL5.HandleLanguageChange'), ('mov', 'dword ptr [ebp - 0xc], 1'))
    initial = get('TCBusNetwork.InitialiseLanguages')
    _calls(image, initial, 'CIS_TNetworkLanguageType.TNetworkLanguageType.GetIdentifier',
           'CIS_TNetworkLanguageType.TNetworkLanguageType.GetTagValue', 'SysUtils.StrToIntDef',
           'CIS_TLanguageType.TLanguageTypeReferenceCollection.ItemByIdentifier',
           'CIS_TCommonCBus.TCBusNetwork.SetLanguageTypeDefault',
           'CIS_TLanguageType.TLanguageTypeFactory.GetDefaultLanguageType')
    _has(initial, ('cmp', 'dword ptr [ebp - 0xc], 0'))
    default = get('TLanguageTypeFactory.GetDefaultLanguageType')
    _has(default, ('mov', 'edx, 1'))
    _calls(image, default, 'CIS_TLanguageType.TLanguageTypeReferenceCollection.ItemByIdentifier')
    finalise = get('TCBusNetwork.FinaliseLanguages')
    _calls(image, finalise, 'CIS_TCommonCBus.TCBusNetwork.GetLanguageTypeDefault',
           'CIS_TLanguageType.TLanguageType.GetIdentifier', 'SysUtils.IntToStr',
           'CIS_TNetworkLanguageType.TNetworkLanguageType.SetTagValue')
    assert {'ID', 'TagValue', 'ProjectSave'} <= set(get('TNetworkLanguageTypeCGateAgent.AgentSave')['literals'])
    assert 'SetNetworkLanguage' in get('TCBusNetworkCGateAgent.AgentSave')['literals']
    broadcast = get('TCBusNetworkCGateAgent.SetNetworkWideLanguageLibremente')
    _has(broadcast, ('cmp', 'eax, 0xff'), ('mov', 'edx, 0xcb'), ('mov', 'edx, 0xca'))
    _calls(image, broadcast, 'CIS_TCommonCBus.TCBUSApplication.GetIsStandardLightingLike')
    assert 'SaveDLTLanguageToApplication' in broadcast['literals']
    assert 'SaveDLTLanguageToApplication' in get('TCBusApplicationCGateAgent.AgentSave')['literals']
    application = get('TCBusApplicationCGateAgent.BroadcastDLTLanguageForApplication')
    _calls(image, application, 'CIS_TCommonCBus.TCBusNetwork.GetLanguageTypeDefault',
           'CIS_TLanguageType.TLanguageType.GetIdentifier', 'SysUtils.IntToStr',
           'CIS_TCGateDLTAgent.TCGateDLTAgent.CommandApplicationLabel')
    assert [application['literal_at'].get(address) for address, mnemonic, _ in application['instructions']
            if mnemonic == 'push' and address in application['literal_at']] == ['0', '-', 'SET_LANGUAGE']
    assert ' LABEL ' in get('TcgcApplicationLabel.GenerateCommandText')['literals']
    return {
        'source_sha256': {'CBusToolkit.exe': EXE_SHA256, 'CBusToolkit.map': MAP_SHA256},
        'methods': [{'symbol': name, 'start': hex(image.method(name)['start']),
                     'end': hex(image.method(name)['end']), 'sha256': image.method(name)['sha256']}
                    for name in METHODS],
        'language_factory': _language_table(image, get('CIS_TLanguageType.InitialiseLanguageTypeFactory')),
        'findings': {
            'block_dynamic_updates_binding': {
                'class': image.class_name(vmt), 'class_pointer_va': hex(class_pointer), 'vmt': hex(vmt),
                'method': 'CIS_TcdUnitGlobal.TcdUnitGlobal.SetupFlashComponents',
                'binding_va': hex(binding_va), 'form_control_offset': control_match[1],
                'expression': setup['literal_at'][binding_va], 'binding_call_va': hex(binding_call[0]),
                'binding_call': 'CIS_FlashGUI.PrepareFlashCheckbox'},
            'global_language_combo': {
                'form_control_offset': '0x328', 'owner': 'unit.GetNetwork()', 'choices': 'LanguageTypes',
                'selection': 'LanguageTypeDefault',
                **{key: 'CIS_TcdUnitGlobal.TcdUnitGlobal.' + suffix for key, suffix in (
                    ('event_enter', 'HandleLanguageComboEnter'), ('event_change', 'HandleLanguageComboChange'),
                    ('event_edit', 'HandleAfterButtonLanguageEditClick'))}},
            'network_language_storage': {
                'default_marker_id': 0, 'default_marker_tagvalue': 'decimal language identifier, not collection index',
                'regular_marker_id': 'language identifier', 'regular_marker_tagvalue': 'language description',
                'fallback_identifier': 1, 'fallback_description': 'English',
                'save': 'TNetworkLanguageTypeCGateAgent.AgentSave updates ID and TagValue then ProjectSave'},
            'language_change_actions': ['remember old language object on unit+0x164',
                'update controller saved language pointer to network default', 'dispatch SetNetworkLanguage',
                'call FinaliseLanguages', 'invoke language changed callback'],
            'network_broadcast_selection': ['every non255 standard-lighting-like application in manager order',
                                            'application203', 'application202'],
            'network_broadcast_command': '<application type> LABEL <application OID> <language identifier> 0 - SET_LANGUAGE ',
            'keyl5_language_callback': 'Loop key numbers1..count; InitialiseDLTLabelCombo updates selection source from network default language; scene-modify uses control application group, scene uses SceneTriggerLevel, other uses PrimaryDLTGroup; GroupLanguageFlavours becomes available list; ExtensionNeo.LabelFlavour remains key selection.',
            'limit': 'Static original-code evidence only. No original GUI execution, native server mutation or physical bus actions. No classic DLT PP language byte mapping established.',
        },
    }
