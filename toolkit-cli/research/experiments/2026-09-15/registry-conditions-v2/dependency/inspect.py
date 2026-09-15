"""Read only staged PE metadata; never execute any original method or guest job."""
from pathlib import Path
import hashlib
import json
import os
import re
import struct
import subprocess

import pefile

ROOT=Path('/Users/mitchell/source/cbus/toolkit-cli')
HERE=Path(__file__).resolve().parent
STAGED=ROOT/'research/runtime/toolkit-update-check'
MONO=ROOT/'research/runtime/mono-macos-owned/expanded/mono.pkg/Payload/Library/Frameworks/Mono.framework/Versions/6.12.0'
sha=lambda data:hashlib.sha256(data).hexdigest()


def main():
    manifest_path=STAGED/'manifest-v2.json';manifest=json.loads(manifest_path.read_bytes())
    filename='microsoft.win32.registry.dll';forwarder=STAGED/'sesu-files'/filename
    expected='e9a9d281c1a708aaae366f82fd6a1742f65da2918cc4fa5eaaaada0be24277d9'
    if manifest['sesu-files/'+filename]!=expected or sha(forwarder.read_bytes())!=expected:
        raise RuntimeError('Staged forwarder disagrees with historical manifest')
    common=STAGED/'sesu-files/se.dad.sesu.common.dll';raw=common.read_bytes()
    if sha(raw)!='477fb88de310852611f26d1f845da23b8f0e6b602de8ab61a3eefc06339dc4ba':
        raise RuntimeError('Original common DLL differs')
    inputs={str(path):{'sha256':sha(path.read_bytes()),'bytes':path.stat().st_size} for path in
            (Path(__file__),manifest_path,forwarder,common,MONO/'bin/monodis64',MONO/'lib/libmonoboehm-2.0.1.dylib') if path.exists()}
    (HERE/'input-pins.json').write_text(json.dumps(inputs,indent=2)+'\n')
    env=dict(os.environ,DYLD_FALLBACK_LIBRARY_PATH=str(MONO/'lib'))
    results={}
    for target,path,option in [('forwarder',forwarder,'--assembly'),('forwarder',forwarder,'--assemblyref'),
                               ('forwarder',forwarder,'--exported'),('forwarder',forwarder,'--typedef'),
                               ('forwarder',forwarder,'--method'),('common',common,'--typeref')]:
        command=[str(MONO/'bin/monodis64'),option,str(path)]
        result=subprocess.run(command,env=env,capture_output=True,timeout=20)
        name=target+'-'+option[2:]
        (HERE/(name+'.stdout')).write_bytes(result.stdout);(HERE/(name+'.stderr')).write_bytes(result.stderr)
        results[name]={'command':command,'exit_code':result.returncode,'stdout_sha256':sha(result.stdout),'stderr_sha256':sha(result.stderr)}
        if result.returncode!=0 or result.stderr or len(result.stdout)>262144:raise RuntimeError('Metadata inspection did not complete')
    exported=(HERE/'forwarder-exported.stdout').read_text()
    refs=(HERE/'forwarder-assemblyref.stdout').read_text()
    methods=(HERE/'forwarder-method.stdout').read_text()
    types=(HERE/'forwarder-typedef.stdout').read_text()
    if len(re.findall(r'(?m)^\d+: Version=',refs))!=1 or 'Name=mscorlib' not in refs:
        raise RuntimeError('Forwarder has unreviewed assembly dependency')
    if 'Microsoft.Win32.Registry is in assemblyref 1, index=0, flags=0x200000' not in exported:
        raise RuntimeError('Registry forwarding metadata differs')
    if 'Method Table (1..0)' not in methods or 'Typedef Table' not in types:
        raise RuntimeError('Expected method-free facade')
    pe=pefile.PE(data=raw);calls=[]
    for name,rva,il in [('EvaluateRegistryKeyExists',0x2980,0x39),('EvaluateRegistryEntryExists',0x2aa0,0x5e),('EvaluateRegistryEntryContent',0x2b8c,0x64)]:
        offset=pe.get_offset_from_rva(rva);header=raw[offset]
        start=offset+1 if header&3==2 else offset+(struct.unpack_from('<H',raw,offset)[0]>>12)*4
        if raw[start+il]!=0x28:raise RuntimeError('Expected original call opcode')
        token=struct.unpack_from('<I',raw,start+il+1)[0]
        if token>>24!=0x0a:raise RuntimeError('Expected original MemberRef')
        calls.append({'method':name,'rva':rva,'il_offset':il,'get_value_memberref_token':token})
    if len({row['get_value_memberref_token'] for row in calls})!=1:raise RuntimeError('Registry provider references differ')
    for path,row in inputs.items():
        if sha(Path(path).read_bytes())!=row['sha256']:raise RuntimeError('Input changed during metadata inspection')
    report={'format':'registry-staged-forwarder-inspection-v1','original_methods_executed':False,'guest_access':False,
            'forwarder_sha256':expected,'historical_manifest_sha256':sha(manifest_path.read_bytes()),
            'forwarder_assembly':'Microsoft.Win32.Registry, Version=5.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a',
            'forwarder_method_count':0,'implementation_assembly_reference':'mscorlib, Version=4.0.0.0, PublicKeyToken=b77a5c561934e089',
            'extra_staged_dependencies_needed':['Microsoft.Win32.Registry'],'original_provider_calls':calls,'inspections':results,
            'runtime_resolution_still_to_verify':'Resolve the original MemberRef before registry writes and require the exact same Registry.GetValue MethodInfo used for the separate witness.',
            'scope':'A forwarding assembly has no independent GetValue implementation. The first witness ran the pinned Framework mscorlib provider; actual original resolution must be proved in a fresh reviewed pilot.'}
    (HERE/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'report_sha256':sha((HERE/'report.json').read_bytes()),'original_provider_calls':calls},indent=2))


if __name__=='__main__':main()
