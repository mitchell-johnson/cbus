"""Synthetic saved PP and pinned original-method comparisons only."""
import hashlib
import json
import os
from fractions import Fraction
from pathlib import Path
import subprocess
import sys

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_temperature as temp

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'research/experiments/2026-09-30/project-documentor-temperature-static.json'
ORIGINAL = ROOT / 'research/fixtures/project-documentor-temperature-original.json'


def snapshot(kind='SENTEMP', **changes):
    values = {'Application': [56], 'AreaGroupAddress': [1], 'ControlGroupAddress': [1],
              'EnableGroupAddress': [2], 'OffsetGroupAddress': [3], 'TemperatureHigh': [22],
              'TemperatureLow': [19], 'OffsetMode': [0], 'TemperatureOffset': [5]}
    if kind == 'SENTEMPB':
        values = {'Application': [56], 'AreaGroupAddress': [1], 'ControlledGroup': [1],
                  'GroupAddress': [2], 'EconomyGroup': [3], 'ModeHeating': [0],
                  'TargetTemperature': [22, 19], 'EconomyOffset': [5], 'TemperatureGroup': [1],
                  'ThermostatRegulationZones': [21], 'BroadcastTriggerGroup': [8],
                  'BroadcastTriggerLevel': [11], 'BroadcastInterval': [7], 'TemperatureChangeThreshold': [6]}
    elif kind == 'SENTEMP4':
        values = {'DeviceID': [255]}
        for n in range(1, 5):
            values.update({f'Channel{n}ChannelName': f'  Channel {n}\t', f'Channel{n}ChannelMode': [172],
                           f'Channel{n}HVACCommunicationGroup': [n % 3 + 1], f'Channel{n}HVACZones': [21],
                           f'Channel{n}BroadcastInterval': [0], f'Channel{n}BroadcastThreshold': [0]})
    values.update(changes)
    parameters = {name: value if isinstance(value, str) else ' '.join(map(str, value))
                  for name, value in values.items() if value is not None}
    return doc.Unit(3, 'Temperature', kind, '', '', '1.2.00', '', parameters, {})


def network():
    return doc.Network(254, '', '', '', [doc.Application(a, '', '', [
        doc.Group(g, '<Unused>' if g == 255 else f'Group <{g}>', '', [doc.Level(11, 'Action <11>', 99)])
        for g in (1, 2, 3, 8, 255)]) for a in (25, 56, 172, 202, 228)], [])


def test_sentemp_complete_report_and_ceil_not_nearest_even():
    data = temp.temperature_data(snapshot())
    assert (data['target'], data['margin']) == (21, 3)
    assert temp.temperature_lines(network(), data)[-4:] == [
        'Mode: Heating<br />', 'Target: 21°C<br />', 'Margin: 3°C<br />', 'Economy Offset: 5°C<br />']
    assert temp.temperature_lines(network(), data, units='fahrenheit')[-3:] == [
        'Target: 70°F<br />', 'Margin: 5°F<br />', 'Economy Offset: 9°F<br />']
    data = temp.temperature_data(snapshot(TemperatureHigh=[19], TemperatureLow=[22], OffsetMode=[255]))
    assert (data['target'], data['margin'], data['heating']) == (21, -3, False)


def test_unused_economy_needs_group_metadata_but_no_offset_field():
    unit = snapshot(OffsetGroupAddress=[255], TemperatureOffset=None)
    lines = temp.temperature_lines(network(), temp.temperature_data(unit))
    assert lines[2] == 'Economy Group: &#60;Unused&#62;<br />'
    assert not any('Offset:' in line for line in lines)


def test_pro_control_clamps_and_ignores_unused_broadcast_fields():
    unit = snapshot('SENTEMPB', TargetTemperature=[0, 255], EconomyOffset=[255], ModeHeating=[1],
                    BroadcastInterval=None, TemperatureChangeThreshold=None, BroadcastTriggerGroup=None)
    data = temp.temperature_data(unit)
    assert (data['high'], data['low'], data['offset']) == (1, 49, 20)
    assert temp.temperature_lines(network(), data)[-4:] == ['Mode: Cooling<br />',
        'Target Temperature High: 1°C<br />', 'Target Temperature Low: 49°C<br />', 'Economy Offset: 20°C<br />']


