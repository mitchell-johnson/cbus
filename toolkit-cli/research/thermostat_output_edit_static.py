"""Pin thermostat output Edit outcomes statically, without original execution.

Extends the retained Add/name/transport contract with selected-object Edit,
programmatic name loading, exact overloaded storage dispatch and Edit hooks.
Emits hashes and bounded checkpoints only; no vendor bytes or private paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402
from thermostat_post_load_static import _Walker  # noqa: E402
from thermostat_quick_zone_initialization_static import dfm_properties  # noqa: E402
import thermostat_output_add_static as add_source  # noqa: E402

METHODS = ('CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick',
 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
 'CIS_TfrmGroupAssign.TfrmGroupAssign.SetValues',
 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
 'CIS_TIdentifiableObject.TPersistableObject.StorageSave@0x7f409c',
 'CIS_TCBusGroupCGateAgent.TCBusGroupCGateAgent.AgentSave',
 'CIS_TCGateAgent.TCGateAgent.AgentSave',
 'Controls.TControl.SetText',
 'Controls.TControl.SetTextBuf',
 'Controls.TControl.GetText',
 'Controls.TControl.GetTextLen',
 'Controls.TControl.GetTextBuf',
 'Controls.TControl.DefaultHandler',
 'Controls.TWinControl.DefaultHandler',
 'StdCtrls.TCustomEdit.DoSetMaxLength',
 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.HandleButtonEditClick',
 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.DoButtonEditClick',
 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.ComboGetGroup',
 'CIS_TCBusObject.TCGateObject.HandleTagNameAfterChange',
 'CIS_TCBusObject.TCGateObject.TagNameBeforeChange',
 'CIS_TCBusObject.TCGateObjectManager.HandleAfterChangeTimerTrigger',
 'CIS_TCBusObject.TCGateObjectManager.SetAfterChangeTimerEnabled',
 'CIS_TCustomFlashObject.TFlashAgent.IsInVerbs',
 'CIS_TCommonCBus.TCBusGroup.IsUnused')

CHECKPOINTS = {'0xbc5dbd': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick',
              'mnemonic': 'call',
              'operand': '0xbc5f50'},
 '0xbc5e16': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick',
              'mnemonic': 'mov',
              'operand': 'byte ptr [eax + 0x404], 0'},
 '0xbc5e6f': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick',
              'mnemonic': 'call',
              'operand': '0xbc612c'},
 '0xbc5e7d': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick',
              'mnemonic': 'mov',
              'operand': 'dword ptr [edx + 0x3f8], eax'},
 '0xbc5e8c': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick',
              'mnemonic': 'call',
              'operand': '0xbc356c'},
 '0xbc5ebe': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick',
              'mnemonic': 'call',
              'operand': 'dword ptr [edx + 0x110]'},
 '0xbc5ec7': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick',
              'mnemonic': 'call',
              'operand': '0xbbc2f8'},
 '0xbc5ecf': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick',
              'mnemonic': 'call',
              'operand': '0xbbbee8'},
 '0xbc561a': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
              'mnemonic': 'call',
              'operand': '0xbc5f50'},
 '0xbc5638': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
              'mnemonic': 'call',
              'operand': '0x84dcac'},
 '0xbc5654': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
              'mnemonic': 'je',
              'operand': '0xbc569b'},
 '0xbc5667': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
              'mnemonic': 'mov',
              'operand': 'edx, dword ptr [0xf23cd4]'},
 '0xbc566d': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
              'mnemonic': 'call',
              'operand': '0x606414'},
 '0xbc5692': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
              'mnemonic': 'call',
              'operand': '0xf27e14'},
 '0xbc5699': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
              'mnemonic': 'je',
              'operand': '0xbc569f'},
 '0xbc56ca': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
              'mnemonic': 'mov',
              'operand': 'ecx, 2'},
 '0xbc56d8': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
              'mnemonic': 'call',
              'operand': 'dword ptr [ebx + 0x530]'},
 '0xbc56e1': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
              'mnemonic': 'and',
              'operand': 'dl, byte ptr [ebp - 5]'},
 '0xbc56e7': {'method': 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.UpdateEnableState',
              'mnemonic': 'call',
              'operand': '0xbbdf5c'},
 '0xbc35ee': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.SetValues',
              'mnemonic': 'mov',
              'operand': 'eax, dword ptr [eax + 0x9c]'},
 '0xbc35f6': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.SetValues',
              'mnemonic': 'call',
              'operand': 'dword ptr [ecx + 0x2c]'},
 '0xbc3605': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.SetValues',
              'mnemonic': 'call',
              'operand': '0x6f62d8'},
 '0xbc38ad': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.SetValues',
              'mnemonic': 'xor',
              'operand': 'edx, edx'},
 '0xbc38b8': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.SetValues',
              'mnemonic': 'call',
              'operand': '0x6f61c0'},
 '0xbc38e0': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.SetValues',
              'mnemonic': 'call',
              'operand': '0xf47a10'},
 '0xbc38fb': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.SetValues',
              'mnemonic': 'call',
              'operand': '0x6f62d8'},
 '0xbc2ded': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'cmp',
              'operand': 'byte ptr [eax + 0x404], 0'},
 '0xbc2dff': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0xf47a10'},
 '0xbc2e07': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'jmp',
              'operand': '0xbc2e14'},
 '0xbc2f04': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'cmp',
              'operand': 'byte ptr [eax + 0x404], 0'},
 '0xbc2f0b': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'je',
              'operand': '0xbc2f35'},
 '0xbc2f41': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0x6f62a0'},
 '0xbc2f4c': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0x618f9c'},
 '0xbc2f57': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'mov',
              'operand': 'ecx, dword ptr [eax + 0x3f8]'},
 '0xbc2f6c': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0xf28e28'},
 '0xbc2f85': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0xf47d64'},
 '0xbc2f96': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0x6f62a0'},
 '0xbc2fa1': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0x618f9c'},
 '0xbc2fc5': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': 'dword ptr [ecx + 0x7c]'},
 '0xbc2fcb': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'cmp',
              'operand': 'byte ptr [eax + 0x404], 0'},
 '0xbc2fd2': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'jne',
              'operand': '0xbc3020'},
 '0xbc2fe4': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'mov',
              'operand': 'dword ptr [ebp - 0x1c], eax'},
 '0xbc2ff3': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'xor',
              'operand': 'ecx, ecx'},
 '0xbc2ff7': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': 'dword ptr [ebx + 0x80]'},
 '0xbc3007': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'jmp',
              'operand': '0x606a9c'},
 '0xbc301b': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'call',
              'operand': '0x606e8c'},
 '0xbc3023': {'method': 'CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute',
              'mnemonic': 'mov',
              'operand': 'dword ptr [eax + 0x2b8], 1'},
 '0x7f40f8': {'method': 'CIS_TIdentifiableObject.TPersistableObject.StorageSave@0x7f409c',
              'mnemonic': 'call',
              'operand': '0x7f3df8'},
 '0x7f4119': {'method': 'CIS_TIdentifiableObject.TPersistableObject.StorageSave@0x7f409c',
              'mnemonic': 'call',
              'operand': 'dword ptr [ebx + 0x88]'},
 '0x1210d62': {'method': 'CIS_TCBusGroupCGateAgent.TCBusGroupCGateAgent.AgentSave',
               'mnemonic': 'call',
               'operand': '0xf47c7c'},
 '0x1210d69': {'method': 'CIS_TCBusGroupCGateAgent.TCBusGroupCGateAgent.AgentSave',
               'mnemonic': 'je',
               'operand': '0x1210d8c'},
 '0x1210d87': {'method': 'CIS_TCBusGroupCGateAgent.TCBusGroupCGateAgent.AgentSave',
               'mnemonic': 'call',
               'operand': '0x1210f3c'},
 '0x1210db7': {'method': 'CIS_TCBusGroupCGateAgent.TCBusGroupCGateAgent.AgentSave',
               'mnemonic': 'call',
               'operand': '0xcac354'},
 '0x1210ded': {'method': 'CIS_TCBusGroupCGateAgent.TCBusGroupCGateAgent.AgentSave',
               'mnemonic': 'call',
               'operand': 'dword ptr [ebx + 0x80]'},
 '0xcac372': {'method': 'CIS_TCGateAgent.TCGateAgent.AgentSave', 'mnemonic': 'call', 'operand': '0x7ef46c'},
 '0xcac379': {'method': 'CIS_TCGateAgent.TCGateAgent.AgentSave', 'mnemonic': 'jne', 'operand': '0xcac383'},
 '0xcac37e': {'method': 'CIS_TCGateAgent.TCGateAgent.AgentSave', 'mnemonic': 'call', 'operand': '0xcac614'},
 '0x6f6309': {'method': 'Controls.TControl.SetText', 'mnemonic': 'call', 'operand': '0x6089b0'},
 '0x6f6312': {'method': 'Controls.TControl.SetText', 'mnemonic': 'call', 'operand': '0x6f56d0'},
 '0x6f56d8': {'method': 'Controls.TControl.SetTextBuf', 'mnemonic': 'mov', 'operand': 'edx, 0xc'},
 '0x6f56dd': {'method': 'Controls.TControl.SetTextBuf', 'mnemonic': 'call', 'operand': '0x6f76d0'},
 '0x6f62a9': {'method': 'Controls.TControl.GetText', 'mnemonic': 'call', 'operand': '0x6f6210'},
 '0x6f62b6': {'method': 'Controls.TControl.GetText', 'mnemonic': 'call', 'operand': '0x608a60'},
 '0x6f62c8': {'method': 'Controls.TControl.GetText', 'mnemonic': 'lea', 'operand': 'ecx, [ebx + 1]'},
 '0x6f62cd': {'method': 'Controls.TControl.GetText', 'mnemonic': 'call', 'operand': '0x6f6220'},
 '0x6f6214': {'method': 'Controls.TControl.GetTextLen', 'mnemonic': 'mov', 'operand': 'edx, 0xe'},
 '0x6f6221': {'method': 'Controls.TControl.GetTextBuf', 'mnemonic': 'mov', 'operand': 'edx, 0xd'},
 '0x6f7ab9': {'method': 'Controls.TControl.DefaultHandler', 'mnemonic': 'sub', 'operand': 'eax, 0xc'},
 '0x6f7b11': {'method': 'Controls.TControl.DefaultHandler', 'mnemonic': 'call', 'operand': '0x61b570'},
 '0x6fc330': {'method': 'Controls.TWinControl.DefaultHandler', 'mnemonic': 'call', 'operand': '0x60ee30'},
 '0x6fc355': {'method': 'Controls.TWinControl.DefaultHandler', 'mnemonic': 'call', 'operand': '0x6f7ab0'},
 '0x6852f9': {'method': 'StdCtrls.TCustomEdit.DoSetMaxLength', 'mnemonic': 'push', 'operand': '0xc5'},
 '0x685306': {'method': 'StdCtrls.TCustomEdit.DoSetMaxLength', 'mnemonic': 'call', 'operand': '0x60f4c4'}}

CHECKPOINTS.update({
    '0xbbe41d': {'method': 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.HandleButtonEditClick',
                 'mnemonic': 'call', 'operand': 'dword ptr [ebx + 0x550]'},
    '0xbbe431': {'method': 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.HandleButtonEditClick',
                 'mnemonic': 'call', 'operand': 'dword ptr [ecx + 0x518]'},
    '0xbbe450': {'method': 'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.HandleButtonEditClick',
                 'mnemonic': 'call', 'operand': 'dword ptr [ebx + 0x570]'},
    '0xf27e25': {'method': 'CIS_TCommonCBus.TCBusGroup.IsUnused',
                 'mnemonic': 'cmp', 'operand': 'eax, 0xff'},
    '0xf47b48': {'method': 'CIS_TCBusObject.TCGateObject.HandleTagNameAfterChange',
                 'mnemonic': 'call', 'operand': 'dword ptr [ebx + 0xa8]'},
    '0xf47b63': {'method': 'CIS_TCBusObject.TCGateObject.HandleTagNameAfterChange',
                 'mnemonic': 'cmp', 'operand': 'byte ptr [eax + 0x59], 3'},
    '0xf47b8a': {'method': 'CIS_TCBusObject.TCGateObject.HandleTagNameAfterChange',
                 'mnemonic': 'cmp', 'operand': 'byte ptr [eax + 0x84], 0'},
    '0xf47b9e': {'method': 'CIS_TCBusObject.TCGateObject.HandleTagNameAfterChange',
                 'mnemonic': 'call', 'operand': '0xf487e0'},
    '0xf4880f': {'method': 'CIS_TCBusObject.TCGateObjectManager.SetAfterChangeTimerEnabled',
                 'mnemonic': 'mov', 'operand': 'edx, 1'},
    '0xf4881d': {'method': 'CIS_TCBusObject.TCGateObjectManager.SetAfterChangeTimerEnabled',
                 'mnemonic': 'call', 'operand': '0x697290'},
    '0xf48753': {'method': 'CIS_TCBusObject.TCGateObjectManager.HandleAfterChangeTimerTrigger',
                 'mnemonic': 'call', 'operand': '0x606200'},
    '0xf4875b': {'method': 'CIS_TCBusObject.TCGateObjectManager.HandleAfterChangeTimerTrigger',
                 'mnemonic': 'call', 'operand': '0x7e99b0'},
})
STORAGE_OVERLOAD = 'CIS_TIdentifiableObject.TPersistableObject.StorageSave@0x7f409c'
CONSTRUCTORS = (
    'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.Create',
    'CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.Create',
    'CIS_TFlashCxComboBox.TFlashCxComboBox.Create',
)
EDIT_FIELDS = (0x550, 0x554, 0x570, 0x574)
EDIT_EVENTS = ('OnBeforeButtonEditClick', 'OnAfterButtonEditClick')
PLATFORM = {
    'authority': 'Microsoft Win32 edit-control contract',
    'url': 'https://learn.microsoft.com/en-us/windows/win32/controls/em-limittext',
    'source_message': 'EM_LIMITTEXT (0xc5)',
    'preload_message': 'WM_SETTEXT (0xc)',
    'rule': 'The user-entry limit does not truncate existing text or text loaded using WM_SETTEXT.',
    'verification': 'Official documentation, composed with pinned Delphi calls; no Windows execution.',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inspect(exe: Path, map_path: Path) -> dict:
    inherited = add_source.inspect(exe, map_path)
    raw, mapping = exe.read_bytes(), map_path.read_bytes()
    if (sha(raw), sha(mapping)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Pinned original EXE/MAP hashes differ')
    image, checks = _Image(raw, mapping), {}
    # The MAP repeats StorageSave. Bind the exact VMT overload, not by_name's
    # first spelling, and prove that its original symbol is at this address.
    storage_name = STORAGE_OVERLOAD.split('@')[0]
    checks['exact_storage_overload_symbol'] = storage_name in image.symbols[0x7f409c]
    image.by_name[STORAGE_OVERLOAD] = 0x7f409c
    walker = _Walker(image)
    methods = dict(inherited['method_spans'])
    listings = {}
    scan_names = sorted(set(inherited['handler_scan']['method_names']) | set(CONSTRUCTORS))
    for name in dict.fromkeys((*METHODS, *scan_names)):
        rows, _tables, digest = walker.listing(name)
        start = image.by_name[name]
        methods[name] = {'address': hex(start), 'end': hex(next(a for a in image.starts if a > start)),
                         'sha256': digest}
        listings[name] = rows
    for address, expected in CHECKPOINTS.items():
        rows = {hex(a): (m, op) for a, m, op, _note in listings[expected['method']]}
        checks[address] = rows.get(address) == (expected['mnemonic'], expected['operand'])
    def calls(name):
        return [note for _a, m, _op, note in listings[name] if m == 'call' and note]
    def has(name, mnemonic, operand):
        return any((m, op) == (mnemonic, operand) for _a, m, op, _n in listings[name])

    group_vmt = walker.dword(image.by_name['CIS_TCommonCBus..TCBusGroup'])
    agent_vmt = walker.dword(image.by_name['CIS_TCBusGroupCGateAgent..TCBusGroupCGateAgent'])
    checks['group_storage_vmt_exact_slot80'] = group_vmt == 0xf23d2c and walker.dword(group_vmt + 0x80) == 0x7f409c
    checks['group_agent_save_vmt_exact_slot88'] = agent_vmt == 0x1210b40 and walker.dword(agent_vmt + 0x88) == 0x1210d28
    edit = 'CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.DoButtonEditClick'
    checks['edit_uses_existing_combo_identity'] = calls(edit).count('CIS_TFlashCxGroupComboBox.TFlashCxGroupComboBox.ComboGetGroup') == 1
    # SetValues is dialog initialization, not a reference setter.
    checks['edit_has_no_reference_assignment_or_creation_callback'] = not any(
        part in note for note in calls(edit) for part in ('DoOnCanChangeElement',
        'DoOnBeforeChange', 'NewGroup', 'GetNextAvailableAddress', 'SetAsElement'))
    modal_slice = [(m, op) for a, m, op, _n in listings[edit] if 0xbc5ebe < a < 0xbc5ecf]
    checks['both_modal_outcomes_refresh_without_result_test'] = not any(m.startswith('j') or m in ('cmp', 'test') for m, _op in modal_slice)
    checks['base_edit_virtual_empty'] = not calls('CIS_TFlashCxActionComboBox.TCustomFlashCxActionComboBox.DoButtonEditClick')
    checks['loaded_name_whole_unicode_string'] = calls('Controls.TControl.SetText').count('System.@UStrToPWChar') == 1
    checks['loaded_name_getter_uses_actual_length'] = (
        calls('Controls.TControl.GetText')[0] == 'Controls.TControl.GetTextLen'
        and 'Controls.TControl.GetTextBuf' in calls('Controls.TControl.GetText'))
    checks['no_handle_preload_copies_whole_string'] = 'SysUtils.StrNew' in calls('Controls.TControl.DefaultHandler')
    checks['handle_preload_uses_window_proc'] = 'Windows.CallWindowProc' in calls('Controls.TWinControl.DefaultHandler')
    checks['edit_ok_has_no_maxlength_field_read'] = not any('0x274' in op for _a, _m, op, _n in listings['CIS_TfrmGroupAssign.TfrmGroupAssign.actOKExecute'])
    checks['inherited_tag_before_change_has_no_validation'] = not calls('CIS_TCBusObject.TCGateObject.TagNameBeforeChange')

    properties = {}
    for name, at, field in (('OnBeforeButtonEditClick', 0xbc47f2, 0x550),
                            ('OnAfterButtonEditClick', 0xbc48bb, 0x570)):
        header = image.pe.get_data(at - image.base, 27)
        record = image.pe.get_data(at - image.base, 27 + header[26])
        get, set_ = struct.unpack_from('<II', record, 4)
        checks['published.' + name] = record[27:].decode('ascii') == name and get == set_ == 0xff000000 + field
        properties[name] = {'address': hex(at), 'get': hex(get), 'set': hex(set_),
                            'bytes': len(record), 'sha256': sha(record)}
    writes = []
    for name in scan_names:
        for address, mnemonic, operands, _note in listings[name]:
            if mnemonic in ('mov', 'xor', 'and', 'or', 'add', 'sub', 'inc', 'dec'):
                destination = operands.split(', ', 1)[0]
                if any(re.search(r'\+ ' + hex(field) + r'\]', destination) for field in EDIT_FIELDS):
                    writes.append({'method': name, 'address': hex(address), 'destination': destination})
    checks['all70_panel_methods_and_constructors_scanned'] = len(scan_names) == 70
    checks['no_direct_edit_hook_writes'] = not writes
    controls = {}
    for resource in ('TFRMCOOLINGGROUPS', 'TFRMHEATINGGROUPS', 'TFRMDAMPERGROUPS', 'TFRMTHERMOSTATPLANT'):
        _data, found = dfm_properties(image, resource)
        combos = {name: item for name, item in found.items() if item['class'] == 'TFlashCxGroupComboBox'}
        controls[resource] = {name: {key: value for key, value in item['properties'].items() if key in EDIT_EVENTS}
                              for name, item in combos.items()}
        for name, item in combos.items():
            checks[resource + '.' + name + '.no_edit_hooks'] = not any(key in item['properties'] for key in EDIT_EVENTS)
    checks['all23_controls_checked_for_edit_hooks'] = sum(map(len, controls.values())) == 23
    # Existing Add fixture pins name Trim/UpperCase, active controls, Save
    # serializer and address255 unused semantics; preserve that proof separately.
    if not all(checks.values()):
        raise ValueError('Output Edit source checkpoints differ: ' + ', '.join(k for k, value in checks.items() if not value))
    if (sha(exe.read_bytes()), sha(map_path.read_bytes())) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original inputs changed during static inspection')
    return {
        'format': 'cbus-thermostat-output-edit-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False, 'native_vendor_executed': False, 'physical_io': False,
        'checks': {**{'inherited_add.' + key: value for key, value in inherited['checks'].items()},
                   **{key: True for key in sorted(checks)}},
        'inherited_add_contract': {'receipt': 'thermostat-output-add-source-review.json',
            'sha256': sha((json.dumps(inherited, indent=2, sort_keys=True) + '\n').encode()),
            'checks': len(inherited['checks'])},
        'edit_checks': len(checks), 'method_spans': dict(sorted(methods.items())),
        'resources': inherited['resources'], 'published_edit_properties': properties,
        'handler_scan': {'method_names': scan_names, 'field_offsets': [hex(v) for v in EDIT_FIELDS],
            'direct_writes': writes, 'scope': '70-method direct-store scan plus fresh zero-fill and all23 DFM controls'},
        'output_edit_controls': controls, 'platform_contract': PLATFORM,
        'name_rules': {'explicit_maximum_utf16_code_units_before_trim': 32,
            'omitted_name': 'Full current TagName programmatically loaded; no32-unit clipping or acceptance length check.',
            'omitted_maximum_utf16_code_units': None, 'trim_code_units_inclusive': [0, 32],
            'project_tag_comparison': 'Exact UTF-16 equality after Trim, only on acceptance.',
            'duplicate_name_comparison': 'ASCII-only UpperCase, excluding the current object identity only.',
            'direct_cancel': 'No edited name, no OK validation and no Project.TagName dependency.'},
        'storage_dispatch': {'dialog_call': '0xbc2ff7', 'group_vmt': hex(group_vmt),
            'storage_slot': hex(group_vmt + 0x80), 'storage_target': '0x7f409c',
            'agent_call': '0x7f4119', 'agent_vmt': hex(agent_vmt),
            'agent_slot': hex(agent_vmt + 0x88), 'agent_target': '0x1210d28',
            'existing_oid_skips_create_branch': ['0x1210d69', '0x1210d8c'],
            'generic_tag_save': ['0x1210db7', '0xcac354', '0xcac614'],
            'native_commands': ['dbset !existing-group-OID/TagName encoded-name', 'ProjectSave'],
            'same_name_accept_still_calls_original_storage': True},
        'projection_boundary': {'same_identity_and_address': True, 'reference_assignment': False,
            'edit_capacity_gate': False, 'group255_editable': False,
            'full_preflight_and_one_owning_save': 'Owned transaction policy; original per-dialog storage exceptions and partial prefixes are not replayed.',
            'omitted_name_win32_rule': 'Pinned WM_SETTEXT/EM_LIMITTEXT calls composed with cited Microsoft semantics.',
            'explicit_name_scope': 'Up to32 UTF-16 units; does not reproduce editing a preloaded over-limit string through arbitrary keystrokes.',
            'manager_notifications': 'TagName after-change may schedule a1ms full sort; native list ordering/timers/messages are not emulated.',
            'same_name_noop': 'Owned projection can omit redundant writes/saves after successful validation.',
            'unimplemented': ['application migration', 'whole initialized GUI/message loop', 'physical acceptance']},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
