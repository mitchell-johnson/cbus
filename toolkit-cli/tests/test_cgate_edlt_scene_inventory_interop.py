"""Causal scene creation through public CLI and closed, owned Rust services."""
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
import test_cgate_edlt_scene_selector_interop as selector

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / 'research/fixtures/edlt-scene-inventory-vectors.json'
FACTS = json.loads(VECTOR.read_bytes())
BACKENDS = selector.BACKENDS
PROFILES = (
    'action-add-explicit-rebind-sees-new-generation',
    'action-add-current-getter-view-new-old-binding-separate',
    'canceled-action-add-keeps-bound-generation',
    'trigger-add-then-explicit-callback',
    'canceled-trigger-add-keeps-current-and-inventory',
    'old42-choice-writes-current43-setter',
    'old42-existing-choice-current43-existing-labels',
    'trigger-callback-creates-missing-retained-action',
    'missing-trigger-getter-requested-not-first-free',
    'initial-loader-reserves-before-first-dialog',
    'all-eight-loader-getters-reserve-before-first-dialog',
    'later-initial-getter-keeps-earlier-label-generation',
    'terminal-fallback-zero-not-borrowed-early',
)
STANDALONE = ('action-add-explicit-rebind-sees-new-generation',
              'missing-trigger-getter-requested-not-first-free',
              'terminal-fallback-zero-not-borrowed-early')
REFUSALS = ('new-choice-stale-bound-generation', 'divergent-action-add-combo-target',
            'pending-name-wrong-bound-target')
PREFERENCES = {'format':'cbus-edlt-display-preferences-v1', 'registry_key_present':True,
    'values': {'DisplayHexAddress':0, 'DisplayAddressValue':0,
               'SortModeApplications':0, 'SortModeGroups':1, 'SortModeLevels':1}}
assert FACTS['fixture']['display_preferences']==PREFERENCES
MUTATIONS = ('DBADD','DBSET','DBDELETE','PP SET','PP SAVE','PROJECT SAVE','PROJECT COPY')


def case_named(name):
    case = deepcopy(next(row for row in FACTS['cases'] if row['name'] == name))
    if name in ('initial-loader-reserves-before-first-dialog',
                'all-eight-loader-getters-reserve-before-first-dialog'):
        # The retained Add-only vectors are legacy histories. This explicit
        # valid getter adapts the public journey to the new inventory profile,
        # without changing their independently literal eight-scene/PP oracles.
        case['operations'].append({'op':'get-selector-view','scene':1})
        scene = case['expected_scenes_before_save'][0]
        group,action = scene['raw_trigger'],scene['raw_action']
        removed = {tuple(row) for row in case.get('input_overrides',{}).get('remove_levels',[])}
        existing = next(row['actions'] for row in FACTS['fixture']['cache']['action_lists'] if row['group']==group)
        names = {row['address']:row['name'] for row in existing if (group,row['address']) not in removed}
        names.update({row['address']:row['name'] for row in case['expected_created_objects']
                      if row['kind']=='level' and row['group']==group})
        case['expected_intermediate_views'].append({
            'operation':2,'scene':1,'raw_trigger':group,'raw_action_selector':action,
            'action_selector':action,'label_value_index':scene['label_value_index'],
            'application_choices':deepcopy(FACTS['fixture']['exact_source_choices']['applications']),
            'trigger_choices':deepcopy(FACTS['fixture']['exact_source_choices']['triggers']),
            'action_choices':[{'identity':f'action:202/{group}/{address}','value':address,
                'name':names[address],'formatted_display':names[address]} for address in sorted(names)],
            'dynamic_labels':[{'identity':f'label:202/{group}/{action}/{index}','value':index,
                'raw_value':label['value'],'name':label['name'],'image_present':label['image_present']}
                for index,label in enumerate(scene['dynamic_labels'])],
            'action_collection_generation':'network-refresh:'+str(len(case['expected_created_objects']))})
        case['public_profile_adaptation']='explicit valid getter after Add; original Add-only vector preserved'
    return case


