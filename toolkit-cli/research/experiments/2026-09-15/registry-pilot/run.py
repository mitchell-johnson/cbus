"""Reviewed twelve-leaf Windows pilot; no guest action without explicit release.

An admitted output directory is never reused. Interrupted or failed stages are
inspected from their durable artifacts, never resubmitted by this driver.
"""
from pathlib import Path
import argparse
import hashlib
import io
import json
import os
import re
import stat
import sys
import time
import zipfile

ROOT=Path('/Users/mitchell/source/cbus/toolkit-cli')
HERE=Path(__file__).resolve().parent
sha=lambda b:hashlib.sha256(b).hexdigest()


class Failures:
    def __init__(self): self.first=self.trace=None;self.records=[]
    def remember(self,phase,error):
        if self.first is None:self.first,self.trace=error,error.__traceback__
        try:self.records.append({'phase':phase,'type':type(error).__name__})
        except BaseException:pass
    def attempt(self,phase,call):
        try:return call()
        except BaseException as error:self.remember(phase,error)
    def raise_first(self):
        if self.first is not None:raise BaseException.with_traceback(self.first,self.trace)


def read(path,limit=2097152):
    path=Path(path)
    for component in [path,*path.parents]:
        if stat.S_ISLNK(component.lstat().st_mode):raise ValueError('Symlink input is not admitted')
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW);first=None
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size>limit:raise ValueError('Expected bounded regular input')
        chunks=[];size=0
        while size<=limit:
            data=os.read(fd,min(65536,limit+1-size))
            if not data:break
            chunks.append(data);size+=len(data)
        if size>limit:raise ValueError('Input grew beyond its bound')
        return b''.join(chunks)
    except BaseException as error:first=error;raise
    finally:
        try:os.close(fd)
        except BaseException:
            if first is None:raise


def write(path,data):
    stream=Path(path).open('xb');first=None
    try:stream.write(data);stream.flush();os.fsync(stream.fileno())
    except BaseException as error:first=error;raise
    finally:
        try:stream.close()
        except BaseException:
            if first is None:raise


def json_write(path,value):write(path,(json.dumps(value,indent=2,ensure_ascii=True)+'\n').encode())


