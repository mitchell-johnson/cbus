"""Public SENLL control histories on owned loopback database services."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.file_transfer import prepare_upload, upload
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import xml_text
from test_cgate_barcode_database_interop import FaultGate, cli, graph, selected_binary
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend,
)
from test_light_level_sensors import fixture

BACKENDS = [('cgate-mock', 'CBUS_CGATE_MOCK_BIN'), ('cmqttd', 'CBUS_CMQTTD_BIN')]
NETWORK = '//SENLL/11'
SOURCE = '/db//SENLL/11/p/20'
# Literal already-normalized forced-save baseline; do not derive the expected
# control outcomes from the Python planner under test.
NORMAL = {
    'PIRLightMovement': '0', 'PIRDarkMovement': '0', 'PIRDark': '0', 'DisableIR': '1',
    'IRBankKeyOffset': '0', 'CorridorLinkOfficeBlock': '0', 'CorridorLinkBlock': '0',
    'CorridorLinkEnablerGroup': '255', 'CorridorLinkActive': '0', 'BroadcastBlock': '4',
    'PIREnablerGroup': '255', 'SingleJoinEnablerGroup': '255',
    'SingleJoinEnablerControlGroup': '255', 'DualJoinEnablerGroup': '255',
    'DualJoinEnablerControlGroup': '255', 'PECFunctionActive': '1', 'PECFunctionBlock': '1',
    'PECFunctionIRKey': '0', 'PECFunctionIRActive': '0', 'PIRFunctionIRKey': '0',
    'PIRFunctionIRActive': '0', 'PIRLevelStore': '0', 'PECEnablerGroupLogic': '0',
    'PIREnablerGroupLogic': '0', 'PotentiometerAFunction': '0', 'PotentiometerBFunction': '0',
    'PotentiometerATimerBlock': '0', 'PotentiometerBTimerBlock': '0',
    'PotentiometerBBankSwitchEnable': '0', 'RampRate': '7 7',
    'LightLevel': '1 2 3 4 5 6 7 8 0 10', 'PECTargetLux': '100', 'PECMarginLux': '10',
    'PECLevelStore': '1', 'IndicatorBlockAssignment': '1 0 0 0 0 0 0 0', 'BroadcastActive': '0',
}
CASES = [
    ('primary-collision', {}, ['application=primary'],
     {'GroupAddress': '255 20 255 255 255 25 255 255', 'SecondApplicationBlocks': '0'}),
    ('secondary-collision', {'SecondApplicationBlocks': '2'}, ['application=secondary'],
     {'GroupAddress': '255 20 255 255 255 25 255 255', 'SecondApplicationBlocks': '6'}),
    ('same-boolean-duplicate', {'SecondApplicationBlocks': '0'}, ['application=primary'], {}),
    ('missing-secondary-load', {'Application': '56 255', 'GroupAddress': '20 20 20 20 20 20 20 20',
                              'SecondApplicationBlocks': '254', 'BroadcastActive': '1'}, ['application=primary'],
     {'GroupAddress': '20 255 255 255 255 255 255 255',
      'SecondApplicationBlocks': '0', 'BroadcastActive': '0'}),
    ('hidden-enable', {'GroupAddress': '255 21 20 255 255 25 255 255', 'PECEnablerGroup': '20'},
     ['application=primary'],
     {'GroupAddress': '255 21 255 255 255 25 255 255', 'SecondApplicationBlocks': '0'}),
    ('ordered-return-to-retained-group', {},
     ['application=primary', 'application=secondary', 'group=20'], {}),
    ('dual-join-lookup', {'GroupAddress': '255 255 20 255 255 255 255 255',
                        'SingleJoinEnablerGroup': '22', 'DualJoinEnablerGroup': '20'},
     ['application=primary'],
     {'SecondApplicationBlocks': '0', 'SingleJoinEnablerGroup': '255', 'DualJoinEnablerGroup': '255'}),
    ('pir-enable-lookup', {'GroupAddress': '255 255 20 255 255 255 255 255', 'PIREnablerGroup': '20'},
     ['application=primary'],
     {'SecondApplicationBlocks': '0', 'PIREnablerGroup': '255'}),
]


def write_spec(folder):
    spec = fixture()
    root = ET.Element('UnitSpecification')
    ET.SubElement(root, 'Type').text = 'SENPILL'
    params = ET.SubElement(root, 'Parameters')
    for parameter in spec.parameters.values():
        node = ET.SubElement(params, 'Param')
        for key, value in parameter.fields.items():
            ET.SubElement(node, key).text = value
    data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    for name in ('SENLL_ST7.xml', 'SENLL.xml'):
        (folder / name).write_bytes(data)
    return spec


def parameter_map(document):
    root = ET.fromstring(document)
    unit = root.find("./Project/Network/Unit[Address='20']")
    rows = unit.findall('PP')
    result = {row.get('Name'): row.get('Value') for row in rows}
    assert len(result) == len(rows)
    return result


def document(owner):
    return xml_text(NativeDatabase(owner).get('//SENLL', xml=True))


def seed(owner, work, trap, spec, changes):
    values = {**spec.defaults(), **NORMAL, 'Application': '56 57',
              'GroupAddress': '255 20 20 255 255 25 255 255', 'SecondApplicationBlocks': '4',
              **changes}
    root = ET.Element('Installation')
    ET.SubElement(root, 'DBVersion').text = '2.3'
    project = ET.SubElement(root, 'Project')
    for name, value in [('OID', str(uuid.uuid4())), ('Address', 'SENLL'), ('TagName', 'SENLL')]:
        ET.SubElement(project, name).text = value
    network = ET.SubElement(project, 'Network')
    for name, value in [('OID', str(uuid.uuid4())), ('Address', '11'), ('NetworkNumber', '11'),
                        ('TagName', 'Closed sensor network')]:
        ET.SubElement(network, name).text = value
    interface = ET.SubElement(network, 'Interface')
    for name, value in [('OID', str(uuid.uuid4())), ('InterfaceType', 'cni'), ('InterfaceAddress', trap)]:
        ET.SubElement(interface, name).text = value
    unit = ET.SubElement(network, 'Unit')
    for name, value in [('OID', str(uuid.uuid4())), ('Address', '20'), ('TagName', 'Retained SENLL'),
                        ('UnitName', 'SENLL20'), ('UnitType', 'SENLL'), ('FirmwareVersion', '2.3.00'),
                        ('CatalogNumber', '5031PE'), ('SerialNumber', '123456.7')]:
        ET.SubElement(unit, name).text = value
    unit.append(ET.Comment('preserve sensor comment'))
    for name, value in values.items():
        ET.SubElement(unit, 'PP', Name=name, Value=value)
    sibling = ET.SubElement(network, 'Unit')
    for name, value in [('OID', str(uuid.uuid4())), ('Address', '21'), ('TagName', 'Sibling'),
                        ('UnitName', 'Sibling'), ('UnitType', 'KEY1'), ('FirmwareVersion', '1.2.67')]:
        ET.SubElement(sibling, name).text = value
    ET.SubElement(sibling, 'PP', Name='OpaqueSetting', Value='retained & exact Ω')
    ET.SubElement(network, '{urn:cbus:synthetic:senll}Unrelated', token='retained').text = 'unchanged Ω'
    path = work / 'senll-synthetic.xml'
    path.write_bytes(ET.tostring(root))
    for command in ('FILE MKDIR Projects', 'FILE MKDIR Projects/archived'):
        assert owner.command(command).code == 200
    assert upload(prepare_upload('Projects/archived/' + path.name, path), owner)['upload_completed']
    for command in ('PROJECT RESTORE SENLL ' + path.name, 'PROJECT USE SENLL', 'PROJECT SAVE SENLL'):
        assert owner.command(command).code == 200


@contextmanager
def journey(backend, variable, tmp_path, changes):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'backend')
    specs = tmp_path / 'synthetic-specs'
    specs.mkdir()
    spec = write_spec(specs)
    flag = '--unitspec' if backend == 'cgate-mock' else '--cgate-unitspec'
    evidence = {'format': 'cbus-senll-controls-owned-v1', 'backend': backend,
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
        associated_evidence(tmp_path / 'senll-controls-evidence.json', evidence)


def sensor_cli(relay, evidence, specs, controls, *, dry_run=False, expected=0, complete=True):
    args = ['unit', '--lock-address', NETWORK, '--source', SOURCE]
    if dry_run:
        args.append('--dry-run')
    args.extend(('sensor-light-level', '--spec-dir', specs))
    for control in controls:
        args.extend(('--on-off-control', control))
    result, call = cli(relay, evidence['calls'], *args, expected=expected, complete=complete)
    assert not any(command.startswith(('NET OPEN ', 'PROJECT SAVE ', 'PP PROGRAM '))
                   for command in call['commands']), call
    return result, call


def assert_graph_changes(before, after, expected):
    old = ET.fromstring(before, ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    old_values, new_values = parameter_map(before), parameter_map(after)
    assert set(old_values) == set(new_values)
    assert {name: value for name, value in new_values.items() if value != old_values[name]} == expected
    for row in old.find("./Project/Network/Unit[Address='20']").findall('PP'):
        if row.get('Name') in expected:
            row.set('Value', expected[row.get('Name')])
    assert graph(ET.tostring(old, encoding='unicode')) == graph(after)
    assert new_values['BlockAllocation'] == old_values['BlockAllocation']
    for name in ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand', 'SceneKeySelector'):
        assert new_values[name] == old_values[name]


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('case,seed_changes,controls,expected', CASES, ids=[row[0] for row in CASES])
def test_public_senll_ordered_controls_save_and_reopen(backend, variable, case, seed_changes,
                                                      controls, expected, tmp_path):
    with journey(backend, variable, tmp_path, seed_changes) as (owner, relay, evidence, specs, _endpoint):
        before = document(owner)
        preview, preview_call = sensor_cli(relay, evidence, specs, controls, dry_run=True)
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
        for command in ('PROJECT SAVE SENLL', 'PROJECT CLOSE SENLL', 'PROJECT LOAD SENLL'):
            assert owner.command(command).code == 200
        assert_graph_changes(before, document(owner), expected)
        fresh, fresh_call = cli(relay, evidence['calls'], 'unit', '--lock-address', NETWORK,
                               '--source', SOURCE, 'show')
        assert fresh == expected_values
        assert not any(command.startswith(('PP SET ', 'PP SAVE')) for command in fresh_call['commands'])


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_senll_lost_save_is_not_replayed(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path, {}) as (owner, _relay, evidence, specs, endpoint):
        before = document(owner)
        with FaultGate(endpoint, 'PP SAVE_TO_SOURCE', 'drop') as fault:
            try:
                result, call = sensor_cli(fault, evidence, specs, ['application=primary'],
                                          expected=1, complete=False)
                assert 'error' in result
                assert fault.matches == 1
                assert sum(command.startswith('PP SAVE') for command in call['commands']) == 1
                assert not any(command.startswith(('PROJECT SAVE ', 'DBSET', 'DBDELETE'))
                               for command in call['commands'])
                assert bytes.fromhex(fault.rows[0]['lost_backend_terminal_hex']).decode().split()[1] == '200'
            finally:
                evidence['wires'].extend(fault.evidence())
        # Independent observer verifies what the owned backend did; the failed
        # public invocation itself never reconnects, retries or rolls back.
        assert_graph_changes(before, document(owner),
                             {'GroupAddress': '255 20 255 255 255 25 255 255',
                              'SecondApplicationBlocks': '0'})


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('case,seed_changes,controls,error', [
    ('missing-destination', {'GroupAddress': '255 20 22 255 255 25 255 255'},
     ['application=primary'], 'creation/decline'),
    ('excluded-after-collision', {}, ['application=primary', 'group=20'], 'excluded'),
], ids=['missing-destination', 'excluded-after-collision'])
def test_public_senll_refusal_is_read_only(backend, variable, case, seed_changes, controls, error, tmp_path):
    with journey(backend, variable, tmp_path, seed_changes) as (owner, relay, evidence, specs, _endpoint):
        before = document(owner)
        result, call = sensor_cli(relay, evidence, specs, controls, expected=1)
        assert error in result['error']
        assert not any(command.startswith(('PP SET ', 'PP SAVE', 'PROJECT SAVE ', 'DBSET', 'DBADD'))
                       for command in call['commands'])
        assert graph(document(owner)) == graph(before)
