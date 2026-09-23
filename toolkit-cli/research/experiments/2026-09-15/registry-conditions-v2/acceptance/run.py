from pathlib import Path
import hashlib,io,json,os,subprocess,sys,tarfile
ROOT=Path('/Users/mitchell/source/cbus/toolkit-cli');OUT=Path(__file__).resolve().parent
modules=['tests.test_toolkit_update_registry_conditions','tests.test_cli_toolkit_update_registry_conditions','tests.test_toolkit_update_conditions','tests.test_toolkit_update_conditions_cli_helper','tests.test_cli_toolkit_update_conditions',
 'tests.test_toolkit_update_metadata','tests.test_cli_toolkit_update_metadata','tests.test_toolkit_update_revocation','tests.test_cli_toolkit_update_revocation']
interpreters={'313':ROOT/'.venv/bin/python','310':ROOT/'research/runtime/full-wheel-environments-20260915-v6/310/bin/python'}
paths=sorted((ROOT/'src/cbus_toolkit').rglob('*.py'))+[ROOT/(name.replace('.','/')+'.py') for name in modules]
paths += [ROOT/'tests/__init__.py',ROOT/'docs/toolkit-update-conditions.md',ROOT/'docs/toolkit-update-registry-conditions.md',ROOT/'pyproject.toml',OUT/'run.py',OUT/'child.py']
paths += [ROOT/'research/fixtures'/name for name in ('toolkit-update-registry-conditions-vectors.json','toolkit-update-conditions-v1-report-baseline.json','toolkit-update-conditions-vectors.json','toolkit-update-metadata-vectors.json','toolkit-update-revocation-vectors.json')]
# Read-only dependency inventory from each existing, supported interpreter.
code="""from pathlib import Path
import cryptography,json,sys,importlib.util
p=Path(cryptography.__file__).resolve().parent
files=[Path(sys.executable).resolve()]+[x for x in p.rglob('*') if x.is_file() and x.suffix in ('.py','.so','.dylib')]
virtualenv=importlib.util.find_spec('_virtualenv')
if virtualenv is not None: files.append(Path(virtualenv.origin).resolve())
try:
 import cffi,_cffi_backend
 files += [x for x in Path(cffi.__file__).resolve().parent.rglob('*.py')]+[Path(_cffi_backend.__file__).resolve()]
except ImportError:pass
print(json.dumps([str(x) for x in files]))
"""
for python in interpreters.values():
 p=subprocess.run([str(python),'-I','-c',code],capture_output=True,check=True,text=True)
 assert not p.stderr;paths.extend(map(Path,json.loads(p.stdout)))
paths=list(dict.fromkeys(p.resolve() for p in paths));source={str(p):p.read_bytes() for p in paths}
sha=lambda raw:hashlib.sha256(raw).hexdigest();before={p:sha(raw) for p,raw in source.items()}
(OUT/'before.json').write_text(json.dumps(before,indent=2)+'\n')
with tarfile.open(OUT/'accepted-inputs.tar.gz','x:gz') as archive:
 for index,(name,raw) in enumerate(source.items()):
  info=tarfile.TarInfo(str(index)+'/'+Path(name).name);info.size=len(raw);info.mtime=0;archive.addfile(info,io.BytesIO(raw))
 archive.add(OUT/'before.json',arcname='manifest.json')
with tarfile.open(OUT/'accepted-inputs.tar.gz') as archive:
 for index,(name,raw) in enumerate(source.items()):assert sha(archive.extractfile(str(index)+'/'+Path(name).name).read())==before[name]
reports={}
for label,python in interpreters.items():
 destination=OUT/label;destination.mkdir();(destination/'tmp').mkdir()
 environment={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME') and not k.startswith(('CBUS_','MONO_','DYLD_'))}
 environment.update(PYTHONPATH=str(ROOT/'src')+os.pathsep+str(ROOT),PYTHONDONTWRITEBYTECODE='1',TMPDIR=str(destination/'tmp'),TMP=str(destination/'tmp'),TEMP=str(destination/'tmp'))
 command=[str(python),'-I',str(OUT/'child.py'),str(destination),json.dumps(modules)]
 with (destination/'stdout').open('xb') as stdout,(destination/'stderr').open('xb') as stderr:
  process=subprocess.run(command,stdout=stdout,stderr=stderr,env=environment,timeout=120)
 report=json.loads((destination/'report.json').read_bytes());reports[label]=report
 assert process.returncode==0 and report['passed'] and report['tests']==78,label
 for name,digest in report['loaded_files'].items():assert before[name]==digest,name
 assert all(sha(Path(name).read_bytes())==digest for name,digest in before.items())
 print(json.dumps({'python':label,'passed':True,'tests':78,'seconds':report['seconds']}),flush=True)
final={'format':'toolkit-update-registry-conditions-focused-acceptance-v2','passed':True,'tests_each':78,'versions':{k:{'tests':r['tests'],'seconds':r['seconds'],'report_sha256':sha((OUT/k/'report.json').read_bytes()),'stdout_sha256':sha((OUT/k/'stdout').read_bytes()),'stderr_sha256':sha((OUT/k/'stderr').read_bytes())} for k,r in reports.items()},
 'inputs_unchanged':True,'input_count':len(before),'input_manifest_sha256':sha((OUT/'before.json').read_bytes()),'input_archive_sha256':sha((OUT/'accepted-inputs.tar.gz').read_bytes()),
 'conditions_tests_each':37,'new_registry_tests_each':17,'v1_complete_reports_byte_identical':248,'supported_registry_original_observations':11,'excluded_registry_collation_observations':1,'original_condition_fixture_arms':279,'separate_supported_original_int32_comparisons':107,
 'metadata_and_revocation_regression_tests_each':41,'metadata_revocation_source_changed':False,'vm_shared_service_public_network_calls':False}
(OUT/'acceptance.json').write_text(json.dumps(final,indent=2)+'\n');print(json.dumps(final,indent=2))
