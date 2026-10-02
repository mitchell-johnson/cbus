"""Independent current ST7 report literals and exact selected-consumer bounds."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit.project_documentation_light_level import (
    document_light_level, light_level_data, light_level_lines, light_level_group_usage, light_level_profile,
)
from cbus_toolkit.project_documentation_native import build_native_model
from cbus_toolkit.project_documentation_st7_light_level import st7_light_level_timer
from cbus_toolkit.project_documentation_usage import action_selector_usage, group_usage

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / 'research/fixtures/project-documentor-st7-light-level.json'
STATIC = ROOT / 'research/fixtures/project-documentor-st7-light-level-static.json'
DATA = json.loads(VECTOR.read_text())


def fixture():
    model = build_native_model(DATA['native_xml'].encode())
    return model, model.by_address[254]


def changed(unit, **values):
    pp = dict(unit.parameters)
    for name, value in values.items():
        if value is None:
            pp.pop(name, None)
        else:
            pp[name] = value if isinstance(value, str) else ' '.join(map(str, value))
    return replace(unit, parameters=pp)


@pytest.mark.parametrize('case', DATA['cases'], ids=lambda case: case['id'])
def test_complete_native_literal_bodies_and_whole_model_preservation(case):
    model, network = fixture()
    before = deepcopy(model)
    unit = next(unit for unit in network.units if unit.address == case['unit']['address'])
    assert light_level_profile(unit) == 'st7'
    assert light_level_lines(network, light_level_data(unit)) == case['body_lines']
    out = doc._Writer()
    assert document_light_level(out, network, unit) == 'recovered'
    assert out.lines[-7:] == case['body_lines'] and not out.unrecovered
    assert model == before


@pytest.mark.parametrize('selected', range(8))
@pytest.mark.parametrize('stored,expected4', [(0,10),(1,10),(2,10),(3,10),(4,10),(5,10),
    (6,10),(7,10),(8,10),(9,10),(10,10),(255,255),(256,256),(300,300),(65535,65535)])
def test_every_broadcast_block_timer_minimum_and_full_word_boundaries(selected, stored, expected4):
    _, network = fixture()
    high, low = [0]*8, [0]*8
    high[selected], low[selected] = divmod(stored, 256)
    unit = changed(network.units[0], TimerHighByte=high, TimerLowByte=low, BroadcastBlock=[selected])
    assert st7_light_level_timer(unit, selected) == (expected4 if selected == 4 else stored)
    assert light_level_data(unit)['timer'] == (expected4 if selected == 4 else stored)


def test_ordered_coincident_roles_and_unassigned_object_identity():
    _, network = fixture()
    for address, application, group in [(9,56,9),(10,255,255)]:
        unit = next(unit for unit in network.units if unit.address == address)
        for kind, expected in [('input','Level Group<br/>On/Off Group'),
                               ('other','Light Level Broadcast Group<br/>Enable Group'),('output','')]:
            actual = group_usage(unit, application, group, kind)
            assert (actual.status, actual.html, actual.missing) == ('recovered', expected, ())
            assert light_level_group_usage(unit, application, group, kind) == actual
        assert group_usage(unit, 57, group, 'input').html == ''
        assert group_usage(unit, 202, 7, 'other').html == ''


def test_secondary_application_identity_and_roles_ignore_active_flags():
    _, network = fixture()
    unit = network.units[0]
    for active in (None, '', '0', '1', '255', 'malformed but unconsumed'):
        candidate = changed(unit, PECFunctionActive=active, BroadcastActive=active)
        for app, group, kind, expected in [(57,2,'input','Level Group'),(56,3,'input','On/Off Group'),
            (56,1,'other','Light Level Broadcast Group'),(56,9,'other','Enable Group'),
            (56,2,'input',''),(57,3,'input',''),(57,1,'other','')]:
            result = group_usage(candidate, app, group, kind)
            assert (result.status, result.html, result.missing) == ('recovered', expected, ())


UNCONSUMED = ('JPCommand','SRCommand','LPCommand','LRCommand','PIRLightMovement','PIRDarkMovement','PIRDark',
 'BlockAllocation','SceneKeySelector','IndicatorBlockAssignment','ControlAppGroupAddress',
 'SceneTable','SceneTablePointer','AreaGroupAddress','PIREnablerGroup','CorridorLinkEnablerGroup',
 'JoinPrimaryApplication','DualJoinPrimaryApplication','JoinSecondaryApplication','DualJoinSecondaryApplication')


@pytest.mark.parametrize('field', UNCONSUMED)
def test_hidden_key_templates_occupancy_and_packed_scenes_are_unconsumed(field):
    _, network = fixture()
    unit = network.units[4]
    original = light_level_lines(network, light_level_data(unit))
    # These are ignored selected-consumer fields, not an admission of their
    # malformed values by a complete Neo scene editor or physical loader.
    for value in (None, '', 'malformed but unconsumed'):
        candidate = changed(unit, **{field:value})
        assert light_level_lines(network, light_level_data(candidate)) == original
        assert group_usage(candidate,57,2,'input').html == 'Level Group'
        assert group_usage(candidate,56,5,'other').html == 'Light Level Broadcast Group'
        assert group_usage(candidate,56,10,'input').html == ''
        assert group_usage(candidate,56,10,'other').html == ''
        for address, value in ((75,99),(99,75)):
            usage = action_selector_usage(candidate,'UnitType',202,7,address,value)
            assert (usage.html, usage.status, usage.missing) == ('','recovered',())


@pytest.mark.parametrize('field', ['Application','GroupAddress','SecondApplicationBlocks','PECFunctionBlock',
 'BroadcastBlock','PECEnablerGroup','TimerHighByte','TimerLowByte','PECTargetLux','PECMarginLux'])
def test_missing_consumed_body_fields_refuse_without_partial_body(field):
    _, network = fixture()
    unit = changed(network.units[4], **{field:None})
    out = doc._Writer()
    assert document_light_level(out,network,unit) == 'partial'
    assert field in out.unrecovered[0]['item']
    assert not any(line.startswith('Light Level Group:') for line in out.lines)


@pytest.mark.parametrize('field,kind', [('PECFunctionBlock','input'),('BroadcastBlock','other')])
@pytest.mark.parametrize('value', [-1,8,255,256])
def test_invalid_consumed_block_identity_refuses(field, kind, value):
    _, network = fixture()
    unit = changed(network.units[0], **{field:[value]})
    with pytest.raises(ValueError):
        light_level_data(unit)
    result = group_usage(unit,56,1,kind)
    assert result.status == 'unrecovered' and not result.html and result.missing


def test_group_consumers_do_not_require_timer_target_or_other_role_fields():
    _, network = fixture()
    unit = changed(network.units[0], TimerHighByte=None,TimerLowByte=None,PECTargetLux=None,PECMarginLux=None)
    assert group_usage(changed(unit,BroadcastBlock=None,PECEnablerGroup=None),57,2,'input').html == 'Level Group'
    assert group_usage(changed(unit,PECFunctionBlock=None),56,1,'other').html == 'Light Level Broadcast Group'
    assert group_usage(changed(unit,Application=None),56,1,'output').html == ''


@pytest.mark.parametrize('firmware,profile', [('1.00','old'),('2.0.00','old'),('2.0.01','st7'),('9','st7')])
def test_exact_saved_report_firmware_partition(firmware, profile):
    _, network = fixture()
    assert light_level_profile(replace(network.units[0],firmware=firmware)) == profile


def test_current_annex_binds_effective_vmt_and_fresh_model_source_without_native_acceptance():
    receipt = json.loads(STATIC.read_text())
    assert all(receipt['checks'].values()) and len(receipt['checks']) == 38
    assert len(receipt['methods']) == 29
    assert receipt['original_executed'] is False
    assert receipt['original_generated_page_comparison'] == 'not_obtained'
    assert receipt['fresh_model'] == {'physical_keys':0,'virtual_key_limit':-1,'effective_input_keys':0,
        'blocks':8,'timer_minima':[0,0,0,0,10,0,0,0],'scene_collection_loaded':True,
        'scene_dependency_consumer':False,'scene_action_consumer':False}
    assert all(set(row) == {'start','end','sha256'} for row in receipt['methods'].values())


def test_static_annex_reproduces_when_explicit_private_inputs_exist():
    exe, mapping = os.environ.get('CBUS_TOOLKIT_EXE'), os.environ.get('CBUS_TOOLKIT_MAP')
    if not exe or not mapping:
        pytest.skip('explicit private Toolkit EXE/MAP static inputs not configured')
    sys.path.insert(0,str(ROOT/'research'))
    from project_documentor_st7_light_level_static import inspect
    assert inspect(Path(exe),Path(mapping)) == json.loads(STATIC.read_text())
