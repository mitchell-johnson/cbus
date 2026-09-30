import json
from dataclasses import replace
from pathlib import Path

from cbus_toolkit.device_scenes import SceneEntry, _encode
from cbus_toolkit.project_documentation import Unit
from cbus_toolkit.project_documentation_neo import NeoBlock, NeoData, NeoKey, neo_data
from cbus_toolkit.project_documentation_neo_usage import (
    action_usage_from_data, input_usage_from_data, neo_action_selector_usage, neo_group_usage,
)

FIXTURES = Path(__file__).parents[1] / 'research' / 'fixtures'


def unit(typ='KEYM8', firmware='2.0.00', **changes):
    table, pointers = _encode(((),) * 8)
    pp = {'Application': [202, 56], 'GroupAddress': [8, 8, 9, 10, 11, 12, 13, 14, 8],
          'DebounceTime': [1], 'LongPressTime': [2], 'RampRate': [0, 1],
          'BlockAllocation': [3, 1, 4, 8, 16, 32, 64, 128],
          'LightLevelStore1': [11] * 8, 'LightLevelStore2': [22] * 8,
          'TimerHighByte': [0] * 8, 'TimerLowByte': [0] * 8, 'TimerExpiryCommand': [15] * 8,
          'JPCommand': [12, 12, 0, 0, 0, 0, 0, 0], 'SRCommand': [6, 0, 0, 0, 0, 0, 0, 0],
          'LPCommand': [0] * 8, 'LRCommand': [0] * 8, 'SecondApplicationBlocks': [0],
          'SceneKeySelector': [0] * 8, 'IndicatorBlockAssignment': [0] * 8,
          'ControlAppGroupAddress': [9], 'SceneTable': table, 'SceneTablePointer': pointers,
          'JoinPrimaryApplication': [255], 'DualJoinPrimaryApplication': [255],
          'JoinSecondaryApplication': [255], 'DualJoinSecondaryApplication': [255],
          'AreaGroupAddress': [8], 'IndicatorBrightness': [255], 'KeyDisableGroup': [8],
          'CorridorMasterGroup': [8], 'KeyMask': [1]}
    pp.update(changes)
    return Unit(1, 'Unit', typ, typ, '', firmware, '', {
        k: ' '.join(map(str, v)) if isinstance(v, (tuple, list)) else v
        for k, v in pp.items() if v is not None}, {})


def data_from_case(case):
    keys = tuple(NeoKey(sum(1 << b for b in key['blocks']), tuple(key['commands']),
                        case['application'], 26, 'Custom', key.get('trigger') is not None,
                        key.get('scene', 0), 0, key.get('trigger'), '') for key in case['keys'])
    blocks = tuple(NeoBlock(b['application'], b['group'], b['stored1'], b['stored2'], 0, b['expiry'])
                   for b in case['blocks'])
    return NeoData(tuple(case['applications']), True, len(keys), ('',) * 4, blocks, keys,
                   ((),) * 8, case['control_group'], ((255, 255), (255, 255)))


def test_action_chain_matches_executed_original_instructions():
    receipt = json.loads((FIXTURES / 'project-documentor-neo-action-original.json').read_text())
    assert len(receipt['cases']) == 15
    for case in receipt['cases']:
        result = action_usage_from_data(data_from_case(case), case['application'], case['group'],
                                        case['address'], case['value'])
        assert result.status == 'recovered'
        assert result.html == case['html'], case['name']


def test_pp_primary_secondary_and_same_application_multiplicity():
    assert neo_action_selector_usage(unit(), 202, 8, 11, 22).html == (
        'Key 1<br/>Key 1<br/>Key 1<br/>Key 1<br/>Key 2')
    secondary = unit(SecondApplicationBlocks=[3], Application=[56, 202])
    assert neo_action_selector_usage(secondary, 202, 8, 11, 22).html == (
        'Key 1<br/>Key 1<br/>Key 1<br/>Key 1<br/>Key 2')
    assert neo_action_selector_usage(secondary, 202, 8, 99, 22).html == ''
    same = unit(Application=[202, 202])
    first = neo_action_selector_usage(unit(), 202, 8, 11, 22).html
    assert neo_action_selector_usage(same, 202, 8, 11, 22).html == first + '<br/>' + first


