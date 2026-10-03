"""Public DIN save normalization against owned Rust database services.

Specifications, projects, interfaces and faults are synthetic and test-owned.
These journeys do not execute original Toolkit instructions or touch hardware.
"""
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
from tests.test_cli_din_output_settings import write_spec


BACKENDS = [('cgate-mock', 'CBUS_CGATE_MOCK_BIN'), ('cmqttd', 'CBUS_CMQTTD_BIN')]
TYPES = ('RELDN4', 'RELDN8', 'RELDN8B', 'RELDN12',
         'DIMDN4', 'DIMDN4F', 'DIMDN8', 'DIMDN8F')
NETWORK = '//DINSAVE/11'
SOURCE = '/db//DINSAVE/11/p/20'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def source_values(spec):
    """Deliberately noncanonical raw levels and retained unused array tails."""
    values = spec.defaults()
    for name, start in (('LightLevel', 10), ('MinDimmingLevel', 20),
                        ('MaxDimmingLevel', 200)):
        count = len(values[name].split())
        values[name] = ' '.join(str(start + index) for index in range(count))
    values['LevelStoreEnable'] = ' '.join(
        str(int(index % 2 == 0)) for index in range(len(values['LevelStoreEnable'].split())))
    values['LogicLevelStoreEnable'] = '1 0 1 0'
    values['GroupAddress'] = ' '.join(map(str, range(1, 17)))
    values['InterLockingChannel'] = '171'
    values['AreaGroupAddress'] = '177'
    values['UnitAddress'] = '20'
    return values


def document(owner, path='//DINSAVE'):
    return xml_text(NativeDatabase(owner).get(path, xml=True))


def parameter_map(text):
    unit = ET.fromstring(text)
    if unit.tag != 'Unit':
        unit = unit.find("./Project/Network/Unit[Address='20']")
    parameters = unit.findall('PP')
    result = {row.get('Name'): row.get('Value') for row in parameters}
    assert len(result) == len(parameters)
    return result


def seed(owner, work, trap, unit_type, values):
    root = ET.Element('Installation')
    ET.SubElement(root, 'DBVersion').text = '2.3'
    project = ET.SubElement(root, 'Project')
    for name, value in (('OID', str(uuid.uuid4())), ('TagName', 'DINSAVE'), ('Address', 'DINSAVE')):
        ET.SubElement(project, name).text = value
    network = ET.SubElement(project, 'Network')
    for name, value in (('OID', str(uuid.uuid4())), ('Address', '11'), ('NetworkNumber', '11'),
                        ('TagName', 'Closed DIN network')):
        ET.SubElement(network, name).text = value
    interface = ET.SubElement(network, 'Interface')
    for name, value in (('OID', str(uuid.uuid4())), ('InterfaceType', 'cni'), ('InterfaceAddress', trap)):
        ET.SubElement(interface, name).text = value
    unit = ET.SubElement(network, 'Unit')
    for name, value in (('OID', str(uuid.uuid4())), ('Address', '20'), ('TagName', 'Retained DIN'),
                        ('UnitName', 'DIN20'), ('UnitType', unit_type), ('FirmwareVersion', '2.7.00'),
                        ('SerialNumber', '123456.7'), ('CatalogNumber', 'SYNTHETIC')):
        ET.SubElement(unit, name).text = value
    unit.append(ET.Comment('retain this unit comment'))
    for name, value in values.items():
        ET.SubElement(unit, 'PP', Name=name, Value=value)
    sibling = ET.SubElement(network, 'Unit')
    for name, value in (('OID', str(uuid.uuid4())), ('Address', '21'), ('TagName', 'Sibling'),
                        ('UnitName', 'Sibling'), ('UnitType', 'KEY1'), ('FirmwareVersion', '1.2.67')):
        ET.SubElement(sibling, name).text = value
    ET.SubElement(sibling, 'PP', Name='OpaqueSetting', Value='retained & exact Ω')
    network.append(ET.Comment('retain this network comment'))
    ET.SubElement(network, '{urn:cbus:synthetic:din}Unrelated', token='retained').text = 'unchanged Ω'
    path = work / 'din-synthetic.xml'
    path.write_bytes(ET.tostring(root))
    for command in ('FILE MKDIR Projects', 'FILE MKDIR Projects/archived'):
        assert owner.command(command).code == 200
    assert upload(prepare_upload('Projects/archived/' + path.name, path), owner)['upload_completed']
    for command in ('PROJECT RESTORE DINSAVE ' + path.name, 'PROJECT USE DINSAVE', 'PROJECT SAVE DINSAVE'):
        assert owner.command(command).code == 200


