#!/usr/bin/env python3
"""Pinned SceneName managed metadata/source annex, without loading assemblies.

PE and ECMA-335 metadata/method headers are read as bytes. No CLR, original
instruction, framework callback, GUI, native service or device is invoked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

import pefile

VENDOR_PINS = {
    'toolkit/app/eDLT.dll': '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3',
    'toolkit/app/CBusLogicModel.dll': '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823',
    'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTUnit.cs': '641f5abc1c3762cd86a0c4b18bc125424a39017a3d78d6edfa4e1e2964af62b2',
    'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTScene.cs': '91fb4aa7438f3ba911062902f022d9bbdc196bc6ce809ecf29cb2ff9bd514774',
    'edlt-decompiled/CBusLogicModel/CBusLogicModel/PPAttribute.cs': '6c057abce7de8793501e34b326d862a9bbc2c2e32ed6c7b7ace796b0ad29e9cb',
    'edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/DataStore.cs': 'd60cd2371e221a54774e6b8c35ce631975d0c2491e6b9e053d700810831f4f2b',
    'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.Utilities/FixedStrings.cs': '6a1347795a0f42f1b1d5b81b08cb002f4592a07e8418211a73874c17b4022809',
    'edlt-decompiled/eDLT/eDLT.Controls/ComboBoxStaticText.cs': 'e6daf32a886e18d67cb20a51d7e483b21af4e470f9f177d8877f7e34d73588c4',
    'edlt-decompiled/eDLT/eDLT.Controls.SceneManagerControls/SceneManager.cs': 'c2aa9a75cf7e128eba6cab952ddbdd45cb7e363b4128dc96ff15bd90adf9d72c',
}

# ECMA-335 II.22 table columns: integer widths, heaps, table indexes or coded
# indexes. All widths come from this pinned image's metadata header/row counts.
S, B, G = 'string', 'blob', 'guid'
TDR=(2,(2,1,27)); HCA=(5,(6,4,1,2,8,9,10,0,14,23,20,17,26,27,32,35,38,39,40,42,44,43))
SCHEMAS={
 0:(2,S,G,G,G),1:((2,(0,26,35,1)),S,S),2:(4,S,S,TDR,('table',4),('table',6)),
 3:(('table',4),),4:(2,S,B),5:(('table',6),),6:(4,2,2,S,B,('table',8)),
 7:(('table',8),),8:(2,2,S),9:(('table',2),TDR),10:((3,(2,1,26,6,27)),S,B),
 11:(2,(2,(4,8,23)),B),12:(HCA,(3,(6,10)),B),13:((1,(4,8)),B),
 14:(2,(2,(2,6,32)),B),15:(2,4,('table',2)),16:(4,('table',4)),17:(B,),
 18:(('table',2),('table',20)),19:(('table',20),),20:(2,S,TDR),
 21:(('table',2),('table',23)),22:(('table',23),),23:(2,S,B),
 24:(2,('table',6),(1,(20,23))),25:(('table',2),(1,(6,10)),(1,(6,10))),
 26:(S,),27:(B,),28:(2,(1,(4,6)),S,('table',26)),29:(4,('table',4)),
 30:(4,4),31:(4,),32:(4,2,2,2,2,4,B,S,S),33:(4,),34:(4,4,4),
 35:(2,2,2,2,4,B,S,S,B),36:(4,('table',35)),37:(4,4,4,('table',35)),
 38:(4,S,B),39:(4,4,S,S,(2,(38,35,39))),40:(4,4,S,(2,(38,35,39))),
 41:(('table',2),('table',2)),42:(2,2,(1,(2,6)),S),43:((1,(6,10)),B),
 44:(('table',42),TDR),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ManagedImage:
    """Read-only ECMA metadata and exact method-body byte spans."""
    def __init__(self, data: bytes):
        self.data=data
        self.pe=pefile.PE(data=data,fast_load=True)
        cli=self.pe.get_offset_from_rva(self.pe.OPTIONAL_HEADER.DATA_DIRECTORY[14].VirtualAddress)
        metadata=self.pe.get_offset_from_rva(struct.unpack_from('<I',data,cli+8)[0])
        if data[metadata:metadata+4]!=b'BSJB':raise ValueError('Not managed metadata')
        version_length=struct.unpack_from('<I',data,metadata+12)[0]
        self.runtime=data[metadata+16:metadata+16+version_length].rstrip(b'\0').decode('ascii')
        cursor=metadata+16+version_length
        _flags,count=struct.unpack_from('<HH',data,cursor);cursor+=4
        streams={}
        for _ in range(count):
            offset,size=struct.unpack_from('<II',data,cursor);cursor+=8
            end=data.index(0,cursor);name=data[cursor:end].decode('ascii')
            cursor=(end+4)&~3
            streams[name]=(metadata+offset,size)
        self.streams=streams
        table=streams.get('#~',streams.get('#-'))
        if table is None:raise ValueError('Missing metadata tables')
        cursor=table[0];self.heaps=data[cursor+6]
        valid=struct.unpack_from('<Q',data,cursor+8)[0];cursor+=24
        self.counts={}
        for index in range(64):
            if valid&(1<<index):
                if index not in SCHEMAS:raise ValueError('Unsupported metadata table')
                self.counts[index]=struct.unpack_from('<I',data,cursor)[0];cursor+=4
        self.tables={}
        for index,count in self.counts.items():
            widths=tuple(self.width(column) for column in SCHEMAS[index])
            self.tables[index]=(cursor,widths);cursor+=count*sum(widths)
        if cursor>table[0]+table[1]:raise ValueError('Metadata table span overflow')
        self.types={}
        for index in range(1,self.counts.get(2,0)+1):
            row=self.row(2,index);name,namespace=self.string(row[1]),self.string(row[2])
            self.types[index]=(namespace+'.' if namespace else '')+name
        for index in range(1,self.counts.get(41,0)+1):
            child,parent=self.row(41,index)
            self.types[child]=self.types[parent]+'+'+self.types[child].rsplit('.',1)[-1]
        self.methods={}
        self.method_symbols={}
        typedefs=list(range(1,self.counts.get(2,0)+1))
        for position,index in enumerate(typedefs):
            start=self.row(2,index)[5]
            stop=self.row(2,typedefs[position+1])[5] if position+1<len(typedefs) else self.counts.get(6,0)+1
            for method in range(start,stop):
                row=self.row(6,method)
                key=self.types[index]+'::'+self.string(row[3])
                self.methods.setdefault(key,[]).append((method,row))
                self.method_symbols[method]=key

    def width(self,column):
        if isinstance(column,int):return column
        if isinstance(column,str):return 4 if self.heaps&{S:1,G:2,B:4}[column] else 2
        if column[0]=='table':return 4 if self.counts.get(column[1],0)>=65536 else 2
        bits,tables=column
        return 4 if max((self.counts.get(t,0) for t in tables),default=0)>=(1<<(16-bits)) else 2

    def row(self,table,index):
        if not 1<=index<=self.counts.get(table,0):raise ValueError('Metadata row out of range')
        offset,widths=self.tables[table];offset+=(index-1)*sum(widths)
        values=[]
        for width in widths:
            values.append(int.from_bytes(self.data[offset:offset+width],'little'));offset+=width
        return tuple(values)

    def string(self,index):
        start,size=self.streams['#Strings'];offset=start+index
        if not start<=offset<start+size:raise ValueError('String heap index out of range')
        end=self.data.index(0,offset,start+size)
        return self.data[offset:end].decode('utf-8')

    def method(self,symbol):
        entries=self.methods.get(symbol,[])
        if len(entries)!=1:raise ValueError('Method must have one exact symbol: '+symbol)
        index,row=entries[0];rva=row[0]
        if not rva:raise ValueError('Method has no managed body')
        offset=self.pe.get_offset_from_rva(rva);first=self.data[offset]
        if first&3==2:header,code,flags=1,first>>2,2
        elif first&3==3:
            flags=struct.unpack_from('<H',self.data,offset)[0]
            header=(flags>>12)*4;code=struct.unpack_from('<I',self.data,offset+4)[0]
            if header<12:raise ValueError('Invalid fat method header')
        else:raise ValueError('Unsupported managed method header')
        end=offset+header+code;sections=0
        if flags&8:
            section=(end+3)&~3
            while True:
                kind=self.data[section]
                size=int.from_bytes(self.data[section+1:section+4],'little') if kind&64 else self.data[section+1]
                if size<4:raise ValueError('Invalid method section')
                end=section+size;sections+=1
                if not kind&128:break
                section=(end+3)&~3
                if sections>8:raise ValueError('Excess method sections')
        if end>len(self.data):raise ValueError('Method body span overflow')
        return {'symbol':symbol,'token':f'0x{0x06000000|index:08x}',
                'rva':f'0x{rva:x}','file_offset':offset,'header_bytes':header,
                'code_bytes':code,'body_bytes':end-offset,'extra_sections':sections,
                'body_sha256':digest(self.data[offset:end]),
                'il_sha256':digest(self.data[offset+header:offset+header+code])}

    def member(self, token):
        table, index = token >> 24, token & 0xffffff
        if table == 6:
            return self.method_symbols[index]
        if table != 10:
            return f'0x{token:08x}'
        parent, name, _signature = self.row(10, index)
        tag, owner = parent & 7, parent >> 3
        if tag == 0:
            typename = self.types[owner]
        elif tag == 1:
            row = self.row(1, owner)
            typename = self.string(row[2]) + '.' + self.string(row[1])
        elif tag == 3:
            typename = self.method_symbols[owner]
        else:
            typename = f'parent({tag},{owner})'
        return typename + '::' + self.string(name)

    def instructions(self, symbol):
        """Decode operand lengths/call metadata only; never execute IL."""
        method = self.method(symbol)
        start = method['file_offset'] + method['header_bytes']
        code = self.data[start:start + method['code_bytes']]
        # ECMA-335 III operand forms. Opcodes not in these sets have no operand.
        short = {*range(0x0e, 0x14), 0x1f, *range(0x2b, 0x38), 0xde}
        word = {0xfe09, 0xfe0a, 0xfe0b, 0xfe0c, 0xfe0d, 0xfe0e}
        long = {0x20, 0x22, *range(0x38, 0x45), 0xdd}
        wide = {0x21, 0x23}
        token_ops = {0x27, 0x28, 0x29, 0x6f, 0x70, 0x71, 0x72, 0x73,
                     0x74, 0x75, 0x79, *range(0x7b, 0x82), 0x8c, 0x8d,
                     0x8f, 0xa3, 0xa4, 0xa5, 0xc2, 0xc6, 0xd0,
                     0xfe06, 0xfe07, 0xfe15, 0xfe16, 0xfe1c}
        calls, integers, branches = [], [], []
        cursor = 0
        while cursor < len(code):
            offset, opcode = cursor, code[cursor]
            cursor += 1
            if opcode == 0xfe:
                opcode = 0xfe00 | code[cursor]
                cursor += 1
            if opcode == 0x45:
                count = int.from_bytes(code[cursor:cursor + 4], 'little')
                size = 4 + 4 * count
            else:
                size = (1 if opcode in short or opcode in {0xfe12, 0xfe19}
                        else 2 if opcode in word else 4 if opcode in long or opcode in token_ops
                        else 8 if opcode in wide else 0)
            operand = code[cursor:cursor + size]
            if len(operand) != size:
                raise ValueError('Managed instruction operand overflow')
            if opcode in {0x27, 0x28, 0x6f, 0x73, 0xfe06, 0xfe07}:
                token = int.from_bytes(operand, 'little')
                calls.append({'il_offset': offset, 'opcode': f'0x{opcode:x}',
                              'token': f'0x{token:08x}', 'symbol': self.member(token)})
            if 0x15 <= opcode <= 0x1e:
                integers.append({'il_offset': offset, 'value': opcode - 0x16})
            elif opcode in {0x1f, 0x20}:
                integers.append({'il_offset': offset,
                                 'value': int.from_bytes(operand, 'little', signed=True)})
            if opcode in {*range(0x2b, 0x45), 0xdd, 0xde}:
                branches.append({'il_offset': offset, 'opcode': f'0x{opcode:x}',
                                 'target': cursor + size + int.from_bytes(operand, 'little', signed=True)})
            cursor += size
        return {'calls': calls, 'integer_constants': integers,
                'branches': branches, 'static_decode_only': True}



FRAMEWORK_COMMIT = 'ec9fa9ae770d522a5b5f0607898044b7478574a3'
FRAMEWORK_PINS = {
    'char.cs': '54c2a31cab70ead8d51e0f29c4f20155c153baafeb2f33dda3967b1ef2ac5a58',
    'string.cs': '4ba1a8c7578a4d2465deceb963ef25c23874a4d8804cb7f991075f811f82208a',
    'charunicodeinfo.cs': '6737eefaa826ce06005dbe02a573e64e92a0abe8915be190615c113ae14cfa88',
    'utf8encoding.cs': '0302f5d59320582f5ae30d7b62ddcf3ceaad0bc31d55c1b5b7f8978a1e09c3e5',
}
L = 'CBusLogicModel.Units.EDLT.'
UI = 'eDLT.Controls.'
LOGIC_METHODS = (
    L+'EDLTScene::get_SceneName', L+'EDLTScene::set_SceneName',
    L+'EDLTScene::get_NameIndex', L+'EDLTScene::set_NameIndex',
    L+'EDLTScene::get_TriggerGroupEditable', L+'EDLTScene::get_ActionSelector',
    L+'EDLTScene::set_ActionSelector', L+'EDLTUnit::get_ScenesNameValue',
    L+'EDLTUnit::AfterLoadPPData', L+'EDLTUnit::GetStaticTextIndex',
    L+'EDLTUnit::GetUsedStaticText', L+'EDLTUnit::LoadScenes',
    L+'EDLTUnit::PopulateStaticTextSuggest', L+'EDLTUnit::SaveStaticText',
    L+'EDLTUnit::SaveScenes', L+'EDLTUnit::GetSceneStartAddress',
    L+'EDLTUnit::BeforeSavePPData', 'CBusLogicModel.PPAttribute::get_ValueAsUtf8String',
    'CBusLogicModel.PPAttribute::set_ValueAsUtf8String',
    'CBusLogicModel.Utilities.DataStore::get_Name', 'CBusLogicModel.Utilities.DataStore::set_Name',
    'CBusLogicModel.Utilities.DataStore::Compare',
    L+'Utilities.FixedStrings::.cctor',
)
UI_METHODS = (
    UI+'ComboBoxStaticText::.ctor', UI+'ComboBoxStaticText::ComboBoxStaticText_Leave',
    UI+'ComboBoxStaticText::ComboImageTagDLT_PreviewKeyDown',
    UI+'ComboBoxStaticText::ComboImageTagDLT_SelectedIndexChanged',
    UI+'ComboBoxStaticText::DataManager_ListChanged',
    UI+'ComboBoxStaticText+<>c__DisplayClass2::<DataManager_ListChanged>b__0',
    UI+'SceneManagerControls.SceneManager::scenesBindingSource_CurrentChanged',
    UI+'SceneManagerControls.SceneManager::InitializeComponent',
    UI+'SceneManagerControls.SceneManager::StaticTextSuggestBindingSourceListChanged',
)
UNIT_SOURCE = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTUnit.cs'
SCENE_SOURCE = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT/EDLTScene.cs'
DATA_SOURCE = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Utilities/DataStore.cs'
PP_SOURCE = 'edlt-decompiled/CBusLogicModel/CBusLogicModel/PPAttribute.cs'
COMBO_SOURCE = 'edlt-decompiled/eDLT/eDLT.Controls/ComboBoxStaticText.cs'
MANAGER_SOURCE = 'edlt-decompiled/eDLT/eDLT.Controls.SceneManagerControls/SceneManager.cs'
FIXED_SOURCE = 'edlt-decompiled/CBusLogicModel/CBusLogicModel.Units.EDLT.Utilities/FixedStrings.cs'
SOURCE_SYMBOLS = (
    (SCENE_SOURCE, 'EDLTScene.SceneName', 'public virtual string SceneName'),
    (SCENE_SOURCE, 'EDLTScene.NameIndex', 'public int NameIndex'),
    (SCENE_SOURCE, 'EDLTScene.TriggerGroupEditable', 'public bool TriggerGroupEditable'),
    (SCENE_SOURCE, 'EDLTScene.ActionSelector', 'public int ActionSelector'),
    (UNIT_SOURCE, 'EDLTUnit.ScenesNameValue', 'public BindingList<DataStore> ScenesNameValue'),
    (UNIT_SOURCE, 'EDLTUnit.AfterLoadPPData', 'public override void AfterLoadPPData()'),
    (UNIT_SOURCE, 'EDLTUnit.GetStaticTextIndex', 'public int GetStaticTextIndex(string strStaticText)'),
    (UNIT_SOURCE, 'EDLTUnit.GetUsedStaticText', 'public HashSet<int> GetUsedStaticText()'),
    (UNIT_SOURCE, 'EDLTUnit.LoadScenes', 'public void LoadScenes()'),
    (UNIT_SOURCE, 'EDLTUnit.PopulateStaticTextSuggest', 'public void PopulateStaticTextSuggest()'),
    (UNIT_SOURCE, 'EDLTUnit.SaveScenes', 'public void SaveScenes(bool notify = true)'),
    (UNIT_SOURCE, 'EDLTUnit.SaveStaticText', 'public void SaveStaticText(bool bRefresh = true)'),
    (UNIT_SOURCE, 'EDLTUnit.BeforeSavePPData', 'protected override void BeforeSavePPData(bool saveDb, bool saveNw)'),
    (UNIT_SOURCE, 'EDLTUnit.GetSceneStartAddress', 'private int GetSceneStartAddress(int sceneIndex)'),
    (PP_SOURCE, 'PPAttribute.ValueAsUtf8String', 'public string ValueAsUtf8String'),
    (DATA_SOURCE, 'DataStore.Name', 'public string Name'),
    (DATA_SOURCE, 'DataStore.Compare', 'public virtual int Compare(object obj)'),
    (COMBO_SOURCE, 'ComboBoxStaticText.constructor', 'public ComboBoxStaticText()'),
    (COMBO_SOURCE, 'ComboBoxStaticText.Leave', 'private void ComboBoxStaticText_Leave(object sender, EventArgs e)'),
    (COMBO_SOURCE, 'ComboBoxStaticText.PreviewKeyDown', 'private void ComboImageTagDLT_PreviewKeyDown(object sender, PreviewKeyDownEventArgs e)'),
    (COMBO_SOURCE, 'ComboBoxStaticText.SelectedIndexChanged', 'private void ComboImageTagDLT_SelectedIndexChanged(object sender, EventArgs e)'),
    (COMBO_SOURCE, 'ComboBoxStaticText.ListChanged', 'private void DataManager_ListChanged(object sender, ListChangedEventArgs e)'),
    (MANAGER_SOURCE, 'SceneManager.CurrentChanged', 'private void scenesBindingSource_CurrentChanged(object sender, EventArgs eventArgs)'),
    (MANAGER_SOURCE, 'SceneManager.InitializeComponent', 'private void InitializeComponent()'),
    (MANAGER_SOURCE, 'SceneManager.SuggestionListChanged', 'private void StaticTextSuggestBindingSourceListChanged(object sender, ListChangedEventArgs changedEvent)'),
    (FIXED_SOURCE, 'FixedStrings.static_initializer', 'public static List<DataStore> StaticTextStrings = new List<DataStore>'),
)
FRAMEWORK_SYMBOLS = (
    ('char.cs', 'Char.IsWhiteSpaceLatin1', 'private static bool IsWhiteSpaceLatin1(char c)'),
    ('char.cs', 'Char.IsWhiteSpace', 'public static bool IsWhiteSpace(char c)'),
    ('charunicodeinfo.cs', 'CharUnicodeInfo.IsWhiteSpace', 'internal static bool IsWhiteSpace(char c)'),
    ('string.cs', 'String.Trim', 'public String Trim()'),
    ('string.cs', 'String.TrimHelper', 'private String TrimHelper(int trimType)'),
    ('string.cs', 'String.IsBOMWhitespace', 'private static bool IsBOMWhitespace(char c)'),
    ('utf8encoding.cs', 'UTF8Encoding.GetChars', 'internal override unsafe int GetChars(byte* bytes, int byteCount,'),
)


def source_span(raw, symbol, anchor):
    """Pin one complete declaration without publishing decompiled code."""
    text = raw.decode('utf-8-sig')
    if text.count(anchor) != 1:
        raise ValueError('Source symbol must have one exact anchor: ' + symbol)
    start = text.index(anchor)
    start = text.rfind('\n', 0, start) + 1
    opening = text.index('{', start)
    # Ignore comment/string/character braces when bounding declarations.
    masked = re.sub(r'//[^\n]*|/\*.*?\*/|@"(?:""|[^"])*"|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                    lambda match: ' ' * len(match.group()), text, flags=re.S)
    depth = 0
    for end in range(opening, len(text)):
        if masked[end] == '{': depth += 1
        elif masked[end] == '}':
            depth -= 1
            if depth == 0:
                end += 1
                break
    else:
        raise ValueError('Unclosed source symbol: ' + symbol)
    fragment = text[start:end].encode('utf-8')
    return {'symbol': symbol, 'start_line': text.count('\n', 0, start) + 1,
            'end_line': text.count('\n', 0, end) + 1,
            'utf8_bytes': len(fragment), 'sha256': digest(fragment),
            'hash_scope': 'Exact UTF8 source declaration without terminal newline/BOM; no code copied.'}


def require_order(values, requested, label):
    position = -1
    for part in requested:
        position = next((i for i in range(position + 1, len(values)) if part in values[i]), -1)
        if position < 0:
            raise ValueError('Static ordered chain mismatch: ' + label)


def recover(vendor_root, framework_root):
    vendor, inputs, framework = {}, [], {}
    for name, expected in VENDOR_PINS.items():
        raw = (vendor_root / name).read_bytes()
        if digest(raw) != expected:
            raise ValueError('Pinned source mismatch: ' + name)
        vendor[name] = raw
        inputs.append({'path': name, 'sha256': expected, 'bytes': len(raw), 'role': 'retained-original-static-input'})
    for name, expected in FRAMEWORK_PINS.items():
        raw = (framework_root / name).read_bytes()
        if digest(raw) != expected:
            raise ValueError('Pinned framework reference mismatch: ' + name)
        framework[name] = raw
        reference = 'mscorlib/system/' + ('text/' if name == 'utf8encoding.cs' else ('globalization/' if name == 'charunicodeinfo.cs' else '')) + name
        inputs.append({'path': reference, 'sha256': expected, 'bytes': len(raw),
                       'role': 'primary-framework-reference-source',
                       'url': 'https://raw.githubusercontent.com/microsoft/referencesource/' + FRAMEWORK_COMMIT + '/' + reference})
    methods, decoded = [], {}
    for name, symbols in [('toolkit/app/CBusLogicModel.dll', LOGIC_METHODS), ('toolkit/app/eDLT.dll', UI_METHODS)]:
        image = ManagedImage(vendor[name])
        if image.runtime != 'v4.0.30319':
            raise ValueError('Pinned metadata runtime changed')
        for symbol in symbols:
            method = image.method(symbol)
            detail = image.instructions(symbol)
            method.update({'assembly': name, 'metadata_runtime': image.runtime, **detail})
            methods.append(method)
            decoded[symbol] = detail
    checks = []
    def calls(symbol, parts, label):
        require_order([call['symbol'] for call in decoded[symbol]['calls']], parts, label)
        checks.append({'id': label, 'symbol': symbol, 'ordered_call_suffixes': parts, 'passed': True})
    def constants(symbol, values, label):
        actual = [entry['value'] for entry in decoded[symbol]['integer_constants']]
        if any(value not in actual for value in values):
            raise ValueError('Static integer anchor mismatch: ' + label)
        checks.append({'id': label, 'symbol': symbol, 'integer_anchors': values, 'passed': True})
    calls(L+'EDLTScene::get_SceneName', ['get_NameIndex', 'get_NameIndex', 'get_StaticLabels', 'get_NameIndex', 'get_Item', 'get_Name'], 'scene-name-getter')
    calls(L+'EDLTScene::set_SceneName', ['GetStaticTextIndex', 'set_NameIndex'], 'allocate-before-old-reference-reassignment')
    calls(L+'EDLTUnit::GetStaticTextIndex', ['System.String::Trim', 'get_Length', 'get_StaticLabels', 'get_Name', 'System.String::Equals', 'GetUsedStaticText', 'get_Count', 'set_Name', 'SaveStaticText'], 'blank-ordinal-capacity-allocation-save-order')
    constants(L+'EDLTUnit::GetStaticTextIndex', [0, 63, 255], 'allocator-boundaries')
    calls(L+'EDLTUnit::AfterLoadPPData', ['get_ValueAsUtf8String', 'CBusLogicModel.Utilities.DataStore::.ctor', 'PopulateStaticTextSuggest', 'LoadScenes'], 'fresh-name-load-before-suggestions-scenes')
    calls(L+'EDLTUnit::SaveStaticText', ['get_ValueAsUtf8String', 'get_Name', 'System.String::Equals', 'get_Name', 'set_ValueAsUtf8String', 'PopulateStaticTextSuggest'], 'decoded-equality-before-setter')
    calls(L+'EDLTUnit::BeforeSavePPData', ['SaveStaticText', 'SaveScenes'], 'static-name-save-before-scene-serialization')
    calls('CBusLogicModel.PPAttribute::get_ValueAsUtf8String', ['System.Text.Encoding::get_UTF8', 'System.Text.Encoding::GetString'], 'pp-utf8-decoder')
    calls('CBusLogicModel.PPAttribute::set_ValueAsUtf8String', ['System.String::IsNullOrEmpty', 'System.Text.Encoding::get_UTF8', 'System.Text.Encoding::GetBytes', 'SetValue'], 'pp-utf8-byte-setter')
    constants('CBusLogicModel.PPAttribute::set_ValueAsUtf8String', [0, 63], 'pp-prefix-boundaries')
    calls(UI+'ComboBoxStaticText::.ctor', ['set_MaxLength', 'set_ValueMember', 'set_DisplayMember', 'add_PreviewKeyDown', 'add_SelectedIndexChanged', 'add_Leave'], 'control-members-and-events')
    constants(UI+'ComboBoxStaticText::.ctor', [64], 'control-maxlength64')
    calls(UI+'ComboBoxStaticText::ComboBoxStaticText_Leave', ['System.Windows.Forms.Binding::WriteValue', 'System.Windows.Forms.Binding::ReadValue'], 'leave-write-read')
    calls(UI+'ComboBoxStaticText::ComboImageTagDLT_PreviewKeyDown', ['System.Windows.Forms.Binding::WriteValue', 'System.Windows.Forms.Binding::ReadValue'], 'enter-write-read')
    constants(UI+'ComboBoxStaticText::ComboImageTagDLT_PreviewKeyDown', [13, 37, 39, 38, 40], 'enter-four-arrow-keycodes')
    calls(UI+'ComboBoxStaticText::ComboImageTagDLT_SelectedIndexChanged', ['remove_ListChanged', 'add_ListChanged', 'System.Windows.Forms.Binding::WriteValue', 'System.Windows.Forms.Binding::ReadValue'], 'selection-rewire-before-write-read')
    calls(UI+'ComboBoxStaticText::DataManager_ListChanged', ['get_InvokeRequired', 'BeginInvoke', 'get_Visible', 'System.Windows.Forms.Binding::ReadValue'], 'async-before-visible-read-only')
    calls(UI+'SceneManagerControls.SceneManager::scenesBindingSource_CurrentChanged', ['get_DataBindings', 'Clear', 'get_DataBindings', 'Add'], 'selected-scene-rebinding')
    constants(UI+'SceneManagerControls.SceneManager::scenesBindingSource_CurrentChanged', [2], 'selected-scene-manual-update-mode')
    constants(UI+'SceneManagerControls.SceneManager::InitializeComponent', [64], 'scene-manager-maxlength64')
    constants(L+'EDLTUnit::SaveScenes', [8, 231, 5, 3], 'eight-scene-header-and-final-ff-shape')
    calls(L+'EDLTUnit::get_ScenesNameValue', ['get_NameIndex', 'get_StaticLabels', 'get_Count', 'get_StaticLabels', 'get_NameIndex', 'get_Item', 'get_Name'], 'scene-name-value-retained-view')
    constants(L+'EDLTUnit::get_ScenesNameValue', [0, 1], 'scene-name-value-zero-based-numbered-display')
    sources = [{'path': name, **source_span(vendor[name], symbol, anchor)} for name, symbol, anchor in SOURCE_SYMBOLS]
    references = [{'path': name, **source_span(framework[name], symbol, anchor)} for name, symbol, anchor in FRAMEWORK_SYMBOLS]
    fixed = re.findall(r'new DataStore\("([^"\\]*)", -1\)', vendor[FIXED_SOURCE].decode())
    if len(fixed) != 64 or len(set(fixed)) != 64:
        raise ValueError('Fixed suggestion membership changed')
    stable = [*range(9, 14), 32, 133, 160, 5760, *range(8192, 8203), 8232, 8233, 8239, 8287, 12288]
    return {
        'format': 'cbus-edlt-scene-name-source-annex-v1',
        'original_inputs': inputs, 'managed_method_spans': methods,
        'decompiled_source_symbols': sources, 'framework_source_symbols': references,
        'static_checks': checks,
        'source_contract': {
            'property_getter': 'NameIndex0..63 returns retained StaticLabels.Name; out-of-range returns empty.',
            'property_setter': 'Null is a no-op. Non-null allocates before assigning NameIndex; old scene references remain used during allocation.',
            'allocation': 'Trim only tests blank, then ordinal existing-name match before used-count>63 refusal; includes255 sentinel; scans highest free63..0.',
            'cache_and_pp': 'Full requested Name stays retained. SaveStaticText compares current PP fallback-decoded Name and only writes unequal rows. Prefix is first63 UTF8 bytes plusNUL, with complete64-byte admitted rows; fresh load decodes PP anew.',
            'save_order': 'BeforeSavePPData saves StaticText(false) before Scenes(false); source eight-empty-scenes byte projection is40 header bytes plus192 FF; pointers0,5,10,15,20,25,30,35.',
            'control_commit': 'Leave/Enter explicitly WriteValue then ReadValue when Text binding exists. Input alone is pending.',
            'selection': 'DataManager handler rewires first. Arrow suppression is one-shot; otherwise source-present nonnegative selection and binding cause WriteValue then ReadValue.',
            'list_refresh': 'Disabled returns first; InvokeRequired schedules BeginInvoke (unexecuted/refused here). Synchronous relevant visible event reads only if new<selected OR(old<selected ANDold!=-1).',
            'view': 'ScenesNameValue uses zero-based integer values and one-based N - Name display. Index64 source off-by-one remains unadmitted.',
            'suggestions': 'Empty255, all retained names, and explicit FixedStrings membership; culture-specific ordering and equal-name survivor unresolved.',
        },
        'fixed_suggestions': {'names': fixed, 'value': -1, 'membership_proved': True, 'ordering_proved': False},
        'framework_profile': {
            'name': 'net4-stable-whitespace', 'reference_commit': FRAMEWORK_COMMIT,
            'primary_trim_url': 'https://learn.microsoft.com/en-us/dotnet/api/system.string.trim?view=netframework-4.8',
            'primary_whitespace_url': 'https://learn.microsoft.com/en-us/dotnet/api/system.char.iswhitespace?view=netframework-4.8',
            'unicode_version_url': 'https://learn.microsoft.com/en-us/dotnet/api/system.string?view=netframework-4.6',
            'stable_white_codepoints': [f'U+{cp:04X}' for cp in stable],
            'stable_nonwhite_edges': ['U+001C', 'U+001D', 'U+001E', 'U+001F', 'U+200B', 'U+FEFF'],
            'version_ambiguous': ['U+180E'],
            'ambiguous_blank_rule': 'Refuse only ifU+180E occurs and every other character is stable white/U+180E. Any proven nonwhite character proves nonblank; preserve entire nonblank text verbatim.',
            'trim_scope': 'Blank test only; no trimming nonblank Name. CLRmetadata alone does not identify host Unicode tables.',
            'legacy_netcf_bom_scope': 'FEATURE_LEGACYNETCF pre-WindowsPhone8 BOM special path is outside the named desktop profile.',
            'utf8_fallback': 'Pinned primary reference GetChars groups constrained invalid lead+second as one replacement; following invalid continuations are separate. Incomplete valid prefix is one replacement.',
        },
        'limits': {
            'original_instructions_executed': 0, 'framework_instructions_executed': 0,
            'host_gui_executed': False, 'original_host_framework_binary_verified': False,
            'physical_device_verified': False, 'native_original_execution_acceptance': False,
            'control_input_utf16_units_max': 64, 'control_embedded_nul_admitted': False,
            'control_unpaired_surrogate_admitted': False, 'wm_settext_behavior_verified': False,
            'culture_collation_or_auto_complete_index_verified': False,
            'asynchronous_framework_dispatch_verified': False, 'implicit_pending_close_verified': False,
            'source_property_arbitrary_dotnet_strings_generalized': False,
            'historical_fixtures_rewritten': False, 'private_paths_or_vendor_code_published': False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-root', type=Path, required=True)
    parser.add_argument('--framework-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result = recover(args.vendor_root, args.framework_root)
    rendered = (json.dumps(result, indent=2, ensure_ascii=False) + '\n').encode()
    if args.check:
        if args.output.read_bytes() != rendered:
            raise SystemExit('SceneName source annex differs')
    else:
        args.output.write_bytes(rendered)
    print(json.dumps({'managed_methods': len(result['managed_method_spans']),
                      'source_symbols': len(result['decompiled_source_symbols']),
                      'framework_symbols': len(result['framework_source_symbols']),
                      'static_checks': len(result['static_checks']),
                      'original_instructions_executed': 0, 'sha256': digest(rendered)}))


if __name__ == '__main__':
    main()
