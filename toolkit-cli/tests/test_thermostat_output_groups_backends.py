"""Ordinary thermostat output loading and explicit selections on owned backends.

All specifications and projects in this module are public synthetic inputs.
Expected mutations will be literal source-derived cases, not planner output.
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
from test_cgate_barcode_database_interop import FaultGate, parse_wire, selected_binary
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend,
)
from test_thermostat_settings import _spec
import test_thermostat_remote_references_backends as refs


BACKENDS = refs.BACKENDS
NETWORK, PROJECT, UNIT, BACKUP = refs.NETWORK, refs.PROJECT, refs.UNIT, refs.BACKUP
# Spell the public PP fields independently from the implementation's lists.
OUTPUT_FIELDS = (
    'CoolActivationOutput', 'CoolStage1Output', 'CoolStage2Output', 'CoolStage3Output',
    'CoolFanLowOutput', 'CoolFanMediumOutput', 'CoolFanHighOutput',
    'HeatActivationOutput', 'HeatStage1Output', 'HeatStage2Output', 'HeatStage3Output',
    'HeatFanLowOutput', 'HeatFanMediumOutput', 'HeatFanHighOutput',
    'DamperZone1Output', 'DamperZone2Output', 'DamperZone3Output', 'DamperZone4Output',
    'InternalRelay1GroupNumber', 'InternalRelay2GroupNumber', 'InternalRelay3GroupNumber',
    'InternalRelay4GroupNumber', 'InternalRelay5GroupNumber',
)


# These are source-derived literal histories. In particular, the joined case
# retains a rename and two new groups even though later controls select other
# existing objects. The old PP byte is not permission to skip ordinary load.
CASES = {
    'programmable-temporary-unused-fan-swap': {
        'unit_type': 'PC_TSA', 'groups': {56: [20, 21, 22, 255], 172: [1], 203: []},
        'seed': {'CoolFanLowOutput': 20, 'CoolFanMediumOutput': 21, 'CoolFanHighOutput': 22},
        'selections': [('CoolFanLowOutput', 255), ('CoolFanMediumOutput', 20), ('CoolFanLowOutput', 21)],
        'changed': {'CoolFanLowOutput': 21, 'CoolFanMediumOutput': 20},
        'operations': [],
    },
    'programmable-alias-shared-load-order': {
        'unit_type': 'PC_TSA5', 'groups': {56: [0, 1, 30, 31, 255], 172: [1], 203: []},
        'group_tags': {56: {1: '[CG01] Previous stage name'}},
        'seed': refs.SAVED_REMOTE | {'CoolStage1Output': 1, 'DamperZone1Output': 40,
                                   'InternalRelay1GroupNumber': 41, 'InternalPlantZones': 3},
        'selections': [('CoolStage1Output', 30), ('CoolStage1Output', 31),
                       ('CoolStage1Output', 30), ('InternalRelay1GroupNumber', 0)],
        'changed': {'CoolStage1Output': 30, 'InternalRelay1GroupNumber': 0},
        'operations': [('create', 203, 21, 'Enable Network Variable 21'),
                       ('create', 203, 22, 'Enable Network Variable 22'),
                       ('rename', 56, 1, '[CG01] Y (heat/cool)'),
                       ('create', 56, 40, '[CG01] Damper Zone 1'),
                       ('create', 56, 41, 'Group 41'),
                       ('create', 203, 12, 'Enable Network Variable 12'),
                       ('create', 203, 13, 'Enable Network Variable 13'),
                       ('create', 203, 14, 'Enable Network Variable 14')],
    },
    'basic-generated-peer-and-unused-damper': {
        'unit_type': 'PC_TSB', 'groups': {56: [20, 255], 172: [1], 203: []},
        'group_tags': {56: {20: '[CG01] Y (heat/cool)'}},
        'seed': {'CoolStage1Output': 1, 'DamperZone1Output': 77},
        'selections': [('HeatStage1Output', 20)],
        'changed': {'CoolStage1Output': 20, 'HeatStage1Output': 20, 'DamperZone1Output': 255},
        'operations': [],
    },
    'basic-alias-create-prefix-and-reassign': {
        'unit_type': 'PC_TSB5', 'groups': {56: [0, 30, 255], 203: []},
        'seed': {'InternalPlantType': 1, 'HeatStage1Output': 5},
        'selections': [('HeatStage1Output', 30), ('InternalRelay1GroupNumber', 0)],
        'changed': {'HeatStage1Output': 30, 'InternalRelay1GroupNumber': 0},
        'operations': [('create', 172, None, 'Air Conditioning'),
                       ('create', 172, 1, 'Communication Group 1'),
                       ('create', 56, 5, '[CG01] W (heat)')],
    },
    'resolve-only-rename-without-pp-change': {
        'unit_type': 'PC_TSA', 'groups': {56: [1, 255], 172: [1], 203: []},
        'group_tags': {56: {1: '[CG01] Previous stage name'}},
        'seed': {'CoolStage1Output': 1}, 'selections': [], 'changed': {},
        'operations': [('rename', 56, 1, '[CG01] Y (heat/cool)')],
    },
}

REFUSALS = {
    'direct-excluded-fan-swap': deepcopy(CASES['programmable-temporary-unused-fan-swap']) | {
        'selections': [('CoolFanLowOutput', 21), ('CoolFanMediumOutput', 20)],
        'error_contains': 'Fan selector excludes'},
    'ambiguous-generated-peer': {
        'unit_type': 'PC_TSA', 'groups': {56: [20, 21, 255], 172: [1], 203: []},
        'group_tags': {56: {20: '[CG01] Y (heat/cool)', 21: '[CG01] Y (heat/cool)'}},
        'seed': {'CoolStage1Output': 1}, 'selections': [],
        'error_contains': 'ambiguous'},
}


def parse(text):
    return ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(
        insert_comments=True, insert_pis=True)))


def prepare_specs(folder):
    names = set(refs.snapshot()) | set(OUTPUT_FIELDS) | {
        'ApplicationNumber', 'Application', 'UnrelatedParameter', 'ZoneGroup', 'InstallationCode'}
    for kind in ('THERMOSTATA', 'THERMOSTATB', 'PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5'):
        (folder / (kind + '.xml')).write_text(_spec(kind, names), encoding='utf-8')


def seed(owner, work, trap, case):
    seeded = deepcopy(case)
    seeded['seed'] = dict.fromkeys(OUTPUT_FIELDS, 255) | {
        'ZoneGroup': 1, 'InstallationCode': 1} | seeded.get('seed', {})
    source = refs.seed(owner, work, trap, seeded)
    root = parse(source.read_text())
    selected = root.find("Project/Network[Address='11']")
    for app in selected.findall('Application'):
        application = int(app.findtext('Address'))
        for group in refs.groups(app):
            address = int(group.findtext('Address'))
            tag = case.get('group_tags', {}).get(application, {}).get(address)
            if tag is not None:
                group.find('TagName').text = tag
            # Two distinct addresses/values and nonempty DLT data must survive
            # any parent group rename, reuse, or explicit reassignment.
            level = group.find('Level')
            label = ET.SubElement(level.find('TagsDLT'), 'TagDLT')
            for name, value in (('LanguageID', 1), ('FlavourID', 1),
                                ('TagType', 'TEXT'), ('TagValue', 'Retain Ω ' + str(address))):
                refs.scalar(label, name, value)
            extra = ET.SubElement(group, 'Level', Value='1')
            for name, value in (('OID', uuid.uuid4()), ('Address', 200),
                                ('TagName', 'Unrelated level at another address')):
                refs.scalar(extra, name, value)
            ET.SubElement(extra, 'TagsDLT')
    path = work / 'thermostat-output-groups-synthetic.xml'
    path.write_bytes(ET.tostring(root))
    assert upload(prepare_upload('Projects/archived/' + path.name, path), owner)['upload_completed']
    for command in ('PROJECT CLOSE ' + PROJECT, 'PROJECT DELETE ' + PROJECT,
                    'PROJECT RESTORE ' + PROJECT + ' ' + path.name,
                    'PROJECT USE ' + PROJECT, 'PROJECT SAVE ' + PROJECT):
        assert owner.command(command).code == 200
    return path


@contextmanager
def journey(backend, variable, tmp_path, name, case):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'backend')
    specs = tmp_path / 'synthetic-specs'
    specs.mkdir()
    prepare_specs(specs)
    evidence = {
        'format': 'cbus-thermostat-output-groups-owned-v1', 'backend': backend,
        'case': name, 'input': deepcopy(case), 'original_execution': False,
        'physical_acceptance': False, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
        'specification_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in specs.iterdir()},
        'calls': [], 'wires': [], 'processes': [],
    }
    relay = None
    try:
        with no_contact_trap() as trap, owned_backend(
                backend, binary, work, extra_args=(
                    '--unitspec' if backend == 'cgate-mock' else '--cgate-unitspec', specs)) as (endpoint, process):
            evidence['processes'].append(process)
            with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                fixture = seed(owner, work, trap, case)
                evidence.update(fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                                before_xml=refs.document(owner), before_parameters=refs.parameters(owner))
                assert refs.document(owner) == evidence['before_xml']
                yield owner, relay, evidence, specs, endpoint
        evidence['closed_graph_trap_contacts'] = 0
    finally:
        if relay is not None:
            evidence['wires'].extend(relay.evidence())
        associated_evidence(tmp_path / 'thermostat-output-groups-evidence.json', evidence)


def settings_cli(relay, evidence, specs, case, *, action='apply', expected=0, complete=True):
    start = len(relay.rows)
    argv = [sys.executable, '-m', 'cbus_toolkit', 'thermostat', 'settings', action, UNIT,
            '--host', relay.endpoint[0], '--port', str(relay.endpoint[1]), '--timeout', '3',
            '--exclusive-project', '--spec-dir', str(specs)]
    selections = case['selections']
    if not selections:
        argv.append('--resolve-output-groups')
    for parameter, address in selections:
        argv.extend(('--output-group', parameter + '=' + str(address)))
    if action == 'apply':
        argv.extend(('--backup-project', BACKUP))
    process = subprocess.run(argv, capture_output=True, text=True, timeout=45)
    call = {'argv': argv, 'exit': process.returncode, 'stdout': process.stdout,
            'stderr': process.stderr}
    evidence['calls'].append(call)
    try:
        result = json.loads(process.stdout or process.stderr)
    except json.JSONDecodeError:
        pytest.fail('Public CLI did not emit JSON: ' + repr(call))
    call['result'] = result
    assert process.returncode == expected, call
    assert len(relay.rows) == start + 1
    row = relay.rows[start]
    assert row['done'].wait(5)
    call.update(parse_wire(row, complete=complete), wire_index=start)
    assert not any(command.startswith(('NET OPEN ', 'PP PROGRAM ')) for command in call['commands'])
    assert all('/db' + UNIT in command for command in call['commands'] if command.startswith('PP LOAD '))
    return result, call


def group_at(root, application, address):
    app = root.find("Project/Network[Address='11']/Application[Address='" + str(application) + "']")
    assert app is not None
    found = [node for node in refs.groups(app) if node.findtext('Address') == str(address)]
    assert len(found) == 1
    return found[0]


def literal_creates(case):
    return [(app, address, name) for action, app, address, name in case['operations'] if action == 'create']


def assert_preserved(before, after, case):
    """Undo only literal allowed names; the old oracle checks every other cell."""
    old, new = parse(before), parse(after)
    renamed = []
    for action, application, address, name in case['operations']:
        if action != 'rename':
            continue
        original, actual = group_at(old, application, address), group_at(new, application, address)
        identity = original.findtext('OID')
        assert actual.findtext('OID') == identity
        assert actual.findtext('TagName') == name
        renamed.append({'application': application, 'address': address, 'oid': identity,
                        'before': original.findtext('TagName'), 'after': name})
        actual.find('TagName').text = original.findtext('TagName')
    created = refs.assert_preserved(before, ET.tostring(new, encoding='unicode'),
                                   {'creates': literal_creates(case), 'changed': case['changed']})
    return created, renamed


def expected_mutations(case, before):
    root = parse(before)
    commands = []
    for action, application, address, name in case['operations']:
        if action == 'create':
            commands.extend(refs.expected_creates({'creates': [(application, address, name)]}))
        else:
            oid = group_at(root, application, address).findtext('OID')
            commands.append('DBSETSAFE !' + oid + '/TagName ' + name)
    return commands


def assert_plan(preview, case):
    assert {row['name']: row['after'] for row in preview['changed_parameters']} == case['changed']
    mutation = bool(case['changed'] or case['operations'])
    assert preview['apply_would_mutate'] is mutation
    assert preview['pp_save_count'] == int(bool(case['changed']))
    assert preview['target_project_save_count'] == int(mutation)
    remote = preview['remote_references']
    assert remote['output_selections'] == [
        {'parameter': parameter, 'address': address} for parameter, address in case['selections']]
    operations = [(row['action'], row['application'],
                   None if row['kind'] == 'Application' else row['address'], row['name'])
                  for row in remote['graph_operations']]
    assert operations == case['operations']
    assert remote['planned_level_creations'] == []
    projection = remote['output_projection']
    assert projection['prefix'] == '[CG01]'
    assert [(row['parameter'], row['address']) for row in projection['selections']] == case['selections']
    assert set(projection['expected']) == set(OUTPUT_FIELDS)
    if case['selections'] and case['selections'][0] == ('CoolFanLowOutput', 255):
        assert [row['changed'] for row in projection['selections']] == [True, True, True]
        assert projection['expected']['CoolFanHighOutput'] == 22
    return remote


def assert_graph_wire(call, before, case, *, rename_confirmed=True):
    commands = call['commands']
    mutations = [command for command in commands if command.startswith(('DBADD', 'DBSET', 'DBDELETE'))]
    assert mutations == expected_mutations(case, before)
    old = parse(before)
    for action, application, address, name in case['operations']:
        if action == 'create':
            command = refs.expected_creates({'creates': [(application, address, name)]})[0]
            index = commands.index(command)
            assert call['statuses'][index] == 301
            terminal = call['terminals'][index]
            assert terminal.startswith('OID=')
            oid = terminal[4:]
            assert str(uuid.UUID(oid)) == oid
            assert commands[index + 1] == 'DBGET !' + oid + '/OID'
            assert call['statuses'][index + 1] == 342
            assert call['terminals'][index + 1] == '!' + oid + '/OID=' + oid
        else:
            original = group_at(old, application, address)
            oid, previous = original.findtext('OID'), original.findtext('TagName')
            command = 'DBSETSAFE !' + oid + '/TagName ' + name
            index = commands.index(command)
            assert commands[index - 2:index] == ['DBGET !' + oid + '/OID', 'DBGET !' + oid + '/TagName']
            assert call['statuses'][index - 2:index] == [342, 342]
            assert call['terminals'][index - 2:index] == ['!' + oid + '/OID=' + oid,
                                                       '!' + oid + '/TagName=' + previous]
            assert call['statuses'][index] == (200 if rename_confirmed else None)


def assert_no_mutation(call):
    assert not any(command.startswith(('DBADD', 'DBSET', 'DBDELETE', 'PP SET ', 'PP SAVE',
                                       'PROJECT SAVE ', 'PROJECT COPY ')) for command in call['commands'])


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('case_name', list(CASES))
def test_public_output_group_load_and_ordered_selections(backend, variable, case_name, tmp_path):
    case = CASES[case_name]
    with journey(backend, variable, tmp_path, case_name, case) as (owner, relay, evidence, specs, _endpoint):
        preview, preview_call = settings_cli(relay, evidence, specs, case, action='preview')
        assert_plan(preview, case)
        assert_no_mutation(preview_call)
        assert refs.document(owner) == evidence['before_xml']
        assert refs.parameters(owner) == evidence['before_parameters']
        result, call = settings_cli(relay, evidence, specs, case)
        assert result['complete'] and result['persistence_verified']
        assert result['plan'] == {key: value for key, value in preview.items() if key != 'scope'}
        assert_graph_wire(call, evidence['before_xml'], case)
        commands = call['commands']
        assert sum(command.startswith('PP SAVE_TO_SOURCE ') for command in commands) == int(bool(case['changed']))
        assert commands.count('PROJECT SAVE ' + PROJECT) == 2  # backup source, then owning target save
        assert commands.count('PROJECT COPY ' + PROJECT + ' ' + BACKUP) == 1
        assert commands.count('PROJECT CLOSE ' + PROJECT) == 1
        assert commands.count('PROJECT LOAD ' + PROJECT) == 1
        first_mutation = next(index for index, command in enumerate(commands)
                              if command.startswith(('DBADD', 'DBSET', 'PP SET ', 'PP SAVE_TO_SOURCE ')))
        assert commands.index('PROJECT COPY ' + PROJECT + ' ' + BACKUP) < first_mutation
        assert not any(command.startswith('DBDELETE') or ' Level ' in command for command in commands)
        assert len(result['renames']) == sum(action == 'rename' for action, *_ in case['operations'])
        assert all(row['attempted'] and row['confirmed'] for row in result['renames'])
        after, actual = refs.document(owner), refs.parameters(owner)
        refs.assert_values(evidence['before_parameters'], actual, case['changed'])
        created, renamed = assert_preserved(evidence['before_xml'], after, case)
        for oid in created + [row['oid'] for row in renamed]:
            reply = owner.command('DBGET !' + oid + '/OID')
            assert reply.code == 342 and reply.lines == ('342 !' + oid + '/OID=' + oid,)
        # A second independently issued persistence cycle proves these effects
        # survive apart from the owner's own verification session.
        for verb in ('SAVE', 'CLOSE', 'LOAD', 'USE'):
            assert owner.command('PROJECT ' + verb + ' ' + PROJECT).code == 200
        reopened, reloaded = refs.document(owner), refs.parameters(owner)
        refs.assert_values(evidence['before_parameters'], reloaded, case['changed'])
        assert_preserved(evidence['before_xml'], reopened, case)
        evidence.update(preview=preview, result=result, after_xml=after, reopened_xml=reopened,
                        after_parameters=actual, reopened_parameters=reloaded, created_oids=created,
                        renamed_groups=renamed, preservation_verified=True, independent_reopen=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('case_name', list(REFUSALS))
def test_public_output_group_refusal_before_backup(backend, variable, case_name, tmp_path):
    case = REFUSALS[case_name]
    with journey(backend, variable, tmp_path, case_name, case) as (owner, relay, evidence, specs, _endpoint):
        result, call = settings_cli(relay, evidence, specs, case, expected=1)
        assert case['error_contains'] in result['error']
        assert result['thermostat_template_evidence']['outcome_uncertain'] is False
        assert_no_mutation(call)
        assert refs.document(owner) == evidence['before_xml']
        assert refs.parameters(owner) == evidence['before_parameters']
        evidence.update(result=result, after_xml=refs.document(owner),
                        after_parameters=refs.parameters(owner), refusal_before_backup=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_output_group_lost_successful_rename_never_replays(backend, variable, tmp_path):
    case = CASES['resolve-only-rename-without-pp-change']
    with journey(backend, variable, tmp_path, 'lost-successful-group-rename', case) as (owner, _relay, evidence, specs, endpoint):
        with FaultGate(endpoint, 'DBSETSAFE', 'drop') as fault:
            result, call = settings_cli(fault, evidence, specs, case, expected=1, complete=False)
        assert fault.matches == 1
        state = result['thermostat_template_evidence']
        assert state['complete'] is False and state['outcome_uncertain'] is True
        assert state['graph_mutation_outcome_uncertain'] is True
        assert state['automatic_retries'] == 0 and state['rollback_performed'] is False
        assert state['pp_save_attempted'] is False and state['target_save_attempted'] is False
        assert len(state['renames']) == 1
        assert state['renames'][0]['attempted'] is True and state['renames'][0]['confirmed'] is False
        assert_graph_wire(call, evidence['before_xml'], case, rename_confirmed=False)
        assert call['commands'].count('PROJECT SAVE ' + PROJECT) == 1  # only the pre-mutation backup
        assert call['commands'].count('PROJECT COPY ' + PROJECT + ' ' + BACKUP) == 1
        assert not any(command.startswith(('DBDELETE', 'PP SET ', 'PP SAVE', 'PROJECT CLOSE ', 'PROJECT LOAD '))
                       for command in call['commands'])
        wires = fault.evidence()
        lost = [row for row in wires if 'lost_backend_terminal_hex' in row]
        assert len(lost) == 1
        assert ' 200 ' in bytes.fromhex(lost[0]['lost_backend_terminal_hex']).decode()
        assert lost[0]['lost_backend_terminal_hex'] not in lost[0]['response_hex']
        after, actual = refs.document(owner), refs.parameters(owner)
        refs.assert_values(evidence['before_parameters'], actual, {})
        created, renamed = assert_preserved(evidence['before_xml'], after, case)
        assert created == [] and len(renamed) == 1
        evidence.update(result=result, fault_wires=wires, after_xml=after,
                        after_parameters=actual, renamed_groups=renamed,
                        preservation_verified=True, replay_count=0, rename_response_lost=True)