@contextmanager
def journey(backend, variable, unit_type, tmp_path):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'backend')
    specs = tmp_path / 'synthetic-specs'
    specs.mkdir()
    spec = write_spec(specs, unit_type)
    # The public fixture uses the real shared layout filename. The owned
    # backend also accepts its unit-type fallback name without a catalogue.
    alias = specs / (unit_type + '.xml')
    if alias.name != spec.filename:
        alias.write_bytes((specs / spec.filename).read_bytes())
    launcher = work / 'owned-din-spec-backend'
    flag = '--unitspec' if backend == 'cgate-mock' else '--cgate-unitspec'
    launcher.write_text('#!' + sys.executable + '\nimport os,sys\nos.execv('
                        + repr(str(binary)) + ', [' + repr(str(binary))
                        + ', *sys.argv[1:], ' + repr(flag) + ', ' + repr(str(specs)) + '])\n')
    launcher.chmod(0o700)
    evidence = {'format': 'cbus-din-toolkit-save-owned-v1', 'backend': backend,
                'unit_type': unit_type, 'original_execution': False, 'physical_acceptance': False,
                'binary_sha256': digest(binary.read_bytes()),
                'specification_sha256': {path.name: digest(path.read_bytes()) for path in specs.iterdir()},
                'calls': [], 'processes': [], 'wires': []}
    relay = None
    try:
        with no_contact_trap() as trap, owned_backend(backend, launcher, work) as (endpoint, process):
            evidence['processes'].append(process)
            with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                seed(owner, work, trap, unit_type, source_values(spec))
                yield owner, relay, evidence, specs, endpoint
        evidence['closed_graph_trap_contacts'] = 0
    finally:
        if relay is not None:
            evidence['wires'].extend(relay.evidence())
        associated_evidence(tmp_path / 'din-save-evidence.json', evidence)


def din_cli(relay, evidence, specs, *options, dry_run=False, expected=0, complete=True):
    arguments = ['unit', '--lock-address', NETWORK, '--source', SOURCE]
    if dry_run:
        arguments.append('--dry-run')
    arguments.extend(('din-settings', '--spec-dir', specs, *options))
    result, call = cli(relay, evidence['calls'], *arguments, expected=expected, complete=complete)
    assert not any(command.startswith(('NET OPEN ', 'PROJECT SAVE ', 'PP PROGRAM '))
                   for command in call['commands']), call
    return result, call


def offline_plan(specs, tmp_path, unit_type, parameters, *options):
    source = tmp_path / 'snapshot.json'
    source.write_text(json.dumps({'format': 'cbus-cli-parameters-v1', 'unit_type': unit_type,
                                 'firmware': '2.7.00', 'catalog_number': 'SYNTHETIC',
                                 'parameters': parameters}))
    argv = [sys.executable, '-m', 'cbus_toolkit', 'din-settings', '--spec-dir', str(specs),
            'plan', str(source), *options]
    process = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stdout + process.stderr
    return json.loads(process.stdout)


def fresh_parameters(relay, evidence):
    result, call = cli(relay, evidence['calls'], 'unit', '--lock-address', NETWORK,
                       '--source', SOURCE, 'show')
    assert sum(command.startswith('PP LOAD ') for command in call['commands']) == 1
    assert not any(command.startswith(('PP SET ', 'PP SAVE')) for command in call['commands'])
    return result


