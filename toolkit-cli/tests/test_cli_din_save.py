"""Public offline DIN agent-save opt-in and legacy targeted-plan boundary."""
import json
import subprocess
import sys

import pytest

from test_cli_din_output_settings import snapshot, write_spec
from test_din_output_settings import fixture


def cli(*args, status=0):
    result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == status, result.stdout + result.stderr
    return json.loads(result.stdout or result.stderr)


@pytest.mark.parametrize('unit_type,channels', [
    ('RELDN4', 4), ('RELDN8B', 8), ('RELDN12', 12),
    ('DIMDN4', 4), ('DIMDN4F', 4), ('DIMDN8', 8), ('DIMDN8F', 8),
])
def test_public_offline_agent_save_and_legacy_targeted_plan(tmp_path, unit_type, channels):
    write_spec(tmp_path, unit_type)
    values = fixture(unit_type).defaults()
    # Distinct stored recovery values make every intended rewrite observable.
    values['LightLevel'] = ' '.join(str(v) for v in range(10, 26))
    values['GroupAddress'] = ' '.join(str(v) for v in range(30, 46))
    path = snapshot(tmp_path, unit_type, parameters=values)
    args = ('din-settings', '--spec-dir', tmp_path, 'plan', path)
    targeted = cli(*args)
    assert targeted['changes'] == {}
    normalized = cli(*args, '--toolkit-save')
    assert normalized['toolkit_save'] is True
    assert normalized['saved'] is False
    assert normalized['device_verified'] is False
    assert normalized['changes']['LightLevel'] == [255] * channels + [0] * (12 - channels) + [22, 23, 24, 25]
    expected_groups = list(range(30, 30 + channels)) + [255] * (12 - channels) + [42, 43, 44, 45]
    assert normalized['changes'].get('GroupAddress', list(range(30, 46))) == expected_groups
    # A direct supported edit occurs before the owning save's dependent fields.
    edited = cli(*args, '--toolkit-save', '--channel', '1', '--level-store', 'off', '--recovery-percent', '20')
    assert edited['changes']['LightLevel'][0] == 51
    assert edited['changes']['LightLevel'][1:channels] == [255] * (channels - 1)
    assert path.read_text() == json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': unit_type,
                                         'firmware': '2.7.00', 'catalog_number': None, 'parameters': values})


def test_public_offline_agent_save_profile_and_show_guards(tmp_path):
    write_spec(tmp_path, 'DIMDN8')
    path = snapshot(tmp_path, 'DIMDN8', firmware='2.6.99')
    error = cli('din-settings', '--spec-dir', tmp_path, 'plan', path, '--toolkit-save', status=1)
    assert '2.7.00' in error['error']
    path = snapshot(tmp_path, 'DIMDN8')
    result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', 'din-settings', '--spec-dir', str(tmp_path),
                             'show', str(path), '--toolkit-save'], capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert '--toolkit-save' in result.stderr


def test_public_marshalling_save_keeps_order_and_short_array_tail(tmp_path):
    write_spec(tmp_path, 'RELDN8')
    values = fixture('RELDN8').defaults()
    values.update(LightLevel='10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25',
                  GroupAddress='30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45',
                  MinDimmingLevel='10 11 12 13 14 15 16 17 18 19 20 21',
                  MaxDimmingLevel='101 102 103 104')
    path = snapshot(tmp_path, 'RELDN8', parameters=values)
    plan = cli('din-settings', '--spec-dir', tmp_path, 'plan', path, '--toolkit-save')
    assert plan['toolkit_save'] is True
    assert plan['changes']['LightLevel'] == [0, 11, 12, 13, 14, 0, 0, 17, 18, 19, 20, 0, 22, 23, 24, 25]
    assert plan['changes']['GroupAddress'] == [255, 31, 32, 33, 34, 255, 255, 37, 38, 39, 40, 255, 42, 43, 44, 45]
    assert plan['changes']['MinDimmingLevel'] == [0, 11, 12, 13, 14, 0, 0, 17, 18, 19, 20, 21]
    assert plan['changes']['MaxDimmingLevel'] == [102, 103, 104, 0]
