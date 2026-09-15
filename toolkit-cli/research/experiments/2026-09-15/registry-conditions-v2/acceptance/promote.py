"""Publish compact acceptance only after both pinned source test runs pass."""
from pathlib import Path
import hashlib
import json

ROOT=Path('/Users/mitchell/source/cbus/toolkit-cli')
OUT=Path(__file__).resolve().parent
BASE=OUT.parent.parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
acceptance=json.loads((OUT/'acceptance.json').read_bytes())
before=json.loads((OUT/'before.json').read_bytes())
assert acceptance['passed'] and acceptance['tests_each']==78 and acceptance['inputs_unchanged']
owned=[
 'src/cbus_toolkit/_toolkit_update_registry_conditions.py',
 'src/cbus_toolkit/toolkit_update_conditions.py',
 'src/cbus_toolkit/toolkit_update_conditions_cli.py',
 'src/cbus_toolkit/toolkit_update_metadata.py',
 'src/cbus_toolkit/toolkit_update_revocation.py',
 'src/cbus_toolkit/cli.py',
 'tests/test_toolkit_update_registry_conditions.py',
 'tests/test_cli_toolkit_update_registry_conditions.py',
 'tests/test_toolkit_update_conditions.py',
 'tests/test_toolkit_update_conditions_cli_helper.py',
 'tests/test_cli_toolkit_update_conditions.py',
 'tests/test_toolkit_update_metadata.py',
 'tests/test_cli_toolkit_update_metadata.py',
 'tests/test_toolkit_update_revocation.py',
 'tests/test_cli_toolkit_update_revocation.py',
 'research/fixtures/toolkit-update-registry-conditions-vectors.json',
 'research/fixtures/toolkit-update-conditions-v1-report-baseline.json',
 'research/fixtures/toolkit-update-conditions-vectors.json',
 'research/fixtures/toolkit-update-metadata-vectors.json',
 'research/fixtures/toolkit-update-revocation-vectors.json',
 'docs/toolkit-update-conditions.md',
 'docs/toolkit-update-registry-conditions.md',
 'pyproject.toml']
for path in owned:assert sha(ROOT/path)==before[str(ROOT/path)],path
runs={}
for label in ('313','310'):
 p=OUT/label/'report.json';run=json.loads(p.read_bytes())
 assert run['passed'] and run['tests']==78 and not run['skips'] and not run['errors'] and not run['failures']
 assert all(before[name]==digest for name,digest in run['loaded_files'].items())
 runs[label]={'report':str(p),'report_sha256':sha(p),'python_version':run['python_version'],
  'tests':78,'failures':0,'errors':0,'skips':0,'elapsed_seconds':run['seconds'],
  'stdout_sha256':sha(OUT/label/'stdout'),'stderr_sha256':sha(OUT/label/'stderr'),
  'loaded_source_runtime_hashes_correlated':True}