CASES = [case_named(name) for name in PROFILES]


@contextmanager
def journey(backend, variable, case, tmp_path):
    """Import only independently declared synthetic inputs, never final outputs."""
    try:
        with selector.journey(backend, variable, tmp_path) as data:
            owner, relay, evidence, specs, endpoint, original = data
            root = ET.fromstring(original)
            app = root.find("Project/Network/Application[Address='202']")
            for node in list(app):
                if node.tag == 'Group': app.remove(node)
            cache = FACTS['fixture']['cache']
            labels = {(row['group'],row['action']):row['labels'] for row in cache['level_labels']}
            removed = {tuple(row) for row in case.get('input_overrides',{}).get('remove_levels',[])}
            for row in cache['trigger_list']['groups']:
                group = ET.SubElement(app,'Group')
                for key, value in [('OID',uuid.uuid4()),('TagName',row['name']),('Address',row['address'])]:
                    selector.scalar(group,key,value)
                actions = next(v['actions'] for v in cache['action_lists'] if v['group']==row['address'])
                for action in actions:
                    identity = (row['address'],action['address'])
                    if identity in removed: continue
                    level = ET.SubElement(group,'Level',Value=str(action['address']))
                    for key,value in [('OID',uuid.uuid4()),('TagName',action['name']),('Address',action['address'])]:
                        selector.scalar(level,key,value)
                    tags = ET.SubElement(level,'TagsDLT')
                    for index,label in enumerate(labels.get(identity,[]),1):
                        assert not label['image_present']
                        tag = ET.SubElement(tags,'TagDLT')
                        for key,value in [('LanguageID',1),('FlavourID',index),('TagType','TEXT'),('TagValue',label['name'])]:
                            selector.scalar(tag,key,value)
            unit = root.find("Project/Network/Unit[Address='20']")
            pp = {node.get('Name'):node for node in unit.findall('PP')}
            for name,value in case['input_consumer_pp_parameters'].items():
                pp[name].set('Value',value)
            project = tmp_path/'inventory-synthetic.xml'
            project.write_bytes(ET.tostring(root))
            assert upload(prepare_upload('Projects/archived/'+project.name,project),owner)['upload_completed']
            for command in ('PROJECT CLOSE TEST','PROJECT DELETE TEST',
                            'PROJECT RESTORE TEST '+project.name,'PROJECT USE TEST','PROJECT SAVE TEST'):
                assert owner.command(command).code == 200
            before = selector.snapshot(owner)
            evidence.update(format='cbus-edlt-scene-inventory-owned-v1',
                vector_sha256=hashlib.sha256(VECTOR.read_bytes()).hexdigest(),
                inventory_fixture_sha256=hashlib.sha256(project.read_bytes()).hexdigest(),
                declared_display_preferences=deepcopy(PREFERENCES),snapshots={'before':before})
            if 'public_profile_adaptation' in case:
                evidence['public_profile_adaptation']=case['public_profile_adaptation']
            yield owner,relay,evidence,specs,endpoint,before
    finally:
        path = tmp_path/'scene-selector-evidence.json'
        if path.exists(): path.rename(tmp_path/'scene-inventory-evidence.json')


def invoke(relay,evidence,specs,tmp_path,operations,*,dry_run=False,expected=0,surface='parent',parent_operations=None):
    path = tmp_path/'inventory-operations.json'
    supplied = (parent_operations if parent_operations is not None else
                [{'op':'scene-manager','operations':operations},selector.parent.widget()]
                if surface=='parent' else operations)
    path.write_text(json.dumps(supplied))
    prefs = tmp_path/'display-preferences.json'; prefs.write_text(json.dumps(PREFERENCES))
    argv = ['unit','--lock-address','//TEST/254','--source','/db//TEST/254/p/20']
    if dry_run: argv.append('--dry-run')
    argv += ['edlt-parent-transaction' if surface=='parent' else 'edlt-scene-manager',
        '--spec-dir',specs,'--auto-metadata','--exclusive-project',
        '--display-preferences',prefs,'--operations',path]
    if not dry_run: argv += ['--backup-project','PABACKUP']
    # A complete creation/save/readback journey can issue many bounded commands.
    # Keep the per-command wire deadline at3s while bounding the whole process.
    return cli(relay,evidence['calls'],*argv,expected=expected,complete=expected==0,process_timeout=90)


