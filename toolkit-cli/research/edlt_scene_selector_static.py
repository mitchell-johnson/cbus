#!/usr/bin/env python3
"""Scene selector static annex; read PE/ECMA bytes and source declarations only.

No original, CLR, GUI, framework callback, vendor service or hardware executes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from research.edlt_scene_name_static import ManagedImage, source_span, require_order

VENDOR_PINS = {'toolkit/app/eDLT.dll': '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3',
 'toolkit/app/CBusLogicModel.dll': '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823',
 'edlt-decompiled/eDLT/eDLT.Controls.SceneManagerControls/SceneManager.cs': 'c2aa9a75cf7e128eba6cab952ddbdd45cb7e363b4128dc96ff15bd90adf9d72c',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTScene.cs': '91fb4aa7438f3ba911062902f022d9bbdc196bc6ce809ecf29cb2ff9bd514774',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTUnit.cs': '641f5abc1c3762cd86a0c4b18bc125424a39017a3d78d6edfa4e1e2964af62b2',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units/CBusBaseUnit.cs': '4f0468941222c6696db5836a32fc0b70d18fcf704ea8fe6dd0c2d709a3842487',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel/CBusNetwork.cs': 'ddd65e5d34d94f3b0468f0db5a8468c0b6b5cdc50b8a49ca27b9f7331000d39c',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel/CBusApplication.cs': '669554fea6b53c01a2d0d0c1d7cf8c89cd76d68af0b7d2b11f3bb73a6bfe5933',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.CBusObjects/CBusGroup.cs': '882ef659aa8114ee8d5a9f51c7d7d14cde7322f7da83a33853c9c6f49a3e7aa2',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.CBusObjects/CBusLevel.cs': '4578b91fd17a688e99cdba16d7c9c1dcc983a88f156caca88e8b55a9ad8194e1',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/DataStore.cs': 'd60cd2371e221a54774e6b8c35ce631975d0c2491e6b9e053d700810831f4f2b',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.CBusObjects.BaseObjects/CBusBaseObject.cs': 'b49db12edd5be47e4c1ad362a8ea62c41fe84107d768f6bd0d5bb8c5b523b99d'}
METHODS = {'toolkit/app/eDLT.dll': ['eDLT.Controls.SceneManagerControls.SceneManager::InitializeComponent',
                          'eDLT.Controls.SceneManagerControls.SceneManager::scenesBindingSource_CurrentChanged',
                          'eDLT.Controls.SceneManagerControls.SceneManager::triggerGroupsBindingSource_CurrentChanged',
                          'eDLT.Controls.SceneManagerControls.SceneManager::levelsBindingSource_CurrentChanged',
                          'eDLT.Controls.SceneManagerControls.SceneManager::BtnAddTriggerGroupClick',
                          'eDLT.Controls.SceneManagerControls.SceneManager::BtnAddActionSelectorClick',
                          'eDLT.Controls.SceneManagerControls.SceneManager::BtnPasteClick',
                          'eDLT.Controls.SceneManagerControls.SceneManager::BtnClearSceneClick',
                          'eDLT.Controls.SceneManagerControls.SceneManager::btnNewGroup_Click',
                          'eDLT.Controls.SceneManagerControls.SceneManager::btnEditDynamicLabel_Click'],
 'toolkit/app/CBusLogicModel.dll': ['CBusLogicModel.Units.EDLT.EDLTScene::get_PriSecApplication',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::set_PriSecApplication',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::get_ApplicationName',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::get_TriggerGroup',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::set_TriggerGroup',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::get_TriggerGroupName',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::get_TriggerGroupEditable',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::get_ActionSelector',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::set_ActionSelector',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::get_ActionSelectorName',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::get_ActionSelectorEditable',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::get_AvailableTriggerGroups',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::get_AvailableActionSelectors',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::get_CurrentDynamicLabels',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::set_CurrentDynamicLabels',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::RefreshDynamicLables',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::get_LabelValueIndex',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::set_LabelValueIndex',
                                    'CBusLogicModel.Units.EDLT.EDLTScene::get_AvailableGroups',
                                    'CBusLogicModel.Units.EDLT.EDLTUnit::get_TriggerGroups',
                                    'CBusLogicModel.Units.CBusBaseUnit::PopulatePrimarySecondaryApplication',
                                    'CBusLogicModel.CBusNetwork::GetApplicationByAddress',
                                    'CBusLogicModel.CBusApplication::GetGroupByAddress',
                                    'CBusLogicModel.CBusObjects.CBusGroup::GetLevelByAddress']}

FRAMEWORK_COMMIT = '44845c0667b7d737c1f8a4821ff6bc16e21912f8'
FRAMEWORK_PINS = {
    'DataSourceUpdateMode.xml': '143bcc5b4500cf5199996440a5bb5709545e90d784d12ebfe3edda3f92a2c557',
    'Binding.xml': '572de5269e375fbb6cbbb363d2c9612163c11f1983a5d4378da76e904dab2d34',
    'ListControl.xml': '9878ba0c89fb49cb2752447865b1009b64e0d3627ed5da5bfd1be04c7d2161d6',
}
PARSER_PIN = '7bb4f3137bf6da42524cc512d94fe6c711f28b5a80532d018411777f9f573223'
UI = 'eDLT.Controls.SceneManagerControls.SceneManager::'
SCENE = 'CBusLogicModel.Units.EDLT.EDLTScene::'
SOURCE_UI = 'edlt-decompiled/eDLT/eDLT.Controls.SceneManagerControls/SceneManager.cs'
SOURCE_SCENE = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTScene.cs'
SOURCE_UNIT = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTUnit.cs'
SOURCE_BASE = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units/CBusBaseUnit.cs'
SOURCE_OBJECT = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.CBusObjects.BaseObjects/CBusBaseObject.cs'
SOURCE_DATA = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/DataStore.cs'
SOURCE_LEVEL = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.CBusObjects/CBusLevel.cs'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def framework_member(raw, name):
    text = raw.decode('utf8')
    start = text.index('<Member MemberName="' + name + '">')
    end = text.index('</Member>', start) + len('</Member>')
    fragment = text[start:end].encode()
    element = ET.fromstring(fragment)
    versions = sorted(set(element.findall('./AssemblyInfo/AssemblyVersion')[i].text
                          for i in range(len(element.findall('./AssemblyInfo/AssemblyVersion')))))
    if '4.0.0.0' not in versions:
        raise ValueError('Primary declaration lacks Framework assembly4: ' + name)
    signatures = [x.attrib['Value'] for x in element.findall('./MemberSignature')
                  if x.attrib.get('Language') == 'ILAsm']
    return {'member': name, 'start_line': text.count('\n', 0, start) + 1,
            'end_line': text.count('\n', 0, end) + 1, 'utf8_bytes': len(fragment),
            'sha256': digest(fragment), 'assembly_versions': versions,
            'enum_value': element.findtext('MemberValue'), 'il_declarations': signatures,
            'scope': 'Pinned primary API declaration, not host Framework implementation or execution.'}


def declaration_span(raw, symbol, anchor):
    """Bound expression-bodied declarations without borrowing the next body."""
    text = raw.decode('utf-8-sig')
    positions = [match.start() for match in re.finditer(re.escape(anchor), text)]
    if len(positions) != 1:
        raise ValueError('Source declaration anchor must be unique: ' + symbol)
    start = positions[0]
    tail = text[start:]
    arrow, opening = tail.find('=>'), tail.find('{')
    if 0 <= arrow < opening:
        end = text.index(';', start + arrow) + 1
        fragment = text[start:end].encode('utf8')
        return {'symbol': symbol, 'start_line': text.count('\n', 0, start) + 1,
                'end_line': text.count('\n', 0, end) + 1, 'utf8_bytes': len(fragment),
                'sha256': digest(fragment), 'hash_scope': 'Exact UTF8 expression declaration; no source copied.'}
    return source_span(raw, symbol, anchor)


def recover(vendor_root, framework_root):
    parser = Path(__file__).with_name('edlt_scene_name_static.py')
    if digest(parser.read_bytes()) != PARSER_PIN:
        raise ValueError('Static PE/source parser pin differs')
    inputs = [{'path': 'toolkit-cli/research/edlt_scene_name_static.py',
               'sha256': PARSER_PIN, 'bytes': len(parser.read_bytes()), 'role': 'static-parser'}]
    vendor, framework = {}, {}
    for name, expected in VENDOR_PINS.items():
        raw = (vendor_root / name).read_bytes()
        if digest(raw) != expected:
            raise ValueError('Pinned original static source differs: ' + name)
        vendor[name] = raw
        inputs.append({'path': name, 'sha256': expected, 'bytes': len(raw), 'role': 'original-static-input'})
    for name, expected in FRAMEWORK_PINS.items():
        raw = (framework_root / name).read_bytes()
        if digest(raw) != expected:
            raise ValueError('Pinned primary API declaration differs: ' + name)
        framework[name] = raw
        inputs.append({'path': 'xml/System.Windows.Forms/' + name, 'sha256': expected,
                       'bytes': len(raw), 'role': 'primary-framework-api-declaration',
                       'url': 'https://raw.githubusercontent.com/dotnet/dotnet-api-docs/' +
                              FRAMEWORK_COMMIT + '/xml/System.Windows.Forms/' + name})
    methods, decoded = [], {}
    for assembly, symbols in METHODS.items():
        image = ManagedImage(vendor[assembly])
        if image.runtime != 'v4.0.30319':
            raise ValueError('Original metadata runtime differs')
        for symbol in symbols:
            method = image.method(symbol)
            detail = image.instructions(symbol)
            method.update(assembly=assembly, metadata_runtime=image.runtime, **detail)
            methods.append(method)
            decoded[symbol] = detail
    checks = []
    def calls(symbol, parts, label):
        require_order([row['symbol'] for row in decoded[symbol]['calls']], parts, label)
        checks.append({'id': label, 'symbol': symbol, 'ordered_call_suffixes': parts, 'passed': True})
    def constants(symbol, values, label):
        actual = [row['value'] for row in decoded[symbol]['integer_constants']]
        if any(value not in actual for value in values):
            raise ValueError('Static integer anchor differs: ' + label)
        checks.append({'id': label, 'symbol': symbol, 'integer_anchors': values, 'passed': True})
    calls(UI+'scenesBindingSource_CurrentChanged', ['get_Current', 'set_Enabled', 'get_Current',
        'Clear', 'get_AvailableActionSelectors', 'set_DataSource', 'Add', 'Clear',
        'get_CurrentDynamicLabels', 'set_DataSource', 'Add', 'Clear', 'Add'], 'scene-current-enable-before-typed-rebind')
    calls(UI+'triggerGroupsBindingSource_CurrentChanged', ['get_Current', 'Clear',
        'get_AvailableActionSelectors', 'set_DataSource', 'Add', 'get_ActionSelector',
        'RefreshDynamicLables'], 'trigger-current-getter-before-refresh')
    calls(UI+'levelsBindingSource_CurrentChanged', ['get_DataBindings', 'get_Item', 'WriteValue'], 'levels-current-write-only')
    if any('ReadValue' in row['symbol'] for row in decoded[UI+'levelsBindingSource_CurrentChanged']['calls']):
        raise ValueError('Levels callback unexpectedly reads')
    checks.append({'id': 'levels-current-no-read', 'symbol': UI+'levelsBindingSource_CurrentChanged', 'absent_call_suffix': 'ReadValue', 'passed': True})
    calls(SCENE+'get_TriggerGroup', ['GetApplicationByAddress', 'GetGroupByAddress', 'set_TriggerGroup'], 'trigger-getter-normalization')
    constants(SCENE+'get_TriggerGroup', [202, 255], 'trigger-getter-application-and-null-value')
    calls(SCENE+'get_ActionSelector', ['get_TriggerGroupEditable', 'GetLevelByAddress', 'set_ActionSelector'], 'action-getter-normalization')
    constants(SCENE+'get_ActionSelector', [-1], 'action-no-selection')
    calls(SCENE+'set_ActionSelector', ['get_TriggerGroupEditable', 'GetLevelByAddress',
        'get_AddressAsInt', 'RefreshDynamicLables', 'NotifyPropertyChanged', 'NotifyPropertyChanged'], 'action-setter-resolve-refresh-notify')
    calls(SCENE+'get_AvailableActionSelectors', ['get_TriggerGroup', 'GetApplicationByAddress',
        'get_TriggerGroup', 'GetGroupByAddress', 'get_Levels'], 'actual-level-list-after-trigger-getter')
    constants(SCENE+'get_AvailableActionSelectors', [202, 255], 'actual-level-list-unused-gate')
    calls(SCENE+'RefreshDynamicLables', ['get_TriggerGroup', 'get_CurrentDynamicLabels',
        'Clear', 'GetApplicationByAddress', 'GetGroupByAddress', 'GetLevelByAddress',
        'get_DynamicAll', 'Add'], 'refresh-clears-before-actual-dynamic-list')
    constants(SCENE+'RefreshDynamicLables', [0, 202, 255], 'refresh-bounds-and-false-create')
    calls('CBusLogicModel.Units.EDLT.EDLTUnit::get_TriggerGroups', ['GetApplicationByAddress', 'get_Groups'], 'unit-actual-trigger-groups')
    calls('CBusLogicModel.Units.CBusBaseUnit::PopulatePrimarySecondaryApplication',
        ['set_RaiseListChangedEvents', 'Clear', 'get_PrimaryApplication', 'get_FormattedDisplay',
         'Add', 'get_SecondaryApplication', 'get_FormattedDisplay', 'Add', 'set_RaiseListChangedEvents'], 'primary-then-secondary-list')
    constants('CBusLogicModel.Units.CBusBaseUnit::PopulatePrimarySecondaryApplication', [0, 1, 255], 'application-selector-values-and-secondary-gate')
    constants(UI+'scenesBindingSource_CurrentChanged', [1, 2], 'action-label-auto-and-name-manual-modes')
    sources = []
    def source(path, symbol, anchor):
        row = declaration_span(vendor[path], symbol, anchor)
        sources.append({'path': path, **row})
    for symbol in ('InitializeComponent','scenesBindingSource_CurrentChanged',
        'triggerGroupsBindingSource_CurrentChanged','levelsBindingSource_CurrentChanged',
        'BtnAddTriggerGroupClick','BtnAddActionSelectorClick','BtnPasteClick',
        'BtnClearSceneClick','btnNewGroup_Click','btnEditDynamicLabel_Click'):
        prefix = 'private void '
        source(SOURCE_UI, symbol, prefix + symbol + '(')
    for name, kind in [('PriSecApplication','int'),('ApplicationName','string'),('TriggerGroup','int'),
        ('TriggerGroupName','string'),('TriggerGroupEditable','bool'),('ActionSelector','int'),
        ('ActionSelectorName','string'),('ActionSelectorEditable','bool'),('LabelValueIndex','int'),
        ('AvailableTriggerGroups','BindingList<CBusGroup>'),('AvailableActionSelectors','BindingList<CBusLevel>'),
        ('CurrentDynamicLabels','BindingList<DataStore>'),('AvailableGroups','List<CBusGroup>')]:
        source(SOURCE_SCENE, name, 'public '+kind+' '+name)
    source(SOURCE_SCENE, 'RefreshDynamicLables', 'public void RefreshDynamicLables(')
    source(SOURCE_UNIT, 'TriggerGroups', 'public BindingList<CBusGroup> TriggerGroups')
    source(SOURCE_UNIT, 'LoadScenes', 'public void LoadScenes(')
    source(SOURCE_UNIT, 'SaveScenes', 'public void SaveScenes(')
    source(SOURCE_BASE, 'PopulatePrimarySecondaryApplication', 'public void PopulatePrimarySecondaryApplication(')
    source(SOURCE_OBJECT, 'Address', 'public string Address\n')
    source(SOURCE_OBJECT, 'AddressAsInt', 'public int AddressAsInt\n')
    source(SOURCE_DATA, 'ValueAsInt', 'public int ValueAsInt\n')
    source(SOURCE_DATA, 'FormattedDisplay', 'public string FormattedDisplay\n')
    source(SOURCE_LEVEL, 'PopulateDynamicAll', 'public void PopulateDynamicAll(')
    for path, symbol, anchor in [
        ('edlt-decompiled/CBusLogicModel/CBusLogicModel/CBusNetwork.cs','GetApplicationByAddress','public CBusApplication GetApplicationByAddress('),
        ('edlt-decompiled/CBusLogicModel/CBusLogicModel/CBusApplication.cs','GetGroupByAddress','public CBusGroup GetGroupByAddress('),
        ('edlt-decompiled/CBusLogicModel/CBusLogicModel.CBusObjects/CBusGroup.cs','GetLevelByAddress','public CBusLevel GetLevelByAddress(')]:
        source(path, symbol, anchor)
    declarations = []
    for path, names in [('DataSourceUpdateMode.xml',['OnValidation','OnPropertyChanged','Never']),
                        ('Binding.xml',['WriteValue','ReadValue']),
                        ('ListControl.xml',['SelectedValue','SelectedIndex'])]:
        for name in names:
            declarations.append({'path':'xml/System.Windows.Forms/'+path, **framework_member(framework[path],name)})
    enum = {row['member']: row['enum_value'] for row in declarations if row['enum_value'] is not None}
    if enum != {'OnValidation':'0','OnPropertyChanged':'1','Never':'2'}:
        raise ValueError('Primary enum values differ')
    return {'format':'cbus-edlt-scene-selector-source-annex-v1','original_inputs':inputs,
        'managed_method_spans':methods,'decompiled_source_symbols':sources,
        'framework_api_declarations':declarations,'static_checks':checks,
        'source_contract':{
            'binding_profile':'net4-explicit-scene-selector-callbacks',
            'application_list':'Primary selector0 then enabled secondary selector1. Names prefix(P)/(S) plus observed application display; secondary255 omitted.',
            'trigger_list':'EDLTUnit.TriggerGroups returns actual application202.Groups in source list order; no synthetic255 object.',
            'action_list':'AvailableActionSelectors consumes TriggerGroup getter;255 returns an empty list, otherwise actual group.Levels order.',
            'scene_current':'All enable flags use Current!=null before type check. Only an EDLTScene clears/rebinds action, dynamic-label and name. Null/non-scene currents retain prior binding targets; explicit public profile admits EDLTScene/null only.',
            'trigger_current':'For EDLTScene:clear action bindings, evaluate available list, assign DataSource, direct ActionSelector binding, evaluate ActionSelector getter, refresh dynamic labels.',
            'levels_current':'Existing SelectedValue binding WriteValue only, including a stale binding while controls disabled; no ReadValue and no current/Enabled check.',
            'property_writes':'Trigger setter only stores unequal trigger and notifies three properties; no explicit refresh. Action setter checks TriggerGroupEditable, resolves level/defaultcreate, stores address or-1, refreshes, then notifies. Disabled action setter leaves retained raw action and labels unchanged.',
            'refresh':'Clear labels first;255/invalid action/missing dependencies yield empty. Group and level lookups explicitly createfalse, application getter keeps source defaultcreate. Present DynamicAll rows are retained in order.',
            'label_index':'Source setter stores integer with no validation. Public selected-index profile separately bounds observed selection-1 or0..3 against complete label rows, not generalized UI conversion.',
            'identities':'Address aliases DataStore.Value and AddressAsInt/ValueAsInt parse the same normal admitted numeric address. Exact ordinal source-list position and object identity disambiguate duplicate names.',
            'getter_creation':'Defaultcreate=true lookup helpers can call native refresh/create loops. Pure model consumes explicit facts; existing outer resolver owns guarded auto-creation, not an invented empty/default lookup.',
            'output_group_identity':'Changing primary/secondary only changes selector/notification; existing Items keep original CBusGroup references. AvailableGroups excludes255 and exact used group objects, not same address in another application.',
            'serialization':'Eight source scenes serialize5-byte header+3-byte items. Action getter precedes attempted setter0 for-1, then second getter. Empty disabled scene action remains-1 and serializesFF; label index/dynamic list are not serialized. SceneCount8; final bucket232 bytes.',
        },
        'framework_profile':{'name':'net4-explicit-binding-declarations','primary_repository_commit':FRAMEWORK_COMMIT,
            'declaration_assembly_version':'4.0.0.0','update_modes':enum,
            'api_scope':'Pinned Microsoft API declaration metadata only. Historical ReferenceSource implementation files were unavailable; no host Framework implementation, null parsing, currency position or event scheduling inferred.'},
        'limits':{'original_instructions_executed':0,'framework_instructions_executed':0,'host_gui_executed':False,
            'original_host_framework_binary_verified':False,'physical_device_verified':False,
            'automatic_initial_population_verified':False,'null_selected_value_conversion_verified':False,
            'automatic_currency_selection_verified':False,'property_changed_schedule_verified':False,
            'implicit_scene_name_refresh_verified':False,'culture_sort_verified':False,
            'queued_begin_invoke_verified':False,'modal_defaults_verified':False,
            'image_pixels_verified':False,'historical_fixtures_rewritten':False,'private_vendor_code_published':False}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-root',type=Path,required=True)
    parser.add_argument('--framework-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args();result=recover(args.vendor_root,args.framework_root)
    rendered=(json.dumps(result,indent=2,ensure_ascii=False)+'\n').encode()
    if args.check:
        if args.output.read_bytes()!=rendered:raise SystemExit('Selector annex differs')
    else:args.output.write_bytes(rendered)
    print(json.dumps({'managed_methods':len(result['managed_method_spans']),
        'source_symbols':len(result['decompiled_source_symbols']),
        'framework_declarations':len(result['framework_api_declarations']),
        'static_checks':len(result['static_checks']),'original_instructions_executed':0,
        'sha256':digest(rendered)}))


if __name__=='__main__':main()
