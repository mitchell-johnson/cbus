"""Canonical encoded KEYC/CIR Scene24 consumers and explicit excluded transitions."""
from dataclasses import replace
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sys

import pytest

from cbus_toolkit import project_documentation_neoclassic as classic
from cbus_toolkit import project_documentation_neo as neo
from cbus_toolkit.macros import STAGES
from cbus_toolkit.project_documentation_neoclassic_usage import (
    neoclassic_action_selector_usage, neoclassic_group_usage,
)
from test_project_documentation_neo import bind_scene, network, pp, unit
from test_project_documentation_neoclassic import body
from test_project_documentation_neoclassic_usage import scene_pp

ROOT = Path(__file__).parents[1]
RECEIPT = ROOT / 'research/experiments/2026-09-30/project-documentor-neoclassic-scene-static.json'


def encoded(typ='KEYC4', keys=(2, 7), scene=1, ramp=2, selector=66):
    values = pp()
    for key in keys:
        bind_scene(values, key, scene, ramp, selector)
    return unit(values, typ, '1.8.01')


@pytest.mark.parametrize('typ', classic.NEOCLASSIC_TYPES)
def test_scene24_matches_accepted_shared_neo_key_graph_and_classic_body(typ):
    u = encoded(typ)
    actual = classic.neoclassic_data(u)
    expected = neo.neo_data(u, classic.neoclassic_profile(u))
    assert actual.keys == expected.keys and actual.blocks == expected.blocks
    assert neo.neo_body_lines(network(), actual, include_scenes=False) == neo.neo_body_lines(
        network(), expected, include_scenes=False)
    out, status = body(u)
    assert status == 'recovered' and not out.unrecovered
    rows = [line for line in out.lines if line.startswith('<tr><td>')]
    assert len(rows) == 8
    for index in (2, 7):
        key = actual.keys[index]
        assert (key.macro_type, key.macro_label, key.commands) == (24, 'Scene', (0, 0, 0, 0))
        assert (key.scene_index, key.scene_ramp, key.scene_trigger) == (1, 2, 66)
        assert '<td>Scene 2</td><td>8 secs</td>' in rows[index]
    assert 'Scenes<br />' not in out.lines
    assert not any('254_202_9_66' in line for line in rows)


@pytest.mark.parametrize('scene,ramp,selector', [(0, 0, 0), (7, 15, 255), (4, 10, 67)])
def test_scene_number_ramp_and_trigger_decode_edges_without_unconsumed_fields(scene, ramp, selector):
    u = encoded(scene=scene, ramp=ramp, selector=selector)
    u = replace(u, parameters={name: value for name, value in u.parameters.items()
        if name not in (*neo.JOIN_PARAMETERS, 'SceneTable', 'SceneTablePointer',
                        'ControlAppGroupAddress', 'KeyMask')})
    data = classic.neoclassic_data(u)
    assert (data.keys[7].scene_index, data.keys[7].scene_ramp, data.keys[7].scene_trigger) == (scene, ramp, selector)
    assert body(u)[1] == 'recovered'
    assert neoclassic_action_selector_usage(u, 56, 255, selector, selector).status == 'recovered'
    result = neoclassic_group_usage(u, 56, 255, 'input')
    assert result.status == 'partial' and result.missing == ('SceneTable (requires explicit byte values)',)


@pytest.mark.parametrize('parameter,value', [
    ('BlockAllocation', '3 2 0 0 0 0 0 0'),
    ('BlockAllocation', '1 1 0 0 0 0 0 0'),
    ('GroupAddress', '1 2 255 255 255 255 255 255 255'),
    ('SecondApplicationBlocks', '1'),
])
def test_modify_or_noncanonical_graph_refuses_atomic_body_and_usage(parameter, value):
    u = encoded(keys=(0,))
    params = dict(u.parameters)
    if value is None:
        params.pop(parameter)
    else:
        params[parameter] = value
    u = replace(u, parameters=params)
    out, status = body(u)
    assert status == 'partial' and not any(line.startswith('<table') for line in out.lines)
    assert neoclassic_group_usage(u, 56, 255, 'input').status == 'unrecovered'
    assert neoclassic_action_selector_usage(u, 56, 255, 0, 0).status == 'unrecovered'
    # Native independent consumers never visit the encoded key branch here.
    assert neoclassic_group_usage(u, 56, 255, 'output').status == 'recovered'
    assert neoclassic_action_selector_usage(u, 202, 255, 0, 0).status == 'recovered'


