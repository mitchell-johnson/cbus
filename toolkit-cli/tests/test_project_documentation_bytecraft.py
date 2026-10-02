"""Old Bytecraft report consumers from explicit synthetic packed records."""
from dataclasses import replace
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
import json
import os
from pathlib import Path
import sys
from xml.sax.saxutils import escape

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit.project_documentation_bytecraft_usage import bytecraft_action_selector_usage
from cbus_toolkit.project_documentation_bytecraft import bytecraft_body_lines, document_bytecraft


def record(*, mode=0, group=7, selector=11, link=255, on=0, off=0,
           ramp_on=0, ramp_off=0, on_levels=None, off_levels=None):
    values = [0] * 32
    values[:4] = [mode, group, selector, link]
    values[4:6] = [(ramp_on << 4) + ((on >> 8) & 15), on & 255]
    values[6:18] = [255] * 12 if on_levels is None else on_levels
    values[18:20] = [(ramp_off << 4) + ((off >> 8) & 15), off & 255]
    values[20:32] = [128] * 12 if off_levels is None else off_levels
    return values


def unit(*, firmware='1.9.02', scenes=None, **changes):
    parameters = {f'PresetRec{index:02d}': record() for index in range(33)}
    if scenes:
        parameters.update({f'PresetRec{index:02d}': value for index, value in scenes.items()})
    parameters.update(changes)
    return doc.Unit(1, 'Synthetic dimmer', 'DIMPR12', '', '', firmware, '',
        {name: ' '.join(map(str, value)) if isinstance(value, (list, tuple)) else value
         for name, value in parameters.items() if value is not None}, {})


def test_action_preserves_all_matches_zero_based_indexes_and_group_vs_selector_identity():
    u = unit(scenes={0: record(on=1), 1: record(mode=1, selector=88, on=2),
        2: record(mode=1, selector=99, off=1 << 11), 3: record(group=8, on=1),
        4: record(selector=22, on=1), 5: record(selector=11)})
    assert bytecraft_action_selector_usage(u, 202, 7, 11, 22).html == (
        '<li />Trigger Scene 0<li />Advanced Trigger Scene 1<li />Advanced Trigger Scene 2')
    assert bytecraft_action_selector_usage(u, 202, 7, 22, 11).html == (
        '<li />Advanced Trigger Scene 1<li />Advanced Trigger Scene 2<li />Trigger Scene 4')
    assert bytecraft_action_selector_usage(u, 202, 8, 11, 11).html == '<li />Trigger Scene 3'


@pytest.mark.parametrize('mode,advanced', [(0, False), (1, True), (2, False), (255, False)])
def test_exact_mode_and_off_only_usage_even_when_basic_body_suppresses_off_table(mode, advanced):
    u = unit(scenes={32: record(mode=mode, group=255, selector=255, off=1 << 11)})
    result = bytecraft_action_selector_usage(u, 202, 255, 255, 12)
    assert result.status == 'recovered'
    assert result.html == '<li />' + ('Advanced Trigger' if advanced else 'Trigger') + ' Scene 32'
    assert bytecraft_action_selector_usage(u, 202, 255, 12, 255).html == (
        '<li />Advanced Trigger Scene 32' if advanced else '')


def test_action_does_not_consume_body_programming_or_level_value():
    u = unit(scenes={1: record(on=1 << 8)})
    assert bytecraft_action_selector_usage(u, 202, 7, 11, 200).html == '<li />Trigger Scene 1'
    assert bytecraft_action_selector_usage(u, 202, 7, 200, 11).html == ''
    sparse = replace(u, parameters={})
    assert bytecraft_action_selector_usage(sparse, 56, 7, 11, 11).status == 'recovered'
    assert bytecraft_action_selector_usage(sparse, 202, 7, 11, 11).status == 'unrecovered'


def test_action_dispatch_keeps_native_class_gate_and_admits_inherited_l1():
    from cbus_toolkit.project_documentation_usage import action_selector_usage
    u = unit(scenes={0: record(on=1)})
    assert action_selector_usage(u, 'BytecraftDimmer', 202, 7, 11, 0).html == '<li />Trigger Scene 0'
    assert action_selector_usage(unit(firmware='1.9.03', scenes={0: record(on=1)}), 'BytecraftDimmer', 202, 7, 11, 99).html == '<li />Trigger Scene 0'


