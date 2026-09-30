"""SCNCTL5 bounded saved-snapshot documentor; synthetic data only."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_scene_controller as sc

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "research/experiments/2026-09-30/project-documentor-scene-controller-static.json"
ORIGINAL = ROOT / "research/fixtures/project-documentor-scene-controller-original.json"


def snapshot(**updates):
    parameters = {"Application": [56], "AreaGroupAddress": [9], "ControlAppGroupAddress": [8],
                  "MasterOffTriggerLevel": [11], "MasterOffRampRate": [5], "MasterOffCustomRampRate": [7],
                  "PrimaryGroupAddress": [1, 255, 1], "PrimaryGroupAddressLevel": [0, 128, 255] * 5,
                  "SceneTriggerLevel": [11, 22, 11, 44, 55], "SceneRampRate": [0, 1, 2, 3, 4],
                  "SceneCustomRampRate": [13], "SecondaryMasterOffEnabled": [0, 1, 0, 1, 0, 1] * 5,
                  **{f"Scene{n}SecondaryGroupTable": [120, 2, 128] + [0, 255, 0] * 5 for n in range(1, 6)}}
    parameters.update(updates)
    return doc.Unit(3, "Scenes", "SCNCTL5", "", "", "1.2.00", "",
                    {k: " ".join(map(str, v)) for k, v in parameters.items() if v is not None}, {})


def network():
    return doc.Network(254, "", "", "", [
        doc.Application(56, "Lighting", "", [doc.Group(n, f"Group <{n}>", "", []) for n in (1, 2, 9)]),
        doc.Application(202, "Triggers", "", [doc.Group(8, "Control", "", [
            doc.Level(n, f"Action <{n}>", 255 - n) for n in (11, 22, 44, 55)]),
            doc.Group(255, "<Unused>", "", [])])], [])


def test_loader_preserves_shared_primary_and_secondary_order_and_rate_fields():
    data = sc.scene_controller_data(snapshot())
    assert (data.application, data.control_group, data.master_selector, data.master_ramp) == (56, 8, 11, 7)
    assert len(data.scenes) == 5 and all(len(row) == 9 for row in data.scenes)
    for row in data.scenes:
        assert [command.group for command in row] == [1, 255, 1, 2, 255, 255, 255, 255, 255]
        assert [command.ramp for command in row] == [13, 13, 13, 15, 0, 0, 0, 0, 0]
        assert [command.master_off for command in row] == [True, True, True, False, True, False, True, False, True]


def test_body_format_names_address_lookup_and_final_line():
    out = doc._Writer()
    assert sc.document_scene_controller(out, network(), snapshot()) == "recovered"
    start = out.lines.index('Control Group: <a href="#254_202_8">Control</a><br />')
    lines = out.lines[start:]
    assert lines[:6] == ['Control Group: <a href="#254_202_8">Control</a><br />',
        'Master Off Action Selector: Action <11><br />', 'Master Off Ramp Rate: 60 secs<br />',
        '<br />', '<table border="1">', '<tr><th>Scene</th><th>Trigger</th><th>Controls</th></tr>']
    assert '<td><a href="#254_202_8_11">Action <11></a></td>' in lines
    assert '<tr><td><a href="#254_56_1">Group <1></a></td><td>100%</td><td>600 secs</td><td>Yes</td></tr>' in lines
    assert '<tr><td><a href="#254_56_2">Group <2></a></td><td>50%</td><td>1020 secs</td><td>No</td></tr>' in lines
    assert lines[-2:] == ['</table></td></tr>', '</table>']
    assert not out.unrecovered


def test_unused_control_hides_trigger_cells_but_uses_original_group_name():
    data = sc.scene_controller_data(snapshot(ControlAppGroupAddress=[255]))
    lines = sc.scene_controller_lines(network(), data)
    assert lines[0] == 'Control Group: &#60;Unused&#62;<br />'
    assert '<tr><th>Scene</th><th>Controls</th></tr>' in lines
    assert not any('Action Selector' in line or '_202_' in line for line in lines)


def test_unused_scenes_skipped_even_with_nonempty_selectors_and_levels():
    unit = snapshot(PrimaryGroupAddress=[255] * 3, **{
        f"Scene{n}SecondaryGroupTable": [0, 255, 255] * 6 for n in range(1, 6)})
    lines = sc.scene_controller_lines(network(), sc.scene_controller_data(unit))
    assert len(lines) == 7 and lines[-1] == '</table>'
    assert sc.scene_controller_action_usage(unit, 202, 8, 11, 244).html == 'Scene Master Off'


def test_actions_match_address_ignore_value_keep_duplicates_and_unused_control():
    unit = snapshot()
    assert sc.scene_controller_action_usage(unit, 202, 8, 11, 22).html == (
        'Scene Master Off<br />Triggers Scene 1<br />Triggers Scene 3')
    assert sc.scene_controller_action_usage(unit, 202, 8, 22, 11).html == 'Triggers Scene 2'
    assert sc.scene_controller_action_usage(unit, 56, 8, 11, 11).html == ''
    assert sc.scene_controller_action_usage(unit, 202, 9, 11, 11).html == ''
    unit.parameters['ControlAppGroupAddress'] = '255'
    assert sc.scene_controller_action_usage(unit, 202, 255, 11, 11).html.startswith('Scene Master Off')


def test_dependencies_are_per_command_without_deduplication():
    unit = snapshot()
    assert sc.scene_controller_group_usage(unit, 56, 1, 'input').html == '<br/>'.join(
        label for scene in range(1, 6) for label in [f'Scene {scene}'] * 2)
    assert sc.scene_controller_group_usage(unit, 56, 255, 'input').html.count('Scene 1') == 6
    assert sc.scene_controller_group_usage(unit, 202, 8, 'input').html == ''
    assert sc.scene_controller_group_usage(unit, 56, 9, 'other').html == 'Area Group'
    assert sc.scene_controller_group_usage(unit, 56, 1, 'output').html == ''


@pytest.mark.parametrize('value,expected', [(0, 0), (1, 1), (2, 3), (3, 7), (4, 13), (5, 9), (255, 1)])
def test_master_off_dragan_conversion(value, expected):
    assert sc.scene_controller_data(snapshot(MasterOffRampRate=[value], MasterOffCustomRampRate=[9])).master_ramp == expected


@pytest.mark.parametrize('value,expected', [(0, 0), (15, 15), (16, 15), (254, 15), (255, 1)])
def test_generic_custom_ramp_conversion(value, expected):
    assert sc.scene_controller_data(snapshot(SceneCustomRampRate=[value])).scenes[0][0].ramp == expected


@pytest.mark.parametrize('field,value', [('PrimaryGroupAddress', []), ('SceneTriggerLevel', [1]),
    ('MasterOffTriggerLevel', None), ('Scene4SecondaryGroupTable', [0] * 17),
    ('SecondaryMasterOffEnabled', [2] * 30), ('PrimaryGroupAddressLevel', [256] * 15),
    ('MasterOffRampRate', [6]), ('SceneRampRate', [6] * 5)])
def test_missing_invalid_and_native_exception_paths_stay_partial(field, value):
    out = doc._Writer()
    assert sc.document_scene_controller(out, network(), snapshot(**{field: value})) == 'partial'
    assert not any(line.startswith('Control Group:') for line in out.lines)
    assert out.unrecovered


@pytest.mark.parametrize('firmware', ['', 'bad', '10', '9.1', '9' * 5000])
def test_unresolved_factory_identity_not_admitted(firmware):
    unit = snapshot()
    unit.firmware = firmware
    assert not sc.scene_controller_supported(unit)
    assert sc.scene_controller_action_usage(unit, 202, 8, 11, 11).status == 'unrecovered'


def test_missing_group_or_action_metadata_not_auto_created():
    net = network()
    net.applications[1].groups[0].levels = []
    out = doc._Writer()
    assert sc.document_scene_controller(out, net, snapshot()) == 'partial'
    assert 'Level 11' in out.unrecovered[0]['item']
    assert net.applications[1].groups[0].levels == []


def test_usage_does_not_require_unconsumed_timing_and_levels():
    unit = snapshot(MasterOffRampRate=None, SceneRampRate=None, PrimaryGroupAddressLevel=None)
    assert sc.scene_controller_action_usage(unit, 202, 8, 22, 22).status == 'recovered'
    assert sc.scene_controller_group_usage(unit, 56, 1, 'input').status == 'recovered'


def test_source_receipt_boundary():
    receipt = json.loads(STATIC.read_text())
    assert all(receipt['checks'].values())
    assert receipt['original_generated_page_comparison'] == 'not_obtained'
    assert receipt['original_executed'] is False


@pytest.mark.parametrize('index', range(4))
def test_body_actions_and_input_dependencies_match_original_instructions(index):
    case = json.loads(ORIGINAL.read_text())['cases'][index]
    groups = sorted({command[0] for scene in case['scenes'] for command in scene})
    selectors = sorted(set(case['selectors']) | {case['master_selector']})
    net = doc.Network(case['network'], '', '', '', [
        doc.Application(case['application'], '', '', [doc.Group(n, f'Group <{n}>', '', []) for n in groups]),
        doc.Application(202, '', '', [doc.Group(case['control_group'], '<Unused>' if case['control_group'] == 255
                                             else f'Group <{case["control_group"]}>', '',
                                             [doc.Level(n, f'Action <{n}>', 255 - n) for n in selectors])])], [])
    data = sc.SceneControllerData(case['application'], case['control_group'], case['master_selector'],
                                  case['master_ramp'], tuple(case['selectors']),
                                  tuple(tuple(sc.SceneCommand(*command) for command in scene) for scene in case['scenes']))
    assert sc.scene_controller_lines(net, data) == case['lines']
    # Re-encode this synthetic dependency graph into the supported PP adapter.
    # All test scenes fit six secondary slots; unused primary slots preserve the
    # exact total number of unused references for native group255 comparisons.
    parameters = {'Application': [case['application']], 'ControlAppGroupAddress': [case['control_group']],
                  'MasterOffTriggerLevel': [case['master_selector']], 'SceneTriggerLevel': case['selectors'],
                  'PrimaryGroupAddress': [255] * 3}
    for scene, commands in enumerate(case['scenes'], 1):
        used = [command for command in commands if command[0] != 255]
        parameters[f'Scene{scene}SecondaryGroupTable'] = [value for command in used for value in (0, command[0], 0)] + [0, 255, 0] * (6 - len(used))
    unit = snapshot(**parameters)
    for action in case['actions']:
        application, group, address = action['query']
        assert sc.scene_controller_action_usage(unit, application, group, address, 255 - address).html == action['html']
    for item in case['inputs']:
        native = item['native']
        expected = native[:-1].replace('|', '<br/>') if native else ''
        assert sc.scene_controller_group_usage(unit, *item['query'], 'input').html == expected


def test_original_receipt_keeps_loader_and_page_boundary():
    receipt = json.loads(ORIGINAL.read_text())
    assert receipt['original_methods_executed'] is True
    assert receipt['original_loader_executed'] is False
    assert receipt['original_generated_page_compared'] is False
    assert len(receipt['methods']) == 8
    assert receipt['master_selector_format_basis'] == sc.MASTER_SELECTOR_FORMAT_BASIS


def test_original_static_receipt_when_configured():
    exe = os.environ.get('CBUS_TOOLKIT_EXE')
    if not exe:
        pytest.skip('Requires pinned Toolkit EXE/MAP')
    sys.path.insert(0, str(ROOT / 'research'))
    from project_documentor_scene_controller_static import inspect
    assert inspect(Path(exe), Path(os.environ.get('CBUS_TOOLKIT_MAP', str(Path(exe).with_suffix('.map'))))) == json.loads(STATIC.read_text())


def test_original_instruction_receipt_when_explicitly_enabled(tmp_path):
    exe = os.environ.get('CBUS_TOOLKIT_EXE')
    if not exe or os.environ.get('CBUS_RUN_DOCUMENTOR_ORIGINAL') != '1':
        pytest.skip('Requires pinned Toolkit inputs and CBUS_RUN_DOCUMENTOR_ORIGINAL=1')
    output = tmp_path / 'scene.json'
    subprocess.run([sys.executable, str(ROOT / 'research/project_documentor_scene_controller_original.py'),
                    '--exe', exe, '--map', os.environ.get('CBUS_TOOLKIT_MAP', str(Path(exe).with_suffix('.map'))),
                    '--output', str(output)], check=True)
    assert json.loads(output.read_text()) == json.loads(ORIGINAL.read_text())