@pytest.mark.parametrize('application,label', [(25, 'Temperature Group:'), (172, 'Communication Group:'), (228, 'Device ID:')])
def test_pro_broadcast_application_mode_and_unused_control_fields(application, label):
    unit = snapshot('SENTEMPB', Application=[application], ControlledGroup=None, EconomyGroup=None,
                    ModeHeating=None, TargetTemperature=None, EconomyOffset=None)
    lines = temp.temperature_lines(network(), temp.temperature_data(unit))
    assert lines[0].startswith(label)
    assert lines[-2:] == ['Broadcast Interval: 1m10s<br />', 'Broadcast Temperature Threshold: 1.50°C<br />']
    assert any('Action <11>' in line for line in lines)


@pytest.mark.parametrize('raw,expected', [(0, 6), (1, 3), (3, 3), (59, 59), (60, 60), (254, 60), (255, None)])
def test_pro_interval_normalization(raw, expected):
    assert temp.temperature_data(snapshot('SENTEMPB', Application=[172], BroadcastInterval=[raw]))['interval'] == expected


@pytest.mark.parametrize('raw,expected', [(0, 3), (1, Fraction(1, 2)), (2, Fraction(1, 2)), (3, Fraction(1, 2)),
    (5, 1), (64, 16), (253, 16), (254, None), (255, None)])
def test_pro_threshold_normalization(raw, expected):
    assert temp.temperature_data(snapshot('SENTEMPB', Application=[172], TemperatureChangeThreshold=[raw]))['threshold'] == expected


def test_pro_unused_trigger_hides_selector_and_disabled_settings():
    unit = snapshot('SENTEMPB', Application=[228], GroupAddress=[255], BroadcastTriggerGroup=[255],
                    BroadcastTriggerLevel=None, BroadcastInterval=[255], TemperatureChangeThreshold=[254])
    assert temp.temperature_lines(network(), temp.temperature_data(unit)) == [
        'Device ID: 255<br />', 'Broadcast Trigger Group: &#60;Unused&#62;<br />',
        'Broadcast Interval: Not Used<br />', 'Broadcast Temperature Threshold: Not Used<br />']


def test_pro_selector_255_on_used_group_is_not_an_unused_level():
    net = network()
    net.application(202).group(8).levels.append(doc.Level(255, 'Maximum <selector>', 0))
    unit = snapshot('SENTEMPB', Application=[25], BroadcastTriggerLevel=[255])
    lines = temp.temperature_lines(net, temp.temperature_data(unit))
    assert 'Broadcast Trigger Action Selector: <a href="#254_202_8_255">Maximum <selector></a><br />' in lines
    net.application(202).group(8).levels.pop()
    assert temp.document_temperature(doc._Writer(), net, unit) == 'partial'


def test_digital_raw_headers_trim_empty_names_and_malformed_table_preserved():
    unit = snapshot('SENTEMP4', Channel1ChannelName=' \t<Raw>\r\n', Channel2ChannelName='\0 \t',
                    Channel3ChannelName='\u00a0Name\u00a0', Channel4HVACCommunicationGroup=[255], Channel4HVACZones=None)
    lines = temp.temperature_lines(network(), temp.temperature_data(unit))
    assert lines[:6] == ['<b>Device ID: </b>Unassigned<br />', '<table border="1"><tr>',
        '<th><Raw></th>', '<th>Channel 2</th>', '<th>\u00a0Name\u00a0</th>', '<th>Channel 4</th>']
    assert lines[-1] == '</tr>' and '</table>' not in lines
    assert lines.count('<b>Mode:</b> HVAC<br />') == 3
    assert lines.count('<b>Mode:</b> Measurement<br />') == 1
    assert lines.count('<b>Broadcast Interval:</b> 60 seconds<br />') == 4
    assert lines.count('<b>Broadcast Threshold:</b> 0.50°C<br />') == 4


