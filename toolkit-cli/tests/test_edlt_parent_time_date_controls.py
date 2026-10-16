"""Exact Time/Date callback parent ownership, phase and replay regressions."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import pytest
from cbus_toolkit.edlt import EdltError, _field, _render
from cbus_toolkit.edlt_parent_metadata import plan_native_parent_metadata
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction, normalize_operations
from tests.test_edlt import Session
from tests.test_edlt_parent_cache_panels import fixture as old_fixture
from tests.test_edlt_parent_metadata import MetadataClient
from tests.test_edlt_scene import prepared

LITERALS = json.loads(Path(__file__).with_name('time-date-public-literals.json').read_text())
CASES = LITERALS['positive_profiles']
UNIT = '//TEST/254/p/20'


def fixture():
    spec = old_fixture()
    parameters = dict(spec.parameters)
    old = parameters.pop('OpaqueFormatBit')
    parameters['LevelBarStyle'] = replace(old, name='LevelBarStyle', type='int', fields={**old.fields,'Name':'LevelBarStyle','Type':'int'})
    return replace(spec, parameters=parameters)


def model(case, spec=None):
    spec = fixture() if spec is None else spec; editor = EdltParentTransaction(spec)
    source = editor.snapshot(prepared(spec.defaults()))
    source['NavWidgetType'] = (1,)
    for offset,value in enumerate(bytes.fromhex(LITERALS['fixture']['record_hex'])):
        source[_field(6,offset)] = (value,)
    source['Widget6RestoreLevel'] = (213,)
    source[_field(7)] = (255,)
    for slot, literal in case['source_records_hex'].items():
        for offset, value in enumerate(bytes.fromhex(literal)):
            source[_field(int(slot), offset)] = (value,)
        if int(slot)>=6: source[f'Widget{slot}RestoreLevel'] = (213,)
    functional = [int(k) for k in case['source_records_hex'] if int(k)>=6]
    if functional: source[_field(max(functional)+1)] = (255,)
    source.update({name:(value,) for name,value in case['source_globals'].items()})
    source['LevelBarStyle'] = (1,)
    for index,literal in LITERALS['source_rows_hex'].items():
        source['StaticTextString'+index] = tuple(bytes.fromhex(literal))
    client = MetadataClient(spec)
    client.values = {name:_render(value) for name,value in source.items()}
    client.saved_values = deepcopy(client.values)
    return editor, client, source


def native(case):
    editor,client,source = model(case)
    return editor,client,source,plan_native_parent_metadata(client.xml(), UNIT, source, editor, case['operations'])


@pytest.mark.parametrize('case', CASES, ids=lambda case:case['id'])
def test_literal_complete_records_globals_and_all_static_rows(case):
    editor,client,source,plan = native(case)
    controls,terminal = plan.parent_plan.after_controls,plan.parent_plan.before_save
    for slot,literal in case['expected_records_hex'].items():
        expected=bytes.fromhex(literal)
        assert bytes(controls[_field(int(slot),i)][0] for i in range(32)) == expected
        assert bytes(terminal[_field(int(slot),i)][0] for i in range(32)) == expected
    for slot,value in case['restore_levels'].items():
        assert terminal[f'Widget{slot}RestoreLevel'] == (value,)
    for name,value in case['expected_globals'].items(): assert terminal[name] == (value,)
    assert terminal['LevelBarStyle'] == source['LevelBarStyle'] == (1,)
    assert all(bytes(terminal['StaticTextString'+index]).hex()==literal for index,literal in LITERALS['expected_rows_hex'].items())
    doc=plan.parent_plan.as_dict()
    rows=[row for row in doc['operation_results'] if 'time_date_controls' in row]
    assert [row['reserved_widget_slots'] for row in rows] == case['expected_reserved_slots']
    assert all(not row['time_date_controls']['pending'] for row in rows)
    assert len(plan.parent_plan.time_date_control_bindings)==len(rows)
    assert doc['execution_counts']['terminal_crc_passes']==1
    assert client.commands==[]


def test_raw_readonly_preserves_display255_and_old_scalar_refusal():
    case=CASES[0];editor,_,source,plan=native(case)
    assert plan.parent_plan.after_controls[_field(7,1)]==(255,)
    row=plan.parent_plan.as_dict()['operation_results'][0]
    assert row['time_date_control_base']['converted'] is False
    with pytest.raises(EdltError,match='display byte'):
        editor._editor('time-date').plan(source,page=1,position=2)


@pytest.mark.parametrize('mutation', ('owner','number','widget','source','copy'))
def test_binding_cannot_be_rebound_or_copied(mutation):
    case=CASES[1];editor,_,source,plan=native(case)
    binding=plan.parent_plan.time_date_control_bindings[0]
    if mutation=='owner': binding=replace(binding,_owner=EdltParentTransaction(editor.spec))
    elif mutation=='number': binding=replace(binding,operation_number=2)
    elif mutation=='widget': binding=replace(binding,widget=8)
    elif mutation=='source': source={**source,'LevelBarStyle':(0,)}
    else: binding=replace(binding)
    with pytest.raises(EdltError,match='issued|owner|binding|source|snapshot'):
        editor.plan(source,metadata=plan.cache,operations=plan.parent_plan.operations,
                    _time_date_control_bindings=(binding,))


def test_canonical_apply_retains_exact_bindings_and_one_write_per_parameter():
    editor,_,source,native_plan=native(CASES[1]);session=Session(editor.spec);session.current=dict(source)
    result=editor.apply(session,native_plan.parent_plan)
    assert result['verified'] is True
    assert len(session.calls)==len({name for name,value in session.calls})


@pytest.mark.parametrize('case',LITERALS['refusal_profiles'],ids=lambda case:case['id'])
def test_shared_normalizer_refuses_caller_state_and_invented_choices(case):
    with pytest.raises(EdltError,match=case['expected_error']): normalize_operations(case['operations'])


def test_manual_metadata_cannot_issue_callbacks():
    editor,_,source,plan=native(CASES[1])
    with pytest.raises(EdltError,match='owner-issued'):
        editor.plan(source,metadata=plan.cache,operations=CASES[1]['operations'])


def test_conflicting_global_writes_refuse_without_io():
    case=deepcopy(CASES[-1]);case['operations'][1]['time_date_controls'][0].update(value=6,choice_index=6,identity='time-date-date-format:6')
    editor,client,source=model(case)
    with pytest.raises(EdltError,match='ownership'):
        plan_native_parent_metadata(client.xml(),UNIT,source,editor,case['operations'])
    assert client.commands==[]


@pytest.mark.parametrize('first_grows',(True,False))
def test_actual_adjacent_ownership_conflicts_in_both_orders(first_grows):
    case=deepcopy(CASES[2]);growth=case['operations'][0]
    growth['time_date_controls'].append({'event':'binding-write','target':'widget-type','value':10,'choice_index':3,'identity':'time-date-widget-type:10'})
    neighbor={'op':'time-date','page':0,'position':2,'display':'time','time_date_controls':[{'event':'get-view'}]}
    case['operations']=[growth,neighbor] if first_grows else [neighbor,growth]
    editor,client,source=model(case)
    with pytest.raises(EdltError,match='ownership'):
        plan_native_parent_metadata(client.xml(),UNIT,source,editor,case['operations'])
    assert client.commands==[]


def test_standby_five_does_not_offer_two_slices_and_covered_slot_is_not_bypassed():
    case=deepcopy(CASES[3]);case['operations'][0]['position']=5
    editor,client,source=model(case)
    with pytest.raises(EdltError,match='ordinal|Two-slice'):
        plan_native_parent_metadata(client.xml(),UNIT,source,editor,case['operations'])
    case=deepcopy(CASES[4]);case['operations'][0]['position']=2
    editor,client,source=model(case)
    with pytest.raises(EdltError,match='covered'):
        plan_native_parent_metadata(client.xml(),UNIT,source,editor,case['operations'])


def test_prior_reset_issues_binding_from_fresh_defaults():
    case=deepcopy(CASES[1]);case['operations']=[{'op':'reset','active_tab':'widgets','binding_variant':'audited-local-wiring'},case['operations'][0]]
    from tests.test_edlt_parent_blank_reset import complete_spec
    base=complete_spec();parameters=dict(base.parameters);extended=fixture()
    additions=[name for name in extended.parameters if name not in parameters]
    padding=[name for name in parameters if name.startswith('OwnedPadding')]
    for name in padding[:len(additions)]: del parameters[name]
    parameters.update({name:parameter for name,parameter in extended.parameters.items()
                       if name!='NavWidgetType' and not name.endswith('WidgetType')})
    assert len(parameters)==874
    editor,client,source=model(case,spec=replace(base,parameters=parameters))
    from tests.test_edlt_parent_metadata import oid
    client.applications[203]={'oid':oid(203),'tag':'Enable Control','groups':{}}
    client.applications[56]['groups'][42]={'oid':oid(5642),'tag':'Reset declared group','levels':()}
    plan=plan_native_parent_metadata(client.xml(),UNIT,source,editor,case['operations'])
    binding=plan.parent_plan.time_date_control_bindings[0]
    assert binding.operation_number==2
    assert plan.parent_plan.before_save[_field(7)]==(10,)
    assert plan.parent_plan.before_save['Widget7RestoreLevel']==(0,)


def test_pending_scene_name_cannot_be_saved_by_later_time_date_callbacks():
    case=deepcopy(CASES[1])
    case['operations']=[{'op':'scene-manager','operations':[{'op':'scene-name-control','scene':1,
        'events':[{'event':'input','text':'Still pending'}]}]},case['operations'][0]]
    editor,client,source=model(case)
    with pytest.raises(EdltError,match='Pending SceneName|pending'):
        plan_native_parent_metadata(client.xml(),UNIT,source,editor,case['operations'])
    assert client.commands==[]
