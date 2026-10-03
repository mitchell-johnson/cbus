#!/usr/bin/env python3
"""Read-only static proof for Lighting types and ComboImageTagDLT callbacks.

Pinned PE metadata and decompiled declarations are read as data. The sanitized
annex retains hashes, named calls and ordered contracts, never vendor code,
instruction bytes, original string heaps or private compiler coordinates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from research.edlt_scene_name_static import ManagedImage, require_order, source_span

PARSER_PIN = '7bb4f3137bf6da42524cc512d94fe6c711f28b5a80532d018411777f9f573223'
UI_SOURCE = 'edlt-decompiled/eDLT/eDLT.Controls/ComboImageTagDLT.cs'
BASE_SOURCE = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.WidgetData.BaseObjects/'
TYPE_SOURCE = BASE_SOURCE + 'StatusLabelTypeData.cs'
APP_SOURCE = BASE_SOURCE + 'StatusLabelAppGroupData.cs'
WIDGET_SOURCE = BASE_SOURCE + 'WidgetBaseData.cs'
LIGHT_SOURCE = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.WidgetData/LightingData.cs'
GROUP_SOURCE = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.CBusObjects/CBusGroup.cs'
CHOICE_SOURCE = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/CommonConstants.cs'
PINS = {
    'toolkit/app/eDLT.dll': '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3',
    'toolkit/app/CBusLogicModel.dll': '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823',
    UI_SOURCE: 'b23f564aa2052981646b7eec3c34a61f06f55cca701f3a3dc215046035c65c5b',
    TYPE_SOURCE: '58f98c4469b4af7c90df4afe48c72e54b9b94c6683a655b80085b851784d891e',
    APP_SOURCE: 'd0116aad0fe28fef6101ba36a719cbe08aa562036cb47ce86e71cd20470c8b6a',
    WIDGET_SOURCE: '9848f4b6eac5360fc9396887be2ea8aace7fa0e5fdc43cab2ece66597a086189',
    LIGHT_SOURCE: 'aa272e496f89d83e66bc4defe79476cc00c1bb42065835fd0e42b1c8644da873',
    GROUP_SOURCE: '882ef659aa8114ee8d5a9f51c7d7d14cde7322f7da83a33853c9c6f49a3e7aa2',
    CHOICE_SOURCE: '98e20887cf973205eaa42e621f0ee21ee5b9367aac1553f88c75b86e16d39020',
}
UI = 'eDLT.Controls.ComboImageTagDLT::'
BASE = 'CBusLogicModel.Units.EDLT.WidgetData.BaseObjects.'
TYPE = BASE + 'StatusLabelTypeData::'
APP = BASE + 'StatusLabelAppGroupData::'
LIGHT = 'CBusLogicModel.Units.EDLT.WidgetData.LightingData::'
WIDGET = BASE + 'WidgetBaseData::'
GROUP = 'CBusLogicModel.CBusObjects.CBusGroup::'
METHODS = {
    'toolkit/app/eDLT.dll': tuple(UI + name for name in (
        '.ctor', 'set_BindingDataSource', 'set_TextEditable', 'RemoveDataSettingBindings',
        'ComboBoxStaticText_Leave', 'ComboImageTagDLT_PreviewKeyDown',
        'ComboImageTagDLT_SelectedIndexChanged', 'DataManager_ListChanged',
        'DataBindingMode', 'OnDrawItem')),
    'toolkit/app/CBusLogicModel.dll': (
        *(TYPE + name for name in ('get_StatusDisplayType', 'set_StatusDisplayType',
          'get_LabelDisplayType', 'set_LabelDisplayType', 'UpdateLabelTypes')),
        *(APP + name for name in ('get_DynamicLabels', 'GetDynamicLabelVariantType',
          'GetDynamicFunctionVariantType', 'get_SelectableLabelVariants',
          'get_SelectableStatusVariants', 'set_LabelValueText', 'set_StatusValueText')),
        *(LIGHT + name for name in ('get_LabelValueIndex', 'set_LabelValueIndex',
          'get_StatusValueIndex', 'set_StatusValueIndex', 'GetUsedStaticText')),
        WIDGET + 'NotifyPropertyChanged', GROUP + 'PopulateDynamicAll'),
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def recover(vendor_root):
    parser = Path(__file__).with_name('edlt_scene_name_static.py')
    if digest(parser.read_bytes()) != PARSER_PIN:
        raise ValueError('Pinned static parser differs')
    inputs = [{'logical_name': 'static-managed-parser', 'sha256': PARSER_PIN,
               'bytes': parser.stat().st_size, 'role': 'repository-static-parser'}]
    originals = {}
    for name, expected in PINS.items():
        raw = (vendor_root / name).read_bytes()
        if digest(raw) != expected:
            raise ValueError('Pinned static original differs: ' + Path(name).name)
        originals[name] = raw
        inputs.append({'logical_name': Path(name).name, 'sha256': expected,
                       'bytes': len(raw), 'role': 'original-static-input'})
    methods, decoded = [], {}
    for assembly, symbols in METHODS.items():
        image = ManagedImage(originals[assembly])
        if image.runtime != 'v4.0.30319':
            raise ValueError('Original managed metadata runtime differs')
        for symbol in symbols:
            detail = image.instructions(symbol)
            for call in detail['calls']:
                token = int(call['token'], 16)
                if token >> 24 == 43:
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

    def constants(symbol, values, label):
        actual = [row['value'] for row in decoded[symbol]['integer_constants']]
        if any(value not in actual for value in values):
            raise ValueError('Pinned integer constants differ: ' + label)
        checks.append({'id': label, 'symbol': symbol,
                       'required_integer_constants': values, 'passed': True})

    def absent(symbol, requested, label):
        if any(any(row['symbol'].endswith(part) for row in decoded[symbol]['calls']) for part in requested):
            raise ValueError('Unexpected original call: ' + label)
        checks.append({'id': label, 'symbol': symbol,
                       'absent_call_suffixes': requested, 'passed': True})

    calls(UI + '.ctor', ['set_MaxLength', 'set_DrawMode', 'set_ValueMember',
          'set_DisplayMember', 'set_DropDownStyle', 'set_AutoCompleteSource',
          'set_AutoCompleteMode', 'set_DoubleBuffered'], 'initial-control-settings-order')
    constants(UI + '.ctor', [64, 0, 2, 256, 3], 'initial-control-settings-values')
    calls(UI + 'set_BindingDataSource', ['RemoveDataSettingBindings', 'get_BindingDataSource',
          'DataBindingMode'], 'changed-source-detaches-before-mode-rebuild')
    calls(UI + 'set_TextEditable', ['set_Visible', 'RemoveDataSettingBindings',
          'get_BindingDataSource', 'DataBindingMode', 'get_DataManager',
          'remove_ListChanged', 'add_ListChanged'], 'editable-visibility-binding-list-subscription-order')
    calls(UI + 'RemoveDataSettingBindings', ['remove_SelectedIndexChanged',
          'remove_PreviewKeyDown', 'remove_Leave', 'get_DataBindings',
          'get_PropertyName', 'get_PropertyName', 'Remove', 'Remove'], 'remove-callbacks-before-two-last-property-bindings')
    calls(UI + 'ComboBoxStaticText_Leave', ['get_DataBindings', 'get_Item',
          'WriteValue', 'ReadValue'], 'leave-text-write-before-read')
    calls(UI + 'ComboImageTagDLT_PreviewKeyDown', ['get_KeyCode', 'WriteValue',
          'ReadValue', 'get_DroppedDown', 'set_DroppedDown'], 'enter-write-read-before-nonenter-dropdown-rule')
    constants(UI + 'ComboImageTagDLT_PreviewKeyDown', [13, 37, 39, 38, 40], 'enter-and-four-arrow-keys')
    calls(UI + 'ComboImageTagDLT_SelectedIndexChanged', ['remove_ListChanged',
          'add_ListChanged', 'get_DataSource', 'get_SelectedIndex',
          'WriteValue', 'ReadValue', 'WriteValue', 'ReadValue', 'LogException'], 'selection-subscriptions-text-then-index-write-read-and-catch')
    constants(UI + 'ComboImageTagDLT_SelectedIndexChanged', [0, -1], 'selection-suppression-and-unselected-boundaries')
    calls(UI + 'DataManager_ListChanged', ['get_TextEditable', 'get_InvokeRequired',
          'BeginInvoke', 'get_Visible', 'get_ListChangedType', 'get_NewIndex',
          'get_OldIndex', 'get_OldIndex', 'ReadValue'], 'list-change-early-mode-then-async-then-visible-index-predicate')
    absent(UI + 'DataManager_ListChanged', ['WriteValue'], 'list-change-is-read-only')
    calls(UI + 'DataBindingMode', ['set_DrawMode', 'set_ValueMember', 'set_DisplayMember',
          'set_DropDownStyle', 'set_AutoCompleteSource', 'get_TextMember', 'Add',
          'add_PreviewKeyDown', 'add_Leave', 'add_SelectedIndexChanged', 'set_DoubleBuffered',
          'set_DrawMode', 'set_ValueMember', 'set_DisplayMember', 'set_DropDownStyle',
          'get_IndexMember', 'Add', 'add_SelectedIndexChanged', 'set_DoubleBuffered'], 'editable-text-and-indexed-selectedvalue-binding-modes')
    constants(UI + 'DataBindingMode', [0, 1, 2, 256], 'binding-modes-and-manual-update-constants')
    constants(UI + 'OnDrawItem', [4, 0, 1], 'drawing-four-row-and-one-based-numbering-profile')
    calls(UI + 'OnDrawItem', ['get_Count', 'get_Index', 'get_Image', 'DrawImage',
          'get_ValueAsInt', 'get_Name', 'get_ValueAsInt'], 'drawing-image-before-name-fallback-descriptor')
    for target, dynamic, mask in (('Status', 'Function', 240), ('Label', 'Label', 143)):
        symbol = TYPE + f'set_{target}DisplayType'
        calls(symbol, [f'GetDynamic{dynamic}VariantType', f'get_{target}DisplayType',
              'set_ValueAsInt', 'NotifyPropertyChanged', f'get_{target}DisplayType',
              f'set_{target}ValueIndex', 'NotifyPropertyChanged', 'NotifyPropertyChanged'],
              target.lower() + '-dynamic-resolution-byte-notify-virtual-index-notify-order')
        constants(symbol, [10, 1, mask, 0], target.lower() + '-type-mask-generic-and-zero-index')
    calls(TYPE + 'UpdateLabelTypes', ['get_StatusDisplayType', 'set_StatusDisplayType',
          'get_LabelDisplayType', 'set_LabelDisplayType'], 'update-status-before-label')
    calls(APP + 'get_DynamicLabels', ['get_SelectedGroup', 'get_AddressAsInt',
          'get_SelectedGroup', 'get_DynamicAll'], 'lighting-dynamic-getter-reads-current-selected-group-list')
    constants(APP + 'get_DynamicLabels', [255], 'unassigned-group-has-no-dynamic-labels')
    for target, dynamic, outputs in (('Label', 'Label', [2, 1]), ('Status', 'Function', [7, 6])):
        symbol = APP + f'GetDynamic{dynamic}VariantType'
        calls(symbol, ['get_DynamicLabels', 'get_Count', f'get_{target}ValueIndex',
              f'set_{target}ValueIndex', 'get_DynamicLabels', 'get_Item', 'get_Image'],
              target.lower() + '-count-before-invalid-index-repair-and-image-read')
        constants(symbol, [0, 3, *outputs], target.lower() + '-dynamic-image-text-subtypes')
        calls(APP + f'get_Selectable{target}Variants', [f'get_{target}DisplayType',
              'get_DynamicLabels', 'get_StaticTextSuggest'], target.lower() + '-dynamic-or-static-choice-source')
        calls(APP + f'set_{target}ValueText', ['GetStaticTextIndex', f'set_{target}ValueIndex'],
              target.lower() + '-text-source-allocator-before-index-setter')
        calls(LIGHT + f'set_{target}ValueIndex', ['get_ValueAsInt', 'set_ValueAsInt',
              f'get_Dynamic{dynamic}Selected', f'set_{target}DisplayType'],
              target.lower() + '-lighting-index-write-then-dynamic-subtype-resolution')
    constants(LIGHT + 'get_LabelValueIndex', [1, 4, 7, 13, 64, 0], 'lighting-label-field-and-getter-clamps')
    constants(LIGHT + 'get_StatusValueIndex', [1, 7, 14, 4, 64, 0], 'lighting-status-field-and-low-three-bit-getter-clamps')
    calls(WIDGET + 'NotifyPropertyChanged', ['Invoke', 'Invoke', 'Invoke'], 'custom-before-property-custom-after-notification')
    calls(GROUP + 'PopulateDynamicAll', ['get_DynamicAll', 'set_DynamicAll',
          'set_RaiseListChangedEvents', 'Clear', 'get_TagsDLT', 'PopulateImage',
          'Add', 'set_RaiseListChangedEvents', 'NotifyPropertyChanged',
          'PopulateDynamicAllLanguages'], 'current-dynamic-list-cleared-repopulated-notified-with-project-images')

    declarations = (
        (UI_SOURCE, 'BindingDataSource', 'public object BindingDataSource', ('RemoveDataSettingBindings();', 'DataBindingMode();')),
        (UI_SOURCE, 'TextEditable', 'public bool TextEditable', ('Visible = true;', 'ListChanged -= DataManager_ListChanged;', 'ListChanged += DataManager_ListChanged;')),
        (UI_SOURCE, 'RemoveDataSettingBindings', 'public void RemoveDataSettingBindings()', ('"SelectedValue"', '"Text"')),
        (UI_SOURCE, 'OnDrawItem', 'protected override void OnDrawItem(', ('Count > 4', '"<Default>"', 'Image != null')),
        (UI_SOURCE, 'Leave', 'private void ComboBoxStaticText_Leave(', ('WriteValue();', 'ReadValue();')),
        (UI_SOURCE, 'PreviewKeyDown', 'private void ComboImageTagDLT_PreviewKeyDown(', ('(int)e.KeyCode == 13', '(int)e.KeyCode == 37', '(int)e.KeyCode == 39', '(int)e.KeyCode == 38', '(int)e.KeyCode == 40')),
        (UI_SOURCE, 'SelectedIndexChanged', 'private void ComboImageTagDLT_SelectedIndexChanged(', ('bDisableIndexChanged', 'SelectedIndex > -1', 'WriteValue();', 'ReadValue();', 'catch')),
        (UI_SOURCE, 'DataManager_ListChanged', 'private void DataManager_ListChanged(', ('!TextEditable', 'bDisableListChanged', 'InvokeRequired', 'Visible', 'e.NewIndex <', 'e.OldIndex != -1', 'ReadValue();')),
        (UI_SOURCE, 'DataBindingMode', 'private void DataBindingMode()', ('(DataSourceUpdateMode)2', '"ValueAsInt"', '"FormattedDisplay"')),
        (TYPE_SOURCE, 'StatusDisplayType', 'public int StatusDisplayType', ('valueAsInt & 0xF0', 'StatusValueIndex = 0;', 'StatusDisplayType == 10')),
        (TYPE_SOURCE, 'LabelDisplayType', 'public int LabelDisplayType', ('valueAsInt & 0x8F', 'LabelValueIndex = 0;', 'LabelDisplayType == 10')),
        (TYPE_SOURCE, 'UpdateLabelTypes', 'public override void UpdateLabelTypes()', ('StatusDisplayType = StatusDisplayType;', 'LabelDisplayType = LabelDisplayType;')),
        (APP_SOURCE, 'DynamicLabels', 'public BindingList<DataStore> DynamicLabels', ('selectedGroup == null', 'selectedGroup.AddressAsInt == 255', 'return SelectedGroup.DynamicAll;')),
        (APP_SOURCE, 'DynamicLabelVariantType', 'public override int GetDynamicLabelVariantType()', ('DynamicLabels.Count > LabelValueIndex', 'LabelValueIndex < 0 || LabelValueIndex > 3', 'DynamicLabels[LabelValueIndex].Image != null')),
        (APP_SOURCE, 'DynamicFunctionVariantType', 'public override int GetDynamicFunctionVariantType()', ('DynamicLabels.Count > StatusValueIndex', 'StatusValueIndex < 0 || StatusValueIndex > 3', 'DynamicLabels[StatusValueIndex].Image != null')),
        (LIGHT_SOURCE, 'LabelValueIndex', 'public override int LabelValueIndex', ('WidgetByte(13)', 'base.DynamicLabelSelected', 'DoNotFireNotifyPropertyChanged = true;', 'base.LabelDisplayType = 10;')),
        (LIGHT_SOURCE, 'StatusValueIndex', 'public override int StatusValueIndex', ('WidgetByte(14)', 'base.DynamicFunctionSelected', 'DoNotFireNotifyPropertyChanged = true;', 'base.StatusDisplayType = 10;')),
        (WIDGET_SOURCE, 'NotifyPropertyChanged', 'public void NotifyPropertyChanged(', ('!DoNotFireNotifyPropertyChanged', 'this.CustomPropertyChangingEvent();', 'CustomPropertyChangingEvent(bFinished: true)')),
        (GROUP_SOURCE, 'PopulateDynamicAll', 'public void PopulateDynamicAll()', ('if (DynamicAll == null)', 'DynamicAll.Clear();', 'PopulateImage', 'DynamicAll.Add(item);', 'PopulateDynamicAllLanguages();')),
    )
    sources, coordinate_omissions = [], 0
    for path, name, anchor, required in declarations:
        span = source_span(originals[path], name, anchor)
        lines = originals[path].decode('utf-8-sig').splitlines(keepends=True)
        text = ''.join(lines[span['start_line'] - 1:span['end_line']])
        if any(value not in text for value in required):
            raise ValueError('Pinned declaration contract differs: ' + name)
        sources.append({'logical_name': Path(path).name, **span})
        checks.append({'id': 'declaration-' + name, 'symbol': name,
                       'required_anchor_count': len(required), 'passed': True})
        coordinate_omissions += len(re.findall(r'(?:[A-Za-z]:\\|/(?:Users|private|Volumes)/)', text))
    choices = {}
    for name, expected in (('lLabelTypes', [0, 10, 3]), ('lLabelTypesScene', [0, 1, 2, 3]),
                           ('lFunctionStatusTypes', [0, 3, 10, 1, 2, 5]),
                           ('lFunctionStatusTypesScenes', [0, 6, 7, 5])):
        span = source_span(originals[CHOICE_SOURCE], name, 'public List<DataStore> ' + name + ' =')
        lines = originals[CHOICE_SOURCE].decode('utf-8-sig').splitlines(keepends=True)
        text = ''.join(lines[span['start_line'] - 1:span['end_line']])
        values = [int(value) for value in re.findall(r'new DataStore\("[^"\\]*", (\d+)\)', text)]
        if values != expected:
            raise ValueError('Source type choice order differs: ' + name)
        choices[name] = values
        sources.append({'logical_name': Path(CHOICE_SOURCE).name, **span})
        checks.append({'id': 'source-type-choices-' + name, 'symbol': name,
                       'ordered_integer_values': values, 'passed': True})
    return {'format': 'cbus-edlt-label-control-source-annex-v1',
        'original_inputs': inputs, 'managed_method_spans': methods,
        'decompiled_source_symbols': sources, 'static_checks': checks,
        'source_type_choice_values': choices,
        'source_contract': {
            'type_properties': 'Byte1 masked nibble preservation, generic dynamic image subtype resolution, same-byte early return, notification before virtual index reset, status-before-label update.',
            'lighting_indices': 'Byte13 label and Byte14 status getters clamp source static/dynamic ranges; label unchanged index does not re-resolve, status unchanged index does.',
            'dynamic_rows': 'Non255 Lighting SelectedGroup.DynamicAll is read at each getter; null/255 yields empty rows. Current group list is cleared/repopulated with current TagsDLT/project image facts.',
            'static_names': 'Label/Status text setters call the source shared StaticText allocator before the virtual index setter; complete retained names and old references are required.',
            'combo_modes': 'Editable Text versus indexed SelectedValue manual bindings, exact detach/rebuild and DataManager subscription order; changed editable mode first makes the control visible.',
            'callbacks': 'Leave/Enter-key preview write then read; enter is only an explicit Enter-key shorthand, never focus Enter. Arrows suppress one selection; selected event rewires ListChanged before suppression and writes Text before SelectedValue where each binding exists.',
            'list_changed': 'Mode/global-disable guard precedes async dispatch; admitted synchronous eligible visible index predicate reads Text only.',
            'drawing': 'Logical four-row DataStore descriptor only: one-based integer display, image branch, null-name Default fallback. No pixels/Graphics or culture formatting claim.',
            'property_notifications': 'PropertyChanged intent ordering only, conditional on real subscriber and the source global suppression flag; no inferred automatic Framework dispatch.'},
        'omissions': {'raw_instruction_bytes_published': False,
            'decompiled_source_text_published': False, 'original_literal_heaps_published': False,
            'local_coordinate_fields_published': 0,
            'private_coordinate_occurrences_omitted': coordinate_omissions},
        'limits': {'original_instructions_executed': 0, 'framework_instructions_executed': 0,
            'original_host_executed': False, 'automatic_currency_selection_verified': False,
            'automatic_event_schedule_verified': False, 'async_begininvoke_verified': False,
            'drawing_pixels_verified': False, 'original_exception_logging_verified': False,
            'static_suggestion_culture_order_verified': False, 'physical_device_verified': False,
            'other_widget_adapters_admitted': False, 'historical_fixtures_rewritten': False}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result = recover(args.vendor_root)
    rendered = (json.dumps(result, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    if args.check:
        if args.output.read_bytes() != rendered:
            raise SystemExit('Label control static annex differs')
    else:
        args.output.write_bytes(rendered)
    print(json.dumps({'managed_methods': len(result['managed_method_spans']),
        'source_symbols': len(result['decompiled_source_symbols']),
        'static_checks': len(result['static_checks']), 'sha256': digest(rendered),
        'original_instructions_executed': 0}))


if __name__ == '__main__':
    main()
