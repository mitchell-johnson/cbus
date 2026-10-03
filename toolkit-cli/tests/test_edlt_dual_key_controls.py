"""Exact whole-record independent source literals and owner-bound callbacks."""
from copy import copy
from dataclasses import replace
import json
from pathlib import Path
import pytest
from cbus_toolkit.edlt import EdltError, _field
from cbus_toolkit import edlt_dual_key_control_properties as props
from cbus_toolkit import edlt_dual_key_controls as controls

FIXTURE = Path(__file__).resolve().parents[1] / 'research/fixtures/edlt-dual-key-control-literal-vectors.json'
VECTORS = json.loads(FIXTURE.read_text())
NAMES = tuple(f'Name {i}' for i in range(64))

def values_for(record, restore=91):
    values = {_field(6,i):(val,) for i,val in enumerate(record)}
    values.update({_field(7,i):(val,) for i,val in enumerate(bytes(range(32)))})
    values['Widget6RestoreLevel']=(restore,)
    values['Widget7RestoreLevel']=(177,)
    values.update({f'StaticTextString{i}':tuple([0]*64) for i in range(64)})
    values.update(UseBigIcon=(1,), UnitName='Exact text', Scene8StartAddress=(65535,), Unrelated=(19,32,77))
    return values


def runtime(case, *, owner=None, initial_state=None, operation_number=1, default_initialized=False):
    family=case['family'];record=bytes.fromhex(case['record_before_hex'])
    values=values_for(record,case.get('restore_level',91));owner=object() if owner is None else owner
    operation={'op':family,'dual_key_controls':case['events']}
    binding=controls.issue_dual_key_control_binding(owner=owner,operation=operation,values=values,
        family=family,widget=6,retained_names=NAMES,external_used_indices=(1,9,200,255),
        operation_number=operation_number,initial_state=initial_state,default_initialized=default_initialized)
    return owner,operation,values,binding


@pytest.mark.parametrize('case',VECTORS['property_cases'],ids=lambda c:c['case_id'])
def test_source_complete_record_properties(case):
    state=props.DualKeyPropertyState(case['family'],bytes.fromhex(case['record_before_hex']),case['restore_level'])
    result=(props.write_dual_key_property(state,case['property'],case['value']) if case['action']=='write'
            else props.read_dual_key_property(state,case['property']))
    assert result.state.record.hex()==case['expected_record_hex']
    assert result.state.restore_level==91
    assert result.as_dict()['assignment_intents']==case['expected_writes']
    assert result.as_dict()['notification_intents']==case['expected_notifications']
    assert result.value==case['expected_observed']


@pytest.mark.parametrize('case',VECTORS['control_cases'],ids=lambda c:c['case_id'])
def test_source_complete_record_control_histories(case):
    owner,op,values,binding=runtime(case)
    before=dict(values)
    result=controls.project_dual_key_controls(binding,owner=owner,operation=op,values=values,retained_names=NAMES)
    record,changes,receipt=controls.prepare_dual_key_projection(result,owner=owner)
    assert record.hex()==case['expected_record_hex']
    assert result.restore_level==91 and result.retained_names==NAMES
    assert [r['assignment_intents'] for r in receipt['journal']]==case['expected_journal_writes']
    if 'expected_notifications' in case:
        assert [r['notification_intents'] for r in receipt['journal']]==case['expected_notifications']
    for target,expected in case.get('expected_levels',{}).items():
        actual=receipt['state']['levels'][target]
        assert {k:actual[k] for k in expected}==expected
    if 'expected_timer_seconds' in case:
        assert receipt['state']['timer_seconds']==case['expected_timer_seconds']
    assert values==before
    after={**values,**changes}
    expected=dict(values)
    expected.update({_field(6,i):(val,) for i,val in enumerate(record)})
    assert after==expected
    assert receipt['automatic_framework_dispatch_inferred'] is False
    assert receipt['original_host_executed'] is False and result.pending is False


