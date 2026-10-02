"""Independent L1 literals, firmware partitions and consumed-field refusals."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit.project_documentation_native import build_native_model
from cbus_toolkit.project_documentation_bytecraft import bytecraft_body_lines, document_bytecraft
from cbus_toolkit.project_documentation_bytecraft_loader import bytecraft_logic, bytecraft_profile, decode_bytecraft_scenes
from cbus_toolkit.project_documentation_bytecraft_usage import bytecraft_action_selector_usage, bytecraft_group_usage

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / 'research/fixtures/project-documentor-bytecraft-l1.json'


def fixture():
    vector = json.loads(VECTOR.read_text())
    model = build_native_model(vector['native_xml'].encode())
    network = model.by_address[254]
    return vector, model, network, network.units[0]


def changed(unit, **values):
    pp = dict(unit.parameters)
    for name, value in values.items():
        if value is None:
            pp.pop(name, None)
        else:
            pp[name] = ' '.join(map(str, value))
    return replace(unit, parameters=pp)


def test_complete_native_l1_literal_body_and_entire_graph_preservation():
    vector, model, network, unit = fixture()
    before = deepcopy(model)
    assert bytecraft_body_lines(network, unit) == vector['body_lines']
    out = doc._Writer()
    assert document_bytecraft(out, network, unit) == 'recovered'
    assert out.lines == ['Unit Address: 1<br />', 'Tagname: L1 dimmer<br />',
        'Part name: DIMPR12<br />', 'Application: <a href="#254_56">Lighting</a><br />',
        'Serial Number: 000000010001<br />', 'Firmware Version: 1.9.03<br />',
        'Notes: <br />', '<br />'] + vector['body_lines']
    assert model == before and not out.unrecovered


def test_literal_ordered_usage_inherited_scenes_and_address_identity():
    vector, _, _, unit = fixture()
    for app, group, kind, key in [(56,8,'output','output_56_8'),(56,9,'output','output_56_9'),
        (56,255,'output','output_56_255'),(56,8,'input','input_56_8'),
        (56,8,'other','other_56_8'),(203,255,'other','other_203_255')]:
        result = bytecraft_group_usage(unit, app, group, kind)
        assert (result.status, result.html) == ('recovered', vector['group_usage'][key])
    for address in (11,99):
        assert bytecraft_action_selector_usage(unit,202,7,address,11).html == vector['selector_usage'][str(address)]
    assert len(decode_bytecraft_scenes(unit)) == 33


@pytest.mark.parametrize('firmware,profile', [('0','old'),('1.9.02','old'),('1.9.03','l1'),('9','l1')])
def test_exact_native_old_l1_firmware_partition(firmware, profile):
    _, _, _, unit = fixture()
    unit = replace(unit, firmware=firmware)
    assert bytecraft_profile(unit) == profile
    assert len(decode_bytecraft_scenes(unit)) == 33
    assert bytecraft_logic(unit) == (None if profile == 'old' else (9,(1,129,128,1)+(0,)*8))


@pytest.mark.parametrize('firmware', ['',None,'1.9.x','9.0.1','10','2147483648'])
def test_unknown_or_malformed_firmware_refuses(firmware):
    _, _, _, unit = fixture()
    with pytest.raises(ValueError, match='DIMPR12 class/agent'):
        bytecraft_profile(replace(unit, firmware=firmware))


def test_only_bit0_enables_and_bit7_selects_min_logic_only_unused_channel_is_skipped():
    _, _, network, unit = fixture()
    for value in range(256):
        candidate = changed(unit, LogicAttributes=[value]*12)
        rows = bytecraft_body_lines(network,candidate)
        channel1 = next(row for row in rows if row.startswith('</tr><tr><td>1</td>'))
        if value & 1:
            assert ', <a href="#254_56_9">Logic<&></a></td><td>' + ('Min' if value & 128 else 'Max') + '</td>' in channel1
        else:
            assert '</a></td><td>&nbsp;</td>' in channel1
        assert not any(row.startswith('</tr><tr><td>4</td>') for row in rows)
        expected = 'Channel 2<br/>Logic Group' + ('' if value & 1 else ' (Unused)')
        assert bytecraft_group_usage(candidate,56,9,'output').html == expected


def test_unused_logic_address_remains_identity_and_follows_every_channel():
    _, _, network, unit = fixture()
    candidate = changed(unit, LogicGroupAddress=[255])
    result = bytecraft_group_usage(candidate,56,255,'output')
    assert result.html == '<br/>'.join([*(f'Channel {i}' for i in range(3,13)), 'Logic Group'])
    rows = bytecraft_body_lines(network,candidate)
    assert '<a href="#254_56_8">Load<&></a>, &#60;Unused&#62;</td><td>Max</td>' in rows[6]
    assert bytecraft_group_usage(candidate,57,255,'output').html == ''


@pytest.mark.parametrize('field,value', [('LogicGroupAddress',None),('LogicGroupAddress',[]),
    ('LogicAttributes',None),('LogicAttributes',[1]*11),('LogicAttributes',[256]*12)])
def test_missing_consumed_l1_logic_fails_before_body_or_output_tables(field,value):
    _, _, network, unit = fixture()
    candidate = changed(unit, **{field:value})
    out = doc._Writer()
    assert document_bytecraft(out,network,candidate) == 'partial'
    assert field in out.unrecovered[0]['item'] and not any(row.startswith('<table') for row in out.lines)
    result = bytecraft_group_usage(candidate,56,8,'output')
    assert result.status == 'unrecovered' and result.html == '' and field in result.missing[0]
    # Inherited scene and action consumers do not read the L1 logic list.
    assert bytecraft_action_selector_usage(candidate,202,7,11,99).html == '<li />Trigger Scene 1'
    assert bytecraft_group_usage(candidate,56,8,'input').html == 'Scene 2'


def test_l1_static_receipt_binds_unchanged_parent_body_and_new_loader():
    receipt = json.loads((ROOT/'research/fixtures/project-documentor-bytecraft-l1-static.json').read_text())
    assert all(receipt['checks'].values()) and receipt['original_instructions_executed'] == 0
    assert receipt['original_generated_page_comparison'] == 'not_obtained'
    assert receipt['unit_factory_profiles'] == [['DIMPR12','CIS_TDIMPR12..TDIMPR12','0','1.9.02'],
                                               ['DIMPR12','CIS_TDIMPR12L1..TDIMPR12L1','1.9.03','9']]


def test_l1_static_receipt_reproduces_when_explicit_inputs_exist():
    executable = os.environ.get('CBUS_TOOLKIT_EXE')
    mapping = os.environ.get('CBUS_TOOLKIT_MAP')
    if not executable or not mapping:
        pytest.skip('explicit private Toolkit EXE/MAP static inputs not configured')
    sys.path.insert(0,str(ROOT/'research'))
    from project_documentor_bytecraft_l1_static import inspect
    assert inspect(Path(executable),Path(mapping)) == json.loads((ROOT/'research/fixtures/project-documentor-bytecraft-l1-static.json').read_text())