@pytest.mark.parametrize('indicators', [None, '0 0 0 0 0 0 0 8', '0 0'])
def test_missing_scene_indexes_affect_extension_consumers_only(indicators):
    u = encoded('KEYC4', keys=(7,))
    if indicators is None:
        u.parameters.pop('IndicatorBlockAssignment')
    else:
        u.parameters['IndicatorBlockAssignment'] = indicators
    assert body(u)[1] == 'partial'
    # Empty primary scene commands and a secondary scan never visit scene refs.
    assert neoclassic_group_usage(u, 56, 255, 'input').status == 'recovered'
    assert neoclassic_group_usage(u, 202, 255, 'input').status == 'recovered'
    assert neoclassic_action_selector_usage(u, 56, 255, 0, 0).status == 'recovered'
    u.parameters.update({name: ' '.join(map(str, values)) for name, values in scene_pp().items()})
    result = neoclassic_group_usage(u, 56, 1, 'input')
    assert result.status == 'partial' and result.html == 'Key 1'
    assert 'IndicatorBlockAssignment' in result.missing[0]


def test_mixed_ordinary_indicator_slots_are_not_consumed_for_scene_references():
    u = encoded(keys=(2, 7))
    u.parameters['IndicatorBlockAssignment'] = '255 -1 1 255 255 255 255 1'
    assert body(u)[1] == 'recovered'
    u.parameters.update({name: ' '.join(map(str, values)) for name, values in scene_pp().items()})
    assert neoclassic_group_usage(u, 56, 8, 'input').html == 'Scene 1<br/>Scene 2'


@pytest.mark.parametrize('typ,physical', [('KEYC1', 1), ('KEYC2', 2), ('KEYC4', 4),
                                        ('KEYCIR1', 0), ('KEYCIR4', 4)])
def test_all_encoded_keys_reference_actual_scene_including_virtual_keys(typ, physical):
    u = encoded(typ, keys=tuple(range(8)))
    u.parameters.update({name: ' '.join(map(str, values)) for name, values in scene_pp().items()})
    blocks = neoclassic_group_usage(u, 56, 255, 'input')
    assert blocks.status == 'recovered'
    assert blocks.html.split('<br/>') == [f'Key {key + 1}' for key in range(physical)] + ['Block (Unused)'] * (8 - physical)
    scenes = neoclassic_group_usage(u, 56, 8, 'input')
    assert (scenes.status, scenes.html) == ('recovered', 'Scene 1 (Unused)<br/>Scene 2')
    # Classic actions consume template24's idle commands, and have no Neo
    # scene-trigger pass even when the primary application itself is Trigger.
    u.parameters['Application'] = '202 56'
    u.parameters['ControlAppGroupAddress'] = '255'
    u.parameters['LightLevelStore1'] = ' '.join(['66'] * 8)
    assert neoclassic_action_selector_usage(u, 202, 255, 66, 66).html == ''


def test_scene_reference_usage_is_independent_of_body_timings_presets_and_trigger_binding():
    u = encoded('KEYCIR1', keys=(7,))
    u.parameters.update({name: ' '.join(map(str, values)) for name, values in scene_pp().items()})
    for field in ('DebounceTime', 'LongPressTime', 'RampRate', 'TimerHighByte', 'TimerLowByte',
                  'LightLevelStore1', 'LightLevelStore2', 'TimerExpiryCommand', 'ControlAppGroupAddress'):
        u.parameters.pop(field)
    result = neoclassic_group_usage(u, 56, 8, 'input')
    assert (result.status, result.html) == ('recovered', 'Scene 1<br/>Scene 2')
    assert body(u)[1] == 'partial'


def test_mixed_scene_and_ordinary_action_keys_preserve_classic_address_gate_and_order():
    u = encoded('KEYCIR1', keys=(7,))
    u.parameters['Application'] = '202 56'
    u.parameters['GroupAddress'] = '8 8 255 255 255 255 255 255 255'
    u.parameters['LightLevelStore1'] = '11 11 0 0 0 0 0 0'
    u.parameters['LightLevelStore2'] = '22 22 0 0 0 0 0 0'
    for stage, value in zip(STAGES, (12, 6, 0, 0)):
        values = u.array(stage)
        values[:2] = [value, value]
        u.parameters[stage] = ' '.join(map(str, values))
    assert neoclassic_action_selector_usage(u, 202, 8, 11, 22).html == 'Key 1<br/>Key 1<br/>Key 2<br/>Key 2'
    assert neoclassic_action_selector_usage(u, 202, 8, 99, 22).html == ''


