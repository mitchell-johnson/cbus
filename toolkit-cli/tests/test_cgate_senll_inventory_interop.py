"""Complete SENLL getter inventories and native scene saves on owned services."""
from contextlib import contextmanager
import hashlib
import json
import subprocess
import sys
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from test_cgate_barcode_database_interop import FaultGate, cli, graph, selected_binary
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend,
)
from test_cgate_senll_controls_interop import (
    BACKENDS, NETWORK, SOURCE, assert_graph_changes, document, parameter_map, seed, sensor_cli,
)
from test_light_level_sensors import fixture
from test_native_sensor_scenes import VECTORS


def complete_fixture():
    base = fixture()
    parameters = dict(base.parameters)
    # Authored minimal layouts, not redistributed unit specification content.
    for name, address, count, values in [
        ('AreaGroupAddress', 67, 1, [255]),
        ('SceneTablePointer', 152, 8, [162, 182, 202, 222, 255, 255, 255, 255]),
        ('PatchEnable', 160, 2, [157, 64]),
        ('SceneTable', 162, 80, [255] * 80),
    ]:
        fields = {'Name': name, 'Type': 'int', 'Address': str(address), 'ArraySize': str(count),
                  'BitSize': '8', 'BitAddress': '0', 'ArraySkip': '0',
                  'DefaultValue': ' '.join(map(str, values))}
        parameters[name] = ParameterSpec(name, 'int', 'literal-senll-inventory.xml', fields)
    return UnitSpec(base.filename, base.metadata, base.sources, parameters)