def test_input_dependencies_are_channel_major_use_on_or_off_and_one_based_scene_labels():
    from cbus_toolkit.project_documentation_usage import group_usage
    u = unit(Application=[56], GroupAddress=[8, 8] + [255] * 10,
        scenes={0: record(on=3), 1: record(group=255, off=1),
                2: record(mode=0, off=2), 32: record(on=1 << 11)})
    result = group_usage(u, 56, 8, 'input')
    assert result.status == 'recovered'
    assert result.html == 'Scene 1<br/>Scene 2 (Unused)<br/>Scene 1<br/>Scene 3'
    assert group_usage(u, 56, 255, 'input').html == 'Scene 33'
    assert group_usage(replace(u, parameters={'Application': '56'}), 202, 8, 'input').status == 'recovered'
    assert group_usage(replace(u, parameters={'Application': '56'}), 56, 8, 'input').status == 'unrecovered'
    no_scene_read = replace(u, parameters={'Application': '56', 'GroupAddress': ' '.join(['8'] * 12)})
    assert group_usage(no_scene_read, 56, 99, 'input').status == 'recovered'
    assert group_usage(no_scene_read, 56, 99, 'input').html == ''
    assert group_usage(no_scene_read, 56, 8, 'input').status == 'unrecovered'


def test_other_dependencies_preserve_area_then_enable_groups_including_unused_identity():
    from cbus_toolkit.project_documentation_usage import group_usage
    u = unit(Application=[203], AreaGroupAddress=[255], CBusDisableGroupAddress=[255],
             DMXCBusSwitchAddress=[255])
    u = replace(u, parameters={name: value for name, value in u.parameters.items() if not name.startswith('PresetRec')})
    result = group_usage(u, 203, 255, 'other')
    assert (result.status, result.html) == ('recovered', 'Area Group<br/>C-Bus Disable Group<br/>DMX Switch')
    u.parameters.pop('AreaGroupAddress')
    result = group_usage(u, 203, 255, 'other')
    assert result.status == 'partial' and result.html == 'C-Bus Disable Group<br/>DMX Switch'
    assert 'AreaGroupAddress' in result.missing[0]
    assert group_usage(unit(Application=[56]), 202, 255, 'other').status == 'recovered'


@pytest.mark.parametrize('parameter,value', [('PresetRec00', None), ('PresetRec32', [0] * 31),
    ('PresetRec15', [256] + [0] * 31), ('PresetRec08', 'invalid')])
def test_actions_refuse_missing_or_invalid_packed_records(parameter, value):
    result = bytecraft_action_selector_usage(unit(**{parameter: value}), 202, 7, 11, 11)
    assert result.status == 'unrecovered' and result.html == ''
    assert parameter in result.missing[0]


def network():
    return doc.Network(254, 'Synthetic', '', '', [
        doc.Application(56, 'Lighting', '', [doc.Group(8, 'Load<&>', '', []),
            doc.Group(9, 'Other load', '', []), doc.Group(255, '<Unused>', '', [])]),
        doc.Application(202, 'Trigger', '', [doc.Group(7, 'Mode', '', [
            doc.Level(11, 'Eleven<&>', 99), doc.Level(99, 'Ninety-nine', 11)]),
            doc.Group(255, '<Unused>', '', [doc.Level(255, 'Unused selector', 255)])]),
        doc.Application(203, 'Enable', '', [doc.Group(20, 'Lock', '', []),
            doc.Group(21, 'DMX', '', []), doc.Group(255, '<Unused>', '', [])]),
    ], [])