def test_digital_measurement_ignores_hvac_pp_and_keeps_absolute_fahrenheit_threshold():
    unit = snapshot('SENTEMP4', DeviceID=[11], **{
        key: value for n in range(1, 5) for key, value in (
            (f'Channel{n}ChannelMode', [228]), (f'Channel{n}HVACCommunicationGroup', None),
            (f'Channel{n}HVACZones', None), (f'Channel{n}BroadcastInterval', [255]),
            (f'Channel{n}BroadcastThreshold', [1]))})
    lines = temp.temperature_lines(network(), temp.temperature_data(unit), units='fahrenheit')
    assert lines[0] == '<b>Device ID: </b>11<br />'
    assert lines.count('<b>Broadcast Interval:</b> 2550 seconds<br />') == 4
    assert lines.count('<b>Broadcast Threshold:</b> 32.23°F<br />') == 4


@pytest.mark.parametrize('mask,text', [(0, ''), (1, 'Unswitched Zone'), (21, 'Unswitched Zone, Zone 2, Zone 4'), (255, 'Unswitched Zone, Zone 1, Zone 2, Zone 3, Zone 4')])
def test_zone_order_and_ignored_high_bits(mask, text):
    assert temp.display_zones(mask) == text


@pytest.mark.parametrize('field,value', [('TemperatureHigh', None), ('TemperatureLow', []), ('ControlGroupAddress', [256]),
    ('OffsetMode', [-1]), ('TemperatureOffset', 'invalid')])
def test_invalid_consumed_pp_keeps_atomic_body_partial(field, value):
    out = doc._Writer()
    assert temp.document_temperature(out, network(), snapshot(**{field: value})) == 'partial'
    assert not any(line.startswith('Controlled Group:') for line in out.lines)
    assert out.unrecovered


@pytest.mark.parametrize('kind,field', [('SENTEMPB', 'TargetTemperature'), ('SENTEMP4', 'Channel3ChannelName'),
    ('SENTEMP4', 'Channel4BroadcastThreshold')])
def test_incomplete_other_profiles_remain_partial(kind, field):
    out = doc._Writer()
    assert temp.document_temperature(out, network(), snapshot(kind, **{field: None})) == 'partial'
    assert out.unrecovered


@pytest.mark.parametrize('firmware', ['', 'bad', '1.2.69', '0.99', '9' * 5000])
def test_sentemp_factory_is_narrower_than_documentor_factory(firmware):
    unit = snapshot()
    unit.firmware = firmware
    assert not temp.temperature_supported(unit)
    assert temp.temperature_group_usage(unit, 56, 1, 'input').status == 'unrecovered'


def test_missing_group_or_selector_metadata_never_invented():
    net = network()
    net.application(202).group(8).levels = []
    out = doc._Writer()
    assert temp.document_temperature(out, net, snapshot('SENTEMPB', Application=[172])) == 'partial'
    assert 'Level 11' in out.unrecovered[0]['item']
    assert not net.application(202).group(8).levels
    net.application(56).groups = []
    assert temp.document_temperature(doc._Writer(), net, snapshot()) == 'partial'


