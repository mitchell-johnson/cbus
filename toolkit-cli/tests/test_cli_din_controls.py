"""Public ordered DIN controls; expected byte arrays are literal source cases."""
import json

import pytest

from test_cli_din_save import cli
from test_cli_din_output_settings import snapshot, write_spec
from test_din_output_settings import fixture


def setup(tmp_path, unit_type='DIMDN8', **overrides):
    write_spec(tmp_path, unit_type)
    values = fixture(unit_type).defaults()
    values.update(overrides)
    path = snapshot(tmp_path, unit_type, parameters=values)
    return path, ('din-settings', '--spec-dir', tmp_path, 'plan', path)


def controls(tmp_path, rows):
    path = tmp_path / 'controls.json'
    path.write_text(json.dumps(rows))
    return path


def test_public_same_position_preserves_noncanonical_raw_level(tmp_path):
    source, args = setup(tmp_path, MinDimmingLevel='26 0 0 0 0 0 0 0',
                         MaxDimmingLevel='255 255 255 255 255 255 255 255')
    before = source.read_bytes()
    operations = [
        {'op': 'synchronise', 'tab': 'turn-on', 'enabled': True},
        {'op': 'minimum', 'channel': 1, 'percent': 10},
    ]
    result = cli(*args, '--controls', controls(tmp_path, operations))
    assert result['format'] == 'cbus-din-output-controls-plan-v1'
    assert result['operations'] == operations
    assert 'MinDimmingLevel' not in result['changes']
    assert result['settings_plan']['format'] == 'cbus-din-output-settings-plan-v1'
    assert result['saved'] is False
    assert source.read_bytes() == before


def test_public_synchronised_minimum_couples_maximum_first(tmp_path):
    _, args = setup(tmp_path, MinDimmingLevel='0 0 0 0 0 0 0 0',
                    MaxDimmingLevel='51 255 255 255 255 255 255 255')
    operations = [
        {'op': 'synchronise', 'tab': 'turn-on', 'enabled': True},
        {'op': 'minimum', 'channel': 1, 'percent': 30},
    ]
    result = cli(*args, '--controls', controls(tmp_path, operations), '--toolkit-save')
    assert result['changes']['MinDimmingLevel'] == [76] * 8
    assert result['changes']['MaxDimmingLevel'] == [79] * 8
    assert result['toolkit_save'] is True
    assert result['settings_plan']['format'] == 'cbus-din-output-settings-plan-v2'
    assert result['settings_plan']['normalization_passes'] == 1


@pytest.mark.parametrize('step,expected', [
    (5, [5, 10, 15, 20, 25, 30, 35, 40]),
    (10, [10, 20, 30, 40, 50, 60, 61, 62]),
    (20, [20, 40, 60, 62, 64, 66, 68, 70]),
    (30, [30, 60, 63, 66, 69, 72, 75, 78]),
])
def test_public_delay_stagger_literal_conversion(tmp_path, step, expected):
    _, args = setup(tmp_path, PowerUpDelay='5 5 5 5 5 5 5 5')
    result = cli(*args, '--controls', controls(tmp_path, [
        {'op': 'stagger-recovery-delay', 'step_seconds': step},
    ]))
    assert result['changes']['PowerUpDelay'] == expected


def test_public_relay_turn_on_stagger(tmp_path):
    _, args = setup(tmp_path, 'RELDN4', MinDimmingLevel='0 0 0 0')
    result = cli(*args, '--controls', controls(tmp_path, [
        {'op': 'stagger-turn-on', 'step_percent': 10},
    ]))
    assert result['changes']['MinDimmingLevel'] == [25, 51, 76, 102]
    assert 'MaxDimmingLevel' not in result['changes']


@pytest.mark.parametrize('rows', [
    [{'op': 'stagger-recovery-delay', 'step_seconds': 15}],
    [{'op': 'stagger-minimum', 'step_percent': True}],
    [{'op': 'stagger-minimum', 'step_percent': 13}],
    [{'op': 'minimum', 'channel': 9, 'percent': 10}],
    [{'op': 'synchronise', 'tab': 'turn-on', 'enabled': 1}],
    [{'op': 'unproved-control'}],
])
def test_public_control_refusals_preserve_input(tmp_path, rows):
    source, args = setup(tmp_path)
    before = source.read_bytes()
    result = cli(*args, '--controls', controls(tmp_path, rows), status=1)
    assert result['error']
    assert source.read_bytes() == before


def test_public_controls_cannot_hide_direct_edit_order(tmp_path):
    _, args = setup(tmp_path)
    result = cli(*args, '--controls', controls(tmp_path, [
        {'op': 'minimum', 'channel': 1, 'percent': 20},
    ]), '--channel', 1, '--min-percent', 30, status=1)
    assert '--controls cannot be combined' in result['error']
