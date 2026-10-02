"""Native button planning contracts from complete invented XML, without I/O."""
import json
import pytest

from cbus_toolkit.edlt import EdltError
from tests.test_edlt_scene_button_model import (
    BIND, SELECT42, button, button_model, control, created,
)


def test_button_history_and_modal_results_are_bound_in_timeline_not_caller_operations():
    operations=[control(BIND,SELECT42),button(dialog={'cancel':False,'name':'Second'})]
    editor,state,resolved,_,client=button_model(operations)
    assert resolved.operations==tuple(operations)
    assert resolved.requested_operations==tuple(operations)
    bound=json.loads(resolved.cache._inventory_timeline._binding)
    assert bound['requested_operations']==operations
    receipt=bound['add_dialogs'][0]
    assert receipt['operation_number']==2
    assert receipt['button_operation']==operations[1]
    assert receipt['component_dialogs'][0]['name']=='Second'
    assert receipt['button_control']['request']['returned_value']=='2'
    assert receipt['button_control']['modal_dialog_executed'] is False
    assert [(row.phase,row.callback) for row in resolved.cache._inventory_timeline._frames]==[
        ('operation-start',0),('bind-scene',1),('write-trigger',2),('operation-end',0),
        ('operation-start',0),('button-request',1),('operation-end',0)]
    assert client.commands==[]
    editor.edit(state,operations=resolved.operations)


def test_action_button_target_not_current_raw_trigger_and_terminal_creation_separate():
    ops=[control(BIND,SELECT42),{'op':'set-trigger','scene':1,'group':44},button()]
    _,_,resolved,_,_=button_model(ops)
    assert created(resolved)==[('Level',202,42,2,'Level 2'),('Level',202,44,7,'Action Selector 7')]
    phases=resolved.cache._inventory_timeline._frames
    new=next(row for row in phases if row.phase=='button-request')
    levels={(a,g):rows for a,g,rows in new.inventory.levels}
    assert 2 in levels[(202,42)] and 7 not in levels[(202,44)]
    terminal=resolved.cache._inventory_timeline._save_frames[0]
    assert 7 in {(a,g):rows for a,g,rows in terminal.inventory.levels}[(202,44)]


def test_lighting_button_non202_creation_is_in_causal_snapshot_and_native_receipt():
    ops=[control(BIND),button('new-lighting-group',selected_scenes=[1])]
    _,state,resolved,_,client=button_model(ops,lighting={56:(),57:()})
    assert created(resolved)==[('Group',56,None,0,'Group 0')]
    timeline=resolved.cache._inventory_timeline
    assert (56,0) not in timeline._initial.groups
    frame=next(row for row in timeline._frames if row.phase=='button-request')
    assert (56,0) in frame.inventory.groups
    assert frame.inventory.refresh_generation==timeline._initial.refresh_generation+1
    assert state.cache.application_cache.find_group_list(56).groups==()
    assert client.commands==[]


@pytest.mark.parametrize('bad_name',['', 'Button Model', 'a#b', 'a\nb', ' a  b ', '\ud800'])
def test_accepted_dialog_name_refuses_before_any_native_mutation(bad_name):
    with pytest.raises((EdltError,ValueError,UnicodeError)):
        button_model([control(BIND,SELECT42),button(dialog={'cancel':False,'name':bad_name})])


@pytest.mark.parametrize('kind',['add-trigger-group','add-action-selector','new-lighting-group'])
def test_cancelled_button_records_null_return_and_zero_creation_generation(kind):
    extra={'selected_scenes':[1]} if kind=='new-lighting-group' else {}
    _,_,resolved,_,_=button_model([control(BIND,SELECT42),button(kind,dialog={'cancel':True},**extra)])
    assert resolved.creations==()
    timeline=resolved.cache._inventory_timeline
    assert {row.inventory.refresh_generation for row in timeline._frames}=={timeline._initial.refresh_generation}
    assert json.loads(resolved.add_dialogs[0])['button_control']['request']['returned_value'] is None


def test_no_selected_trigger_does_not_invoke_add_or_infer_group_from_scene_binding():
    _,_,resolved,_,_=button_model([control(BIND),button()])
    assert resolved.creations==()
    receipt=json.loads(resolved.add_dialogs[0])
    assert receipt['component_dialogs']==[]
    assert receipt['button_control']['request'] is None
    assert not any(row.phase=='button-request' for row in resolved.cache._inventory_timeline._frames)


def test_button_binding_without_current_refuses_unproved_selected_value_parse():
    with pytest.raises(EdltError,match='current Scene binding'):
        button_model([button('add-trigger-group')])
    with pytest.raises(EdltError,match='current Scene binding'):
        button_model([button('new-lighting-group',selected_scenes=[1])])


def test_lighting_cancel_does_not_execute_onok_duplicate_seed_or_project_name_checks():
    ops=[control(BIND),button('new-lighting-group',selected_scenes=[1],dialog={'cancel':True})]
    _,_,resolved,_,_=button_model(ops,lighting={56:(20,),57:()},duplicate_seed=True,project_tag='Group 0')
    assert resolved.creations==()
    receipt=json.loads(resolved.add_dialogs[0])['component_dialogs'][0]
    assert receipt['seeded_name']=='Group 0' and receipt['shown_name']=='Group 0'
    assert receipt['outcome']=='cancelled'
    assert 'address' not in receipt


@pytest.mark.parametrize('operations',[
    [button('new-lighting-group',selected_scenes=[])],
    [button('new-lighting-group',selected_scenes=[1,2])],
    [control(BIND),button()],
    [button('add-trigger-group',dialog={'cancel':True})],
    [control(BIND,SELECT42),button(dialog={'cancel':True})],
    [control(BIND),button('new-lighting-group',selected_scenes=[1],dialog={'cancel':True})],
])
def test_missing_project_tag_allowed_only_when_button_never_consumes_onok(operations):
    editor,state,resolved,_,_=button_model(operations,project_tag=None)
    assert resolved.creations==()
    editor.edit(state,operations=resolved.operations)


def test_accepted_actual_dialog_still_requires_exact_project_tag():
    with pytest.raises(EdltError,match='Project.TagName'):
        button_model([control(BIND,SELECT42),button()],project_tag=None)


def test_cancel_still_requires_an_available_provisional_address():
    with pytest.raises(EdltError,match='2271'):
        button_model([control(BIND),button('new-lighting-group',selected_scenes=[1],dialog={'cancel':True})],lighting={56:range(255)})


def test_button_raw_json_has_no_creation_or_history_authority():
    for extra in ({'returned_value':'2'},{'context':{}},{'state':{}},{'creation':{}},{'items':[]}):
        with pytest.raises(EdltError,match='Invalid scene-button-control'):
            button_model([button(**extra)])