def test_scene_micro_nibbles_are_not_recalls_and_selector_address_is_distinct():
    u = unit(GroupAddress=[255, 8, 9, 10, 11, 12, 13, 14, 8], BlockAllocation=[1, 2, 4, 8, 16, 32, 64, 128],
             SceneKeySelector=[1] + [0] * 7, JPCommand=[14] + [0] * 7,
             SRCommand=[7] + [0] * 7, LPCommand=[12] + [0] * 7, LRCommand=[6] + [0] * 7,
             IndicatorBlockAssignment=[3] + [0] * 7, ControlAppGroupAddress=[255])
    data = neo_data(u)
    assert data.keys[0].commands == (0, 0, 0, 0)
    assert neo_action_selector_usage(u, 202, 255, 198, 99).html == 'Triggers Scene 4'
    assert neo_action_selector_usage(u, 202, 255, 99, 198).html == ''


def test_input_is_block_major_then_scene_major_and_ordinary_keys_reference_scene_one():
    data = neo_data(unit())
    data = replace(data, scenes=((SceneEntry(8, 100),), (SceneEntry(8, 150),)) + ((),) * 6)
    expected = 'Key 1<br/>Key 2<br/>Key 1<br/>Scene 1<br/>Scene 2 (Unused)'
    assert input_usage_from_data(data, 202, 8).html == expected
    assert input_usage_from_data(data, 202, 8, dlt=True).html == expected.replace(' (Unused)', '')
    assert input_usage_from_data(data, 56, 8).html == ''
    assert input_usage_from_data(data, 202, 9).html == 'Block (Unused)'


def test_keye_native_count_four_ignores_connectivity_for_input_dependency():
    u = unit('KEYE1', '2.5.00', BlockAllocation=[1] * 8, JPCommand=[12] * 8, SRCommand=[0] * 8)
    result = neo_group_usage(u, 202, 8, 'input')
    assert result.status == 'recovered'
    assert result.html == 'Key 1<br/>Key 2<br/>Key 3<br/>Key 4<br/>Block (Unused)'


def test_neo_other_uses_ninth_group_and_primary_corridor_even_if_disabled():
    result = neo_group_usage(unit(), 202, 8, 'other')
    assert result.html == 'Area Group<br/>Indicator Brightness Group<br/>Corridor Link Group'
    assert neo_group_usage(unit(IndicatorBrightness=' '), 202, 8, 'other').html == result.html
    assert neo_group_usage(unit(IndicatorBrightness=''), 202, 8, 'other').html == 'Area Group<br/>Corridor Link Group'
    assert neo_group_usage(unit(), 203, 8, 'other').html == 'Key Disable Group'
    assert neo_group_usage(unit(), 202, 9, 'other').html == 'Control App Group'
    old = unit(firmware='1.4.00', Application=[202])
    assert neo_group_usage(old, 202, 8, 'other').html == 'Area Group<br/>Indicator Brightness Group'
    assert neo_group_usage(old, 203, 8, 'other').html == ''


def test_missing_data_is_reported_without_erasing_known_other_uses():
    u = unit(AreaGroupAddress=None, KeyDisableGroup=None)
    result = neo_group_usage(u, 202, 8, 'other')
    assert (result.html, result.status, result.missing) == (
        'Indicator Brightness Group<br/>Corridor Link Group', 'partial', ('AreaGroupAddress',))
    assert neo_group_usage(u, 203, 8, 'other').missing == ('KeyDisableGroup',)
    assert neo_action_selector_usage(unit(SceneTable=None), 202, 8, 11, 22).status == 'unrecovered'
    assert neo_group_usage(unit(SceneTable=None), 202, 8, 'input').status == 'unrecovered'
    assert neo_group_usage(unit(SceneTable=None), 202, 8, 'output').status == 'recovered'
    assert neo_group_usage(unit('KEYGL5'), 202, 8, 'output').status == 'unrecovered'