def inventory_timeline(native):
    assert isinstance(native,dict), 'Automatic SceneManager metadata is required'
    timeline = native['inventory_timeline']
    assert isinstance(timeline,dict) and timeline['frames']
    assert len(timeline['initial_scene_bindings'])==8
    assert not timeline['serialized_input_capability'] and not timeline['original_execution']
    return timeline


def inspect_initial_bindings(timeline,case):
    if case['name']=='later-initial-getter-keeps-earlier-label-generation':
        assert timeline['initial_scene_bindings']==[
            [42,7,0],[43,9,1],*[[255,-1,1] for _ in range(6)]]
        assert timeline['initial']['refresh_generation']==1


def inspect_intermediate(result,case):
    if 'state' in result and 'operation_results' in result:
        operation = {'nested_operation_results':result['operation_results'],
            'composition':{'scene_selector_control':result['state']['scene_selector_control']}}
        native = result['automatic_metadata']
    else:
        operation = selector.selector_operation(result)
        native = result.get('plan',result)['automatic_scene_metadata']
    nested = operation['nested_operation_results']
    timeline = inventory_timeline(native)
    inspect_initial_bindings(timeline,case)
    end_frames = [row for row in timeline['frames'] if row['phase']=='operation-end']
    assert len(end_frames)==len(nested)
    for expected in case['expected_intermediate_views']:
        ordinal = sum(not (row['op'] in ('add-trigger-dialog','add-action-dialog')
                          and row.get('cancel'))
                      for row in case['operations'][:expected['operation']])
        row = nested[ordinal-1]
        assert row['operation']['op']=='get-selector-view'
        view = row['view']
        for key in ('scene','raw_action_selector','action_selector','label_value_index',
                    'application_choices','trigger_choices','action_choices','dynamic_labels'):
            assert view[key]==expected[key],(case['name'],expected['operation'],key,view[key],expected[key])
        assert view['trigger_group']==expected['raw_trigger']
        generation = expected['action_collection_generation']
        number = 0 if generation=='initial' else int(generation.split(':')[1])
        assert end_frames[ordinal-1]['inventory']['refresh_generation']==number
    for row in nested:
        control = row.get('scene_selector_control')
        if control:
            assert not control['automatic_notify_schedule_inferred'] and not control['host_gui_executed']
            if row['operation']['events']==[{'event':'scene-current-changed','current':True}]:
                assert [row['action'] for row in control['binding_callbacks']]==[
                    'SetControlEnabled','ClearActionBindings','ResolveAvailableActionSelectors','SetActionDataSource',
                    'BindActionSelectedValue','ClearDynamicLabelBindings','SetDynamicLabelDataSource',
                    'BindLabelSelectedIndex','ClearSceneNameBindings','BindSceneNameText']
    control = operation['composition']['scene_selector_control']
    if case['name'] in ('action-add-current-getter-view-new-old-binding-separate',
                        'old42-choice-writes-current43-setter',
                        'old42-existing-choice-current43-existing-labels'):
        assert (control['current_scene'],control['bound_scene'],control['action_source_trigger'])==(1,1,42)
        assert control['view']['action_choices']==[
            {'identity':f'action:202/42/{address}','value':address,'name':name,'formatted_display':name}
            for address,name in ((0,'Zero'),(1,'Same action'),(7,'Same action'))]
    if case['name']=='trigger-add-then-explicit-callback':
        assert (control['current_scene'],control['bound_scene'],control['action_source_trigger'])==(1,1,0)
        assert control['view']['action_choices']==[]


