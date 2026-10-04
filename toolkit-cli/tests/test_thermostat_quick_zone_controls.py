"""Independent literals for one fresh source-owned callback owner; no I/O."""
from copy import deepcopy
from dataclasses import replace

import pytest

from cbus_toolkit.thermostat_quick_zone_controls import (
    ThermostatControlModel, normalize_quick_zone_operation, prepare_quick_zone_save)
from cbus_toolkit.thermostat_output_groups import OutputGroupModel
from cbus_toolkit.thermostat_remote_references import (
    _GraphResolver, ProjectGraphSnapshot, RemoteApplication)
from cbus_toolkit.thermostat_templates import ThermostatTemplateError
from test_thermostat_plant_types import base_pp, retained


def model(kind='PC_TSA5', *, changes=None, groups=None):
    values = base_pp(3)
    values.update(MinimumSetTemperature=15, MaximumSetTemperature=32,
                  GuardEnable=0, PlantMinimumOnTime=1, PlantMinimumOffTime=2,
                  PlantCycleTime=12, EvapProgramEnabled=1, NonEvapProgramEnabled=1,
                  RemoteScheduleEnable=1)
    values.update(changes or {})
    inventory = [(255, '<Unused>'), (70, 'Opaque user & Ω'), (71, 'Other user')]
    inventory += list(groups or [])
    applications = (
        RemoteApplication(56, 'app56', 'Lighting', tuple(retained(n,name) for n,name in inventory), 'opaque56'),
        RemoteApplication(172, 'app172', 'Air Conditioning', (retained(7,'Zone',172),), 'opaque172'),
        RemoteApplication(203, 'app203', 'Enable Control', tuple(retained(n,'Schedule '+str(n),203) for n in (32,33,34,255)), 'opaque203'))
    graph=ProjectGraphSnapshot('QZONE',11,20,'//QZONE/11/20',(),applications,(), 'shape','digest')
    resolver=_GraphResolver(graph)
    owner=OutputGroupModel(values,'basic' if 'TSB' in kind else 'programmable',kind,resolver)
    owner.load()
    remotes={role:resolver.live[(203,n)] for role,n in (('schedule_on',32),('schedule_off',33),('schedule_override',34))}
    return ThermostatControlModel(owner,temperature_preference='celsius',remote_references=remotes)


def call(m,op,**kw):
    return m.process({'op':op,**kw},m._position+1,project_tag_name='QZONE',validate_address=lambda p,a:None)


def test_one_live_store_and_real_installation_order():
    m=model()
    assert m.values is m.output.values is m.plant.values
    assert m.plant.references is m.output.references
    assert m.damper._owner is m.output
    assert [x.code for x in m._installations]==list(range(10))
    assert m._installation is m._installations[0]
    assert m._current_installation()=='<Custom>'


@pytest.mark.parametrize('code',[2,3,7])
def test_basic_omitted_installation_is_nil_before_real_item0_reset(code):
    m=model('PC_TSB',changes={'InstallationCode':code})
    assert [x.code for x in m._installations]==[0,1,4,5,6,8,9]
    assert m._installation is None
    assert m._current_installation() is None
    call(m,'select-plant-type',value=0)
    call(m,'dispatch-plant-type-change',posted_by=1)
    assert m._installation is m._installations[0]


def test_include_then_exclude_literal_masks_and_loaded_master():
    m=model()
    call(m,'quick-zone-click',zone=2,checked=True)
    assert m._used==4
    assert {k:m.values[k] for k in ('UIAllocatedZones','InternalPlantZones','MeasuredZones','ScheduleControlledZones','InstalledZones','ControlledZones')}=={
        'UIAllocatedZones':6,'InternalPlantZones':30,'MeasuredZones':5,
        'ScheduleControlledZones':4,'InstalledZones':30,'ControlledZones':30}
    call(m,'quick-zone-click',zone=2,checked=False)
    assert m._used==0
    assert {k:m.values[k] for k in ('UIAllocatedZones','InternalPlantZones','MeasuredZones','ScheduleControlledZones','InstalledZones','ControlledZones')}=={
        'UIAllocatedZones':2,'InternalPlantZones':26,'MeasuredZones':1,
        'ScheduleControlledZones':0,'InstalledZones':26,'ControlledZones':26}
    assert m._loaded_master and m.output.master


