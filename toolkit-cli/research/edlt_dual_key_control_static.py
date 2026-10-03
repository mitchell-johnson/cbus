#!/usr/bin/env python3
"""Static dual-key source annex. Reads PE/ECMA metadata and source bytes only."""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from pathlib import Path

PINS = {'toolkit/app/eDLT.dll': '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3', 'toolkit/app/CBusLogicModel.dll': '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.WidgetData/TimerData.cs': 'a80a4ce82a7ca31350bfd31a05e37e10253d38d6efc978352937717c8e7ffcf0', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.EDLT.WidgetData/ShutterRelayData.cs': '2059ac05ce1f2aaa440045286623b97f9ba98807c37b8fcd2534ec4729bb7543', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.EDLT.WidgetData/RCPData.cs': '5a18876d33b2733c188c612e7b64bb1a3dec59257b555da70c2f638ad0741b95', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.WidgetData.BaseObjects/AppGroupButtonFunctionsData.cs': '344f29ff4b77767cadfb439dd3525e40cc042cf914b877acd4fe32417fa006b2', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.WidgetData.BaseObjects/StatusLabelAppGroupData.cs': 'd0116aad0fe28fef6101ba36a719cbe08aa562036cb47ce86e71cd20470c8b6a', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.WidgetData.BaseObjects/StatusLabelTypeData.cs': '58f98c4469b4af7c90df4afe48c72e54b9b94c6683a655b80085b851784d891e', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.WidgetData.BaseObjects/WidgetBaseData.cs': '9848f4b6eac5360fc9396887be2ea8aace7fa0e5fdc43cab2ece66597a086189', 'edlt-decompiled/CBusLogicModel/CBusLogicModel/PPAttribute.cs': '6c057abce7de8793501e34b326d862a9bbc2c2e32ed6c7b7ace796b0ad29e9cb', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.Utilities/MacroFunctionTypes.cs': '828d9b0a68076478b8514764a65b2374ee4f7cd236c088548484a2f533d176d7', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.Utilities/MicroFunctions.cs': '39f871176be4185088281e075e8801878b11aeda0891be77d0d5033da5c9681e', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.Utilities/MacroFunction.cs': '6d4aecce2becc6f15d9111a9679d910d134773ec5b6fdf38194ead785c3ef9ae', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/CommonConstants.cs': '98e20887cf973205eaa42e621f0ee21ee5b9367aac1553f88c75b86e16d39020', 'edlt-decompiled/eDLT/eDLT.WidgetPanels/TimerWidget.cs': '63789f46c488a6b7114813cebc8e914859de6131b1e9b21ec8c6c95d97ee1697', 'edlt-decompiled/eDLT/eDLT.WidgetPanels/ShutterRelayWidget.cs': '0a95a9fea56509be71bb3ae2201bfd6442cb328768a936dee017b3e246d3f2f9', 'edlt-decompiled/eDLT/eDLT.WidgetPanels/RCAWidget.cs': '40b99765bb4b3a94683b370d9d62b22e88a0eb3da5382b289c1f75ea877e44a3', 'edlt-decompiled/eDLT/eDLT.Controls/TimerSelector.cs': 'ec540e43843fcc87e2cc048428b921c8d22fb12b5c702b2c4c5eff177254bcc9', 'edlt-decompiled/eDLT/eDLT.Controls/LevelControl.cs': 'ce4d52534a374e1b2bd76421e597cd24df011d11e1c6d775c07de77e9ca55e5d', 'edlt-decompiled/eDLT/eDLT.WidgetPanels.baseWidgePanels/BaseDualKey.cs': 'b101d15bf449d72b223c24974d731f064cba2bacba49fac2bbc17949bd46f8d3', 'edlt-decompiled/eDLT/eDLT.WidgetPanels.baseWidgePanels/BaseAppGroupLabel.cs': '1a3f588c66349ea47e7f9a2379bb812e45926038dd68d874f657e18de45fe8e4', 'edlt-decompiled/eDLT/eDLT.WidgetPanels.baseWidgePanels/BaseStatusLabel.cs': 'e9e186ef63c85e9ea2c4cf0003e44792c460852d133fbba811796a92bc08fc81', 'edlt-decompiled/eDLT/eDLT.WidgetPanels.baseWidgePanels/BaseWidget.cs': 'e2ecee24752731238d7901b8e2a20e7482e2e8225e76ad0afa660cc602b407d8'}
PARSER_PIN = '7bb4f3137bf6da42524cc512d94fe6c711f28b5a80532d018411777f9f573223'