def test_group_dependency_order_modes_sentinels_and_partial_fields():
    unit = snapshot(EnableGroupAddress=[1], OffsetGroupAddress=[1], TemperatureHigh=None)
    assert temp.temperature_group_usage(unit, 56, 1, 'input').html == 'Control Group'
    assert temp.temperature_group_usage(unit, 56, 1, 'other').html == 'Area Group<br/>Enable Group<br/>Economy Group'
    unit.parameters.pop('EnableGroupAddress')
    usage = temp.temperature_group_usage(unit, 56, 1, 'other')
    assert usage.status == 'partial' and usage.html == 'Area Group<br/>Economy Group'
    assert temp.temperature_group_usage(unit, 56, 1, 'output').html == ''
    assert temp.temperature_group_usage(unit, 202, 1, 'other').status == 'recovered'
    unit = snapshot('SENTEMPB', ControlledGroup=[255])
    assert temp.temperature_group_usage(unit, 56, 255, 'input').html == 'Controlled Group'
    for application, field, label in [(25, 'TemperatureGroup', 'Temperature Group'), (172, 'GroupAddress', 'Communication Group')]:
        unit = snapshot('SENTEMPB', Application=[application], **{field: [255]})
        assert temp.temperature_group_usage(unit, application, 255, 'other').html == label
        assert temp.temperature_group_usage(unit, application, 255, 'input').html == ''
    unit = snapshot('SENTEMPB', Application=[228])
    assert temp.temperature_group_usage(unit, 228, 1, 'other').html == ''


@pytest.mark.parametrize('index', range(18))
def test_all_original_body_lines(index):
    row = json.loads(ORIGINAL.read_text())['cases'][index]
    assert temp.temperature_lines(network(), row, units=row['units']) == row['lines']


def test_all_576_original_decimal_threshold_vectors():
    rows = json.loads(ORIGINAL.read_text())['numeric']
    assert len(rows) == 576
    for row in rows:
        units = 'fahrenheit' if row['fahrenheit'] else 'celsius'
        result = temp._temperature(Fraction(row['numerator'], row['denominator']), units, delta=row['delta'], decimals=True)
        assert result == row['text'] + ('°F' if row['fahrenheit'] else '°C')
    assert temp._temperature(Fraction(1, 8), 'celsius', decimals=True) == '0.13°C'


def test_every_possible_byte_average_matches_original_ceil():
    rows = json.loads(ORIGINAL.read_text())['ceil_half_sums']
    assert [total for total, _ in rows] == list(range(511))
    for total, result in rows:
        assert result == (total + 1) // 2


def test_receipts_bind_source_and_keep_complete_page_boundary():
    source, original = json.loads(STATIC.read_text()), json.loads(ORIGINAL.read_text())
    assert all(source['checks'].values()) and len(source['checks']) == 39
    assert source['model_sha256'] == hashlib.sha256(Path(temp.__file__).read_bytes()).hexdigest()
    assert source['original_executed'] is False and source['original_generated_page_comparison'] == 'not_obtained'
    assert original['original_methods_executed'] is True and original['original_loader_executed'] is False
    assert original['original_generated_page_compared'] is False
    assert 'running preferences not observed' in source['format_basis']


def test_original_static_receipt_when_configured():
    exe = os.environ.get('CBUS_TOOLKIT_EXE')
    if not exe:
        pytest.skip('Requires pinned Toolkit EXE/MAP')
    sys.path.insert(0, str(ROOT / 'research'))
    from project_documentor_temperature_static import inspect
    assert inspect(Path(exe), Path(os.environ.get('CBUS_TOOLKIT_MAP', str(Path(exe).with_suffix('.map'))))) == json.loads(STATIC.read_text())


def test_original_instruction_receipt_when_explicitly_enabled(tmp_path):
    exe = os.environ.get('CBUS_TOOLKIT_EXE')
    if not exe or os.environ.get('CBUS_RUN_DOCUMENTOR_ORIGINAL') != '1':
        pytest.skip('Requires pinned Toolkit inputs and CBUS_RUN_DOCUMENTOR_ORIGINAL=1')
    result = tmp_path / 'temperature-original.json'
    subprocess.run([sys.executable, str(ROOT / 'research/project_documentor_temperature_original.py'), '--exe', exe,
                    '--map', os.environ.get('CBUS_TOOLKIT_MAP', str(Path(exe).with_suffix('.map'))), '--output', str(result)], check=True)
    assert json.loads(result.read_text()) == json.loads(ORIGINAL.read_text())