def test_last_checkbox_warning_and_unswitched_response_order():
    m=model()
    call(m,'quick-zone-click',zone=0,checked=False,confirm_unswitched=False)
    assert [r['code'] for r in m._alerts]==[7320]
    assert m._quick_checked[0]
    for zone in (1,2,3,4):
        call(m,'quick-zone-click',zone=zone,checked=False)
    call(m,'quick-zone-click',zone=0,checked=False,confirm_unswitched=True)
    assert [r['code'] for r in m._alerts]==[7320,7321]
    assert m._quick_checked==[True,False,False,False,False]
    assert m.values['ControlledZones']==0
    assert m._loaded_master and m.save_facts['controlled_zones']==m.values['InstalledZones']


@pytest.mark.parametrize('value',range(12))
def test_every_source_offered_choice_posts_and_only_owned_dispatch_allocates(value):
    m=model()
    old_graph=list(m.output.resolver.operations)
    call(m,'select-plant-type',value=value)
    assert m.values['InternalPlantType']==value
    assert list(m.output.resolver.operations)==old_graph
    assert m.queue.as_dict()['pending_positions']==[1]
    with pytest.raises(ThermostatTemplateError,match='pending'):
        m.issue_save()
    call(m,'dispatch-plant-type-change',posted_by=1)
    assert not m.queue.as_dict()['pending_positions']
    assert m._installation is m._installations[0]
    assert not any(m._guards.values())
    with pytest.raises(ThermostatTemplateError,match='consumed'):
        call(m,'dispatch-plant-type-change',posted_by=1)


def test_multiple_posts_deliver_live_type_and_do_not_restore_enqueue_snapshot():
    m=model()
    call(m,'select-plant-type',value=1)
    call(m,'select-plant-type',value=2)
    call(m,'dispatch-plant-type-change',posted_by=1)
    assert m.values['InternalPlantType']==2
    assert m.queue.as_dict()['pending_positions']==[2]
    call(m,'dispatch-plant-type-change',posted_by=2)
    assert m.values['InternalPlantType']==2


def test_shared_select_edit_add_and_damper_callback_observe_live_identity():
    m=model()
    original=m.output.resolver.live[(56,70)]
    call(m,'select-output-group',parameter='DamperZone1Output',address=70)
    call(m,'damper-form-show')
    assert m.damper.cache[0].identity==original.identity
    call(m,'edit-output-group',parameter='DamperZone1Output',outcome='accept',name='Renamed Ω')
    assert m.output.resolver.current(m.damper.cache[0]).name=='Renamed Ω'
    assert m.output.resolver.current(m.damper.cache[0]).levels==original.levels
    call(m,'add-output-group',parameter='HeatStage1Output',outcome='accept',address=75,name='New user')
    assert m.output.references['HeatStage1'].address==75
    assert [r['position'] for r in m.output.operations]==[1,3,4]


def test_installed_boolean_dispatch_observes_intermediate_mask():
    m=model(changes={'InstalledZones':0})
    # Resolve the current mask without a setter; this is the same owned getter.
    m.get_zone_mask('cbus')
    call(m,'damper-installed-zones',value=6)
    updates=[r for r in m._trace if r['method']=='TZones.GetZones' and r.get('role')=='cbus']
    assert updates
    # Source Unit->Templates refresh resets/reincludes all five checked bits.
    # The outer five-Boolean setter resumes; each later false bit is restored
    # by the same live callback. A direct whole-mask final6 oracle is wrong.
    assert m.values['InstalledZones']==31
    assert m.damper.installed_zones==31
    assert len(m.damper.operations)==1
    assert m.damper.operations[0]['owned_subscriber_dispatch']