def inspect_blank_variants(node):
    tags = node.find('TagsDLT')
    if tags is None:
        # Native creation stores no explicit labels. The independent fresh
        # public getter below must still return all four blank model defaults.
        return
    if not list(tags):
        return
    assert [{child.tag:child.text or '' for child in row} for row in tags.findall('TagDLT')]==[
        {'LanguageID':'1','FlavourID':str(index),'TagType':'TEXT','TagValue':''} for index in range(1,5)]


def inspect_saved(before,after,case,commands,*,surface='parent',extra_pp=None):
    old,new = ET.fromstring(before),ET.fromstring(after)
    baseline,actual = selector.parent.values(old),selector.parent.values(new)
    assert len(baseline)==len(actual)==844
    assert bytes(actual['SceneBucket']).hex()==case['expected_scene_bucket_hex']
    assert len(actual['SceneBucket'])==232
    assert actual['SceneCount']==[case['expected_scene_count']]
    assert [actual[f'Scene{i}StartAddress'][0] for i in range(1,9)]==case['expected_scene_starts']
    for index,raw in enumerate(case['expected_static_rows_hex']):
        assert bytes(actual['StaticTextString'+str(index)]).hex()==raw
    allowed = {'OverallCRC','GlobalParameterCRC','WidgetsCRC','StaticTextCRC','ScenesCheckSum',
        'SceneBucket','SceneCount',*[f'Scene{i}StartAddress' for i in range(1,9)]}
    if surface=='parent':
        allowed |= {'WidgetGroups','Widget6WidgetType',*[f'Widget6WidgetByteValue{i}' for i in range(1,14)]}
        assert actual['Widget6WidgetType']==[12]
        for offset,value in enumerate((42,1,2,1,0,0,0,0,0,255,255,135,64),1):
            assert actual[f'Widget6WidgetByteValue{offset}']==[value]
    for name, expected in (extra_pp or {}).items():
        allowed.add(name)
        assert actual[name]==expected
    assert {name for name in actual if actual[name]!=baseline[name]} <= allowed
    # Remove only literal issued creations, and restore only permitted PP
    # values before comparing the complete independent project graph.
    app = new.find("Project/Network/Application[Address='202']")
    creations = case['expected_created_objects']
    for row in reversed(creations):
        if row['kind']=='level':
            owner = app.find(f"Group[Address='{row['group']}']")
            node = owner.find(f"Level[Address='{row['address']}']")
            assert node is not None and node.findtext('TagName')==row['name']
            assert node.get('Value')==str(row['address'])
            assert node.findtext('OID') not in before
            inspect_blank_variants(node)
            owner.remove(node)
        elif row['kind']=='group':
            node = app.find(f"Group[Address='{row['address']}']")
            assert node is not None and node.findtext('TagName')==row['name']
            assert node.findtext('OID') not in before
            inspect_blank_variants(node)
            app.remove(node)
        else:
            raise AssertionError('Public fixture only admits group/level creation')
    old_pp = {row.get('Name'):row for row in old.find("Project/Network/Unit[Address='20']").findall('PP')}
    for row in new.find("Project/Network/Unit[Address='20']").findall('PP'):
        if row.get('Name') in allowed: row.set('Value',old_pp[row.get('Name')].get('Value'))
    assert graph(ET.tostring(new,encoding='unicode'))==graph(before)
    assert sum(c.startswith('DBADDSAFE ') for c in commands)==len(creations)
    assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands)==1
    assert commands.count('PROJECT SAVE TEST')==2
    assert commands.count('PROJECT COPY TEST PABACKUP')==1
    assert commands.count('PROJECT CLOSE TEST')==commands.count('PROJECT LOAD TEST')==1


