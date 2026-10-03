#!/usr/bin/env python3
"""Read-only SceneWidget/SceneData source proof, without loading assemblies.

The public annex contains method spans/hashes, declaration spans/hashes,
named call order, source constants and bounds. It omits vendor source text,
raw IL, original string heaps and private compiler coordinates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from research.edlt_scene_name_static import ManagedImage, require_order, source_span

PARSER_PIN = '7bb4f3137bf6da42524cc512d94fe6c711f28b5a80532d018411777f9f573223'
BASE = 'edlt-decompiled/CBusLogicModel/'
SCENE_SOURCE = BASE + 'CBusLogicModel.Units.EDLT.WidgetData/SceneData.cs'
TYPE_SOURCE = BASE + 'CBusLogicModel.Units.EDLT.WidgetData.BaseObjects/StatusLabelTypeData.cs'
WIDGET_SOURCE = BASE + 'CBusLogicModel.Units.EDLT.WidgetData.BaseObjects/WidgetBaseData.cs'
UNIT_SOURCE = BASE + 'CBusLogicModel.Units.EDLT/EDLTUnit.cs'
CHOICES_SOURCE = BASE + 'CBusLogicModel.Utilities/CommonConstants.cs'
MACROS_SOURCE = BASE + 'CBusLogicModel.Units.EDLT.Utilities/MacroFunctionTypes.cs'
MICROS_SOURCE = BASE + 'CBusLogicModel.Units.EDLT.Utilities/MicroFunctions.cs'
UI_SOURCE = 'edlt-decompiled/eDLT/eDLT.WidgetPanels/SceneWidget.cs'
PINS = {
    'toolkit/app/eDLT.dll': '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3',
    'toolkit/app/CBusLogicModel.dll': '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823',
    SCENE_SOURCE: '27993e0c0f6e9aa4bf7485b65b1dbc2d3cfd87f49d1d287ada9dbca5193074c1',
    UI_SOURCE: 'ec8c3d138e2ad4afb5a9d45d15316d3037eb5fb64f8ff7a197ad63aa9cd83abb',
    TYPE_SOURCE: '58f98c4469b4af7c90df4afe48c72e54b9b94c6683a655b80085b851784d891e',
    WIDGET_SOURCE: '9848f4b6eac5360fc9396887be2ea8aace7fa0e5fdc43cab2ece66597a086189',
    UNIT_SOURCE: '641f5abc1c3762cd86a0c4b18bc125424a39017a3d78d6edfa4e1e2964af62b2',
    CHOICES_SOURCE: '98e20887cf973205eaa42e621f0ee21ee5b9367aac1553f88c75b86e16d39020',
    MACROS_SOURCE: '828d9b0a68076478b8514764a65b2374ee4f7cd236c088548484a2f533d176d7',
    MICROS_SOURCE: '39f871176be4185088281e075e8801878b11aeda0891be77d0d5033da5c9681e',
}
SCENE = 'CBusLogicModel.Units.EDLT.WidgetData.SceneData::'
TYPE = 'CBusLogicModel.Units.EDLT.WidgetData.BaseObjects.StatusLabelTypeData::'
UI = 'eDLT.WidgetPanels.SceneWidget::'
UNIT = 'CBusLogicModel.Units.EDLT.EDLTUnit::'
METHODS = {
    'toolkit/app/eDLT.dll': tuple(UI + name for name in (
        'SetUpDataSource', 'InitializeComponent', 'DeleteSceneItem', 'btnDelete_Click',
        'btnAdd_Click', 'buttonNoFocus1_Click', 'buttonNoFocus2_Click',
        'dataGridView1_KeyDown', 'dataGridView1_DataError',
        'dataGridView1_CurrentCellDirtyStateChanged')),
    'toolkit/app/CBusLogicModel.dll': (
        *(SCENE + name for name in (
            '.ctor', 'get_DualButtonMacrofunction', 'set_DualButtonMacrofunction',
            'get_LeftButtonMacrofunction', 'set_LeftButtonMacrofunction',
            'get_RightButtonMacrofunction', 'set_RightButtonMacrofunction',
            'get_SceneCycleSelectionEditable', 'get_SceneSingleSelectionEditable',
            'get_SceneCycleVariant', 'set_SceneCycleVariant',
            'get_NotSceneCycleVariantSelect', 'set_NotSceneCycleVariantSelect',
            'get_SceneCycleVariantSelect', 'set_SceneCycleVariantSelect',
            'get_RampRateEditable', 'get_OffsetEditable', 'get_SceneCycleStateLabel',
            'get_SceneItem', 'set_SceneItem', 'get_SceneCycle', 'SceneCycleAddScene',
            'get_CanAddScene', 'get_CanRemoveScene', 'get_SceneCyclesFull',
            'get_LabelValueIndex', 'set_LabelValueIndex', 'get_StatusValueIndex', 'set_StatusValueIndex',
            'get_StatusValueText', 'set_StatusValueText', 'get_LabelVariants', 'get_StatusVariants',
            'get_SelectedLabelVariant', 'set_SelectedLabelVariant',
            'get_SelectedStatusVariant', 'set_SelectedStatusVariant',
            'get_DltVariantsEnabled', 'get_SelectLabelVariantsEnabled', 'get_SelectStatusVariantsEnabled',
            'get_ShowStatusVariants', 'GetUsedStaticText', 'this_PropertyChanged', 'InputValueIsEditable')),
        *(TYPE + name for name in ('get_StatusDisplayType', 'set_StatusDisplayType',
            'get_LabelDisplayType', 'set_LabelDisplayType', 'set_LabelValueIndex', 'set_StatusValueIndex')),
        *(UNIT + name for name in ('GetStaticTextIndex', 'get_ScenesNameValue')),
        'CBusLogicModel.Units.EDLT.Utilities.MacroFunctionTypes::.cctor',
        'CBusLogicModel.Units.EDLT.Utilities.MicroFunctions::.cctor'),
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def recover(vendor_root):
    parser = Path(__file__).with_name('edlt_scene_name_static.py')
    if digest(parser.read_bytes()) != PARSER_PIN:
        raise ValueError('Pinned managed parser differs')
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
            raise ValueError('Managed runtime metadata differs')
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

    def calls(symbol, values, label):
        require_order([row['symbol'] for row in decoded[symbol]['calls']], values, label)
        checks.append({'id': label, 'symbol': symbol, 'ordered_call_suffixes': values, 'passed': True})

    def constants(symbol, values, label):
        actual = [row['value'] for row in decoded[symbol]['integer_constants']]
        if any(value not in actual for value in values):
            raise ValueError('Pinned integer constants differ: ' + label)
        checks.append({'id': label, 'symbol': symbol, 'required_integer_constants': values, 'passed': True})

    def absent(symbol, suffixes, label):
        if any(any(row['symbol'].endswith(part) for row in decoded[symbol]['calls']) for part in suffixes):
            raise ValueError('Unexpected call: ' + label)
        checks.append({'id': label, 'symbol': symbol, 'absent_call_suffixes': suffixes, 'passed': True})

    calls(SCENE + 'get_SceneCycle', ['set_RaiseListChangedEvents', 'Clear', 'WidgetByte',
        'SceneCycleAddScene', 'WidgetByte', 'set_ValueAsInt', 'set_RaiseListChangedEvents'], 'explicit-cycle-read-normalization-order')
    constants(SCENE + 'get_SceneCycle', [9, 13, 255], 'getter-nine-fields-and-trailing-sentinel')
    constants(SCENE + 'SceneCycleAddScene', [9, -1], 'getter-raw-zero-through-eight')
    for name in ('CanAddScene', 'CanRemoveScene'):
        calls(SCENE + 'get_' + name, ['get_SceneCycle', 'get_Count'], name + '-explicit-getter-effect')
    calls(UI + 'btnAdd_Click', ['get_DataSource', 'get_SceneCyclesFull', 'get_ValueAsInt',
        'get_SceneCyclesFull', 'set_ValueAsInt', 'get_SceneCyclesFull', 'set_ValueAsInt',
        'get_CurrencyManager', 'get_List', 'get_Count', 'set_Position', 'ResetCurrentItem',
        'ResetBindings', 'get_CurrencyManager', 'get_List', 'get_Count', 'set_Position', 'ResetBindings'], 'add-eight-slots-then-two-position-reset-sequences')
    constants(UI + 'btnAdd_Click', [8, 7, 0, 255], 'add-eight-fields-no-ninth-normalization')
    absent(UI + 'btnAdd_Click', ['get_SceneCycle'], 'add-has-no-explicit-cycle-getter')
    calls(UI + 'DeleteSceneItem', ['get_Current', 'get_DataSource', 'get_SceneCycle', 'IndexOf',
        'get_SceneCyclesFull', 'set_ValueAsInt', 'get_SceneCyclesFull', 'get_SceneCyclesFull',
        'get_ValueAsInt', 'set_ValueAsInt', 'get_SceneCyclesFull', 'get_Count',
        'ResetBindings', 'ResetBindings'], 'delete-current-then-getter-index-shift-and-two-resets')
    constants(UI + 'DeleteSceneItem', [8, 255], 'delete-ninth-slot-is-sentinel')
    calls(UI + 'buttonNoFocus1_Click', ['get_CurrentCell', 'get_CurrentCell', 'get_RowIndex',
        'get_DataSource', 'get_SceneCyclesFull', 'get_ValueAsInt', 'get_SceneCyclesFull',
        'get_ValueAsInt', 'set_ValueAsInt', 'set_ValueAsInt', 'ResetCurrentItem',
        'ResetBindings', 'set_Position', 'ResetBindings'], 'move-up-explicit-grid-row-before-resets')
    calls(UI + 'buttonNoFocus2_Click', ['get_CurrentCell', 'get_RowIndex', 'get_RowCount',
        'get_DataSource', 'get_ValueAsInt', 'get_ValueAsInt', 'set_ValueAsInt', 'set_ValueAsInt',
        'ResetCurrentItem', 'ResetBindings', 'set_Position', 'ResetBindings'], 'move-down-explicit-rowcount-before-resets')
    for name in ('buttonNoFocus1_Click', 'buttonNoFocus2_Click'):
        absent(UI + name, ['get_SceneCycle'], name + '-no-explicit-cycle-getter')
    calls(UI + 'dataGridView1_KeyDown', ['get_KeyCode', 'DeleteSceneItem', 'set_Handled'], 'delete-key-calls-delete-before-handled')
    constants(UI + 'dataGridView1_KeyDown', [46, 1], 'delete-key-and-handled-true')
    calls(UI + 'dataGridView1_CurrentCellDirtyStateChanged', ['get_IsCurrentCellDirty', 'CommitEdit'], 'dirty-cell-commit-request')
    constants(UI + 'dataGridView1_CurrentCellDirtyStateChanged', [512], 'dirty-cell-commit-context')
    calls(UI + 'dataGridView1_DataError', ['set_Cancel'], 'data-error-cancel-false')
    constants(UI + 'dataGridView1_DataError', [0], 'data-error-cancel-value')
    calls(UI + 'SetUpDataSource', ['get_DataBindings', 'Clear', 'SetUpDataSource',
        'get_SelectedLabelVariant', 'get_SelectedStatusVariant', 'get_StatusValueText',
        'get_StatusValueIndex', 'set_DataSource', 'set_SelectedValue', 'set_SelectedValue',
        'get_ScenesNameValue', 'set_DataSource', 'get_ScenesNameValue', 'set_DataSource',
        'ResetBindings', 'ResetBindings', 'ResetBindings', 'set_StatusValueIndex', 'set_Text'], 'setup-snapshots-before-binding-then-status-restore')
    constants(UI + 'SetUpDataSource', [1, 2, 0], 'scene-binding-onpropertychanged-and-never')
    absent(UI + 'SetUpDataSource', ['get_SceneCycle'], 'setup-no-explicit-cycle-getter')
    for target, offset in (('Label', 11), ('Status', 12)):
        constants(SCENE + 'set_' + target + 'ValueIndex', [offset], target.lower() + '-new-raw-index-offset')
        absent(SCENE + 'set_' + target + 'ValueIndex', ['NotifyPropertyChanged', 'set_' + target + 'DisplayType'], target.lower() + '-new-index-no-subtype-or-notify')
        constants(SCENE + 'set_Selected' + target + 'Variant', [offset], target.lower() + '-selected-variant-same-raw-offset')
        absent(TYPE + 'set_' + target + 'ValueIndex', ['WidgetByte', 'set_ValueAsInt'], target.lower() + '-base-auto-property-is-not-raw-index')
    calls(SCENE + 'set_StatusValueText', ['get_StatusValueText', 'op_Inequality', 'GetStaticTextIndex', 'set_StatusValueIndex'], 'status-text-same-name-guard-before-old-reference-allocation')
    calls(SCENE + 'GetUsedStaticText', ['GetUsedStaticText', 'get_StatusDisplayType', 'get_StatusValueIndex', 'Add'], 'static-status-old-reference-is-reserved')
    constants(SCENE + 'GetUsedStaticText', [5], 'static-status-type')
    constants(SCENE + 'set_SceneCycleVariant', [1, 7, 127], 'cycle-variant-preserves-low-seven-bits')
    calls(SCENE + 'set_DualButtonMacrofunction', ['Split', 'TryParse', 'TryParse',
        'set_LeftButtonMacrofunction', 'set_RightButtonMacrofunction', 'NotifyPropertyChanged'], 'macro-left-before-right-before-single-visibility-notify')
    calls(SCENE + 'this_PropertyChanged', ['get_PropertyName', 'op_Equality', 'get_PropertyName',
        'op_Equality', 'NotifyPropertyChanged', 'get_PropertyName', 'op_Equality', 'NotifyPropertyChanged'], 'macro-subscriber-and-selected-group-notify-intent')
    calls(UNIT + 'GetStaticTextIndex', ['Trim', 'get_Length', 'get_StaticLabels',
        'get_Name', 'Equals', 'GetUsedStaticText'], 'allocator-blank-then-cached-name-before-used-capacity')

    declarations = (
        (SCENE_SOURCE, 'SceneCycle', 'public BindingList<PPAttribute> SceneCycle\n', ('for (; i < 9; i++)', 'if (flag)', 'SceneCycleAddScene(WidgetByte(13 + i))', 'ValueAsInt = 255;')),
        (SCENE_SOURCE, 'SceneCycleAddScene', 'private bool SceneCycleAddScene(', ('ValueAsInt < 9', 'ValueAsInt > -1', 'sceneCycle.Add(ppAtt);')),
        (SCENE_SOURCE, 'SceneDataConstructor', 'public SceneData(', ('for (int i = 0; i < 9; i++)', 'SceneCyclesFull.Add(WidgetByte(13 + i));', 'base.PropertyChanged += this_PropertyChanged;')),
        (SCENE_SOURCE, 'LabelValueIndex', 'public new int LabelValueIndex', ('WidgetByte(11).ValueAsInt',)),
        (SCENE_SOURCE, 'StatusValueIndex', 'public new int StatusValueIndex', ('WidgetByte(12).ValueAsInt',)),
        (SCENE_SOURCE, 'StatusValueText', 'public virtual string StatusValueText', ('StatusValueIndex > 63', 'StaticLabels[StatusValueIndex].Name', 'value != StatusValueText && value != null', 'GetStaticTextIndex(value)')),
        (SCENE_SOURCE, 'SceneCycleVariant', 'public int SceneCycleVariant\n', ('>> 7', 'value << 7', 'valueAsInt & 0x7F')),
        (SCENE_SOURCE, 'NotSceneCycleVariantSelect', 'public bool NotSceneCycleVariantSelect', ('SceneCycleVariant = 0;', 'SceneCycleVariant = 1;')),
        (SCENE_SOURCE, 'SceneCycleVariantSelect', 'public bool SceneCycleVariantSelect', ('SceneCycleVariant = 1;', 'SceneCycleVariant = 0;')),
        (SCENE_SOURCE, 'PropertyChanged', 'private void this_PropertyChanged(', ('"RightButtonMacrofunctin"', '"RampRateEditable"', '"SelectedApplicationGroups"', '"SceneCycleSelectionEditable"')),
        (SCENE_SOURCE, 'InputValueIsEditable', 'public bool InputValueIsEditable(', ('macroFunction.Key == LeftButtonMacrofunction', 'macroFunction.Key == RightButtonMacrofunction', 'if (flag || num >= 2)')),
        (TYPE_SOURCE, 'BaseLabelValueIndex', 'public virtual int LabelValueIndex', ('get; set;',)),
        (TYPE_SOURCE, 'BaseStatusValueIndex', 'public virtual int StatusValueIndex', ('get; set;',)),
        (TYPE_SOURCE, 'LabelDisplayType', 'public int LabelDisplayType', ('GetType() != typeof(SceneData)', 'valueAsInt & 0x8F', 'LabelValueIndex = 0;')),
        (TYPE_SOURCE, 'StatusDisplayType', 'public int StatusDisplayType', ('GetType() != typeof(SceneData)', 'valueAsInt & 0xF0', 'StatusValueIndex = 0;')),
        (UI_SOURCE, 'SetUpDataSource', 'public override void SetUpDataSource()', ('DataBindings.Clear();', 'selectedLabelVar =', 'selectedStatusVar =', 'statusValueText =', 'statusValueIndex =', 'StatusValueIndex = statusValueIndex;', '.Text = statusValueText;')),
        (UI_SOURCE, 'DeleteSceneItem', 'private void DeleteSceneItem()', ('pPAttribute == null || sceneData == null', 'SceneCycle.IndexOf(pPAttribute)', 'if (i == 8)', 'ResetBindings(false);')),
        (UI_SOURCE, 'AddSceneItem', 'private void btnAdd_Click(', ('for (int i = 0; i < 8; i++)', 'ValueAsInt > 7', 'ValueAsInt = 0;', 'ValueAsInt = 255;', 'Position = sceneCycleBindingSource.List.Count;')),
        (UI_SOURCE, 'MoveUp', 'private void buttonNoFocus1_Click(', ('CurrentCell != null', 'if (rowIndex > 0)', 'Position = rowIndex - 1;')),
        (UI_SOURCE, 'MoveDown', 'private void buttonNoFocus2_Click(', ('CurrentCell != null', 'rowIndex < dataGridView1.RowCount - 1 && rowIndex >= 0', 'Position = rowIndex + 1;')),
        (UI_SOURCE, 'DirtyCell', 'private void dataGridView1_CurrentCellDirtyStateChanged(', ('IsCurrentCellDirty', 'CommitEdit((DataGridViewDataErrorContexts)512)')),
        (UNIT_SOURCE, 'ScenesNameValue', 'public BindingList<DataStore> ScenesNameValue', ('Scenes.Count', 'StaticLabels', 'NameIndex')),
    )
    sources = []
    for path, name, anchor, anchors in declarations:
        span = source_span(originals[path], name, anchor)
        lines = originals[path].decode('utf-8-sig').splitlines(keepends=True)
        text = ''.join(lines[span['start_line'] - 1:span['end_line']])
        if any(value not in text for value in anchors):
            raise ValueError('Pinned declaration differs: ' + name)
        sources.append({'logical_name': Path(path).name, **span})
        checks.append({'id': 'declaration-' + name, 'symbol': name, 'required_anchor_count': len(anchors), 'passed': True})
    choices = {}
    for name, expected in (('lLabelTypesScene', [0,1,2,3]), ('lFunctionStatusTypesScenes', [0,6,7,5])):
        span = source_span(originals[CHOICES_SOURCE], name, 'public List<DataStore> ' + name + ' =')
        lines = originals[CHOICES_SOURCE].decode('utf-8-sig').splitlines(keepends=True)
        text = ''.join(lines[span['start_line'] - 1:span['end_line']])
        rows = [(label, int(value)) for label, value in re.findall(r'new DataStore\("([^"\\]*)", (\d+)\)', text)]
        if [value for _,value in rows] != expected:
            raise ValueError('Scene choices differ: ' + name)
        choices[name] = [{'name':label,'value':value} for label,value in rows]
        sources.append({'logical_name': Path(CHOICES_SOURCE).name, **span})
        checks.append({'id': 'ordered-' + name, 'ordered_integer_values': expected, 'passed': True})
    span = source_span(originals[CHOICES_SOURCE], 'SceneMacros', 'public List<DataStore> lDualKeyMacroFunctionsScenes =')
    lines = originals[CHOICES_SOURCE].decode('utf-8-sig').splitlines(keepends=True)
    text = ''.join(lines[span['start_line'] - 1:span['end_line']])
    macro_rows = re.findall(r'new DataStore\("([^"\\]*)", "([0-9]+\|[0-9]+)"\)', text)
    if [value for _,value in macro_rows] != ['30|31','26|27','28|29','32|33']:
        raise ValueError('Scene macro choice order differs')
    choices['lDualKeyMacroFunctionsScenes'] = [{'name':name,'value':value} for name,value in macro_rows]
    sources.append({'logical_name': Path(CHOICES_SOURCE).name, **span})
    checks.append({'id':'ordered-source-scene-macros','passed':True})
    return {'format': 'cbus-edlt-scene-widget-control-source-annex-v1',
        'original_inputs': inputs, 'managed_method_spans': methods, 'decompiled_source_symbols': sources,
        'static_checks': checks, 'source_choices': choices,
        'source_contract': {
            'scene_indices': 'SceneData new byte11/12 properties hide, rather than override, base virtual auto-properties. Display type writes preserve raw stored variants and bit7.',
            'cycle_getter': 'Explicit SceneCycle/CanAddScene/CanRemoveScene reads accept raw0..8, return up to9 PPAttribute objects and write255 only after the first invalid slot; generic views never read it.',
            'add': 'Scan only slots0..7; first raw>7 becomes0, later scanned slots255, ninth unchanged. Two Position=List.Count requests remain symbolic; host currency and reflection are unassessed.',
            'delete': 'Null Current or DataSource returns before getter. Otherwise getter then IndexOf current PPAttribute, shift all9 and write final255; negative-index original exception remains refused.',
            'move': 'Explicit nonnull current cell and observed RowCount guard adjacent swaps, followed by exact reset/position requests. No explicit getter occurs in move callbacks.',
            'setup': 'Original snapshots both variants and status text/index, binds scene choices, issues reset requests, restores status index/text. Automatic SelectedValue callbacks and hidden binding reads are not inferred.',
            'status_text': 'Same-name/null guard precedes allocator; retained cached ordinal match precedes capacity, old status reference remains reserved until assignment. Enter-key/Leave and list refresh use the separately pinned ComboBoxStaticText profile.',
            'macro': 'Source fixed4pairs only; left/right property writes precede single-selection notification. Original RightButtonMacrofunctin typo is preserved.',
            'grid': 'Dirty callback requests CommitEdit512, DataError sets Cancel=false, Delete key invokes delete then Handled=true. No pending cell value or host scheduling is invented.'},
        'limits': {'original_instructions_executed': 0, 'framework_instructions_executed':0,
            'original_host_executed':False, 'physical_device_verified':False,
            'implicit_binding_reads_inferred':False, 'currency_first_selection_inferred':False,
            'culture_order_inferred':False, 'unconfigured_native_parent_scene_admitted':False,
            'native_parent_raw_cycle8_admitted':False, 'original_negative_index_exception_reproduced':False},
        'omissions': {'raw_instruction_bytes_published':False, 'vendor_source_text_published':False,
            'original_string_heaps_published':False, 'private_coordinates_published':False}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-root',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    result = recover(args.vendor_root)
    rendered = (json.dumps(result,indent=2,ensure_ascii=False)+'\n').encode('utf-8')
    if args.check:
        if args.output.read_bytes() != rendered:
            raise SystemExit('Scene widget static annex differs')
    else:
        args.output.write_bytes(rendered)
    print(json.dumps({'managed_methods':len(result['managed_method_spans']),
        'source_symbols':len(result['decompiled_source_symbols']),
        'static_checks':len(result['static_checks']), 'sha256':digest(rendered), 'original_instructions_executed':0}))


if __name__ == '__main__':
    main()
