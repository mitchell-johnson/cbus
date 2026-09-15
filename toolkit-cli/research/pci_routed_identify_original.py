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
        values=[c['id'],str(c['unit']),str(c['parameter']),','.join(map(str,c['bridges'])) or '-',
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
        def finish_clock():record['duration_seconds']=time.monotonic()-clock
        failures.attempt(stage+'.finish_clock',finish_clock)
    for suffix in ('stdout','stderr'):
        def output_stat(suffix=suffix):
            path=destination/(stage+'.'+suffix)
            record[suffix+'_bytes']=path.stat().st_size
            record[suffix+'_sha256']=digest(path)
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


def _file(path, *, limit, collect=False):
    """Bounded regular descriptors; first read failure wins over close failure."""
    import os
    import stat
    flags=os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    descriptor=os.open(path,flags);first=None;size=0;hasher=hashlib.sha256();parts=[]
    try:
        state=os.fstat(descriptor)
        if not stat.S_ISREG(state.st_mode) or state.st_size>limit:
            raise ValueError('Input must be a bounded regular file')
        while True:
            block=os.read(descriptor,min(65536,limit+1-size))
            if not block:break
            size+=len(block)
            if size>limit:raise ValueError('Input exceeded its byte bound')
            if collect:parts.append(block)
            else:hasher.update(block)
        return b''.join(parts) if collect else hasher.hexdigest()
    except BaseException as error:
        first=error
        raise
    finally:
        try:os.close(descriptor)
        except BaseException:
            if first is None:raise


def digest(path):
    return _file(path,limit=512*1024*1024)


def read_bytes(path):
    return _file(path,limit=16*1024*1024,collect=True)


def run_original(root, *, java, javac, jar, destination):
    """Fresh exact902 in two bounded processes; no sender or shared service."""
    from pathlib import Path
    import sys
    import zipfile
    if sys.platform != 'darwin' or sys.version_info[:2] not in ((3,10),(3,13)):
        raise ValueError('Explicit macOS Python3.10/3.13 original probe required')
    root=Path(root).resolve(strict=True)
    java,javac,jar=(Path(p).resolve(strict=True) for p in (java,javac,jar))
    destination=Path(destination).absolute()
    if destination.parent.resolve(strict=True)!=destination.parent:
        raise ValueError('Original output parent must be an existing resolved directory')
    source=root/'research/NativeRoutedIdentifyProbe.java'
    fixture_path=root/'research/fixtures/pci-routed-identify-original-vectors.json'
    fixture=json.loads(read_bytes(fixture_path))
    assert digest(source)==fixture['source_sha256']
    assert digest(jar)==fixture['jar_sha256']
    batches=fixture['batches']
    assert [b['name'] for b in batches]==['batch-00','batch-01']
    assert [len(b['cases']) for b in batches]==[480,422]
    ids=[r['input']['id'] for b in batches for r in b['cases']]
    assert len(ids)==len(set(ids))==902
    inputs={}
    for batch in batches:
        data=plan_tsv([r['input'] for r in batch['cases']])
        assert hashlib.sha256(data).hexdigest()==batch['tsv_sha256']
        inputs[batch['name']+'.tsv']=data
    paths=[source,fixture_path,Path(__file__).resolve(),java,javac,jar,java.parent.parent/'lib/modules',Path(sys.executable).resolve()]
    before={str(p):digest(p) for p in paths}
    destination.mkdir(exist_ok=False)
    failures=Failures()
    report={'format':'pci-routed-identify-fresh-original-v1','passed':False,
            'python_version':sys.version,'python_executable':sys.executable,'inputs_before':before,
            'network_denied':True,'processes':[],'vm_or_shared_service_used':False,
            'historical_research':fixture['historical_research'],'comparisons':[]}
    compiled=[]
    try:
        for name in ('tmp','home'):(destination/name).mkdir()
        pinned_files={str(p.relative_to(root)):read_bytes(p) for p in (source,fixture_path,Path(__file__).resolve())}
        for p in (source,fixture_path,Path(__file__).resolve()):
            assert hashlib.sha256(pinned_files[str(p.relative_to(root))]).hexdigest()==before[str(p)]
        with (destination/source.name).open('xb') as stream:stream.write(pinned_files[str(source.relative_to(root))])
        for name,data in inputs.items():
            with (destination/name).open('xb') as stream:stream.write(data)
        profile=destination/'network-denied.sb';profile.write_text('(version 1)\n(allow default)\n(deny network*)\n')
        with zipfile.ZipFile(destination/'pre-execution-inputs.zip','x',zipfile.ZIP_DEFLATED) as archive:
            for name,data in {**pinned_files,**inputs}.items():archive.writestr(name,data)
            archive.writestr('runtime-input-hashes.json',json.dumps(before,sort_keys=True))
        with zipfile.ZipFile(destination/'pre-execution-inputs.zip') as archive:
            for name,data in {**pinned_files,**inputs}.items():assert archive.read(name)==data
        sandbox=['/usr/bin/sandbox-exec','-f',str(profile)]
        environment={'PATH':'/usr/bin:/bin','HOME':str(destination/'home'),'TMPDIR':str(destination/'tmp')+'/',
                     'LANG':'en_US.UTF-8'}
        command=sandbox+[str(javac),'-encoding','UTF-8','-classpath',str(jar),'-d',str(destination),str(destination/source.name)]
        process=run_process('compile',command,destination=destination,environment=environment,failures=failures)
        report['processes'].append(process);failures.raise_first();assert process['exit_code']==0
        compiled=[destination/source.name,profile,*[destination/name for name in inputs],*sorted(destination.glob('*.class'))]
        report['compiled_before']={p.name:digest(p) for p in compiled}
        (destination/'original-before.json').write_text(json.dumps(report['compiled_before'],indent=2)+'\n')
        for batch in batches:
            stage=batch['name']
            command=sandbox+[str(java),'-XX:-UsePerfData','-Djava.io.tmpdir='+str(destination/'tmp'),
                '-Duser.home='+str(destination/'home'),'-Djava.awt.headless=true','-classpath',str(destination)+':'+str(jar),
                'NativeRoutedIdentifyProbe',str(destination/(stage+'.tsv')),str(destination)]
            process=run_process(stage,command,destination=destination,environment=environment,failures=failures)
            report['processes'].append(process);failures.raise_first();assert process['exit_code']==0
            assert (destination/(stage+'.stderr')).read_bytes()==b''
            rows=[json.loads(line) for line in (destination/(stage+'.stdout')).read_text().splitlines()]
            assert rows[0]==batch['runtime']
            assert rows[-1]=={'kind':'complete','cases':len(batch['cases'])}
            assert len(rows)==len(batch['cases'])+2
            for row,expected in zip(rows[1:-1],batch['cases']):
                assert row['id']==expected['input']['id']
                actual=semantic_digest(row)
                assert actual==expected['semantic_sha256'],row['id']
                for action in row['actions']:
                    start,end=action['utc_milliseconds_before'],action['utc_milliseconds_after']
                    assert type(start) is type(end) is int and start<=end
                    if action['after']['aW.N']!=action['before']['aW.N']:
                        assert start<=action['after']['aW.N']<=end
                report['comparisons'].append({'id':row['id'],'semantic_sha256':actual})
        report['cases']=902;report['passed']=True
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
