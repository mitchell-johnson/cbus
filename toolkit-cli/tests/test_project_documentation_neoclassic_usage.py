"""Independent consumer boundaries for Classic documentor / Neo unit hybrids."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

import pytest

from cbus_toolkit.device_scenes import SceneEntry, _encode
from cbus_toolkit.project_documentation import Unit
from cbus_toolkit.project_documentation_neoclassic_usage import (
    _scenes, neoclassic_action_selector_usage, neoclassic_group_usage,
)

FIXTURES = Path(__file__).parents[1] / 'research/fixtures'


def unit(kind='KEYC2', firmware='1.8.01', **changes):
    pp = {'Application': [202, 56], 'GroupAddress': [8, 8, 9, 10, 11, 12, 13, 14, 8],
        'DebounceTime': [1], 'LongPressTime': [2], 'RampRate': [0, 1],
        'BlockAllocation': [3, 1, 4, 8, 16, 32, 64, 128],
        'LightLevelStore1': [11] * 8, 'LightLevelStore2': [22] * 8,
        'TimerHighByte': [0] * 8, 'TimerLowByte': [0] * 8, 'TimerExpiryCommand': [15] * 8,
        'JPCommand': [12] * 8, 'SRCommand': [6] * 8, 'LPCommand': [0] * 8, 'LRCommand': [0] * 8,
        'SecondApplicationBlocks': [0], 'SceneKeySelector': [0] * 8,
        'AreaGroupAddress': [8], 'IndicatorBrightness': [255], 'KeyDisableGroup': [8],
        'CorridorMasterGroup': [8], 'ControlAppGroupAddress': [8]}
    pp.update(changes)
    return Unit(1, 'Key', kind, kind, '', firmware, '', {name: ' '.join(map(str, value))
        if isinstance(value, (list, tuple)) else value for name, value in pp.items() if value is not None}, {})


def scene_pp():
    table, pointers = _encode(((SceneEntry(8, 100),), (SceneEntry(8, 150),)) + ((),) * 6)
    return dict(SceneTable=table, SceneTablePointer=pointers)


@pytest.mark.parametrize('kind,count', [('KEYC1', 1), ('KEYC2', 2), ('KEYC4', 4), ('KEYCIR1', 0), ('KEYCIR4', 4)])
def test_input_uses_physical_count_but_action_scans_all_eight(kind, count):
    u = unit(kind, GroupAddress=[8] * 9, BlockAllocation=[1 << i for i in range(8)], SceneTable=[])
    result = neoclassic_group_usage(u, 202, 8, 'input')
    assert result.status == 'recovered'
    assert result.html.split('<br/>') == [f'Key {i + 1}' for i in range(count)] + ['Block (Unused)'] * (8 - count)
    action = neoclassic_action_selector_usage(u, 202, 8, 11, 22)
    assert action.html.split('<br/>') == [f'Key {i + 1}' for i in range(8) for _ in range(2)]


def test_scene_usage_is_loaded_even_though_class_scenes_enabled_is_false():
    result = neoclassic_group_usage(unit(**scene_pp()), 202, 8, 'input')
    assert result.status == 'recovered'
    assert result.html == 'Key 1<br/>Key 2<br/>Key 1<br/>Scene 1<br/>Scene 2 (Unused)'
    # The scene-use scan sees all virtual scene references, even with zero
    # physical keys; every fresh ordinary key references scene one.
    ir = neoclassic_group_usage(unit('KEYCIR1', **scene_pp()), 202, 8, 'input')
    assert ir.html == 'Block (Unused)<br/>Block (Unused)<br/>Scene 1<br/>Scene 2 (Unused)'


@pytest.mark.parametrize('table', [[], [255], [255, 77, 8, 90]])
def test_empty_or_first_unused_scene_table_does_not_read_pointers(table):
    u = unit(SceneTable=table, SceneTablePointer=None)
    assert _scenes(u) == ((),) * 8
    assert neoclassic_group_usage(u, 202, 8, 'input').status == 'recovered'


def test_input_scene_missingness_does_not_erase_blocks_or_affect_secondary_app():
    result = neoclassic_group_usage(unit(), 202, 8, 'input')
    assert (result.html, result.status) == ('Key 1<br/>Key 2<br/>Key 1', 'partial')
    assert 'SceneTable' in result.missing[0]
    secondary = unit(SecondApplicationBlocks=[3])
    result = neoclassic_group_usage(secondary, 56, 8, 'input')
    assert result.status == 'recovered' and result.html == 'Key 1<br/>Key 2<br/>Key 1'
    assert neoclassic_action_selector_usage(unit(), 202, 8, 11, 22).status == 'recovered'


def test_dependencies_do_not_require_body_timings_timer_duration_or_unconsumed_presets():
    u = unit(SceneTable=[], **{name: None for name in (
        'DebounceTime', 'LongPressTime', 'RampRate', 'TimerHighByte', 'TimerLowByte')})
    assert neoclassic_action_selector_usage(u, 202, 8, 11, 22).status == 'recovered'
    assert neoclassic_action_selector_usage(u, 202, 8, 11, 22).html.count('Key 1') == 4
    for name in ('LightLevelStore1', 'LightLevelStore2', 'TimerExpiryCommand'):
        u.parameters.pop(name)
    result = neoclassic_group_usage(u, 202, 8, 'input')
    assert (result.status, result.html) == ('recovered', 'Key 1<br/>Key 2<br/>Key 1')
    assert neoclassic_action_selector_usage(u, 202, 8, 11, 22).status == 'unrecovered'


@pytest.mark.parametrize('changes', [{'SceneTable': [8, 12]}, {'SceneTable': [-1]},
    {'SceneTable': [8, 12] + [255] * 78, 'SceneTablePointer': [163] + [255] * 7},
    {'SceneTable': [8, 12, 8, 13] + [255] * 76, 'SceneTablePointer': [162, 182, 202, 222] + [255] * 4}])
def test_noncanonical_or_invalid_scene_data_remains_partial(changes):
    result = neoclassic_group_usage(unit(**changes), 202, 8, 'input')
    assert result.status == 'partial' and result.html == 'Key 1<br/>Key 2<br/>Key 1'


def test_classic_action_preserves_outer_stored1_gate_and_has_no_secondary_or_scene_pass():
    result = neoclassic_action_selector_usage(unit(), 202, 8, 11, 22)
    assert result.html == 'Key 1<br/>Key 1<br/>Key 1<br/>Key 1<br/>Key 2<br/>Key 2'
    assert neoclassic_action_selector_usage(unit(), 202, 8, 99, 22).html == ''
    assert neoclassic_action_selector_usage(unit(), 202, 8, 11, 99).html == 'Key 1<br/>Key 1<br/>Key 2'
    same_app = unit(Application=[202, 202])
    assert neoclassic_action_selector_usage(same_app, 202, 8, 11, 22).html == result.html
    secondary = unit(Application=[56, 202], SecondApplicationBlocks=[3])
    assert neoclassic_action_selector_usage(secondary, 202, 8, 11, 22).html == ''
    # Native primary-app guard precedes every key-field read.
    sparse = replace(unit(), parameters={'Application': '56'})
    assert neoclassic_action_selector_usage(sparse, 202, 8, 11, 22).status == 'recovered'
    assert neoclassic_action_selector_usage(sparse, 56, 8, 11, 22).status == 'unrecovered'


def test_action_selector255_and_unused_group_remain_real_identities():
    u = unit(GroupAddress=[255] * 9, LightLevelStore1=[255] * 8)
    assert neoclassic_action_selector_usage(u, 202, 255, 255, 22).html.startswith('Key 1<br/>Key 1')
    assert neoclassic_action_selector_usage(u, 202, 255, 22, 255).html == ''


def test_other_uses_own_fields_and_never_requires_join_programming():
    u = replace(unit(), parameters={'Application': '202', 'AreaGroupAddress': '8',
        'IndicatorBrightness': ' ', 'GroupAddress': '0 0 0 0 0 0 0 0 8',
        'CorridorMasterGroup': '8', 'ControlAppGroupAddress': '8'})
    result = neoclassic_group_usage(u, 202, 8, 'other')
    assert result.status == 'recovered'
    assert result.html == 'Area Group<br/>Indicator Brightness Group<br/>Corridor Link Group<br/>Control App Group'
    disabled = replace(u, parameters={**u.parameters, 'IndicatorBrightness': ''})
    assert 'Indicator Brightness' not in neoclassic_group_usage(disabled, 202, 8, 'other').html
    enable = replace(u, parameters={'Application': '56', 'KeyDisableGroup': '255'})
    assert neoclassic_group_usage(enable, 203, 255, 'other').html == 'Key Disable Group'
    assert neoclassic_group_usage(enable, 203, 255, 'other').status == 'recovered'


def test_other_missing_known_fields_preserves_ordered_results():
    u = unit(AreaGroupAddress=None, CorridorMasterGroup=None)
    result = neoclassic_group_usage(u, 202, 8, 'other')
    assert (result.html, result.status, result.missing) == ('Indicator Brightness Group<br/>Control App Group',
                                                          'partial', ('AreaGroupAddress', 'CorridorMasterGroup'))
    result = neoclassic_group_usage(unit(Application=None), 203, 8, 'other')
    assert result.html == 'Key Disable Group' and result.missing == ('Application',)


def test_invalid_identity_and_encoded_scene_state_cannot_be_silently_recovered():
    for u in (unit(firmware='1.8.00'), unit('KEYGL5'), unit(firmware='١.٨.٠١')):
        assert neoclassic_group_usage(u, 202, 8, 'output').status == 'unrecovered'
    u = unit(SceneKeySelector=[1] + [0] * 7)
    assert neoclassic_group_usage(u, 202, 8, 'input').status == 'unrecovered'
    assert neoclassic_action_selector_usage(u, 202, 8, 11, 22).status == 'unrecovered'
    assert neoclassic_group_usage(u, 202, 8, 'output').status == 'recovered'


def test_static_receipt_pins_every_supported_class():
    receipt = json.loads((FIXTURES / 'project-documentor-neoclassic-usage-static.json').read_text())
    assert {r['unit_type'] for r in receipt['registrations']} == {'KEYC1', 'KEYC2', 'KEYC4', 'KEYCIR1', 'KEYCIR4'}
    assert all(receipt['checks'].values())
    assert receipt['original_loader_execution'] == 'not_executed'


def test_static_receipt_reproduces_when_configured():
    source = os.environ.get('CBUS_TOOLKIT_EXE')
    if not source:
        pytest.skip('Set CBUS_TOOLKIT_EXE for the pinned KEYC/CIR static comparison')
    sys.path.insert(0, str(FIXTURES.parent))
    from project_documentor_neoclassic_usage_static import inspect
    exe = Path(source)
    result = inspect(exe, Path(os.environ.get('CBUS_TOOLKIT_MAP', exe.with_suffix('.map'))))
    assert result == json.loads((FIXTURES / 'project-documentor-neoclassic-usage-static.json').read_text())


def test_classic_actions_match_retained_original_instruction_vectors():
    # Reuse the already executed Classic-only receipt; no new vendor execution.
    receipt = json.loads((FIXTURES / 'project-documentor-pir-original.json').read_text())
    for case in receipt['action_cases']:
        blocks = case['blocks'] + [{'application': case['applications'][0], 'group': 255,
            'stored1': 0, 'stored2': 0, 'expiry': 15}] * (8 - len(case['blocks']))
        keys = case['keys'] + [{'blocks': [], 'commands': []}] * (8 - len(case['keys']))
        commands = [key['commands'] + [0] * (4 - len(key['commands'])) for key in keys]
        u = unit(Application=case['applications'], GroupAddress=[b['group'] for b in blocks],
            LightLevelStore1=[b['stored1'] for b in blocks], LightLevelStore2=[b['stored2'] for b in blocks],
            TimerExpiryCommand=[b['expiry'] for b in blocks],
            SecondApplicationBlocks=[sum(1 << i for i, b in enumerate(blocks) if b['application'] != case['applications'][0])],
            BlockAllocation=[sum(1 << i for i in key['blocks']) for key in keys],
            **{name: [commands[i][stage] for i in range(8)] for stage, name in enumerate(
                ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand'))})
        result = neoclassic_action_selector_usage(u, case['application'], case['group'], case['address'], case['value'])
        assert result.status == 'recovered'
        assert result.html == case['html'], case['name']


@pytest.mark.parametrize('kind,count', [('KEYC1', 1), ('KEYC2', 2), ('KEYC4', 4), ('KEYCIR1', 0), ('KEYCIR4', 4)])
def test_report_dispatch_preserves_scene_input_and_primary_virtual_actions(kind, count):
    from cbus_toolkit.project_documentation_usage import action_selector_usage, group_usage
    u = unit(kind, GroupAddress=[8] * 9, BlockAllocation=[1 << i for i in range(8)], **scene_pp())
    result = group_usage(u, 202, 8, 'input')
    assert result.status == 'recovered'
    assert result.html.split('<br/>') == ([f'Key {i + 1}' for i in range(count)]
        + ['Block (Unused)'] * (8 - count) + ['Scene 1', 'Scene 2 (Unused)'])
    actions = action_selector_usage(u, 'ClassicKeyInput', 202, 8, 11, 22)
    assert actions.status == 'recovered'
    assert actions.html.split('<br/>') == [f'Key {i + 1}' for i in range(8) for _ in range(2)]
    secondary = unit(kind, Application=[56, 202], GroupAddress=[8] * 9,
                     BlockAllocation=[1 << i for i in range(8)], SecondApplicationBlocks=[255])
    assert action_selector_usage(secondary, 'ClassicKeyInput', 202, 8, 11, 22).html == ''