def complete_body_unit(**changes):
    switches = [0] * 16
    switches[7] = switches[9] = 1  # rotated bits15 restore and1 Update
    locks = [0] * 16
    locks[8] = 1  # rotated bit0
    fields = dict(Application=[56], GroupAddress=[8, 9] + [255] * 10,
        CBusDisableGroupAddress=[20], DMXCBusSwitchAddress=[21],
        DMXCbusSwitchOverActionAndRestoreMode=switches, CBusDisable=locks,
        DMXPatchInfo=[0, 0, 255, 255, 0, 17] + [0] * 18,
        ChannelDimmerCurve=[0x50] + [0] * 5,
        ChannelMinLevel=[64, 254] + [0] * 10, ChannelMaxLevel=[255] * 12,
        MaxChannelVoltage=[0, 230] + [255] * 10,
        CbusDMXSwitchOverFadeTime=[0x10, 0x0F] + [0] * 4,
        DMXCbusSwitchOverFadeTime=[0x32, 0x04] + [0] * 4,
        scenes={0: record(on=1, ramp_on=2, on_levels=[64] * 12),
            1: record(on=1, off=2, ramp_on=1, ramp_off=15),
            2: record(mode=1, on=4, off=1, ramp_on=10, ramp_off=15),
            32: record(off=1 << 11)})
    fields.update(changes)
    return unit(**fields)


def test_body_native_prefix_tags_column_gates_text_bits_and_enable_group_identity():
    lines = bytecraft_body_lines(network(), complete_body_unit())
    assert lines[:4] == [
        'C-Bus Lock Enable Group: <a href="#254_203_20">Lock</a><br />',
        'DMX Enable Group: <a href="#254_203_21">DMX</a><br />',
        'Control Failure Scene: Enabled<br />', 'Control Failure Scene Ramp Rate: 8 s<br />']
    assert lines[6] == ('</tr><tr><th>Channel</th><th>Groups</th><th>Logic Function</th><th>Curve</th>'
        '<th>Min</th><th>Max</th><th>C-Bus Lock</th><th>Max RMS Voltage</th><th>DMX</th>'
        '<th>Take|Update</th><th>C-Bus Fade</th><th>DMX Fade</th><th>Restore Level</th>')
    assert lines[7] == ('</tr><tr><td>1</td><td><a href="#254_56_8">Load<&></a></td><td>&nbsp;</td>'
        '<td>Lite 1</td><td>25%</td><td>100%</td><td>Yes</td><td>LINE</td>'
        '<td>&#60;Unused&#62;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>25%</td>')
    assert '<td>1:1</td><td>100%</td><td>100%</td><td>No</td><td>230</td>' in lines[8]
    assert '<td>65535</td><td>Update</td><td>4 s</td><td>12 s</td>' in lines[8]
    assert lines[9].startswith('</tr><tr><td>3</td><td>&#60;Unused&#62;</td>')
    assert '<td>17</td><td>Take</td><td>17 min</td><td>20 s</td>' in lines[9]
    assert not any(line.startswith('</tr><tr><td>4</td>') for line in lines)
    assert lines[12] == '<table border="1"'  # source deliberately omits >


def test_scene_tables_exclude_zero_preserve_empty_tables_and_basic_off_suppression():
    lines = bytecraft_body_lines(network(), complete_body_unit())
    assert '<tr><td>0</td>' not in lines
    assert '<tr><td>1</td>' in lines and '<tr><td>2</td>' in lines and '<tr><td>32</td>' in lines
    one = lines[lines.index('<tr><td>1</td>'):lines.index('<tr><td>2</td>')]
    assert one[:3] == ['<tr><td>1</td>', '<td>Basic</td>', '<td><a href="#254_202_7_11">Eleven<&></a></td>']
    assert one[-2:] == ['<td>&nbsp;</td>', '</tr>']  # off inclusion ignored in basic mode
    assert any('<td>100%</td><td>4 s</td></tr>' in line for line in one)
    two = lines[lines.index('<tr><td>2</td>'):lines.index('<tr><td>32</td>')]
    assert two[2] == '<td><a href="#254_202_7">Mode</a></td>'
    assert two[3:7] == ['<td><table border="1">',
        '<tr><th>Group</th><th>Level</th><th>Ramp Rate</th></tr>', '</table>', '</td>']
    assert '<td>50%</td><td>17 min</td></tr>' in two[9]
    last = lines[lines.index('<tr><td>32</td>'):]
    assert last[-4:] == ['<td>&nbsp;</td>', '<td>&nbsp;</td>', '</tr>', '</table>']