def evidence(path):return {'path':str(path),'sha256':sha(path)}
pilot=BASE/'registry-pilot-v2/pilot-v2'
vectors=json.loads((ROOT/'research/fixtures/toolkit-update-registry-conditions-vectors.json').read_bytes())
value={
 'status':'accepted',
 'scope':'Pure bounded update conditions under unverified supplied file and HKCU registry primitive facts; no live provider, full applicability or update-availability evaluation',
 'test_count_each_python':78,'new_registry_core_tests':12,'new_registry_cli_tests':5,
 'existing_conditions_regressions':20,'existing_metadata_revocation_regressions':41,
 'runs':runs,'source_hashes':{name:before[str(ROOT/name)] for name in owned},
 'input_manifest':{**evidence(OUT/'before.json'),'input_count':len(before)},
 'accepted_input_archive':{**evidence(OUT/'accepted-inputs.tar.gz'),'files':len(before)+1,'pre_execution_readback_verified':True},
 'v1_compatibility':{'complete_report_byte_comparisons_each_python':248,'completed_baseline_reports':99,
  'capture_before_production_edit':True,'baseline_archive':evidence(OUT.parent/'v1-report-baseline-v2.zip'),
  'initial_invalid_context_capture_preserved':evidence(OUT.parent/'v1-report-baseline.zip'),
  'initial_capture_classification':evidence(OUT.parent/'baseline-first-capture-note.json')},
 'preserved_failed_acceptance_preparation':evidence(OUT.parent/'acceptance-final-v1/failed-preparation.json'),
 'original_registry':{'original_leaf_calls':12,'separate_same_provider_witness_calls':12,'raw_ordered_records':47,
  'observed_booleans':10,'observed_expected_errors':2,'supported_leaf_observations_each_python':11,
  'excluded_original_collation_observations':1,'replayed_original_calls':0,
  'pilot_report':evidence(pilot/'report.json'),'independent_audit':evidence(pilot/'audit.json'),
  'original_stdout':evidence(pilot/'original.stdout'),'provider_identity':vectors['original_provider'],
  'cleanup':vectors['cleanup'],
  'prior_failed_dependency_pilot':evidence(BASE/'registry-pilot-v1/pilot-v1/report.json'),
  'prior_failure_analysis':evidence(BASE/'registry-pilot-v1/failure-analysis-v1/analysis.json')},
 'original_int32':{'separate_direct_calls_compared_each_python':107,'booleans':76,'errors':31,
  'outer_registry_content_shortcuts_compared_separately':True,
  'integer_source_evidence':evidence(BASE/'registry-proposal-v1/integer-evidence.json')},
 'limits':{'json_bytes_each':131072,'json_depth':12,'definitions':8,'file_facts':8,'registry_facts':8,
  'expression_name_characters':256,'path_characters':1024,'entry_result_rhs_characters':256,
  'hive':'HKCU/HKEY_CURRENT_USER only','culture':'invariant-ascii',
  'provider':'framework-registry-getvalue-x86-process-default-v1','provider_live_verified':False,
  'results':['null','System.String','System.Int32'],
  'query_key':['expanded exact path','exact entry','exact tagged original default'],
  'integer_outer_whitespace':['space','tab','CR','LF'],
  'fresh_successful_result_cache':True},
 'not_claimed':['Live registry reads','Other hives or views','Registry32 rollout',
  'General string ordering/prefix collation','Arbitrary provider objects or errors',
  'Public Evaluate invocation or full candidate selection','Current publisher trust','Update availability'],
 'metadata_six_stages_unchanged':True,'revocation_seven_stages_unchanged':True,
 'focused_acceptance_vm_or_shared_service_calls':False,'public_network_calls':False}
doc=ROOT/'docs/toolkit-update-registry-conditions.md'
with doc.open('a') as stream:
 stream.write('\nFocused acceptance passed 78 tests on each of Python 3.13 and 3.10, with zero failures, errors or skips: 17 new registry core/CLI tests and 61 existing conditions/metadata/revocation regressions. Exact source, fixture and runtime inputs were archived before both runs and remained unchanged. [The acceptance fixture](../research/fixtures/toolkit-update-registry-conditions-acceptance.json) records the runs, raw original evidence, exclusions and preserved failed attempts.\n')
value['published_document']={'path':'docs/toolkit-update-registry-conditions.md','sha256':sha(doc),
 'note':'Final acceptance paragraph added after execution; tested document bytes remain in source_hashes and the pre-execution archive.'}
path=ROOT/'research/fixtures/toolkit-update-registry-conditions-acceptance.json'
with path.open('x') as stream:stream.write(json.dumps(value,indent=2)+'\n')
state={'acceptance_fixture':evidence(path),'published_document':value['published_document'],
       'source_release':True,'no_more_windows_jobs_for_this_slice':True}
(OUT/'STATE.json').write_text(json.dumps(state,indent=2)+'\n')
print(json.dumps(state,indent=2))
