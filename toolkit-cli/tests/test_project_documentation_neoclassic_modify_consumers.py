"""Canonical SceneModify consumer state remains distinct from Scene24."""
from dataclasses import replace

import pytest

from cbus_toolkit import project_documentation_neoclassic as classic
from cbus_toolkit.macros import STAGES
from cbus_toolkit.project_documentation_neoclassic_usage import (
    neoclassic_action_selector_usage, neoclassic_group_usage,
)
from test_project_documentation_neo import pp, unit
from test_project_documentation_neoclassic import body
from test_project_documentation_neoclassic_usage import scene_pp


def modify(typ='KEYC4', *, commands=(12, 6, 7, 0), indexes=(7,), **changes):
    values = pp()
    for index in indexes:
        values['SceneKeySelector'][index] = 1
        values['BlockAllocation'][index] = 1 << index
        values['GroupAddress'][index] = 255
        for stage, value in zip(STAGES, commands):
            values[stage][index] = value
    values.update(changes)
    values.pop('IndicatorBlockAssignment')
    return unit({name: value for name, value in values.items() if value is not None}, typ, '1.8.01')


@pytest.mark.parametrize('typ', classic.NEOCLASSIC_TYPES)
def test_modify_body_keeps_template25_raw_stages_and_scene1_instant_without_indicator(typ):
    u = modify(typ)
    for field in ('SceneTable', 'SceneTablePointer', 'ControlAppGroupAddress'):
        u.parameters.pop(field)
    data = classic.neoclassic_data(u)
    key = data.keys[7]
    assert (key.macro_type, key.macro_label, key.commands) == (25, '<Scene Modify>', (12, 6, 7, 0))
    assert (key.scene_index, key.scene_ramp, key.scene_trigger) == (0, 0, None)
    out, status = body(u)
    assert status == 'recovered'
    row = next(line for line in out.lines if line.startswith('<tr><td>Virtual Key 8') or line.startswith('<tr><td>IR Key 8'))
    assert '<td>&#60;Scene Modify&#62;</td><td>&nbsp;</td>' in row
    assert '<td>Scene 1</td><td>Instant</td>' in row
    assert 'Scene 2' not in row and 'Timer' not in row
    assert 'Scenes<br />' not in out.lines


@pytest.mark.parametrize('commands', [(0, 0, 0, 0), (13, 7, 15, 0), (12, 0, 0, 0), (15, 15, 15, 15)])
def test_modify_template_survives_global_macro_matches_and_never_initializes_timer(commands):
    u = modify(commands=commands, TimerHighByte=[0] * 8, TimerLowByte=[0] * 8,
               LightLevelStore1=[255] * 8, Application=[202, 56])
    data = classic.neoclassic_data(u)
    assert data.keys[7].macro_type == 25 and data.keys[7].commands == commands
    assert data.blocks[7].timer == 0


@pytest.mark.parametrize('typ,physical', [('KEYC1', 1), ('KEYC2', 2), ('KEYC4', 4), ('KEYCIR1', 0), ('KEYCIR4', 4)])
def test_idle_modify_keys_stay_active_and_all_reference_scene1(typ, physical):
    u = modify(typ, commands=(0, 0, 0, 0), indexes=tuple(range(8)))
    u.parameters.update({name: ' '.join(map(str, values)) for name, values in scene_pp().items()})
    blocks = neoclassic_group_usage(u, 56, 255, 'input')
    assert blocks.status == 'recovered'
    assert blocks.html.split('<br/>') == [f'Key {index + 1}' for index in range(physical)] + ['Block (Unused)'] * (8 - physical)
    scenes = neoclassic_group_usage(u, 56, 8, 'input')
    assert (scenes.status, scenes.html) == ('recovered', 'Scene 1<br/>Scene 2 (Unused)')


def test_modify_classic_actions_preserve_raw_stages_stored1_gate_and_virtual_keys():
    u = modify('KEYCIR1', indexes=tuple(range(8)), Application=[202, 56],
               LightLevelStore1=[11] * 8, LightLevelStore2=[22] * 8)
    for field in ('DebounceTime', 'LongPressTime', 'RampRate', 'TimerHighByte', 'TimerLowByte',
                  'SceneTable', 'SceneTablePointer', 'ControlAppGroupAddress'):
        u.parameters.pop(field)
    assert neoclassic_action_selector_usage(u, 202, 255, 11, 22).html == '<br/>'.join(
        f'Key {index + 1}' for index in range(8) for _ in range(2))
    assert neoclassic_action_selector_usage(u, 202, 255, 99, 22).html == ''
    assert neoclassic_action_selector_usage(u, 56, 255, 11, 22).html == ''


def test_mixed_scene24_and_modify_only_consumes_actual_scene24_indicator_slots():
    u = modify(indexes=(0,))
    u.parameters['SceneKeySelector'] = '1 0 0 0 0 0 0 1'
    u.parameters['BlockAllocation'] = '1 2 0 0 0 0 0 128'
    u.parameters['GroupAddress'] = '255 2 255 255 255 255 255 255 255'
    u.parameters['IndicatorBlockAssignment'] = '255 255 255 255 255 255 255 1'
    for stage, value in zip(STAGES, (14, 2, 4, 2)):
        values = u.array(stage)
        values[7] = value
        u.parameters[stage] = ' '.join(map(str, values))
    data = classic.neoclassic_data(u)
    assert (data.keys[0].macro_type, data.keys[0].scene_index) == (25, 0)
    assert (data.keys[7].macro_type, data.keys[7].scene_index, data.keys[7].commands) == (24, 1, (0, 0, 0, 0))
    u.parameters.update({name: ' '.join(map(str, values)) for name, values in scene_pp().items()})
    assert neoclassic_group_usage(u, 56, 8, 'input').html == 'Scene 1<br/>Scene 2'


@pytest.mark.parametrize('parameter,value', [('BlockAllocation', '1 2 0 0 0 0 0 3'),
    ('BlockAllocation', '129 2 0 0 0 0 0 128'), ('GroupAddress', '1 2 255 255 255 255 255 1 255'),
    ('SecondApplicationBlocks', '128')])
def test_modify_noncanonical_graph_remains_partial(parameter, value):
    u = modify()
    u.parameters[parameter] = value
    assert body(u)[1] == 'partial'
    assert neoclassic_group_usage(u, 56, 255, 'input').status == 'unrecovered'
