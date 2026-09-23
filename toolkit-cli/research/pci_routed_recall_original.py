"""Local process evidence only; never retries an original process."""
import base64
import hashlib
import json
import subprocess
import time


def description(error):
    result={'class':type(error).__name__}
    try:result['message']=str(error)
    except BaseException:result['message']='<unavailable>'
    return result


class Failures:
    def __init__(self):
        self.first=None
        self.traceback=None
        self.records=[]
    def remember(self, stage, error):
        if self.first is None:self.first,self.traceback=error,error.__traceback__
        try:self.records.append({'stage':stage,**description(error)})
        except BaseException:pass
    def attempt(self, stage, operation):
        try:return operation()
        except BaseException as error:self.remember(stage,error)
    def raise_first(self):
        if self.first is not None:raise BaseException.with_traceback(self.first, self.traceback)


def plan_tsv(plans):
    lines=[]
    for c in plans:
        values=[c['id'],str(c['unit']),str(c['parameter']),str(c['count']),','.join(map(str,c['bridges'])) or '-',
                str(c['root']),str(c['context']),c['cache'],str(int(c['n'])),str(int(c['t'])),str(int(c['active'])),
                c['tag'],','.join(base64.b64encode(raw.encode('ascii')).decode('ascii') for raw in c['raws']),
                ';'.join(c['operations']) or '-']
        lines.append('\t'.join(values))
    return ('\n'.join(lines)+'\n').encode('ascii')