def fresh_state(after,specs,tmp_path,evidence,*,operations=None):
    project = tmp_path/'fresh-inventory.xml'; project.write_text(after)
    parameters = tmp_path/'fresh-inventory-parameters.json'
    parameters.write_text(json.dumps(selector.parent.values(ET.fromstring(after))))
    ops = tmp_path/'fresh-inventory-operations.json'
    ops.write_text(json.dumps(operations if operations is not None else
                   [{'op':'get-selector-view','scene':i} for i in range(1,9)]))
    prefs = tmp_path/'fresh-display-preferences.json'; prefs.write_text(json.dumps(PREFERENCES))
    argv = [sys.executable,'-m','cbus_toolkit','edlt','--spec-dir',str(specs),'scene-manager-state',
        str(parameters),'--project-xml',str(project),'--unit','//TEST/254/p/20',
        '--display-preferences',str(prefs),'--operations',str(ops)]
    process = subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    stdout,stderr = process.communicate(timeout=40)
    evidence.setdefault('offline_calls',[]).append({'pid':process.pid,'argv':argv,'exit':process.returncode,
        'stdout':stdout,'stderr':stderr,'stdout_sha256':hashlib.sha256(stdout.encode()).hexdigest(),
        'stderr_sha256':hashlib.sha256(stderr.encode()).hexdigest()})
    assert process.returncode==0,(stdout,stderr)
    result = json.loads(stdout); assert result['saved'] is False
    return result


def inspect_fresh(result,case):
    assert len(result['operation_results'])==8
    for expected,row in zip(case['expected_scenes_after_fresh_load'],result['operation_results']):
        view = row['view']
        for actual_key,expected_key in (('scene','scene'),('application_selector','application_selector'),
            ('trigger_group','raw_trigger'),('raw_action_selector','raw_action'),
            ('label_value_index','label_value_index')):
            assert view[actual_key]==expected[expected_key],(case['name'],actual_key,view,expected)
        labels = [{'identity':f"label:202/{expected['raw_trigger']}/{expected['raw_action']}/{index}",
            'value':index,'raw_value':str(label['value']),'name':label['name'],
            'image_present':label['image_present']}
            for index,label in enumerate(expected['dynamic_labels'])]
        assert view['dynamic_labels']==labels


def inspect_scene_models(actual,expected):
    assert len(actual)==len(expected)==8
    for model,literal in zip(actual,expected):
        for key,target in (('slot','scene'),('primary_secondary','application_selector'),
                ('can_edit','can_edit'),('raw_trigger','raw_trigger'),('raw_action','raw_action'),
                ('name_index','name_index'),('scene_name','name'),('label_value_index','label_value_index'),
                ('dynamic_labels','dynamic_labels'),('items','items')):
            assert model[key]==literal[target],(literal['scene'],key,model[key],literal[target])


def inspect_standalone_plan(result,case):
    plan = result.get('plan',result)
    timeline = inventory_timeline(plan['automatic_metadata'])
    inspect_initial_bindings(timeline,case)
    scene_plan = plan['scene_manager']
    inspect_scene_models(scene_plan['source']['scenes'],case['expected_scenes_before_save'])
    inspect_scene_models(scene_plan['terminal']['scenes'],case['expected_scenes_after_terminal_save'])
    assert scene_plan['source']['inventory_timeline']['branch']=='edit'
    assert scene_plan['terminal']['inventory_timeline']['branch']=='save'
    assert scene_plan['terminal']['inventory_timeline']['branch_position']==8


def ordered_parent_case():
    """Independent supplied99/100 graph facts around the literal Add2 case.

    Source callback order is99,2,100; native materialization can use its
    separately declared dependency/address order. No producer generates the
    expected choices, scene bytes, names or preservation allowance.
    """
    case = deepcopy(case_named('action-add-explicit-rebind-sees-new-generation'))
    case['name'] = 'prior-add99-scene-add2-later-add100'
    case['input_consumer_pp_parameters'].update(
        ActivityDuration='30',ProximityMode='3',ProximityGroup='42',ProximityLevel='7')
    earlier = {'identity':'action:202/42/99','value':99,
               'name':'Earlier action99','formatted_display':'Earlier action99'}
    for view in case['expected_intermediate_views']:
        view['action_choices'].append(deepcopy(earlier))
        generation = view['action_collection_generation']
        count = 0 if generation=='initial' else int(generation.split(':')[1])
        view['action_collection_generation']='network-refresh:'+str(count+1)
    case['expected_created_objects'].extend([
        {'kind':'level','application':202,'group':42,'address':99,'name':'Earlier action99'},
        {'kind':'level','application':202,'group':42,'address':100,'name':'Later action100'}])
    return case


