"""Run source-pinned Python preference tests in the owned Windows runner."""
from pathlib import Path
import hashlib,io,json,os,sys,uuid,zipfile
from research.windows_bridge import WindowsBridge
from research.windows_provenance import resolve_windows_provenance

ROOT=Path(__file__).resolve().parents[1]

def run_native_preferences(output_directory):
    from cbus_toolkit import toolkit_preferences_store,windows_preferences,toolkit_numeric
    directory=Path(output_directory);directory.mkdir(parents=True,exist_ok=True)
    result_path=directory/'native-result.json'
    if result_path.exists():raise ValueError('Preserve the existing native preferences result')
    fixture=ROOT/'research/fixtures/toolkit-preferences-controls-vectors.json'
    source_files={'cbus_toolkit/toolkit_preferences_store.py':Path(toolkit_preferences_store.__file__),
                  'cbus_toolkit/windows_preferences.py':Path(windows_preferences.__file__),
                  'cbus_toolkit/toolkit_numeric.py':Path(toolkit_numeric.__file__),
                  'cases.py':ROOT/'research/windows_preferences_native_cases.py',
                  'runtime.json':ROOT/'research/fixtures/windows-python-runtime.json'}
    source={name:path.read_bytes() for name,path in source_files.items()}
    initial=json.loads(fixture.read_bytes())['initial_values_fixture']
    source['initial.json']=json.dumps(initial).encode()
    source['cbus_toolkit/__init__.py']=b''
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
        for name,content in source.items():z.writestr(name,content)
    archive=data.getvalue()
    (directory/'inputs.zip').write_bytes(archive)
    identifier=uuid.uuid4().hex[:16]
    prefix='prefs-native-'+identifier;namespace='native-'+identifier
    bridge=WindowsBridge();provenance=resolve_windows_provenance(ROOT,bridge)
    manifest={'inputs':{name:hashlib.sha256(content).hexdigest() for name,content in source.items()},
              'archive_sha256':hashlib.sha256(archive).hexdigest(),'namespace':namespace,
              'provenance':provenance.as_dict()}
    (directory/'input-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    bridge.push(prefix+'.zip',archive);bridge.push(prefix+'.py',source['cases.py'])
    runtime=json.loads(source['runtime.json'])
    script='@echo off\n"'+bridge.path(runtime['relative_executable'])+'" -I -S "'+bridge.path(prefix+'.py')+'" "'+bridge.path(prefix+'.zip')+'" '+namespace+'\n'
    job=bridge.submit(script)
    (directory/'submission.json').write_text(json.dumps({'job_id':job,'namespace':namespace},indent=2)+'\n')
    result=bridge.wait(job)
    for suffix in ('.admitted.json','.ready.json','.result.json','.stdout.txt','.stderr.txt'):
        content=bridge.pull(job+suffix,missing_ok=True)
        if content is not None:(directory/(job+suffix)).write_bytes(content)
    provenance.verify(bridge)
    unchanged=all(path.read_bytes()==source[name] for name,path in source_files.items())
    outcome={'job_id':job,'complete':result.get('complete'),'exit_code':result.get('exit_code'),
             'input_hashes_unchanged':unchanged,'archive_sha256':manifest['archive_sha256'],
             'source_sha256':manifest['inputs']}
    try:outcome['native']=json.loads(result['stdout'].decode('utf-8-sig'))
    except (ValueError,AttributeError):outcome['native']=None
    outcome['passed']=bool(result.get('complete') is True and result.get('exit_code')==0 and unchanged and
                           outcome['native'] and outcome['native']['passed'])
    result_path.write_text(json.dumps(outcome,indent=2)+'\n')
    return outcome

if __name__=='__main__':
    result=run_native_preferences(Path(sys.argv[1]))
    print(json.dumps({k:v for k,v in result.items() if k not in ('native','source_sha256')}))
    if result['native']:print(json.dumps({k:v for k,v in result['native'].items() if k not in ('evidence','cleanup')}))
    raise SystemExit(0 if result['passed'] else 1)