def run_process(stage, command, *, destination, environment, failures, timeout=30, popen=subprocess.Popen):
    """Always file-backed output; record start/reap separately from exit success."""
    record={'stage':stage,'command':command,'launch_attempted':False,'started':False,
            'completed':False,'exit_code':None,'timeout':False,'resubmitted':False}
    streams=[];process=None;clock=time.monotonic()
    try:
        for suffix in ('stdout','stderr'):
            streams.append((destination/(stage+'.'+suffix)).open('xb',buffering=0))
        record['launch_attempted']=True
        process=popen(command,cwd=destination,env=environment,stdout=streams[0],stderr=streams[1],start_new_session=True)
        record['started']=True;record['pid']=process.pid
        record['exit_code']=process.wait(timeout=timeout)
        record['completed']=True
    except BaseException as error:
        record['timeout']=isinstance(error,subprocess.TimeoutExpired)
        failures.remember(stage,error)
        if process is not None:
            # Exact locally returned Popen only; no group/shared-process operation.
            failures.attempt(stage+'.kill_owned_process',process.kill)
            def reap():
                record['exit_code']=process.wait(timeout=5)
                record['completed']=True
            failures.attempt(stage+'.reap_owned_process',reap)
    finally:
        for index,stream in enumerate(streams):
            failures.attempt(stage+'.close_'+str(index),stream.close)
        record['duration_seconds']=time.monotonic()-clock
    for suffix in ('stdout','stderr'):
        def output_stat(suffix=suffix):
            path=destination/(stage+'.'+suffix)
            record[suffix+'_bytes']=path.stat().st_size
            record[suffix+'_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        failures.attempt(stage+'.inspect_'+suffix,output_stat)
    return record


def semantic(value):
    """Retain all original fields except nondeterministic reply timestamps."""
    if type(value) is dict:
        return {key: ('<original UTC milliseconds>' if key == 'aW.N' and type(item) is int and item > 0
                      else semantic(item)) for key,item in value.items()
                if key not in ('utc_milliseconds_before','utc_milliseconds_after')}
    if type(value) is list:
        return [semantic(item) for item in value]
    return value


def semantic_digest(value):
    return hashlib.sha256(json.dumps(semantic(value),sort_keys=True,separators=(',',':')).encode()).hexdigest()


def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        while True:
            block=stream.read(65536)
            if not block:break
            result.update(block)
    return result.hexdigest()


def run_original(root, *, java, javac, jar, destination):
    """Fresh exact428 matrix; no sender/receiver/VM/shared service is invoked."""
    from pathlib import Path
    import os
    import shutil
    import sys
    import zipfile
    if sys.platform!='darwin' or sys.version_info[:2] not in ((3,10),(3,13)):
        raise ValueError('Explicit macOS Python3.10/3.13 original probe required')
    root=Path(root).resolve(strict=True)
    java,javac,jar=(Path(p).resolve(strict=True) for p in (java,javac,jar))
    destination=Path(destination).absolute()
    if destination.parent.resolve(strict=True)!=destination.parent:
        raise ValueError('Original output parent must be an existing resolved directory')
    source=root/'research/NativeRoutedRecallProbe.java'
    fixture_path=root/'research/fixtures/pci-routed-recall-original-vectors.json'
    fixture=json.loads(fixture_path.read_text())
    assert digest(source)==fixture['source_sha256']
    assert digest(jar)==fixture['jar_sha256']
    plans=[r['input'] for r in fixture['cases']]
    assert len(plans)==428 and len({p['id'] for p in plans})==428
    data=plan_tsv(plans)
    assert hashlib.sha256(data).hexdigest()==fixture['tsv_sha256']
    paths=[source,fixture_path,Path(__file__).resolve(),java,javac,jar,java.parent.parent/'lib/modules',Path(sys.executable).resolve()]
    before={str(p):digest(p) for p in paths}
    destination.mkdir(exist_ok=False)
    failures=Failures()
    report={'format':'pci-routed-recall-fresh-original-v1','passed':False,
            'python_version':sys.version,'python_executable':sys.executable,'inputs_before':before,
            'network_denied':True,'processes':[],'vm_or_shared_service_used':False}
    compiled=[]
    try:
        for name in ('tmp','home'):(destination/name).mkdir()
        shutil.copyfile(source,destination/source.name)
        assert digest(destination/source.name)==before[str(source)]
        (destination/'input.tsv').write_bytes(data)
        profile=destination/'network-denied.sb';profile.write_text('(version 1)\n(allow default)\n(deny network*)\n')
        with zipfile.ZipFile(destination/'pre-execution-inputs.zip','x',zipfile.ZIP_DEFLATED) as archive:
            for path in (source,fixture_path,Path(__file__).resolve()):
                raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==before[str(path)]
                archive.writestr(str(path.relative_to(root)),raw)
            archive.writestr('input.tsv',data)
            archive.writestr('runtime-input-hashes.json',json.dumps(before,sort_keys=True))
        with zipfile.ZipFile(destination/'pre-execution-inputs.zip') as archive:
            for path in (source,fixture_path,Path(__file__).resolve()):
                assert hashlib.sha256(archive.read(str(path.relative_to(root)))).hexdigest()==before[str(path)]
            assert archive.read('input.tsv')==data
        sandbox=['/usr/bin/sandbox-exec','-f',str(profile)]
        commands=[sandbox+[str(javac),'-encoding','UTF-8','-classpath',str(jar),'-d',str(destination),str(destination/source.name)],
            sandbox+[str(java),'-XX:-UsePerfData','-Djava.io.tmpdir='+str(destination/'tmp'),
                '-Duser.home='+str(destination/'home'),'-Djava.awt.headless=true','-classpath',str(destination)+':'+str(jar),
                'NativeRoutedRecallProbe',str(destination/'input.tsv'),str(destination)]]
        environment={'PATH':'/usr/bin:/bin','HOME':str(destination/'home'),'TMPDIR':str(destination/'tmp')+'/',
                     'LANG':'en_US.UTF-8'}
        for stage,command in zip(('compile','original'),commands):
            if stage=='original':
                compiled=[destination/source.name,destination/'input.tsv',profile,*sorted(destination.glob('*.class'))]
                report['compiled_before']={p.name:digest(p) for p in compiled}
                (destination/'original-before.json').write_text(json.dumps(report['compiled_before'],indent=2)+'\n')
            process=run_process(stage,command,destination=destination,environment=environment,failures=failures)
            report['processes'].append(process);failures.raise_first()
            assert process['exit_code']==0
        assert (destination/'original.stderr').read_bytes()==b''
        rows=[json.loads(line) for line in (destination/'original.stdout').read_text().splitlines()]
        assert rows[0]==fixture['runtime'] and rows[-1]=={'kind':'complete','cases':428}
        assert len(rows)==430
        comparisons=[]
        for row,expected in zip(rows[1:-1],fixture['cases']):
            assert row['id']==expected['input']['id']
            actual=semantic_digest(row)
            assert actual==expected['semantic_sha256'],row['id']
            for action in row['actions']:
                start,end=action['utc_milliseconds_before'],action['utc_milliseconds_after']
                assert type(start) is type(end) is int and start<=end
                if action['after']['aW.N']!=action['before']['aW.N']:
                    assert start<=action['after']['aW.N']<=end
            comparisons.append({'id':row['id'],'semantic_sha256':actual})
        report['cases']=428;report['comparisons']=comparisons;report['passed']=True
    except BaseException as error:
        if failures.first is not error:failures.remember('original_execution_or_comparison',error)
    finally:
        def verify():
            report['inputs_after']={str(p):digest(p) for p in paths}
            assert report['inputs_after']==before
            report['inputs_unchanged']=True
            if compiled:
                report['compiled_after']={p.name:digest(p) for p in compiled}
                assert report['compiled_after']==report['compiled_before']
                report['compiled_unchanged']=True
        failures.attempt('verify_original_inputs',verify)
        def artifacts():report['artifacts']={str(p.relative_to(destination)):digest(p) for p in destination.rglob('*') if p.is_file()}
        failures.attempt('hash_artifacts',artifacts)
        report['passed']=report['passed'] and failures.first is None
        report['failures']=list(failures.records)
        stream=None
        try:
            stream=(destination/'report.json').open('x')
            stream.write(json.dumps(report,indent=2)+'\n')
        except BaseException as error:failures.remember('write_report',error)
        finally:
            if stream is not None:failures.attempt('close_report',stream.close)
    failures.raise_first()
    return report
