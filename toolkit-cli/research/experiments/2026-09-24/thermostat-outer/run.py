"""One-shot original launcher; requires separately created exact root admission."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,stat,sys,zipfile
BASE=Path(__file__).resolve().parent
HELPER_SHA='52e87ad4cab2f441479186ec521ed9b2fefea9a63ed89e89bb5ff71e527479d6'
def digest(raw):return hashlib.sha256(raw).hexdigest()
def check(value,message):
 if not value:raise ValueError(message)
def read(path,limit=64*1024*1024):
 fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW);first=None
 try:
  info=os.fstat(fd);check(stat.S_ISREG(info.st_mode) and info.st_size<=limit,'Regular bounded input');out=[];size=0
  while size<=limit:
   chunk=os.read(fd,min(65536,limit+1-size))
   if not chunk:break
   out.append(chunk);size+=len(chunk)
  check(size<=limit,'Input grew');return b''.join(out)
 except BaseException as error:first=error;raise
 finally:
  try:os.close(fd)
  except BaseException:
   if first is None:raise
def module(path,raw,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);exec(compile(raw,str(path),'exec'),m.__dict__);return m
def fresh(path):
 path=Path(path).absolute();check(path.parent.resolve(strict=True)==BASE and not path.parent.is_symlink() and not path.exists() and not path.is_symlink(),'Fresh direct owned child');return path
def associate(child,inputs,cases,*,partial=False):
 check(type(child) is dict and child.get('format')=='thermostat-outer-original12-v1','Child report type')
 observed=child.get('inputs_before');check(type(observed) is dict and all(inputs.get(p)==h for p,h in observed.items()),'Exact child source associations')
 required=[str(BASE/'probe.py'),str(BASE/'cases.json')]
 check(all(p in observed for p in required),'Child declared code/cases')
 rows=child.get('results');check(type(rows) is list and len(rows)<=12 and (partial or len(rows)==12),'Row bound')
 check([r.get('id') for r in rows]==[c['id'] for c in cases[:len(rows)]],'Ordered case prefix')
 check(all(r.get('case')==c for r,c in zip(rows,cases)),'Full echoed case input')
 rt=child.get('runtime_before');check(type(rt) is dict,'Runtime report')
 check(inputs.get(rt['executable'])==rt['executable_sha256'],'Executed interpreter association')
 check(all(inputs.get(p)==h for p,h in rt['libraries'].items()),'Executed native runtime association')
 check(all(inputs.get(v['path'])==v['sha256'] for v in rt['loaded_python_modules'].values()),'Actually loaded Python wrapper association')
 if not partial:
  check(observed==child['inputs_after'] and child['runtime_before']==child['runtime_after'] and child['secondary_errors']==[],'Child source/runtime stability')
  check(child['passed'] and child['original_requested'] and child['original_executed'],'Completed original evidence')
  check(all(r['matched_expected'] and r['original_entries']>0 for r in rows),'Every original case matched')
 return {'case_ids':[r['id'] for r in rows],'partial':partial,'sources':observed,'loaded_wrapper_count':len(rt['loaded_python_modules'])}
def write(path,raw):
 stream=path.open('xb');first=None
 try:check(stream.write(raw)==len(raw),'Complete file write');stream.flush();os.fsync(stream.fileno())
 except BaseException as error:first=error;raise
 finally:
  try:stream.close()
  except BaseException:
   if first is None:raise
def archive(path,blobs):
 z=zipfile.ZipFile(path,'x',zipfile.ZIP_DEFLATED);first=None;names=[]
 try:
  for i,(p,raw) in enumerate(blobs.items()):name=f'{i}/{Path(p).name}';z.writestr(name,raw);names.append(name)
 except BaseException as error:first=error;raise
 finally:
  try:z.close()
  except BaseException:
   if first is None:raise
 z=zipfile.ZipFile(path);first=None
 try:
  check(z.namelist()==names,'Exact archive names')
  for name,raw in zip(names,blobs.values()):check(z.read(name)==raw,'Archive member equality')
 except BaseException as error:first=error;raise
 finally:
  try:z.close()
  except BaseException:
   if first is None:raise
 return names
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--release',required=True);parser.add_argument('--output',required=True);a=parser.parse_args()
 check(sys.version_info[:2] in ((3,10),(3,13)) and sys.platform=='darwin','Supported isolated host');check(a.release=='root-reviewed-thermostat-outer12-v1','Reviewed release required');out=fresh(a.output)
 prepared=json.loads(read(BASE/'prepared-inputs.json',65536));blobs={p:read(Path(p)) for p in prepared['files']};before={p:digest(raw) for p,raw in blobs.items()};check(before==prepared['files'],'Reviewed prepared source pins')
 check(before[str(BASE/'process_harness.py')]==HELPER_SHA,'Accepted process helper')
 probe=module(BASE/'probe.py',blobs[str(BASE/'probe.py')],'outer_driver_probe');cases=json.loads(blobs[str(BASE/'cases.json')]);probe.validate(cases)
 hypotheses=module(BASE/'make_cases.py',blobs[str(BASE/'make_cases.py')],'outer_driver_hypotheses');check(cases==hypotheses.build(),'Exact prewritten hypotheses')
 adm=read(BASE/'admission.json',4096);check(json.loads(adm)=={'release':a.release,'probe_sha256':before[str(BASE/'probe.py')],'cases_sha256':before[str(BASE/'cases.json')]},'Exact root admission')
 helper=module(BASE/'process_harness.py',blobs[str(BASE/'process_harness.py')],'outer_driver_process');m=probe.load_prior();runtime=m.runtime_evidence()
 runtime_paths=[runtime['executable'],*runtime['libraries'],*(v['path'] for v in runtime['loaded_python_modules'].values())]
 for p in dict.fromkeys(runtime_paths):blobs[p]=read(Path(p))
 blobs[str(BASE/'admission.json')]=adm;blobs[str(BASE/'prepared-inputs.json')]=read(BASE/'prepared-inputs.json',65536);before={p:digest(raw) for p,raw in blobs.items()}
 out.mkdir();(out/'tmp').mkdir();f=helper.Failures();report={'format':'thermostat-outer-driver-v1','passed':False,'inputs_before':before,'runtime_before':runtime,'network_denied':True,'process':None,'original_job_replayed':False}
 try:
  report['archive_members']=archive(out/'inputs.zip',blobs);report['archive_sha256']=digest(read(out/'inputs.zip',256*1024*1024))
  env={'PATH':'/usr/bin:/bin','TMPDIR':str(out/'tmp')+'/','PYTHONDONTWRITEBYTECODE':'1','LANG':'en_US.UTF-8'}
  capture=BASE/(out.name+'-capture');fresh(capture)
  command=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)',sys.executable,'-I','-B',str(BASE/'probe.py'),'execute',str(capture),str(BASE)]
  report['process']=helper.run_process('original',command,destination=out,environment=env,failures=f,timeout=200);f.raise_first();check(report['process']['exit_code']==0,'Original process failed; no replay')
  child_raw=read(capture/'report.json');child=json.loads(child_raw);report['child_association']=associate(child,before,cases);report['child_report']={'path':str(capture/'report.json'),'sha256':digest(child_raw)};report['passed']=True
 except BaseException as error:
  if f.first is not error:f.remember('original workflow',error)
 finally:
  report['inputs_after']={p:f.attempt('hash '+p,lambda p=p:digest(read(Path(p)))) for p in before};f.attempt('source/runtime equality',lambda:check(report['inputs_after']==before,'Inputs changed'))
  if 'capture' in locals():
   def partial():
    if not (capture/'report.json').exists():return
    raw=read(capture/'report.json');d=json.loads(raw);report['retained_child_report']={'path':str(capture/'report.json'),'sha256':digest(raw),'association':associate(d,before,cases,partial=True)}
   f.attempt('partial child association',partial)
  report['passed']=report['passed'] and f.first is None;report['failures']=list(f.records)
  f.attempt('write report',lambda:write(out/'report.json',(json.dumps(report,indent=2)+'\n').encode()))
 f.raise_first();print(json.dumps({'passed':True,'report':str(out/'report.json')}))
if __name__=='__main__':main()
