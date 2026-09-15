"""Independent, source-pinned scratch-key gateway for DontAskAgain reset."""
from pathlib import Path
import hashlib,io,json,sys,uuid,zipfile

ROOT=Path(__file__).resolve().parents[1]
from research.windows_bridge import WindowsBridge
from research.windows_provenance import resolve_windows_provenance

def run_native_reset(output):
    from cbus_toolkit import toolkit_preferences_reset, windows_preferences_reset
    directory=Path(output);directory.mkdir(parents=True,exist_ok=True)
    if(directory/'result.json').exists():raise ValueError('preserve prior native result')
    paths={'cbus_toolkit/toolkit_preferences_reset.py':Path(toolkit_preferences_reset.__file__),
           'cbus_toolkit/windows_preferences_reset.py':Path(windows_preferences_reset.__file__),
           'cases.py':ROOT/'research/windows_preferences_reset_native_cases.py','runtime.json':ROOT/'research/fixtures/windows-python-runtime.json'}
    sources={name:path.read_bytes()for name,path in paths.items()};sources['cbus_toolkit/__init__.py']=b''
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED)as archive:
        for name,content in sources.items():archive.writestr(name,content)
    packed=data.getvalue();(directory/'inputs.zip').write_bytes(packed)
    identifier=uuid.uuid4().hex[:16];prefix='reset-native-'+identifier;namespace='reset-'+identifier
    bridge=WindowsBridge();provenance=resolve_windows_provenance(ROOT,bridge)
    manifest={'sources':{name:hashlib.sha256(content).hexdigest()for name,content in sources.items()},
              'gateway_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'archive_sha256':hashlib.sha256(packed).hexdigest(),'namespace':namespace,'provenance':provenance.as_dict()}
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    bridge.push(prefix+'.zip',packed);bridge.push(prefix+'.py',sources['cases.py'])
    runtime=json.loads(sources['runtime.json'])
    script='@echo off\n"'+bridge.path(runtime['relative_executable'])+'" -I -S "'+bridge.path(prefix+'.py')+'" "'+bridge.path(prefix+'.zip')+'" '+namespace+'\n'
    job=bridge.submit(script);(directory/'submission.json').write_text(json.dumps({'job_id':job,'namespace':namespace},indent=2)+'\n')
    response=bridge.wait(job)
    for suffix in('.admitted.json','.ready.json','.result.json','.stdout.txt','.stderr.txt'):
        value=bridge.pull(job+suffix,missing_ok=True)
        if value is not None:(directory/(job+suffix)).write_bytes(value)
    provenance.verify(bridge)
    unchanged=all(path.read_bytes()==sources[name]for name,path in paths.items())
    try:native=json.loads(response['stdout'].decode('utf-8-sig'))
    except(ValueError,AttributeError):native=None
    outcome={'passed':response.get('complete')is True and response.get('exit_code')==0 and unchanged and bool(native and native['passed']),
             'job_id':job,'transport_complete':response.get('complete'),'exit_code':response.get('exit_code'),'inputs_unchanged':unchanged,
             'native':native,'manifest':manifest}
    (directory/'result.json').write_text(json.dumps(outcome,indent=2)+'\n')
    return outcome

if __name__=='__main__':
    outcome=run_native_reset(sys.argv[1]);print(json.dumps({key:value for key,value in outcome.items()if key not in('native','manifest')}))
    if outcome['native']:print(json.dumps({key:value for key,value in outcome['native'].items()if key not in('evidence','cleanup')}))
    raise SystemExit(0 if outcome['passed']else 1)
