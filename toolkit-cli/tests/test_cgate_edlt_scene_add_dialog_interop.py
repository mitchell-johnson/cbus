"""SceneManager dialogs through the public CLI and both owned Rust services.

All projects and specifications are synthetic. The source Network is closed;
its interface points at a test-owned trap, never a physical C-Bus endpoint.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.edlt import _render
from cbus_toolkit.edlt_scene_manager_cli import SceneCLIEditor
from cbus_toolkit.file_transfer import prepare_upload, upload
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import xml_text
from test_cgate_barcode_database_interop import FaultGate, cli, graph, selected_binary
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap,
    owned_backend,
)
from tests.test_edlt_lifecycle import fixture
from tests.test_edlt_scene_manager import vectors
from tests.test_edlt_scene_metadata import SceneMetadataClient


BACKENDS = [('cgate-mock', 'CBUS_CGATE_MOCK_BIN'),
            ('cmqttd', 'CBUS_CMQTTD_BIN')]
WIRE = json.loads((Path(__file__).resolve().parents[2] /
                   'rust/testdata/vectors/cgate_edlt_scene_dialog_wire.json').read_text())


def digest(value):
    return hashlib.sha256(value).hexdigest()


def synthetic_spec(directory):
    """Serialize the public editor fixture, not a vendor specification."""
    directory.mkdir()
    spec = fixture()
    root = ET.Element('UnitSpecification')
    for name, value in (('Type', 'KEYGL5'), ('MinVersion', '5.5.00'),
                        ('MaxVersion', '5.5.00'), ('MemorySize', '16384')):
        ET.SubElement(root, name).text = value
    parameters = ET.SubElement(root, 'Parameters')
    for parameter in spec.parameters.values():
        node = ET.SubElement(parameters, 'Param')
        for name, value in parameter.fields.items():
            ET.SubElement(node, name).text = value
    path = directory / 'KEYGL5.xml'
    path.write_bytes(ET.tostring(root))
    return spec, path


def provision(owner, work, trap, spec):
    model = SceneMetadataClient(spec)
    editor = SceneCLIEditor(spec)
    source = editor.snapshot(model.values)
    source.update({name: value for name, value in vectors()['input'].items()
                   if name in spec.parameters})
    model.values = {name: _render(value)
                    for name, value in editor.snapshot(source).items()}
    root = ET.fromstring(model.xml())
    ET.SubElement(root, 'DBVersion').text = '2.3'
    project = root.find('Project')
    ET.SubElement(project, 'OID').text = str(uuid.uuid4())
    # RESTORE owns project naming; the imported display name is replaced.
    ET.SubElement(project, 'TagName').text = 'Synthetic SceneManager'
    network = project.find('Network')
    # The public archive schema stores interface fields in an Interface object.
    network.remove(network.find('InterfaceType'))
    for application in network.findall('Application'):
        application.remove(application.find('Description'))
        for group in application.findall('Group') + application.findall('NetVar'):
            group.remove(group.find('Notes'))
            if group.tag == 'NetVar':
                group.remove(group.find('TagsDLT'))
    ET.SubElement(network, 'OID').text = str(uuid.uuid4())
    ET.SubElement(network, 'NetworkNumber').text = '254'
    ET.SubElement(network, 'TagName').text = 'Closed synthetic network'
    interface = ET.SubElement(network, 'Interface')
    ET.SubElement(interface, 'OID').text = str(uuid.uuid4())
    ET.SubElement(interface, 'InterfaceType').text = 'cni'
    ET.SubElement(interface, 'InterfaceAddress').text = trap
    ET.SubElement(network.find('Unit'), 'UnitName').text = 'KEYGL5'
    path = work / 'scene-dialog-synthetic.xml'
    path.write_bytes(ET.tostring(root))
    for command in ('FILE MKDIR Projects', 'FILE MKDIR Projects/archived'):
        assert owner.command(command).code == 200
    result = upload(prepare_upload('Projects/archived/' + path.name, path), owner)
    assert result['upload_completed']
    for command in ('PROJECT RESTORE TEST ' + path.name,
                    'PROJECT USE TEST', 'PROJECT SAVE TEST'):
        assert owner.command(command).code == 200
    return digest(path.read_bytes())


def snapshot(owner):
    return xml_text(NativeDatabase(owner).get('//TEST', xml=True))


@contextmanager
def journey(backend, variable, tmp_path):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'backend')
    specs = tmp_path / 'synthetic-specs'
    spec, path = synthetic_spec(specs)
    flag = '--unitspec' if backend == 'cgate-mock' else '--cgate-unitspec'
    evidence = {'format': 'cbus-edlt-scene-dialog-owned-v1',
                'backend': backend, 'binary_sha256': digest(binary.read_bytes()),
                'specification_sha256': digest(path.read_bytes()),
                'original_execution': False, 'physical_acceptance': False,
                'calls': [], 'processes': []}
    relay = None
    try:
        with no_contact_trap() as trap:
            with owned_backend(backend, binary, work, extra_args=(flag, specs)) as (endpoint, process):
                evidence['processes'].append(process)
                with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                    evidence['fixture_sha256'] = provision(owner, work, trap, spec)
                    yield owner, relay, evidence, specs, endpoint
        evidence['closed_graph_trap_contacts'] = 0
    finally:
        if relay is not None:
            evidence['wires'] = relay.evidence()
        associated_evidence(tmp_path / 'scene-dialog-evidence.json', evidence)


def scene_cli(relay, evidence, specs, ops_path, *, dry_run=False,
              expected=0, complete=True, backup=True):
    arguments = ['unit', '--lock-address', '//TEST/254',
                 '--source', '/db//TEST/254/p/20']
    if dry_run:
        arguments.append('--dry-run')
    arguments.extend(('edlt-scene-manager', '--spec-dir', specs,
                      '--auto-metadata', '--exclusive-project',
                      '--operations', ops_path))
    if not dry_run and backup:
        arguments.extend(('--backup-project', 'SCBACKUP'))
    return cli(relay, evidence['calls'], *arguments,
               expected=expected, complete=complete)


def operation_file(tmp_path, rows):
    path = tmp_path / 'operations.json'
    path.write_text(json.dumps(rows), encoding='utf-8')
    return path


def pp_bytes(root):
    unit = root.find("./Project/Network/Unit[Address='20']")
    parameters = unit.findall('PP')
    names = [parameter.get('Name') for parameter in parameters]
    assert len(names) == len(set(names))
    return {parameter.get('Name'): [int(value, 0) for value in
                                   parameter.get('Value').split()]
            for parameter in parameters}


def verify_preservation(before, after, saved, call, case):
    """Use literal PP and object allowances, independent of product flags."""
    old = ET.fromstring(before)
    new = ET.fromstring(after)
    expected = WIRE['expected_pp']
    outcome = expected['cases'][case]
    changes = set(expected['changed_parameters'])
    old_pp, new_pp = pp_bytes(old), pp_bytes(new)
    assert set(old_pp) == set(new_pp)
    assert {name for name in old_pp if old_pp[name] != new_pp[name]} == changes
    values = {**expected['common_values'],
              **{name: outcome[name] for name in
                 ('SceneBucket', 'ScenesCheckSum', 'OverallCRC')}}
    assert {name: new_pp[name] for name in changes} == values
    assert saved['plan']['scene_manager']['changes'] == values
    sets = [(index, command.split(' ', 4)[3])
            for index, command in enumerate(call['commands'])
            if command.startswith('PP SET ')]
    assert [name for _, name in sets] == expected['set_order']
    assert all(call['statuses'][index] == 200 for index, _ in sets)
    pointers = [new_pp[f'Scene{slot}StartAddress'][0]
                for slot in range(1, 9)]
    assert pointers == expected['scene_pointers']
    bucket = new_pp['SceneBucket']
    assert len(bucket) == 232
    assert bucket[pointers[0] + 2:pointers[0] + 4] == outcome['scene1_trigger_action']
    assert bucket[pointers[1] + 2:pointers[1] + 4] == expected['scene2_trigger_action']
    old_oids = {node.text for node in old.iter('OID')}
    created = saved['objects']
    assert [{key: row[key] for key in expected_row}
            for row, expected_row in zip(created, outcome['objects'], strict=True)
            ] == outcome['objects']
    fresh = {row['oid'] for row in created}
    assert len(fresh) == len(created) and not fresh & old_oids
    for row in created:
        identity = row['oid']
        assert str(uuid.UUID(identity)) == identity
        index = next(n for n, command in enumerate(call['commands'])
                     if command.startswith('DBADDSAFE')
                     and call['terminals'][n] == 'OID=' + identity)
        assert call['statuses'][index] == WIRE['database_add_receipt']['status']
        if row['kind'] == 'Level':
            assert call['commands'].count('DBGET !' + identity + '/OID') == 1
            assert call['commands'].count(
                'DBSETSAFE !' + identity + '/Value ' + str(row['value'])) == 1
    parents = {child: parent for parent in new.iter() for child in parent}
    application = new.find("./Project/Network[Address='254']/Application[Address='202']")
    issued_nodes = {}
    for row, expected_row in zip(created, outcome['objects'], strict=True):
        identity = row['oid']
        matches = [node for node in new.iter()
                   if any(oid.text == identity for oid in node.findall('OID'))]
        assert len(matches) == 1, (identity, len(matches))
        node = matches[0]
        assert node.tag == expected_row['kind']
        assert node.findtext('Address') == str(expected_row['address'])
        assert len(node.findall('OID')) == 1
        owner = parents[node]
        if node.tag == 'Group':
            assert owner is application
            assert node.attrib == {}
        else:
            assert owner.tag == 'Group'
            assert owner.findtext('Address') == str(expected_row['group'])
            assert parents[owner] is application
            assert node.attrib == {'Value': str(expected_row['value'])}
        fields = list(node)[:3]
        assert [field.tag for field in fields] == ['OID', 'TagName', 'Address']
        assert all(not field.attrib and not list(field) for field in fields)
        assert fields[0].text == identity
        assert node.findtext('TagName') == row['name']
        assert all(child.tag == 'Level' for child in list(node)[3:])
        issued_nodes[identity] = node
    for row in created:
        node = issued_nodes[row['oid']]
        expected_levels = [issued_nodes[level['oid']] for level in created
                           if level['kind'] == 'Level'
                           and level.get('group') == row['address']]
        assert list(node)[3:] == (expected_levels if row['kind'] == 'Group' else [])
    # Remove only the uniquely bound descendants before their containers.
    for node in reversed(list(new.iter())):
        if node in issued_nodes.values():
            parents[node].remove(node)
    for root in (old, new):
        unit = root.find("./Project/Network/Unit[Address='20']")
        for parameter in list(unit):
            if parameter.tag == 'PP' and parameter.get('Name') in changes:
                unit.remove(parameter)
    assert graph(ET.tostring(old, encoding='unicode')) == graph(
        ET.tostring(new, encoding='unicode'))


def test_scene_manager_oracle_rejects_unbound_created_metadata():
    """Pure adversarial XML controls, without a client, process or socket."""
    from copy import deepcopy

    expected = WIRE['expected_pp']
    for case in ('action8', 'trigger70_action0'):
        outcome = expected['cases'][case]
        values = {**expected['common_values'],
                  **{name: outcome[name] for name in
                     ('SceneBucket', 'ScenesCheckSum', 'OverallCRC')}}
        old = ET.fromstring(
            '<Installation><Project><Address>TEST</Address><Network>'
            '<Address>254</Address><Application><Address>202</Address>'
            '<Group><OID>00000000-0000-0000-0000-000000000001</OID>'
            '<TagName>Existing</TagName><Address>42</Address></Group>'
            '</Application><Unit><Address>20</Address></Unit>'
            '</Network></Project></Installation>')
        unit = old.find('./Project/Network/Unit')
        for name in values:
            ET.SubElement(unit, 'PP', Name=name, Value='255')
        for slot, value in ((1, 0), (2, 11)):
            ET.SubElement(unit, 'PP', Name=f'Scene{slot}StartAddress',
                          Value=str(value))
        new = deepcopy(old)
        for parameter in new.findall('./Project/Network/Unit/PP'):
            if parameter.get('Name') in values:
                parameter.set('Value', ' '.join(map(str, values[parameter.get('Name')])))
        application = new.find('./Project/Network/Application')
        created, commands, statuses, terminals = [], [], [], []
        for index, row in enumerate(outcome['objects'], start=2):
            identity = str(uuid.UUID(int=index))
            name = f"{row['kind']} {row['address']}"
            parent = (application if row['kind'] == 'Group' else
                      application.find(f"Group[Address='{row['group']}']"))
            node = ET.SubElement(parent, row['kind'])
            for field, value in (('OID', identity), ('TagName', name),
                                 ('Address', str(row['address']))):
                ET.SubElement(node, field).text = value
            if row['kind'] == 'Level':
                node.set('Value', str(row['value']))
            created.append({**row, 'oid': identity, 'name': name})
            commands.append('DBADDSAFE synthetic')
            statuses.append(301)
            terminals.append('OID=' + identity)
            if row['kind'] == 'Level':
                commands.extend((f'DBGET !{identity}/OID',
                                 f"DBSETSAFE !{identity}/Value {row['value']}"))
                statuses.extend((342, 200))
                terminals.extend(('', ''))
        commands.extend('PP SET synthetic ' + name + ' value'
                        for name in expected['set_order'])
        statuses.extend([200] * len(expected['set_order']))
        terminals.extend([''] * len(expected['set_order']))
        saved = {'objects': created,
                 'plan': {'scene_manager': {'changes': values}}}
        call = {'commands': commands, 'statuses': statuses, 'terminals': terminals}
        before = ET.tostring(old, encoding='unicode')
        verify_preservation(before, ET.tostring(new, encoding='unicode'),
                            saved, call, case)
        issued_level = next(row for row in created if row['kind'] == 'Level')
        identity = issued_level['oid']
        for fault in ('duplicate_oid', 'wrong_kind', 'wrong_address',
                      'wrong_owner', 'unexpected_child', 'unexpected_attribute',
                      'duplicate_oid_field', 'unexpected_group_metadata'):
            broken = deepcopy(new)
            node = next(n for n in broken.iter() if n.findtext('OID') == identity)
            parents = {child: parent for parent in broken.iter() for child in parent}
            if fault == 'duplicate_oid':
                parents[node].append(deepcopy(node))
            elif fault == 'wrong_kind':
                node.tag = 'NetVar'
            elif fault == 'wrong_address':
                node.find('Address').text = '99'
            elif fault == 'wrong_owner':
                parents[node].remove(node)
                broken.find('./Project/Network/Application').append(node)
            elif fault == 'unexpected_child':
                ET.SubElement(node, 'Unexpected').text = 'must remain visible'
            elif fault == 'unexpected_attribute':
                node.set('Unexpected', 'must remain visible')
            elif fault == 'duplicate_oid_field':
                ET.SubElement(node, 'OID').text = identity
            elif case == 'trigger70_action0':
                ET.SubElement(parents[node], 'Unexpected').text = 'must remain visible'
            else:
                continue
            with pytest.raises(AssertionError):
                verify_preservation(before, ET.tostring(broken, encoding='unicode'),
                                    saved, call, case)


def verify_action_order(call):
    expected = WIRE['accepted_action_order']
    cursor = 0
    for command in call['commands']:
        wanted = expected[cursor]
        matches = (command.startswith('PP SAVE_TO_SOURCE ')
                   if '<session>' in wanted else command == wanted)
        if matches:
            cursor += 1
            if cursor == len(expected):
                break
    assert cursor == len(expected), call['commands']


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_scene_manager_exact_action_creation(backend, variable, tmp_path):
    """Baseline distinguishes exact getter naming from the Add dialog seed."""
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, specs, _):
        before = snapshot(owner)
        operations = operation_file(tmp_path, [
            {'op': 'set-action', 'scene': 1, 'action': 8}])
        preview, call = scene_cli(relay, evidence, specs, operations, dry_run=True)
        assert not preview['saved']
        assert not any(row.startswith(('DBADD', 'DBSET', 'PROJECT SAVE'))
                       for row in call['commands'])
        saved, call = scene_cli(relay, evidence, specs, operations)
        assert saved['saved'] and saved['existing_metadata_preserved']
        assert sum(row.startswith('PP SAVE') for row in call['commands']) == 1
        node = ET.fromstring(snapshot(owner)).find(
            "./Project/Network/Application[Address='202']/Group[Address='42']/Level[Address='8']")
        assert node.findtext('TagName') == WIRE['exact_getter']['name']
        assert node.get('Value') == '8'
        verify_preservation(before, snapshot(owner), saved, call, 'action8')


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_scene_manager_action_dialog_seed_and_save(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, specs, _):
        operations = operation_file(tmp_path, [
            {'op': 'add-action-dialog', 'scene': 1}])
        before = snapshot(owner)
        preview, call = scene_cli(relay, evidence, specs, operations, dry_run=True)
        assert not preview['saved'] and snapshot(owner) == before
        assert not any(row.startswith(('DBADD', 'DBSET', 'PROJECT SAVE'))
                       for row in call['commands'])
        saved, call = scene_cli(relay, evidence, specs, operations)
        assert saved['saved'] and saved['persistence_verified']
        assert saved['existing_metadata_preserved']
        assert sum(row.startswith('DBADDSAFE') for row in call['commands']) == 1
        assert sum(row.startswith('PP SAVE') for row in call['commands']) == 1
        node = ET.fromstring(snapshot(owner)).find(
            "./Project/Network/Application[Address='202']/Group[Address='42']/Level[Address='8']")
        assert node.findtext('TagName') == WIRE['accepted_action_dialog']['name']
        assert node.get('Value') == '8'
        assert sum(row.startswith('PROJECT SAVE TEST')
                   for row in call['commands']) == 2
        verify_action_order(call)
        verify_preservation(before, snapshot(owner), saved, call, 'action8')


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_scene_manager_dialog_cancel_preserves_metadata(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, specs, _):
        operations = operation_file(tmp_path, [
            {'op': 'add-trigger-dialog', 'scene': 1, 'cancel': True},
            {'op': 'add-action-dialog', 'scene': 1, 'cancel': True}])
        before = snapshot(owner)
        _preview, call = scene_cli(relay, evidence, specs, operations, dry_run=True)
        assert snapshot(owner) == before
        assert not any(row.startswith(('DBADD', 'DBSET', 'PROJECT SAVE'))
                       for row in call['commands'])
        saved, call = scene_cli(relay, evidence, specs, operations, backup=False)
        assert saved['saved'] and saved['existing_metadata_preserved']
        assert not any(row.startswith(('DBADD', 'DBSET', 'PROJECT COPY'))
                       for row in call['commands'])
        verify_preservation(before, snapshot(owner), saved, call, 'cancelled_baseline')


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_scene_manager_trigger_then_action_dialog_order(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, specs, _):
        before = snapshot(owner)
        operations = operation_file(tmp_path, [
            {'op': 'add-trigger-dialog', 'scene': 1},
            {'op': 'add-action-dialog', 'scene': 1}])
        saved, call = scene_cli(relay, evidence, specs, operations)
        assert saved['saved'] and saved['existing_metadata_preserved']
        adds = [row for row in call['commands'] if row.startswith('DBADDSAFE')]
        expected = WIRE['accepted_trigger_then_action_dialog']
        assert adds[0] == expected['group_add']
        assert len(adds) == expected['database_adds']
        assert sum(row.startswith('PP SAVE') for row in call['commands']) == 1
        group = ET.fromstring(snapshot(owner)).find(
            "./Project/Network/Application[Address='202']/Group[Address='70']")
        assert group.findtext('TagName') == 'Trigger Group 70'
        names = {node.findtext('Address'): node.findtext('TagName')
                 for node in group.findall('Level')}
        assert names == expected['level_names']
        verify_preservation(before, snapshot(owner), saved, call, 'trigger70_action0')


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_scene_manager_lost_save_never_replays(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, _relay, evidence, specs, endpoint):
        before = snapshot(owner)
        operations = operation_file(tmp_path, [
            {'op': 'add-action-dialog', 'scene': 1, 'name': 'Accepted Ω'}])
        with FaultGate(endpoint, 'PP SAVE_TO_SOURCE', 'drop') as fault:
            result, call = scene_cli(fault, evidence, specs, operations,
                                     expected=1, complete=False)
            assert fault.matches == 1
            assert sum(row.startswith('PP SAVE') for row in call['commands']) == 1
            detail = result['edlt_scene_metadata_evidence']
            assert detail['pp_save_attempted']
            assert not detail['pp_save_confirmed'] and not detail['saved']
            assert detail['pp_save_outcome_uncertain']
            assert not any(row.startswith('DBDELETE') for row in call['commands'])
            save_index = next(n for n, row in enumerate(call['commands'])
                              if row.startswith('PP SAVE_TO_SOURCE '))
            assert not any(row.startswith(('PROJECT SAVE', 'PROJECT CLOSE',
                                           'PROJECT LOAD'))
                           for row in call['commands'][save_index + 1:])
            forwarded = bytes.fromhex(fault.rows[-1]['forwarded_request_hex']).decode().splitlines()
            assert sum('] PP SAVE_TO_SOURCE ' in row for row in forwarded) == 1
            terminal = bytes.fromhex(fault.rows[-1]['lost_backend_terminal_hex']).decode()
            assert terminal.split('] ', 1)[1].startswith('200 ')
        evidence['lost_save_wires'] = fault.evidence()
        node = ET.fromstring(snapshot(owner)).find(
            "./Project/Network/Application[Address='202']/Group[Address='42']/Level[Address='8']")
        assert node.findtext('TagName') == 'Accepted Ω'
        # The backend applied this one save before its reply was dropped;
        # verify the observed state without claiming confirmed persistence.
        verify_preservation(before, snapshot(owner), detail, call, 'action8')


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_scene_manager_dialog_name_guards_precede_mutation(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, specs, _):
        before = snapshot(owner)
        assert ET.fromstring(before).findtext('./Project/TagName') == 'TEST'
        for name in ('TEST', 'bad#tail', 'two  spaces',
                     'nonbreak\u00a0space', '\ufffe', '\uffff'):
            operations = operation_file(tmp_path, [
                {'op': 'add-action-dialog', 'scene': 1, 'name': name}])
            result, call = scene_cli(relay, evidence, specs, operations, expected=1)
            assert 'error' in result
            assert not any(row.startswith(('DBADD', 'DBSET', 'PROJECT SAVE',
                                           'PROJECT COPY', 'PP '))
                           for row in call['commands'])
            assert snapshot(owner) == before


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_scene_manager_restored_display_name_is_not_retained(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, specs, _):
        before = snapshot(owner)
        operations = operation_file(tmp_path, [
            {'op': 'add-action-dialog', 'scene': 1, 'name': 'Synthetic SceneManager'}])
        saved, call = scene_cli(relay, evidence, specs, operations)
        assert saved['saved']
        node = ET.fromstring(snapshot(owner)).find(
            "./Project/Network/Application[Address='202']/Group[Address='42']/Level[Address='8']")
        assert node.findtext('TagName') == 'Synthetic SceneManager'
        verify_preservation(before, snapshot(owner), saved, call, 'action8')
