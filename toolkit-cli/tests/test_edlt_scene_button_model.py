"""Actual button callbacks with owner-issued native timelines, no host I/O."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from cbus_toolkit.edlt import EdltError, _render
from cbus_toolkit.edlt_display_model import EdltDisplayPreferences
from cbus_toolkit.edlt_scene_manager import EdltSceneManager, SceneManagerCache
from cbus_toolkit.edlt_scene_metadata import resolve_native_scene_metadata
from tests.test_edlt_lifecycle import fixture
from tests.test_edlt_scene_metadata import SceneMetadataClient
from tests.test_edlt_scene_selectors import VECTOR


BIND = {'event': 'scene-current-changed', 'current': True}
REFRESH = {'event': 'trigger-current-changed'}
SELECT42 = {'event': 'trigger-selected', 'value': 42, 'choice_index': 0, 'choice_identity': 'trigger:202/42'}
ADDRESS_ORDER = EdltDisplayPreferences.from_registry({'SortModeGroups': 1, 'SortModeLevels': 1})


def control(*events, scene=1):
    return {'op': 'scene-selector-control', 'scene': scene, 'events': list(events)}


def button(kind='add-action-selector', *, scene=1, **options):
    return {'op': 'scene-button-control', 'scene': scene, 'button': kind, **options}


def button_model(operations, *, lighting=None, levels=None, source=None, project_tag='Button Model', duplicate_seed=False):
    """Independent invented XML input, complete names/levels/blank widgets."""
    spec = fixture(); editor = EdltSceneManager(spec); client = SceneMetadataClient(spec)
    old = client.applications[202]['groups']
    actual = {42: (0, 1, 7), 43: (0, 7, 9), 44: (0,), 45: ()}
    if levels is not None: actual.update(levels)
    client.applications[202]['groups'] = {address: deepcopy(old[address]) for address in actual}
    for address, values in actual.items():
        group = client.applications[202]['groups'][address]
        group['tag'] = f'Trigger {address}'; group['levels'] = values
        group['level_names'] = {value: f'Existing {address}/{value}' for value in values}
        group['level_tags'] = {value: tuple({'variant': n, 'type': 'TEXT', 'value': f'Label {address}/{value}/{n}'} for n in range(4)) for value in values}
    if lighting is not None:
        for application, rows in lighting.items():
            existing = client.applications[application]['groups']
            from tests.test_edlt_parent_metadata import oid
            selected = {}
            for n in rows:
                item = deepcopy(existing[n] if n in existing else existing[20])
                item['oid'] = oid(100000 + application * 300 + n)
                item['tag'] = f'Owned {application}/{n}'
                selected[n] = item
            client.applications[application]['groups'] = selected
    if duplicate_seed:
        client.applications[56]['groups'][20]['tag']='Group 0'
    raw = {**client.values, **VECTOR['fixture']['consumer_pp_parameters']}
    if source:raw.update(source)
    values = editor.snapshot(raw); client.values = {name:_render(value) for name,value in values.items()}
    from xml.sax.saxutils import escape
    xml = client.xml().replace('<Address>TEST</Address>', '<Address>TEST</Address>' +
        ('' if project_tag is None else '<TagName>'+escape(project_tag)+'</TagName>'), 1)
    resolved = resolve_native_scene_metadata(xml, '//TEST/254/p/20', values, editor, operations, display_preferences=ADDRESS_ORDER)
    state = editor.load(values, metadata=resolved.cache)
    return editor, state, resolved, values, client


def replay(operations, **options):
    editor, state, resolved, values, client = button_model(operations, **options)
    outcome = editor.edit(state, operations=resolved.operations)
    return editor, state, resolved, outcome, client


def rows(outcome):return outcome.as_dict()['operation_results']
def created(resolved):return [(r['kind'],r.get('application',202),r.get('group'),r['address'],r['name']) for r in resolved.as_dict()['planned_creations']]


def test_action_add_selected_trigger_creates_metadata_without_implicit_selection_or_write():
    ops=[control(BIND,SELECT42),button(),{'op':'get-selector-view','scene':1}]
    editor, initial, resolved, outcome, client = replay(ops)
    assert created(resolved)==[('Level',202,42,2,'Level 2')]
    assert outcome.state.scenes[0].raw_action==7
    receipt=rows(outcome)[1]['scene_button_control']
    assert receipt['request']['arguments']==['202','42']
    assert receipt['selected_item'] is None
    assert [r['action'] for r in receipt['callbacks']]==['AddLevelRequest','ObserveItems','ResetCurrentItem','ResetBindings','ResetBindings']
    assert [r['value'] for r in outcome.state.selector_control.as_dict()['view']['action_choices']]==[0,1,7]
    assert [r['value'] for r in rows(outcome)[2]['view']['action_choices']]==[0,1,2,7]
    assert initial.scenes[0].dynamic_labels is outcome.state.scenes[0].dynamic_labels
    assert client.commands==[]
    assert editor.prepare_save(outcome.state).terminal.scenes[0].raw_action==7


def test_action_add_uses_retained_selected42_even_after_raw_trigger_changes43():
    ops=[control(BIND,SELECT42),{'op':'set-trigger','scene':1,'group':43},button()]
    _, initial, resolved, outcome, _=replay(ops)
    assert created(resolved)==[('Level',202,42,2,'Level 2')]
    assert (outcome.state.scenes[0].raw_trigger,outcome.state.scenes[0].raw_action)==(43,7)
    assert rows(outcome)[2]['scene_button_control']['request']['arguments']==['202','42']
    assert outcome.state.scenes[0].dynamic_labels is initial.scenes[0].dynamic_labels


def test_scene_binding_never_infers_selected_trigger_from_raw_property():
    _, initial, resolved, outcome, _=replay([control(BIND),button()])
    assert created(resolved)==[]
    assert rows(outcome)[1]['scene_button_control']['request'] is None
    assert outcome.state.scenes==initial.scenes


def test_explicit_rebind_and_later_action_callback_can_select_new_inventory():
    selected2={'event':'action-selected','value':2,'choice_index':2,'choice_identity':'action:202/42/2'}
    ops=[control(BIND,SELECT42),button(),control(REFRESH,selected2)]
    _, _, resolved, outcome, _=replay(ops)
    assert created(resolved)==[('Level',202,42,2,'Level 2')]
    assert outcome.state.scenes[0].raw_action==2
    assert [r['value'] for r in outcome.state.selector_control.as_dict()['view']['action_choices']]==[0,1,2,7]
    assert outcome.state.scenes[0].dynamic_labels[0].name==''


def test_unrebound_new_action_is_not_selectable_after_button_refresh():
    ops=[control(BIND,SELECT42),button(),control({'event':'action-selected','value':2,'choice_index':2,'choice_identity':'action:202/42/2'})]
    with pytest.raises(EdltError,match='ordinal, identity and value'):button_model(ops)


def test_trigger_button_matches_actual_repopulated_group_list_and_explicitly_writes_trigger():
    _, initial, resolved, outcome, _=replay([control(BIND),button('add-trigger-group')])
    assert created(resolved)==[('Group',202,None,0,'Trigger Group 0'),('Level',202,0,7,'Action Selector 7')]
    receipt=rows(outcome)[1]['scene_button_control']
    assert [r['action'] for r in receipt['callbacks']]==['AddGroupRequest','ObserveItems','SetSelectedIndex','SetCurrencyPosition','WriteValue','ResetCurrentItem','ResetBindings','ResetBindings']
    assert receipt['selected_item']['item']=={'identity':'trigger:202/0','value':'0','name':'Trigger Group 0'}
    assert outcome.state.scenes[0].raw_trigger==0
    assert outcome.state.scenes[0].raw_action==7
    assert initial.scenes[0].dynamic_labels is outcome.state.scenes[0].dynamic_labels
    assert outcome.state.selector_control.action_source_trigger==42


@pytest.mark.parametrize('kind', ['add-trigger-group','add-action-selector','new-lighting-group'])
def test_cancel_is_recorded_without_object_property_or_binding_mutation(kind):
    options={'dialog':{'cancel':True}}
    if kind=='new-lighting-group':options['selected_scenes']=[1]
    _, initial, resolved, outcome, _=replay([control(BIND,SELECT42),button(kind,**options)])
    assert created(resolved)==[]
    assert outcome.state.scenes==initial.scenes
    assert rows(outcome)[1]['scene_button_control']['request']['returned_value'] is None
    assert rows(outcome)[1]['scene_button_control']['selected_item'] is None


@pytest.mark.parametrize(('existing','selector','app','expected'),[((),0,56,0),((0,),0,56,1),((0,1),0,56,0),((),1,57,0)])
def test_lighting_add_values01_are_application_selectors_and_never_insert_scene_items(existing,selector,app,expected):
    ops=[{'op':'set-application','scene':1,'selector':selector},control(BIND),button('new-lighting-group',selected_scenes=[1])]
    _, initial, resolved, outcome, _=replay(ops,lighting={56:existing,57:existing})
    address=0 if not existing else 1 if existing==(0,) else 2
    assert created(resolved)==[('Group',app,None,address,f'Group {address}')]
    assert outcome.state.scenes[0].primary_secondary==expected
    assert outcome.state.scenes[0].items==initial.scenes[0].items
    receipt=rows(outcome)[2]['scene_button_control']
    assert receipt['request']['arguments']==[str(app)]
    assert receipt['selected_item'] is None if address==2 else receipt['selected_item']['item']['value']==str(address)
    assert receipt['scene_items_changed_by_handler'] is False


@pytest.mark.parametrize('selected',[[],[1,2]])
def test_lighting_zero_multiple_rows_return_before_request_and_all_resets(selected):
    _, initial, resolved, outcome, _=replay([button('new-lighting-group',selected_scenes=selected)])
    assert created(resolved)==[]
    assert outcome.state.scenes==initial.scenes
    assert rows(outcome)[0]['scene_button_control']['callbacks']==[]


def test_existing_typed_add_dialog_keeps_its_historical_setter_lowering():
    _, _, resolved, outcome, _=replay([{'op':'add-action-dialog','scene':1}])
    assert resolved.operations==({'op':'set-action','scene':1,'action':2},)
    assert outcome.state.scenes[0].raw_action==2
    assert 'scene_button_control' not in rows(outcome)[0]


def test_pending_scene_name_survives_button_and_still_refuses_save():
    ops=[control(BIND,SELECT42),{'op':'scene-name-control','scene':1,'events':[{'event':'input','text':'Pending'}]},button()]
    editor,_,_,outcome,_=replay(ops)
    assert outcome.state.name_controls[0].pending
    with pytest.raises(EdltError,match='Pending SceneName'):editor.prepare_save(outcome.state)


def test_selected_trigger_is_global_retained_and_owner_fingerprinted():
    ops=[control(BIND,SELECT42),control({'event':'scene-current-changed','current':False},scene=2),button(scene=2)]
    editor,_,resolved,outcome,_=replay(ops)
    assert rows(outcome)[2]['scene_button_control']['request']['arguments']==['202','42']
    assert created(resolved)==[('Level',202,42,2,'Level 2')]
    exported=outcome.state.as_dict();exported['button_selected_trigger']['address']='43'
    assert outcome.state._button_selected_trigger==('trigger:202/42','42')
    forged=replace(outcome.state,_button_selected_trigger=('trigger:202/43','43'))
    with pytest.raises(EdltError,match='intact'):editor.edit(forged,operations=[])


def test_unissued_json_cache_and_other_owner_cannot_authorize_button_replay():
    ops=[control(BIND,SELECT42),button()]
    editor,_,resolved,_,_=replay(ops)
    plain=editor.load(dict(resolved.snapshot.values),metadata=resolved.cache.as_dict())
    with pytest.raises(EdltError,match='owner-issued'):editor.edit(plain,operations=[button()])
    foreign=EdltSceneManager(editor.spec)
    with pytest.raises(EdltError,match='foreign'):foreign.load(dict(resolved.snapshot.values),metadata=resolved.cache)
