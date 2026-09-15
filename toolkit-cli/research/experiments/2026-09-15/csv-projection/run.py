"""Held, file-backed, network-denied launcher for the reviewed twelve cases."""
from __future__ import annotations
import hashlib
import importlib.util
import io
import json
import os
import stat
from pathlib import Path
import sys
import tarfile

BASE=Path(__file__).resolve().parent
REPO=Path('/Users/mitchell/source/cbus/toolkit-cli')
HELPER=REPO/'research/toolkit_database_csv_original.py'
HELPER_SHA='4a18e3885a388eaeb54ab163311b568eda1570a6f06363fe1f8191053c96cad4'
TOKEN='b0f8078731a54cc4aa069f00b043d210'
LIBRARIES={'016084c6e70d929249a2abb22f1afda95095294e6cd70f509964ffc54006bf94','7207c8e3d7a63118fb0bca73e01816797fd51b1d8a39a4cbc7abfd562ee59c85'}

def sha(raw):return hashlib.sha256(raw).hexdigest()
def check(condition,message):
    if not condition:raise RuntimeError(message)
def read(path, limit=64*1024*1024):
    # Nonblocking descriptor admission prevents FIFO/device paths from stalling
    # before the child deadline. No-follow rejects a final symlink component.
    descriptor=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW);first=None
    try:
        info=os.fstat(descriptor)
        check(stat.S_ISREG(info.st_mode),'Regular input required: '+str(path))
        check(info.st_size<=limit,'Input byte bound: '+str(path))
        chunks=[];size=0
        while size<=limit:
            chunk=os.read(descriptor,min(65536,limit+1-size))
            if not chunk:break
            chunks.append(chunk);size+=len(chunk)
        check(size<=limit,'Input byte bound: '+str(path))
        return b''.join(chunks)
    except BaseException as error:first=error;raise
    finally:
        try:os.close(descriptor)
        except BaseException:
            if first is None:raise


def archive_inputs(out,inputs):
    archive=tarfile.open(out/'inputs.tar.gz','x:gz');first=None
    try:
        for index,(path,raw) in enumerate(inputs.items()):
            info=tarfile.TarInfo(str(index)+'/'+path.name);info.size=len(raw);info.mtime=0
            archive.addfile(info,io.BytesIO(raw))
    except BaseException as error:first=error;raise
    finally:
        try:archive.close()
        except BaseException:
            if first is None:raise
    archive=tarfile.open(out/'inputs.tar.gz','r:gz');first=None
    try:
        for index,(path,raw) in enumerate(inputs.items()):
            stream=archive.extractfile(str(index)+'/'+path.name)
            check(stream is not None,'Archive member missing')
            member_error=None
            try:observed=stream.read(len(raw)+1)
            except BaseException as error:member_error=error;raise
            finally:
                try:stream.close()
                except BaseException:
                    if member_error is None:raise
            check(observed==raw,'Archive pre-execution verification')
    except BaseException as error:first=error;raise
    finally:
        try:archive.close()
        except BaseException:
            if first is None:raise