@contextmanager
def journey(backend, variable, tmp_path, changes):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'inventory-backend')
    specs = tmp_path / 'synthetic-specs'
    specs.mkdir()
    spec = complete_fixture()
    root = ET.Element('UnitSpecification')
    ET.SubElement(root, 'Type').text = 'SENPILL'
    params = ET.SubElement(root, 'Parameters')
    for parameter in spec.parameters.values():
        node = ET.SubElement(params, 'Param')
        for name, value in parameter.fields.items():
            ET.SubElement(node, name).text = value
    data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    for name in ('SENLL_ST7.xml', 'SENLL.xml'):
        (specs / name).write_bytes(data)
    flag = '--unitspec' if backend == 'cgate-mock' else '--cgate-unitspec'
    evidence = {'format': 'cbus-senll-inventory-owned-v1', 'backend': backend,
                'original_execution': False, 'physical_acceptance': False,
                'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                'calls': [], 'processes': [], 'wires': []}
    relay = None
    try:
        with no_contact_trap() as trap, owned_backend(backend, binary, work, extra_args=(flag, specs)) as (endpoint, process):
            evidence['processes'].append(process)
            with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                seed(owner, work, trap, spec, changes)
                yield owner, relay, evidence, specs, endpoint
        evidence['closed_graph_trap_contacts'] = 0
    finally:
        if relay is not None:
            evidence['wires'].extend(relay.evidence())
        associated_evidence(tmp_path / 'senll-inventory-evidence.json', evidence)


def pp(values):
    return ' '.join(map(str, values))


CASES = [
    ('area-before-refresh', {'Application': '56 255', 'AreaGroupAddress': '20',
                            'GroupAddress': '255 255 20 255 255 255 255 255'},
     ['application=primary'], {'SecondApplicationBlocks': '0'}),
    ('area-select-not-reserved', {'AreaGroupAddress': '22', 'SecondApplicationBlocks': '0',
                                'GroupAddress': '255 255 255 255 255 255 255 255'},
     ['group=22'], {'GroupAddress': '255 255 22 255 255 255 255 255'}),
    ('scene-after-refresh', {'SceneTable': pp([20, 137] + [255] * 78),
                            'GroupAddress': '255 255 20 255 255 255 255 255'},
     ['application=primary'], {'SecondApplicationBlocks': '0'}),
    ('scene-select-not-reserved', {'SceneTable': pp([22, 12] + [255] * 78),
                                 'SecondApplicationBlocks': '0',
                                 'GroupAddress': '255 255 255 255 255 255 255 255'},
     ['group=22'], {'GroupAddress': '255 255 22 255 255 255 255 255'}),
    ('scene-padding-walk', {'SceneTable': pp([20, 100, 255, 17, 22, 18] + [255] * 74),
                           'SceneTablePointer': '42 163 163 0 255 255 255 255',
                           'SecondApplicationBlocks': '0',
                           'GroupAddress': '255 255 255 255 255 255 255 255'},
     ['group=22'], {'GroupAddress': '255 255 22 255 255 255 255 255'}),
]
# The same public flow exercises all six source-audited enabled-save histories.
for case, table, pointers, _scenes, saved_table, saved_pointers in VECTORS:
    expected = {}
    if table != saved_table:
        expected['SceneTable'] = pp(saved_table)
    if pointers != saved_pointers:
        expected['SceneTablePointer'] = pp(saved_pointers)
    CASES.append(('enabled-' + case,
                  {'PatchEnable': '0 0', 'SceneTable': pp(table), 'SceneTablePointer': pp(pointers),
                   'SecondApplicationBlocks': '0',
                   'GroupAddress': '255 255 255 255 255 255 255 255'},
                  ['application=primary'], expected))
_compatible_hole = next(row for row in CASES if row[0] == 'enabled-compatible-hole')
CASES.append(('flat-enabled-compatible-hole', _compatible_hole[1], [], _compatible_hole[3]))


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('case,seed_changes,controls,expected', CASES, ids=[row[0] for row in CASES])
def test_public_senll_inventory_save_and_reopen(backend, variable, case, seed_changes,
                                              controls, expected, tmp_path):
    with journey(backend, variable, tmp_path, seed_changes) as (owner, relay, evidence, specs, _endpoint):
        before = document(owner)
        snapshot = tmp_path / 'complete-sensor.json'
        snapshot.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': 'SENLL',
                                        'firmware': '2.3.00', 'catalog_number': '5031PE',
                                        'parameters': parameter_map(before)}))
        original_snapshot = snapshot.read_bytes()
        specification_bytes = {path.name: path.read_bytes() for path in specs.iterdir()}
        offline_args = [sys.executable, '-m', 'cbus_toolkit', 'sensors', '--spec-dir', str(specs),
                        'light-level-plan', str(snapshot)]
        for control in controls:
            offline_args.extend(('--on-off-control', control))
        offline = subprocess.run(offline_args, capture_output=True, text=True, timeout=30)
        assert offline.returncode == 0, offline.stdout + offline.stderr
        planned = json.loads(offline.stdout)
        assert len(planned['expected']) == 47
        assert snapshot.read_bytes() == original_snapshot
        assert {path.name: path.read_bytes() for path in specs.iterdir()} == specification_bytes
        preview, preview_call = sensor_cli(relay, evidence, specs, controls, dry_run=True)
        assert planned['changes'] == preview['changes']
        assert preview['verified'] and preview['saved'] is False and preview['device_verified'] is False
        assert not any(command.startswith('PP SAVE') for command in preview_call['commands'])
        assert graph(document(owner)) == graph(before)
        expected_values = {**parameter_map(before), **expected}
        assert preview['parameters'] == expected_values
        result, call = sensor_cli(relay, evidence, specs, controls)
        assert result['verified'] and result['saved'] is True and result['device_verified'] is False
        assert result['parameters'] == expected_values
        assert sum(command.startswith('PP SAVE') for command in call['commands']) == 1
        assert_graph_changes(before, document(owner), expected)
        for name in ('AreaGroupAddress', 'PatchEnable'):
            assert result['parameters'][name] == parameter_map(before)[name]
        for command in ('PROJECT SAVE SENLL', 'PROJECT CLOSE SENLL', 'PROJECT LOAD SENLL'):
            assert owner.command(command).code == 200
        assert_graph_changes(before, document(owner), expected)
        fresh, fresh_call = cli(relay, evidence['calls'], 'unit', '--lock-address', NETWORK,
                               '--source', SOURCE, 'show')
        assert fresh == expected_values
        assert not any(command.startswith(('PP SET ', 'PP SAVE')) for command in fresh_call['commands'])


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('case,changes,controls,error', [
    ('late-scene-cannot-help-refresh', {'Application': '56 255',
                                      'GroupAddress': '255 255 20 255 255 255 255 255',
                                      'SceneTable': pp([20, 1] + [255] * 78)},
     ['application=primary'], 'creation/decline'),
    ('first-sentinel-suppresses-getter', {'SecondApplicationBlocks': '0',
                                        'GroupAddress': '255 255 255 255 255 255 255 255',
                                        'SceneTable': pp([255, 0, 20, 1] + [255] * 76)},
     ['group=20'], 'creation/decline'),
], ids=['late-scene-cannot-help-refresh', 'first-sentinel-suppresses-getter'])
def test_public_senll_inventory_refusal_before_staging(backend, variable, case, changes,
                                                     controls, error, tmp_path):
    with journey(backend, variable, tmp_path, changes) as (owner, relay, evidence, specs, _endpoint):
        before = document(owner)
        result, call = sensor_cli(relay, evidence, specs, controls, expected=1)
        assert error in result['error']
        assert not any(command.startswith(('PP SET ', 'PP SAVE', 'PROJECT SAVE ', 'DBSET', 'DBADD'))
                       for command in call['commands'])
        assert graph(document(owner)) == graph(before)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_senll_enabled_scene_lost_save_is_not_replayed(backend, variable, tmp_path):
    # First independently audited vector: duplicate level and noncanonical start.
    changes = {'PatchEnable': '0 0', 'SceneTable': pp([20, 1, 20, 2, 255, 3, 30, 4] + [255] * 72),
               'SceneTablePointer': '0 255 255 255 255 255 255 255',
               'GroupAddress': '255 255 255 255 255 255 255 255', 'SecondApplicationBlocks': '0'}
    expected = {'SceneTable': pp([20, 1, 30, 4] + [255] * 76),
                'SceneTablePointer': '162 182 202 222 255 255 255 255'}
    with journey(backend, variable, tmp_path, changes) as (owner, _relay, evidence, specs, endpoint):
        before = document(owner)
        with FaultGate(endpoint, 'PP SAVE_TO_SOURCE', 'drop') as fault:
            try:
                result, call = sensor_cli(fault, evidence, specs, ['application=primary'], expected=1, complete=False)
                assert 'error' in result
                assert fault.matches == 1
                assert sum(command.startswith('PP SAVE') for command in call['commands']) == 1
                assert not any(command.startswith(('PROJECT SAVE ', 'DBSET', 'DBDELETE'))
                               for command in call['commands'])
                assert bytes.fromhex(fault.rows[0]['lost_backend_terminal_hex']).decode().split()[1] == '200'
            finally:
                evidence['wires'].extend(fault.evidence())
        assert_graph_changes(before, document(owner), expected)
