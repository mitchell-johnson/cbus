#!/usr/bin/env python3
"""Static image lookup/download annex. Read bytes; never load vendor assemblies."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from research.edlt_scene_name_static import ManagedImage, source_span, require_order
from research.edlt_scene_selector_static import VENDOR_PINS

LOGIC='toolkit/app/CBusLogicModel.dll'
SHARP='toolkit/app/SharpCGateCommunicator.dll'
PINS={LOGIC:VENDOR_PINS[LOGIC],SHARP:'fd589789f2c40c0853c06a7d836add0f81a6afe3f397a8d6965a1a1f549a2d6e',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel/TagDLT.cs':'ce6461d96e5017e91f4dc394a27796ff806da3bee12518113b8c2770a1132aa6',
 'edlt-decompiled/CBusLogicModel/CBusLogicModel/CBusNetwork.cs':VENDOR_PINS['edlt-decompiled/CBusLogicModel/CBusLogicModel/CBusNetwork.cs'],
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.CBusObjects/CBusLevel.cs':VENDOR_PINS['edlt-decompiled/CBusLogicModel/CBusLogicModel.CBusObjects/CBusLevel.cs'],
 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/DataStore.cs':VENDOR_PINS['edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/DataStore.cs']}
METHODS={LOGIC:[
 'CBusLogicModel.TagDLT::PopulateImage','CBusLogicModel.CBusNetwork::RefreshData',
 'CBusLogicModel.CBusNetwork::LoadChineseCharacterImages',
 'CBusLogicModel.CBusNetwork::ReadXmlData','CBusLogicModel.CBusObjects.CBusLevel::ReadXmlData',
 'CBusLogicModel.CBusObjects.CBusLevel::PopulateDynamicAll',
 'CBusLogicModel.CBusObjects.CBusLevel::PopulateDynamicAllLanguages',
 'CBusLogicModel.Utilities.DataStore::.ctor',
 'CBusLogicModel.Units.EDLT.EDLTUnit::LoadScenes',
 'CBusLogicModel.Units.EDLT.EDLTScene::get_ActionSelector',
 'CBusLogicModel.Units.EDLT.EDLTScene::set_ActionSelector'],SHARP:[
 'SharpCGateCommunicator.CGateConnection::FileDirProjectImages',
 'SharpCGateCommunicator.CGateConnection::FileDownloadProjectImages',
 'SharpCGateCommunicator.CGateConnection::FileDir',
 'SharpCGateCommunicator.CGateConnection::FileDownload',
 'SharpCGateCommunicator.CGateConnection+CommandFileDir::Prepare',
 'SharpCGateCommunicator.CommandFileDownload::Prepare',
 'SharpCGateCommunicator.CGateCommand::set_SendData',
 'SharpCGateCommunicator.CGateCommand::Send']}


def strings(image,symbol):
    """Decode ldstr operands at actual IL boundaries, not byte-pattern searches."""
    method=image.method(symbol);start=method['file_offset']+method['header_bytes']
    code=image.data[start:start+method['code_bytes']];cursor=0;result=[]
    short={*range(0x0e,0x14),0x1f,*range(0x2b,0x38),0xde}
    word={0xfe09,0xfe0a,0xfe0b,0xfe0c,0xfe0d,0xfe0e}
    long={0x20,0x22,*range(0x38,0x45),0xdd};wide={0x21,0x23}
    tokens={0x27,0x28,0x29,0x6f,0x70,0x71,0x72,0x73,0x74,0x75,0x79,
        *range(0x7b,0x82),0x8c,0x8d,0x8f,0xa3,0xa4,0xa5,0xc2,0xc6,0xd0,
        0xfe06,0xfe07,0xfe15,0xfe16,0xfe1c}
    while cursor<len(code):
        offset=cursor;opcode=code[cursor];cursor+=1
        if opcode==0xfe:opcode=0xfe00|code[cursor];cursor+=1
        size=(4+4*int.from_bytes(code[cursor:cursor+4],'little') if opcode==0x45
            else 1 if opcode in short or opcode in {0xfe12,0xfe19}
            else 2 if opcode in word else 4 if opcode in long or opcode in tokens
            else 8 if opcode in wide else 0)
        operand=code[cursor:cursor+size]
        if len(operand)!=size:raise ValueError('IL operand overflow')
        if opcode==0x72:
            token=int.from_bytes(operand,'little');heap,length=image.streams['#US'];index=token&0xffffff
            if token>>24!=0x70 or not 0<index<length:raise ValueError('Invalid ldstr token')
            at=heap+index;first=image.data[at]
            if first<0x80:n,prefix=first,1
            elif first<0xc0:n,prefix=((first&0x3f)<<8)|image.data[at+1],2
            elif first<0xe0:n,prefix=((first&0x1f)<<24)|int.from_bytes(image.data[at+1:at+4],'big'),4
            else:raise ValueError('Invalid compressed string length')
            if n<1 or index+prefix+n>length or (n-1)%2:raise ValueError('String heap overflow')
            result.append({'il_offset':offset,'value':image.data[at+prefix:at+prefix+n-1].decode('utf-16le')})
        cursor+=size
    return result


def recover(root):
    raw={name:(root/name).read_bytes() for name in PINS}
    for name,data in raw.items():
        if hashlib.sha256(data).hexdigest()!=PINS[name]:raise ValueError('Pinned static input differs: '+Path(name).name)
    decoded={};spans=[]
    for path,names in METHODS.items():
        image=ManagedImage(raw[path])
        if image.runtime!='v4.0.30319':raise ValueError('Metadata runtime differs')
        # This overload is the exact token called by PopulateDynamicAll.
        if path==LOGIC:
            symbol='CBusLogicModel.Utilities.DataStore::.ctor'
            called=[row for row in image.instructions('CBusLogicModel.CBusObjects.CBusLevel::PopulateDynamicAll')['calls'] if row['symbol']==symbol]
            if len(called)!=1 or called[0]['token']!='0x06000005':raise ValueError('TagDLT DataStore constructor differs')
            image.methods[symbol]=[row for row in image.methods[symbol] if row[0]==5]
        for symbol in names:
            spans.append({'assembly':Path(path).name,**image.method(symbol)})
            decoded[symbol]={**image.instructions(symbol),'strings':strings(image,symbol)}
    declarations=[]
    sources={
      'TagDLT.cs':[('CBusLogicModel.TagDLT.PopulateImage','public void PopulateImage(')],
      'CBusNetwork.cs':[('CBusNetwork.RefreshData','public void RefreshData('),('CBusNetwork.LoadChineseCharacterImages','private void LoadChineseCharacterImages(')],
      'CBusLevel.cs':[('CBusLevel.PopulateDynamicAll','public void PopulateDynamicAll(')],
      'DataStore.cs':[('DataStore.TagDLTConstructor','public DataStore(TagDLT tempTag)')]}
    for name,data in raw.items():
        for symbol,anchor in sources.get(Path(name).name,[]):declarations.append(source_span(data,symbol,anchor))
    checks=[]
    def order(symbol,calls,label):
        require_order([row['symbol'] for row in decoded[symbol]['calls']],calls,label)
        checks.append({'id':label,'symbol':symbol,'ordered_calls':calls,'passed':True})
    sharp='SharpCGateCommunicator.CGateConnection::'
    order(sharp+'FileDownloadProjectImages',['FileDirProjectImages','FileDownload','FromBase64String','System.IO.MemoryStream::.ctor','FromStream','Split','get_Length','Substring','Add'],'directory-download-decode-before-keyed-list-add')
    order(sharp+'FileDirProjectImages',['FileDir','EndsWith','StartsWith','Add'],'returned-directory-order-filter')
    order('CBusLogicModel.CBusNetwork::RefreshData',['FileDownloadProjectImages','set_ProjectImages','LoadXMLData'],'fresh-project-images-before-network-xml-load')
    order('CBusLogicModel.CBusNetwork::LoadChineseCharacterImages',['ReadLine','Split','Parse','FromFile','Add'],'index-key-and-decoded-file-in-source-order')
    order('CBusLogicModel.CBusObjects.CBusLevel::PopulateDynamicAll',['get_TagsDLT','PopulateImage','CBusLogicModel.Utilities.DataStore::.ctor','Add'],'all-tag-kinds-populate-image-before-datastore')
    order('CBusLogicModel.Utilities.DataStore::.ctor',['get_TagValue','set_Name','get_Variant','set_ValueAsInt','get_Image','set_Image'],'complete-tag-value-name-preserved')
    order('CBusLogicModel.Units.EDLT.EDLTUnit::LoadScenes',['GetGroupByAddress','GetLevelByAddress','set_ActionSelector','set_NameIndex','Add'],'each-initial-slot-captures-current-label-owner')
    order('CBusLogicModel.Units.EDLT.EDLTScene::set_ActionSelector',['GetLevelByAddress','RefreshDynamicLables'],'explicit-setter-adopts-current-labels')
    if any(row['symbol'].endswith('::RefreshDynamicLables') for row in decoded['CBusLogicModel.Units.EDLT.EDLTScene::get_ActionSelector']['calls']):raise ValueError('Valid getter unconditionally refreshes labels')
    checks.append({'id':'valid-getter-has-no-unconditional-label-refresh','passed':True})
    expected={sharp+'FileDirProjectImages':['%PROJ%/','-DLTD-Pic','.bmp'],sharp+'FileDownloadProjectImages':['%PROJ%/','/','Base64 File Info']}
    for symbol,values in expected.items():
        if [row['value'] for row in decoded[symbol]['strings']]!=values:raise ValueError('FILE literal grammar differs')
        checks.append({'id':'exact-file-grammar-'+symbol.rsplit('::',1)[1],'symbol':symbol,'literals':values,'passed':True})
    text=raw['edlt-decompiled/CBusLogicModel/CBusLogicModel/TagDLT.cs'].decode()
    for fragment in ['if (TagType == "ICON")','item.Key.ToString() == TagValue','if (TagType == "FONT")',"TagValue.Split(new char[1] { ',' })[0]",'if (image.Key == text)','break;']:
        if fragment not in text:raise ValueError('Lookup declaration differs')
    checks.append({'id':'exact-icon-key-font-first-comma-and-first-project-match','passed':True})
    return {'format':'cbus-edlt-scene-language-images-static-v1',
      'inputs':[{'name':Path(name).name,'bytes':len(data),'sha256':PINS[name],'role':'static-byte-input'} for name,data in raw.items()],
      'managed_method_spans':spans,'decompiled_declarations':declarations,'static_checks':checks,
      'lookup_contract':{'project_directory':'%PROJ%/{project}','project_download':'%PROJ%/{project}/{returned_name}',
        'filename_filter':'ASCII admitted profile: exact {project}-DLTD-Pic prefix and .bmp suffix',
        'key':'last four characters of filename segment before first dot','project_duplicate_match':'first',
        'font_key':'segment before first comma without trimming','other_non_icon_key':'whole TagValue',
        'icon_key':'exact decimal Index key string; duplicate keys refused by admitted loader',
        'display_name':'complete original TagValue','refresh_order':['ProjectImages download if enabled','Network XML load','Language default before TagDLT selection','new DynamicAll'],
        'dltp_reloaded_by_refresh':False,'old_valid_scene_labels_retained':True},
      'admission':{'BMP':'BITMAPINFOHEADER40, BI_RGB, 1/4/8-bit indexed and 16-bit RGB555/24/32-bit RGB; bounded exact file/palette/pixel spans',
        'decoded_provider_sha_bound':True,'directory_authenticity_claimed':False,'opacity_modeled':False,
        'GDI_equivalence_claimed':False,'culture_filter_equivalence_claimed':False,
        'original_instructions_executed':False,'framework_instructions_executed':False,
        'implicit_callback_schedule_verified':False,'font_rendering_implemented':False,
        'native_PROJ_namespace_equivalence_universal':False}}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--vendor-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    raw=(json.dumps(recover(args.vendor_root),indent=2,ensure_ascii=True)+'\n').encode('ascii')
    if args.check:
        if args.output.read_bytes()!=raw:raise SystemExit('Static image annex differs')
    else:args.output.write_bytes(raw)


if __name__=='__main__':main()
