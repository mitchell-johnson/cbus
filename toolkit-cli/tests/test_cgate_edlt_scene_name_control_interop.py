"""Source SceneName property/control journeys through both owned Rust backends."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.programming import Programmer
import test_cgate_edlt_parent_add_dialog_interop as parent
from test_cgate_barcode_database_interop import FaultGate, cli, graph
from test_cgate_edlt_scene_add_dialog_interop import snapshot

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / 'research/fixtures/cgate-edlt-scene-name-control-owned.json'
FACTS = json.loads(VECTOR.read_bytes())
BACKENDS = parent.BACKENDS


def tree(text):
    return ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(
        insert_comments=True, insert_pis=True)))


@contextmanager
def journey(backend, variable, tmp_path, case):
    try:
        with parent.journey(backend, variable, tmp_path, {}) as data:
            owner, relay, evidence, specs, endpoint = data
            evidence.update(format='cbus-edlt-scene-name-control-owned-v1',
                vector_sha256=hashlib.sha256(VECTOR.read_bytes()).hexdigest())
            assert owner.command('DBADDSAFE //TEST/254/56 Group 12 Lighting').code == 301
            with Programmer(owner).load('//TEST/254', '/db//TEST/254/p/20') as session:
                for index, raw in case.get('seed_rows', {}).items():
                    row = bytes.fromhex(raw); assert len(row) == 64
                    assert session.set('StaticTextString'+index, ' '.join(map(str, row))).code == 200
                initial = [2, 0, 255, 255, case.get('initial_index', 63)] + [255]*227
                for name, value in [('SceneCount', '1'), ('Scene1StartAddress', '0'),
                                    ('SceneBucket', ' '.join(map(str, initial)))]:
                    assert session.set(name, value).code == 200
                assert session.save_to_source().code == 200
            assert owner.command('PROJECT SAVE TEST').code == 200
            before = snapshot(owner)
            evidence['snapshots'] = {'before': before}
            yield owner, relay, evidence, specs, endpoint, before
    finally:
        path = tmp_path/'parent-add-evidence.json'
        if path.exists(): path.rename(tmp_path/'scene-name-control-evidence.json')


def plan_from(result):
    return result.get('plan', result)['parent_transaction']


def inspect_names(result, case):
    plan = plan_from(result)
    operations = [row for row in plan['operation_results']
                  if row['format'] == 'cbus-edlt-parent-scene-manager-operation-v1']
    assert len(operations) == 1
    getters = [row for row in operations[0]['nested_operation_results']
               if row['operation']['op'] == 'get-name']
    assert len(getters) == 1 and getters[0]['value'] == case['name']
    composition = operations[0]['composition']
    assert len(composition['static_names']) == 64
    assert composition['scene_names_view'][0]['scene_name'] == case['name']
    final = plan['retained_name_views']
    assert final['read_only'] and len(final['static_names']) == 64
    assert len(final['scene_names']) == 8
    assert final['scene_names'][0]['name_index'] == case['index']
    assert final['scene_names'][0]['scene_name'] == case.get('terminal_name', case['name'])
    assert not plan['native_parent_form_executed'] and not plan['physical_device_verified']


def inspect_saved(before, after, case, call):
    old, new = tree(before), tree(after)
    baseline, actual = parent.values(old), parent.values(new)
    assert len(baseline) == len(actual) == FACTS['declared_synthetic_parameter_count']
    for index, raw in case['all_final_rows'].items():
        assert bytes(actual['StaticTextString'+index]) == bytes.fromhex(raw)
    assert bytes(actual['SceneBucket']).hex() == case['expected_scene_bucket_hex']
    assert [actual[f'Scene{i}StartAddress'][0] for i in range(1, 9)] == case['expected_scene_pointers']
    assert actual['SceneCount'] == [8]
    # Unchanged original-DLL-backed Measurement record and explicit device/channel.
    assert actual['Widget6WidgetType'] == [12]
    for offset, value in enumerate((42, 1, 2, 1, 0, 0, 0, 0, 0, 255, 255, 135, 64), 1):
        assert actual[f'Widget6WidgetByteValue{offset}'] == [value]
    allowed = {'OverallCRC','GlobalParameterCRC','WidgetsCRC','StaticTextCRC','ScenesCheckSum',
               'SceneBucket','SceneCount','WidgetGroups',*[f'Scene{i}StartAddress' for i in range(1,9)],
               'Widget6WidgetType',*[f'Widget6WidgetByteValue{i}' for i in range(1,14)]}
    allowed.update('StaticTextString'+i for i in case['final_rows'])
    if 'widget_label_index' in case:
        assert actual['Widget7WidgetType'] == [2]
        assert actual['Widget8WidgetType'] == [case['companion_widget_type']]
        for offset, value in {1:48,2:2,3:1,6:12,7:15,8:16,9:1,10:255,11:255,12:25,
                              13:case['widget_label_index']}.items():
            assert actual[f'Widget7WidgetByteValue{offset}'] == [value]
        for offset in (4,5):
            assert actual[f'Widget7WidgetByteValue{offset}'] == baseline[f'Widget7WidgetByteValue{offset}']
        allowed.update({'Widget7WidgetType','Widget8WidgetType',
                        *[f'Widget7WidgetByteValue{i}' for i in range(1,14)]})
    changed = {name for name in actual if actual[name] != baseline[name]}
    assert changed <= allowed, changed-allowed
    unit, source = new.find("Project/Network/Unit[Address='20']"), old.find("Project/Network/Unit[Address='20']")
    for node in unit.findall('PP'):
        if node.get('Name') in allowed:
            node.set('Value', source.find("PP[@Name='"+node.get('Name')+"']").get('Value'))
    assert graph(ET.tostring(new, encoding='unicode')) == graph(before)
    commands = call['commands']
    assert not any(c.startswith(('DBADD','DBSET','DBDELETE')) for c in commands)
    assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands) == 1
    assert commands.count('PROJECT SAVE TEST') == 2
    assert commands.count('PROJECT COPY TEST PABACKUP') == 1
    assert commands.count('PROJECT CLOSE TEST') == commands.count('PROJECT LOAD TEST') == 1
    for i, command in enumerate(commands):
        if command.startswith(('PP SET ','PP SAVE_TO_SOURCE ','PROJECT SAVE ','PROJECT CLOSE ','PROJECT LOAD ')):
            assert call['statuses'][i] == 200


def fresh_cli_names(after, specs, tmp_path, evidence, case):
    project = tmp_path/'fresh-project.xml'; project.write_text(after)
    parameters = tmp_path/'fresh-parameters.json'; parameters.write_text(json.dumps(parent.values(tree(after))))
    operations = tmp_path/'fresh-name-operations.json'; operations.write_text('[{"op":"get-name","scene":1}]')
    argv = [sys.executable,'-m','cbus_toolkit','edlt','--spec-dir',str(specs),'scene-manager-state',str(parameters),
            '--project-xml',str(project),'--unit','//TEST/254/p/20','--operations',str(operations)]
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate(timeout=40)
    evidence.setdefault('offline_calls', []).append({'pid':process.pid,'exit':process.returncode,
        'argv':argv,'stdout':stdout,'stderr':stderr,
        'stdout_sha256':hashlib.sha256(stdout.encode()).hexdigest(),
        'stderr_sha256':hashlib.sha256(stderr.encode()).hexdigest()})
    assert process.returncode == 0, (stdout,stderr)
    view = json.loads(stdout)
    assert view['saved'] is False
    assert len(view['state']['static_names']) == 64
    assert view['state']['scene_names_view'][0]['scene_name'] == case['fresh_name']
    assert view['operation_results'][0]['value'] == case['fresh_name']
    assert view['state']['scene_names_view'][0]['name_index'] == case['index']
    return view


def invoke_invalid_cache(relay, evidence, specs, tmp_path, case):
    operations = tmp_path/'invalid-cache-operations.json'
    operations.write_text(json.dumps([*case['ops'], parent.widget()]))
    return cli(relay, evidence['calls'], 'unit', '--lock-address', '//TEST/254',
        '--source', '/db//TEST/254/p/20', 'edlt-parent-transaction',
        '--spec-dir', specs, '--auto-metadata', '--exclusive-project',
        '--operations', operations, expected=1, connections=0)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock','daemon'))
@pytest.mark.parametrize('case', FACTS['cases'], ids=lambda row:row['id'])
def test_public_scene_name_control_preview_apply_and_fresh_names(backend,variable,case,tmp_path,request):
    with journey(backend,variable,tmp_path,case) as (owner,relay,evidence,specs,_endpoint,before):
        evidence.update(nodeid=request.node.nodeid,case_id=case['id'],test_kind='preview-apply-fresh')
        preview, read = parent.invoke(relay,evidence,specs,tmp_path,case,dry_run=True)
        inspect_names(preview,case)
        assert not any(c.startswith(('DBADD','DBSET','DBDELETE','PROJECT SAVE','PROJECT COPY','PP SET','PP SAVE')) for c in read['commands'])
        after = snapshot(owner)
        evidence['snapshots']['after_preview'] = after
        assert after == before
        result, call = parent.invoke(relay,evidence,specs,tmp_path,case)
        assert result['saved'] and result['target_project_save_confirmed'] and result['persistence_verified']
        inspect_names(result,case)
        after = snapshot(owner); inspect_saved(before,after,case,call)
        fresh_cli_names(after,specs,tmp_path,evidence,case)
        assert snapshot(owner) == after
        evidence['snapshots']['after'] = after


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock','daemon'))
@pytest.mark.parametrize('case', FACTS['refusals'], ids=lambda row:row['id'])
def test_public_pending_scene_name_and_cache_injection_refuse_without_write(backend,variable,case,tmp_path,request):
    with journey(backend,variable,tmp_path,case) as (owner,relay,evidence,specs,_endpoint,before):
        evidence.update(nodeid=request.node.nodeid,case_id=case['id'],test_kind='refusal')
        if case['id'] == 'cache-injection':
            result, call = invoke_invalid_cache(relay,evidence,specs,tmp_path,case)
        else:
            result, call = parent.invoke(relay,evidence,specs,tmp_path,case,expected=1,complete=False)
        assert case['error'].lower() in str(result).lower()
        assert not any(c.startswith(('DBADD','DBSET','DBDELETE','PROJECT SAVE','PROJECT COPY','PP SET','PP SAVE')) for c in call['commands'])
        after = snapshot(owner)
        evidence['snapshots']['after_refusal'] = after
        assert after == before
        if case['id'] == 'cache-injection': assert call['commands'] == []


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock','daemon'))
@pytest.mark.parametrize('phase', FACTS['fault_phases'], ids=('pp-save','project-save'))
def test_public_scene_name_control_lost_successful_save_not_replayed(backend,variable,phase,tmp_path,request):
    case = FACTS['cases'][0]
    with journey(backend,variable,tmp_path,case) as (owner,_relay,evidence,specs,endpoint,_before):
        evidence.update(nodeid=request.node.nodeid,fault_phase=phase,test_kind='lost-save')
        # Ignore the explicit pre-backup PROJECT SAVE; fault the later owning target save.
        with FaultGate(endpoint,phase,'drop',occurrence=2 if phase=='PROJECT SAVE' else 1) as fault:
            result, call = parent.invoke(fault,evidence,specs,tmp_path,case,expected=1,complete=False)
            commands = call['commands']
            matches = [i for i,c in enumerate(commands) if c.startswith(phase)]
            expected_attempts = 2 if phase=='PROJECT SAVE' else 1
            assert len(matches) == expected_attempts and fault.matches == expected_attempts
            boundary = matches[-1]
            assert not any(c.startswith(('PP SET','PP SAVE','PROJECT SAVE','PROJECT CLOSE','PROJECT LOAD','DBDELETE')) for c in commands[boundary+1:])
            rows = [row for row in fault.evidence() if row.get('fault')]
            assert len(rows) == 1
            assert bytes.fromhex(rows[0]['lost_backend_terminal_hex']).decode() == f"[{rows[0]['fault']['tag']}] 200 OK\r\n"
            state = result['edlt_parent_metadata_evidence']
            assert state['state'] == 'uncertain'
            assert state['database_state_uncertain'] and not state['persistence_verified']
            assert not state['saved'] and state['automatic_retries'] == 0
            assert state['pp_save_outcome_uncertain'] is (phase == 'PP SAVE_TO_SOURCE')
            assert state['target_project_save_outcome_uncertain'] is (phase == 'PROJECT SAVE')
            evidence['lost_save_wires'] = fault.evidence()
        after = snapshot(owner)
        evidence['snapshots']['after_uncertain_save'] = after
        actual = parent.values(tree(after))
        assert bytes(actual['StaticTextString62']).hex() == case['final_rows']['62']
        assert actual['SceneBucket'][4] == 62
