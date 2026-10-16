"""One owning thermostat settings transaction on two closed, owned backends.

Inputs and expected deltas are synthetic literal cases. Original source pins
the inherited setback-before-schedule resolution and remote validation; these
tests establish public CLI/database behavior, not original or physical execution.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.file_transfer import prepare_upload, upload
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import Programmer, xml_text
from test_cgate_barcode_database_interop import FaultGate, graph, parse_wire, selected_binary
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend,
)
from test_thermostat_settings import _spec, snapshot


BACKENDS = [('cgate-mock', 'CBUS_CGATE_MOCK_BIN'), ('cmqttd', 'CBUS_CMQTTD_BIN')]
PROJECT = 'THREMOTE'
NETWORK = '//THREMOTE/11'
UNIT = NETWORK + '/p/20'
SOURCE = '/db' + UNIT
BACKUP = 'THBACKUP'
REMOTE = {
    'RemoteSetbackControlSource': 2, 'RemoteSetbackOnGroup': 21,
    'RemoteSetbackOffGroup': 22, 'EvapProgramEnabled': 1,
    'RemoteScheduleOnGroup': 12, 'RemoteScheduleOffGroup': 13,
    'RemoteScheduleOverrideGroup': 14,
}
SAVED_REMOTE = REMOTE | {'RemoteScheduleEnable': 1}
CREATE_ALL = [(203, None, 'Enable Control'), (203, 21, 'Enable Network Variable 21'),
              (203, 22, 'Enable Network Variable 22'), (203, 12, 'Enable Network Variable 12'),
              (203, 13, 'Enable Network Variable 13'), (203, 14, 'Enable Network Variable 14')]
CASES = {
    'programmable-joined': {
        'unit_type': 'PC_TSA', 'edits': REMOTE | {'PlantCycleTime': 23},
        'changed': SAVED_REMOTE | {'PlantCycleTime': 23}, 'creates': CREATE_ALL,
    },
    'programmable-alias-cross-application': {
        'unit_type': 'PC_TSA5', 'groups': {56: [12], 203: [12]},
        'edits': {'RemoteSetbackControlSource': 1, 'RemoteSetbackOnGroup': 12,
                  'RemoteSetbackOffGroup': 13, 'NonEvapProgramEnabled': 1,
                  'RemoteScheduleOnGroup': 12, 'RemoteScheduleOffGroup': 13,
                  'RemoteScheduleOverrideGroup': 14},
        'changed': {'RemoteSetbackControlSource': 1, 'RemoteSetbackOnGroup': 12,
                    'RemoteSetbackOffGroup': 13, 'NonEvapProgramEnabled': 1,
                    'RemoteScheduleEnable': 1, 'RemoteScheduleOnGroup': 12,
                    'RemoteScheduleOffGroup': 13, 'RemoteScheduleOverrideGroup': 14},
        'creates': [(56, 13, 'Group 13'), (203, 13, 'Enable Network Variable 13'),
                    (203, 14, 'Enable Network Variable 14')],
    },
    'basic-lighting': {
        'unit_type': 'PC_TSB', 'groups': {56: [7]},
        'edits': {'RemoteSetbackControlSource': 1, 'RemoteSetbackOnGroup': 7,
                  'RemoteSetbackOffGroup': 8, 'BeepEnable': 1},
        'changed': {'RemoteSetbackControlSource': 1, 'RemoteSetbackOnGroup': 7,
                    'RemoteSetbackOffGroup': 8, 'BeepEnable': 1},
        'creates': [(56, 8, 'Group 8')],
    },
    'basic-alias-one-unused': {
        'unit_type': 'PC_TSB5', 'groups': {56: [], 203: [21]},
        'edits': {'RemoteSetbackControlSource': 2, 'RemoteSetbackOnGroup': 21,
                  'RemoteSetbackOffGroup': 255},
        'changed': {'RemoteSetbackControlSource': 2, 'RemoteSetbackOnGroup': 21,
                    'RemoteSetbackOffGroup': 255},
        'creates': [(203, 255, '<Unused>')],
    },
    'graph-only': {'unit_type': 'PC_TSA', 'seed': SAVED_REMOTE,
                   'edits': {}, 'changed': {}, 'creates': CREATE_ALL},
    'already-present': {
        'unit_type': 'PC_TSA', 'seed': SAVED_REMOTE,
        'groups': {56: [], 203: [21, 22, 12, 13, 14]},
        'edits': {}, 'changed': {}, 'creates': [],
    },
    'disable-still-creates-enable-application': {
        'unit_type': 'PC_TSA', 'seed': SAVED_REMOTE,
        'edits': {'RemoteSetbackControlSource': 0, 'EvapProgramEnabled': 0},
        'changed': {'RemoteSetbackControlSource': 0, 'RemoteSetbackOnGroup': 30,
                    'RemoteSetbackOffGroup': 31, 'EvapProgramEnabled': 0,
                    'RemoteScheduleEnable': 0, 'RemoteScheduleOnGroup': 32,
                    'RemoteScheduleOffGroup': 33, 'RemoteScheduleOverrideGroup': 34},
        'creates': [(203, None, 'Enable Control')],
    },
}


def scalar(parent, name, value):
    ET.SubElement(parent, name).text = str(value)


def document(owner, path='//' + PROJECT):
    return xml_text(NativeDatabase(owner).get(path, xml=True))


def parameters(owner):
    with Programmer(owner).load(NETWORK, SOURCE) as session:
        return session.values()


def numeric(values):
    return {name: int(value, 0) for name, value in values.items()}


def prepare_specs(folder):
    # The existing public synthetic fixture supplies the scalar dependency
    # surface. Literal deltas below do not call any production projection.
    names = set(snapshot()) | {'ApplicationNumber', 'Application', 'UnrelatedParameter'}
    # The CLI resolves the family filename; owned PP backends also receive
    # explicit alias files so no vendor catalogue is required.
    for kind in ('THERMOSTATA', 'THERMOSTATB', 'PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5'):
        (folder / (kind + '.xml')).write_text(_spec(kind, names), encoding='utf-8')


def seed(owner, work, trap, case):
    current = snapshot(**case.get('seed', {}))
    current.update(ApplicationNumber='56', Application='49', UnrelatedParameter='173')
    root = ET.Element('Installation')
    scalar(root, 'DBVersion', '2.3')
    project = ET.SubElement(root, 'Project')
    for name, value in (('OID', uuid.uuid4()), ('TagName', PROJECT), ('Address', PROJECT)):
        scalar(project, name, value)
    project.append(ET.Comment('retain project comment'))
    ET.SubElement(project, '{urn:cbus:synthetic:thermostat}Opaque', exact='yes').text = 'kept Ω'
    for address in (11, 12):
        network = ET.SubElement(project, 'Network')
        for name, value in (('OID', uuid.uuid4()), ('Address', address), ('NetworkNumber', address),
                            ('TagName', 'Closed network ' + str(address))):
            scalar(network, name, value)
        interface = ET.SubElement(network, 'Interface')
        for name, value in (('OID', uuid.uuid4()), ('InterfaceType', 'cni'), ('InterfaceAddress', trap)):
            scalar(interface, name, value)
        if address == 12:
            ET.SubElement(network, '{urn:cbus:synthetic:thermostat}RetainedNetworkMetadata',
                          note='unrelated').text = 'unchanged'
            continue
        for application, addresses in case.get('groups', {56: []}).items():
            app = ET.SubElement(network, 'Application')
            for name, value in (('OID', uuid.uuid4()), ('Address', application),
                                ('TagName', 'Retained ' + str(application))):
                scalar(app, name, value)
            for group_address in addresses:
                group = ET.SubElement(app, 'Group')
                for name, value in (('OID', uuid.uuid4()), ('Address', group_address),
                                    ('TagName', 'Existing same label')):
                    scalar(group, name, value)
                level = ET.SubElement(group, 'Level', Value='207')
                for name, value in (('OID', uuid.uuid4()), ('Address', 7), ('TagName', 'Retained unusual level')):
                    scalar(level, name, value)
                ET.SubElement(level, 'TagsDLT')
        # An unrelated application with a nondefault Level proves that missing
        # optional schedule/setback levels are declined rather than generated.
        app = ET.SubElement(network, 'Application')
        for name, value in (('OID', uuid.uuid4()), ('Address', 202), ('TagName', 'Unrelated Trigger')):
            scalar(app, name, value)
        unit = ET.SubElement(network, 'Unit')
        for name, value in (('OID', uuid.uuid4()), ('Address', 20), ('TagName', 'Selected thermostat'),
                            ('UnitType', case['unit_type']), ('UnitName', 'THERMOSTAT20'),
                            ('FirmwareVersion', '5.4.01'), ('SerialNumber', '123456.7'),
                            ('CatalogNumber', '5070THP,BK' if case['unit_type'].startswith('PC_TSA') else '5070THB,BK')):
            scalar(unit, name, value)
        unit.append(ET.Comment('retained unit metadata'))
        for name, value in current.items():
            ET.SubElement(unit, 'PP', Name=name, Value=value)
        sibling = ET.SubElement(network, 'Unit')
        for name, value in (('OID', uuid.uuid4()), ('Address', 21), ('TagName', 'Unrelated sibling'),
                            ('UnitName', 'Sibling'), ('UnitType', 'KEY1'), ('FirmwareVersion', '1.2.67')):
            scalar(sibling, name, value)
        ET.SubElement(sibling, 'PP', Name='OpaqueSetting', Value='untouched & exact')
    path = work / 'thermostat-synthetic.xml'
    path.write_bytes(ET.tostring(root))
    for command in ('FILE MKDIR Projects', 'FILE MKDIR Projects/archived'):
        assert owner.command(command).code == 200
    assert upload(prepare_upload('Projects/archived/' + path.name, path), owner)['upload_completed']
    for command in ('PROJECT RESTORE ' + PROJECT + ' ' + path.name,
                    'PROJECT USE ' + PROJECT, 'PROJECT SAVE ' + PROJECT):
        assert owner.command(command).code == 200
    return path


@contextmanager
def journey(backend, variable, tmp_path, case_name, case):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'backend')
    specs = tmp_path / 'synthetic-specs'; specs.mkdir()
    prepare_specs(specs)
    evidence = {'format': 'cbus-thermostat-remote-references-owned-v1',
                'backend': backend, 'case': case_name, 'input': deepcopy(case),
                'original_execution': False, 'physical_acceptance': False,
                'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                'specification_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in specs.iterdir()},
                'calls': [], 'wires': [], 'processes': []}
    relay = None
    try:
        with no_contact_trap() as trap, owned_backend(
                backend, binary, work, extra_args=(
                    '--unitspec' if backend == 'cgate-mock' else '--cgate-unitspec', specs)) as (endpoint, process):
            evidence['processes'].append(process)
            with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                fixture = seed(owner, work, trap, case)
                evidence['fixture_sha256'] = hashlib.sha256(fixture.read_bytes()).hexdigest()
                evidence['before_xml'] = document(owner)
                evidence['before_parameters'] = parameters(owner)
                assert document(owner) == evidence['before_xml']
                yield owner, relay, evidence, specs, endpoint
        evidence['closed_graph_trap_contacts'] = 0
    finally:
        if relay is not None:
            evidence['wires'].extend(relay.evidence())
        associated_evidence(tmp_path / 'thermostat-remote-references-evidence.json', evidence)


def settings_cli(relay, evidence, specs, edits, *, action='apply', expected=0, complete=True):
    before = len(relay.rows)
    argv = [sys.executable, '-m', 'cbus_toolkit', 'thermostat', 'settings', action, UNIT,
            '--host', relay.endpoint[0], '--port', str(relay.endpoint[1]), '--timeout', '3',
            '--exclusive-project', '--spec-dir', str(specs)]
    for name, value in edits.items():
        argv.extend(('--set', name + '=' + str(value)))
    if action == 'apply':
        argv.extend(('--backup-project', BACKUP))
    process = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    result = json.loads(process.stdout or process.stderr)
    call = {'argv': argv, 'exit': process.returncode, 'stdout': process.stdout,
            'stderr': process.stderr, 'result': result}
    evidence['calls'].append(call)
    assert process.returncode == expected, call
    assert len(relay.rows) == before + 1
    row = relay.rows[before]
    assert row['done'].wait(5)
    call.update(parse_wire(row, complete=complete), wire_index=before)
    assert not any(command.startswith(('NET OPEN ', 'PP PROGRAM ')) for command in call['commands'])
    assert all('/db' + UNIT in command for command in call['commands'] if command.startswith('PP LOAD '))
    return result, call


def creates_from_commands(commands):
    return [command for command in commands if command.startswith('DBADDSAFE ')]


def expected_creates(case):
    return [('DBADDSAFE ' + NETWORK + ' Application ' + str(app) + ' ' + name)
            if address is None else ('DBADDSAFE ' + NETWORK + '/' + str(app)
                                     + ' Group ' + str(address) + ' ' + name)
            for app, address, name in case['creates']]


def groups(app):
    return [node for node in app if node.tag in ('Group', 'NetVar')]


def assert_preserved(before, after, case):
    """Remove only literal declared additions/PP delta, then compare everything."""
    old, new = (ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(
                    insert_comments=True, insert_pis=True))) for text in (before, after))
    old_network, new_network = old.find("Project/Network[Address='11']"), new.find("Project/Network[Address='11']")
    created_oids = []
    for app_address, address, tag in case['creates']:
        app = new_network.find("Application[Address='" + str(app_address) + "']")
        assert app is not None
        if address is None:
            assert app.findtext('TagName') == tag
            created_oids.append(app.findtext('OID'))
        else:
            candidates = [node for node in groups(app) if node.findtext('Address') == str(address)]
            assert len(candidates) == 1
            node = candidates[0]
            assert node.tag == 'Group'  # Literal retained serialization on both owned Rust backends.
            assert node.findtext('TagName') == tag
            assert node.findall('Level') == []
            created_oids.append(node.findtext('OID'))
    assert len(set(created_oids)) == len(created_oids)
    existing_oids = {node.text for node in old.iter('OID')}
    assert not set(created_oids) & existing_oids
    for app_address, address, _tag in reversed(case['creates']):
        app = new_network.find("Application[Address='" + str(app_address) + "']")
        if address is None:
            assert groups(app) == []
            new_network.remove(app)
        else:
            app.remove(next(node for node in groups(app) if node.findtext('Address') == str(address)))
    retained_pp = []
    for root in (old, new):
        unit = root.find("Project/Network[Address='11']/Unit[Address='20']")
        records = {}
        for node in list(unit):
            if node.tag == 'PP':
                if node.get('Name') not in case['changed']:
                    assert node.get('Name') not in records
                    records[node.get('Name')] = graph(ET.tostring(node, encoding='unicode'))
                unit.remove(node)
        retained_pp.append(records)
    # PP SAVE emits the selected unit's PP collection sorted by Name. Preserve
    # each complete record, independently of that observed collection order.
    assert retained_pp[0] == retained_pp[1]
    assert graph(ET.tostring(old, encoding='unicode')) == graph(ET.tostring(new, encoding='unicode'))
    return created_oids


def assert_values(before, after, changed):
    assert numeric(after) == numeric(before) | changed


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('case_name', list(CASES))
def test_public_remote_settings_combined_save(backend, variable, case_name, tmp_path):
    case = CASES[case_name]
    with journey(backend, variable, tmp_path, case_name, case) as (owner, relay, evidence, specs, _endpoint):
        preview, preview_call = settings_cli(relay, evidence, specs, case['edits'], action='preview')
        assert {row['name']: row['after'] for row in preview['changed_parameters']} == case['changed']
        assert preview['apply_would_mutate'] is bool(case['changed'] or case['creates'])
        assert preview['pp_save_count'] == int(bool(case['changed']))
        assert preview['target_project_save_count'] == int(bool(case['changed'] or case['creates']))
        assert not any(command.startswith(('DBADD', 'DBSET', 'DBDELETE', 'PP SET ', 'PP SAVE',
                                           'PROJECT SAVE ', 'PROJECT COPY ')) for command in preview_call['commands'])
        assert document(owner) == evidence['before_xml']
        result, call = settings_cli(relay, evidence, specs, case['edits'])
        assert result['complete']
        assert result['plan'] == {key: value for key, value in preview.items() if key != 'scope'}
        assert {row['name']: row['after'] for row in result['plan']['changed_parameters']} == case['changed']
        assert creates_from_commands(call['commands']) == expected_creates(case)
        assert sum(command.startswith('PP SAVE_TO_SOURCE ') for command in call['commands']) == bool(case['changed'])
        mutation = bool(case['changed'] or case['creates'])
        assert call['commands'].count('PROJECT SAVE ' + PROJECT) == (2 if mutation else 0)
        assert call['commands'].count('PROJECT COPY ' + PROJECT + ' ' + BACKUP) == int(mutation)
        assert not any(' Level ' in command for command in creates_from_commands(call['commands']))
        if mutation:
            assert result['persistence_verified']
            first_write = next(index for index, command in enumerate(call['commands'])
                               if command.startswith(('DBADD', 'PP SET ', 'PP SAVE_TO_SOURCE ')))
            assert call['commands'].index('PROJECT COPY ' + PROJECT + ' ' + BACKUP) < first_write
            assert call['commands'].count('PROJECT CLOSE ' + PROJECT) == 1
            assert call['commands'].count('PROJECT LOAD ' + PROJECT) == 1
        after, actual = document(owner), parameters(owner)
        assert_values(evidence['before_parameters'], actual, case['changed'])
        created_oids = assert_preserved(evidence['before_xml'], after, case)
        for identity in created_oids:
            reply = owner.command('DBGET !' + identity + '/OID')
            assert reply.code == 342 and reply.lines[-1].endswith('=' + identity)
        if mutation:
            for verb in ('SAVE', 'CLOSE', 'LOAD', 'USE'):
                assert owner.command('PROJECT ' + verb + ' ' + PROJECT).code == 200
        reopened, reloaded = document(owner), parameters(owner)
        assert_values(evidence['before_parameters'], reloaded, case['changed'])
        assert_preserved(evidence['before_xml'], reopened, case)
        evidence.update(preview=preview, result=result, after_xml=after, reopened_xml=reopened,
                        after_parameters=actual, reopened_parameters=reloaded, created_oids=created_oids,
                        preservation_verified=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_remote_reference_collision_refused_before_mutation(backend, variable, tmp_path):
    case = deepcopy(CASES['programmable-joined'])
    case['edits']['RemoteSetbackOnGroup'] = 12
    with journey(backend, variable, tmp_path, 'selected-object-collision', case) as (owner, relay, evidence, specs, _endpoint):
        result, call = settings_cli(relay, evidence, specs, case['edits'], expected=1)
        assert result.get('error')
        assert 'duplicate' in result['error'] and 'group identities' in result['error']
        assert result['thermostat_template_evidence']['outcome_uncertain'] is False
        assert not any(command.startswith(('DBADD', 'DBSET', 'DBDELETE', 'PP SET ', 'PP SAVE',
                                           'PROJECT SAVE ', 'PROJECT COPY ')) for command in call['commands'])
        assert document(owner) == evidence['before_xml']
        assert parameters(owner) == evidence['before_parameters']
        evidence.update(result=result, after_xml=document(owner), after_parameters=parameters(owner))


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('changed_scope', ['unrelated-graph', 'pp'])
def test_public_remote_stale_snapshot_refused_before_backup(backend, variable, changed_scope, tmp_path):
    case = CASES['basic-lighting']
    with journey(backend, variable, tmp_path, 'stale-' + changed_scope, case) as (owner, _relay, evidence, specs, endpoint):
        def mutate():
            if changed_scope == 'unrelated-graph':
                reply = owner.command('DBSETSAFE ' + NETWORK + '/202/TagName External edit')
                assert reply.code == 200
            else:
                with Programmer(owner).load(NETWORK, SOURCE) as session:
                    assert session.set('UnrelatedParameter', '174').code == 200
                    assert session.save_to_source().code == 200
        # The recorded preview selects the project three times: initial use
        # and two fresh PP sessions. Selection four begins apply, before its
        # bound snapshot recheck and before any backup or target mutation.
        with FaultGate(endpoint, 'PROJECT USE', 'change', occurrence=4, callback=mutate) as fault:
            result, call = settings_cli(fault, evidence, specs, case['edits'], expected=1)
            assert fault.matches >= 4 and any(row.get('controlled_change_completed') for row in fault.rows)
        evidence['fault_wires'] = fault.evidence()
        assert result.get('error')
        assert 'changed since planning' in result['error']
        assert result['thermostat_template_evidence']['outcome_uncertain'] is False
        assert not any(command.startswith(('DBADD', 'DBSET', 'DBDELETE', 'PP SET ', 'PP SAVE',
                                           'PROJECT SAVE ', 'PROJECT COPY ')) for command in call['commands'])
        evidence.update(result=result, after_xml=document(owner), after_parameters=parameters(owner))


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('phase', ['PP SAVE_TO_SOURCE', 'PROJECT SAVE'])
def test_public_remote_lost_successful_save_never_replays(backend, variable, phase, tmp_path):
    case = CASES['programmable-joined']
    with journey(backend, variable, tmp_path, 'lost-' + phase, case) as (owner, _relay, evidence, specs, endpoint):
        occurrence = 2 if phase == 'PROJECT SAVE' else 1
        with FaultGate(endpoint, phase, 'drop', occurrence=occurrence) as fault:
            result, call = settings_cli(fault, evidence, specs, case['edits'], expected=1, complete=False)
        assert fault.matches == occurrence
        state = result['thermostat_template_evidence']
        assert state['complete'] is False and state['outcome_uncertain'] is True
        assert state['pp_save_attempted'] is True
        assert state['pp_save_confirmed'] is (phase == 'PROJECT SAVE')
        assert state['target_save_attempted'] is (phase == 'PROJECT SAVE')
        assert state['target_save_confirmed'] is False
        assert state['automatic_retries'] == 0 and state['rollback_performed'] is False
        wires = fault.evidence()
        lost = [row for row in wires if 'lost_backend_terminal_hex' in row]
        assert len(lost) == 1
        assert ' 200 ' in bytes.fromhex(lost[0]['lost_backend_terminal_hex']).decode()
        assert lost[0]['lost_backend_terminal_hex'] not in lost[0]['response_hex']
        assert sum(command.startswith('PP SAVE_TO_SOURCE ') for command in call['commands']) == 1
        assert call['commands'].count('PROJECT SAVE ' + PROJECT) == (2 if phase == 'PROJECT SAVE' else 1)
        assert not any(command.startswith(('DBDELETE', 'PROJECT CLOSE ', 'PROJECT LOAD '))
                       for command in call['commands'])
        after, actual = document(owner), parameters(owner)
        assert_values(evidence['before_parameters'], actual, case['changed'])
        assert_preserved(evidence['before_xml'], after, case)
        evidence.update(result=result, fault_wires=wires, after_xml=after,
                        after_parameters=actual, replay_count=0, saved_response_lost=True)