def test_neo_static_receipt_reproduces_when_configured():
    import os
    import sys
    import pytest

    source = os.environ.get('CBUS_TOOLKIT_EXE')
    if not source:
        pytest.skip('Set CBUS_TOOLKIT_EXE to inspect pinned original Neo usage methods')
    sys.path.insert(0, str(FIXTURES.parent))
    from project_documentor_neo_usage_static import inspect
    exe = Path(source)
    result = inspect(exe, Path(os.environ.get('CBUS_TOOLKIT_MAP', exe.with_suffix('.map'))))
    assert result == json.loads((FIXTURES / 'project-documentor-neo-usage-static.json').read_text())


def test_original_neo_action_vectors_reproduce_in_opt_in_subprocess(tmp_path):
    import os
    import subprocess
    import sys
    import pytest

    source = os.environ.get('CBUS_TOOLKIT_EXE')
    if not source or os.environ.get('CBUS_RUN_DOCUMENTOR_ORIGINAL') != '1':
        pytest.skip('Set CBUS_TOOLKIT_EXE and CBUS_RUN_DOCUMENTOR_ORIGINAL=1; requires executable memory')
    exe = Path(source)
    output = tmp_path / 'neo-actions.json'
    completed = subprocess.run([sys.executable, str(FIXTURES.parent / 'project_documentor_neo_usage_original.py'),
                                '--executable', str(exe), '--map-file',
                                os.environ.get('CBUS_TOOLKIT_MAP', str(exe.with_suffix('.map'))),
                                '--output', str(output)], capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text()) == json.loads((FIXTURES / 'project-documentor-neo-action-original.json').read_text())
    completed = subprocess.run([sys.executable, str(FIXTURES.parent / 'project_documentor_neo_usage_original.py'),
                                '--executable', str(exe), '--map-file',
                                os.environ.get('CBUS_TOOLKIT_MAP', str(exe.with_suffix('.map'))),
                                '--output', str(output), '--group-inputs'],
                               capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text()) == json.loads((FIXTURES / 'project-documentor-neo-input-original.json').read_text())


def test_input_dependencies_match_executed_original_neo_and_dlt_instructions():
    receipt = json.loads((FIXTURES / 'project-documentor-neo-input-original.json').read_text())
    assert len(receipt['cases']) == 7
    for case in receipt['cases']:
        blocks = tuple(NeoBlock(b['application'], b['group'], 0, 0, 0, 0) for b in case['blocks'])
        keys = tuple(NeoKey(sum(1 << b for b in key['blocks']), tuple(key['commands']), 56,
                            key['macro_type'], '', False, key['scene'], 0, None, '') for key in case['keys'])
        data = NeoData(tuple(case['applications']), True, case['physical_count'], ('',) * 4,
                       blocks, keys, tuple(tuple(SceneEntry(g, 100) for g in scene) for scene in case['scenes']),
                       9, ((255, 255), (255, 255)))
        assert input_usage_from_data(data, case['application'], case['group'], dlt=case['dlt']).html == case['html'], case['name']


def test_dlt_other_refuses_to_claim_absent_joins_from_missing_or_configured_pp():
    from cbus_toolkit.project_documentation_dlt import dlt_profile

    u = unit('KEYML5', '3.0.00', JoinPrimaryApplication=[8])
    result = neo_group_usage(u, 203, 8, 'other', profile=dlt_profile(u), dlt=True)
    assert result.html == 'Key Disable Group'
    assert result.status == 'partial'
    assert result.missing == ('JoinPrimaryApplication (requires disabled join)',)
