#!/usr/bin/env python3
"""Read-only static proof of the three original SceneManager Add buttons.

PE/ECMA metadata and pinned decompiled declarations are read as data. No CLR,
original instruction, Framework callback, vendor process or device executes.
The public annex contains hashes and API/order facts, never instruction bytes,
source text, original literal heaps or private local coordinates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from research.edlt_scene_name_static import ManagedImage, require_order, source_span


PARSER_PIN = '7bb4f3137bf6da42524cc512d94fe6c711f28b5a80532d018411777f9f573223'
PINS = {
    'toolkit/app/eDLT.dll': '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3',
    'toolkit/app/CBusLogicModel.dll': '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823',
    'edlt-decompiled/eDLT/eDLT.Controls.SceneManagerControls/SceneManager.cs': 'c2aa9a75cf7e128eba6cab952ddbdd45cb7e363b4128dc96ff15bd90adf9d72c',
    'edlt-decompiled/CBusLogicModel/CBusLogicModel/CBusNetwork.cs': 'ddd65e5d34d94f3b0468f0db5a8468c0b6b5cdc50b8a49ca27b9f7331000d39c',
}
UI = 'eDLT.Controls.SceneManagerControls.SceneManager::'
NETWORK = 'CBusLogicModel.CBusNetwork::'
METHODS = {
    'toolkit/app/eDLT.dll': tuple(UI + name for name in (
        'BtnAddTriggerGroupClick', 'BtnAddActionSelectorClick', 'btnNewGroup_Click')),
    'toolkit/app/CBusLogicModel.dll': tuple(NETWORK + name for name in ('AddGroupRequest', 'AddLevelRequest')),
}
SOURCE_UI = 'edlt-decompiled/eDLT/eDLT.Controls.SceneManagerControls/SceneManager.cs'
SOURCE_NETWORK = 'edlt-decompiled/CBusLogicModel/CBusLogicModel/CBusNetwork.cs'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def recover(vendor_root):
    parser = Path(__file__).with_name('edlt_scene_name_static.py')
    if digest(parser.read_bytes()) != PARSER_PIN:
        raise ValueError('Static PE/source parser pin differs')
    inputs = [{'logical_name': 'static-managed-parser', 'sha256': PARSER_PIN,
               'bytes': len(parser.read_bytes()), 'role': 'repository-static-parser'}]
    originals = {}
    for name, expected in PINS.items():
        raw = (vendor_root / name).read_bytes()
        if digest(raw) != expected:
            raise ValueError('Pinned original static input differs: ' + Path(name).name)
        originals[name] = raw
        inputs.append({'logical_name': Path(name).name, 'sha256': expected,
                       'bytes': len(raw), 'role': 'original-static-input'})
    methods, decoded = [], {}
    for assembly, symbols in METHODS.items():
        image = ManagedImage(originals[assembly])
        if image.runtime != 'v4.0.30319':
            raise ValueError('Original managed runtime metadata differs')
        for symbol in symbols:
            detail = image.instructions(symbol)
            for call in detail['calls']:
                token = int(call['token'], 16)
                if token >> 24 == 43:  # ECMA MethodSpec -> MethodDefOrRef.
                    coded = image.row(43, token & 0xffffff)[0]
                    call['symbol'] = image.member(((10 if coded & 1 else 6) << 24) | (coded >> 1))
            methods.append(dict(image.method(symbol), assembly=Path(assembly).name,
                                metadata_runtime=image.runtime, **detail))
            decoded[symbol] = detail
    checks = []

    def calls(symbol, requested, label):
        require_order([row['symbol'] for row in decoded[symbol]['calls']], requested, label)
        checks.append({'id': label, 'symbol': symbol,
                       'ordered_call_suffixes': requested, 'passed': True})

    def absent(symbol, parts, label):
        observed = [row['symbol'] for row in decoded[symbol]['calls']]
        if any(any(call.endswith(part) for call in observed) for part in parts):
            raise ValueError('Unexpected source callback: ' + label)
        checks.append({'id': label, 'symbol': symbol,
                       'absent_call_suffixes': parts, 'passed': True})

    def declaration(path, name, anchor, required=(), forbidden=()):
        row = source_span(originals[path], name, anchor)
        lines = originals[path].decode('utf-8-sig').splitlines(keepends=True)
        text = ''.join(lines[row['start_line'] - 1:row['end_line']])
        if any(value not in text for value in required) or any(value in text for value in forbidden):
            raise ValueError('Pinned decompiled source contract differs: ' + name)
        checks.append({'id': 'declaration-' + name, 'symbol': name,
                       'required_anchors': len(required), 'forbidden_anchors': len(forbidden), 'passed': True})
        return {'logical_name': Path(path).name, **row}, text

    resets = ['ResetCurrentItem', 'ResetBindings', 'ResetBindings']
    calls(UI+'BtnAddTriggerGroupClick', ['get_ParentForm', 'get_FormBaseUnit',
          'AddGroupRequest', 'get_Items', 'get_Value', 'Equals', 'set_SelectedIndex',
          'get_DataSource', 'get_CurrencyManager', 'set_Position', 'get_DataBindings',
          'get_Item', 'WriteValue', *resets], 'trigger-exact-match-selection-currency-write-reset-order')
    calls(UI+'BtnAddActionSelectorClick', ['get_ParentForm', 'get_FormBaseUnit',
          'get_SelectedItem', 'get_Address', 'AddLevelRequest', 'get_Items',
          'get_Value', 'Equals', 'set_SelectedItem', *resets], 'action-selected-group-request-item-selection-reset-order')
    absent(UI+'BtnAddActionSelectorClick', ['WriteValue', 'set_Position', 'ReadValue'], 'action-no-explicit-write-currency-or-read')
    calls(UI+'btnNewGroup_Click', ['get_SelectedRows', 'get_Count', 'get_SelectedRows',
          'Select', 'ToList', 'get_Current', 'get_PriSecApplication', 'GetApplicationByAddress',
          'get_FormBaseUnit', 'get_AddressAsInt', 'AddGroupRequest', 'get_Items',
          'get_Value', 'Equals', 'set_SelectedIndex', 'get_CurrencyManager',
          'set_Position', 'get_DataBindings', 'get_Item', 'WriteValue', *resets], 'lighting-selected-row-target-application-currency-write-reset-order')
    absent(UI+'btnNewGroup_Click', ['get_ParentForm', 'InsertSceneItem', 'AddSceneItem', 'RemoveSceneItem'], 'lighting-no-parent-form-gate-or-scene-item-write')
    for symbol in (UI+'BtnAddTriggerGroupClick', UI+'btnNewGroup_Click'):
        absent(symbol, ['ReadValue'], symbol.rsplit('::', 1)[-1]+'-no-explicit-read')
    for symbol in (NETWORK+'AddGroupRequest', NETWORK+'AddLevelRequest'):
        calls(symbol, ['Invoke'], symbol.rsplit('::', 1)[-1]+'-optional-delegate-call')
    sources, source_texts = [], []
    for name, required, forbidden in (
        ('BtnAddTriggerGroupClick', ('ParentForm != null', 'AddGroupRequest', 'if (val != null)', 'if (val2 != null)'), ()),
        ('BtnAddActionSelectorClick', ('SelectedItem is CBusGroup', 'cBusGroup.Address', 'if (text != null)', 'SelectedItem = item'), ('WriteValue()',)),
        ('btnNewGroup_Click', ('SelectedRows).Count != 1', ').ToList();', 'eDLTScene.PriSecApplication != 0', 'val.CurrencyManager', 'if (text != null)'), ('if (val != null)',)),
    ):
        row, text = declaration(SOURCE_UI, name, 'private void '+name+'(', required, forbidden)
        sources.append(row); source_texts.append(text)
    for name, anchor, required in (
        ('AddGroupRequest', 'public string AddGroupRequest(', ('string outStr = null;', 'if (this.addGroupEvent != null)', 'return outStr;')),
        ('AddLevelRequest', 'public string AddLevelRequest(', ('string outStr = null;', 'if (this.addLevelEvent != null)', 'return outStr;')),
    ):
        row, text = declaration(SOURCE_NETWORK, name, anchor, required)
        sources.append(row); source_texts.append(text)
    coordinate_omissions = sum(len(re.findall(r'(?:[A-Za-z]:\\|/(?:Users|private|Volumes)/)', text)) for text in source_texts)
    return {'format': 'cbus-edlt-scene-button-source-annex-v1',
            'original_inputs': inputs, 'managed_method_spans': methods,
            'decompiled_source_symbols': sources, 'static_checks': checks,
            'source_contract': {
                'trigger_add': 'Application202; exact first DataStore.Value match; selected index, optional CurrencyManager Position, optional explicit SelectedValue WriteValue.',
                'action_add': 'Application202 and actual selected CBusGroup.Address; first exact retained Items Value match assigns SelectedItem only; no explicit WriteValue.',
                'lighting_add': 'Exactly one selected Scene row; candidate group cast/list result discarded; current Scene chooses independently resolved primary/secondary Application; no SceneItems insertion.',
                'lighting_selection': 'Returned group string is compared with application selector Values0/1; match sets index, dereferences CurrencyManager, then optional explicit SelectedValue WriteValue.',
                'null_empty': 'Null returned result skips Items scan; empty initialization/result remains a distinct exact string.',
                'resets': 'Every non-early successful handler resets current Scene, Scene bindings false and available-group bindings false, in that order.',
                'profile': 'Explicit synchronous handlers with complete owner-observed Items. Current-culture numeric ToString is bounded to supplied byte decimal digits; no host culture or automatic notification claim.'},
            'omissions': {'raw_instruction_bytes_published': False, 'decompiled_source_text_published': False,
                          'original_literal_heaps_published': False, 'local_coordinate_fields_published': 0,
                          'private_coordinate_occurrences_omitted': coordinate_omissions},
            'limits': {'original_instructions_executed': 0, 'framework_instructions_executed': 0,
                       'host_gui_executed': False, 'modal_dialog_executed': False,
                       'automatic_currency_selection_verified': False, 'automatic_event_schedule_verified': False,
                       'original_host_null_exception_verified': False, 'physical_device_verified': False,
                       'global_refresh_implies_control_rebind': False,
                       'historical_fixtures_rewritten': False, 'private_vendor_code_published': False}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result = recover(args.vendor_root)
    rendered = (json.dumps(result, indent=2, ensure_ascii=False)+'\n').encode('utf-8')
    if args.check:
        if args.output.read_bytes() != rendered:
            raise SystemExit('Scene button static annex differs')
    else:
        args.output.write_bytes(rendered)
    print(json.dumps({'managed_methods': len(result['managed_method_spans']),
                      'source_symbols': len(result['decompiled_source_symbols']),
                      'static_checks': len(result['static_checks']),
                      'original_instructions_executed': 0, 'sha256': digest(rendered)}))


if __name__ == '__main__':
    main()