def validate_original_provenance(records,contract,compiled_sha256):
    before=records[0]
    if (type(before.get('process_bits')) is not int or before['process_bits']!=32 or before.get('culture')!=''
            or before.get('input_sha256')!=contract['input_sha256'] or before.get('sid')!=contract['user_sid']
            or before.get('type_tokens')!=contract['type_tokens']
            or before.get('method_tokens')!={k:v['token'] for k,v in contract['method_pins'].items()}
            or before.get('methods')!={k:v['sha256'] for k,v in contract['method_pins'].items()}
            or before.get('public_Evaluate_called') is not False or before.get('provider_remapping') is not False):
        raise ValueError('Original invocation identities differ from prepared pins')
    guest='C:\\CBusCliOracle118-88d8\\'+contract['prefix']+'-'
    expected={name:(guest+Path(row['path']).name,row['sha256']) for name,row in contract['vendor'].items()}
    expected.update({'mscorlib':(r'C:\Windows\Microsoft.NET\Framework\v4.0.30319\mscorlib.dll',contract['mscorlib_sha256']),
                     contract['prefix']+'-probe':(guest+'probe.exe',compiled_sha256)})
    baseline=None
    for stage in (before,records[-2]):
        assemblies=stage.get('assemblies')
        if not isinstance(assemblies,list) or not 3<=len(assemblies)<=32:raise ValueError('Bounded assembly inventory required')
        seen={}
        for row in assemblies:
            name=row['name'].split(',',1)[0];path=row['location'];digest=row['sha256'];mvid=row['mvid']
            if (name in seen or not re.fullmatch(r'[a-f0-9]{64}',digest)
                    or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',mvid)):
                raise ValueError('Invalid or duplicate loaded assembly identity')
            if name in expected:
                wanted_path,wanted_digest=expected[name]
                if path.lower()!=wanted_path.lower() or digest!=wanted_digest:raise ValueError('Loaded assembly differs from accepted bytes')
            elif not path.lower().startswith('c:\\windows\\microsoft.net\\'):
                raise ValueError('Unexpected loaded assembly location')
            seen[name]=(row['name'],path,digest,mvid)
        required={'SE.DAD.SESU.Common','mscorlib',contract['prefix']+'-probe'}
        if not required<=seen.keys():raise ValueError('Required original/runtime/probe assembly absent')
        if baseline is not None and any(seen.get(name)!=value for name,value in baseline.items()):
            raise ValueError('Loaded assembly identity changed after original invocation')
        baseline=seen
    if before.get('mscorlib')!=expected['mscorlib'][0]:raise ValueError('Mscorlib location differs')
    if records[1].get('sid')!=contract['user_sid']:raise ValueError('Owned root user identity differs')
    final=records[-1]
    if (final.get('provider_remapping') is not False or type(final.get('network_call_sites_in_whitelisted_original_graph')) is not int
            or final['network_call_sites_in_whitelisted_original_graph']!=0 or final.get('dynamic_network_instrumentation') is not False):
        raise ValueError('Declared provider/network boundary differs')


def validate_capture(raw,plan):
    if len(raw)>262144:raise ValueError('Native stdout exceeds bound')
    text=raw.decode('utf-8-sig')
    if text and not text.endswith('\n'):raise ValueError('Native stdout has incomplete final record')
    records=[json.loads(line) for line in text.splitlines()]
    fixtures=[case for case in plan['cases'] if case['fixture']['value_kind'] is not None]
    expected_stages=['original-pins','root-created']+['fixture']*len(fixtures)
    expected_stages+=['provider-witness','original-call-admitted','original-return']*12
    expected_stages+=['assemblies-after','complete']
    if [r.get('stage') for r in records]!=expected_stages:raise ValueError('Unexpected native stage ordering')
    root=records[1]
    if root.get('root')!='HKEY_CURRENT_USER\\Software\\'+plan['root_name'] or type(root.get('disposition')) is not int or root['disposition']!=1:
        raise ValueError('New owned root identity/disposition not established')
    for row,case in zip(records[2:2+len(fixtures)],fixtures):
        fixture=case['fixture']
        value=fixture['value']
        raw_value=((value+'\0').encode('utf-16-le') if fixture['value_kind']=='REG_SZ' else value.to_bytes(4,'little'))
        kind=1 if fixture['value_kind']=='REG_SZ' else 4
        if row.get('subkey')!=fixture['subkey'] or row.get('entry')!=fixture['entry'] or type(row.get('type')) is not int or row['type']!=kind or row.get('bytes_hex')!=raw_value.hex().upper():
            raise ValueError('Raw fixture association differs')
    witnesses=[r for r in records if r.get('stage')=='provider-witness']
    for row,case in zip(witnesses,plan['cases']):
        expected=case['expected_provider_witness'];condition=case['condition'];what=condition['whatToCheck']
        path=condition['fileOrRegistryKeyPath']
        if path.startswith('HKCU\\'):path='HKEY_CURRENT_USER'+path[4:]
        default=({'kind':'System.Int32','value':1} if what==3 else
                 {'kind':'System.String','value':'23021957-xxx-yy-z-27331bfa-adf0-46be-8d44-18b1a831affe'})
        if (row.get('id')!=case['id'] or row.get('path')!=path or row.get('entry')!=('Test' if what==3 else condition['registryEntryNameOrProductCode'])
                or row.get('default_value')!=default or row.get('result')!={'kind':expected['kind'],'value':expected['value']}
                or row.get('original_call_intercepted') is not False):raise ValueError('Provider witness association differs')
    returns=[r['observation'] for r in records if r.get('stage')=='original-return']
    admitted=[r['id'] for r in records if r.get('stage')=='original-call-admitted']
    wanted=[r['id'] for r in plan['cases']]
    if admitted!=wanted or [r['id'] for r in returns]!=wanted:raise ValueError('Exact twelve original associations required')
    for row,case in zip(returns,plan['cases']):
        expected=case['expected_original'];error=row['error']
        if 'error_type' in expected:
            if not isinstance(error,dict) or error.get('type')!=expected['error_type'] or error.get('message')!=expected['message']:
                raise ValueError('Unexpected original exception: '+case['id'])
        elif error is not None or type(row['result']) is not bool or row['result']!=expected['result']:
            raise ValueError('Unexpected original result: '+case['id'])
    finals=[r for r in records if r.get('stage')=='complete']
    if len(finals)!=1 or records[-1] is not finals[0]:raise ValueError('Exactly one terminal completion record required')
    final=finals[0]
    if (final.get('passed') is not True or type(final.get('original_rows')) is not int or final['original_rows']!=12 or final.get('root_created') is not True
            or final.get('root_absence_verified') is not True or final.get('handles_closed') is not True
            or type(final.get('handle_close_failures')) is not int or final['handle_close_failures']!=0 or final.get('failures')!=[] or final.get('first_error') is not None):
        raise ValueError('Native fixture/original/cleanup completion is not established')
    return {'original_calls':12,'original_expected_errors':sum(r['error'] is not None for r in returns),
            'root_absence_verified':True,'handles_closed':True,'records':records}


def main(release):
    if release!='root-reviewed-registry-twelve-v1':raise ValueError('Exact parent-reviewed release required')
    if sys.version_info[:2] not in ((3,13),(3,10)):raise RuntimeError('Unsupported host interpreter')
    seal=json.loads(read(HERE/'source-seal.json'))
    inputs={}
    for name,row in seal['inputs'].items():
        data=read(row['path'])
        if sha(data)!=row['sha256']:raise RuntimeError('Prepared input changed: '+name)
        inputs[name]=data
    contract=json.loads(inputs['contract.json']);plan=json.loads(inputs['input.json'])
    if sha(inputs['input.json'])!=contract['input_sha256']:raise RuntimeError('Input contract changed')
    interpreter=Path(sys.executable).resolve()
    if not any(Path(row['path'])==interpreter for name,row in seal['inputs'].items() if name.startswith('host/interpreter-')):
        raise RuntimeError('Actual interpreter was not included in the pre-execution seal')
    output=HERE/'pilot-v1';output.mkdir(exist_ok=False)
    errors=Failures();report={'passed':False,'all_original_calls_validated':False,'original_process_started':None,'stages':[],
        'root_name':contract['root_name'],'input_hashes':{k:sha(v) for k,v in inputs.items()},
        'automatic_resubmit':False,'registry_cleanup_claimed':False,'host_version':sys.version,
        'host_interpreter':str(interpreter),'host_interpreter_sha256':sha(read(interpreter)),
        'source_seal_sha256':sha(read(HERE/'source-seal.json'))}
    bridge=provenance=None;started=time.monotonic();old_environment=os.environ.get('CBUS_WINDOWS_PROVENANCE_ROOT')
    def stage(name,script):
        job_id='job-registry-'+name+'-a16df02361e14a1c'
        row={'name':name,'job_id':job_id,'submission_attempted':False,'process_started':None,'process_reaped':False}
        report['stages'].append(row);json_write(output/(name+'-admitted.json'),dict(row,script=script,script_sha256=sha(script.replace('\n','\r\n').encode())))
        row['submission_attempted']=True
        job=bridge.submit(script,job_id=job_id)
        if job!=job_id:raise RuntimeError('Unexpected admitted job ID')
        result=bridge.wait(job,timeout=75)
        row['bridge_result']={k:v for k,v in result.items() if k not in ('stdout','stderr')}
        if result.get('pre_execution') is False and type(result.get('exit_code')) is int:
            row['process_started']=True;row['process_reaped']=True
        for stream in ('stdout','stderr'):
            data=result.get(stream)
            if isinstance(data,bytes):write(output/(name+'.'+stream),data);row[stream+'_sha256']=sha(data)
        if result.get('complete') is not True or result.get('pre_execution') is not False or result.get('admitted') is not True or result.get('exit_code')!=0 or result.get('stderr')!=b'':
            raise RuntimeError('Native '+name+' did not complete successfully; preserved exact stage result')
        return result
    try:
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for name,data in inputs.items():z.writestr(name,data)
        data=archive.getvalue();write(output/'accepted-inputs.zip',data)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if {n:sha(z.read(n)) for n in z.namelist()}!={n:sha(b) for n,b in inputs.items()}:raise RuntimeError('Pre-execution archive mismatch')
        report['archive_sha256']=sha(data);json_write(output/'host-admitted.json',{'release':release,'one_use':True,'root_name':contract['root_name']})
        sys.path.insert(0,str(ROOT))
        from research.windows_bridge import WindowsBridge
        from research.windows_provenance import resolve_windows_provenance
        for module_name,logical in [('research.windows_bridge','host/windows_bridge.py'),('research.windows_provenance','host/windows_provenance.py')]:
            actual=Path(sys.modules[module_name].__file__).resolve()
            if actual!=Path(seal['inputs'][logical]['path']).resolve() or read(actual)!=inputs[logical]:
                raise RuntimeError('Actual imported host helper differs from archived bytes')
        bridge=WindowsBridge();os.environ['CBUS_WINDOWS_PROVENANCE_ROOT']=contract['provenance_root']
        provenance=resolve_windows_provenance(ROOT,bridge);evidence=provenance.as_dict()
        if evidence['file_sha256']['bridge-ready.json']!=contract['ready_sha256'] or evidence['file_sha256']['windows-runtime.json']!=contract['runtime_sha256']:
            raise RuntimeError('Reviewed Windows generation changed; prepare new admission rather than silently replacing it')
        report['provenance']=evidence;json_write(output/'provenance.json',evidence)
        prefix=contract['prefix'];uploads={'probe.cs':inputs['NativeRegistryConditionProbe.cs'],'Pins.cs':inputs['Pins.cs'],'input.json':inputs['input.json']}
        uploads.update({name:inputs['vendor/'+name] for name in (Path(v['path']).name for v in contract['vendor'].values())})
        for suffix in [*uploads,'probe.exe']:
            if bridge.pull(prefix+'-'+suffix,missing_ok=True) is not None:raise RuntimeError('Guest artifact exists; no adoption or replay')
        for suffix,data in uploads.items():bridge.push(prefix+'-'+suffix,data)
        compiler=r'C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe'
        script='@echo off\ncd /d '+bridge.guest_root+'\n'+compiler+' /nologo /platform:x86 /r:System.Web.Extensions.dll /out:'+prefix+'-probe.exe '+prefix+'-probe.cs '+prefix+'-Pins.cs\nexit /b %errorlevel%\n'
        stage('compile',script)
        binary=bridge.pull(prefix+'-probe.exe');write(output/'compiled-probe.exe',binary);report['compiled_probe_sha256']=sha(binary)
        provenance.verify(bridge)
        for suffix,data in uploads.items():
            if bridge.pull(prefix+'-'+suffix)!=data:raise RuntimeError('Guest input changed before original admission')
        for name,row in seal['inputs'].items():
            if read(row['path'])!=inputs[name]:raise RuntimeError('Local source changed before original admission')
        original=stage('original','@echo off\ncd /d '+bridge.guest_root+'\n'+prefix+'-probe.exe\nexit /b %errorlevel%\n')
        report['capture']=validate_capture(original['stdout'],plan)
        validate_original_provenance(report['capture']['records'],contract,report['compiled_probe_sha256'])
        report['all_original_calls_validated']=True
        report['registry_cleanup_claimed']=True
        provenance.verify(bridge)
        report['passed']=True
    except BaseException as error:errors.remember('operation',error)
    finally:
        # No guest diagnostics after interruption. The known job ID and bridge's
        # last_wait evidence permit later read-only inspection without replay.
        if bridge is not None:
            errors.attempt('wait-evidence',lambda:report.update(last_wait_evidence=bridge.last_wait_evidence))
        original_rows=[row for row in report['stages'] if row['name']=='original']
        if original_rows:report['original_process_started']=original_rows[0]['process_started']
        def restore_environment():
            if old_environment is None:os.environ.pop('CBUS_WINDOWS_PROVENANCE_ROOT',None)
            else:os.environ['CBUS_WINDOWS_PROVENANCE_ROOT']=old_environment
        errors.attempt('restore-environment',restore_environment)
        def unchanged():
            report['input_hashes_after']={n:sha(read(r['path'])) for n,r in seal['inputs'].items()}
            if report['input_hashes_after']!=report['input_hashes']:raise RuntimeError('Accepted input changed during run')
        errors.attempt('final-inputs',unchanged)
        report['elapsed_seconds']=errors.attempt('elapsed',lambda:time.monotonic()-started)
        report['passed']=report['passed'] and errors.first is None
        report['errors']=errors.records
        errors.attempt('report',lambda:json_write(output/'report.json',report))
    errors.raise_first()
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--release',required=True)
    args=parser.parse_args();result=main(args.release)
    print(json.dumps({'passed':result['passed'],'root_name':result['root_name'],'report':str(HERE/'pilot-v1/report.json')}))
