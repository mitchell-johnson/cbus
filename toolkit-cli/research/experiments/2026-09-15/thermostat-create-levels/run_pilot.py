"""No execution without explicit reviewed pilot release; one isolated process."""
from pathlib import Path
import argparse,hashlib,json,os,stat,sys,zipfile
BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE))
from process_harness import Failures,run_process
TOKEN='root-reviewed-thermostat-levels-pilot-v1'

def read(path,limit):
 fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW);parts=[];size=0;first=None
 try:
  state=os.fstat(fd)
  if not stat.S_ISREG(state.st_mode) or state.st_size>limit:raise ValueError('Bounded regular input required')
  while True:
   data=os.read(fd,min(65536,limit+1-size))
   if not data:break
   size+=len(data)
   if size>limit:raise ValueError('Input grew beyond bound')
   parts.append(data)
  return b''.join(parts)
 except BaseException as error:first=error;raise
 finally:
  try:os.close(fd)
  except BaseException:
   if first is None:raise

def associate_child(result, *, expected, cases, partial=False):
 if type(result) is not dict or result.get('format')!='thermostat-levels-original-pilot-v1':raise ValueError('Child report format')
 for name,sha in expected.items():
  if result.get(name)!=sha:raise ValueError('Archived child input association: '+name)
 rows=result.get('results')
 if type(rows) is not list or len(rows)>len(cases) or not partial and len(rows)!=len(cases):raise ValueError('Child case count')
 if [r.get('id') if type(r) is dict else None for r in rows]!=[c['id'] for c in cases[:len(rows)]]:raise ValueError('Ordered child case IDs')
 if not partial and (result.get('source_after')!=expected or result.get('source_postcheck_errors')!=[]):raise ValueError('Child source postchecks')
 return {'input_hashes':dict(expected),'ordered_case_ids':[r['id'] for r in rows],'partial':partial}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--release',required=True);parser.add_argument('--output',required=True)
 args=parser.parse_args()
 if args.release!=TOKEN or sys.version_info[:2] not in ((3,10),(3,13)) or sys.platform!='darwin':raise ValueError('Reviewed release and supported macOS interpreter required')
 out=Path(args.output).absolute()
 if out.parent.resolve(strict=True)!=BASE or out.exists() or out.is_symlink():raise ValueError('Fresh direct owned output required')
 manifest=json.loads(read(BASE/'input-manifest.json',65536))
 files=[BASE/name for name in ('probe.py','cases.json','process_harness.py','make_cases.py','input-manifest.json','run_pilot.py')]
 blobs={str(p):read(p,1024*1024) for p in files}
 for name,sha in manifest['prepared_files'].items():
  if hashlib.sha256(blobs[str(BASE/name)]).hexdigest()!=sha:raise ValueError('Prepared source changed')
 for name,sha in manifest['inputs'].items():
  if hashlib.sha256(read(Path(name),64*1024*1024)).hexdigest()!=sha:raise ValueError('Original source changed')
 import capstone,pefile,unicorn
 from unicorn.unicorn_py3 import unicorn as uc_core
 runtimes=[Path(sys.executable).resolve(),Path(capstone._cs._name).resolve(),Path(uc_core.uclib._name).resolve(),Path(pefile.__file__).resolve()]
 for package in (capstone,unicorn):runtimes.extend(sorted(Path(package.__file__).resolve().parent.rglob('*.py')))
 runtimes=list(dict.fromkeys(runtimes))
 runtime={str(p):hashlib.sha256(read(p,64*1024*1024)).hexdigest() for p in runtimes}
 before={p:hashlib.sha256(raw).hexdigest() for p,raw in blobs.items()}
 out.mkdir();(out/'tmp').mkdir();(out/'home').mkdir()
 staged={};child_expected={'cases_sha256':before[str(BASE/'cases.json')],'probe_sha256':before[str(BASE/'probe.py')],'exe_sha256':next(sha for name,sha in manifest['inputs'].items() if name.endswith('CBusToolkit.exe'))}
 cases=json.loads(blobs[str(BASE/'cases.json')])
 report={'format':'thermostat-levels-driver-v1','passed':False,'python':sys.version,'inputs_before':before,'runtime_before':runtime,'original_before':manifest['inputs'],'network_denied':True,'process':None};failures=Failures()
 try:
  for name in ('probe.py','cases.json'):
   with (out/name).open('xb') as stream:stream.write(blobs[str(BASE/name)])
   staged[str(out/name)]=hashlib.sha256(read(out/name,1024*1024)).hexdigest();assert staged[str(out/name)]==before[str(BASE/name)]
  report['staged_before']=dict(staged)
  with zipfile.ZipFile(out/'inputs.zip','x',zipfile.ZIP_DEFLATED) as archive:
   for p,raw in blobs.items():archive.writestr(Path(p).name,raw)
   archive.writestr('runtime-pins.json',json.dumps(runtime,sort_keys=True))
   for i,p in enumerate(runtimes):
    raw=read(p,64*1024*1024);assert hashlib.sha256(raw).hexdigest()==runtime[str(p)];archive.writestr('runtime/'+str(i)+'/'+p.name,raw)
  with zipfile.ZipFile(out/'inputs.zip') as archive:
   for p,raw in blobs.items():assert archive.read(Path(p).name)==raw
   for i,p in enumerate(runtimes):assert hashlib.sha256(archive.read('runtime/'+str(i)+'/'+p.name)).hexdigest()==runtime[str(p)]
  profile=out/'network-denied.sb';profile.write_text('(version 1)\n(allow default)\n(deny network*)\n')
  exe=next(p for p in manifest['inputs'] if p.endswith('CBusToolkit.exe'))
  command=['/usr/bin/sandbox-exec','-f',str(profile),sys.executable,'-I','-B',str(out/'probe.py'),TOKEN,str(out/'cases.json'),str(out/'original'),exe]
  env={'PATH':'/usr/bin:/bin','HOME':str(out/'home'),'TMPDIR':str(out/'tmp')+'/','PYTHONDONTWRITEBYTECODE':'1','LANG':'en_US.UTF-8'}
  report['process']=run_process('original',command,destination=out,environment=env,failures=failures,timeout=75)
  failures.raise_first();assert report['process']['exit_code']==0
  result=json.loads(read(out/'original/report.json',32*1024*1024));assert result['passed'] and len(result['results'])==12
  report['child_input_association']=associate_child(result,expected=child_expected,cases=cases)
  assert result['runtime_before']==result['runtime_after']
  actual=result['runtime_before'];assert actual['python']==sys.version and actual['executable_sha256']==runtime[actual['executable']]
  assert all(runtime.get(path)==sha for path,sha in actual['libraries'].items())
  assert all(runtime.get(v['path'])==v['sha256'] for v in actual['loaded_python_modules'].values())
  report['child_runtime_associated']=True
  report['original_report_sha256']=hashlib.sha256(read(out/'original/report.json',32*1024*1024)).hexdigest();report['passed']=True
 except BaseException as error:
  if failures.first is not error:failures.remember('pilot',error)
 finally:
  def verify():
   after={p:hashlib.sha256(read(Path(p),1024*1024)).hexdigest() for p in before}
   runtime_after={str(p):hashlib.sha256(read(p,64*1024*1024)).hexdigest() for p in runtimes}
   original_after={p:hashlib.sha256(read(Path(p),64*1024*1024)).hexdigest() for p in manifest['inputs']}
   report.update(inputs_after=after,runtime_after=runtime_after,original_after=original_after)
   assert after==before and runtime_after==runtime and original_after==manifest['inputs']
  failures.attempt('verify_inputs',verify)
  def verify_staged():
   report['staged_after']={p:hashlib.sha256(read(Path(p),1024*1024)).hexdigest() for p in staged}
   assert report['staged_after']==staged
  failures.attempt('verify_executed_staged_inputs',verify_staged)
  def partial_capture():
   path=out/'original/report.json'
   if not path.exists():return
   raw=read(path,32*1024*1024);result=json.loads(raw)
   report['retained_child_report']={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'passed':result.get('passed'),'association':associate_child(result,expected=child_expected,cases=cases,partial=True)}
  failures.attempt('associate_retained_child_report',partial_capture)
  report['passed']=report['passed'] and failures.first is None;report['failures']=list(failures.records)
  stream=None
  try:stream=(out/'report.json').open('x');stream.write(json.dumps(report,indent=2)+'\n')
  except BaseException as error:failures.remember('report.write',error)
  finally:
   if stream is not None:failures.attempt('report.close',stream.close)
 failures.raise_first();print(json.dumps({'passed':report['passed'],'output':str(out)}))

if __name__=='__main__':main()
