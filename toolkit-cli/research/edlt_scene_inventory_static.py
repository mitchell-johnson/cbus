#!/usr/bin/env python3
"""Recover causal SceneManager inventory facts by static PE/source reads only.

Never load assemblies, execute original instructions, open a Framework host,
contact services or inspect a site project. Public output contains spans/hashes
and bounded facts; proprietary source and instruction bytes remain private.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import capstone
import pefile
from research.edlt_scene_name_static import ManagedImage, source_span, require_order
from research.edlt_scene_selector_static import declaration_span, VENDOR_PINS

PARSER_PINS = {
    'edlt_scene_name_static.py': '7bb4f3137bf6da42524cc512d94fe6c711f28b5a80532d018411777f9f573223',
    'edlt_scene_selector_static.py': 'cc88faa1c43fb801ebcfaf7e891c08d79be80c0fd378734496f0020fe794ce4a',
}
EXE_SHA = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
MAP_SHA = 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
UNIT = 'CBusLogicModel.Units.EDLT.EDLTUnit::'
SCENE = 'CBusLogicModel.Units.EDLT.EDLTScene::'
UI = 'eDLT.Controls.SceneManagerControls.SceneManager::'
NET = 'CBusLogicModel.CBusNetwork::'
APP = 'CBusLogicModel.CBusApplication::'
GROUP = 'CBusLogicModel.CBusObjects.CBusGroup::'
LEVEL = 'CBusLogicModel.CBusObjects.CBusLevel::'
METHODS = {
 'toolkit/app/SharpContainer.dll': ['SharpContainer.SharkUnitDialogFactory::'+x for x in ('CreateUnitDialog','CreateUnitsDialogWithDefault','UpdateDatabase','FrmKeyUnitAddGroupDialogRequest','FrmKeyUnitAddLevelDialogRequest')],
 'toolkit/app/eDLT.dll': [UI+x for x in (
  'scenesBindingSource_CurrentChanged','triggerGroupsBindingSource_CurrentChanged',
  'levelsBindingSource_CurrentChanged','BtnAddTriggerGroupClick','BtnAddActionSelectorClick','BtnPasteClick','BtnClearSceneClick')],
 'toolkit/app/CBusLogicModel.dll': [UNIT+x for x in (
  'AfterLoadPPData','LoadScenes','SaveScenes','BeforeSavePPData','GetSceneStartAddress','ValidateScenes','GetStaticTextIndex','GetUsedStaticText')]
  + [SCENE+x for x in ('get_TriggerGroup','set_TriggerGroup','get_ActionSelector','set_ActionSelector',
   'get_AvailableActionSelectors','get_AvailableTriggerGroups','RefreshDynamicLables','CopyFrom','CheckGroupsAndTrigger','get_SceneName','set_SceneName')]
  + [NET+x for x in ('AddApplicationRequest','AddGroupRequest','AddLevelRequest','GetApplicationByAddress','RefreshData','ReadXmlData')]
  + [APP+x for x in ('GetGroupByAddress','ReadXmlData')]
  + [GROUP+x for x in ('GetLevelByAddress','ReadXmlData','InitialiseGroup')]
  + ['CBusLogicModel.CBusObjects.BaseObjects.CBusBaseObject::LoadXMLData','CBusLogicModel.CBusObjects.BaseObjects.CBusBaseObject::ReadXmlData','CBusLogicModel.GlobalSoftwareParameters::UpdateValues']
  + [LEVEL+x for x in ('InitialiseLevel','ReadXmlData','PopulateDynamicAll')],
}
NATIVE_METHODS = (
 'CIS_TfrmKEYGL5.TfrmKEYGL5.ProjectXMLChanged',
 'CIS_TfrmKEYGL5.TfrmKEYGL5.CreateAndEmbedDialog',
 'SharpContainer_TLB.TSharkUnitDialogFactory.UpdateDatabase',
 'CIS_TfrmKEYGL5.TfrmKEYGL5.AddSharpApplication',
 'CIS_TfrmKEYGL5.TfrmKEYGL5.AddSharpGroup',
 'CIS_TfrmKEYGL5.TfrmKEYGL5.AddSharpLevel',
 'CIS_TCommonCBus.TCBUSApplicationManager.ApplicationByAddress',
 'CIS_TCommonCBus.TCBusGroupManager.GroupByAddress',
 'CIS_TCommonCBus.TLevelManager.FindLevelByAddress',
 'CIS_TCommonCBus.TLevelManager.GetNextAvailableAddress',
 'CIS_TCommonCBus.TLevelManager.GetMaximumPossibleAddress',
 'CIS_TCBusApplicationGUIAgent.TCBusApplicationGUIAgent.AddLevel',
 'CIS_TddLevel.TddLevel.SetValues',
 'CIS_TfrmLevelAssign.TfrmLevelAssign.actOKExecute',
 'CIS_TCBusEDLTCGateAgent.TCBusEDLTCGateAgent.AddSharpLevel',
)
SOURCES = {
 'edlt-decompiled/eDLT/eDLT.Controls.SceneManagerControls/SceneManager.cs': [
  (UI+x,'private void '+x+'(') for x in ('scenesBindingSource_CurrentChanged','triggerGroupsBindingSource_CurrentChanged',
   'levelsBindingSource_CurrentChanged','BtnAddTriggerGroupClick','BtnAddActionSelectorClick','BtnPasteClick','BtnClearSceneClick')],
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTUnit.cs': [
  (UNIT+'AfterLoadPPData','public override void AfterLoadPPData('),
  (UNIT+'LoadScenes','public void LoadScenes('),(UNIT+'SaveScenes','public void SaveScenes('),
  (UNIT+'BeforeSavePPData','protected override void BeforeSavePPData('),
  (UNIT+'GetSceneStartAddress','private int GetSceneStartAddress('),
  (UNIT+'ValidateScenes','public bool ValidateScenes('),(UNIT+'GetStaticTextIndex','public int GetStaticTextIndex('),(UNIT+'GetUsedStaticText','public HashSet<int> GetUsedStaticText(')],
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTScene.cs': [
  (SCENE+x,'public '+typ+' '+x) for x,typ in (
   ('TriggerGroup','int'),('ActionSelector','int'),('AvailableActionSelectors','BindingList<CBusLevel>'),
   ('AvailableTriggerGroups','BindingList<CBusGroup>'),('SceneName','virtual string'))]
   + [(SCENE+'RefreshDynamicLables','public void RefreshDynamicLables('),
      (SCENE+'CopyFrom','public void CopyFrom('),(SCENE+'CheckGroupsAndTrigger','public void CheckGroupsAndTrigger('),
      (SCENE+'.ctor(unit,sceneIndex)','public EDLTScene(EDLTUnit unit, int sceneIndex)')],
 'edlt-decompiled/CBusLogicModel/CBusLogicModel/CBusNetwork.cs': [
  (NET+x,'public '+typ+' '+x+'(') for x,typ in (
   ('AddApplicationRequest','string'),('AddGroupRequest','string'),('AddLevelRequest','string'),
   ('GetApplicationByAddress','CBusApplication'),('RefreshData','void'))]
   + [(NET+'ReadXmlData','public override XmlDocument ReadXmlData(')],
 'edlt-decompiled/CBusLogicModel/CBusLogicModel/CBusApplication.cs': [
  (APP+'GetGroupByAddress','public CBusGroup GetGroupByAddress('),
  (APP+'ReadXmlData','public override XmlDocument ReadXmlData(')],
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.CBusObjects/CBusGroup.cs': [
  (GROUP+'GetLevelByAddress','public CBusLevel GetLevelByAddress('),
  (GROUP+'ReadXmlData','public override XmlDocument ReadXmlData('),
  (GROUP+'InitialiseGroup','private void InitialiseGroup(')],
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.CBusObjects.BaseObjects/CBusBaseObject.cs': [('CBusLogicModel.CBusObjects.BaseObjects.CBusBaseObject::LoadXMLData','public virtual bool LoadXMLData('),('CBusLogicModel.CBusObjects.BaseObjects.CBusBaseObject::ReadXmlData','public virtual XmlDocument ReadXmlData(')],
 'edlt-decompiled/CBusLogicModel/CBusLogicModel/GlobalSoftwareParameters.cs': [('CBusLogicModel.GlobalSoftwareParameters::UpdateValues','public static void UpdateValues(')],
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.CBusObjects/CBusLevel.cs': [
  (LEVEL+'InitialiseLevel','private void InitialiseLevel('),
  (LEVEL+'ReadXmlData','public override XmlDocument ReadXmlData('),
  (LEVEL+'PopulateDynamicAll','public void PopulateDynamicAll(')],
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def native_spans(exe_raw, map_raw):
    if digest(exe_raw)!=EXE_SHA or digest(map_raw)!=MAP_SHA:
        raise ValueError('Original EXE/MAP identity differs')
    pe=pefile.PE(data=exe_raw,fast_load=True)
    if pe.FILE_HEADER.Machine!=0x14c:
        raise ValueError('Expected original x86 image')
    base=pe.OPTIONAL_HEADER.ImageBase
    segments={n:base+next(s.VirtualAddress for s in pe.sections if s.Name.startswith(name))
              for n,name in ((1,b'.text'),(2,b'.itext'))}
    symbols={};by_name={}
    for line in map_raw.decode('ascii').splitlines():
        m=re.fullmatch(r'\s*000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*',line)
        if m:
            address=segments[int(m[1])]+int(m[2],16)
            symbols.setdefault(address,set()).add(m[3]);by_name.setdefault(m[3],address)
    starts=sorted(symbols);decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
    result=[]
    for name in NATIVE_METHODS:
        start=by_name[name];end=starts[starts.index(start)+1]
        if not 0<end-start<65536:raise ValueError('Unbounded native method')
        raw=pe.get_data(start-base,end-start);calls=[]
        for instruction in decoder.disasm(raw,start):
            if instruction.mnemonic=='call' and instruction.op_str.startswith('0x'):
                target=int(instruction.op_str,16)
                calls.append({'address':hex(instruction.address),'target':hex(target),
                              'symbols':sorted(symbols.get(target,()))})
        result.append({'symbol':name,'start':hex(start),'end':hex(end),
                       'bytes':len(raw),'sha256':digest(raw),'direct_calls':calls,'static_decode_only':True})
    return result


def recover(vendor_root, original_app):
    inputs=[];source={};methods=[];decoded={}
    for name,pin in PARSER_PINS.items():
        raw=Path(__file__).with_name(name).read_bytes()
        if digest(raw)!=pin:raise ValueError('Static parser differs: '+name)
        inputs.append({'path':'toolkit-cli/research/'+name,'sha256':pin,'bytes':len(raw),'role':'static-reader'})
    vendor_pins={**VENDOR_PINS,'toolkit/app/SharpContainer.dll':'5cba17be19a783e4b0c1e99025c9556fea605b97003ed6a3e9f3f182fb2c3ed0','edlt-decompiled/CBusLogicModel/CBusLogicModel/GlobalSoftwareParameters.cs':'08a79965131c84e87becd4294218c66737fe9e641ca6bea5728e07c901934b6f'}
    for name,pin in vendor_pins.items():
        if name not in METHODS and name not in SOURCES:continue
        raw=(vendor_root/name).read_bytes()
        if digest(raw)!=pin:raise ValueError('Pinned source differs: '+name)
        source[name]=raw
        inputs.append({'path':name,'sha256':pin,'bytes':len(raw),'role':'original-static-input'})
    for assembly,names in METHODS.items():
        image=ManagedImage(source[assembly])
        if image.runtime!='v4.0.30319':raise ValueError('Managed runtime metadata differs')
        for name in names:
            row=image.method(name);detail=image.instructions(name);decoded[name]=detail
            row.update(assembly=assembly,metadata_runtime=image.runtime,**detail);methods.append(row)
    declarations=[{'path':path,**declaration_span(source[path],name,anchor)}
                  for path,entries in SOURCES.items() for name,anchor in entries]
    checks=[]
    def calls(name,ordered,label):
        require_order([r['symbol'] for r in decoded[name]['calls']],ordered,label)
        checks.append({'id':label,'symbol':name,'ordered_call_suffixes':ordered,'passed':True})
    def constants(name,values,label):
        found=[r['value'] for r in decoded[name]['integer_constants']]
        if any(value not in found for value in values):raise ValueError('Integer anchor differs: '+label)
        checks.append({'id':label,'symbol':name,'integer_anchors':values,'passed':True})
    def absent(name,suffix,label):
        if any(r['symbol'].endswith('::'+suffix) for r in decoded[name]['calls']):raise ValueError('Unexpected call: '+label)
        checks.append({'id':label,'symbol':name,'absent_call_suffix':suffix,'passed':True})
    calls(UNIT+'AfterLoadPPData',['AfterLoadPPData','get_StaticLabels','Clear','get_ValueAsUtf8String','Add','PopulateStaticTextSuggest','LoadScenes','LoadWidgetsFromAttributes'],'static-rows-before-scenes-before-widgets')
    constants(UNIT+'AfterLoadPPData',[64],'all-64-static-rows')
    calls(UNIT+'LoadScenes',['get_Scenes','Clear','GetPPAttribute','GetPPAttribute','get_PriSecApplication','set_PriSecApplication','set_TriggerGroup','GetApplicationByAddress','get_TriggerGroup','GetGroupByAddress','GetLevelByAddress','set_ActionSelector','set_NameIndex','get_Scenes','Add'],'loader-getter-before-scene-append')
    constants(UNIT+'LoadScenes',[8,255,202],'eight-scenes-exact-trigger-application')
    calls(UI+'BtnClearSceneClick',['get_Current','get_Items','get_Count','.ctor','CopyFrom','ResetBindings','EndEdit'],'clear-default-scene-copy-with-explicit-resets')
    calls(UNIT+'SaveScenes',['SetPPAttibuteValue','GetSceneStartAddress','get_CanEdit','get_PriSecApplication','get_Items','get_TriggerGroup','get_ActionSelector','set_ActionSelector','get_ActionSelector','get_NameIndex','SetPPAttibuteValue'],'terminal-getter-before-zero-before-second-getter')
    constants(UNIT+'SaveScenes',[8,-1,0,231],'save-header-count-fallback-and-tail')
    calls(UNIT+'BeforeSavePPData',['BeforeSavePPData','SaveStaticText','SaveScenes'],'terminal-static-before-scenes')
    calls(SCENE+'get_TriggerGroup',['GetApplicationByAddress','GetGroupByAddress','set_TriggerGroup','get_AddressAsInt'],'trigger-default-create-normalize')
    calls(SCENE+'get_ActionSelector',['get_TriggerGroupEditable','GetLevelByAddress','set_ActionSelector','get_AddressAsInt'],'action-getter-create-then-normalize')
    calls(SCENE+'set_ActionSelector',['get_TriggerGroupEditable','GetLevelByAddress','get_AddressAsInt','RefreshDynamicLables','NotifyPropertyChanged'],'action-setter-create-before-label-refresh')
    absent(SCENE+'set_TriggerGroup','RefreshDynamicLables','trigger-setter-no-label-refresh')
    absent(SCENE+'set_TriggerGroup','GetLevelByAddress','trigger-setter-no-action-create')
    calls(SCENE+'get_AvailableActionSelectors',['get_TriggerGroup','GetApplicationByAddress','get_TriggerGroup','GetGroupByAddress','get_Levels'],'available-actions-retains-group-live-list')
    calls(GROUP+'GetLevelByAddress',['get_Levels','AddLevelRequest','GetApplicationByAddress','GetGroupByAddress','get_Levels'],'level-callback-then-exact-refetch')
    constants(GROUP+'GetLevelByAddress',[-1],'nonnegative-level-create-gate')
    calls(GROUP+'ReadXmlData',['ReadXmlData','InitialiseGroup','get_SortModeLevels','Sort','get_Levels','Clear','Add','ResetBindings'],'reload-replaces-level-list-before-sort-add')
    calls(APP+'ReadXmlData',['GetGroupByAddress','ReadXmlData','get_SortModeGroups','Sort','get_Groups','Clear','Add','Add','ResetBindings'],'reload-reuses-groups-and-mutates-list')
    calls(UI+'triggerGroupsBindingSource_CurrentChanged',['Clear','get_AvailableActionSelectors','set_DataSource','Add','get_ActionSelector','RefreshDynamicLables'],'trigger-callback-list-bind-before-action-getter-refresh')
    calls(UI+'BtnAddActionSelectorClick',['get_SelectedItem','get_Address','AddLevelRequest','get_Items','get_Value','set_SelectedItem','ResetCurrentItem','ResetBindings','ResetBindings'],'add-action-selected-trigger-request-before-selection-and-resets')
    calls(UI+'BtnAddTriggerGroupClick',['AddGroupRequest','get_Items','get_Value','set_SelectedIndex','get_CurrencyManager','set_Position','WriteValue','ResetCurrentItem','ResetBindings','ResetBindings'],'add-trigger-request-before-explicit-write-and-resets')
    absent(UI+'BtnAddActionSelectorClick','WriteValue','add-action-no-explicit-write')
    absent(UI+'levelsBindingSource_CurrentChanged','ReadValue','level-current-write-only')
    constants(LEVEL+'InitialiseLevel',[4],'created-level-four-default-variants')
    calls(LEVEL+'ReadXmlData',['ReadXmlData','InitialiseLevel','get_TagsDLT','ResetBindings','PopulateDynamicAll'],'level-load-default-variants-before-dynamic-all')
    calls('SharpContainer.SharkUnitDialogFactory::CreateUnitsDialogWithDefault',['GetNetwork','RefreshData','.ctor','add_NetworkRefreshEvent','FrmKeyUnitAddGroupDialogRequest','add_addGroupEvent','FrmKeyUnitAddLevelDialogRequest','add_addLevelEvent'],'bridge-binds-network-refresh-and-add-delegates')
    calls('SharpContainer.SharkUnitDialogFactory::UpdateDatabase',['get_WaitCursor','set_Cursor','Invoke','get_Default','set_Cursor'],'bridge-update-invokes-before-default-cursor')
    calls('CBusLogicModel.CBusObjects.BaseObjects.CBusBaseObject::LoadXMLData',['DBGetXML','ReadXmlData'],'whole-network-xml-read-virtual-dispatch')
    calls('CBusLogicModel.CBusObjects.BaseObjects.CBusBaseObject::ReadXmlData',['UpdateValues','get_DisplayAddressValue','get_Address','PadLeft','get_DisplayHex','get_AddressAsInt','ToString','PadLeft','Trim','get_TagName','set_FormattedDisplay'],'display-flags-before-rendered-tag-name')
    calls('CBusLogicModel.GlobalSoftwareParameters::UpdateValues',['OpenSubKey','GetValue','set_DisplayHex','GetValue','set_DisplayAddressValue','GetValue','set_SortModeApplications','GetValue','set_SortModeGroups','GetValue','set_SortModeLevels'],'five-dword-preferences-source-order')
    calls(NET+'ReadXmlData',['GetApplicationByAddress','ReadXmlData','get_SortModeApplications','Sort','get_Applications','Clear','Add','ResetBindings'],'whole-network-existing-applications-reused')
    calls(NET+'RefreshData',['LoadXMLData'],'network-refresh-loads-native-xml')
    calls(GROUP+'InitialiseGroup',['get_TagsDLT','Clear','.ctor','Add','.ctor','set_Levels'],'group-initializer-replaces-levels')
    exe=(original_app/'CBusToolkit.exe').read_bytes();mp=(original_app/'CBusToolkit.map').read_bytes()
    native=native_spans(exe,mp)
    project=next(r for r in native if r['symbol'].endswith('.ProjectXMLChanged'))
    if not any('SharpContainer_TLB.TSharkUnitDialogFactory.UpdateDatabase' in r['symbols'] for r in project['direct_calls']):
        raise ValueError('Original bridge UpdateDatabase call differs')
    pe=pefile.PE(data=exe,fast_load=True)
    callback_assignment=pe.get_data(0x11c48ad-pe.OPTIONAL_HEADER.ImageBase,10)
    if callback_assignment!=bytes.fromhex('c780d80000005c4b1c01'):
        raise ValueError('Original embedded-form project XML callback registration differs')
    checks.append({'id':'native-embedded-form-registers-project-xml-callback','symbol':'CIS_TfrmKEYGL5.TfrmKEYGL5.CreateAndEmbedDialog','instruction_address':'0x11c48ad','registered_callback':'CIS_TfrmKEYGL5.TfrmKEYGL5.ProjectXMLChanged','passed':True})
    checks.append({'id':'native-project-xml-callback-dispatches-managed-update','symbol':project['symbol'],'direct_call_target':'SharpContainer_TLB.TSharkUnitDialogFactory.UpdateDatabase','passed':True})
    sharp=ManagedImage(source['toolkit/app/SharpContainer.dll'])
    update=sharp.method('SharpContainer.SharkUnitDialogFactory::UpdateDatabase')
    start=update['file_offset']+update['header_bytes']
    fields=[]
    for offset in (1,67):
        raw=sharp.data[start+offset:start+offset+5]
        if raw!=bytes.fromhex('7b19000004'):raise ValueError('Exact UpdateDatabase event field differs')
        name=sharp.string(sharp.row(4,25)[1])
        if name!='NetworkRefreshEvent':raise ValueError('NetworkRefreshEvent field differs')
        fields.append({'il_offset':offset,'field_token':'0x04000019','field':name})
    checks.append({'id':'managed-update-uses-retained-network-refresh-event','symbol':update['symbol'],'exact_field_references':fields,'passed':True})
    inputs.extend([{'path':'CBusToolkit.exe','sha256':EXE_SHA,'bytes':len(exe),'role':'original-static-input'},
                   {'path':'CBusToolkit.map','sha256':MAP_SHA,'bytes':len(mp),'role':'original-static-input'}])
    return {'format':'cbus-edlt-scene-inventory-source-annex-v1','original_inputs':inputs,
       'managed_method_spans':methods,'decompiled_source_symbols':declarations,
       'native_method_spans':native,'static_checks':checks,
       'display_profile':{'format':'cbus-edlt-display-preferences-v1','registry_key_present':True,'values':{'DisplayHexAddress':0,'DisplayAddressValue':0,'SortModeApplications':0,'SortModeGroups':1,'SortModeLevels':1},'scope':'Explicit supplied DWORD profile, not read from host. Bare TagName display; source-declared address sorts for refreshed groups/levels.'},
       'source_contract':{
        'phase_order':'AfterLoadPPData loads64 raw labels then8 Scenes before Widgets. Every stored non-FF pointer resolves exact trigger and level before adding scene; controls follow this initial loader.',
        'trigger_getter':'Exact default-create group lookup; setter stores unequal raw field/notifications only. AvailableActionSelectors performs trigger getter then returns that group.Levels object.',
        'action_getter':'Nonnegative retained action resolves exact Level through fresh bContinue guard and native owner callback; valid existing getter does not refresh labels. Setter resolves current scene Trigger group and explicitly refreshes.',
        'action_add':'Button requests blank Level for actual selected Trigger combo object; returned decimal is matched against actual action Items and sets SelectedItem. No explicit WriteValue occurs in that handler. Qualified accepted-dialog lowering is separately modeled; divergent current/selected target refuses.',
        'trigger_add':'Button requests blank group. Nonnull return matches Items, sets selection/currency and explicitly writes existing binding. Cancel creates nothing and skips this branch. Three explicit Reset calls do not establish host callbacks.',
        'getter_vs_add':'Getter names Group N and Action Selector N; requested address can be255. Dialog first free0..254 and seeds Trigger Group N/Level N. Accepted results and names follow separately retained original native Add receipts.',
        'bridge_refresh':'Native ProjectXMLChanged calls TSharkUnitDialogFactory.UpdateDatabase. Managed creation binds Network.RefreshData to NetworkRefreshEvent; UpdateDatabase invokes that retained event, RefreshData performs LoadXMLData/ReadXmlData. Whole Network FullPath XML is loaded; existing Application/Group objects reused by address, all loaded Groups replace Levels and reconstruct Level/DynamicAll objects. Existing scene CurrentDynamicLabels retains old references until explicit refresh. Callback registration and call bodies are static facts; actual project-event schedule/reentrancy is not executed.',
        'level_collection':'AvailableActionSelectors returns the actual same Levels list, not a copied usable list. Original XML ReadXmlData calls InitialiseGroup, replacing Levels, then clears/repopulates its NEW list after observed sort preference; existing Group objects are reused by address. An old bound Levels list can remain stale. Creating a new level does not source-prove appending to an old bound Levels generation. Consuming new rows requires a separately explicit rebind in the admitted profile; original notification/schedule equivalence remains unverified.',
        'terminal_save':'SaveScenes writes SceneCount8 and pointer starts, then each header. Evaluate trigger getter then ActionSelector; if-1 call setter0 then getter again. Disabled trigger255 leaves raw action unchanged and serializes getter-1 asFF. Fallback0 belongs only to terminal save unless an earlier explicit getter/setter requires it.',
        'initial_label_epochs':'LoadScenes creates/resolves each slot then invokes ActionSelector setter/Refresh before NameIndex andsceneappend. A later slot getter canrefreshwholeNetwork, replacingearlier Levels/DynamicAll; earlierScene.CurrentDynamicLabels retainsoldDataStore references. Capture per-slot initial label epoch; do not borrow finalpostloader labels for earlier slots. LaterWidget/defaultgetter refresh cannot silently rewrite earlier Scene label owners.',
        'label_ownership':'Create-level initializer establishes4 blank default-language variants; explicit refresh copies DynamicAll in order with group/level createfalse. Trigger setter and valid getter preserve prior labels; no pixels inferred.',
        'copy':'CopyFrom reads source Trigger/Action getters, assigns destination private fields and copies items, retaining target dynamic-label list until explicit refresh; no host selection callbacks inferred.',
        'name':'SceneName callback uses retained static row allocator; pending text is control state. Explicit selector binding and Name bound target must agree; history cannot infer auto commit on rebind.',
       },
       'historical_dependencies':[
        {'path':'research/fixtures/edlt-scene-selector-source-annex.json','sha256':'688e514c8addc1f24ff166c8ca5558a7fba40219c5d7a4429a649276155fc1d0','role':'immutable-framework-declarations-and-source-profile'},
        {'path':'research/fixtures/edlt-scene-add-dialog-evidence.json','sha256':'d676b237c1bdb51a92d7e802f8da5edba9f471233cc91d046a0b48802d57c781','role':'immutable-original-add-allocation-name-and-cancel-evidence'},
        {'path':'research/fixtures/edlt-scene-metadata-evidence.json','sha256':'1625f9e578d805f3c23c0ca25af117a3f5f793f723fa646e07f57c08d56814bc','role':'immutable-original-exact-create-names-and-field-evidence'},
       ],
       'limits':{'original_instructions_executed':0,'framework_instructions_executed':0,
        'host_gui_executed':False,'physical_device_verified':False,'native_original_combined_form_verified':False,
        'automatic_notification_schedule_verified':False,'automatic_currency_selection_verified':False,
        'modal_callback_schedule_verified':False,'original_live_append_order_verified':False,
        'culture_sort_verified':False,'queued_begin_invoke_verified':False,'private_vendor_code_published':False,
        'historical_evidence_rewritten':False}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-root',type=Path,required=True)
    parser.add_argument('--original-app',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args();result=recover(args.vendor_root,args.original_app)
    raw=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode()
    if args.check:
        if args.output.read_bytes()!=raw:raise SystemExit('Scene inventory annex differs')
    else:args.output.write_bytes(raw)
    print(json.dumps({'managed_methods':len(result['managed_method_spans']),
                     'native_methods':len(result['native_method_spans']),
                     'source_symbols':len(result['decompiled_source_symbols']),
                     'checks':len(result['static_checks']),'sha256':digest(raw),'original_instructions_executed':0}))


if __name__=='__main__':main()
