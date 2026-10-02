"""Independent literal sensor bodies, usage and strict snapshot admission."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_multisensor as multi
from cbus_toolkit import project_documentation_thermostat as thermo

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / 'research/fixtures/project-documentor-sensors-literal.json'
PROOF = ROOT / 'research/fixtures/project-documentor-sensors-static.json'
CASES = json.loads(VECTOR.read_text())['cases']


def unit(case, **changes):
    pp = deepcopy(case['parameters'])
    pp.update(changes)
    return doc.Unit(case['address'], case['id'], case['unit_type'], '', '', case['firmware'], '', {
        name: value if isinstance(value, str) else ' '.join(map(str, value))
        for name, value in pp.items() if value is not None}, {})


def network():
    raw = json.loads(VECTOR.read_text())['network']
    return doc.Network(raw['address'], raw['name'], '', '', [
        doc.Application(app['address'], app['name'], '', [doc.Group(group['address'], group['name'], '', [
            doc.Level(level['address'], level['name'], level['value']) for level in group['levels']])
            for group in app['groups']]) for app in raw['applications']], [])


def case(name):
    return next(row for row in CASES if row['id'] == name)


@pytest.mark.parametrize('row', CASES, ids=lambda row: row['id'])
def test_complete_literal_bodies_and_no_input_mutation(row):
    u, net = unit(row), network()
    before = deepcopy((u, net))
    if row['family'] == 'multisensor':
        assert multi.multisensor_profile(u)[0] == row['class']
        actual = multi.neo_body_lines(net, multi.multisensor_data(u))
        renderer = multi.document_multisensor
    else:
        assert thermo.thermostat_profile(u) == row['unit_type']
        actual = thermo.thermostat_lines(net, thermo.thermostat_data(u))
        renderer = thermo.document_thermostat
    assert actual == row['body_lines']
    out = doc._Writer()
    assert renderer(out, net, u) == 'recovered'
    assert out.lines[-len(actual):] == row['body_lines']
    assert not out.unrecovered and (u, net) == before


@pytest.mark.parametrize('row', CASES, ids=lambda row: row['id'])
def test_complete_literal_dependencies_and_actions(row):
    u = unit(row)
    group_fn = multi.multisensor_group_usage if row['family'] == 'multisensor' else thermo.thermostat_group_usage
    action_fn = multi.multisensor_action_selector_usage if row['family'] == 'multisensor' else thermo.thermostat_action_selector_usage
    for probe in row['group_usage']:
        result = group_fn(u, probe['application'], probe['group'], probe['kind'],
                          **({'network': network()} if row['family']=='thermostat' else {}))
        assert result.status == 'recovered', result.missing
        assert result.html == probe['html']
    for probe in row['actions']:
        result = action_fn(u, probe['application'], probe['group'], probe['address'], probe['value'])
        assert result.status == 'recovered' and result.html == probe['html']


@pytest.mark.parametrize('raw,expected', [(0,'0s'), (1,'30s'), (2,'1m'), (3,'1m30s'), (84,'42m'), (85,'42m30s')])
def test_literal_half_minute_delay_format(raw, expected):
    assert thermo.display_fan_delay(raw) == expected


@pytest.mark.parametrize('raw,expected', [(0,'0s'), (3,'0s'), (9,'1m'), (15,'1m'), (21,'2m'), (255,'21m')])
def test_fan_five_second_round_to_even_before_display(raw, expected):
    data = thermo.thermostat_data(unit(case('pc_tsa'), HeatingPlantFanOnDelay=[raw]))
    assert thermo.display_fan_delay(data['fans']['Heating']['on']) == expected


@pytest.mark.parametrize('raw,celsius,fahrenheit', [(0,20,68), (40,30,86), (128,-12,10), (255,20,68), (2,20,69), (6,22,71)])
def test_guard_signed_byte_and_explicit_units(raw, celsius, fahrenheit):
    u = unit(case('pc_tsa'), GuardLowerTemperature=[raw])
    assert thermo.thermostat_data(u)['lower'] == celsius
    assert thermo.thermostat_data(u, units='fahrenheit')['lower'] == fahrenheit


def test_thermostat_application_is_separate_from_application_number():
    u = unit(case('pc_tsa5'), ApplicationNumber=[57])
    assert thermo.thermostat_data(u)['relays'][0] == 56
    assert thermo.thermostat_group_usage(u, 56, 1, 'output').html == 'Internal Relay 1'
    assert thermo.thermostat_group_usage(u, 57, 1, 'output').html == ''


def test_program_invalid_bool_defaults_and_basic_scheduler():
    for evap, non, expected in [(255,255,(False,True)), (2,0,(False,False)), (1,2,(True,True))]:
        data = thermo.thermostat_data(unit(case('pc_tsa'), EvapProgramEnabled=[evap], NonEvapProgramEnabled=[non]))
        assert (data['evap'],data['nonevap']) == expected
    disabled = unit(case('pc_tsb'), RemoteScheduleEnable=[0], RemoteScheduleOnGroup=None,
                    RemoteScheduleOffGroup=None, RemoteScheduleOverrideGroup=None)
    assert thermo.thermostat_group_usage(disabled,203,255,'other').html == 'Schedule On<br/>Schedule Off<br/>Schedule Override'
    assert thermo.thermostat_group_usage(disabled,203,3,'other').html == 'Remote Setback Off'


def test_unconsumed_disabled_fields_do_not_turn_into_requirements():
    u = unit(case('pc_tsb'), GuardEnable=[0], GuardLowerTemperature=None, GuardUpperTemperature=None,
             HeatingPlantFanEnable=[0], HeatingPlantFanOnDelay=None, HeatingPlantFanOffDelay=None,
             HeatingPlantFanSpeeds=None, HeatingPlantFanDefaultSpeed=None, HeatingPlantFanSpeedControlEnable=None,
             EvapProgramEnabled=None, NonEvapProgramEnabled=None, ZoneTemperatureDisplay=None,
             RemoteScheduleOnGroup=None, RemoteScheduleOffGroup=None, RemoteScheduleOverrideGroup=None)
    assert 'Guard Disabled<br/>' in thermo.thermostat_lines(network(),thermo.thermostat_data(u))


def test_virtual_plant_hydronic_vs_fan_coil():
    row = case('pc_tsa')
    pp = {name+'Output':[255] for name in ('CoolActivation','CoolStage1','CoolStage2','CoolStage3','CoolFanLow','CoolFanMedium','CoolFanHigh','HeatFanLow','HeatFanMedium','HeatFanHigh')}
    assert thermo.thermostat_data(unit(row,InternalPlantType=[8],**pp))['plant'] == 8
    assert thermo.thermostat_data(unit(row,InternalPlantType=[8],**(pp | {'CoolStage1Output':[1]})))['plant'] == 11


def test_current_and_foreign_master_use_explicit_network_number_only():
    net = network()
    master = unit(case('pc_tsa'))
    slave = unit(case('pc_tsb'),ControlledZones=[0],MasterAddress=[master.address])
    net.units = [master,slave]
    assert thermo.thermostat_lines(net,thermo.thermostat_data(slave))[1] == 'Master Unit: <a href="#254_unit_10">pc_tsa - PC_TSA</a><br/>'
    foreign = network()
    foreign.address,foreign.network_number = 253,17
    foreign.units = [master]
    model = doc.ProjectModel('DOCSENS',[net,foreign])
    slave.parameters['MasterNetworkAddress']='17'
    assert thermo.thermostat_lines(net,thermo.thermostat_data(slave),model=model)[1] == 'Master Unit: <a href="#253_unit_10">pc_tsa - PC_TSA</a><br/>'
    foreign.network_number=None
    with pytest.raises(ValueError,match='NetworkNumber'):
        thermo.thermostat_lines(net,thermo.thermostat_data(slave),model=model)
    foreign.network_number=17
    net.network_number=17
    with pytest.raises(ValueError,match='NetworkNumber'):
        thermo.thermostat_lines(net,thermo.thermostat_data(slave),model=model)
    slave.parameters['MasterNetworkAddress']='255'
    slave.parameters['MasterAddress']='255'
    with pytest.raises(ValueError,match='MasterAddress'):
        thermo.thermostat_lines(net,thermo.thermostat_data(slave),model=model)


@pytest.mark.parametrize('field,value', [('InstalledZones',None),('GuardLowerTemperature',[]),('HeatingPlantFanOnDelay',[256]),
                                      ('FanOperationMode',[3]),('InternalPlantType',[12]),('ZoneTemperatureDisplay',[5])])
def test_thermostat_body_refuses_missing_consumed_data_atomically(field,value):
    out=doc._Writer()
    assert thermo.document_thermostat(out,network(),unit(case('pc_tsa'),**{field:value})) == 'partial'
    assert out.unrecovered and not any(line.startswith('Master/Slave:') for line in out.lines)


@pytest.mark.parametrize('name', ['JoinPrimaryApplication','DualJoinPrimaryApplication','JoinSecondaryApplication','DualJoinSecondaryApplication'])
def test_multisensor_active_pro_joins_remain_explicit(name):
    u=unit(case('senpilla'),**{name:[1]})
    out=doc._Writer()
    assert multi.document_multisensor(out,network(),u) == 'partial'
    assert multi.multisensor_group_usage(u,56,1,'input').status == 'unrecovered'


@pytest.mark.parametrize('name',multi.OLD_JOIN_PARAMETERS)
def test_multisensor_active_old_joins_remain_explicit(name):
    u=unit(case('senpill-old'),**{name:[1]})
    with pytest.raises(ValueError,match='join'):
        multi.multisensor_data(u)


def test_maintenance_order_and_inactive_block_unused():
    u=unit(case('senpilla'),JPCommand=[0]*8,SRCommand=[0]*8,LPCommand=[0]*8,LRCommand=[0]*8,
           SceneKeySelector=[0]*8)
    assert multi.multisensor_group_usage(u,56,1,'input').html=='Light Level Maintenance<br/>Scene 1'
    u.parameters['PECFunctionActive']='0'
    assert multi.multisensor_group_usage(u,56,1,'input').html=='Block (Unused)<br/>Scene 1'


def test_surface_target_clears_margin_and_threshold_direction():
    u=unit(case('senpilla'),LightLevelMarginGroup=None)
    assert multi.multisensor_group_usage(u,56,255,'other').html=='Light Level Margin Group<br/>Bank Switch High Threshold Group'
    u.parameters['BankSwitchThresholdBehaviour']='0'
    assert multi.multisensor_group_usage(u,56,1,'other').html.endswith('Light Level Target Group<br/>Bank Switch High Threshold Group')
    u.parameters['LightLevelTargetGroup']='255'
    assert multi.multisensor_group_usage(u,56,1,'other').status=='unrecovered'
    u.parameters['LightLevelMarginGroup']='1'
    assert multi.multisensor_group_usage(u,56,1,'other').html.endswith('Light Level Margin Group<br/>Bank Switch High Threshold Group')


def test_broadcast_dependency_ignores_enable_and_uses_block_application():
    u=unit(case('senpilla'),BroadcastActive=[0])
    assert multi.multisensor_group_usage(u,57,5,'other').html=='Light Level Broadcast Group'
    assert multi.multisensor_group_usage(u,56,5,'other').html==''


def test_macro_subsets_application255_and_trigger_differences():
    assert multi.multisensor_macro((7,0,0,0),255,64,128)==(26,'<Custom>')
    assert multi.multisensor_macro((13,15,7,15),255,64,128,light_level=True)==(34,'Sunset')
    assert multi.multisensor_macro((13,0,0,0),255,64,128,light_level=True)==(0,'On')
    assert multi.multisensor_macro((12,0,0,0),202,64,128)==(14,'Trigger 1')
    assert multi.multisensor_macro((12,0,0,0),202,64,128,light_level=True)==(26,'<Custom>')
    assert multi.multisensor_macro((12,0,0,0),56,255,128,light_level=True)==(20,'Shutter Open')


def test_multisensor_timer_first_allocated_not_linear_key_block():
    u=unit(case('senpilla'),BlockAllocation=[3,2,4,8,16,32,64,128])
    data=multi.multisensor_data(u)
    assert data.blocks[0].timer==300 and data.blocks[1].timer==300
    u.parameters['JPCommand']='0 7 0 0 0 0 14 1'
    u.parameters['SRCommand']='0 0 0 0 0 0 2 2'
    u.parameters['LPCommand']='0 0 0 0 0 0 4 3'
    u.parameters['LRCommand']='0 0 0 0 0 0 2 4'
    u.parameters['BlockAllocation']='1 3 4 8 16 32 64 128'
    data=multi.multisensor_data(u)
    assert (data.blocks[0].timer,data.blocks[1].timer)==(300,0)


@pytest.mark.parametrize('row', CASES, ids=lambda row: row['id'])
def test_factory_unknown_firmware_and_missing_body_arrays_refuse(row):
    u=unit(row)
    u.firmware='missing'
    renderer=multi.document_multisensor if row['family']=='multisensor' else thermo.document_thermostat
    assert renderer(doc._Writer(),network(),u)=='partial'


def test_source_proof_current_model_hashes_and_no_original_execution():
    receipt=json.loads(PROOF.read_text())
    assert receipt['original_executed'] is False and receipt['original_generated_page_comparison']=='not_obtained'
    assert all(receipt['checks'].values())
    assert len(receipt['factory'])==11
    for module in (multi,thermo):
        assert receipt['model_sha256'][Path(module.__file__).name]==hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()


def test_thermostat_input_auto_generated_or_missing_groups_refuse_instead_of_allocating():
    u=unit(case('pc_tsa'))
    assert thermo.thermostat_group_usage(u,56,1,'input').status=='unrecovered'
    net=network()
    net.application(56).group(1).name='[CG01] generated pump'
    assert thermo.thermostat_group_usage(u,56,1,'input',network=net).status=='unrecovered'
    net.application(56).groups=[]
    assert thermo.thermostat_group_usage(u,56,1,'input',network=net).status=='unrecovered'
    # A different thermostat's prefix is an ordinary pre-existing group here.
    net=network()
    net.application(56).group(1).name='[CG02] other zone'
    assert thermo.thermostat_group_usage(u,56,1,'input',network=net).status=='recovered'


@pytest.mark.parametrize('light_level,application', [(False,56),(False,202),(False,255),(True,56),(True,202),(True,255)])
def test_every_micro_nibble_vector_against_independent_source_registrations(light_level,application):
    import itertools
    receipt=json.loads(PROOF.read_text())
    ordered={tuple(row['commands']):row['type'] for row in receipt['macro_first_match']}
    subset=receipt['macro_subsets']['SENLLA' if light_level else 'SENPILL']
    allowed=subset.get(str(application),subset['0'])
    labels={int(key):value for key,value in receipt['macro_labels'].items()}
    for commands in itertools.product(range(16),repeat=4):
        expected=ordered.get(commands,26)
        expected={27:26,31:29,32:30}.get(expected,expected)
        if application!=202:
            if expected==14:expected=20  # first stored level255
            elif expected==15:expected=22  # second stored level5
        if expected not in allowed:expected=26
        assert multi.multisensor_macro(commands,application,255,5,light_level=light_level)==(expected,labels[expected]),commands