def simple(events=None,family='timer'):
    case=next(c for c in VECTORS['control_cases'] if c['family']==family)
    return {**case,'events':events or [{'event':'get-view'}]}


@pytest.mark.parametrize('kind', ['binding-copy','binding-replace','binding-owner-none','binding-foreign',
    'stale-record','stale-other-field','stale-operation','stale-names','retained-name-same-PP',
    'binding-mutated-pin','binding-mutated-source-default'])
def test_binding_requires_original_instance_and_complete_facts(kind):
    owner,op,values,binding=runtime(simple());names=NAMES
    if kind=='binding-copy':binding=copy(binding)
    elif kind=='binding-replace':binding=replace(binding)
    elif kind=='binding-owner-none':owner=None
    elif kind=='binding-foreign':owner=object()
    elif kind=='stale-record':values={**values,_field(6,20):(99,)}
    elif kind=='stale-other-field':values={**values,'UnitName':'changed'}
    elif kind=='stale-operation':op={**op,'page':2}
    elif kind in ('stale-names','retained-name-same-PP'):names=(*NAMES[:63],'Long retained name')
    elif kind=='binding-mutated-pin':object.__setattr__(binding,'provider_sha256','1'*64)
    else:object.__setattr__(binding,'default_initialized',True)
    with pytest.raises(EdltError):
        controls.project_dual_key_controls(binding,owner=owner,operation=op,values=values,retained_names=names)


@pytest.mark.parametrize('kind',['result-copy','result-replace','foreign','none','record','state','model','level'])
def test_projection_or_continuation_cannot_promote_mutated_payload(kind):
    owner,op,values,binding=runtime(simple([{'event':'level-set','target':'expiry','value':17}]))
    result=controls.project_dual_key_controls(binding,owner=owner,operation=op,values=values,retained_names=NAMES)
    if kind=='result-copy':result=copy(result)
    elif kind=='result-replace':result=replace(result)
    elif kind=='foreign':owner=object()
    elif kind=='none':owner=None
    elif kind=='record':object.__setattr__(result,'record',bytes([5]+[0]*31))
    elif kind=='state':object.__setattr__(result.state,'timer_seconds',999)
    elif kind=='model':object.__setattr__(result.state.model,'editable',(False,)*4)
    elif kind=='level':object.__setattr__(dict(result.state.levels)['expiry'],'value',99)
    with pytest.raises(EdltError):controls.prepare_dual_key_projection(result,owner=owner)


@pytest.mark.parametrize('family,event',[('timer',{'event':'binding-write','target':'macro','value':35,'identity':'x'}),
 ('room-courtesy',{'event':'binding-write','target':'icon-off','value':77}),
 ('shutter',{'event':'timer-read'}),('room-courtesy',{'event':'level-set','target':'target','value':12}),
 ('timer',{'event':'binding-write','target':'ramp-rate','value':1,'identity':'wrong'}),
 ('timer',{'event':'binding-write','target':'ramp-rate','value':True,'identity':'dual-key-ramp:True'}),
 ('timer',{'event':'level-set','target':[],'value':1}),('timer',{'event':'level-read','target':'target','state':{}}),
 ('timer',{'event':'timer-value-changed','seconds':86400}),('timer',{'event':'timer-set-value','seconds':2147483648}),
 ('timer',{'event':'input','text':'12:34'}),('timer',{'event':'close'}),
 ('timer',{'event':'get-property','property':'KeyMacrofunction'}),('shutter',{'event':'get-property','property':'TimerValue'}),
 ('room-courtesy',{'event':'level-add','target':'group','accepted':True})])
def test_normalization_refuses_unproven_shape_before_owner(family,event):
    with pytest.raises(EdltError):controls.normalize_dual_key_controls([event],family=family)


