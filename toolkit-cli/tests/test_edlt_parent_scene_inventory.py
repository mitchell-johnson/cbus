"""Parent position, initialization provenance and future-fact isolation."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from cbus_toolkit.edlt import EdltError, _render
from cbus_toolkit.edlt_display_model import EdltDisplayPreferences
from cbus_toolkit.edlt_parent_metadata import plan_native_parent_metadata
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from tests.test_edlt_parent_add_dialog import NamedClient, oid, widget
from tests.test_edlt_parent_cache_panels import fixture
from tests.test_edlt_parent_transaction import lighting, measurement
from tests.test_edlt_application_add_dialog import reset_spec
from tests.test_edlt_parent_blank_reset import reset_source

FACTS = json.loads((Path(__file__).resolve().parents[1]/
    'research/fixtures/edlt-scene-inventory-vectors.json').read_bytes())
PREFS = EdltDisplayPreferences.from_dict(FACTS['fixture']['display_preferences'])


def source(name='populated-history-unchanged', *, reset=False):
    case = next(row for row in FACTS['cases'] if row['name']==name)
    spec = reset_spec() if reset else fixture()
    editor = EdltParentTransaction(spec); client = NamedClient(spec)
    if reset:
        client.values = reset_source(spec)
    client.applications[56]['tag']='Lighting'
    client.applications[57]=dict(oid=oid(5700),tag='Secondary',groups={})
    client.applications[203]=dict(oid=oid(20300),tag='Enable Control',groups={})
    cache = FACTS['fixture']['cache']
    labels = {(r['group'],r['action']):r['labels'] for r in cache['level_labels']}
    # The retained initial parent PP consumes non-trigger application objects.
    # Supply their complete native facts; only the tested future Lighting 99
    # remains absent. This is separate from the causal Trigger inventories.
    for application in (56, 57, 203):
        client.applications[application]['groups'] = {
            address: dict(oid=oid(500000 + application * 256 + address),
                          tag=f'Group {address}', levels=())
            for address in range(70)
        }
    removed = {tuple(r) for r in case['input_overrides'].get('remove_levels',[])}
    groups = {}
    for row in cache['trigger_list']['groups']:
        actions = next(v['actions'] for v in cache['action_lists'] if v['group']==row['address'])
        actions = [r for r in actions if (row['address'],r['address']) not in removed]
        groups[row['address']] = dict(oid=oid(2000+row['address']),tag=row['name'],
            levels=tuple(r['address'] for r in actions),
            level_names={r['address']:r['name'] for r in actions},
            level_tags={r['address']:tuple({'variant':i,'type':'TEXT','value':v['name']}
                for i,v in enumerate(labels.get((row['address'],r['address']),[]))) for r in actions})
    client.applications[202]['groups']=groups
    values=editor.snapshot(client.values)
    values.update(case['input_consumer_pp_parameters'])
    client.values={k:_render(v) for k,v in editor.snapshot(values).items()}
    return editor,client,case


def plan(editor,client,operations):
    return plan_native_parent_metadata(client.xml(),'//TEST/254/p/20',
        editor.snapshot(client.values),editor,operations,display_preferences=PREFS)


def scene_receipt(result):
    return next(r for r in result.as_dict()['parent_transaction']['operation_results']
                if r['format']=='cbus-edlt-parent-scene-manager-operation-v1')


@pytest.mark.parametrize('prefix',('measurement','lighting','activation'))
def test_prior_controls_bind_exact_normalized_scene_source(prefix):
    editor,client,case=source('action-add-explicit-rebind-sees-new-generation')
    operation = {'measurement':measurement(position=2),
        'lighting':lighting(position=2,label_text=None),
        'activation':{'op':'activation','wake_mode':'trigger-event','group':42}}[prefix]
    result=plan(editor,client,[operation,{'op':'scene-manager','operations':case['operations']},widget()])
    row=scene_receipt(result)
    assert row['nested_operation_results'][-1]['scene_selector_control']['state']['view']['raw_action_selector']==2
    assert result.parent_plan.as_dict()['execution_counts']['terminal_crc_passes']==1
    assert result.cache._inventory_timeline is not None
    assert result.scene_metadata.cache._inventory_timeline is not None
    assert not any(c.startswith(('DBADD','DBSET','PP ','PROJECT ')) for c in client.commands)


def test_future_widget_group_cannot_enter_prior_scene_inventory():
    editor,client,_case=source()
    client.applications[56]['groups'].pop(99,None)
    later=lighting(position=2,group=99,label_text=None)
    rows=[{'op':'scene-manager','operations':[{'op':'get-selector-view','scene':1}]},later]
    result=plan(editor,client,rows)
    timeline=result.scene_metadata.cache._inventory_timeline.as_dict()
    assert [56,99] not in timeline['initial']['groups']
    assert result.cache.application_cache.lifecycle.find(56,99).exists
    rows[0]['operations'].append({'op':'add-groups','scene':1,'groups':[99]})
    with pytest.raises(EdltError,match='available|metadata|group'):
        plan(editor,client,rows)
    assert not any(c.startswith(('DBADD','DBSET','PP ','PROJECT ')) for c in client.commands)


def test_initial_scene_epochs_survive_genuine_prior_and_future_parent_adds():
    editor,client,case=source('later-initial-getter-keeps-earlier-label-generation')
    client.values.update(ProximityMode='3',ProximityGroup='42',ProximityLevel='0')
    rows=[{'op':'add-activation-action-dialog','address':99,'name':'Earlier action'},
        {'op':'scene-manager','operations':case['operations']},
        {'op':'add-activation-action-dialog','address':100,'name':'Later action'},widget()]
    result=plan(editor,client,rows)
    timeline=result.scene_metadata.cache._inventory_timeline.as_dict()
    assert timeline['initial_scene_bindings'][0]==[42,7,0]
    assert timeline['initial_scene_bindings'][1]==[43,9,1]
    assert timeline['initial']['refresh_generation']==2
    visible={(a,g):actions for a,g,actions in timeline['initial']['levels']}
    assert visible[(202,42)]==[0,1,7,99]
    assert 100 not in visible[(202,42)]
    assert result.cache.application_cache.lifecycle.find(202,42).levels==(0,1,7,99,100)
    getter_rows = [r for r in scene_receipt(result)['nested_operation_results']
                   if r['operation']['op'] == 'get-selector-view']
    assert len(getter_rows) == 1
    view = getter_rows[0]['view']
    assert [r['identity'] for r in view['dynamic_labels']]==[f'label:202/42/7/{i}' for i in range(4)]
    assert [r['name'] for r in view['dynamic_labels']]==['Evening on','Evening wait','Evening off','']
    assert timeline['binding']['initialization_timeline_sha256']


def test_reset_issues_fresh_scene_initialization_without_old_label_binding():
    editor,client,_case=source(reset=True)
    rows=[{'op':'reset', 'active_tab':'widgets',
           'binding_variant':'audited-local-wiring',
           'dirty_parameters':['UnitAddress']}, {'op':'scene-manager','operations':[
        {'op':'set-trigger','scene':1,'group':42},
        {'op':'get-selector-view','scene':1}]},widget()]
    result=plan(editor,client,rows)
    timeline=result.scene_metadata.cache._inventory_timeline.as_dict()
    assert timeline['initial_scene_bindings']==[[255,-1,0]]*8
    view=scene_receipt(result)['nested_operation_results'][-1]['view']
    assert view['trigger_group']==42 and view['raw_action_selector']==-1
    assert view['dynamic_labels']==[]
    assert result.parent_plan.as_dict()['execution_counts']['terminal_crc_passes']==1


def test_serialized_cache_never_recreates_native_inventory_capability():
    editor,client,case=source('action-add-explicit-rebind-sees-new-generation')
    result=plan(editor,client,[{'op':'scene-manager','operations':case['operations']},widget()])
    from cbus_toolkit.edlt_scene_manager import SceneManagerCache
    copied=SceneManagerCache.from_dict(deepcopy(result.cache.as_dict()))
    assert copied._inventory_timeline is None
    other=EdltParentTransaction(editor.spec)
    with pytest.raises(EdltError,match='foreign|owner'):
        other.plan(client.values,metadata=result.cache,
            operations=[{'op':'scene-manager','operations':result.scene_metadata.operations},widget()])
