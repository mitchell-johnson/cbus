#!/usr/bin/env python3
"""Pin static Global source load/image/CRC facts; no original instructions run."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from research.edlt_scene_name_static import ManagedImage, source_span, require_order

BASE = 'edlt-decompiled/CBusLogicModel/'
PINS = {
 'toolkit/app/CBusLogicModel.dll':'34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823',
 BASE+'CBusLogicModel.Units.EDLT/EDLTUnit.cs':'641f5abc1c3762cd86a0c4b18bc125424a39017a3d78d6edfa4e1e2964af62b2',
 BASE+'CBusLogicModel.Units.EDLT.WidgetData/LightingData.cs':'aa272e496f89d83e66bc4defe79476cc00c1bb42065835fd0e42b1c8644da873',
 BASE+'CBusLogicModel.CBusObjects/CBusGroup.cs':'882ef659aa8114ee8d5a9f51c7d7d14cde7322f7da83a33853c9c6f49a3e7aa2',
 BASE+'CBusLogicModel/TagDLT.cs':'ce6461d96e5017e91f4dc394a27796ff806da3bee12518113b8c2770a1132aa6',
 BASE+'CBusLogicModel/CBusNetwork.cs':'ddd65e5d34d94f3b0468f0db5a8468c0b6b5cdc50b8a49ca27b9f7331000d39c',
 BASE+'CBusLogicModel/CBusApplication.cs':'669554fea6b53c01a2d0d0c1d7cf8c89cd76d68af0b7d2b11f3bb73a6bfe5933',
 BASE+'CBusLogicModel.Units/CBusBaseUnit.cs':'4f0468941222c6696db5836a32fc0b70d18fcf704ea8fe6dd0c2d709a3842487',
}
UNIT='CBusLogicModel.Units.EDLT.EDLTUnit::'
LIGHT='CBusLogicModel.Units.EDLT.WidgetData.LightingData::'
GROUP='CBusLogicModel.CBusObjects.CBusGroup::'
NETWORK='CBusLogicModel.CBusNetwork::'
TAG='CBusLogicModel.TagDLT::'
APP='CBusLogicModel.CBusApplication::'
BASEUNIT='CBusLogicModel.Units.CBusBaseUnit::'
CRC='CBusLogicModel.Crc16Ccitt::'
METHODS=(UNIT+'AfterLoadPPData',UNIT+'LoadWidgetsFromAttributes',UNIT+'LoadScenes',
 UNIT+'BeforeSavePPData',UNIT+'SaveStaticText',UNIT+'SaveScenes',
 UNIT+'GetMemoryRangeForCRCParameter',LIGHT+'.ctor',LIGHT+'get_LabelValueIndex',
 GROUP+'ReadXmlData',GROUP+'PopulateDynamicAll',GROUP+'InitialiseGroup',
 NETWORK+'ReadXmlData',NETWORK+'get_DefaultLanguage',TAG+'PopulateImage',
 APP+'ReadXmlData',BASEUNIT+'CalculateCRCForPPAttributes',CRC+'checkCrc16',CRC+'IpUtilityUpdateCrc')
DECLARATIONS={
 'EDLTUnit.cs': [('EDLTUnit.AfterLoadPPData','public override void AfterLoadPPData('),
  ('EDLTUnit.LoadWidgetsFromAttributes','public void LoadWidgetsFromAttributes('),
  ('EDLTUnit.LoadScenes','public void LoadScenes('),
  ('EDLTUnit.BeforeSavePPData','protected override void BeforeSavePPData('),
  ('EDLTUnit.GetMemoryRangeForCRCParameter','protected override bool GetMemoryRangeForCRCParameter(')],
 'LightingData.cs':[('LightingData.ctor','public LightingData('),
  ('LightingData.LabelValueIndex','public override int LabelValueIndex')],
 'CBusGroup.cs':[('CBusGroup.ReadXmlData','public override XmlDocument ReadXmlData('),
  ('CBusGroup.PopulateDynamicAll','public void PopulateDynamicAll(')],
 'CBusNetwork.cs':[('CBusNetwork.ReadXmlData','public override XmlDocument ReadXmlData(')],
 'CBusApplication.cs':[('CBusApplication.ReadXmlData','public override XmlDocument ReadXmlData(')],
 'TagDLT.cs':[('TagDLT.PopulateImage','public void PopulateImage(')],
 'CBusBaseUnit.cs':[('CBusBaseUnit.CalculateCRCForPPAttributes','private void CalculateCRCForPPAttributes(')]}


def recover(vendor_root):
 raw = {name:(vendor_root/name).read_bytes() for name in PINS}
 for name,data in raw.items():
  if hashlib.sha256(data).hexdigest()!=PINS[name]:raise ValueError('Pinned original static input differs: '+Path(name).name)
 image=ManagedImage(raw['toolkit/app/CBusLogicModel.dll'])
 if image.runtime!='v4.0.30319':raise ValueError('Pinned metadata runtime differs')
 methods=[]; decoded={}
 for symbol in METHODS:
  detail=image.instructions(symbol)
  for call in detail['calls']:
   token=int(call['token'],16)
   if token>>24==43:
    coded=image.row(43,token&0xffffff)[0]
    call['symbol']=image.member(((10 if coded&1 else 6)<<24)|(coded>>1))
  decoded[symbol]=detail
  methods.append({'assembly':'CBusLogicModel.dll',**image.method(symbol)})
 checks=[]
 def order(symbol,names,key):
  require_order([row['symbol']for row in decoded[symbol]['calls']],names,key)
  checks.append({'id':key,'symbol':symbol,'ordered_call_suffixes':names,'passed':True})
 def constants(symbol,numbers,key):
  actual=[row['value']for row in decoded[symbol]['integer_constants']]
  if any(n not in actual for n in numbers):raise ValueError('Static integer contract differs: '+key)
  checks.append({'id':key,'symbol':symbol,'required_integer_constants':numbers,'passed':True})
 order(UNIT+'AfterLoadPPData',['AfterLoadPPData','get_ValueAsInt','set_ValueAsInt','get_StaticLabels','Clear','PopulateStaticTextSuggest','LoadScenes','LoadWidgetsFromAttributes','InitializeMRAGlobalValues','CheckIfGroupsExist'],'source-load-scenes-before-widget-constructors')
 constants(UNIT+'AfterLoadPPData',[255,56,64,202,203],'source-load-defaults-and-lists')
 order(LIGHT+'.ctor',['get_SelectedApplication','GetGroupByAddress','get_DynamicAll','get_LabelValueIndex','get_Image','set_ValueAsInt'],'constructor-current-group-image-subtype')
 constants(LIGHT+'.ctor',[1,2,32,239,16,223],'constructor-type1-to2-and-type2-to1-masks')
 constants(LIGHT+'get_LabelValueIndex',[1,2,3,4,13,64,0],'lighting-effective-dynamic-index')
 order(GROUP+'ReadXmlData',['ReadXmlData','InitialiseGroup','get_DefaultLanguage','PopulateDynamicAll'],'source-network-language-before-dynamic-all')
 order(GROUP+'PopulateDynamicAll',['get_DynamicAll','Clear','get_TagsDLT','get_ProjectImages','PopulateImage','Add','NotifyPropertyChanged'],'populate-images-before-datastore-list')
 order(TAG+'PopulateImage',['get_FlavourID','get_TagType','get_ParentGroup','get_DLTP','get_TagValue','set_Image','get_TagValue','get_TagType','IndexOf','Split','set_Image'],'icon-then-font-or-exact-project-key')
 order(UNIT+'BeforeSavePPData',['BeforeSavePPData','SaveStaticText','SaveScenes','SetMRAWidgetGlobalValues','SetForcedValues'],'source-terminal-save-phase-order')
 constants(UNIT+'GetMemoryRangeForCRCParameter',[16,9199,239,256,3839,4096,4095,8192,1023],'all-five-original-crc-ranges')
 order(BASEUNIT+'CalculateCRCForPPAttributes',['SetMemoryFromParamStringValue','GetMappingCRCByteToParameterTag','GetMemoryRangeForCRCParameter','checkCrc16'],'source-crc-memory-before-five-ranges')
 constants(BASEUNIT+'CalculateCRCForPPAttributes',[9216,8,255],'crc-zero-memory-and-big-endian-byte-spelling')
 constants(CRC+'checkCrc16',[64080],'source-crc-seed-fa50')
 constants(CRC+'IpUtilityUpdateCrc',[8,32768,4129],'source-crc-polynomial1021-msb-first')
 constants(APP+'ReadXmlData',[255],'stored255-is-not-native-real-group')
 sources=[]
 for name,rows in DECLARATIONS.items():
  source=next(data for path,data in raw.items()if Path(path).name==name)
  for symbol,anchor in rows:sources.append({'logical_name':name,**source_span(source,symbol,anchor)})
 historical=Path(__file__).with_name('fixtures')/'edlt-global-programming-vectors.json'
 v=json.loads(historical.read_bytes())
 if hashlib.sha256(historical.read_bytes()).hexdigest()!='e0ac5e0747279cc11e1c697045ec245f063905c8c11a6aae365f1941b6b0a415':raise ValueError('Historical category vector differs')
 for source in v['sources']:
  if [row['mask']for row in source['masks']]!=list(range(16)):raise ValueError('Historical16mask denominator differs')
  for row in source['masks']:
   if row['ordered_payload'][-1]!=['GlobalParameterCRC','0x0 0x0']:raise ValueError('Historical zero global CRC tail differs')
 checks.append({'id':'historical-category-mask-order-and-zero-global-crc','passed':True,'source_contexts':2,'masks_per_source':16,'new_original_execution':False})
 return {'format':'cbus-edlt-global-image-source-annex-v1',
  'original_inputs':[{'logical_name':Path(name).name,'sha256':PINS[name],'bytes':len(data)}for name,data in raw.items()],
  'managed_method_spans':methods,'decompiled_source_symbols':sources,'static_checks':checks,
  'historical_category_vector':{'logical_name':historical.name,'sha256':hashlib.sha256(historical.read_bytes()).hexdigest(),'bytes':historical.stat().st_size},
  'source_contract':{'load':'AfterLoad creates retained static labels/scenes before all widget constructors, then bindings/MRA/group checks. No destination model is loaded by a PP category merge.',
   'image':'Source network current Language selects TagsDLT; PopulateDynamicAll populates Image before DataStore. ICON resolves exact decimal DLTP key; FONT strips first comma; other tags including TEXT use exact key, first project-image match wins.',
   'lighting':'Actual selected source group, effective index0 for stored>=4, and null/Image presence distinguish dynamic label types1/2. No caller Boolean or target label is borrowed.',
   'global_payload':'Existing historical all16 masks preserve source PP attribute order, include source OverallCRC, append zero GlobalParameterCRC and preserve three destination CRC sections. New image profile does not prove a new original worker run.',
   'scope':'Ordinary complete source lifecycle only. Existing factory six-profile restrictions remain; missing applications are refused rather than invented. Whole project preservation allows only selected target PP Value attributes.'},
  'limits':{'original_instructions_executed':0,'framework_host_executed':False,'physical_hardware_executed':False,'new_original_global_worker_execution':False,'factory_admission_expanded':False,'image_upload_performed':False,'label_transfer_performed':False,'target_lifecycle_loads':0,'vendor_code_published':False,'instruction_bytes_published':False}}


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--vendor-root',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--check',action='store_true');a=p.parse_args()
 result=recover(a.vendor_root);data=(json.dumps(result,indent=2)+'\n').encode()
 if a.check:
  if a.output.read_bytes()!=data:raise SystemExit('Global image source annex differs')
 else:a.output.write_bytes(data)
 print(json.dumps({'managed_spans':len(result['managed_method_spans']),'source_symbols':len(result['decompiled_source_symbols']),'checks':len(result['static_checks']),'sha256':hashlib.sha256(data).hexdigest(),'original_instructions_executed':0}))
if __name__=='__main__':main()