def test_program_disable_updates_live_flag_and_source_unused_references():
    m=model()
    m.set_program_enabled('evap',False)
    assert m.values['RemoteScheduleEnable']==1
    m.set_program_enabled('non_evap',False)
    assert m.values['RemoteScheduleEnable']==0
    assert [m.remote_references[r].address for r in ('schedule_on','schedule_off','schedule_override')]==[255]*3
    saved=prepare_quick_zone_save(m,m.issue_save())
    assert [saved[k] for k in ('RemoteScheduleEnable','RemoteScheduleOnGroup','RemoteScheduleOffGroup','RemoteScheduleOverrideGroup')]==[0,32,33,34]


def test_save_result_refuses_clone_mutation_and_stale_live_history():
    m=model()
    result=m.issue_save()
    assert prepare_quick_zone_save(m,result)['ControlledZones']==30
    with pytest.raises(ThermostatTemplateError,match='original'):
        prepare_quick_zone_save(m,replace(result))
    object.__setattr__(result,'retained_master',False)
    with pytest.raises(ThermostatTemplateError,match='original'):
        prepare_quick_zone_save(m,result)
    result=m.issue_save()
    call(m,'quick-zone-click',zone=2,checked=False)
    with pytest.raises(ThermostatTemplateError,match='original'):
        prepare_quick_zone_save(m,result)


@pytest.mark.parametrize('row',[{'op':False},{'op':[]},{'op':'select-plant-type','value':True},
    {'op':'select-plant-type','value':12},{'op':'dispatch-plant-type-change','posted_by':0},
    {'op':'quick-zone-click','zone':0,'checked':1},{'op':'quick-zone-click','zone':1,'checked':False,'confirm_unswitched':True}])
def test_closed_typed_grammar(row):
    with pytest.raises(ThermostatTemplateError):
        normalize_quick_zone_operation(row)


@pytest.mark.parametrize('changes',[{'GuardEnable':1},{'MinimumSetTemperature':20},
    {'PlantMinimumOnTime':9},{'PlantCycleTime':3}])
def test_unsettled_native_control_profiles_refuse_before_history(changes):
    with pytest.raises(ThermostatTemplateError,match='Settled'):
        model(changes=changes)


@pytest.mark.parametrize('kind,code,expected',[('PC_TSA5',250,1),('PC_TSA5',0,0),
    ('PC_TSB',2,0),('PC_TSB',3,0),('PC_TSB',7,0)])
def test_current_installation_object_code_is_saved_without_a_plant_action(kind,code,expected):
    m=model(kind,changes={'InstallationCode':code})
    assert prepare_quick_zone_save(m,m.issue_save())['InstallationCode']==expected


def test_opaque_level_metadata_is_bound_in_the_save_seal():
    m=model()
    result=m.issue_save()
    group=m.output.resolver.live[(56,70)]
    object.__setattr__(group.levels[0],'value','another opaque value')
    with pytest.raises(ThermostatTemplateError,match='original'):
        prepare_quick_zone_save(m,result)


def test_basic_master_source_init_and_family_save_tail_full_literal():
    m=model('PC_TSB',changes={'ZoneTemperatureDisplay':4,'UIAllocatedZones':2,
                            'MeasuredZones':1,'HeatingPlantType':3,'CoolingPlantType':3,
                            'VentingPlantType':0})
    assert m.values['ZoneTemperatureDisplay']==0
    saved=prepare_quick_zone_save(m,m.issue_save())
    assert {key:saved[key] for key in ('ZoneTemperatureDisplay','UIAllocatedZones','InstalledZones',
        'ControlledZones','InternalPlantZones','HeatingPlantInstalledZones','CoolingPlantInstalledZones',
        'VentingPlantInstalledZones','MeasuredZones','GuardEnable')}=={
        'ZoneTemperatureDisplay':0,'UIAllocatedZones':1,'InstalledZones':1,'ControlledZones':1,
        'InternalPlantZones':1,'HeatingPlantInstalledZones':1,'CoolingPlantInstalledZones':1,
        'VentingPlantInstalledZones':1,'MeasuredZones':1,'GuardEnable':0}


