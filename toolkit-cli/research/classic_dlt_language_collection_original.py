"""Source receipts for the original classic DLT language model lifecycle.

Read-only: pass an EXE/MAP-hash-verified ``_Toolkit`` image.  This helper checks
the executable hash, source symbols, branches, call ordering and VMT ownership.
It never executes vendor code, opens projects or calls C-Gate.  Results contain
derived rules and hashes only; the actual vendor input paths are caller-owned.
"""
from __future__ import annotations

import hashlib

from classic_dlt_language_original import _calls, _has
from project_documentor_static import EXE_SHA256, MAP_SHA256, _Toolkit


METHODS = {
    'CIS_TGroupLanguage.TGroupLanguageCollection.InitialiseLanguages': 0xF37154,
    'CIS_TGroupLanguage.TGroupLanguageCollection.FinaliseLanguage': 0xF37474,
    'CIS_TGroupLanguage.TGroupLanguageCollection.AddLanguageTypes': 0xF3707C,
    'CIS_TGroupLanguage.TGroupLanguageCollection.ItemByLanguageType': 0xF3701C,
    'CIS_TGroupLanguage.TGroupLanguageFlavourCollection.ItemByFlavour': 0xF36ABC,
    'CIS_TGroupTagDLT.TGroupTagDLTCollection.ItemByLanguageAndFlavourID': 0x85A208,
    'CIS_TGroupLanguage.TGroupLanguage.GetHasTagTypeText': 0xF36DB0,
    'CIS_TGroupLanguage.TGroupLanguage.GetHasTagTypePredefined': 0xF36D74,
    'CIS_TGroupLanguage.TGroupLanguage.InternalCreate': 0xF36B1C,
    'CIS_TGroupLanguage.TGroupLanguageFlavour.InternalCreate': 0xF3657C,
    'CIS_TLanguageTag.TLanguageTag.InternalCreate': 0x8583A4,
    'CIS_TLanguageTag.TLanguageTag.SetTagTypeAsCode': 0x858658,
    'CIS_TLanguageTag.TLanguageTag.GetTagTypeAsCode': 0x858584,
    'CIS_TLanguageTag.TLanguageTag.SetTagValue': 0x858528,
    'CIS_TDLTGraphic.IsDLTFontTagValue': 0x856FBC,
    'CIS_jcl.StrLeft': 0x7B6C10,
    'CIS_TCommonCBus.TCBusGroup.InitialiseLanguages': 0xF2879C,
    'CIS_TCommonCBus.TLevel.InitialiseLanguages': 0xF27058,
    'CIS_TCustomFlashObject.TCustomFlashObject.GetAsString': 0x7EA47C,
    'CIS_TCustomFlashObject.TCustomFlashObject.InternalGetDefaultRepresentation': 0x7EA5F8,
    'CIS_TCommonCBus.TCBusGroup.GetDefaultRepresentation': 0xF280F4,
    'CIS_TCommonCBus.TLevel.GetDefaultRepresentation': 0xF26D88,
    'CIS_TCBusObject.TCGateObject.GetExtendedTagName': 0xF47DC4,
    'CIS_TCBusObject.TCGateObject.InternalCreate': 0xF47718,
    'CIS_TCommonCBus.TLevel.GetExtendedTagName': 0xF270CC,
    'CIS_TCommonCBus.TLevel.InternalCreate': 0xF26A48,
    'CIS_GlobalSoftwareParameters.UseAddressValueFormat': 0x85B3D8,
    'CIS_TLanguageType.Add': 0x8541EC,
    'CIS_TGroupTagDLTCGateAgent.TGroupTagDLTCGateAgent.AgentSave': 0x1213388,
    'CIS_TGroupTagDLTCGateAgent.TGroupTagDLTCGateAgent.AgentDelete': 0x1213318,
}


