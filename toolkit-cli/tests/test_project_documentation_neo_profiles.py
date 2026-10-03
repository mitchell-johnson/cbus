"""All exact Neo report classes consume independently literal rows and graphs."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit.project_documentation_native import build_native_model
from cbus_toolkit.project_documentation_neo import neo_data, neo_profile, document_neo, neo_body_lines
from cbus_toolkit.project_documentation_neo_profiles import NEO_CLASS_PROFILES, NEO_TYPES, profile_facts
from cbus_toolkit.project_documentation_neo_usage import neo_action_selector_usage, neo_group_usage

ROOT=Path(__file__).resolve().parents[1]
VECTOR=ROOT/'research/fixtures/project-documentor-neo-profiles-literal.json'
RECEIPT=ROOT/'research/fixtures/project-documentor-neo-profiles-static.json'
DATA=json.loads(VECTOR.read_text())
PROFILES=DATA['profiles']


def fixture():
    model=build_native_model(DATA['native_xml'].encode())
    network=model.by_address[254]
    return model,network,{unit.address:unit for unit in network.units}


def changed(unit, **updates):
    pp=dict(unit.parameters)
    for name,values in updates.items():
        if values is None:pp.pop(name,None)
        else:pp[name]=' '.join(map(str,values))
    return replace(unit,parameters=pp)


@pytest.mark.parametrize('row',PROFILES,ids=lambda r:r['unit_type']+'-'+r['firmware'])
def test_complete_snapshot_exact_literal_body_and_graph_preservation(row):
    model,network,units=fixture();before=deepcopy(model)
    unit=units[row['address']];out=doc._Writer()
    assert document_neo(out,network,unit)=='recovered'
    start=out.lines.index('<table border="1">')
    assert out.lines[start:]==DATA['body_lines'][str(row['address'])]
    assert not out.unrecovered and model==before
    assert len(neo_data(unit).keys)==len(neo_data(unit).blocks)==8


@pytest.mark.parametrize('row',PROFILES,ids=lambda r:r['unit_type']+'-'+r['firmware'])
def test_exact_class_partition_facts_and_ordered_consumers(row):
    _,_,units=fixture();unit=units[row['address']]
    facts=profile_facts(unit);profile=neo_profile(unit)
    assert (facts.class_name,facts.firmware_min,facts.firmware_max)==(row['class_name'],row['firmware_min'],row['firmware_max'])
    assert (profile.physical_key_count,profile.is_pro,profile.infrared_virtual_keys,profile.bistable)==(row['physical_keys'],row['pro'],row['infrared'],row['bistable'])
    expected=DATA['group_usage'][str(row['address'])]
    for app,group,kind,key in [(56,1,'input','primary_input'),(202 if row['pro'] else 56,2,'input','second_input'),
                              (56,9,'other','primary_other'),(202,9,'other','trigger_other'),
                              (203,9,'other','enable_other'),(56,10,'other','brightness_other')]:
        result=neo_group_usage(unit,app,group,kind)
        assert (result.status,result.html)==('recovered',expected[key])
    assert neo_group_usage(unit,56,1,'output').html==''


def test_complete_profile_census_is_the_exact_report_factory_surface():
    assert len(NEO_CLASS_PROFILES)==59 and len(NEO_TYPES)==43
    assert {r[0] for r in doc.REGISTRATIONS if r[1] in {'NeoInput','NeoProInput'}}==NEO_TYPES
    assert len({(r.unit_type,r.class_name,r.firmware_min,r.firmware_max) for r in NEO_CLASS_PROFILES})==59


@pytest.mark.parametrize('row',PROFILES,ids=lambda r:r['unit_type']+'-'+r['firmware'])
def test_source_factory_boundary_versions_and_no_invented_partition(row):
    _,_,units=fixture();unit=units[row['address']]
    lo='0.0.00' if row['firmware_min']=='0' else row['firmware_min']
    hi='9.0.00' if row['firmware_max']=='9' else row['firmware_max']
    assert profile_facts(replace(unit,firmware=lo)).class_name==row['class_name']
    assert profile_facts(replace(unit,firmware=hi)).class_name==row['class_name']
    with pytest.raises(ValueError,match='class/firmware'):profile_facts(replace(unit,firmware='9.0.01'))


@pytest.mark.parametrize('firmware',['','unknown','1.x.00','2.5','2.5.0','2.5.000','3.0.00','-1.5.00'])
def test_historical_strict_firmware_identity_and_keym8_bounds_remain(firmware):
    _,_,units=fixture();unit=next(u for u in units.values() if u.unit_type=='KEYM8' and u.firmware=='2.5.00')
    with pytest.raises(ValueError,match='class/firmware'):profile_facts(replace(unit,firmware=firmware))


@pytest.mark.parametrize('typ,default,ir',[('KEYE1',1,False),('KEYE2',3,False),('KEYE3',7,False),('KEYE4',15,False),
                                         ('KEYEIR1',1,True),('KEYEIR2',3,True),('KEYEIR3',7,True),('KEYEIR4',15,True)])
def test_keyex_every_byte_mask_uses_exact_type_default_and_four_physical_positions(typ,default,ir):
    _,network,units=fixture();unit=next(u for u in units.values() if u.unit_type==typ)
    for value in range(256):
        data=neo_data(changed(unit,KeyMask=[value]))
        connected=value&15 if value&1 else default
        expected=['' if connected&(1<<i) else 'Unconnected Key ' for i in range(4)]
        expected+=['IR Key ' if ir else 'Virtual Key ']*4
        assert [key.prefix for key in data.keys]==expected
    assert neo_body_lines(network,neo_data(changed(unit,KeyMask=[2])))[8].find('Bistable')==-1


@pytest.mark.parametrize('typ',['BCI4A','BCN2B','BCN4B','KEYV1SP','KEYV2SP','KEYV3SP'])
def test_coupler_bistable_is_consumed_but_powerup_state_is_not_reported(typ):
    _,network,units=fixture();unit=next(u for u in units.values() if u.unit_type==typ)
    original=neo_body_lines(network,neo_data(unit))
    assert '<th>Bistable</th>' in original[8]
    assert neo_body_lines(network,neo_data(changed(unit,GroupAssertOnPowerup=[255])))==original
    data=neo_data(changed(unit,BistableSwitchBlock=[255]));lines=neo_body_lines(network,data)
    for i in range(8):assert ('<td>Yes</td>' if i<data.physical_key_count else '<td>&nbsp;</td>') in lines[9+i]
    # Source couplers inherit Neo's Other method, despite their Pro blocks.
    minimal=changed(unit,KeyDisableGroup=None,CorridorMasterGroup=None)
    assert neo_group_usage(minimal,202,9,'other').html==''
    assert neo_group_usage(minimal,203,9,'other').html==''
    with pytest.raises(ValueError,match='BistableSwitchBlock'):neo_data(changed(unit,BistableSwitchBlock=None))


@pytest.mark.parametrize('typ',['KEYA1','KEYBIR6','KEYDV3','BCI4A','KEYEIR4'])
def test_source_selector_address_value_gates_are_retained_on_new_profiles(typ):
    _,_,units=fixture();unit=next(u for u in units.values() if u.unit_type==typ and u.firmware=='2.5.00')
    unit=changed(unit,SecondApplicationBlocks=[1],GroupAddress=[9,2,255,255,255,255,255,255,10],
                 BlockAllocation=[1,0,0,0,0,0,0,0],LightLevelStore1=[66,0,0,0,0,0,0,0],
                 LightLevelStore2=[67,0,0,0,0,0,0,0],JPCommand=[12,0,0,0,0,0,0,0],SRCommand=[6,0,0,0,0,0,0,0])
    assert neo_action_selector_usage(unit,202,9,66,67).html==DATA['action_usage']['secondary_recall_address66_value67']
    assert neo_action_selector_usage(unit,202,9,99,67).html==DATA['action_usage']['address99_value67']


@pytest.mark.parametrize('typ',['KEYA1','KEYBIR6','KEYDV3','BCI4A','KEYEIR4'])
def test_missing_consumed_fields_active_joins_and_scene_modify_still_refuse(typ):
    _,network,units=fixture();unit=next(u for u in units.values() if u.unit_type==typ and u.firmware=='2.5.00')
    for updates in [{'LightLevelStore1':None},{'JoinPrimaryApplication':[1]},
                    {'SceneKeySelector':[1,0,0,0,0,0,0,0]}, {'SceneTable':[0]*80}]:
        out=doc._Writer();assert document_neo(out,network,changed(unit,**updates))=='partial'
        assert len(out.unrecovered)==1
        assert '<table border="1">' not in out.lines


def test_join_capability_follows_effective_class_and_firmware():
    _,_,units=fixture()
    pro=next(u for u in units.values() if u.unit_type=='KEYA1' and u.firmware=='2.5.00')
    assert neo_profile(replace(pro,firmware='1.5.03')).join_supported is False
    assert neo_profile(replace(pro,firmware='1.6.00')).join_supported is True
    for typ in ['KEYA8','KEYBIR6','KEYE2','KEYEIR2','BCI4A','BCN2B','KEYV1SP']:
        unit=next(u for u in units.values() if u.unit_type==typ and u.firmware=='2.5.00')
        assert neo_profile(unit).join_supported is False


def test_static_annex_is_bounded_and_contains_complete_effective_slots():
    data=json.loads(RECEIPT.read_text())
    assert (data['types'],data['factory_partitions'])==(43,59)
    assert len(data['profiles'])==59 and all(data['checks'].values())
    assert data['original_executed'] is False
    assert not any('instructions' in row for row in data['methods'].values())


@pytest.mark.skipif(not os.environ.get('CBUS_TOOLKIT_EXE'),reason='Requires pinned Toolkit EXE/MAP for read-only static proof')
def test_current_static_annex_reproduces_from_pinned_inputs():
    sys.path.insert(0,str(ROOT/'research'))
    from project_documentor_neo_profiles_static import inspect
    exe=Path(os.environ['CBUS_TOOLKIT_EXE'])
    assert inspect(exe,Path(os.environ.get('CBUS_TOOLKIT_MAP',exe.with_suffix('.map'))))==json.loads(RECEIPT.read_text())


@pytest.mark.parametrize('row',DATA['state_cases'],ids=lambda r:r['name'])
def test_additional_stored_state_literals_preserve_complete_graph(row):
    model,network,units=fixture();before=deepcopy(model)
    unit=units[row['address']];out=doc._Writer()
    assert document_neo(out,network,unit)=='recovered'
    assert out.lines[out.lines.index('<table border="1">'):]==DATA['body_lines'][str(row['address'])]
    data=neo_data(unit)
    if 'decoded_scenes' in row:
        assert [[{'group':entry.group,'level':entry.level} for entry in scene] for scene in data.scenes]==row['decoded_scenes']
        assert neo_group_usage(unit,56,1,'input').html==row['group_usage']['primary_scene']
        assert neo_group_usage(unit,56,2,'input').html==row['group_usage']['second_scene']
        assert neo_action_selector_usage(unit,202,9,66,99).html==row['action_usage']['trigger_address66']
        assert neo_action_selector_usage(unit,202,9,99,66).html==row['action_usage']['trigger_address99']
    if 'loaded_timers' in row:assert [block.timer for block in data.blocks]==row['loaded_timers']
    assert model==before and not out.unrecovered
