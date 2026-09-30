"""Source-bounded PIR tables, usage ordering and missing-data boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_pir as pir

FIXTURES = Path(__file__).parents[1] / 'research/fixtures'


def unit(kind='SENPIRIA', firmware='2.4.00', **changes):
    values = {'Application': [202, 56], 'GroupAddress': [8, 8, 9, 10],
        'BlockAllocation': [3, 1, 4, 8], 'JPCommand': [12, 12, 0, 0], 'SRCommand': [6, 0, 0, 0],
        'LPCommand': [0] * 4, 'LRCommand': [0] * 4, 'DebounceTime': [1], 'LongPressTime': [2],
        'RampRate': [0, 1], 'LightLevelStore1': [11] * 4, 'LightLevelStore2': [22] * 4,
        'TimerHighByte': [0] * 4, 'TimerLowByte': [0] * 4, 'TimerExpiryCommand': [15] * 4,
        'SceneKeySelector': [0] * 4, 'SecondApplicationBlocks': [0], 'SceneTable': [255],
        'EnableGroupAddress': [8], 'EnableGroupLogic': [0], 'PIREnablerGroup': [8],
        'PIREnablerGroupLogic': [0], 'PECEnablerGroup': [8], 'PECFunctionActive': [0],
        'PECFunctionBlock': [2], 'BroadcastBlock': [0], 'CorridorLinkEnablerGroup': [8],
        'ControlAppGroupAddress': [8], 'AreaGroupAddress': [8]}
    values.update(changes)
    return doc.Unit(1, 'PIR', kind, '', '', firmware, '', {key: ' '.join(map(str, value))
        if isinstance(value, (list, tuple)) else value for key, value in values.items() if value is not None}, {})


def network():
    return doc.Network(254, 'Local', '', '', [doc.Application(app, str(app), '', [
        doc.Group(group, 'Unused' if group == 255 else f'G{group}', '', [doc.Level(11, 'Named', 33)])
        for group in (8, 9, 10, 255)]) for app in (56, 202, 203)], [])


@pytest.mark.parametrize('kind,version,st7', [('SENPIRSS', '1.00', False), ('SENPIROA', '1.2.60', False),
    ('SENPIRIA', '2.0.00', False), ('SENPIRIB', '2.0.00', False), ('SENPIROA', '2.0.01', True),
    ('SENPIRIA', '2.4.00', True), ('SENPIRIB', '2.3.09', True)])
def test_native_class_admission(kind, version, st7):
    assert pir.pir_profile(unit(kind, version)) is st7


@pytest.mark.parametrize('kind,version', [('SENPIRIA', '1.0'), ('SENPIROA', '1.2.59'),
    ('SENPIRIB', '2.3.10'), ('SENPIRIB', '2.4.00'), ('SENPIRSS', '2.0.01'),
    ('SENLL', '2.4.00'), ('SENPIRSS', ''), ('SENPIRIA', '9.0.1')])
def test_surface_multisensor_unknown_and_wrong_ranges_stay_unrecovered(kind, version):
    assert pir.pir_group_usage(unit(kind, version), 56, 8, 'output').status == 'unrecovered'


@pytest.mark.parametrize('version,logic,label', [('1.2.60', 0, 'PIR Disable Group: '),
    ('1.2.60', 1, 'PIR Enable Group: '), ('2.4.00', 0, 'PIR Enable Group: '),
    ('2.4.00', 1, 'PIR Disable Group: ')])
def test_enable_polarity_primary_application_and_body_order(version, logic, label):
    u = unit(firmware=version, EnableGroupLogic=[logic], PIREnablerGroupLogic=[logic])
    out = doc._Writer()
    assert pir.document_pir(out, network(), u) == 'recovered'
    assert out.lines[-2:] == ['<br />', label + '<a href="#254_202_8">G8</a><br />']
    assert out.lines.count('Unit Address: 1<br />') == 1
    assert len([line for line in out.lines if line.startswith('<tr><td>')]) == 4
    assert '<a href="#254_202_8_11">Named</a> (5%)' in ''.join(out.lines)


def test_unused_appendix_does_not_consume_polarity_and_missing_body_keeps_known_suffix():
    u = unit(PIREnablerGroup=[255], PIREnablerGroupLogic=None, JPCommand=None)
    out = doc._Writer()
    assert pir.document_pir(out, network(), u) == 'partial'
    assert out.lines[-2:] == ['<br />', 'PIR Enable/Disable Group: Unused<br />']
    assert 'JPCommand' in out.unrecovered[0]['item']


def test_sensor_macros_and_template_event_timer_defaults():
    u = unit(JPCommand=[7, 13, 13, 13], SRCommand=[0, 7, 7, 15], LPCommand=[0, 7, 0, 7],
             LRCommand=[0, 0, 7, 15], BlockAllocation=[1, 2, 4, 8])
    data = pir.pir_data(u)
    assert data.macros == ((31, 'Day Move'), (32, 'Night Move'), (33, 'Any Move'), (34, 'Sunset'))
    assert data.classic.timers == [300] * 4
    assert pir.pir_macro((13, 15, 0, 15), 202, 0, 0) == (7, 'Bell Press')
    assert pir.pir_macro((7, 0, 0, 0), 255, 0, 0) == (26, '<Custom>')


def test_mixed_secondary_block_macro_and_table_identity():
    u = unit(Application=[255, 202], SecondApplicationBlocks=[2], BlockAllocation=[3, 3, 4, 8],
             JPCommand=[7, 7, 0, 0], SRCommand=[0] * 4)
    data = pir.pir_data(u)
    assert data.macros[:2] == ((26, '<Custom>'), (31, 'Day Move'))
    assert data.block_applications == (255, 202, 255, 255)
    assert data.classic.timers == [300, 0, 0, 0]
    out = doc._Writer()
    u = unit(SecondApplicationBlocks=[2])
    assert pir.document_pir(out, network(), u) == 'recovered'
    assert '<a href="#254_56_8">G8</a>' in ''.join(out.lines)


def test_classic_action_only_preserves_duplicates_address_value_and_group_255():
    assert pir.pir_action_selector_usage(unit(), 202, 8, 11, 22).html == 'Key 1<br/>Key 1<br/>Key 1<br/>Key 1<br/>Key 2'
    assert pir.pir_action_selector_usage(unit(), 202, 8, 99, 22).html == ''
    assert pir.pir_action_selector_usage(unit(), 202, 8, 11, 99).html == 'Key 1<br/>Key 1<br/>Key 2'
    assert pir.pir_action_selector_usage(unit(Application=[56, 202], SecondApplicationBlocks=[3]), 202, 8, 11, 22).html == ''
    u = unit(Application=[202, 202])
    assert pir.pir_action_selector_usage(u, 202, 8, 11, 22).html.count('Key 2') == 1
    u = unit(GroupAddress=[255] * 4, LightLevelStore1=[255] * 4)
    assert pir.pir_action_selector_usage(u, 202, 255, 255, 22).html.startswith('Key 1<br/>Key 1')


def test_input_block_major_maintenance_and_empty_scene_boundary():
    assert pir.pir_group_usage(unit(), 202, 8, 'input').html == 'Key 1<br/>Key 2<br/>Key 1'
    assert pir.pir_group_usage(unit(PECFunctionActive=[1]), 202, 9, 'input').html == 'Light Level Maintenance'
    assert pir.pir_group_usage(unit(), 202, 9, 'input').html == 'Block (Unused)'
    result = pir.pir_group_usage(unit(SceneTable=[8, 99]), 202, 8, 'input')
    assert (result.html, result.status) == ('Key 1<br/>Key 2<br/>Key 1', 'partial')
    assert pir.pir_group_usage(unit(SceneTable=None), 202, 8, 'input').status == 'partial'
    assert pir.pir_group_usage(unit(firmware='1.2.60', SceneTable=None, PECFunctionActive=None), 202, 8, 'input').status == 'recovered'
    assert pir.pir_group_usage(unit(SceneTable=None), 56, 8, 'input').status == 'recovered'


def test_other_native_order_unsupported_brightness_and_disabled_broadcast_still_used():
    expected = ('Area Group<br/>Corridor Link Group<br/>Control App Group<br/>'
        'Light Level Maintenance Enable<br/>Occupancy Enable<br/>Corridor Link<br/>Light Level Broadcast Group')
    assert pir.pir_group_usage(unit(BroadcastActive=[0]), 202, 8, 'other').html == expected
    assert pir.pir_group_usage(unit(), 203, 255, 'other').html == 'Key Disable Group'
    assert pir.pir_group_usage(unit(firmware='1.2.60'), 202, 8, 'other').html == 'Area Group<br/>PIR Enable Group'
    u = unit(SecondApplicationBlocks=[1])
    assert pir.pir_group_usage(u, 56, 8, 'other').html == 'Light Level Broadcast Group'
    result = pir.pir_group_usage(unit(AreaGroupAddress=None, CorridorLinkEnablerGroup=None), 202, 8, 'other')
    assert result.status == 'partial' and result.html.startswith('Control App Group')
    assert len(result.missing) == 2
    assert pir.pir_group_usage(unit(BroadcastBlock=[255]), 202, 8, 'other').status == 'partial'


@pytest.mark.parametrize('changes', [{'SceneKeySelector': [1, 0, 0, 0]}, {'BlockAllocation': [16] * 4},
    {'LightLevelStore1': None}, {'SecondApplicationBlocks': None}, {'Application': [202]}])
def test_unknown_graph_never_becomes_complete(changes):
    u = unit(**changes)
    assert pir.pir_action_selector_usage(u, 202, 8, 11, 22).status == 'unrecovered'
    assert pir.pir_group_usage(u, 202, 8, 'input').status == 'unrecovered'
    assert pir.pir_group_usage(u, 202, 8, 'output').status == 'recovered'


def test_appendix_matches_executed_original_wrappers(monkeypatch):
    receipt = json.loads((FIXTURES / 'project-documentor-pir-original.json').read_text())
    monkeypatch.setattr(pir, '_group_link', lambda *_: '<fixture group>')
    for case in receipt['appendix_cases']:
        if not case['class_match']:
            assert case['lines'] == ['<synthetic inherited body>']
            continue
        logic = int(case['off']) if case['st7'] else int(not case['off'])
        u = unit(firmware='2.4.00' if case['st7'] else '1.2.60',
                 PIREnablerGroup=[255 if case['unused'] else 8],
                 EnableGroupAddress=[255 if case['unused'] else 8],
                 PIREnablerGroupLogic=[logic], EnableGroupLogic=[logic])
        out = doc._Writer()
        assert pir.document_pir(out, network(), u) == 'recovered'
        assert out.lines[-2:] == case['lines'][-2:]
        assert ('polarity' in case['calls']) is not case['unused']


def test_inherited_action_matches_executed_original_with_no_neo_pass():
    receipt = json.loads((FIXTURES / 'project-documentor-pir-original.json').read_text())
    for case in receipt['action_cases']:
        blocks = case['blocks'] + [{'application': case['applications'][0], 'group': 255,
             'stored1': 0, 'stored2': 0, 'expiry': 15}] * (4 - len(case['blocks']))
        keys = case['keys'] + [{'blocks': [], 'commands': []}] * (4 - len(case['keys']))
        commands = [key['commands'] + [0] * (4 - len(key['commands'])) for key in keys]
        u = unit(Application=case['applications'], GroupAddress=[b['group'] for b in blocks],
            LightLevelStore1=[b['stored1'] for b in blocks], LightLevelStore2=[b['stored2'] for b in blocks],
            TimerExpiryCommand=[b['expiry'] for b in blocks],
            SecondApplicationBlocks=[sum(1 << i for i, b in enumerate(blocks) if b['application'] != case['applications'][0])],
            BlockAllocation=[sum(1 << i for i in key['blocks']) for key in keys],
            **{name: [commands[i][stage] for i in range(4)] for stage, name in enumerate(
               ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand'))})
        result = pir.pir_action_selector_usage(u, case['application'], case['group'], case['address'], case['value'])
        assert result.status == 'recovered'
        assert result.html == case['html'], case['name']


def test_source_receipt_and_complete_macro_matrix_are_retained():
    receipt = json.loads((FIXTURES / 'project-documentor-pir-static.json').read_text())
    assert len(receipt['registrations']) == 7 and all(receipt['checks'].values())
    macro = json.loads((FIXTURES / 'project-documentor-pir-macro-source.json').read_text())
    assert macro['vectors'] == 983040
    assert all(row['mismatches'] == 0 for row in macro['scenarios'])
    assert macro['original_generated_page_comparison'] == 'not_obtained'


def test_source_receipts_reproduce_when_configured():
    source = os.environ.get('CBUS_TOOLKIT_EXE')
    if not source:
        pytest.skip('Set CBUS_TOOLKIT_EXE for pinned PIR static/source comparisons')
    sys.path.insert(0, str(FIXTURES.parent))
    from project_documentor_pir_static import inspect, compare_macros
    exe = Path(source)
    mapping = Path(os.environ.get('CBUS_TOOLKIT_MAP', exe.with_suffix('.map')))
    assert inspect(exe, mapping) == json.loads((FIXTURES / 'project-documentor-pir-static.json').read_text())
    assert compare_macros(exe, mapping) == json.loads((FIXTURES / 'project-documentor-pir-macro-source.json').read_text())


def test_original_receipt_reproduces_when_configured(tmp_path):
    source = os.environ.get('CBUS_TOOLKIT_EXE')
    if not source or os.environ.get('CBUS_RUN_DOCUMENTOR_ORIGINAL') != '1':
        pytest.skip('Set CBUS_TOOLKIT_EXE and CBUS_RUN_DOCUMENTOR_ORIGINAL=1; executable memory required')
    exe = Path(source)
    output = tmp_path / 'pir-original.json'
    result = subprocess.run([sys.executable, str(FIXTURES.parent / 'project_documentor_pir_original.py'),
        '--executable', str(exe), '--map-file', os.environ.get('CBUS_TOOLKIT_MAP', str(exe.with_suffix('.map'))),
        '--output', str(output)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text()) == json.loads((FIXTURES / 'project-documentor-pir-original.json').read_text())
