"""Read-only source receipts for native Delphi network-language lifecycle.

The caller verifies the full pinned EXE and MAP before constructing _Toolkit.
This helper rechecks the executable hash and every consumed method address.
It does not infer a previous Toolkit process cache or installed preferences from
project XML.  It neither runs the original GUI nor writes a project/server/device.
"""
from __future__ import annotations

import hashlib

from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit


METHODS = {
    'CIS_TCommonCBus.TCBusNetwork.InternalCreate': 0xF299B0,
    'CIS_TCommonCBus.TCBusNetwork.InitialiseLanguages': 0xF2B864,
    'CIS_TCommonCBus.TCBusNetwork.FinaliseLanguages': 0xF2B9CC,
    'CIS_TCommonCBus.TCBusNetwork.GetLanguageTypeDefault': 0xF2B218,
    'CIS_TCommonCBus.TCBusNetwork.SetLanguageTypeDefault': 0xF2B23C,
    'CIS_TLanguageType.TLanguageTypeFactory.PopulateNetworkDefaults': 0x854260,
    'CIS_TLanguageType.TLanguageTypeFactory.GetDefaultLanguageType': 0x854314,
    'CIS_TLanguageType.Add': 0x8541EC,
    'CIS_DLTPreferences.CIS_DLTPreferences': 0x136AFB8,
    'CIS_DLTPreferences.RegInt': 0x852720,
    'CIS_TLanguageType.TLanguageTypeReferenceCollection.ItemByIdentifier': 0x854084,
    'CIS_TNetworkLanguageType.TNetworkLanguageTypeCollection.ItemByIdentifier': 0x8580F4,
    'CIS_TNetworkLanguageTypeCGateAgent.TNetworkLanguageTypeCGateAgent.AgentSave': 0x120FBC4,
    'CIS_TNetworkLanguageTypeCGateAgent.TNetworkLanguageTypeCGateAgent.AgentDelete': 0x120FB40,
    'CIS_TNetworkLanguageTypeCGateAgent.TNetworkLanguageTypeCGateAgent.CreateNetworkLanguageType': 0x120FD9C,
    'CIS_TCBusNetworkGUIAgent.TCBusNetworkGUIAgent.EditNetworkLanguageTypes': 0xD8CF40,
    'CIS_TCBusNetworkGUIAgent.TCBusNetworkGUIAgent.AddLanguage': 0xD8D5C4,
    'CIS_TCBusNetworkGUIAgent.TCBusNetworkGUIAgent.SetDefaultLanguage': 0xD8D76C,
    'CIS_TCBusNetworkGUIAgent.IsDefaultLanguageValid': 0xD8D560,
    'CIS_Handles.TFlashCollectionVariable.SaveToCollection': 0x8502DC,
}


def _has(method: dict, *pairs: tuple[str, str]) -> None:
    rows = [row[1:] for row in method['instructions']]
    assert all(pair in rows for pair in pairs), (hex(method['start']), pairs)


def _at(method: dict, address: int, mnemonic: str, operands: str) -> None:
    assert (address, mnemonic, operands) in method['instructions'], (hex(address), mnemonic, operands)


def _calls(image: _Toolkit, method: dict, *symbols: str) -> None:
    calls = iter(operands for _, mnemonic, operands in method['instructions'] if mnemonic == 'call')
    for symbol in symbols:
        targets = {hex(address) for address, names in image.symbols.items() if symbol in names}
        assert targets and any(operand in targets for operand in calls), (hex(method['start']), symbol)


