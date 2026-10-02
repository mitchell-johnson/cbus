"""Explicit selector callbacks through both owned Rust services and public CLI."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.file_transfer import prepare_upload, upload
from test_cgate_barcode_database_interop import FaultGate, cli, graph
import test_cgate_edlt_parent_add_dialog_interop as parent
from test_cgate_edlt_scene_add_dialog_interop import snapshot

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / 'research/fixtures/edlt-scene-selector-vectors.json'
FACTS = json.loads(VECTOR.read_bytes())
BACKENDS = parent.BACKENDS
PROFILES = ('application-secondary-selector-one', 'trigger-callback-action-valid-in-both',
            'action-selected-duplicate-name-exact-identity', 'null-current-retains-stale-action-binding',
            'scene-two-rebinding-does-not-leak-first-labels', 'label-selection-3')
CASES = [next(row for row in FACTS['cases'] if row['name'] == name) for name in PROFILES]
REFUSALS = ('cache-injection', 'post-load-getter-creation', 'scene-add-timeline', 'future-parent-action')


def scalar(parent_node, name, value):
    ET.SubElement(parent_node, name).text = str(value)


@contextmanager
def journey(backend, variable, tmp_path, *, activation=False):
    try:
        with parent.journey(backend, variable, tmp_path, {}) as data:
            owner, relay, evidence, specs, endpoint = data
            root = ET.fromstring(snapshot(owner))
            network = root.find('Project/Network')
            if network.find("Application[Address='57']") is None:
                secondary = ET.SubElement(network, 'Application')
                for name, value in [('OID',uuid.uuid4()),('TagName','Secondary'),('Address',57)]:
                    scalar(secondary,name,value)
            app = network.find("Application[Address='202']")
            for node in list(app):
                if node.tag == 'Group': app.remove(node)
            cache = FACTS['fixture']['cache']
            labels = {(row['group'], row['action']): row['labels'] for row in cache['level_labels']}
            for trigger in cache['trigger_list']['groups']:
                group = ET.SubElement(app, 'Group')
                for name, value in [('OID', uuid.uuid4()), ('TagName', trigger['name']), ('Address', trigger['address'])]:
                    scalar(group, name, value)
                actions = next(row['actions'] for row in cache['action_lists'] if row['group'] == trigger['address'])
                for action in actions:
                    level = ET.SubElement(group, 'Level', Value=str(action['address']))
                    for name, value in [('OID', uuid.uuid4()), ('TagName', action['name']), ('Address', action['address'])]:
                        scalar(level, name, value)
                    tags = ET.SubElement(level, 'TagsDLT')
                    for index, label in enumerate(labels.get((trigger['address'], action['address']), [])):
                        assert not label['image_present']  # Text-only native fixture; no invented images.
                        tag = ET.SubElement(tags, 'TagDLT')
                        for name, value in [('LanguageID', 1), ('FlavourID', index+1), ('TagType', 'TEXT'), ('TagValue', label['name'])]:
                            scalar(tag, name, value)
            unit = network.find("Unit[Address='20']")
            parameters = {node.get('Name'): node for node in unit.findall('PP')}
            for name, value in FACTS['fixture']['consumer_pp_parameters'].items():
                parameters[name].set('Value', value)
            for name, value in {'ProximityMode':'3' if activation else '1',
                                'ProximityGroup':'42' if activation else '255', 'ProximityLevel':'0'}.items():
                parameters[name].set('Value', value)
            project = tmp_path/'selector-synthetic.xml'; project.write_bytes(ET.tostring(root))
            result = upload(prepare_upload('Projects/archived/'+project.name, project), owner)
            assert result['upload_completed']
            assert owner.command('PROJECT CLOSE TEST').code == 200
            assert owner.command('PROJECT DELETE TEST').code == 200
            assert owner.command('PROJECT RESTORE TEST '+project.name).code == 200
            assert owner.command('PROJECT USE TEST').code == 200
            assert owner.command('PROJECT SAVE TEST').code == 200
            before = snapshot(owner)
            evidence.update(format='cbus-edlt-scene-selector-owned-v1',
                vector_sha256=hashlib.sha256(VECTOR.read_bytes()).hexdigest(),
                selector_fixture_sha256=hashlib.sha256(project.read_bytes()).hexdigest(),
                snapshots={'before':before})
            # Observe the backend's retained XML order independently of CLI producers.
            actual = ET.fromstring(before).find("Project/Network/Application[Address='202']")
            assert [int(row.findtext('Address')) for row in actual.findall('Group')] == [42,43,44,45]
            assert [int(row.findtext('Address')) for row in actual.find("Group[Address='42']").findall('Level')] == [0,1,7]
            yield owner, relay, evidence, specs, endpoint, before
    finally:
        path = tmp_path/'parent-add-evidence.json'
        if path.exists(): path.rename(tmp_path/'scene-selector-evidence.json')


def invoke(relay, evidence, specs, tmp_path, operations, *, dry_run=False, expected=0, connections=1):
    path = tmp_path/'selector-operations.json'
    path.write_text(json.dumps([*operations, parent.widget()]))
    argv = ['unit','--lock-address','//TEST/254','--source','/db//TEST/254/p/20']
    if dry_run: argv.append('--dry-run')
    argv += ['edlt-parent-transaction','--spec-dir',specs,'--auto-metadata',
             '--exclusive-project','--operations',path]
    if not dry_run: argv += ['--backup-project','PABACKUP']
    return cli(relay, evidence['calls'], *argv, expected=expected,
               complete=expected == 0, connections=connections)


def scene_operations(case):
    operations = deepcopy(case['operations'])
    # Owned services serialize by address. These literal ordinals describe
    # their observed source XML, separately from the arbitrary declared-cache
    # order covered by the source vectors. Expected properties/PP do not change.
    for operation in operations:
        for event in operation.get('events', []):
            if event['event'] == 'trigger-selected':
                event['choice_index'] = {42:0,43:1,44:2,45:3}[event['value']]
            elif event['event'] in ('action-selected','level-current-changed') and 'value' in event:
                event['choice_index'] = {0:0,1:1,7:2}[event['value']]
    return [{'op':'scene-manager','operations':[
        *operations, {'op':'get-selector-view','scene':1},
        {'op':'get-selector-view','scene':2}]}]


def selector_operation(result):
    plan = result.get('plan', result)['parent_transaction']
    rows = [row for row in plan['operation_results']
            if row['format'] == 'cbus-edlt-parent-scene-manager-operation-v1']
    assert len(rows) == 1
    assert not plan['native_parent_form_executed'] and not plan['physical_device_verified']
    return rows[0]


def inspect_callback_views(result, case):
    nested = selector_operation(result)['nested_operation_results']
    controls = [row['scene_selector_control'] for row in nested if row['operation']['op'] == 'scene-selector-control']
    assert len(controls) == 1
    control = controls[0]
    expected = case['expected_control_binding']
    for key in ('current_scene','bound_scene','controls_enabled'):
        assert control['state'][key] == expected[key]
    assert control['binding_scope'] == 'one-retained-global-form'
    assert not control['automatic_notify_schedule_inferred'] and not control['host_gui_executed']
    actions = []
    mapping = {'ClearActionBindings':['action-bindings-clear'],
        'ResolveAvailableActionSelectors':['available-actions-get'],
        'SetActionDataSource':['action-data-source-set'],
        'BindActionSelectedValue':['action-binding-add'],
        'ClearDynamicLabelBindings':['label-bindings-clear'],
        'SetDynamicLabelDataSource':['dynamic-labels-get','label-data-source-set'],
        'BindLabelSelectedIndex':['label-binding-add'],
        'ClearSceneNameBindings':['name-bindings-clear'], 'BindSceneNameText':['name-binding-add'],
        'ActionSelectorGetterThenRefreshDynamicLables':['action-get'],
        'RefreshDynamicLables':['dynamic-labels-refresh']}
    for row in control['binding_callbacks']:
        if row['action'] == 'WriteValue':
            target = {'application-selected':'application','trigger-selected':'trigger',
                      'action-selected':'action','level-current-changed':'action','label-selected':'label'}[row['event']]
            actions.append(target+'-binding-write')
        else: actions.extend(mapping.get(row['action'],[]))
    assert actions == case['expected_source_actions']
    views = {row['operation']['scene']:row['view'] for row in nested if row['operation']['op'] == 'get-selector-view'}
    for slot in (1,2):
        view, scene = views[slot], case['expected_scenes_after_callbacks'][slot-1]
        for key, field in [('application_selector','application_selector'),('trigger_group','raw_trigger'),
                           ('raw_action_selector','raw_action'),('label_value_index','label_value_index')]:
            assert view[key] == scene[field]
        assert [row['value'] for row in view['trigger_choices']] == [42,43,44,45]
        assert view['application_choices'] == [
            {'identity':'application:0/56','value':0,'application':56,'name':'(P) Lighting','formatted_display':'(P) Lighting'},
            {'identity':'application:1/57','value':1,'application':57,'name':'(S) Secondary','formatted_display':'(S) Secondary'}]
        assert view['trigger_choices'] == [
            {'identity':f'trigger:202/{address}','value':address,'name':name,'formatted_display':name}
            for address,name in ((42,'Same trigger'),(43,'Same trigger'),(44,'Group 44'),(45,'Group 45'))]
        action_names = {42:((0,'Zero'),(1,'Same action'),(7,'Same action')),
                        43:((0,'Zero'),(7,'Other seven'),(9,'Nine'))}
        assert view['action_choices'] == [
            {'identity':f'action:202/{scene["raw_trigger"]}/{address}','value':address,'name':name,'formatted_display':name}
            for address,name in action_names[scene['raw_trigger']]]
        assert [row['name'] for row in view['dynamic_labels']] == [row['name'] for row in scene['dynamic_labels']]
    return views


def inspect_saved(before, after, case, commands):
    old, new = ET.fromstring(before), ET.fromstring(after)
    baseline, actual = parent.values(old), parent.values(new)
    assert len(baseline) == len(actual) == 844
    assert bytes(actual['SceneBucket']).hex() == case['expected_scene_bucket_hex']
    assert actual['SceneCount'] == [case['expected_scene_count']]
    assert [actual[f'Scene{i}StartAddress'][0] for i in range(1,9)] == case['expected_scene_starts']
    for index, raw in enumerate(case['expected_static_rows_hex']):
        assert bytes(actual['StaticTextString'+str(index)]).hex() == raw
    assert actual['Widget6WidgetType'] == [12]
    for offset, value in enumerate((42,1,2,1,0,0,0,0,0,255,255,135,64),1):
        assert actual[f'Widget6WidgetByteValue{offset}'] == [value]
    allowed = {'OverallCRC','GlobalParameterCRC','WidgetsCRC','StaticTextCRC','ScenesCheckSum',
               'SceneBucket','SceneCount','WidgetGroups',*[f'Scene{i}StartAddress' for i in range(1,9)],
               'Widget6WidgetType',*[f'Widget6WidgetByteValue{i}' for i in range(1,14)]}
    changed = {name for name in actual if actual[name] != baseline[name]}
    assert changed <= allowed
    old_pp = {node.get('Name'):node for node in old.find("Project/Network/Unit[Address='20']").findall('PP')}
    for node in new.find("Project/Network/Unit[Address='20']").findall('PP'):
        if node.get('Name') in allowed: node.set('Value',old_pp[node.get('Name')].get('Value'))
    assert graph(ET.tostring(new,encoding='unicode')) == graph(before)
    assert not any(command.startswith(('DBADD','DBSET','DBDELETE')) for command in commands)
    assert sum(command.startswith('PP SAVE_TO_SOURCE ') for command in commands) == 1
    assert commands.count('PROJECT SAVE TEST') == 2
    assert commands.count('PROJECT COPY TEST PABACKUP') == 1
    assert commands.count('PROJECT CLOSE TEST') == commands.count('PROJECT LOAD TEST') == 1


def fresh_view(after, specs, tmp_path, evidence):
    project = tmp_path/'fresh.xml'; project.write_text(after)
    parameters = tmp_path/'fresh-parameters.json'; parameters.write_text(json.dumps(parent.values(ET.fromstring(after))))
    operations = tmp_path/'fresh-views.json'; operations.write_text('[{"op":"get-selector-view","scene":1},{"op":"get-selector-view","scene":2}]')
    argv = [sys.executable,'-m','cbus_toolkit','edlt','--spec-dir',str(specs),'scene-manager-state',str(parameters),
            '--project-xml',str(project),'--unit','//TEST/254/p/20','--operations',str(operations)]
    process = subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    stdout,stderr = process.communicate(timeout=40)
    evidence.setdefault('offline_calls',[]).append({'pid':process.pid,'exit':process.returncode,
        'argv':argv,'stdout':stdout,'stderr':stderr,
        'stdout_sha256':hashlib.sha256(stdout.encode()).hexdigest(),
        'stderr_sha256':hashlib.sha256(stderr.encode()).hexdigest()})
    assert process.returncode == 0, (stdout,stderr)
    result = json.loads(stdout); assert result['saved'] is False
    return result


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock','daemon'))
@pytest.mark.parametrize('case', CASES, ids=lambda row:row['name'])
def test_public_selectors_preview_apply_fresh_complete_graph(backend,variable,case,tmp_path,request):
    with journey(backend,variable,tmp_path) as (owner,relay,evidence,specs,_endpoint,before):
        evidence.update(nodeid=request.node.nodeid,case_id=case['name'],test_kind='preview-apply-fresh')
        operations = scene_operations(case)
        preview, read = invoke(relay,evidence,specs,tmp_path,operations,dry_run=True)
        inspect_callback_views(preview,case)
        assert not any(command.startswith(('DBADD','DBSET','DBDELETE','PP SET','PP SAVE','PROJECT SAVE','PROJECT COPY')) for command in read['commands'])
        assert snapshot(owner) == before
        result, call = invoke(relay,evidence,specs,tmp_path,operations)
        assert result['saved'] and result['persistence_verified'] and result['target_project_save_confirmed']
        inspect_callback_views(result,case)
        after = snapshot(owner); inspect_saved(before,after,case,call['commands'])
        fresh = fresh_view(after,specs,tmp_path,evidence)
        for slot in (1,2):
            view = fresh['operation_results'][slot-1]['view']
            expected = case['expected_scenes_after_before_save'][slot-1]
            assert view['trigger_group'] == expected['raw_trigger']
            assert view['raw_action_selector'] == expected['raw_action']
            assert view['label_value_index'] == 0  # Cursor is retained UI state, not stored PP.
        assert snapshot(owner) == after
        evidence['snapshots'].update(after_preview=before,after=after)


def refused_operations(kind):
    bind = {'op':'scene-selector-control','scene':1,'events':[{'event':'scene-current-changed','current':True}]}
    if kind == 'cache-injection':
        bind['events'][0]['choices'] = []
        return [{'op':'scene-manager','operations':[bind]}], 0
    if kind == 'post-load-getter-creation':
        bind['events'] += [{'event':'trigger-selected','value':44,'choice_index':2,'choice_identity':'trigger:202/44'},
                           {'event':'trigger-current-changed'}]
        return [{'op':'scene-manager','operations':[bind]}], 1
    if kind == 'scene-add-timeline':
        return [{'op':'scene-manager','operations':[bind,{'op':'add-action-dialog','scene':1,'name':'Later'}]}], 1
    return [{'op':'scene-manager','operations':[{'op':'scene-selector-control','scene':1,'events':[
        {'event':'scene-current-changed','current':True},
        {'event':'action-selected','value':99,'choice_index':3,'choice_identity':'action:202/42/99'}]}]},
        {'op':'activation','wake_mode':'trigger-event','group':42},
        {'op':'add-activation-action-dialog','address':99,'name':'Future'}], 1


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock','daemon'))
@pytest.mark.parametrize('kind', REFUSALS)
def test_public_selector_refusals_precede_database_writes(backend,variable,kind,tmp_path,request):
    with journey(backend,variable,tmp_path) as (owner,relay,evidence,specs,_endpoint,before):
        evidence.update(nodeid=request.node.nodeid,case_id=kind,test_kind='refusal')
        operations, connections = refused_operations(kind)
        result, call = invoke(relay,evidence,specs,tmp_path,operations,expected=1,connections=connections)
        assert result
        assert not any(command.startswith(('DBADD','DBSET','DBDELETE','PP SET','PP SAVE','PROJECT SAVE','PROJECT COPY')) for command in call['commands'])
        assert snapshot(owner) == before
        if connections == 0: assert call['commands'] == []
        evidence['snapshots']['after_refusal'] = before


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock','daemon'))
def test_public_prior_parent_add_visible_later_add_excluded(backend,variable,tmp_path,request):
    with journey(backend,variable,tmp_path,activation=True) as (owner,relay,evidence,specs,_endpoint,before):
        evidence.update(nodeid=request.node.nodeid,case_id='prior-and-later-parent-add',test_kind='ordered-add')
        operations = [
            {'op':'add-activation-action-dialog','address':99,'name':'Earlier action'},
            {'op':'scene-manager','operations':[
                {'op':'scene-selector-control','scene':1,'events':[
                    {'event':'scene-current-changed','current':True},
                    {'event':'action-selected','value':99,'choice_index':3,'choice_identity':'action:202/42/99'}]},
                {'op':'get-selector-view','scene':1}]},
            {'op':'add-activation-action-dialog','address':100,'name':'Later action'}]
        for dry_run in (True,False):
            result, call = invoke(relay,evidence,specs,tmp_path,operations,dry_run=dry_run)
            view = selector_operation(result)['nested_operation_results'][-1]['view']
            assert view['raw_action_selector'] == 99
            assert view['action_choices'] == [
                {'identity':f'action:202/42/{address}','value':address,'name':name,'formatted_display':name}
                for address,name in ((0,'Zero'),(1,'Same action'),(7,'Same action'),(99,'Earlier action'))]
            assert [row['identity'] for row in view['dynamic_labels']] == [f'label:202/42/99/{i}' for i in range(4)]
            assert [row['name'] for row in view['dynamic_labels']] == ['']*4
            if dry_run:
                assert snapshot(owner) == before
                assert not any(c.startswith(('DBADD','DBSET','PP SET','PP SAVE','PROJECT SAVE','PROJECT COPY')) for c in call['commands'])
        assert result['saved'] and result['persistence_verified']
        after = snapshot(owner); old,new = ET.fromstring(before),ET.fromstring(after)
        actual,baseline = parent.values(new),parent.values(old)
        expected_bucket = bytes([2,0,42,99,63,2,0,43,9,62]+[2,0,255,255,255]*6+[255]*192)
        assert len(actual) == 844 and bytes(actual['SceneBucket']) == expected_bucket
        assert actual['SceneCount'] == [8]
        assert [actual[f'Scene{i}StartAddress'][0] for i in range(1,9)] == [0,5,10,15,20,25,30,35]
        assert actual['ProximityLevel'] == [100]
        for index,raw in enumerate(FACTS['fixture']['static_rows_hex']):
            assert bytes(actual['StaticTextString'+str(index)]).hex() == raw
        level_parent = new.find("Project/Network/Application[Address='202']/Group[Address='42']")
        levels = level_parent.findall('Level')
        assert [int(row.findtext('Address')) for row in levels] == [0,1,7,99,100]
        for address,name in ((99,'Earlier action'),(100,'Later action')):
            level = level_parent.find(f"Level[Address='{address}']")
            assert level.findtext('TagName') == name and level.get('Value') == str(address)
            assert level.findtext('OID') not in before
            level_parent.remove(level)
        allowed = {'OverallCRC','GlobalParameterCRC','WidgetsCRC','StaticTextCRC','ScenesCheckSum',
            'SceneBucket','SceneCount','ProximityLevel','WidgetGroups',*[f'Scene{i}StartAddress' for i in range(1,9)],
            'Widget6WidgetType',*[f'Widget6WidgetByteValue{i}' for i in range(1,14)]}
        assert {name for name in actual if actual[name] != baseline[name]} <= allowed
        old_pp = {row.get('Name'):row for row in old.find("Project/Network/Unit[Address='20']").findall('PP')}
        for row in new.find("Project/Network/Unit[Address='20']").findall('PP'):
            if row.get('Name') in allowed: row.set('Value',old_pp[row.get('Name')].get('Value'))
        assert graph(ET.tostring(new,encoding='unicode')) == graph(before)
        commands = call['commands']
        assert sum(c.startswith('DBADDSAFE ') for c in commands) == 2
        assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands) == 1
        assert commands.count('PROJECT SAVE TEST') == 2
        assert commands.count('PROJECT CLOSE TEST') == commands.count('PROJECT LOAD TEST') == 1
        evidence['snapshots']['after'] = after


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock','daemon'))
@pytest.mark.parametrize('phase', ('PP SAVE_TO_SOURCE','PROJECT SAVE'), ids=('pp-save','project-save'))
def test_public_selector_lost_successful_save_never_replayed(backend,variable,phase,tmp_path,request):
    with journey(backend,variable,tmp_path) as (owner,_relay,evidence,specs,endpoint,_before):
        evidence.update(nodeid=request.node.nodeid,fault_phase=phase,test_kind='lost-save')
        with FaultGate(endpoint,phase,'drop',occurrence=2 if phase=='PROJECT SAVE' else 1) as fault:
            result, call = invoke(fault,evidence,specs,tmp_path,scene_operations(CASES[0]),expected=1)
            matches = [i for i,command in enumerate(call['commands']) if command.startswith(phase)]
            assert len(matches) == fault.matches == (2 if phase=='PROJECT SAVE' else 1)
            assert not any(command.startswith(('PP SET','PP SAVE','PROJECT SAVE','PROJECT CLOSE','PROJECT LOAD','DBDELETE')) for command in call['commands'][matches[-1]+1:])
            lost = [row for row in fault.evidence() if row.get('fault')]
            assert len(lost) == 1
            assert bytes.fromhex(lost[0]['lost_backend_terminal_hex']).decode() == f"[{lost[0]['fault']['tag']}] 200 OK\r\n"
            state = result['edlt_parent_metadata_evidence']
            assert state['state'] == 'uncertain' and state['database_state_uncertain']
            assert not state['saved'] and not state['persistence_verified'] and state['automatic_retries'] == 0
            assert state['pp_save_outcome_uncertain'] is (phase == 'PP SAVE_TO_SOURCE')
            assert state['target_project_save_outcome_uncertain'] is (phase == 'PROJECT SAVE')
            evidence['lost_save_wires'] = fault.evidence()
        evidence['snapshots']['after_lost_save'] = snapshot(owner)