def inspect_ordered_parent(result,case):
    inspect_intermediate(result,case)
    plan = result.get('plan',result)
    timeline = inventory_timeline(plan['automatic_scene_metadata'])
    initial = next(rows for app,group,rows in timeline['initial']['levels'] if (app,group)==(202,42))
    assert initial==[0,1,7,99]
    assert timeline['initial']['refresh_generation']==1
    assert timeline['initial_scene_bindings']==[
        [42,7,0],[43,9,0],*[[255,-1,0] for _ in range(6)]]
    for frame in timeline['frames']+timeline['save_frames']:
        visible = next(rows for app,group,rows in frame['inventory']['levels'] if (app,group)==(202,42))
        assert 100 not in visible
    assert {(row['kind'],row.get('group'),row['address'],row['name'])
            for row in plan['planned_creations']}=={
        ('Level',42,99,'Earlier action99'),('Level',42,2,'Level 2'),('Level',42,100,'Later action100')}
    dialogs = plan['add_dialogs']
    assert [(row['operation_index'],row['address'],row['name']) for row in dialogs]==[
        (1,99,'Earlier action99'),(3,100,'Later action100')]
    composition = selector.selector_operation(result)['composition']
    inspect_scene_models(composition['terminal_scene_models'],case['expected_scenes_after_terminal_save'])


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
def test_public_inventory_ordered_parent_add99_scene_add2_later_add100(backend,variable,tmp_path,request):
    case = ordered_parent_case()
    operations = [
        {'op':'add-activation-action-dialog','address':99,'name':'Earlier action99'},
        {'op':'scene-manager','operations':case['operations']},
        {'op':'add-activation-action-dialog','address':100,'name':'Later action100'},
        selector.parent.widget()]
    with journey(backend,variable,case,tmp_path) as (owner,relay,evidence,specs,_endpoint,before):
        evidence.update(nodeid=request.node.nodeid,case_id=case['name'],
            test_kind='inventory-ordered-parent-adds',declared_parent_operations=operations)
        preview,read = invoke(relay,evidence,specs,tmp_path,case['operations'],dry_run=True,
            parent_operations=operations)
        inspect_ordered_parent(preview,case)
        assert not any(command.startswith(MUTATIONS) for command in read['commands'])
        assert selector.snapshot(owner)==before
        result,call = invoke(relay,evidence,specs,tmp_path,case['operations'],parent_operations=operations)
        assert result['saved'] and result['persistence_verified'] and result['target_project_save_confirmed']
        inspect_ordered_parent(result,case)
        after = selector.snapshot(owner)
        inspect_saved(before,after,case,call['commands'],extra_pp={'ProximityLevel':[100]})
        fresh = fresh_state(after,specs,tmp_path,evidence)
        inspect_fresh(fresh,case)
        actual42 = next(row for row in fresh['automatic_metadata']['cache']['action_lists'] if row['group']==42)
        assert [(row['address'],row['name']) for row in actual42['actions']]==[
            (0,'Zero'),(1,'Same action'),(2,'Level 2'),(7,'Same action'),
            (99,'Earlier action99'),(100,'Later action100')]
        consumed = fresh_state(after,specs,tmp_path,evidence,operations=[
            {'op':'set-action','scene':1,'action':99},{'op':'get-selector-view','scene':1},
            {'op':'set-action','scene':1,'action':100},{'op':'get-selector-view','scene':1}])
        for address,row in zip((99,100),consumed['operation_results'][1::2]):
            assert row['view']['raw_action_selector']==row['view']['action_selector']==address
            assert row['view']['dynamic_labels']==[
                {'identity':f'label:202/42/{address}/{index}','value':index,
                 'raw_value':str(index),'name':'','image_present':False} for index in range(4)]
        assert consumed['automatic_metadata']['planned_creations']==[]
        assert selector.snapshot(owner)==after
        evidence['snapshots'].update(after_preview=before,after=after)


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
@pytest.mark.parametrize('case',CASES,ids=lambda row:row['name'])
def test_public_inventory_preview_apply_fresh_complete_graph(backend,variable,case,tmp_path,request):
    with journey(backend,variable,case,tmp_path) as (owner,relay,evidence,specs,_endpoint,before):
        evidence.update(nodeid=request.node.nodeid,case_id=case['name'],test_kind='inventory-preview-apply-fresh')
        preview,read = invoke(relay,evidence,specs,tmp_path,case['operations'],dry_run=True)
        inspect_intermediate(preview,case)
        assert not any(c.startswith(MUTATIONS) for c in read['commands'])
        assert selector.snapshot(owner)==before
        result,call = invoke(relay,evidence,specs,tmp_path,case['operations'])
        assert result['saved'] and result['persistence_verified'] and result['target_project_save_confirmed']
        inspect_intermediate(result,case)
        after = selector.snapshot(owner)
        inspect_saved(before,after,case,call['commands'])
        inspect_fresh(fresh_state(after,specs,tmp_path,evidence),case)
        assert selector.snapshot(owner)==after
        evidence['snapshots'].update(after_preview=before,after=after)


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
@pytest.mark.parametrize('name',STANDALONE)
def test_public_inventory_standalone_owner(backend,variable,name,tmp_path,request):
    case = case_named(name)
    with journey(backend,variable,case,tmp_path) as (owner,relay,evidence,specs,_endpoint,before):
        evidence.update(nodeid=request.node.nodeid,case_id=name,test_kind='inventory-standalone')
        state = fresh_state(before,specs,tmp_path,evidence,operations=case['operations'])
        inspect_intermediate(state,case)
        inspect_scene_models(state['state']['scenes'],case['expected_scenes_before_save'])
        preview,read = invoke(relay,evidence,specs,tmp_path,case['operations'],surface='standalone',dry_run=True)
        inspect_standalone_plan(preview,case)
        assert not any(c.startswith(MUTATIONS) for c in read['commands'])
        assert selector.snapshot(owner)==before
        result,call = invoke(relay,evidence,specs,tmp_path,case['operations'],surface='standalone')
        assert result['saved'] and result['persistence_verified']
        inspect_standalone_plan(result,case)
        after = selector.snapshot(owner)
        inspect_saved(before,after,case,call['commands'],surface='standalone')
        inspect_fresh(fresh_state(after,specs,tmp_path,evidence),case)
        evidence['snapshots'].update(after_preview=before,after=after)


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
@pytest.mark.parametrize('name',REFUSALS)
def test_public_inventory_refusal_before_creation(backend,variable,name,tmp_path,request):
    refusal = next(row for row in FACTS['refusals'] if row['name']==name)
    with journey(backend,variable,case_named('populated-history-unchanged'),tmp_path) as data:
        owner,relay,evidence,specs,_endpoint,before = data
        evidence.update(nodeid=request.node.nodeid,case_id=name,test_kind='inventory-refusal')
        result,call = invoke(relay,evidence,specs,tmp_path,refusal['operations'],expected=1)
        assert result and not any(c.startswith(MUTATIONS) for c in call['commands'])
        expected_error = {
            'new-choice-stale-bound-generation':'Selected choice must match current ordinal, identity and value',
            'divergent-action-add-combo-target':'Action Add target needs an explicit trigger selection/rebinding; stale host combo selection is unestablished',
            'pending-name-wrong-bound-target':'SceneName callbacks must match the retained selector form binding; explicitly rebind the scene first'}[name]
        assert result['edlt_parent_metadata_evidence']['error']=={'type':'EdltError','message':expected_error}
        assert selector.snapshot(owner)==before
        evidence['snapshots']['after_refusal']=before


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
def test_public_inventory_known_failure_rolls_back_created_graph(backend,variable,tmp_path,request):
    case = case_named('missing-trigger-getter-requested-not-first-free')
    with journey(backend,variable,case,tmp_path) as (owner,_relay,evidence,specs,endpoint,before):
        evidence.update(nodeid=request.node.nodeid,test_kind='inventory-known-rollback')
        with FaultGate(endpoint,'PP SET','refuse') as fault:
            result,call = invoke(fault,evidence,specs,tmp_path,case['operations'],expected=1)
            assert fault.matches==2  # one refused edit and one source restoration
            assert not any(c.startswith('PP SAVE') for c in call['commands'])
            deletes = [c for c in call['commands'] if c.startswith('DBDELETE ')]
            state = result['edlt_parent_metadata_evidence']
            sets = [(command,call['statuses'][index]) for index,command in enumerate(call['commands'])
                    if command.startswith('PP SET ')]
            assert len(sets)==2 and [status for _command,status in sets]==[408,200]
            session = sets[0][0].split(' ',4)[2]
            proposed = state['plan']['parent_transaction']['changes']['OverallCRC']
            original = selector.parent.values(ET.fromstring(before))['OverallCRC']
            expected_set = lambda values: 'PP SET '+session+' OverallCRC "'+'\\ '.join(map(str,values))+'"'
            assert [command for command,_status in sets]==[expected_set(proposed),expected_set(original)]
            assert proposed!=original
            assert len(deletes)==2
            assert state['automatic_retries']==0 and state['rollback_attempted'] and state['rollback_verified']
            fault_rows = [row for row in fault.evidence() if row.get('fault')]
            assert len(fault_rows)==1 and fault_rows[0]['fault']['occurrence']==1
            rejected = '['+fault_rows[0]['fault']['tag']+'] '+sets[0][0]+'\r\n'
            assert rejected.encode().hex() not in fault_rows[0]['forwarded_request_hex']
            evidence['fault_wires']=fault.evidence()
        assert selector.snapshot(owner)==before
        evidence['snapshots']['after_rollback']=before


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
@pytest.mark.parametrize('phase',('PP SAVE_TO_SOURCE','PROJECT SAVE'),ids=('pp-save','project-save'))
def test_public_inventory_lost_successful_save_never_replayed(backend,variable,phase,tmp_path,request):
    case = case_named('missing-trigger-getter-requested-not-first-free')
    with journey(backend,variable,case,tmp_path) as (owner,_relay,evidence,specs,endpoint,_before):
        evidence.update(nodeid=request.node.nodeid,fault_phase=phase,test_kind='inventory-lost-save')
        with FaultGate(endpoint,phase,'drop',occurrence=2 if phase=='PROJECT SAVE' else 1) as fault:
            result,call = invoke(fault,evidence,specs,tmp_path,case['operations'],expected=1)
            matches = [i for i,c in enumerate(call['commands']) if c.startswith(phase)]
            assert len(matches)==fault.matches==(2 if phase=='PROJECT SAVE' else 1)
            assert not any(c.startswith(('PP SET','PP SAVE','PROJECT SAVE','PROJECT CLOSE','PROJECT LOAD','DBDELETE'))
                           for c in call['commands'][matches[-1]+1:])
            lost = [row for row in fault.evidence() if row.get('fault')]
            assert len(lost)==1
            assert bytes.fromhex(lost[0]['lost_backend_terminal_hex']).decode()==f"[{lost[0]['fault']['tag']}] 200 OK\r\n"
            state = result['edlt_parent_metadata_evidence']
            assert state['state']=='uncertain' and state['database_state_uncertain']
            assert not state['saved'] and not state['persistence_verified'] and state['automatic_retries']==0
            assert state['pp_save_outcome_uncertain'] is (phase=='PP SAVE_TO_SOURCE')
            assert state['target_project_save_outcome_uncertain'] is (phase=='PROJECT SAVE')
            evidence['lost_save_wires']=fault.evidence()
        evidence['snapshots']['after_lost_save']=selector.snapshot(owner)