def main():
    check(sys.version_info[:2] in ((3,10),(3,13)),'Research runtime must be Python3.10 or3.13')
    check(len(sys.argv)==2,'New owned output child required')
    output=Path(sys.argv[1]);check(output.parent.resolve()==BASE and not output.exists() and not output.is_symlink(),'Fresh direct owned output')
    ownership=json.loads(read(BASE.parent/'ownership.json',4096))
    check(ownership['owner_token']==TOKEN and ownership['root']==str(BASE.parent) and ownership['volume_uuid']=='24F890EF-A1B9-4B52-8E18-823080A2F0BB','Exact external ownership')
    check(sys.platform=='darwin' and Path('/usr/bin/sandbox-exec').is_file(),'Requires local macOS network denial')
    source=BASE/'NativeCachedCSVProbe.py';cases=BASE/'cases.json';admission_path=BASE/'admission.json'
    admission=json.loads(read(admission_path,4096))
    check(admission=={'format':'csv-projection-admission-v1','probe_sha256':sha(read(source)), 'cases_sha256':sha(read(cases)), 'authorization':'root-reviewed-cached-csv-pilot12-v1'},'Exact reviewed admission required before launch')
    paths=[Path(__file__).resolve(),HELPER,source,cases,admission_path,BASE/'PROPOSAL.md',BASE.parent/'ownership.json',
       REPO/'research/NativeToolkitDatabaseCSVProbe.py',REPO/'research/vendor/toolkit/app/CBusToolkit.exe',REPO/'research/vendor/toolkit/app/CBusToolkit.map',Path(sys.executable).resolve()]
    for name in ('capstone','unicorn','pefile'):
        spec=importlib.util.find_spec(name);check(spec is not None and spec.origin,'Missing runtime dependency')
        path=Path(spec.origin).resolve();paths.append(path)
        if name!='pefile':
            paths.extend(sorted(path.parent.rglob('*.py')));paths.extend(sorted(path.parent.rglob('*.dylib')))
    paths=list(dict.fromkeys(paths));inputs={p:read(p) for p in paths}
    check(sha(inputs[HELPER])==HELPER_SHA,'Accepted first-error launcher helper changed')
    check(LIBRARIES<={sha(raw) for p,raw in inputs.items() if p.suffix=='.dylib'},'Actual emulation-library pins')
    spec=importlib.util.spec_from_file_location('csv_original_accepted_launcher',HELPER)
    helper=importlib.util.module_from_spec(spec);exec(compile(inputs[HELPER],str(HELPER),'exec'),helper.__dict__)
    check(sha(read(HELPER))==HELPER_SHA,'Launcher changed during import')
    output.mkdir();report={'format':'cbus-cached-csv-launch-v1','passed':False,'before':{str(p):sha(raw) for p,raw in inputs.items()},'case_count':12,'vm_calls':False,'native_network_calls':False}
    first=None
    try:
        archive_inputs(output,inputs)
        report['archive_sha256']=sha(read(output/'inputs.tar.gz',128*1024*1024))
        marker={'format':'csv-cached-owned-launch-v1','owner_token':TOKEN,'probe_sha256':sha(inputs[source]),'cases_sha256':sha(inputs[cases])}
        marker_raw=(json.dumps(marker,indent=2)+'\n').encode();stream=(output/'launch-owned.json').open('xb');write_error=None
        try:stream.write(marker_raw);stream.flush();os.fsync(stream.fileno())
        except BaseException as error:write_error=error;raise
        finally:
            try:stream.close()
            except BaseException:
                if write_error is None:raise
        environment={k:v for k,v in os.environ.items() if k not in ('PYTHONHOME','PYTHONPATH')}
        environment.update(PYTHONDONTWRITEBYTECODE='1',TMPDIR=str(output),TMP=str(output),TEMP=str(output))
        command=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)',str(Path(sys.executable).absolute()),'-I',str(source),'execute',str(output/'capture')]
        report['command']=command;report['exit_code']=helper._run(command,environment,output,report)
        check(report['exit_code']==0 and (output/'stderr.txt').stat().st_size==0,'Original process failed; preserve its first run')
        capture_raw=read(output/'capture/report.json',8*1024*1024);capture=json.loads(capture_raw)
        check(capture['capture_complete'] and len(capture['results'])==12 and all(r['captured'] for r in capture['results']),'Complete finite capture required')
        check([r['case'] for r in capture['results']]==json.loads(inputs[cases]),'Every echoed case field')
        check([r['completed'] for r in capture['results']]==[c['expected_complete'] for c in json.loads(inputs[cases])],'Independent completion sequence')
        check(set(capture['runtime']['libraries'].values())==LIBRARIES and capture['runtime_after']==capture['runtime']['libraries'],'Actual runtime association')
        check(all(capture['inputs'].get(str(p))==sha(inputs[p]) for p in (source,cases,REPO/'research/NativeToolkitDatabaseCSVProbe.py',REPO/'research/vendor/toolkit/app/CBusToolkit.exe',REPO/'research/vendor/toolkit/app/CBusToolkit.map')),'Archived/executed source association')
        report['capture']={'path':str(output/'capture/report.json'),'sha256':sha(capture_raw)}
        report['original_completed_cases']=sum(r['completed'] for r in capture['results']);report['expected_partial_cases']=sum(not r['completed'] for r in capture['results'])
        report['passed']=True
    except BaseException as error:first=error;report['error']={'type':type(error).__name__}
    finally:
        report['after']={};report['postcheck_errors']=[];report['partial_capture_artifacts']={}
        def postcheck(label,operation):
            nonlocal first
            try:return operation()
            except BaseException as error:
                try:message=str(error)
                except BaseException:message='<unprintable>'
                report['postcheck_errors'].append({'check':label,'type':type(error).__name__,'message':message[:2048]})
                report['passed']=False
                if first is None:first=error
                return None
        for path,raw in inputs.items():
            value=postcheck(str(path),lambda path=path:sha(read(path)))
            if value is not None:
                report['after'][str(path)]=value
                postcheck('source/runtime equality '+str(path),lambda value=value,raw=raw:check(value==sha(raw),'Source/runtime input changed'))
        for relative in ('capture/report.json','capture/report.pending.json'):
            path=output/relative
            exists=postcheck(relative+' exists',path.exists)
            if exists:
                raw=postcheck(relative+' bytes',lambda path=path:read(path,8*1024*1024))
                if raw is not None:
                    report['partial_capture_artifacts'][relative]={'sha256':sha(raw),'bytes':len(raw)}
                    parsed=postcheck(relative+' JSON',lambda raw=raw:json.loads(raw))
                    if type(parsed) is dict:
                        report['partial_capture_artifacts'][relative]['capture_complete']=parsed.get('capture_complete')
                        report['partial_capture_artifacts'][relative]['error']=parsed.get('error')
        helper._finish_report(output,report,first)
    if first is not None:raise first
    print(json.dumps({'passed':True,'cases':12,'report':str(output/'report.json')}))

if __name__=='__main__':main()
