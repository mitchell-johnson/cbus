"""Ordered parent Language boundaries preserve prior/future label ownership."""
import json

import pytest

from cbus_toolkit.edlt_parent_metadata import plan_native_parent_metadata
from tests.test_edlt_scene_language_initializer import language_source,LITERALS,UNIT,operation
from tests.test_edlt_parent_add_dialog import widget


def plan(data,operations):
    parent=data[0]
    return plan_native_parent_metadata(data[3],UNIT,parent.snapshot(data[2].values),parent,operations)


def scene_result(result):
    return next(row for row in result.parent_plan.as_dict()['operation_results']
                if row['format']=='cbus-edlt-parent-scene-manager-operation-v1')


@pytest.mark.parametrize('setter',[False,True])
def test_prior_language_then_selector_preserves_old_or_explicit_current_labels(setter):
    data=language_source()
    children=([{'op':'set-action','scene':1,'action':7}] if setter else [])
    children += [{'op':'get-selector-view','scene':1}]
    result=plan(data,[operation(),{'op':'scene-manager','operations':children},widget()])
    view=scene_result(result)['nested_operation_results'][-1]['view']
    assert [row['name'] for row in view['dynamic_labels']]==LITERALS['current_labels' if setter else 'old_labels']
    assert result.parent_plan.as_dict()['execution_counts']['terminal_crc_passes']==1
    assert result.scene_metadata.cache._inventory_timeline.as_dict()['binding']['language_initializer_sha256']
    assert data[2].commands==[]


def test_later_language_cannot_change_earlier_scene_getter_receipt():
    data=language_source()
    result=plan(data,[{'op':'scene-manager','operations':[{'op':'get-selector-view','scene':1}]},operation(),widget()])
    view=scene_result(result)['nested_operation_results'][-1]['view']
    assert [row['name'] for row in view['dynamic_labels']]==LITERALS['old_labels']
    assert result.scene_metadata.cache._inventory_timeline.as_dict()['binding']['language_initializer_sha256'] is None


@pytest.mark.parametrize('op',[operation(cancel=True),operation((1,2))],ids=['cancel','noop'])
def test_parent_cancel_and_noop_have_no_language_refresh(op):
    data=language_source()
    result=plan(data,[op,{'op':'scene-manager','operations':[{'op':'get-selector-view','scene':1}]},widget()])
    timeline=result.scene_metadata.cache._inventory_timeline
    assert timeline._initial.refresh_generation==0
    assert [row['name'] for row in scene_result(result)['nested_operation_results'][-1]['view']['dynamic_labels']]==LITERALS['old_labels']


def test_language_then_pending_name_is_not_discarded_by_selector_rebinding():
    data=language_source()
    rows=[operation(),{'op':'scene-manager','operations':[
        {'op':'scene-name-control','scene':1,'events':[{'event':'input','text':'Pending name'}]},
        {'op':'scene-selector-control','scene':1,'events':[{'event':'scene-current-changed','current':True}]}]},widget()]
    with pytest.raises(ValueError,match='pending|Pending|uncommitted'):
        plan(data,rows)


def test_reset_then_language_uses_fresh_scene_owners():
    data=language_source(reset=True)
    rows=[{'op':'reset','active_tab':'widgets','binding_variant':'audited-local-wiring','dirty_parameters':['UnitAddress']},
          operation(),{'op':'scene-manager','operations':[{'op':'get-selector-view','scene':1}]},widget()]
    result=plan(data,rows)
    assert result.scene_metadata.cache._inventory_timeline._initial_scene_bindings==((255,-1,0),)*8
    assert scene_result(result)['nested_operation_results'][-1]['view']['dynamic_labels']==[]
    assert result.parent_plan.as_dict()['execution_counts']['terminal_crc_passes']==1


def test_button_only_empty_selection_still_receives_causal_language_initializer():
    data=language_source()
    result=plan(data,[operation(),{'op':'scene-manager','operations':[
        {'op':'scene-button-control','scene':1,'button':'new-lighting-group','selected_scenes':[]}]},widget()])
    timeline=result.scene_metadata.cache._inventory_timeline
    assert timeline is not None
    assert timeline.as_dict()['binding']['language_initializer_sha256']
    row=scene_result(result)['nested_operation_results'][0]['scene_button_control']
    assert row['early_return'] is True
    assert row['request'] is None
    assert row['callbacks'] == []


@pytest.mark.parametrize('op',[operation(cancel=True),operation((2,1))],ids=['cancel','noop'])
def test_no_language_mutation_preserves_exact_original_xml_declaration(op):
    data=language_source(encoded_declaration=True)
    result=plan(data,[op,{'op':'scene-manager','operations':[{'op':'get-selector-view','scene':1}]},widget()])
    binding=result.scene_metadata.cache._inventory_timeline.as_dict()['binding']['language_initializer']
    assert binding['refresh_count']==0
    assert binding['binding']['original_xml_sha256']==binding['binding']['projected_xml_sha256']
    assert [row['name'] for row in scene_result(result)['nested_operation_results'][-1]['view']['dynamic_labels']]==LITERALS['old_labels']
    assert data[2].commands==[]


def test_language_before_reset_retains_established_operation_one_reset_refusal():
    data=language_source(reset=True)
    with pytest.raises(ValueError,match='Reset must be operation 1'):
        plan(data,[operation(),{'op':'reset','active_tab':'widgets',
            'binding_variant':'audited-local-wiring','dirty_parameters':['UnitAddress']},
            operation(),{'op':'scene-manager','operations':[{'op':'get-selector-view','scene':1}]},widget()])
    assert data[2].commands==[]
