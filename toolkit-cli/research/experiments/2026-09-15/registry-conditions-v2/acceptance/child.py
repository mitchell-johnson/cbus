from pathlib import Path
import hashlib,json,os,sys,time,unittest
ROOT=Path('/Users/mitchell/source/cbus/toolkit-cli')
OUT=Path(sys.argv[1]);modules=json.loads(sys.argv[2])
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
began=time.monotonic();suite=unittest.defaultTestLoader.loadTestsFromNames(modules)
result=unittest.TextTestRunner(verbosity=2).run(suite)
loaded={}
for name,module in list(sys.modules.items()):
 path=getattr(module,'__file__',None)
 if path and Path(path).is_file() and (name in ('cbus_toolkit','_virtualenv') or name.startswith(('cbus_toolkit.','tests.','cryptography','cffi','_cffi_backend'))):
  loaded[str(Path(path).resolve())]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
report={'python_version':sys.version,'python_executable':str(Path(sys.executable).resolve()),
 'tests':result.testsRun,'failures':[{'test':str(t),'traceback':v} for t,v in result.failures],
 'errors':[{'test':str(t),'traceback':v} for t,v in result.errors],
 'skips':[{'test':str(t),'reason':v} for t,v in result.skipped],'seconds':time.monotonic()-began,
 'passed':result.wasSuccessful() and not result.skipped,'loaded_files':loaded,
 'no_original_processes':True,'no_vm_or_shared_service_calls':True,'public_network_calls':False}
(OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if report['passed'] else 1)