def test_continuation_keeps_source_macro_flags_and_exact_numeric_display():
    case=simple([{'event':'get-property','property':'DualButtonMacrofunction'}])
    owner,op,values,binding=runtime(case)
    first=controls.project_dual_key_controls(binding,owner=owner,operation=op,values=values,retained_names=NAMES)
    assert first.state.model.editable==(False,)*4
    # Owner advances the source record to a ramp macro, keeping private flags.
    # A different record cannot reuse continuation without a corresponding
    # issued projection. Two operations on the same unchanged record can.
    nextop={'op':'timer','dual_key_controls':[{'event':'get-property','property':'RampRateEditable'}]}
    nextbinding=controls.issue_dual_key_control_binding(owner=owner,operation=nextop,values=values,
        family='timer',widget=6,retained_names=NAMES,external_used_indices=(),operation_number=2,initial_state=first.state)
    second=controls.project_dual_key_controls(nextbinding,owner=owner,operation=nextop,values=values,retained_names=NAMES)
    assert second.as_dict()['journal'][0]['observed'] is False
    with pytest.raises(EdltError):
        controls.issue_dual_key_control_binding(owner=owner,operation=nextop,values=values,
            family='timer',widget=6,retained_names=NAMES,external_used_indices=(),operation_number=2,initial_state=replace(first.state))


def test_source_macro_getter_false_to_true_resets_timer_ramp_only_on_explicit_read():
    r=bytearray(bytes.fromhex(simple()['record_before_hex']));r[7:9]=bytes([15,16]);r[16]=9
    state=props.DualKeyPropertyState('timer',bytes(r),91,(False,)*4)
    view=props.dual_key_readonly_view(state)
    assert view['source_editable_flags']==[False]*4 and state.record[16]==9
    result=props.read_dual_key_property(state,'DualButtonMacrofunction')
    assert result.writes==((16,1),) and result.notifications==('InputValues',)
    assert result.state.editable==(True,False,False,False)
    assert result.value=='15|16'


def test_source_defaults_initialize_private_flags_without_extra_record_writes():
    owner,op,values,binding=runtime(simple(),default_initialized=True)
    result=controls.project_dual_key_controls(binding,owner=owner,operation=op,values=values,retained_names=NAMES)
    assert result.record==bytes.fromhex(simple()['record_before_hex'])
    assert result.state.model.editable==(False,)*4
    assert result.as_dict()['binding']['model_initialization']=='source-default'


def test_no_changed_suppresses_delivery_not_explicit_binding_write():
    owner,op,values,binding=runtime(simple([{'event':'level-no-changed','target':'expiry','value':17}]))
    result=controls.project_dual_key_controls(binding,owner=owner,operation=op,values=values,retained_names=NAMES)
    cb=result.as_dict()['journal'][0]['binding_callbacks']
    assert cb[0]['event_delivery_suppressed'] is True
    assert cb[1]=={'action':'Binding.WriteValue','target':'expiry','value':17}


def test_icon_requires_causal_visible_setting_not_modal_claim():
    owner,op,values,binding=runtime(simple([{'event':'binding-write','target':'icon-on','value':77}],family='room-courtesy'))
    values['UseBigIcon']=(0,)
    binding=controls.issue_dual_key_control_binding(owner=owner,operation=op,values=values,
        family='room-courtesy',widget=6,retained_names=NAMES,external_used_indices=())
    with pytest.raises(EdltError,match='UseBigIcon'):
        controls.project_dual_key_controls(binding,owner=owner,operation=op,values=values,retained_names=NAMES)


@pytest.mark.parametrize('family', ['timer', 'shutter', 'room-courtesy'])
def test_used_static_text_uses_source_clamped_static_getters_without_writing(family):
    case=simple(family=family)
    raw=bytearray(bytes.fromhex(case['record_before_hex']))
    raw[1]=0xB5
    raw[props.OFFSETS[family]['label']]=200
    raw[props.OFFSETS[family]['status']]=255
    state=props.DualKeyPropertyState(family,bytes(raw),91)
    assert state.used_static_text()==(0,)
    assert props.dual_key_readonly_view(state)['raw_label_index']==200
    assert state.record==bytes(raw)
