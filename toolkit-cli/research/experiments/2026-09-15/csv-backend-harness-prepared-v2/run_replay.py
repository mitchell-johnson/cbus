"""Held replay launcher. No native/VM calls; one network-denied original process."""
from __future__ import annotations
import hashlib,importlib.util,json,os,stat,sys
from pathlib import Path
BASE=Path(__file__).resolve().parent;ROOT=Path('/Users/mitchell/source/cbus/toolkit-cli')
HELPER=ROOT/'research/toolkit_database_csv_original.py';HELPER_SHA='4a18e3885a388eaeb54ab163311b568eda1570a6f06363fe1f8191053c96cad4'

def require(c,m):
 if not c:raise RuntimeError(m)
def read(path,limit=64*1024*1024):
 fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW);first=None
 try:
  info=os.fstat(fd);require(stat.S_ISREG(info.st_mode) and info.st_size<=limit,'Bounded regular launcher input')
  chunks=[];size=0
  while size<=limit:
   raw=os.read(fd,min(65536,limit+1-size))
   if not raw:break
   chunks.append(raw);size+=len(raw)
  require(size<=limit,'Read bound');return b''.join(chunks)
 except BaseException as e:first=e;raise
 finally:
  try:os.close(fd)
  except BaseException:
   if first is None:raise

def load(path,raw,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);exec(compile(raw,str(path),'exec'),m.__dict__);return m

