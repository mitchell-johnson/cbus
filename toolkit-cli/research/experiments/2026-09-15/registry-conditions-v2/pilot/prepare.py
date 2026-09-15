"""Offline fixed-input/pin preparation; no original method or guest execution."""
from pathlib import Path
import hashlib
import json
import re
import struct
import pefile

ROOT = Path('/Users/mitchell/source/cbus/toolkit-cli')
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
PREFIX = 'registry-admission-d0fe9896d3764e53'
ROOT_NAME = 'CBusCliCondition_d0fe9896d3764e53b7327afb4d1af652'
sha = lambda b: hashlib.sha256(b).hexdigest()


def main():
    source = BASE/'registry-proposal-v1/pilot-cases.json'
    data = source.read_bytes()
    if sha(data) != '706ef80be3ce1708d5bc97940fb63f3b56b3941656be34d2e59bf389c4102e36':
        raise RuntimeError('Original reviewed twelve-case plan changed')
    original = json.loads(data)
    cases = json.loads(data)['cases']
    for case in cases:
        case['condition']['fileOrRegistryKeyPath'] = case['condition']['fileOrRegistryKeyPath'].replace('{owned_root_name}', ROOT_NAME)
    payload = {'format': 'toolkit-update-registry-admission-input-v1', 'root_name': ROOT_NAME,
               'reviewed_plan_sha256': sha(data), 'cases': cases}
    raw = (json.dumps(payload, indent=2, ensure_ascii=True)+'\n').encode()
    if len(raw) > 65536 or len(cases) != 12:
        raise RuntimeError('Input bounds')
    (HERE/'input.json').write_bytes(raw)
    inventory_path = BASE/'static-v1/inventory.json'
    inventory_bytes = inventory_path.read_bytes()
    if sha(inventory_bytes) != '6b1708300f47c617e0dab410eadc6894f8373b4d3ea2ba63729e9f9de47aa7fd':
        raise RuntimeError('Historical inventory changed')
    inventory = json.loads(inventory_bytes)
    common = Path(inventory['inputs']['assemblies/se.dad.sesu.common.dll']['path']).read_bytes()
    if sha(common) != '477fb88de310852611f26d1f845da23b8f0e6b602de8ab61a3eefc06339dc4ba':
        raise RuntimeError('Original common DLL changed')
    pe = pefile.PE(data=common)
    source_il = Path(inventory['inputs']['common.il']['path']).read_bytes()
    if sha(source_il) != inventory['inputs']['common.il']['sha256']:
        raise RuntimeError('Historical IL changed')
    lines = source_il.decode().splitlines()
    checker = {'EvaluateRegistryKeyExists','EvaluateRegistryEntryExists','EvaluateRegistryEntryContent',
               'ReplaceRegistryRootAbbreviations','ReplaceFirstOccurrence','CompareInt','.cctor'}
    properties = {'WhatToCheck','HowToCheck','FileOrRegistryKeyPath','RegistryEntryNameOrProductCode','ComparisonRightSideValue'}
    method_records = {}
    for record in inventory['methods']:
        owner, name = record['method'].split('::',1)
        selected = (owner == 'ClientConditionChecker' and name in checker) or (owner == 'Condition' and
                   (name == '.cctor' or name in {prefix+p for p in properties for prefix in ('get_','set_')}))
        if not selected:
            continue
        preceding = '\n'.join(lines[max(0,record['first_line']-8):record['first_line']-1])
        numbers = re.findall(r'// method line (\d+)',preceding)
        if len(numbers) != 1:
            raise RuntimeError('Method-token association missing: '+record['method'])
        offset = pe.get_offset_from_rva(int(record['rva'],16))
        header = common[offset]
        if header & 3 == 2:
            start, size = offset+1, header >> 2
        else:
            flags = struct.unpack_from('<H',common,offset)[0]
            if flags & 3 != 3:
                raise RuntimeError('Unexpected IL header')
            start = offset + (flags >> 12)*4
            size = struct.unpack_from('<I',common,offset+4)[0]
        if size != record['code_size']:
            raise RuntimeError('IL extent disagrees with historical disassembly')
        method_records[record['method']] = {'token':0x06000000+int(numbers[0]),'rva':record['rva'],
                                            'il_bytes':size,'sha256':sha(common[start:start+size])}
    types_text=(HERE/'original-types.txt').read_text()
    type_tokens={}
    for simple,full in [('Checker','SE.DAD.SESU.Common.Validation.ClientConditionChecker'),('Condition','SE.DAD.SESU.Common.Models.Condition')]:
        match=re.search(r'(?m)^(\d+): '+re.escape(full)+r' ',types_text)
        if match is None: raise RuntimeError('Original type metadata missing')
        type_tokens[simple]=0x02000000+int(match[1])
    aliases={'SE.DAD.SESU.Common':'se.dad.sesu.common.dll','SE.DAD.Core.Common':'se.dad.core.common.dll',
             'Newtonsoft.Json':'newtonsoft.json.dll','NCalc':'ncalc.dll','Antlr3.Runtime':'antlr3.runtime.dll'}
    vendor={name:inventory['inputs']['assemblies/'+filename] for name,filename in aliases.items()}
    for row in vendor.values():
        if sha(Path(row['path']).read_bytes())!=row['sha256']:raise RuntimeError('Vendor alias identity')
    facade=ROOT/'research/runtime/toolkit-update-check/sesu-files/microsoft.win32.registry.dll'
    facade_sha='e9a9d281c1a708aaae366f82fd6a1742f65da2918cc4fa5eaaaada0be24277d9'
    historical=json.loads((ROOT/'research/runtime/toolkit-update-check/manifest-v2.json').read_bytes())
    if historical['sesu-files/microsoft.win32.registry.dll']!=facade_sha or sha(facade.read_bytes())!=facade_sha:
        raise RuntimeError('Exact staged forwarding dependency changed')
    aliases['Microsoft.Win32.Registry']='microsoft.win32.registry.dll'
    vendor['Microsoft.Win32.Registry']={'path':str(facade),'bytes':facade.stat().st_size,'sha256':facade_sha}
    quoted=lambda value:json.dumps(value,ensure_ascii=True)
    dictionary=lambda pairs:'new Dictionary<string,string> {'+','.join('{'+quoted(k)+','+quoted(v)+'}' for k,v in pairs)+'}'
    text='using System.Collections.Generic;\nstatic class Pins {\n'
    text+='public const string Prefix='+quoted(PREFIX)+', RootName='+quoted(ROOT_NAME)+', InputSha='+quoted(sha(raw))+';\n'
    text+='public const int RegistryGetValueMemberRef=0x0a000054;\n'
    text+='public const string Sid="S-1-5-21-271988887-4100452682-1621969429-1001";\n'
    text+='public const string MscorlibSha="93d46bdac1664dba87641925572c789d71a21bb01dc7c7e5aa99c0eca8335e5e";\n'
    text+='public const int CheckerToken='+str(type_tokens['Checker'])+', ConditionToken='+str(type_tokens['Condition'])+';\n'
    text+='public static readonly Dictionary<string,string> VendorFiles='+dictionary(aliases.items())+';\n'
    text+='public static readonly Dictionary<string,string> VendorHashes='+dictionary((k,v['sha256']) for k,v in vendor.items())+';\n'
    text+='public static readonly Dictionary<string,string> MethodHashes='+dictionary((k,v['sha256']) for k,v in method_records.items())+';\n'
    text+='public static readonly Dictionary<string,int> MethodTokens=new Dictionary<string,int> {'+','.join('{'+quoted(k)+','+str(v['token'])+'}' for k,v in method_records.items())+'};\n}\n'
    (HERE/'Pins.cs').write_text(text)
    contract={'format':'toolkit-update-registry-admission-contract-v2','original_executed':False,
              'prefix':PREFIX,'root_name':ROOT_NAME,'input_sha256':sha(raw),'input_bytes':len(raw),
              'reviewed_plan_sha256':sha(data),'expected_original_calls':12,'expected_original_errors':2,
              'registry_getvalue_memberref':0x0a000054,'expected_clr_bits':32,'vendor':vendor,'type_tokens':type_tokens,'method_pins':method_records,
              'provenance_root':str(ROOT/'research/runtime/windows-generation-20260915T062650'),
              'ready_sha256':'19de41378e0a061b6871adcae18587fe7598205472b03660ac2eec13eeac0b56',
              'runtime_sha256':'4b223e9ead90082abd4fa40a6c1c320e3d4cfbf5e37bee6f9bc6210181f6c12f',
              'compiler_sha256':'012e8cd8adff0c439a90ffd22c0e33efeb6fbc8cf660d52b4858d310649382fa',
              'mscorlib_sha256':'93d46bdac1664dba87641925572c789d71a21bb01dc7c7e5aa99c0eca8335e5e',
              'user_sid':'S-1-5-21-271988887-4100452682-1621969429-1001',
              'operator_domain':'No general CompareTo collation support claimed by this admission pilot',
              'network_enforcement':'Source whitelists local registry-only original call graph; no dynamic network instrumentation or OS policy change',
              'execution_release_required':'root-reviewed-registry-twelve-v2'}
    (HERE/'contract.json').write_text(json.dumps(contract,indent=2)+'\n')
    print(json.dumps({'prepared':True,'input_bytes':len(raw),'method_pins':len(method_records),'type_tokens':type_tokens,'original_executed':False},indent=2))

if __name__=='__main__':main()