def test_all_unused_body_omits_unconsumed_curves_lock_fades_and_levels():
    u = unit(Application=[56], GroupAddress=[255] * 12, CBusDisableGroupAddress=[255],
        DMXCBusSwitchAddress=[255], DMXCbusSwitchOverActionAndRestoreMode=[0] * 16,
        DMXPatchInfo=[0] * 24, ChannelDimmerCurve='invalid', CBusDisable='invalid',
        CbusDMXSwitchOverFadeTime='invalid', MaxChannelVoltage='invalid')
    lines = bytecraft_body_lines(network(), u)
    assert lines[:3] == ['C-Bus Lock Enable Group: &#60;Unused&#62;<br />',
        'DMX Enable Group: &#60;Unused&#62;<br />', 'Control Failure Scene: Disabled<br />']
    assert not any('Restore Level' in line or '<th>DMX</th>' in line or '<th>C-Bus Lock</th>' in line for line in lines)
    assert not any(line.startswith('</tr><tr><td>') for line in lines)


@pytest.mark.parametrize('field,value', [('Application', None), ('DMXPatchInfo', [0] * 23),
    ('ChannelDimmerCurve', [6] + [0] * 5), ('ChannelMinLevel', None),
    ('CBusDisable', [0] * 15), ('DMXCbusSwitchOverActionAndRestoreMode', [0] * 15),
    ('CbusDMXSwitchOverFadeTime', None)])
def test_missing_consumed_body_fields_refuse_atomic_tables(field, value):
    out = doc._Writer()
    assert document_bytecraft(out, network(), complete_body_unit(**{field: value})) == 'partial'
    assert not any(line.startswith('<table') for line in out.lines)
    assert field in out.unrecovered[0]['item']


def test_body_requires_actual_trigger_address_metadata_and_l1_logic_fields():
    net = network()
    net.application(202).group(7).levels = [doc.Level(99, 'Same value, wrong Address', 11)]
    out = doc._Writer()
    assert document_bytecraft(out, net, complete_body_unit()) == 'partial'
    assert 'Level 11' in out.unrecovered[0]['item']
    out = doc._Writer()
    assert document_bytecraft(out, network(), complete_body_unit(firmware='1.9.03')) == 'partial'
    assert 'LogicGroupAddress' in out.unrecovered[0]['item']


@pytest.mark.parametrize('bits', ['0  ' + '0 ' * 15, '00 ' + '0 ' * 15, '0\t' + '0 ' * 15])
def test_bit_text_canonical_shape_is_not_replaced_with_numeric_array_inference(bits):
    out = doc._Writer()
    assert document_bytecraft(out, network(), complete_body_unit(CBusDisable=bits)) == 'partial'
    assert 'canonical text bits' in out.unrecovered[0]['item']


def test_full_report_dispatch_uses_bounded_bytecraft_body_without_promoting_parity():
    net, u = network(), complete_body_unit(AreaGroupAddress=[8])
    net.units = [u]
    text, summary = doc.render(doc.ProjectModel('Synthetic', [net]), generated=datetime(2026, 9, 30))
    assert summary['units'][0]['documentor'] == 'TBytecraftDimmerDocumentor'
    assert summary['units'][0]['status'] == 'recovered'
    assert 'C-Bus Lock Enable Group' in text and 'Scenes: <br />' in text
    assert summary['unrecovered']  # intentionally missing calculator/status fields


def test_body_source_receipt_pins_consumed_fields_and_quirks():
    fixture = Path(__file__).parents[1] / 'research/fixtures/project-documentor-bytecraft-body-static.json'
    receipt = json.loads(fixture.read_text())
    assert len(receipt['checks']) == 122 and all(receipt['checks'].values())
    assert len(receipt['methods']) == 34
    assert receipt['original_execution'] == 'not_executed'
    assert receipt['original_generated_page_comparison'] == 'not_obtained'


def test_body_source_receipt_reproduces_when_configured():
    source = os.environ.get('CBUS_TOOLKIT_EXE')
    if not source:
        pytest.skip('Set CBUS_TOOLKIT_EXE for the old Bytecraft body source comparison')
    root = Path(__file__).parents[1]
    sys.path.insert(0, str(root / 'research'))
    from project_documentor_bytecraft_body_static import inspect
    exe = Path(source)
    result = inspect(exe, Path(os.environ.get('CBUS_TOOLKIT_MAP', exe.with_suffix('.map'))))
    assert result == json.loads((root / 'research/fixtures/project-documentor-bytecraft-body-static.json').read_text())