def sha(raw): return hashlib.sha256(raw).hexdigest()

def recover(repo, vendor):
    parser = repo / 'toolkit-cli/research/edlt_scene_name_static.py'
    if sha(parser.read_bytes()) != PARSER_PIN: raise ValueError('Static parser pin differs')
    sys.path.insert(0, str(repo/'toolkit-cli'))
    from research.edlt_scene_name_static import ManagedImage, source_span, require_order
    original, inputs = {}, [{'logical_name':'managed-static-parser','sha256':PARSER_PIN,'bytes':parser.stat().st_size,'role':'repository-static-parser'}]
    for name, expected in PINS.items():
        raw = (vendor/name).read_bytes()
        if sha(raw) != expected: raise ValueError('Static input pin differs: '+Path(name).name)
        original[name] = raw
        inputs.append({'logical_name':Path(name).name,'sha256':expected,'bytes':len(raw),'role':'original-static-input'})
    images = {n:ManagedImage(original['toolkit/app/'+n]) for n in ('eDLT.dll','CBusLogicModel.dll')}
    if any(image.runtime != 'v4.0.30319' for image in images.values()):raise ValueError('CLR metadata differs')
    methods, decoded, declarations, checks = [], {}, [], []
    owned = ('TimerData','ShutterRelayData','RCPData','AppGroupButtonFunctionsData',
             'TimerWidget','ShutterRelayWidget','RCAWidget','TimerSelector','LevelControl')
    dependencies = {'WidgetBaseData':('WidgetByte','GetIntValueFromTwoBytes','SetIntValueToTwoBytes','SetForcedValues','GetUsedStaticText'),
        'StatusLabelAppGroupData':('get_StatusIconOnIndex','set_StatusIconOnIndex','get_StatusIconOffIndex','set_StatusIconOffIndex','SetToDefault'),
        'PPAttribute':('get_ValueAsInt','set_ValueAsInt'),
        'MacroFunctionTypes':('.cctor',),'MicroFunctions':('.cctor',),'MacroFunction':None,
        'BaseDualKey':('.ctor','InitializeComponent','SetUpDataSource'),
        'BaseAppGroupLabel':('.ctor','InitializeComponent','SetUpDataSource'),
        'BaseStatusLabel':('.ctor','InitializeComponent','SetUpDataSource'),
        'BaseWidget':('.ctor','SetWidgetData','SetUpDataSource'),
        'CommonConstants':('.ctor','get_ShutterRelayKeyFunctions','get_DualKeyMacroFunctionTimer','get_DualKeyMacroFunctionsRCP','get_RampRates','get_KeyColours')}
    for assembly, image in images.items():
        for symbol in sorted(image.methods):
            owner, member = symbol.split('::')
            short = owner.rsplit('.',1)[-1].split('+')[0]
            take = short in owned and member != 'Dispose'
            take |= short in dependencies and (dependencies[short] is None or member in dependencies[short])
            if not take:continue
            entries=image.methods[symbol]
            for ordinal, entry in enumerate(entries):
                try:
                    image.methods[symbol]=[entry]
                    detail=image.instructions(symbol)
                    for call in detail['calls']:
                        token=int(call['token'],16)
                        if token>>24==43:
                            coded=image.row(43,token&0xffffff)[0]
                            call['symbol']=image.member(((10 if coded&1 else 6)<<24)|(coded>>1))
                    # No original string values/compiler coordinates are exported.
                    strings=detail.pop('string_literals',[])
                    decoded[symbol]=detail
                    methods.append({**image.method(symbol),'assembly':assembly,'overload_ordinal':ordinal,
                        'method_flags':f'0x{entry[1][2]:04x}', 'method_virtual':bool(entry[1][2]&0x40),
                        'method_new_slot':bool(entry[1][2]&0x100), 'metadata_runtime':image.runtime,
                        'omitted_string_literal_count':len(strings),**detail})
                finally:image.methods[symbol]=entries
    relationships=[]
    for assembly,image in images.items():
        for index,name in image.types.items():
            if name.rsplit('.',1)[-1] not in ('TimerData','ShutterRelayData','RCPData','AppGroupButtonFunctionsData','TimerWidget','ShutterRelayWidget','RCAWidget'):
                continue
            coded=image.row(2,index)[3];tag,base=coded&3,coded>>2
            if tag==0:parent=image.types[base]
            elif tag==1:
                row=image.row(1,base);parent=image.string(row[2])+'.'+image.string(row[1])
            else:raise ValueError('Unexpected base-type metadata')
            relationships.append({'type':name,'type_token':f'0x{0x02000000|index:08x}','assembly':assembly,'base_type':parent})
    for name in PINS:
        if not name.endswith('.cs'):continue
        raw=original[name]; lines=raw.decode('utf-8-sig').splitlines(keepends=True)
        for i,line in enumerate(lines):
            anchor=line.strip()
            if not re.match(r'(public|protected|private|internal)\s+',anchor) or ' class ' in anchor or ' enum ' in anchor:continue
            if anchor.endswith(';') or '=>' in anchor or ('{ get;' in anchor):
                body=line.rstrip('\r\n').encode()
                declarations.append({'logical_name':Path(name).name,'start_line':i+1,'end_line':i+1,'sha256':sha(body),'utf8_bytes':len(body),'hash_scope':'Exact UTF8 declaration line; no text exported'})
            elif '(' in anchor or re.match(r'(public|protected|private) (override |virtual )?(int|bool|string) \w+$',anchor):
                span=source_span(raw,Path(name).stem+'.'+anchor.split('(')[0].split()[-1],anchor+'\n')
                declarations.append({'logical_name':Path(name).name,**span})
    def symbol(short, member):
        choices=[s for s in decoded if s.rsplit('.',1)[-1]==short+'::'+member]
        if len(choices)!=1:raise ValueError('Missing/ambiguous method '+short+'.'+member)
        return choices[0]
    def order(short, member, calls, id):
        name=symbol(short,member)
        require_order([r['symbol'] for r in decoded[name]['calls']],calls,id)
        checks.append({'id':id,'symbol':name,'ordered_call_suffixes':calls,'passed':True,
            'qualification':'Linear static call occurrence order; branch/dispatch guards are separately pinned. No runtime trace.'})
    def constants(short, member, vals, id):
        name=symbol(short,member);actual=[r['value'] for r in decoded[name]['integer_constants']]
        if any(v not in actual for v in vals):raise ValueError('Missing constants '+id)
        checks.append({'id':id,'symbol':name,'required_integer_constants':vals,'passed':True})
    def declaration(file, member, anchor, fragments, id):
        name=next(n for n in original if Path(n).name==file)
        span=source_span(original[name],member,anchor)
        lines=original[name].decode('utf-8-sig').splitlines(keepends=True)
        body=''.join(lines[span['start_line']-1:span['end_line']])
        if any(v not in body for v in fragments):raise ValueError('Declaration check differs '+id)
        checks.append({'id':id,'declaration':{'logical_name':file,**span},'required_anchor_count':len(fragments),'passed':True})
    constants('PPAttribute','set_ValueAsInt',[255,0],'byte-setter-clamps-before-storage')
    constants('TimerData','get_ExpiryLevel',[15,14],'expiry-high15-low14-signed-helper')
    order('TimerData','set_ExpiryLevel',['SetIntValueToTwoBytes','NotifyPropertyChanged'],'expiry-write-before-notify')
    constants('WidgetBaseData','SetIntValueToTwoBytes',[255,8],'two-byte-helper-masks-high-and-low')
    order('TimerData','set_TimerValue',['set_ValueAsInt','set_ValueAsInt'],'timer-high-before-low')
    constants('TimerData','set_TimerValue',[13,8,12,255],'timer-high-shift-not-mask')
    order('TimerData','SetForcedValues',['SetForcedValues','get_TargetLevel','set_TargetLevel'],'timer-force-only-terminal-explicit')
    constants('TimerData','SetForcedValues',[1],'timer-zero-to-one-forced')
    order('RCPData','set_StatusIconIndex',['set_StatusIconOffIndex','set_StatusIconOnIndex'],'rcp-coupled-icon-off-before-on')
    order('ShutterRelayData','set_LeftButtonMacrofunction',['get_LeftButtonMacrofunction','set_LeftButtonMacrofunction','SetKeyFunctionDefaults'],'shutter-same-left-still-input-notify')
    for prop in ('TargetLevel1','TargetLevel2'):
        constants('ShutterRelayData','get_'+prop,[6,248],'shutter-'+prop+'-getter-clamps')
        order('ShutterRelayData','set_'+prop,['set_'+prop,'set_'+prop,'set_ValueAsInt'],'shutter-'+prop+'-recursive-inner-before-outer')
    declaration('ShutterRelayData.cs','shutter-handler','private void this_PropertyChanged(',['RightButtonMacrofunctin','NotifyPropertyChanged("TargetLevel1Editable")'],'source-typo-target1-only')
    order('AppGroupButtonFunctionsData','get_DualButtonMacrofunction',['get_LeftButtonMacrofunction','get_RightButtonMacrofunction','SetKeyFunctionDefaults'],'macro-getter-effects-explicit')
    order('AppGroupButtonFunctionsData','SetKeyFunctionDefaults',['set_RampRateEditable','set_TargetLevel1Editable','set_TargetLevel2Editable','set_OffsetEditable','NotifyPropertyChanged'],'editable-defaults-order')
    for prop in ('RampRateEditable','TargetLevel1Editable','TargetLevel2Editable','OffsetEditable'):
        declaration('AppGroupButtonFunctionsData.cs',prop,'public '+('virtual ' if prop.startswith('Target') else '')+'bool '+prop,['!= value','if (_'],'false-to-true-'+prop+'-default-only')
    mouse_symbol = symbol('LevelControl', 'trackbar_MouseDown')
    mouse_method = images['eDLT.dll'].method(mouse_symbol)
    start = mouse_method['file_offset'] + mouse_method['header_bytes']
    mouse_il = images['eDLT.dll'].data[start:start + mouse_method['code_bytes']]
    # Exact instruction boundaries: ldloc.1, ldc.i4.7, sub, stloc.1.
    # A checked subtraction would use sub.ovf/sub.ovf.un instead of 0x59.
    if mouse_il[17:21] != bytes((0x07, 0x1d, 0x59, 0x0b)):
        raise ValueError('MouseDown signed Int32 subtraction differs')
    checks.append({'id':'mouse-down-int32-unchecked-sub-before-double',
        'symbol':mouse_symbol,'il_offset':19,'opcode':'0x59','instruction':'sub',
        'left_operand':'Int32 local','right_operand':7,'passed':True,
        'qualification':'Unchecked signed32 subtraction precedes conversion to double; no host event delivery inferred.'})
    order('LevelControl','set_Value',['OnValueChanged','WriteValue','UpdateControls'],'level-value-explicit-write-before-update')
    order('LevelControl','SetValueNoChanged',['set_Value'],'level-suppressed-event-keeps-value-setter-write')
    constants('LevelControl','SetValueNoChanged',[0,1],'level-static-suppression-clear-then-restore')
    order('LevelControl','UpdateControls',['SetLabel','get_Value','set_Value','set_Value'],'level-update-recursive-numeric-bound')
    order('LevelControl','trackbar_Validating',['WriteValue','WriteValue','WriteValue'],'validation-self-lower-higher-order-unlinked-profile')
    order('TimerSelector','get_TimerValue',['get_Value','get_TimeOfDay','get_TotalSeconds'],'timer-timeofday-seconds')
    declaration('TimerSelector.cs','selector-clamp','public int TimerValue',['if (value > MaxValue)','if (value < MinValue)','MinDate.AddSeconds(value)'],'timer-value-clamp-max-then-min')
    declaration('TimerWidget.cs','timer-target-bounds','private void InitializeComponent()',['levelControl2.MinLevel = 1','timerSelector1.MaxValue = 64800'],'actual-target-min1-and-timer18hours')
    declaration('ShutterRelayWidget.cs','shutter-control-bounds','private void InitializeComponent()',['levelControl1.MinLevel = 6','levelControl1.MaxLevel = 248','levelControl2.MinLevel = 6','levelControl2.MaxLevel = 248'],'both-shutter-controls-have-six-248-setvalue-bounds')
    for cls in ('TimerData','ShutterRelayData','RCPData'):
        for prop in ('LabelValueIndex','StatusValueIndex'):
            constants(cls,'get_'+prop,[4,64],cls+'-'+prop+'-virtual-bound-no-write')
    # Whole declaration roster, including inherited panels; default update mode stays explicit None.
    bindings=[]
    for name in PINS:
        if Path(name).name not in ('TimerWidget.cs','ShutterRelayWidget.cs','RCAWidget.cs','BaseDualKey.cs','BaseAppGroupLabel.cs','BaseStatusLabel.cs'):continue
        for no,line in enumerate(original[name].decode('utf-8-sig').splitlines(),1):
            m=re.search(r'new Binding\("([^"]*)", \(object\)([A-Za-z_0-9]+), "([^"]*)", (true|false)(?:, \(DataSourceUpdateMode\)([0-9]+))?\)',line)
            if m:
                prop,owner,target,fmt,mode=m.groups()
                control=re.search(r'\(\(Control\)([^)]+)\)',line)
                bindings.append({'panel':Path(name).stem,'line':no,'control':control.group(1) if control else None,
                    'control_property':prop,'source':owner,'source_property':target,'formatting_enabled':fmt=='true',
                    'explicit_update_mode':None if mode is None else int(mode),'line_sha256':sha(line.encode()),
                    'declaration_scope':'Constructor InitializeComponent or explicit SetUp replacement; not a callback trace'})
    rca=original[next(n for n in original if Path(n).name=='RCAWidget.cs')].decode('utf-8-sig')
    for no,line in enumerate(rca.splitlines(),1):
        if 'DataBindings.Add("SelectedValue"' in line:
            if '"KeyMacrofunction", true, (DataSourceUpdateMode)1' not in line:raise ValueError('RCA binding overload differs')
            bindings.append({'panel':'RCAWidget','line':no,'control':'cmbLeftMacroFunction',
                'control_property':'SelectedValue','source':'rCPDataBindingSource.DataSource',
                'source_property':'KeyMacrofunction','formatting_enabled':True,'explicit_update_mode':1,
                'line_sha256':sha(line.encode()),'declaration_scope':'Explicit SetUpDataSource string-overload replacement; not a host callback'})
    macro_source=original[next(n for n in original if Path(n).name=='MacroFunctionTypes.cs')].decode('utf-8-sig')
    micro_source=original[next(n for n in original if Path(n).name=='MicroFunctions.cs')].decode('utf-8-sig')
    micro={n:re.findall(r'InputValues\.([A-Za-z0-9_]+)',b) for n,b in re.findall(r'public static List<InputValues> (\w+) = new List<InputValues>\s*([\s\S]*?);',micro_source)}
    macro_profiles=[]
    for key,body in re.findall(r'new KeyValuePair<int, MacroFunction>\((\d+), new MacroFunction\(([^)]*)\)\)',macro_source):
        lists=[v.strip().removeprefix('MicroFunctions.') for v in body.split(',')]
        if len(lists)!=4:raise ValueError('Macro needs exact four source micro lists')
        macro_inputs=list(dict.fromkeys(x for name in lists for x in micro[name]))
        macro_profiles.append({'macro':int(key),'four_input_lists':lists,'inputs':macro_inputs})
    choices={}
    common=original[next(n for n in original if Path(n).name=='CommonConstants.cs')]
    for name in ('lRampRate','lShutterRelayKeyFunction','lDualKeyMacroFunctionsRCP','lDualKeyMacroFunctionsTimer','LKeyColours'):
        text=common.decode('utf-8-sig');anchor='public List<DataStore> '+name+' ='
        if anchor not in text:continue
        span=source_span(common,name,anchor)
        lines=text.splitlines(keepends=True);body=''.join(lines[span['start_line']-1:span['end_line']])
        rows=re.findall(r'new DataStore\("([^"]*)", ("[^"]*"|[0-9]+)\)',body)
        choices[name]=[{'name':label,'value':json.loads(val)} for label,val in rows]
    return {'format':'cbus-edlt-dual-key-control-source-annex-v1','original_inputs':inputs,
        'managed_method_spans':methods,'metadata_type_relationships':relationships,'macro_input_profiles':macro_profiles,
        'decompiled_source_symbols':declarations,'static_checks':checks,
        'ordered_panel_bindings':bindings,'source_choices':choices,
        'scope':{'families':['timer','shutter','room-courtesy'],'numeric_profile':'Unlinked LevelControl, no Group selected; explicit signed32 inputs, no host parsing',
            'timer_profile':'Explicit integer seconds/time-of-day,0..64800 display; no DateTime event-scheduling inference',
            'omitted_dispose_bodies':True,'original_executed':False,'framework_executed':False,'physical_verified':False,
            'implicit_host_dispatch':False,'full_parity':False},
        'remaining':['Host Binding parse/culture/currency/event schedule','Linked LevelControl and populated Group modal Add/Edit','Implicit DateTimePicker recursion/notifications','Hidden macro/off-icon input is not an offered callback','Rendering and hardware acceptance']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--vendor-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--check',action='store_true');args=p.parse_args()
    repo=Path(__file__).resolve().parents[2]
    result=recover(repo,args.vendor_root)
    raw=(json.dumps(result,sort_keys=True,indent=2)+'\n').encode()
    if args.check:
        if args.output.read_bytes()!=raw:raise ValueError('Saved source annex differs')
    else:args.output.write_bytes(raw)
    print(json.dumps({'method_spans':len(result['managed_method_spans']),'declarations':len(result['decompiled_source_symbols']),
        'checks':len(result['static_checks']),'bindings':len(result['ordered_panel_bindings']),'sha256':sha(raw),'original_executed':False}))
    return 0
if __name__=='__main__':raise SystemExit(main())