def main():
 require(sys.platform=='darwin' and sys.version_info[:2] in ((3,10),(3,13)) and len(sys.argv)==3,'Supported host/report/new output')
 admission=json.loads(read(BASE/'native-admission.json',8192));source_map=admission.get('inputs_sha256')
 require(type(source_map) is dict and set(source_map)=={'run_native.py','backend_support.py','NativeCSVBackendProbe.py','run_original.py','replay_native.py','run_replay.py','native-cases.json','cases.json','PLAN.md'},'Reviewed source manifest')
 sources={BASE/name:read(BASE/name) for name in source_map}
 require(admission.get('authorization')=='root-reviewed-csv-backend-native4-v1' and all(hashlib.sha256(sources[BASE/name]).hexdigest()==value for name,value in source_map.items()),'Exact native/replay source admission')
 host=load(BASE/'backend_support.py',sources[BASE/'backend_support.py'],'csv_backend_replay_support');host.own(BASE)
 native_path=host.existing_output(BASE,Path(sys.argv[1]),'report.json');out=Path(sys.argv[2]);host.new_output(BASE,out)
 native_raw=host.read(native_path,48*1024*1024);native=host.strict_json(native_raw)
 require(native.get('passed') is True and native.get('native_capture_complete') is True and native.get('service',{}).get('cleanup_complete') is True,'Successful native stage and cleanup required')
 for path,raw in sources.items():require(native['before'][str(path)]==host.digest(raw)==native['after'][str(path)],'Native source association')
 inputs={**sources,native_path:native_raw,BASE/'native-admission.json':host.read(BASE/'native-admission.json'),BASE.parent/'ownership.json':host.read(BASE.parent/'ownership.json'),
  HELPER:host.read(HELPER),BASE.parent/'projection-pilot-v1/NativeCachedCSVProbe.py':host.read(BASE.parent/'projection-pilot-v1/NativeCachedCSVProbe.py'),
  ROOT/'research/NativeToolkitDatabaseCSVProbe.py':host.read(ROOT/'research/NativeToolkitDatabaseCSVProbe.py'),
  ROOT/'research/vendor/toolkit/app/CBusToolkit.exe':host.read(ROOT/'research/vendor/toolkit/app/CBusToolkit.exe'),
  ROOT/'research/vendor/toolkit/app/CBusToolkit.map':host.read(ROOT/'research/vendor/toolkit/app/CBusToolkit.map'),Path(sys.executable).resolve():host.read(Path(sys.executable).resolve())}
 for name in ('capstone','unicorn','pefile'):
  spec=importlib.util.find_spec(name);require(spec is not None and spec.origin,'Research dependency')
  path=Path(spec.origin).resolve();inputs[path]=host.read(path)
  if name!='pefile':
   for p in sorted(path.parent.rglob('*.py'))+sorted(path.parent.rglob('*.dylib')):inputs[p]=host.read(p)
 require(host.digest(inputs[HELPER])==HELPER_SHA,'Pinned first-error process helper')
 helper=load(HELPER,inputs[HELPER],'csv_backend_accepted_process_helper')
 host.new_output(BASE,out);out.mkdir();report={'format':'csv-backend-replay-launch-v1','passed':False,'before':{str(p):host.digest(b) for p,b in inputs.items()},'native_report_sha256':host.digest(native_raw),'native_or_vm_calls':False};failures=host.Failures(report)
 try:
  report['archive_index']=host.archive(out,inputs);report['archive_sha256']=host.digest(host.read(out/'inputs.tar.gz',256*1024*1024))
  for path,raw in inputs.items():require(host.read(path)==raw,'Pre-original input changed')
  names=('replay_native.py','NativeCSVBackendProbe.py','backend_support.py','native-cases.json')
  marker={'format':'csv-backend-replay-launch-v1','owner_token':host.TOKEN,'native_report_sha256':host.digest(native_raw),'inputs_sha256':{name:host.digest(sources[BASE/name]) for name in names}}
  stream=(out/'replay-owned.json').open('xb');first=None
  try:
   raw=(json.dumps(marker,indent=2)+'\n').encode();require(stream.write(raw)==len(raw),'Marker write');stream.flush();os.fsync(stream.fileno())
  except BaseException as e:first=e;raise
  finally:
   try:stream.close()
   except BaseException:
    if first is None:raise
  env={k:v for k,v in os.environ.items() if k not in ('PYTHONHOME','PYTHONPATH')};env.update(PYTHONDONTWRITEBYTECODE='1',TMPDIR=str(out),TMP=str(out),TEMP=str(out))
  command=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)',str(Path(sys.executable).absolute()),'-I',str(BASE/'replay_native.py'),str(native_path),str(out/'capture')]
  report['command']=command;report['exit_code']=helper._run(command,env,out,report)
  require(report['exit_code']==0 and (out/'stderr.txt').stat().st_size==0,'Original replay subprocess failed')
  raw=host.read(out/'capture/report.json',16*1024*1024);capture=host.strict_json(raw)
  require(capture.get('passed') is True and capture.get('capture_complete') is True and len(capture['results'])==4,'Complete four-case original capture')
  require([r['id'] for r in capture['results']]==['B01','B02','B03','B04'] and all(r['captured'] for r in capture['results']),'Exact replay IDs')
  require([r['completed'] for r in capture['results']]==[True,True,False,True],'Three completions/one declared partial')
  for path,value in capture['inputs'].items():require(Path(path) in inputs and host.digest(inputs[Path(path)])==value==capture['after'][path],'Archived/executed replay input association')
  require(capture['original_execution'] is True and capture['original_invocations_attempted']==8 and capture['original_instruction_entries']>0,'Reached original B instructions')
  require(capture['runtime']['python_sources']==capture['runtime_python_sources_after'],'Actual loaded wrapper set stable')
  for item in capture['runtime']['python_sources'].values():
   path=Path(item['path']);require(path in inputs and item['sha256']==host.digest(inputs[path]),'Archived/actually loaded Python wrapper association')
  require(capture['runtime']['executable_sha256']==host.digest(inputs[Path(sys.executable).resolve()]),'Actual replay interpreter')
  report['capture']={'path':str(out/'capture/report.json'),'sha256':host.digest(raw)};report['passed']=True
 except BaseException as error:failures.retain('replay capture',error)
 finally:
  host.posthashes(inputs,report,failures);report['partial_capture_artifacts']={}
  for name in ('capture/report.json','capture/report.pending.json'):
   path=out/name
   exists=failures.attempt('partial existence '+name,path.exists)
   if exists:
    raw=failures.attempt('partial bytes '+name,lambda path=path:host.read(path,16*1024*1024))
    if raw is not None:report['partial_capture_artifacts'][name]={'bytes':len(raw),'sha256':host.digest(raw)}
  host.finish(out,report,failures)
 failures.raise_first();print(json.dumps({'passed':True,'captured':4,'completed':3,'partial':1,'report':str(out/'report.json')}))

if __name__=='__main__':main()