def test_cli_complete_bytecraft_and_modify_software_smoke_receipt(tmp_path):
    from cbus_toolkit.cli import main
    from test_project_documentation import application, group, network as xml_network, unit as xml_unit, xml
    from test_project_documentation_neoclassic_modify_consumers import modify
    from test_project_documentation_neoclassic_usage import scene_pp
    units = []
    for address, typ in enumerate(('KEYC1', 'KEYC2', 'KEYC4', 'KEYCIR1', 'KEYCIR4'), 1):
        u = modify(typ, indexes=tuple(range(8)))
        u.parameters.update({name: ' '.join(map(str, values)) for name, values in scene_pp().items()})
        units.append(xml_unit(address, typ, firmware=u.firmware, pps=u.parameters.items()))
    for address, firmware in ((6, '1.9.02'), (7, '1.9.03')):
        u = complete_body_unit(firmware=firmware, AreaGroupAddress=[8])
        units.append(xml_unit(address, u.unit_type, firmware=firmware, pps=u.parameters.items()))
    apps = [application(app.address, app.name, tuple(group(g.address, escape(g.name),
        tuple((level.address, escape(level.name)) for level in g.levels)) for g in app.groups))
        for app in network().applications]
    source, target = tmp_path / 'synthetic.xml', tmp_path / 'report.html'
    source.write_bytes(xml((xml_network(254, 'Synthetic', apps=apps, units=units, interface=('None', '')),), name='Synthetic'))
    captured = StringIO()
    with redirect_stdout(captured):
        status = main(['project', 'document', str(source), '--output', str(target), '--generated-at', '2026-09-30T12:00:00'])
    result = json.loads(captured.getvalue())
    raw = target.read_bytes()
    report = raw.decode('utf-8-sig')
    assert status == 0 and raw.startswith(b'\xef\xbb\xbf') and b'\n' not in raw.replace(b'\r\n', b'')
    assert report.count('<td>&#60;Scene Modify&#62;</td><td>&nbsp;</td>') == 40
    assert '<td>65535</td><td>Update</td><td>4 s</td><td>12 s</td>' in report
    assert '<li />Trigger Scene 0<li />Trigger Scene 1<li />Advanced Trigger Scene 2<li />Trigger Scene 32' in report
    assert len([row for row in result['units'] if row['status'] == 'recovered']) == 6
    assert result['units'][-1]['status'] == 'partial'
    receipt = {'format': 'cbus-documentor-bytecraft-modify-software-smoke-v1', 'cli_exit': status,
        'synthetic_units': len(units), 'recovered_bodies': 6, 'scene_modify_controls': 40,
        'old_bytecraft_body': 'recovered', 'l1_body': 'partial',
        'original_toolkit_executed': result['parity']['original_toolkit_executed'],
        'byte_parity': result['parity']['byte_parity'], 'visual_parity': result['parity']['visual_parity'],
        'remaining_marker_count': len(result['unrecovered']), 'encoding': 'UTF-8 BOM and CRLF',
        'original_generated_page_comparison': 'not_obtained'}
    fixture = Path(__file__).parents[1] / 'research/experiments/2026-09-30/project-documentor-bytecraft-modify-software-smoke.json'
    historical = json.loads(fixture.read_text())
    assert historical['remaining_marker_count'] == 37
    # Unit7's inherited L1 scene/action consumers now recover. The incomplete
    # body/output fixture still refuses its missing logic list. Keep this check
    # scoped to that unit instead of binding unrelated report marker counts.
    missing_logic = 'LogicGroupAddress (requires 1 explicit values in 0..255)'
    expected_l1 = [{'network': 254, 'unit': 7, 'item': f'Group output usage ({app}/{group})',
                    'missing': [missing_logic]} for app, group in ((56, 8), (56, 9), (203, 20), (203, 21))]
    expected_l1.append({'network': 254, 'unit': 7, 'item': 'Bytecraft controls: ' + missing_logic})
    assert [row for row in result['unrecovered'] if row['unit'] == 7] == expected_l1
    assert {k: v for k, v in receipt.items() if k != 'remaining_marker_count'} == {
        k: v for k, v in historical.items() if k != 'remaining_marker_count'}
