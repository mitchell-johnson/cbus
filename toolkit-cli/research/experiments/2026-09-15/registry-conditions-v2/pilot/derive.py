"""Derive a fresh, unexecuted pilot from sealed v1; never touch the old root or job."""
from pathlib import Path
import hashlib
import json

HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'registry-pilot-v1'
sha=lambda data:hashlib.sha256(data).hexdigest()


def replace_once(text,old,new):
    if text.count(old)!=1:raise RuntimeError('Expected one exact source fragment: '+old[:70])
    return text.replace(old,new)


def main():
    identity=json.loads((HERE/'identity.json').read_bytes())
    manifest=json.loads((OLD/'source-copy-manifest.json').read_bytes())
    for name,row in manifest['files'].items():
        if sha((OLD/name).read_bytes())!=row['sha256']:raise RuntimeError('Sealed v1 source changed')
    replacements={'registry-admission-a16df02361e14a1c':identity['prefix'],
                  'CBusCliCondition_a16df02361e14a1c9329771a063bbd4e':identity['root_name'],
                  'a16df02361e14a1c':identity['job_suffix'],
                  'root-reviewed-registry-twelve-v1':identity['release']}
    sources={}
    for name in ('NativeRegistryConditionProbe.cs','prepare.py','run.py','test_guards.py'):
        text=(OLD/name).read_text()
        for old,new in replacements.items():text=text.replace(old,new)
        sources[name]=text
    c=sources['NativeRegistryConditionProbe.cs']
    c=replace_once(c,'static Type Condition, Checker;','static Type Condition, Checker;\n    static MethodInfo RegistryProvider;\n    static object RegistryProviderEvidence;')
    line='        foreach(string name in new[]{"WhatToCheck","HowToCheck","FileOrRegistryKeyPath","RegistryEntryNameOrProductCode","ComparisonRightSideValue"})Properties.Add(name,Condition.GetProperty(name,Flags));'
    addition='''
        LoadVendor("Microsoft.Win32.Registry");
        RegistryProvider=original.ManifestModule.ResolveMethod(Pins.RegistryGetValueMemberRef) as MethodInfo;
        var witness=typeof(Registry).GetMethod("GetValue",new[]{typeof(string),typeof(string),typeof(object)});
        Guard(RegistryProvider!=null&&RegistryProvider.Equals(witness)&&RegistryProvider.DeclaringType==typeof(Registry)&&RegistryProvider.Module.Assembly==typeof(object).Assembly,"exact original/witness Registry.GetValue provider");
        byte[] providerIL=RegistryProvider.GetMethodBody().GetILAsByteArray();Guard(providerIL.Length<=8192,"provider IL bound");
        RegistryProviderEvidence=new {source_memberref=Pins.RegistryGetValueMemberRef,declaring_type=RegistryProvider.DeclaringType.FullName,method=RegistryProvider.Name,return_type=RegistryProvider.ReturnType.FullName,parameter_types=RegistryProvider.GetParameters().Select(p=>p.ParameterType.FullName).ToArray(),assembly=RegistryProvider.Module.Assembly.FullName,location=RegistryProvider.Module.Assembly.Location,sha256=Hash(Read(RegistryProvider.Module.Assembly.Location,33554432)),method_token=RegistryProvider.MetadataToken,il_bytes_hex=BitConverter.ToString(providerIL).Replace("-",""),same_original_and_witness=true,type_remapping=false};'''
    c=replace_once(c,line,line+addition)
    c=replace_once(c,'method_tokens=Pins.MethodTokens,methods=Pins.MethodHashes,assemblies=Assemblies()',
                   'method_tokens=Pins.MethodTokens,methods=Pins.MethodHashes,registry_provider=RegistryProviderEvidence,assemblies=Assemblies()')
    c=replace_once(c,'object witness=Registry.GetValue(query,queryEntry,defaultValue);',
                   'object witness=RegistryProvider.Invoke(null,new[]{(object)query,queryEntry,defaultValue});')
    sources['NativeRegistryConditionProbe.cs']=c
    p=sources['prepare.py']
    p=replace_once(p,"    quoted=lambda value:json.dumps(value,ensure_ascii=True)",'''    facade=ROOT/'research/runtime/toolkit-update-check/sesu-files/microsoft.win32.registry.dll'
    facade_sha='e9a9d281c1a708aaae366f82fd6a1742f65da2918cc4fa5eaaaada0be24277d9'
    historical=json.loads((ROOT/'research/runtime/toolkit-update-check/manifest-v2.json').read_bytes())
    if historical['sesu-files/microsoft.win32.registry.dll']!=facade_sha or sha(facade.read_bytes())!=facade_sha:
        raise RuntimeError('Exact staged forwarding dependency changed')
    aliases['Microsoft.Win32.Registry']='microsoft.win32.registry.dll'
    vendor['Microsoft.Win32.Registry']={'path':str(facade),'bytes':facade.stat().st_size,'sha256':facade_sha}
    quoted=lambda value:json.dumps(value,ensure_ascii=True)''')
    p=replace_once(p,"    text+='public const string Sid=", "    text+='public const int RegistryGetValueMemberRef=0x0a000054;\\n'\n    text+='public const string Sid=")
    p=replace_once(p,"'expected_clr_bits':32,'vendor':vendor", "'registry_getvalue_memberref':0x0a000054,'expected_clr_bits':32,'vendor':vendor")
    p=p.replace("toolkit-update-registry-admission-contract-v1","toolkit-update-registry-admission-contract-v2")
    sources['prepare.py']=p
    r=sources['run.py'].replace("HERE/'pilot-v1'","HERE/'pilot-v2'").replace("HERE/'pilot-v1/report.json'","HERE/'pilot-v2/report.json'")
    marker="    guest='C:\\\\CBusCliOracle118-88d8\\\\'+contract['prefix']+'-'"
    extra='''    provider=before.get('registry_provider')
    if (not isinstance(provider,dict) or type(provider.get('source_memberref')) is not int
            or provider['source_memberref']!=contract['registry_getvalue_memberref']
            or provider.get('declaring_type')!='Microsoft.Win32.Registry' or provider.get('method')!='GetValue'
            or provider.get('return_type')!='System.Object' or provider.get('parameter_types')!=['System.String','System.String','System.Object']
            or provider.get('assembly')!='mscorlib, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089'
            or provider.get('location')!=r'C:\\Windows\\Microsoft.NET\\Framework\\v4.0.30319\\mscorlib.dll'
            or provider.get('sha256')!=contract['mscorlib_sha256'] or type(provider.get('method_token')) is not int
            or provider['method_token']>>24!=6 or not isinstance(provider.get('il_bytes_hex'),str)
            or not re.fullmatch(r'(?:[A-F0-9]{2}){1,8192}',provider['il_bytes_hex'])
            or provider.get('same_original_and_witness') is not True or provider.get('type_remapping') is not False):
        raise ValueError('Exact original/witness registry provider resolution not established')
'''
    r=replace_once(r,marker,extra+marker)
    r=replace_once(r,"required={'SE.DAD.SESU.Common','mscorlib',contract['prefix']+'-probe'}", "required={'SE.DAD.SESU.Common','Microsoft.Win32.Registry','mscorlib',contract['prefix']+'-probe'}")
    sources['run.py']=r
    t=sources['test_guards.py']
    t=replace_once(t,"        assemblies=[]",'''        rows[0]['registry_provider']={'source_memberref':contract['registry_getvalue_memberref'],'declaring_type':'Microsoft.Win32.Registry',
            'method':'GetValue','return_type':'System.Object','parameter_types':['System.String','System.String','System.Object'],
            'assembly':'mscorlib, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089','location':rows[0]['mscorlib'],
            'sha256':contract['mscorlib_sha256'],'method_token':0x06000001,'il_bytes_hex':'2A','same_original_and_witness':True,'type_remapping':False}
        assemblies=[]''')
    t=replace_once(t,"                                 ('mscorlib',rows[0]['mscorlib'],contract['mscorlib_sha256']),", "                                 ('Microsoft.Win32.Registry',guest+'microsoft.win32.registry.dll',contract['vendor']['Microsoft.Win32.Registry']['sha256']),\n                                 ('mscorlib',rows[0]['mscorlib'],contract['mscorlib_sha256']),")
    t=replace_once(t,"                       lambda r:r[0].update(culture='en-US'),", "                       lambda r:r[0]['registry_provider'].update(same_original_and_witness=False),\n                       lambda r:r[0]['registry_provider'].update(source_memberref=0x0a000055),\n                       lambda r:r[0]['registry_provider'].update(type_remapping=True),\n                       lambda r:r[0].update(culture='en-US'),")
    sources['test_guards.py']=t
    for name,text in sources.items():(HERE/name).write_text(text)
    (HERE/'original-types.txt').write_bytes((OLD/'original-types.txt').read_bytes())
    (HERE/'derivation.json').write_text(json.dumps({'format':'registry-pilot-v2-source-derivation','old_original_failure_preserved':True,'original_execution_authorized':False,
        'identity':identity,'added_assembly_aliases':['Microsoft.Win32.Registry'],'old_source_hashes':{n:manifest['files'][n]['sha256'] for n in sources},
        'derived_source_hashes':{n:sha((HERE/n).read_bytes()) for n in sources},'extra_scope':'Resolve original MemberRef and require same Framework Registry.GetValue provider as separate witness before any registry writes; capture provider IL without invoking it.'},indent=2)+'\n')


if __name__=='__main__':main()
