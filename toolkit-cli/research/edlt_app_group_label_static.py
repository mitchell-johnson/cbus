#!/usr/bin/env python3
"""Read-only source annex for six AppGroup label/status adapters.

Retain exact managed/decompiled span hashes and named contracts. No vendor
instructions, source text, private paths or original execution are published.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
from research.edlt_scene_name_static import ManagedImage, require_order, source_span
from research.edlt_label_control_static import recover as recover_inherited

PINS = {'toolkit/app/eDLT.dll': '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3', 'toolkit/app/CBusLogicModel.dll': '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.WidgetData/EnableData.cs': '78df65a569d583224679e349cc75586398f7e23cb0814ef015c095cfe665ec6e', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.WidgetData/TimerData.cs': 'a80a4ce82a7ca31350bfd31a05e37e10253d38d6efc978352937717c8e7ffcf0', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.EDLT.WidgetData/ShutterRelayData.cs': '2059ac05ce1f2aaa440045286623b97f9ba98807c37b8fcd2534ec4729bb7543', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.EDLT.WidgetData/MultiLevelData.cs': '205764dd5198037e07fd3efa543eb37332cba825fc71db6a8e16fcdb3dfb52da', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.EDLT.WidgetData/FanControllerData.cs': '78fefc573eb5f6d3ce43a4f6c2fb8ac8f70ccb33065b28c997b2a61aff20e24a', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.EDLT.WidgetData/RCPData.cs': '5a18876d33b2733c188c612e7b64bb1a3dec59257b555da70c2f638ad0741b95', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.WidgetData.BaseObjects/StatusLabelTypeData.cs': '58f98c4469b4af7c90df4afe48c72e54b9b94c6683a655b80085b851784d891e', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.WidgetData.BaseObjects/StatusLabelAppGroupData.cs': 'd0116aad0fe28fef6101ba36a719cbe08aa562036cb47ce86e71cd20470c8b6a', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/CommonConstants.cs': '98e20887cf973205eaa42e621f0ee21ee5b9367aac1553f88c75b86e16d39020', 'edlt-decompiled/eDLT/eDLT.WidgetPanels/EnableWidget.cs': '865f44b341e8e550ac165be00278166f53f46c318d7b817af70f8f8579fb1fc4', 'edlt-decompiled/eDLT/eDLT.WidgetPanels/TimerWidget.cs': '63789f46c488a6b7114813cebc8e914859de6131b1e9b21ec8c6c95d97ee1697', 'edlt-decompiled/eDLT/eDLT.WidgetPanels/ShutterRelayWidget.cs': '0a95a9fea56509be71bb3ae2201bfd6442cb328768a936dee017b3e246d3f2f9', 'edlt-decompiled/eDLT/eDLT.WidgetPanels/MultiLevelWidget2.cs': 'a44dfc636c500d102b1dc54d55d3e2e6e9cbf413b10dc8569ba9bedc483de73c', 'edlt-decompiled/eDLT/eDLT/FanControlWidget.cs': '03be2124a6e2ea48074e167bd76a32b3943c71f65fda51743aa76dccdafe9148', 'edlt-decompiled/eDLT/eDLT.WidgetPanels/RCAWidget.cs': '40b99765bb4b3a94683b370d9d62b22e88a0eb3da5382b289c1f75ea877e44a3', 'edlt-decompiled/eDLT/eDLT.WidgetPanels.baseWidgePanels/BaseStatusLabel.cs': 'e9e186ef63c85e9ea2c4cf0003e44792c460852d133fbba811796a92bc08fc81', 'edlt-decompiled/eDLT/eDLT.WidgetPanels.baseWidgePanels/BaseAppGroupLabel.cs': '1a3f588c66349ea47e7f9a2379bb812e45926038dd68d874f657e18de45fe8e4', 'edlt-decompiled/eDLT/eDLT.WidgetPanels.baseWidgePanels/BaseDualKey.cs': 'b101d15bf449d72b223c24974d731f064cba2bacba49fac2bbc17949bd46f8d3', 'edlt-decompiled/eDLT/eDLT.Controls/ComboImageTagDLT.cs': 'b23f564aa2052981646b7eec3c34a61f06f55cca701f3a3dc215046035c65c5b', 'edlt-decompiled/eDLT/eDLT.Controls/ComboBoxStaticText.cs': 'e6daf32a886e18d67cb20a51d7e483b21af4e470f9f177d8877f7e34d73588c4'}
MODEL_ROOT='edlt-decompiled/CBusLogicModel/'
UI_ROOT='edlt-decompiled/eDLT/'
FAMILIES=(
 ('enable','CBusLogicModel.Units.EDLT.WidgetData','EnableData',14,11,12,True,[0,3,10,1,2,5]),
 ('timer','CBusLogicModel.Units.EDLT.WidgetData','TimerData',5,17,18,False,[0,10,5,4]),
 ('shutter','CBusLogicModel.EDLT.WidgetData','ShutterRelayData',3,10,11,False,[0,3,10,1,2,5]),
 ('multilevel','CBusLogicModel.EDLT.WidgetData','MultiLevelData',16,9,10,False,[]),
 ('fan','CBusLogicModel.EDLT.WidgetData','FanControllerData',4,9,10,False,[]),
 ('room-courtesy','CBusLogicModel.EDLT.WidgetData','RCPData',15,8,9,False,[0,10,5]),
)


def digest(raw):return hashlib.sha256(raw).hexdigest()


def recover(vendor_root):
    inherited=recover_inherited(vendor_root)
    originals={}
    inputs=[]
    for logical,expected in PINS.items():
        raw=(vendor_root/logical).read_bytes()
        if digest(raw)!=expected:raise ValueError('Pinned AppGroup input differs: '+Path(logical).name)
        originals[logical]=raw
        inputs.append({'logical_name':Path(logical).name,'sha256':expected,'bytes':len(raw),'role':'original-static-input'})
    assemblies={name:ManagedImage(originals['toolkit/app/'+name]) for name in ('CBusLogicModel.dll','eDLT.dll')}
    if any(image.runtime!='v4.0.30319' for image in assemblies.values()):raise ValueError('Managed runtime differs')
    methods,sources,checks=[],[],[]
    omissions=0

    def method(symbol,assembly='CBusLogicModel.dll'):
        image=assemblies[assembly]
        entries=image.methods.get(symbol,[])
        if not entries:raise ValueError('Pinned method missing: '+symbol)
        details=[]
        try:
            for ordinal,entry in enumerate(entries):
                image.methods[symbol]=[entry]
                detail=image.instructions(symbol)
                for call in detail['calls']:
                    token=int(call['token'],16)
                    if token>>24==43:
                        coded=image.row(43,token&0xffffff)[0]
                        call['symbol']=image.member(((10 if coded&1 else 6)<<24)|(coded>>1))
                methods.append(dict(image.method(symbol),assembly=assembly,
                    metadata_runtime=image.runtime,overload_ordinal=ordinal,**detail))
                details.append(detail)
        finally:image.methods[symbol]=entries
        return details[0]

    def declaration(path,symbol,anchor,required=(),absent=()):
        nonlocal omissions
        span=source_span(originals[path],symbol,anchor)
        lines=originals[path].decode('utf-8-sig').splitlines(keepends=True)
        text=''.join(lines[span['start_line']-1:span['end_line']])
        if any(value not in text for value in required) or any(value in text for value in absent):
            raise ValueError('Pinned declaration contract differs: '+symbol)
        omissions+=len(re.findall(r'(?:[A-Za-z]:\\|/(?:Users|private|Volumes)/)',text))
        sources.append({'logical_name':Path(path).name,**span})
        checks.append({'id':'declaration-'+symbol,'required_anchor_count':len(required),'absent_anchor_count':len(absent),'passed':True})
        return text

    profiles=[]
    for family,namespace,name,kind,label,status,conditional,choices in FAMILIES:
        source=MODEL_ROOT+namespace+'/'+name+'.cs'
        actual_name='MultiLevelData' if family=='fan' else name
        actual_ns='CBusLogicModel.EDLT.WidgetData' if family=='fan' else namespace
        if family!='fan':
            for target,offset in (('Label',label),('Status',status)):
                getter=method(actual_ns+'.'+actual_name+'::get_'+target+'ValueIndex')
                integers=[row['value'] for row in getter['integer_constants']]
                if any(value not in integers for value in (offset,4,64,0)):
                    raise ValueError('Getter field/clamp contract differs: '+family+target)
                checks.append({'id':family+'-'+target.lower()+'-field-and-getter-bounds','integer_values':[offset,4,64,0],'passed':True})
                setter=method(actual_ns+'.'+actual_name+'::set_'+target+'ValueIndex')
                require_order([row['symbol'] for row in setter['calls']],['set_ValueAsInt','get_Dynamic'+('Label' if target=='Label' else 'Function')+'Selected','set_'+target+'DisplayType'],family+target+'setter')
                checks.append({'id':family+'-'+target.lower()+'-write-before-dynamic-resolution','passed':True})
                declaration(source,family+'-'+target+'ValueIndex','public override int '+target+'ValueIndex',
                    ('WidgetByte('+str(offset)+')','DoNotFireNotifyPropertyChanged = true;','DoNotFireNotifyPropertyChanged = false;'),
                    () if conditional else ('if (WidgetByte('+str(offset)+').ValueAsInt != value)',))
                if conditional:
                    declaration(source,family+'-'+target+'ValueIndex-unchanged-guard','public override int '+target+'ValueIndex',
                        ('if (WidgetByte('+str(offset)+').ValueAsInt != value)',))
            method(namespace+'.'+name+'::GetUsedStaticText')
        method(namespace+'.'+name+'::SetToDefault')
        declaration(source,family+'-defaults','public override void SetToDefault()',('base.SetToDefault();',))
        profiles.append({'family':family,'source_model':namespace+'.'+name,'widget_type':kind,
            'label_offset':label,'status_offset':status,'unchanged_index_resolution':not conditional,
            'label_type_choice_values':[0,10,3],'status_type_choice_values':choices,
            'static_status_offsets':{'status':10,'status-low':11,'status-medium':12,'status-high':13} if family in ('fan','multilevel') else {}})
    enable=FAMILIES[0]
    method(enable[1]+'.'+enable[2]+'::GetSelectedApplication')
    declaration(MODEL_ROOT+enable[1]+'/'+enable[2]+'.cs','enable-fixed-application','public override CBusApplication GetSelectedApplication()',('GetApplicationByAddress(203)',))
    multi=MODEL_ROOT+'CBusLogicModel.EDLT.WidgetData/MultiLevelData.cs'
    for prefix,offset in (('Low',11),('Med',12),('High',13)):
        for accessor in ('get','set'):method('CBusLogicModel.EDLT.WidgetData.MultiLevelData::'+accessor+'_'+prefix+'StatusTextIndex')
        declaration(multi,prefix+'StatusTextIndex','public int '+prefix+'StatusTextIndex',('WidgetByte('+str(offset)+')',))
        for accessor in ('get','set'):method('CBusLogicModel.EDLT.WidgetData.MultiLevelData::'+accessor+'_'+prefix+'StatusText')
        declaration(multi,prefix+'StatusText','public virtual string '+prefix+'StatusText',('GetStaticTextIndex(value)',prefix+'StatusTextIndex < 0 || '+prefix+'StatusTextIndex > 63','if (value != null)'))
    declaration(multi,'MultiLevel-used-static','public override HashSet<int> GetUsedStaticText()',('usedStaticText.Add(LowStatusTextIndex);','usedStaticText.Add(MedStatusTextIndex);','usedStaticText.Add(HighStatusTextIndex);'))
    fan=MODEL_ROOT+'CBusLogicModel.EDLT.WidgetData/FanControllerData.cs'
    if 'class FanControllerData : MultiLevelData' not in originals[fan].decode('utf-8-sig'):raise ValueError('Fan model inheritance differs')
    checks.append({'id':'fan-inherits-exact-multilevel-index-and-text-properties','passed':True})
    choice_path=MODEL_ROOT+'CBusLogicModel.Utilities/CommonConstants.cs'
    for name,expected in (('lLabelTypes',[0,10,3]),('lFunctionStatusTypes',[0,3,10,1,2,5]),
                          ('lFunctionStatusTypesTimer',[0,10,5,4]),('lFunctionStatusTypesRCP',[0,10,5])):
        text=declaration(choice_path,'choices-'+name,'public List<DataStore> '+name+' =')
        actual=[int(value) for value in re.findall(r'new DataStore\("[^"\\]*", (\d+)\)',text)]
        if actual!=expected:raise ValueError('Ordered panel choices differ: '+name)
        checks.append({'id':'ordered-'+name,'values':actual,'passed':True})
    panel_root=UI_ROOT+'eDLT.WidgetPanels/'
    for panel in ('EnableWidget','TimerWidget','ShutterRelayWidget','RCAWidget','MultiLevelWidget2'):
        method('eDLT.WidgetPanels.'+panel+'::.ctor','eDLT.dll')
        method('eDLT.WidgetPanels.'+panel+'::InitializeComponent','eDLT.dll')
    method('eDLT.FanControlWidget::.ctor','eDLT.dll')
    base_status=UI_ROOT+'eDLT.WidgetPanels.baseWidgePanels/BaseStatusLabel.cs'
    declaration(base_status,'generic-panel-status','private void InitializeComponent()',('"FunctionStatusTypes"','"StatusDisplayType"','"LabelDisplayType"'))
    method('eDLT.WidgetPanels.TimerWidget::SetUpDataSource','eDLT.dll')
    declaration(panel_root+'TimerWidget.cs','timer-panel-status','public override void SetUpDataSource()',('commonConstants.FunctionStatusTypesTime',))
    declaration(panel_root+'RCAWidget.cs','rcp-panel-status','private void InitializeComponent()',('"FunctionStatusTypesRCP"',))
    shutter=originals[panel_root+'ShutterRelayWidget.cs'].decode('utf-8-sig')
    if 'FunctionStatusTypesShutter' in shutter:raise ValueError('Unexpected Shutter status choice override')
    checks.append({'id':'shutter-does-not-bind-unused-shutter-status-list','source_profile':'inherited generic BaseStatusLabel choices','passed':True})
    declaration(panel_root+'MultiLevelWidget2.cs','four-static-status-bindings','private void InitializeComponent()',('"StatusValueText"','"LowStatusText"','"MedStatusText"','"HighStatusText"','new ComboBoxStaticText()'),('"StatusDisplayType"',))
    if 'class FanControlWidget : MultiLevelWidget2' not in originals[UI_ROOT+'eDLT/FanControlWidget.cs'].decode('utf-8-sig'):raise ValueError('Fan panel inheritance differs')
    checks.append({'id':'fan-panel-inherits-four-static-status-controls','passed':True})
    for type_name,namespace in (('BaseAppGroupLabel','eDLT.WidgetPanels.baseWidgePanels'),('BaseDualKey','eDLT.WidgetPanels.baseWidgePanels')):
        method(namespace+'.'+type_name+'::.ctor','eDLT.dll')
    static_path=UI_ROOT+'eDLT.Controls/ComboBoxStaticText.cs'
    for method_name in ('.ctor','ComboBoxStaticText_Leave','ComboImageTagDLT_PreviewKeyDown','ComboImageTagDLT_SelectedIndexChanged','DataManager_ListChanged'):
        method('eDLT.Controls.ComboBoxStaticText::'+method_name,'eDLT.dll')
    declaration(static_path,'static-key-and-leave','private void ComboImageTagDLT_PreviewKeyDown(',('(int)e.KeyCode == 13','WriteValue();','ReadValue();'))
    return {'format':'cbus-edlt-app-group-label-source-annex-v1','original_inputs':inputs,
        'managed_method_spans':methods,'decompiled_source_symbols':sources,'static_checks':checks,
        'family_profiles':profiles,'inherited_control_source':{'format':inherited['format'],
          'canonical_sha256':digest(json.dumps(inherited,sort_keys=True,separators=(',',':')).encode()),
          'managed_spans':len(inherited['managed_method_spans']),'source_spans':len(inherited['decompiled_source_symbols']),
          'checks':len(inherited['static_checks']),'role':'existing Lighting-independent base properties and ComboImageTagDLT callbacks'},
        'source_contract':{'group_rows':'Current SelectedGroup.DynamicAll is read at the causal post-ordinary widget position. Enable chooses application203; unassigned/null group has empty choices.',
          'static_status':'Fan/MultiLevel expose Off/Low/Medium/High ComboBoxStaticText; no status type chooser. Low/Medium/High raw fields remain used references independently of visibility.',
          'index_setters':'Enable conditional unchanged-index guard on both fields; Timer/Shutter/MultiLevel/Fan/RCP assign and recompute every dynamic index assignment.',
          'type_properties':'Inherited source semantic type recursion and masks preserve bit7 and opposite nibble. Source notification intent only.',
          'callback_profile':'Enter event is explicit Enter-key shorthand, never focus Enter. All callbacks are explicitly supplied; end of events never silently commits pending text.'},
        'omissions':{'local_coordinate_fields_published':0,'private_coordinate_occurrences_omitted':omissions,
          'raw_instruction_bytes_published':False,'decompiled_source_text_published':False,'original_literal_heaps_published':False},
        'limits':{'original_instructions_executed':0,'framework_instructions_executed':0,
          'automatic_event_schedule_verified':False,'culture_sorted_suggestion_ordinals_verified':False,
          'graphics_rendering_verified':False,'original_host_executed':False,'physical_device_verified':False}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--check',action='store_true')
    options=parser.parse_args()
    document=recover(options.vendor_root)
    if options.check:
        if json.loads(options.output.read_text())!=document:raise SystemExit('Static AppGroup annex differs')
    else:options.output.write_text(json.dumps(document,indent=2)+'\n')
    print(json.dumps({'managed_spans':len(document['managed_method_spans']),
      'source_spans':len(document['decompiled_source_symbols']),'checks':len(document['static_checks']),
      'original_instructions_executed':0}))


if __name__=='__main__':main()