def network_facts(image: _Toolkit) -> dict:
    """Extract native rules with explicit fresh-cache/preference prerequisites."""
    assert hashlib.sha256(image.raw).hexdigest() == EXE_SHA256, 'Unexpected Toolkit executable'
    methods = {}
    for symbol, start in METHODS.items():
        assert image.by_name.get(symbol) == start, ('Unexpected Toolkit MAP symbol', symbol)
        methods[symbol] = image.method(symbol)
    get = lambda suffix: next(method for name, method in methods.items() if name.endswith(suffix))
    init = get('TCBusNetwork.InitialiseLanguages')
    _has(get('TCBusNetwork.InternalCreate'), ('mov', 'dword ptr [edx + 0xf4], eax'),
         ('mov', 'dword ptr [edx + 0xf8], eax'), ('mov', 'dword ptr [edx + 0xfc], eax'))
    _calls(image, init, 'CIS_TLanguageType.InitialiseLanguageTypeFactory',
           'CIS_TNetworkLanguageType.TNetworkLanguageType.GetIdentifier',
           'CIS_TNetworkLanguageType.TNetworkLanguageType.GetTagValue', 'SysUtils.StrToIntDef',
           'CIS_TLanguageType.TLanguageTypeReferenceCollection.ItemByIdentifier',
           'CIS_TCommonCBus.TCBusNetwork.SetLanguageTypeDefault',
           'CIS_TLanguageType.TLanguageTypeReferenceCollection.ItemByIdentifier',
           'CIS_TLanguageType.TLanguageTypeReferenceCollection.ItemByIdentifier',
           'CIS_TLanguageType.TLanguageTypeFactory.PopulateNetworkDefaults',
           'CIS_TCommonCBus.TCBusNetwork.GetLanguageTypeDefault',
           'CIS_TLanguageType.TLanguageTypeFactory.GetDefaultLanguageType',
           'CIS_TCommonCBus.TCBusNetwork.SetLanguageTypeDefault')
    _at(init, 0xF2B8C2, 'mov', 'dword ptr [ebp - 8], 0')
    _at(init, 0xF2B8E2, 'cmp', 'dword ptr [ebp - 0xc], 0')
    _at(init, 0xF2B904, 'xor', 'edx, edx')
    _at(init, 0xF2B93D, 'jne', '0xf2b968')
    _at(init, 0xF2B955, 'je', '0xf2b968')
    _at(init, 0xF2B993, 'jne', '0xf2b9ab')
    _has(get('TLanguageTypeFactory.GetDefaultLanguageType'), ('mov', 'edx, 1'))
    # The defaults read preference objects+0x20 in slot order, not XML or locale.
    defaults = get('TLanguageTypeFactory.PopulateNetworkDefaults')
    pointer_slots = (0x13C3430, 0x13C35E0, 0x13C281C, 0x13C1D54,
                     0x13C2FB8, 0x13C2BC0, 0x13C4088, 0x13C1A10)
    actual_slots = [int(op.split('[')[1][:-1], 16) for _, mn, op in defaults['instructions']
                    if mn == 'mov' and op.startswith('eax, dword ptr [0x')]
    assert actual_slots == list(pointer_slots)
    assert [image.dword(address) for address in pointer_slots] == list(range(0x144DDE8, 0x144DE08, 4))
    assert [op for _, mn, op in defaults['instructions'] if mn in ('mov', 'or') and op.startswith('edx, ')] == ['edx, 1'] + ['edx, 0xffffffff'] * 7
    preference_init = get('CIS_DLTPreferences.CIS_DLTPreferences')
    assert [op for _, mn, op in preference_init['instructions'] if mn == 'push' and op in ('1', '-1')] == ['1'] + ['-1'] * 7
    _has(get('CIS_DLTPreferences.RegInt'), ('mov', 'dword ptr [eax + 0x20], edx'))
    add_pref = get('CIS_TLanguageType.Add')
    _has(add_pref, ('cmp', 'dword ptr [ebp - 4], 0'), ('cmp', 'dword ptr [ebp - 8], 0'),
         ('cmp', 'eax, 8'), ('jge', '0x85425b'), ('jne', '0x85425b'))
    _calls(image, add_pref, 'CIS_TLanguageType.TLanguageTypeReferenceCollection.ItemByIdentifier',
           'CIS_TLanguageType.TLanguageTypeReferenceCollection.ItemByIdentifier')
    final = get('TCBusNetwork.FinaliseLanguages')
    _at(final, 0xF2BAA8, 'dec', 'dword ptr [ebp - 8]')
    _at(final, 0xF2BAAB, 'cmp', 'dword ptr [ebp - 8], -1')
    _at(final, 0xF2BA33, 'je', '0xf2ba5b')
    _at(final, 0xF2BA5E, 'mov', 'dword ptr [ebp - 0x10], eax')
    _at(final, 0xF2BA82, 'jne', '0xf2baa8')
    _at(final, 0xF2BB0A, 'jne', '0xf2bb60')
    _at(final, 0xF2BBA0, 'je', '0xf2bbc4')
    _has(final, ('mov', 'dword ptr [ebp - 8], 0'), ('call', 'dword ptr [edx + 0x84]'),
         ('call', 'dword ptr [ebx + 0x80]'), ('call', 'dword ptr [edx + 0x7c]'))
    _calls(image, final, 'CIS_TNetworkLanguageType.TNetworkLanguageTypeCollection.Extract',
           'CIS_TLanguageType.TLanguageTypeReferenceCollection.ItemByIdentifier',
           'CIS_TNetworkLanguageType.TNetworkLanguageTypeCollection.Extract',
           'CIS_TNetworkLanguageType.TNetworkLanguageTypeCollection.ItemByIdentifier',
           'CIS_TNetworkLanguageType.TNetworkLanguageType.SetIdentifier',
           'CIS_TLanguageType.TLanguageType.GetDescription',
           'CIS_TNetworkLanguageType.TNetworkLanguageType.SetTagValue',
           'CIS_TNetworkLanguageType.TNetworkLanguageType.SetIdentifier',
           'CIS_TCommonCBus.TCBusNetwork.GetLanguageTypeDefault')
    assert 'CreateNetworkLanguageType' in final['literals']
    for offset, name in ((0x7C, 'StorageSave'), (0x80, 'StorageSave'), (0x84, 'StorageDelete')):
        assert image.slot('CIS_TNetworkLanguageType..TNetworkLanguageType', offset) == 'CIS_TIdentifiableObject.TPersistableObject.' + name
    save = get('TNetworkLanguageTypeCGateAgent.AgentSave')
    assert {'CreateNetworkLanguageType', 'ID', 'TagValue', 'ProjectSave'} <= set(save['literals'])
    _calls(image, save, 'CIS_TNetworkLanguageTypeCGateAgent.TNetworkLanguageTypeCGateAgent.CreateNetworkLanguageType',
           'CIS_TCGateAgent.TCGateAgent.UpdateCGateValue', 'CIS_TCGateAgent.TCGateAgent.UpdateCGateValue')
    assert 'ProjectSave' in get('TNetworkLanguageTypeCGateAgent.AgentDelete')['literals']
    create = get('TNetworkLanguageTypeCGateAgent.CreateNetworkLanguageType')
    assert {'Languages', '/Languages', 'Language'} <= set(create['literals'])
    _calls(image, create, 'CIS_TNetworkLanguageTypeCGateAgent.TNetworkLanguageTypeCGateAgent.SetProjectActive',
           'CIS_TCGateAgent.TCGateAgent.CommandDBGetExists', 'CIS_TCGateAgent.TCGateAgent.CommandDBAdd',
           'CIS_TCGateAgent.TCGateAgent.CGateAdd')
    dialog = get('TCBusNetworkGUIAgent.EditNetworkLanguageTypes')
    _has(dialog, ('mov', 'dword ptr [eax + 0x3e0], 8'), ('mov', 'dword ptr [eax + 0x3e4], 1'))
    _calls(image, dialog, 'CIS_TLanguageType.TLanguageTypeReferenceCollection.ItemByIdentifier',
           'CIS_Handles.TFlashCollectionVariable.Extract', 'CIS_Handles.TFlashCollectionVariable.LoadFromCollection',
           'CIS_TfrmFlashObjectListSelect.TfrmFlashObjectListSelect.Execute',
           'CIS_Handles.TFlashCollectionVariable.SaveToCollection')
    _has(get('TFlashCollectionVariable.SaveToCollection'), ('call', 'dword ptr [edx + 0x6c]'),
         ('call', 'dword ptr [ecx + 0x68]'))
    add_dialog = get('TCBusNetworkGUIAgent.AddLanguage')
    _calls(image, add_dialog, 'CIS_TCBusNetworkGUIAgent.TCBusNetworkGUIAgent.EditNetworkLanguageTypes',
           'CIS_TCommonCBus.TCBusNetwork.FinaliseLanguages',
           'CIS_TCBusNetworkGUIAgent.IsDefaultLanguageValid',
           'CIS_TLanguageType.TLanguageTypeReferenceCollection.GetItem',
           'CIS_TCommonCBus.TCBusNetwork.SetLanguageTypeDefault',
           'CIS_TCommonCBus.TCBusNetwork.FinaliseLanguages')
    assert 'SetNetworkLanguage' in add_dialog['literals']
    _has(get('CIS_TCBusNetworkGUIAgent.IsDefaultLanguageValid'), ('cmp', 'eax, dword ptr [ebp - 4]'))
    set_default = get('TCBusNetworkGUIAgent.SetDefaultLanguage')
    assert image.pe.get_data(0xD8D864 - image.base, 4).decode('utf-16le') == '0\0'
    _has(set_default, ('mov', 'edx, 1'))
    _calls(image, set_default, 'SysUtils.StrToIntDef',
           'CIS_TLanguageType.TLanguageTypeReferenceCollection.ItemByIdentifier',
           'CIS_TCommonCBus.TCBusNetwork.SetLanguageTypeDefault',
           'CIS_TCommonCBus.TCBusNetwork.FinaliseLanguages')
    assert {'1', 'SetNetworkLanguage'} <= set(set_default['literals'])
    return {
        'source_sha256': {'CBusToolkit.exe': EXE_SHA256, 'CBusToolkit.map': MAP_SHA256},
        'methods': [{'symbol': name, 'start': hex(method['start']), 'end': hex(method['end']),
                     'sha256': method['sha256']} for name, method in methods.items()],
        'findings': {
            'state': {'network_xml_collection_offset': '0xF4', 'language_reference_cache_offset': '0xF8',
                      'selected_default_reference_offset': '0xFC'},
            'prerequisites': [
                'Explicit fresh native network object, or complete ordered prior language cache and selected default reference; InitialiseLanguages clears neither.',
                'Exact eight preference values, or explicitly selected original registered-default profile [1,-1,-1,-1,-1,-1,-1,-1]; do not infer user preferences from XML or host locale.',
                'Pinned factory identifiers/descriptions from this executable, same workspace factory; positive preference IDs must resolve in that factory.',
                'Preserve ordered complete Languages/Language rows and identities; their ID0/default semantics differ from managed CBusLogicModel.dll.',
            ],
            'initialise': [
                'Ensure global language factory exists and matches network workspace.',
                'Walk existing XML rows forward. ID0: selected=factory.ItemByIdentifier(StrToIntDef(TagValue,0)); later ID0 overwrites earlier.',
                'Nonzero row: if identifier absent from existing cache, append factory object when found; ignore unknown identifier. Existing cache entries remain. No eight-language cap applies to this XML loop.',
                'Attempt PopulateNetworkDefaults in preference-slot order after XML imports.',
                'If selected reference is nil, select factory identifier1. Identifier0 resolves to <None> and is not nil, so parsed0 suppresses this fallback.',
            ],
            'preferences': {
                'registered_defaults': [1, -1, -1, -1, -1, -1, -1, -1],
                'rule': 'For each slot, choose positive preference value, else positive fallback (slot1=1;slots2..8=-1), else0. If candidate>0, cache count<8 and ID absent, append matching factory object.',
                'order': 'slot1 through slot8; additions follow already cached/imported entries in a fresh unsorted cache',
                'unknown_positive_identifier': 'Add helper does not check factory lookup for nil before Append; bounded transaction should reject unavailable preference identifiers',
            },
            'finalise': [
                'Scan XML collection backward. Retain first encountered ID0 (last in original order), delete all earlier ID0 rows through StorageDelete then Extract/Free.',
                'Delete nonzero XML rows whose identifier is absent from cache through StorageDelete then Extract/Free. Retain all matching nonzero rows, including duplicates and existing TagValue descriptions.',
                'Walk cache forward. For each identifier missing from XML, append Language row, set ID and factory Description as TagValue, StorageSave(CreateNetworkLanguageType).',
                'Append default marker if none retained; set ID0 and TagValue=decimal selected identifier, or factory default1 if selected reference nil; StorageSave marker.',
            ],
            'xml_shape': '<Languages><Language><ID>0</ID><TagValue>selected language identifier</TagValue></Language><Language><ID>language identifier</ID><TagValue>description</TagValue></Language>...</Languages>',
            'persistence': {
                'new_row': 'Set active project; create Languages if absent; add Language; update ID and TagValue; dispatch ProjectSave.',
                'existing_marker': 'Update ID and TagValue, then dispatch ProjectSave. Blank OID triggers row creation.',
                'delete': 'Inherited CGate AgentDelete followed by ProjectSave.',
                'atomic': False,
            },
            'add_language_callback': [
                'EditNetworkLanguageTypes exposes factory choices excluding identifier0 and existing choices; limits selection to1..8; canceled dialog leaves original collection unchanged.',
                'Accepted dialog replaces cache with selected collection order and returns string1; canceled returns string0.',
                'After acceptance FinaliseLanguages runs once before validating selected default membership by object identity.',
                'If selected default is absent and cache nonempty, select first cached object; dispatch SetNetworkLanguage if nonnil; FinaliseLanguages again.',
            ],
            'set_default_callback': [
                'Exact string0 becomes string1; otherwise parse with StrToIntDef(input,1); resolve factory object and replace selected reference.',
                'Dispatch SetNetworkLanguage then FinaliseLanguages; no cache-membership validation or missing real-language addition occurs in this callback.',
            ],
            'fresh_registered_default_examples': [
                {'xml': 'empty', 'cache_ids': [1], 'selected_id': 1},
                {'xml': 'ID0=2 only', 'cache_ids': [1], 'selected_id': 2},
                {'xml': 'ID2 only', 'cache_ids': [2, 1], 'selected_id': 1},
                {'xml': 'ID0=0 or unparsable; ID2', 'cache_ids': [2, 1], 'selected_id': 0},
                {'xml': 'ID0=unknown positive; ID2', 'cache_ids': [2, 1], 'selected_id': 1},
            ],
            'managed_boundary': 'These are native Delphi lifecycle rules. Managed CBusLogicModel.dll ReadXmlData/DefaultLanguage normalization and delegate invocation are separate; managed callback absence cannot establish native persistence.',
            'limit': 'Static source recovery only. No native GUI session, preferences readback, C-Gate mutation, original runtime execution or device action was performed.',
        },
    }
