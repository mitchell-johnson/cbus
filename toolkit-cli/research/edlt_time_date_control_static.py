#!/usr/bin/env python3
"""Time/Date control source annex from pinned PE/ECMA metadata and source bytes.

No original, framework, GUI, native-service or hardware instruction is executed.
Method bodies and original files are represented by spans and hashes, never copied.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

PINS = {'toolkit/app/eDLT.dll': '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3', 'toolkit/app/CBusLogicModel.dll': '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.EDLT.WidgetData/TimeAndDateData.cs': 'a469d0275fe9277a7c97c228a737771c54d8c01bcbb2eb7c8e2cd978ca5ac946', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.EDLT.WidgetData/BlankData.cs': '8e78031a43015d5323858427905b45677389c8fbfa34d8c576e3c5ce63b60737', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTWidget.cs': 'de02300ce1cbdfdde44ef5967922e15a8a01f06bb18b0bd64231dfb7005bc1a7', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTUnit.cs': '641f5abc1c3762cd86a0c4b18bc125424a39017a3d78d6edfa4e1e2964af62b2', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.WidgetData.BaseObjects/WidgetBaseData.cs': '9848f4b6eac5360fc9396887be2ea8aace7fa0e5fdc43cab2ece66597a086189', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units/CBusBaseUnit.cs': '4f0468941222c6696db5836a32fc0b70d18fcf704ea8fe6dd0c2d709a3842487', 'edlt-decompiled/CBusLogicModel/CBusLogicModel/PPAttribute.cs': '6c057abce7de8793501e34b326d862a9bbc2c2e32ed6c7b7ace796b0ad29e9cb', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/CommonConstants.cs': '98e20887cf973205eaa42e621f0ee21ee5b9367aac1553f88c75b86e16d39020', 'edlt-decompiled/eDLT/eDLT.WidgetPanels/TimeDateWidget2.cs': '3de70bb1c91adb26c039fec0b917cfb4d7397ccf1e0d129639298efca4434cd4', 'edlt-decompiled/eDLT/eDLT.WidgetPanels.baseWidgePanels/BaseWidget.cs': 'e2ecee24752731238d7901b8e2a20e7482e2e8225e76ad0afa660cc602b407d8', 'edlt-decompiled/eDLT/eDLT/FrmBaseUnit.cs': '060323b11494c7a697656d048f97351526a143e339db767731675a87ba1b1b16', 'unitspec-plain/KEYGL5.xml': '812d2f92ccf3176d9f3d4c0f35fc196ac9ba45bc419639421e4e5ff082d2af21', 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/DataStore.cs': 'd60cd2371e221a54774e6b8c35ce631975d0c2491e6b9e053d700810831f4f2b'}
PARSER_PIN = '7bb4f3137bf6da42524cc512d94fe6c711f28b5a80532d018411777f9f573223'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def recover(repo, vendor):
    parser = repo / 'toolkit-cli/research/edlt_scene_name_static.py'
    if sha(parser.read_bytes()) != PARSER_PIN:
        raise ValueError('Static parser pin differs')
    sys.path.insert(0, str(repo / 'toolkit-cli'))
    from research.edlt_scene_name_static import ManagedImage, source_span, require_order
    originals = {}
    inputs = [{'logical_name':'managed-static-parser','sha256':PARSER_PIN,
               'bytes':parser.stat().st_size,'role':'repository-static-parser'}]
    for name, expected in PINS.items():
        raw = (vendor / name).read_bytes()
        if sha(raw) != expected:
            raise ValueError('Static input pin differs: ' + Path(name).name)
        originals[name] = raw
        inputs.append({'logical_name':Path(name).name,'sha256':expected,'bytes':len(raw),
                       'role':'original-static-input'})
    images = {a:ManagedImage(originals['toolkit/app/' + a])
              for a in ('CBusLogicModel.dll','eDLT.dll')}
    if any(i.runtime != 'v4.0.30319' for i in images.values()):
        raise ValueError('CLR metadata differs')
    selected = {
        'DataStore':('.ctor','get_Name','set_Name','get_FormattedDisplay','set_FormattedDisplay','get_ValueAsInt','set_ValueAsInt'),
        'TimeAndDateData':None, 'BlankData':None, 'TimeDateWidget2':None,
        'EDLTWidget':('.ctor','get_WidgetType','set_WidgetType','get_RestoreLevel',
                      'set_RestoreLevel','CreateData','GetAttribute','NotifyPropertyChanged'),
        'WidgetBaseData':('.ctor','get_ParentWidget','set_ParentWidget','WidgetByte',
                          'GetAttribute','SetToDefault','SetForcedValues','GetUsedStaticText',
                          'NotifyPropertyChanged','Dispose','DetachEventHandlers'),
        'EDLTUnit':('get_DateFormat','set_DateFormat','get_TimeFormat','set_TimeFormat',
                    'get_TimeDateLeadingZero','set_TimeDateLeadingZero'),
        'PPAttribute':('get_ValueAsInt','set_ValueAsInt','GetValue','SetValue','NotifyPropertyChanged'),
        'CBusBaseUnit':('GetPPAttribute',),
        'CommonConstants':('.ctor','get_TwoSliceTimeDateStatus','get_DateFormat','get_TimeFormat',
                           'get_WidgetTypesFunctionPages','get_WidgetTypesTimeOut',
                           'get_WidgetTypesTimeOutNo2Slice'),
        'BaseWidget':('.ctor','SetUpDataSource','SetWidgetData','InitializeComponent'),
        'FrmBaseUnit':('GetAvailableWidgetTypes','SetUpWidgetSelection',
                       'cmbWidgetType_SelectedIndexChanged','InitializeComponent'),
    }
    methods, details, declarations, checks = [], {}, [], []
    for assembly, image in images.items():
        for symbol in sorted(image.methods):
            owner, member = symbol.split('::')
            short = owner.rsplit('.',1)[-1]
            if short not in selected or (selected[short] is not None and member not in selected[short]):
                continue
            if member == 'Dispose' and short == 'TimeDateWidget2':
                continue
            entries = image.methods[symbol]
            for ordinal, entry in enumerate(entries):
                try:
                    image.methods[symbol] = [entry]
                    detail = image.instructions(symbol)
                    for call in detail['calls']:
                        token = int(call['token'],16)
                        if token >> 24 == 43:
                            coded = image.row(43, token & 0xffffff)[0]
                            call['symbol'] = image.member(((10 if coded & 1 else 6)<<24)|(coded>>1))
                    strings = detail.pop('string_literals', [])
                    details[symbol] = detail
                    methods.append({**image.method(symbol),'assembly':assembly,
                        'overload_ordinal':ordinal,'metadata_runtime':image.runtime,
                        'method_flags':f'0x{entry[1][2]:04x}',
                        'method_virtual':bool(entry[1][2]&0x40),
                        'method_new_slot':bool(entry[1][2]&0x100),
                        'omitted_string_literal_count':len(strings), **detail})
                finally:
                    image.methods[symbol] = entries
    relationships = []
    for assembly,image in images.items():
        for index,name in image.types.items():
            if name.rsplit('.',1)[-1] not in ('TimeAndDateData','BlankData','TimeDateWidget2'):
                continue
            coded=image.row(2,index)[3];tag,base=coded&3,coded>>2
            if tag==0:
                parent=image.types[base]
            elif tag==1:
                row=image.row(1,base);parent=image.string(row[2])+'.'+image.string(row[1])
            else:
                raise ValueError('Unexpected base-type metadata')
            relationships.append({'type':name,'type_token':f'0x{0x02000000|index:08x}',
                                  'assembly':assembly,'base_type':parent})
    def symbol(short, member):
        found=[s for s in details if s.rsplit('.',1)[-1]==short+'::'+member]
        if len(found)!=1:
            raise ValueError('Missing/ambiguous method ' + short + '.' + member)
        return found[0]
    def order(short,member,suffixes,id):
        name=symbol(short,member)
        require_order([c['symbol'] for c in details[name]['calls']],suffixes,id)
        checks.append({'id':id,'symbol':name,'ordered_call_suffixes':suffixes,'passed':True,
                       'qualification':'Linear static call occurrence order only; branch/dispatch guards separately pinned.'})
    def constants(short,member,required,id):
        name=symbol(short,member)
        actual=[r['value'] for r in details[name]['integer_constants']]
        if any(v not in actual for v in required):
            raise ValueError('Missing source constant '+id)
        checks.append({'id':id,'symbol':name,'required_integer_constants':required,'passed':True})
    def declaration(filename,name,anchor,fragments=(),absent=()):
        path=next(p for p in originals if Path(p).name==filename)
        raw=originals[path];span=source_span(raw,name,anchor)
        body=''.join(raw.decode('utf-8-sig').splitlines(keepends=True)[span['start_line']-1:span['end_line']])
        if any(x not in body for x in fragments) or any(x in body for x in absent):
            raise ValueError('Source declaration differs '+name)
        row={'logical_name':filename,**span}
        if row not in declarations:declarations.append(row)
        checks.append({'id':name,'declaration':row,'required_anchor_count':len(fragments),
                       'absent_anchor_count':len(absent),'passed':True})
        return body
    declaration('TimeAndDateData.cs','display-byte1-no-guard','public int DisplayType\n',
                ('return WidgetByte(1).ValueAsInt;','WidgetByte(1).ValueAsInt = value;'),('!= value',))
    declaration('TimeAndDateData.cs','time-date-default-base-only','public override void SetToDefault()\n',
                ('base.SetToDefault();',),('WidgetByte(',))
    blank=originals[next(p for p in originals if Path(p).name=='BlankData.cs')].decode('utf-8-sig')
    if 'SetToDefault' in blank:raise ValueError('Blank now overrides default')
    checks.append({'id':'blank-default-inherited','logical_name':'BlankData.cs',
                   'source_sha256':sha(blank.encode()),'passed':True,
                   'qualification':'No BlankData SetToDefault override; metadata base is WidgetBaseData.'})
    declaration('WidgetBaseData.cs','base-default-restore-only','public virtual void SetToDefault()\n',
                ('ParentWidget.RestoreLevel = 0;',),('WidgetByte(',))
    declaration('EDLTWidget.cs','type-changed-next-before-selected-default','public virtual int WidgetType\n',
                ('ValueAsInt != value','if (value == 11)','Unit.Widgets[_widgetNumber].WidgetType = 0;',
                 'CreateData();','WidgetData.SetToDefault();','NotifyPropertyChanged("WidgetType");'))
    order('EDLTWidget','set_WidgetType',['set_WidgetType','set_ValueAsInt','CreateData','SetToDefault','NotifyPropertyChanged'],
          'next-widget-setter-before-selected-default')
    constants('EDLTWidget','set_WidgetType',[11,0,1],'type11-next-and-notification-suppression')
    declaration('EDLTWidget.cs','create-data-time-date-and-blank','private void CreateData()\n',
                ('case 0:','new BlankData','case 10:','case 11:','new TimeAndDateData'))
    order('WidgetBaseData','SetToDefault',['get_ParentWidget','set_RestoreLevel'],'base-default-restore-write')
    declaration('EDLTWidget.cs','restore-direct-attribute-write','public virtual int RestoreLevel\n',
                ('GetAttribute(_widgetPrefix + "RestoreLevel").ValueAsInt = value;',))
    declaration('EDLTWidget.cs','missing-widget-attribute-detached','public PPAttribute GetAttribute(string strName)\n',
                ('if (pPAttribute == null)','return new PPAttribute();'))
    declaration('EDLTWidget.cs','widgettype-notify-independent-of-widgetbase-suppression','private void NotifyPropertyChanged(string info)\n',
                ('if (this.PropertyChanged != null)','this.PropertyChanged(this, new PropertyChangedEventArgs(info));'),
                ('DoNotFireNotifyPropertyChanged',))
    declaration('DataStore.cs','formatted-display-default-name','public string FormattedDisplay\n',
                ('_formattedDisplay == null || _formattedDisplay.Length == 0','return Name;'))
    declaration('DataStore.cs','integer-choice-constructor-no-custom-format','public DataStore(string strName, int iValue)\n',
                ('Name = strName;','ValueAsInt = iValue;'),('FormattedDisplay',))
    for prop,fallback in (('DateFormat',0),('TimeFormat',3),('TimeDateLeadingZero',0)):
        declaration('EDLTUnit.cs','global-'+prop+'-guard','public int '+prop+'\n',
                    ('?.ValueAsInt ?? '+str(fallback),'pPAttribute != null && pPAttribute.ValueAsInt != value',
                     'pPAttribute.ValueAsInt = value;'),('& 0x', '| value'))
        order('EDLTUnit','set_'+prop,['GetPPAttribute','get_ValueAsInt','set_ValueAsInt'],
              'global-'+prop+'-numeric-equality-before-write')
    declaration('PPAttribute.cs','byte-setter-clamp-and-uppercase-token','public int ValueAsInt\n',
                ('if (value > 255)','value = 255;','if (value < 0)','value = 0;',
                 'SetValue(0, $"0x{value:X}");'))
    constants('PPAttribute','set_ValueAsInt',[255,0],'byte-setter-clamp-0-255')
    declaration('PPAttribute.cs','raw-token-notify-init-mode-guard','private void SetValue(int i, string value)\n',
                ('if (Values[i] != value)','if (!bInitialiseMode)','NotifyPropertyChanged("Value");'))
    declaration('WidgetBaseData.cs','widget-data-notify-suppression','public void NotifyPropertyChanged(string info)\n',
                ('!DoNotFireNotifyPropertyChanged','bFinished: true'))
    declaration('TimeDateWidget2.cs','panel-type-field-not-model-setter','public TimeDateWidget2(EDLTUnit unit)\n',
                ('InitializeComponent();','WidgetType = 10;'))
    field_source=originals[next(p for p in originals if Path(p).name=='BaseWidget.cs')].decode('utf-8-sig')
    field_line=next((n,line) for n,line in enumerate(field_source.splitlines(),1) if line.strip()=='public int WidgetType;')
    declarations.append({'logical_name':'BaseWidget.cs','symbol':'BaseWidget.WidgetType','start_line':field_line[0],'end_line':field_line[0],
        'sha256':sha(field_line[1].encode()),'utf8_bytes':len(field_line[1].encode()),'hash_scope':'Exact UTF8 field declaration line'})
    order('TimeDateWidget2','SetUpDataSource',['SetUpDataSource','set_DataSource','get_EDLTWidget','get_WidgetData','set_DataSource',
          'get_TwoSliceTimeDateStatus','set_DataSource'],'panel-setup-base-before-data-and-display-list')
    declaration('TimeDateWidget2.cs','display-binding-mode1','private void InitializeComponent()\n',
                ('"SelectedValue", (object)timeAndDateData2SliceBindingSource, "DisplayType", true, (DataSourceUpdateMode)1',
                 'DisplayMember = "FormattedDisplay"','ValueMember = "ValueAsInt"'))
    declaration('FrmBaseUnit.cs','widget-list-location-branch','public List<DataStore> GetAvailableWidgetTypes(EDLTWidget widget)\n',
                ('widget._widgetNumber == -1','widget._widgetNumber < 6','widget._widgetNumber == 5',
                 'WidgetTypesTimeOutNo2Slice','WidgetTypesTimeOut','WidgetTypesFunctionPages'))
    declaration('FrmBaseUnit.cs','setup-reuses-binding-and-read','private void SetUpWidgetSelection()\n',
                ('DataBindings)[0]','DataBindings.Clear();','eDLTWidget._widgetNumber == 5',
                 'DataBindings.Add(val);','val.ReadValue();'))
    order('FrmBaseUnit','SetUpWidgetSelection',['get_DataBindings','get_Item','Clear','Add','ReadValue'],
          'setup-clear-restore-same-binding-explicit-read')
    declaration('FrmBaseUnit.cs','selected-index-handler-empty','private void cmbWidgetType_SelectedIndexChanged(object sender, EventArgs e)\n')
    handler=details[symbol('FrmBaseUnit','cmbWidgetType_SelectedIndexChanged')]
    if handler['calls']:raise ValueError('SelectedIndexChanged no longer empty')
    checks.append({'id':'selected-index-handler-no-calls','symbol':symbol('FrmBaseUnit','cmbWidgetType_SelectedIndexChanged'),
                   'passed':True})
    declaration('FrmBaseUnit.cs','global-and-type-bindings-mode1','private void InitializeComponent()\n',
                ('"TimeFormat", true, (DataSourceUpdateMode)1','"DateFormat", true, (DataSourceUpdateMode)1',
                 '"TimeDateLeadingZero", true, (DataSourceUpdateMode)1','"WidgetType", true, (DataSourceUpdateMode)1'))
    choices={}
    common=originals[next(p for p in originals if Path(p).name=='CommonConstants.cs')]
    for name in ('l2SliceTimeDateStatus','LDateFormat','LTimeFormat','LWidgetTypesScreenSaverInt',
                 'LWidgetTypesScreenSaverIntNo2Slice','LWidgetTypesFunctionPages'):
        body=declaration('CommonConstants.cs','choices-'+name,'public List<DataStore> '+name+' =')
        rows=re.findall(r'new DataStore\("([^"]*)", ([0-9]+)\)',body)
        if not rows:raise ValueError('No choice rows '+name)
        choices[name]=[{'name':label,'value':int(value)} for label,value in rows]
    expected_lists={'l2SliceTimeDateStatus':[1,0,2],'LDateFormat':list(range(8)),'LTimeFormat':[3,1,0,2],
        'LWidgetTypesScreenSaverInt':[0,13,12,10,11],'LWidgetTypesScreenSaverIntNo2Slice':[0,13,12,10],
        'LWidgetTypesFunctionPages':[0,14,4,13,2,12,7,8,9,16,6,3,5,10,15]}
    if {k:[r['value'] for r in v] for k,v in choices.items()}!=expected_lists:
        raise ValueError('Ordered source choices differ')
    bindings=[]
    for filename in ('TimeDateWidget2.cs','FrmBaseUnit.cs'):
        source=originals[next(p for p in originals if Path(p).name==filename)].decode('utf-8-sig')
        for no,line in enumerate(source.splitlines(),1):
            match=re.search(r'new Binding\("([^"]*)", \(object\)([A-Za-z_0-9]+), "([^"]*)", (true|false)(?:, \(DataSourceUpdateMode\)([0-9]+))?\)',line)
            if not match:continue
            prop,owner,target,fmt,mode=match.groups()
            if target not in ('DisplayType','WidgetType','DateFormat','TimeFormat','TimeDateLeadingZero'):continue
            control=re.search(r'\(\(Control\)([^)]+)\)',line)
            bindings.append({'panel':Path(filename).stem,'line':no,'control':control.group(1) if control else None,
                'control_property':prop,'source':owner,'source_property':target,'formatting_enabled':fmt=='true',
                'explicit_update_mode':None if mode is None else int(mode),'line_sha256':sha(line.encode()),
                'declaration_phase':'InitializeComponent during construction; no automatic callback schedule inferred'})
    spec=originals['unitspec-plain/KEYGL5.xml']
    root=ET.fromstring(spec[spec.index(b'<?xml'):])
    params={p.findtext('Name'):p for p in root.iter('Param')}
    def integer(s):return int(s.replace('$','0x'),0)
    fields=[]
    for name,bit,size,kind in (('DateFormat',0,4,'int'),('TimeDateLeadingZero',4,1,'bit'),('TimeFormat',5,2,'int'),('LevelBarStyle',7,1,'int')):
        p=params[name]
        if (integer(p.findtext('Address')),int(p.findtext('BitAddress')),int(p.findtext('BitSize')),p.findtext('Type'))!=(0x119,bit,size,kind):
            raise ValueError('Original format layout differs')
        fields.append({'name':name,'address':0x119,'bit_address':bit,'bit_size':size,'mask':((1<<size)-1)<<bit,
                       'default_value':integer(p.findtext('DefaultValue')),'type':kind})
    restore=[n for n in range(1,22) if 'Widget'+str(n)+'RestoreLevel' in params]
    if restore!=list(range(6,22)):raise ValueError('Original Restore roster differs')
    overlap=[]
    for name,p in params.items():
        if p.findtext('Address') is not None and p.findtext('Address').strip()=='$119':overlap.append(name)
    if set(overlap)!={'DateFormat','TimeDateLeadingZero','TimeFormat','LevelBarStyle'}:
        raise ValueError('Additional parameter shares format byte')
    checks.append({'id':'original-global-layout-masks-and-levelbarstyle-bit7','source_sha256':sha(spec),
        'field_masks':[15,16,96],'sibling_field':'LevelBarStyle','sibling_mask':128,'passed':True,
        'qualification':'Source unit layout, not a model setter bit mask or raw hardware verification.'})
    checks.append({'id':'original-restore-only-functional-six-through21','source_sha256':sha(spec),
                   'restore_widget_numbers':restore,'passed':True})
    return {'format':'cbus-edlt-time-date-control-source-annex-v1','original_inputs':inputs,
        'managed_method_spans':methods,'metadata_type_relationships':relationships,
        'decompiled_source_symbols':declarations,'static_checks':checks,'ordered_panel_bindings':bindings,
        'source_choices':choices,'unit_layout':{'unit_type':'KEYGL5','format_fields':fields,
           'sibling_field':'LevelBarStyle','sibling_mask':128,'restore_widget_numbers':restore},
        'source_contract':{'display_byte':1,'display_getter_repairs':False,'display_setter_numeric_guard':False,
            'global_numeric_equality_guard':True,'model_global_masks':False,'byte_setter_bounds':[0,255],
            'changed_type11_next_setter':0,'same_type11_touches_next':False,
            'shrink_type10_touches_next':False,'default_selected_restore':0,'default_opaque_bytes_cleared':False,
            'adjacent_blank_default':'Inherited WidgetBaseData RestoreLevel=0 only; setter0 equality skips default',
            'standby4_type11_offered':True,'standby5_type11_offered':False,'functional_type11_offered':False,
            'panel_constructor_widgettype':'BaseWidget field10; not EDLTWidget setter',
            'notifications':'PPAttribute raw token equality and initialise-mode dependent; numeric snapshots alone do not establish Value events'},
        'scope':{'original_executed':False,'framework_executed':False,'host_gui':False,
            'service_executed':False,'physical_verified':False,'full_parity':False,
            'original_method_string_table_exported':False,'source_ui_display_choices_exported':True,'original_method_bodies_exported':False},
        'remaining':['Framework Binding parse/currency/scheduling and implicit automatic notifications',
            'Raw token/init-mode input is required for exact PPAttribute Value notification counts',
            'Clock/time-source control, visual rendering and physical device acceptance',
            'Off-UI two-slice functional placement and finalwidget21 unchecked next access remain refused']}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--vendor-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--check',action='store_true')
    args=p.parse_args()
    result=recover(Path(__file__).resolve().parents[2],args.vendor_root)
    raw=(json.dumps(result,sort_keys=True,indent=2)+'\n').encode()
    if args.check:
        if args.output.read_bytes()!=raw:raise ValueError('Saved Time/Date annex differs')
    else:args.output.write_bytes(raw)
    print(json.dumps({'method_spans':len(result['managed_method_spans']),
        'declarations':len(result['decompiled_source_symbols']),'checks':len(result['static_checks']),
        'bindings':len(result['ordered_panel_bindings']),'sha256':sha(raw),'original_executed':False}))
    return 0
if __name__=='__main__':raise SystemExit(main())
