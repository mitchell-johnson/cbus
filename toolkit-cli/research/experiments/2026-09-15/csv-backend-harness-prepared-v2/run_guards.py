"""Host-only guard acceptance; never original/native execution."""
import importlib.util,json,os,sys
from pathlib import Path
BASE=Path(__file__).resolve().parent;ROOT=Path('/Users/mitchell/source/cbus/toolkit-cli')
spec=importlib.util.spec_from_file_location('csv_backend_guard_support',BASE/'backend_support.py');host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)

def main():
 host.own(BASE);host.require(len(sys.argv)==2,'New guard output');out=Path(sys.argv[1]);host.new_output(BASE,out)
 runtimes=[ROOT/'.venv/bin/python',BASE.parent/'python310-csv/bin/python']
 names=('run_guards.py','guard_tests.py','backend_support.py','NativeCSVBackendProbe.py','run_original.py','run_native.py','replay_native.py','run_replay.py','cases.json','native-cases.json','PLAN.md')
 helper_path=ROOT/'research/toolkit_database_csv_original.py';inputs={BASE/name:host.read(BASE/name) for name in names}
 inputs[helper_path]=host.read(helper_path);host.require(host.digest(inputs[helper_path])=='4a18e3885a388eaeb54ab163311b568eda1570a6f06363fe1f8191053c96cad4','Pinned process-only helper')
 inputs.update({p.resolve():host.read(p.resolve()) for p in runtimes});inputs[BASE.parent/'ownership.json']=host.read(BASE.parent/'ownership.json')
 spec=importlib.util.spec_from_file_location('csv_backend_guard_process',helper_path);helper=importlib.util.module_from_spec(spec);exec(compile(inputs[helper_path],str(helper_path),'exec'),helper.__dict__)
 host.new_output(BASE,out);out.mkdir();report={'format':'csv-backend-host-guards-v1','passed':False,'original_or_native_execution':False,'before':{str(p):host.digest(b) for p,b in inputs.items()},'runs':[]};failures=host.Failures(report)
 try:
  report['archive_index']=host.archive(out,inputs);report['archive_sha256']=host.digest(host.read(out/'inputs.tar.gz',256*1024*1024))
  for index,python in enumerate(runtimes):
   child=out/('python313' if index==0 else 'python310');child.mkdir();row={'python':str(python),'passed':False};report['runs'].append(row)
   env={k:v for k,v in os.environ.items() if k not in ('PYTHONHOME','PYTHONPATH')};env.update(PYTHONDONTWRITEBYTECODE='1',TMPDIR=str(child),TEMP=str(child),TMP=str(child))
   command=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)',str(python),'-I',str(BASE/'guard_tests.py')]
   row['command']=command;row['exit_code']=helper._run(command,env,child,row)
   raw=host.read(child/'stderr.txt');row['stderr_sha256']=host.digest(raw);row['stderr']=raw.decode()
   host.require(row['exit_code']==0 and b'Ran 15 tests' in raw and raw.rstrip().endswith(b'OK'),'All15 host guards')
   row['passed']=True
  report['passed']=True
 except BaseException as error:failures.retain('host guards',error)
 finally:host.posthashes(inputs,report,failures);host.finish(out,report,failures)
 failures.raise_first();print(json.dumps({'passed':True,'tests_each':15,'report':str(out/'report.json')}))
if __name__=='__main__':main()