def collection_facts(image: _Toolkit) -> dict:
    """Recover bounded model-lifecycle facts; caller validates the raw MAP hash."""
    assert hashlib.sha256(image.raw).hexdigest() == EXE_SHA256
    methods = {}
    for name, start in METHODS.items():
        assert image.by_name.get(name) == start, name
        methods['.'.join(name.split('.')[-2:])] = image.method(name)
    get = methods.__getitem__
    initial = get('TGroupLanguageCollection.InitialiseLanguages')
    final = get('TGroupLanguageCollection.FinaliseLanguage')
    add = get('TGroupLanguageCollection.AddLanguageTypes')
    _has(initial, ('mov', 'dword ptr [ebp - 0xc], ecx'), ('mov', 'dword ptr [ebp - 8], edx'),
         ('mov', 'cl, 1'), ('cmp', 'byte ptr [ebp + 8], 0'), ('jne', '0xf37431'),
         ('cmp', 'dword ptr [ebp - 0x14], 5'), ('ret', '4'))
    _calls(image, initial, 'CIS_TGroupLanguage.TGroupLanguageCollection.AddLanguageTypes',
           'CIS_TGroupTagDLT.TGroupTagDLTCollection.ItemByLanguageAndFlavourID',
           'CIS_TGroupTagDLT.TGroupTagDLTCollection.ItemByLanguageAndFlavourID',
           'CIS_TLanguageTag.TLanguageTag.SetTagTypeAsCode',
           'CIS_TLanguageTag.TLanguageTag.GetTagType', 'CIS_TLanguageTag.TLanguageTag.SetTagValue',
           'CIS_jcl.StrLeft')
    _has(initial, ('xor', 'ecx, ecx'), ('cmp', 'al, 3'), ('mov', 'edx, 0x14'))
    _calls(image, add, 'CIS_TLanguageType.TLanguageTypeReferenceCollection.IndexOf',
           'CIS_TGroupLanguage.TGroupLanguageCollection.ItemByLanguageType',
           'CIS_TGroupLanguage.TGroupLanguage.SetLanguageType',
           'CIS_TGroupLanguage.TGroupLanguageFlavour.SetFlavour')
    _has(add, ('dec', 'dword ptr [ebp - 0x10]'), ('mov', 'edx, 1'))
    _has(final, ('mov', 'dword ptr [ebp - 0xc], ecx'), ('mov', 'dword ptr [ebp - 8], edx'),
         ('cmp', 'dword ptr [ebp - 0xc], 0'), ('mov', 'eax, dword ptr [ebp + 8]'),
         ('mov', 'dword ptr [ebp - 0x10], 1'), ('cmp', 'dword ptr [ebp - 0x10], 5'),
         ('cmp', 'dword ptr [ebp - 0x20], 0'), ('cmp', 'dword ptr [ebp - 0x24], 0'),
         ('cmp', 'al, 3'), ('mov', 'edx, 0x14'), ('ret', '4'))
    _calls(image, final, 'CIS_TGroupTagDLT.TGroupTagDLTCollection.ItemByLanguageAndFlavourID',
           'CIS_TGroupTagDLT.TGroupTagDLTCollection.ItemByLanguageAndFlavourID',
           'CIS_TGroupTagDLT.TGroupTagDLT.SetLanguageID', 'CIS_TGroupTagDLT.TGroupTagDLT.SetFlavourID',
           'CIS_TGroupTagDLT.TGroupTagDLTCollection.Extract', 'System.TObject.Free',
           'CIS_TGroupTagDLT.TGroupTagDLT.SetTagType', 'CIS_TGroupTagDLT.TGroupTagDLT.SetTagValue',
           'CIS_jcl.StrLeft')
    _has(final, ('call', 'dword ptr [edx + 0x84]'), ('call', 'dword ptr [edx + 0x7c]'))
    for slot, target in ((0x84, 'CIS_TIdentifiableObject.TPersistableObject.StorageDelete'),
                         (0x7C, 'CIS_TIdentifiableObject.TPersistableObject.StorageSave')):
        assert image.slot('CIS_TGroupTagDLT..TGroupTagDLT', slot) == target
    # Set IDs only in the newly-added-tag block; a fallback legacy tag keeps ID0.
    for function in ('SetLanguageID', 'SetFlavourID'):
        target = hex(image.by_name['CIS_TGroupTagDLT.TGroupTagDLT.' + function])
        addresses = [va for va, mn, op in final['instructions'] if (mn, op) == ('call', target)]
        assert len(addresses) == 1 and 0xF37542 <= addresses[0] < 0xF3756D
    _has(get('CIS_jcl.StrLeft'), ('mov', 'edx, 1'), ('mov', 'ecx, dword ptr [ebp - 8]'))
    _calls(image, get('CIS_jcl.StrLeft'), 'System.@UStrCopy')
    _calls(image, get('TLanguageTag.InternalCreate'), 'CIS_TLanguageTag.TLanguageTag.SetTagType',
           'CIS_TLanguageTag.TLanguageTag.SetTagValue')
    _has(get('TLanguageTag.InternalCreate'), ('xor', 'edx, edx'))
    _calls(image, get('TLanguageTag.SetTagTypeAsCode'), 'CIS_TLanguageTag.TLanguageTag.GetTagValue',
           'CIS_TDLTGraphic.IsDLTFontTagValue')
    _has(get('CIS_TDLTGraphic.IsDLTFontTagValue'), ('mov', 'ax, 0x2c'), ('cmp', 'eax, 9'))
    assert {'TEXT', 'ICON', 'DYNAMIC', 'FONT'} <= set(get('TLanguageTag.GetTagTypeAsCode')['literals'])
    _has(get('TGroupLanguage.GetHasTagTypeText'), ('cmp', 'eax, 0xca'), ('test', 'eax, eax'))
    _has(get('TGroupLanguage.GetHasTagTypePredefined'), ('cmp', 'eax, 0xca'))
    for owner in ('TCBusGroup', 'TLevel'):
        symbol = 'CIS_TCommonCBus..' + owner
        assert image.slot(symbol, 0x2C) == 'CIS_TCustomFlashObject.TCustomFlashObject.GetAsString'
        assert image.slot(symbol, 0x58) == 'CIS_TCommonCBus.' + owner + '.GetDefaultRepresentation'
        _has(get(owner + '.InitialiseLanguages'), ('mov', 'byte ptr [ebp - 5], dl'),
             ('mov', 'al, byte ptr [ebp - 5]'), ('push', 'eax'))
    assert image.slot('CIS_TCommonCBus..TCBusGroup', 0x94) == 'CIS_TCBusObject.TCGateObject.GetExtendedTagName'
    assert image.slot('CIS_TCommonCBus..TLevel', 0x94) == 'CIS_TCommonCBus.TLevel.GetExtendedTagName'
    for owner in ('TCGateObject', 'TLevel'):
        method = get(owner + '.GetExtendedTagName')
        _calls(image, method, 'CIS_GlobalSoftwareParameters.UseAddressValueFormat',
               'CIS_GlobalSoftwareParameters.FormattedAddress')
        assert ' - ' in method['literals']
    _has(get('TCBusGroup.GetDefaultRepresentation'), ('cmp', 'eax, 0xff'))
    _has(get('TLevel.GetExtendedTagName'), ('cmp', 'byte ptr [eax + 0xbc], 0'))
    _has(get('TLevel.InternalCreate'), ('mov', 'byte ptr [eax + 0xbc], 1'))
    _has(get('TCGateObject.InternalCreate'), ('mov', 'dword ptr [edx + 0x9c], eax'))
    assert 'TagName' in get('TCGateObject.InternalCreate')['literals']
    _has(get('CIS_TLanguageType.Add'), ('cmp', 'dword ptr [ebp - 0xc], 0'), ('jle', '0x85425b'))
    return {
        'format': 'cbus-classic-dlt-language-dialog-source-v1',
        'source_sha256': {'CBusToolkit.exe': EXE_SHA256, 'CBusToolkit.map': MAP_SHA256},
        'methods': [{ 'symbol': name, 'start': hex(methods['.'.join(name.split('.')[-2:])]['start']),
                     'end': hex(methods['.'.join(name.split('.')[-2:])]['end']),
                     'sha256': methods['.'.join(name.split('.')[-2:])]['sha256']} for name in METHODS],
        'arguments': {
            'InitialiseLanguages': {'eax': 'model GroupLanguageCollection', 'edx': 'LanguageTypeReferenceCollection',
                'ecx': 'saved GroupTagDLTCollection', 'stack_ebp_plus_8': 'preserve missing alternate model flavours'},
            'FinaliseLanguage': {'eax': 'model GroupLanguageCollection', 'edx': 'requested LanguageType object',
                'ecx': 'optional supplied GroupLanguage object; nil resolves requested object identity',
                'stack_ebp_plus_8': 'saved GroupTagDLTCollection'},
        },
        'rules': {
            'graph': 'Group/Level owns saved TagsDLT and separate model GroupLanguages. Each model language references a LanguageType object and owns Flavours; each flavour owns DLTTag(type,value). New DLTTag is TEXT with empty value. New language gets flavour1 only.',
            'language_reconciliation': 'Initialise always calls AddLanguageTypes(types,true): remove missing language object references backward, preserve surviving order, append missing requested languages in supplied order. Numeric saved-tag lookup and object-identity model-language lookup are distinct.',
            'iteration': 'Initialise iterates model languages in current collection order and flavours1..4. Finalise operates one requested language and flavours1..4, with each mutation completed before the next flavour.',
            'saved_lookup': 'First exact requested languageID/flavour row wins. Only flavour1 falls back to legacy flavour0 when exact1 is absent. Finalise fallback uses selected model language ID; exact lookup/new row uses requested language ID.',
            'legacy_identity': 'Existing fallback flavour0 remains flavour0 on update. If both0 and1 exist, only1 is selected and0 survives. New nonempty rows always get requested languageID and flavour1..4.',
            'existing_saved_initialisation': 'Ensure matching model flavour. SetTagTypeAsCode first, then assign complete saved value for resulting type3/FONT or first20 UTF16 code units otherwise.',
            'dynamic_type_order': 'Case-insensitive TEXT=0,ICON=1,FONT=3; DYNAMIC becomesFONT iff current pre-assignment model value contains exactly9 commas, otherwise2; unknown code becomesTEXT. SetTagValue does not reclassify.',
            'missing_first_flavour': 'Ensure flavour1. Language ID not0/202 resets tag toTEXT and empty, then Group/Level owner.GetAsString left20 if present. ID202 setsICON without clearing existing value. ID0 leaves existing type/value unchanged.',
            'missing_alternate_flavour': 'Absent saved flavour2..4 removes existing model flavour iff stack Boolean isfalse; true preserves it. Neither path creates an absent alternate flavour.',
            'finalise_create': 'If selected saved row absent and model flavour exists with value !=empty, append saved object then set requested languageID and current flavourID. StorageSave later creates persistence.',
            'finalise_delete': 'If selected saved row exists and model flavour absent or its value exactlyempty, call StorageDelete, then Extract from saved collection, then Free. Whitespace is nonempty.',
            'finalise_update': 'For nonempty model flavour, compare saved type code and saved value against full model code/value BEFORE truncation. Only if different: set type code; set full FONT value or first20 UTF16 units; call StorageSave.',
            'unknown_saved_rows': 'Rows of other languageIDs, flavours outside0..4, and shadowed duplicates are not swept by Finalise. Init changes only model cache. A selected unknown type is interpreted asTEXT; it cannot be promised preserved by a TEXT-only API.',
            'utf16': 'StrLeft(value,20) calls Delphi System.@UStrCopy(value,start1,count20): count is UTF16 code units, not Unicode code points; a surrogate pair may be split.',
            'owner_display': 'Group non255 uses GetExtendedTagName: optional FormattedAddress(address,false)+space-hyphen-space prefix under UseAddressValueFormat. Group255 uses TagName directly. Level prefix additionally needs model byte+0xbc, whose constructor default istrue. TagName is object attribute+0x9c. Missing-flavour1 fallback requires exact owner display metadata, not an assumed XML TagName.',
            'scope_admission': 'TEXT-only fresh-model transactions avoid retained DYNAMIC classification state. Reject nonTEXT rows in normalized scope unless complete cache/image/type semantics are supplied; require owner display metadata if fallback flavour1 is absent.',
        },
        'boundary': 'Static source evidence only. No original model/GUI execution, storage transaction, language-object cache reconstruction, or hardware acceptance is implied.',
    }