def test_basic_enable_booleans_are_not_rederived_from_quick_mutated_masks():
    m=model('PC_TSB',changes={'UIAllocatedZones':0,'MeasuredZones':0})
    call(m,'quick-zone-click',zone=2,checked=True)
    assert m.values['UIAllocatedZones'] & 4 and m.values['MeasuredZones'] & 4
    saved=prepare_quick_zone_save(m,m.issue_save())
    assert saved['UIAllocatedZones']==0 and saved['MeasuredZones']==0


@pytest.mark.parametrize('display,mask',[(0,1),(1,2),(2,4),(3,8),(4,16)])
def test_basic_slave_operation_zone_reads_retained_live_enum(display,mask):
    m=model('PC_TSB',changes={'ControlledZones':0,'ZoneTemperatureDisplay':display})
    assert m.values['ZoneTemperatureDisplay']==display
    saved=prepare_quick_zone_save(m,m.issue_save())
    assert saved['UIAllocatedZones']==mask and saved['MeasuredZones']==mask
    assert saved['ControlledZones']==0 and saved['InternalPlantZones']==0
    assert saved['InstalledZones']==30


def test_whole_live_pp_include_literal_preserves_every_other_parameter():
    m=model()
    before=dict(m.values)
    call(m,'quick-zone-click',zone=2,checked=True)
    expected=before | {'UIAllocatedZones':6,'MeasuredZones':5,'ScheduleControlledZones':4}
    assert m.values==expected
    assert m.output.resolver.live[(56,70)].levels[0].value=='oops'


@pytest.mark.parametrize('kind',['PC_TSA5','PC_TSB'])
@pytest.mark.parametrize('field,value', [('ZoneTemperatureDisplay',5),('ZoneTemperatureDisplay',255),
    ('HeatingPlantType',12),('HeatingPlantType',255),('CoolingPlantType',12),('CoolingPlantType',255),
    ('HeatCoolPlantType',12),('HeatCoolPlantType',255),('VentingPlantType',12),('VentingPlantType',255),
    ('VentPlantType',3),('VentPlantType',255)])
def test_actual_enum_controller_refuses_invalid_raw_load_before_setup(kind,field,value):
    with pytest.raises(ThermostatTemplateError,match=field):
        model(kind,changes={field:value})


@pytest.mark.parametrize('row',[{'op':'unknown'},{'op':'select-output-group'},
    {'op':'select-output-group','parameter':'DamperZone1Output','address':True},
    {'op':'edit-output-group','parameter':'HeatStage1Output','outcome':'accept','name':False}])
def test_foreign_or_invalid_ordinary_rows_refuse_before_adapter(row):
    m=model(); position=m._position
    with pytest.raises(ThermostatTemplateError):
        m.process(row,position+1)
    assert m._position==position


def test_copied_owner_and_mutated_source_installation_are_not_authority():
    from copy import copy
    m=model(); duplicate=copy(m)
    with pytest.raises(ThermostatTemplateError,match='original'):
        duplicate.issue_save()
    m._installation.code=5
    with pytest.raises(ThermostatTemplateError,match='original source objects'):
        m.issue_save()


def test_original_source_snapshot_and_offered_object_mutation_refuse():
    m=model(); result=m.issue_save(); m.source['InstallationCode']=1
    with pytest.raises(ThermostatTemplateError,match='original'):
        prepare_quick_zone_save(m,result)
    m=model(); m._choices[1].value=12
    with pytest.raises(ThermostatTemplateError,match='originally issued'):
        m._select_choice(m._choices[1],1)