def assert_preservation(before, after, expected):
    old = ET.fromstring(before, ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    new = ET.fromstring(after, ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    old_unit = old.find("./Project/Network/Unit[Address='20']")
    new_unit = new.find("./Project/Network/Unit[Address='20']")
    old_pp, new_pp = parameter_map(before), parameter_map(after)
    assert set(old_pp) == set(new_pp)
    assert {name: value for name, value in new_pp.items() if value != old_pp[name]} == expected
    for row in old_unit.findall('PP'):
        if row.get('Name') in expected:
            row.set('Value', expected[row.get('Name')])
    # This includes all unrelated parameters, unit metadata, comments,
    # namespace content, sibling units, interface and project/network IDs.
    assert graph(ET.tostring(old, encoding='unicode')) == graph(ET.tostring(new, encoding='unicode'))
    assert old_unit.findtext('OID') == new_unit.findtext('OID')


def normalized_changes(unit_type):
    """Literal source-derived outputs, independent of the editor and plan.

    The marshalling relay overwrites the base save's enabled-store levels;
    its four-value maximum array also shifts on each separate dialog save.
    """
    if unit_type == 'RELDN8':
        return {
            'InterLockingChannel': '3',
            'GroupAddress': '255 2 3 4 5 255 255 8 9 10 11 255 13 14 15 16',
            'LightLevel': '0 11 12 13 14 0 0 17 18 19 20 0 22 23 24 25',
            'LevelStoreEnable': '0 0 1 0 1 0 0 0 1 0 1 0',
            'PowerUpDelay': '0 5 5 5 5 0 0 5 5 5 5 5',
            'MinDimmingLevel': '0 21 22 23 24 0 0 27 28 29 30 31',
            'MaxDimmingLevel': '201 202 203 0',
        }
    count = {'RELDN4': 4, 'RELDN8B': 8, 'RELDN12': 12,
             'DIMDN4': 4, 'DIMDN4F': 4, 'DIMDN8': 8, 'DIMDN8F': 8}[unit_type]
    light = {
        4: '255 11 255 13 0 0 0 0 0 0 0 0 22 23 24 25',
        8: '255 11 255 13 255 15 255 17 0 0 0 0 22 23 24 25',
        12: '255 11 255 13 255 15 255 17 255 19 255 21 22 23 24 25',
    }[count]
    result = {'LightLevel': light}
    if count < 12:
        result['GroupAddress'] = {
            4: '1 2 3 4 255 255 255 255 255 255 255 255 13 14 15 16',
            8: '1 2 3 4 5 6 7 8 255 255 255 255 13 14 15 16',
        }[count]
    if unit_type.startswith('REL'):
        result['InterLockingChannel'] = '3'
    return result


def saved_once(call):
    saves = [index for index, command in enumerate(call['commands'])
             if command.startswith('PP SAVE')]
    assert len(saves) == 1
    assert call['commands'][saves[0]].startswith('PP SAVE_TO_SOURCE ')
    assert call['statuses'][saves[0]] == 200


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('unit_type', TYPES)
def test_public_din_toolkit_save_all_profiles(backend, variable, unit_type, tmp_path):
    with journey(backend, variable, unit_type, tmp_path) as (owner, relay, evidence, specs, _):
        before = document(owner)
        current = fresh_parameters(relay, evidence)
        plan = offline_plan(specs, tmp_path, unit_type, current, '--toolkit-save')
        expected = normalized_changes(unit_type)
        assert plan['toolkit_save'] is True
        assert plan['changes'] == {name: list(map(int, value.split())) for name, value in expected.items()}
        preview, call = din_cli(relay, evidence, specs, '--toolkit-save', dry_run=True)
        for name in ('format', 'expected', 'changes', 'toolkit_save'):
            assert preview[name] == plan[name]
        assert preview['verified'] is True and preview['saved'] is False
        assert not any(command.startswith('PP SAVE') for command in call['commands'])
        assert document(owner) == before
        assert fresh_parameters(relay, evidence) == current

        # The serialized normalized plan must replay its admitted inputs, not
        # trust a caller-supplied list of derived PP writes.
        altered = json.loads(json.dumps(plan))
        altered['changes']['LightLevel'][0] = 1
        bad = tmp_path / 'tampered.json'
        bad.write_text(json.dumps(altered))
        refused, call = din_cli(relay, evidence, specs, '--plan', bad, expected=1)
        assert 'error' in refused
        assert not any(command.startswith(('PP SET ', 'PP SAVE')) for command in call['commands'])
        assert document(owner) == before

        saved_plan = tmp_path / 'plan.json'
        saved_plan.write_text(json.dumps(plan))
        applied, call = din_cli(relay, evidence, specs, '--plan', saved_plan)
        assert applied['saved'] is True and applied['toolkit_save'] is True
        saved_once(call)
        after = document(owner)
        assert_preservation(before, after, expected)
        fresh = fresh_parameters(relay, evidence)
        assert fresh == applied['parameters']
        assert {name: fresh[name] for name in expected} == expected
        refused, call = din_cli(relay, evidence, specs, '--plan', saved_plan, expected=1)
        assert 'changed since' in refused['error']
        assert not any(command.startswith(('PP SET ', 'PP SAVE')) for command in call['commands'])
        assert document(owner) == after

        for action in ('save', 'close', 'load'):
            outcome, call = cli(relay, evidence['calls'], 'project', action, 'DINSAVE')
            assert outcome['status'] == 200
            assert call['commands'] == [f'PROJECT {action.upper()} DINSAVE']
        assert owner.command('PROJECT USE DINSAVE').code == 200
        assert document(owner) == after
        assert fresh_parameters(relay, evidence) == fresh

        # A legacy targeted plan remains targeted. In particular, re-opening
        # RELDN8 must not silently perform another maximum-array remapping.
        legacy = offline_plan(specs, tmp_path, unit_type, fresh, '--channel', '1', '--min-level', '77')
        assert legacy['format'] == 'cbus-din-output-settings-plan-v1'
        assert legacy.get('toolkit_save', False) is False
        old_minimum = list(map(int, fresh['MinDimmingLevel'].split()))
        old_minimum[1 if unit_type == 'RELDN8' else 0] = 77
        assert legacy['changes'] == {'MinDimmingLevel': old_minimum}
        legacy_path = tmp_path / 'legacy.json'
        legacy_path.write_text(json.dumps(legacy))
        targeted, call = din_cli(relay, evidence, specs, '--plan', legacy_path)
        saved_once(call)
        assert targeted['saved'] is True
        assert_preservation(after, document(owner), {'MinDimmingLevel': ' '.join(map(str, old_minimum))})
        assert fresh_parameters(relay, evidence) == targeted['parameters']
        evidence['snapshots'] = {'before': before, 'normalized': after, 'targeted': document(owner)}


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('unit_type', ['DIMDN8', 'RELDN8'])
def test_public_din_successful_save_lost_response_is_not_replayed(backend, variable, unit_type, tmp_path):
    with journey(backend, variable, unit_type, tmp_path) as (owner, relay, evidence, specs, endpoint):
        before = document(owner)
        with FaultGate(endpoint, 'PP SAVE_TO_SOURCE', 'drop') as fault:
            failure, call = din_cli(fault, evidence, specs, '--toolkit-save', expected=1, complete=False)
            assert 'error' in failure and not failure.get('saved', False)
            assert len(fault.rows) == 1 and fault.matches == 1
            row = fault.rows[0]
            terminal = bytes.fromhex(row['lost_backend_terminal_hex']).decode()
            assert '] 200 ' in terminal, terminal
            saves = [command for command in call['commands'] if command.startswith('PP SAVE')]
            assert len(saves) == 1 and saves[0].startswith('PP SAVE_TO_SOURCE ')
            assert call['commands'][-1] == saves[0], call
            evidence['wires'].extend(fault.evidence())
        after = document(owner)
        expected = normalized_changes(unit_type)
        assert_preservation(before, after, expected)
        fresh = fresh_parameters(relay, evidence)
        assert {name: fresh[name] for name in expected} == expected
        assert document(owner) == after
        evidence['snapshots'] = {'before': before, 'after_lost_successful_save': after}