def test_scene_transition_source_receipt_preserves_modify_prerequisites():
    receipt = json.loads(RECEIPT.read_text())
    assert len(receipt['checks']) == 15 and all(receipt['checks'].values())
    assert receipt['original_executed'] is False
    for name, checks in receipt['contract']['supporting_receipt_checks'].items():
        support = json.loads((RECEIPT.parent / name).read_text())
        assert all(support['checks'][check] for check in checks)
    assert receipt['checks']['modify_final_indicator_only']


def test_scene_transition_source_receipt_reproduces_when_configured():
    source = os.environ.get('CBUS_TOOLKIT_EXE')
    if not source:
        pytest.skip('Set CBUS_TOOLKIT_EXE for the encoded KEYC/CIR source comparison')
    sys.path.insert(0, str(ROOT / 'research'))
    from project_documentor_neoclassic_scene_static import inspect
    exe = Path(source)
    assert inspect(exe, Path(os.environ.get('CBUS_TOOLKIT_MAP', exe.with_suffix('.map')))) == json.loads(RECEIPT.read_text())


def test_source_cli_encoded_and_bytecraft_smoke_receipt(tmp_path):
    from cbus_toolkit.cli import main
    from test_project_documentation import application, group, network as xml_network, unit as xml_unit, xml
    units = []
    for address, typ in enumerate(classic.NEOCLASSIC_TYPES, 1):
        u = encoded(typ, keys=tuple(range(8)))
        u.parameters.update({name: ' '.join(map(str, values)) for name, values in scene_pp().items()})
        units.append(xml_unit(address, typ, firmware=u.firmware, pps=u.parameters.items()))
    for address, firmware in ((6, '1.9.02'), (7, '1.9.03')):
        units.append(xml_unit(address, 'DIMPR12', firmware=firmware,
            pps=(('Application', '56'), ('GroupAddress', '8 9 8 255 10 11 12 13 14 15 16 8'))))
    apps = (application(56, 'Lighting', (group(8, 'Synthetic load'), group(9, 'Other load'))),
            application(202, 'Trigger', (group(9, 'Synthetic scene', ((66, 'Selector'),)),)))
    source, target = tmp_path / 'synthetic.xml', tmp_path / 'report.html'
    source.write_bytes(xml((xml_network(254, 'Synthetic', apps=apps, units=units, interface=('None', '')),), name='Synthetic'))
    captured = StringIO()
    with redirect_stdout(captured):
        status = main(['project', 'document', str(source), '--output', str(target),
                       '--generated-at', '2026-09-30T12:00:00'])
    result = json.loads(captured.getvalue())
    raw = target.read_bytes()
    report = raw.decode('utf-8-sig')
    assert status == 0 and raw.startswith(b'\xef\xbb\xbf')
    assert b'\r\n' in raw and b'\n' not in raw.replace(b'\r\n', b'')
    assert report.count('<td>Scene 2</td><td>8 secs</td>') == 40
    assert 'Channel 1<br/>Channel 3<br/>Channel 12' in report
    assert 'Scene 1 (Unused)<br/>Scene 2' in report
    recovered = [row for row in result['units'] if row['status'] == 'recovered']
    assert len(recovered) == 5 and all(row['unit_type'] in classic.NEOCLASSIC_TYPES for row in recovered)
    receipt = {'format': 'cbus-documentor-encoded-bytecraft-software-smoke-v1', 'cli_exit': status,
        'synthetic_units': len(units), 'recovered_scene_bodies': len(recovered), 'scene_controls': 40,
        'old_bytecraft_output': 'Channel 1<br/>Channel 3<br/>Channel 12',
        'original_toolkit_executed': result['parity']['original_toolkit_executed'],
        'byte_parity': result['parity']['byte_parity'], 'visual_parity': result['parity']['visual_parity'],
        'remaining_marker_count': len(result['unrecovered']), 'encoding': 'UTF-8 BOM and CRLF',
        'original_generated_page_comparison': 'not_obtained'}
    assert receipt == json.loads((RECEIPT.parent / 'project-documentor-encoded-bytecraft-software-smoke.json').read_text())
