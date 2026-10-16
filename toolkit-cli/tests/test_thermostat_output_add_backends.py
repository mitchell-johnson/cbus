"""Typed thermostat output Add histories on two explicitly owned backends.

Public synthetic fixtures and literal dialog expectations are independent of
the production planner. No vendor instructions or physical endpoint runs.
"""
from contextlib import contextmanager
import hashlib
import json
import re
import subprocess
import sys
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateError
from cbus_toolkit.file_transfer import prepare_upload, upload
from test_cgate_barcode_database_interop import FaultGate, graph, parse_wire
import test_thermostat_output_groups_backends as outputs
import test_thermostat_remote_levels_backends as levels


refs = outputs.refs
BACKENDS = outputs.BACKENDS
NETWORK, PROJECT, UNIT, BACKUP = outputs.NETWORK, outputs.PROJECT, outputs.UNIT, outputs.BACKUP


def select(parameter, address):
    return {'op': 'select-output-group', 'parameter': parameter, 'address': address}


def add(parameter, outcome='accept', **edits):
    return {'op': 'add-output-group', 'parameter': parameter, 'outcome': outcome, **edits}


def complete_response(owner, command):
    """Retain complete expected refusal replies without treating them as I/O loss."""
    try:
        return owner.command(command)
    except CGateError as error:
        return error.response


CASES = {
    'cancel-provisional-name-collision-noop': {
        'unit_type': 'PC_TSA5', 'groups': {56: [1, 20, 255], 172: [1], 203: []},
        'group_tags': {56: {20: 'Group 0'}},
        'history': [add('InternalRelay1GroupNumber', 'cancel')],
        'dialogs': [(1, 'cancel', 0, 'Group 0', None, None)],
        'changed': {}, 'creates': [],
    },
    'fan-adds-use-evolving-numeric-inventory': {
        'unit_type': 'PC_TSA', 'groups': {56: [1, 20, 255], 172: [1], 203: []},
        'group_tags': {56: {20: 'Group 0'}},
        'history': [select('CoolFanLowOutput', 20), add('CoolFanLowOutput', 'cancel'),
                    add('CoolFanLowOutput', address=5),
                    add('CoolFanMediumOutput', name='  Fresh fan\t '), add('CoolFanHighOutput')],
        'dialogs': [(2, 'cancel', 0, 'Group 0', None, None),
                    (3, 'accept', 0, 'Group 0', 5, 'Group 5'),
                    (4, 'accept', 0, 'Group 0', 0, 'Fresh fan'),
                    (5, 'accept', 2, 'Group 2', 2, 'Group 2')],
        'changed': {'CoolFanLowOutput': 5, 'CoolFanMediumOutput': 0, 'CoolFanHighOutput': 2},
        'creates': [(56, 5, 'Group 5'), (56, 0, 'Fresh fan'), (56, 2, 'Group 2')],
    },
    'basic-interleaved-add-retained-after-reselection': {
        'unit_type': 'PC_TSB', 'groups': {56: [20, 30, 255], 172: [1], 203: []},
        'group_tags': {56: {20: 'ÉPump  Ω'}}, 'seed': {'HeatStage1Output': 30},
        'history': [select('HeatStage1Output', 20),
                    add('HeatStage1Output', address=4, name=' \téPump  Ω\t '),
                    select('HeatStage1Output', 30)],
        'dialogs': [(2, 'accept', 0, 'Group 0', 4, 'éPump  Ω')],
        'changed': {}, 'creates': [(56, 4, 'éPump  Ω')],
    },
    'basic-alias-shared-enable-and-accepted-levels': {
        'unit_type': 'PC_TSB5', 'application': 203,
        'groups': {56: [], 172: [1], 203: [0, 1, 255]},
        'seed': {'RemoteSetbackControlSource': 2, 'RemoteSetbackOnGroup': 0,
                 'RemoteSetbackOffGroup': 255},
        'history': [add('InternalRelay1GroupNumber')],
        'dialogs': [(1, 'accept', 2, 'Enable Network Variable 2', 2, 'Enable Network Variable 2')],
        'prompts': {'setback': 'accept', 'schedule': 'decline'},
        'roles': [(203, 0, 'Setbk', 'Enable')],
        'changed': {'InternalRelay1GroupNumber': 2},
        'creates': [(203, 2, 'Enable Network Variable 2')],
    },
    'slave-damper-add-retains-group-and-normalizes-plant': {
        'unit_type': 'PC_TSA', 'groups': {56: [255], 172: [1], 203: []},
        'seed': {'ControlledZones': 0, 'InternalPlantType': 3, 'InternalPlantZones': 3},
        'history': [add('DamperZone1Output')],
        'dialogs': [(1, 'accept', 0, 'Group 0', 0, 'Group 0')],
        'changed': {'InternalPlantType': 0, 'InternalPlantZones': 0},
        'creates': [(56, 0, 'Group 0')],
    },
}

REFUSALS = {
    'later-add-sees-earlier-name': {
        'unit_type': 'PC_TSA', 'groups': {56: [255], 172: [1], 203: []},
        'history': [add('CoolStage1Output', name='Shared name'),
                    add('CoolStage2Output', name='shared NAME')],
        'error_contains': '2203',
    },
    'accepted-add-then-final-reference-collision': {
        'unit_type': 'PC_TSA', 'groups': {56: [255], 172: [1], 203: []},
        'history': [add('CoolStage1Output'), select('CoolStage2Output', 0)],
        'error_contains': 'duplicate cooling group identities',
    },
}


@contextmanager
def journey(backend, variable, tmp_path, name, case):
    """Reuse the frozen accepted fixture; alter only selected-app input if needed."""
    try:
        with outputs.journey(backend, variable, tmp_path, name, case) as data:
            owner, relay, evidence, specs, endpoint = data
            evidence['format'] = 'cbus-thermostat-output-add-owned-v1'
            if case.get('application', 56) != 56:
                root = outputs.parse(refs.document(owner))
                pp = root.find("Project/Network[Address='11']/Unit[Address='20']/PP[@Name='ApplicationNumber']")
                assert pp is not None
                pp.set('Value', str(case['application']))
                fixture = tmp_path / 'output-add-selected-application-synthetic.xml'
                fixture.write_bytes(ET.tostring(root))
                assert upload(prepare_upload('Projects/archived/' + fixture.name, fixture), owner)['upload_completed']
                for command in ('PROJECT CLOSE ' + PROJECT, 'PROJECT DELETE ' + PROJECT,
                                'PROJECT RESTORE ' + PROJECT + ' ' + fixture.name,
                                'PROJECT USE ' + PROJECT, 'PROJECT SAVE ' + PROJECT):
                    assert owner.command(command).code == 200
                evidence.update(fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                                before_xml=refs.document(owner), before_parameters=refs.parameters(owner))
            try:
                yield owner, relay, evidence, specs, endpoint
            finally:
                # Retain fresh partial state even when the owning command or
                # an independent preservation assertion fails.
                try:
                    evidence['terminal_xml'] = refs.document(owner)
                except Exception as error:
                    evidence['terminal_readback_error'] = repr(error)
                evidence['terminal_parameters'] = refs.parameters(owner)
    finally:
        original = tmp_path / 'thermostat-output-groups-evidence.json'
        if original.exists():
            original.rename(tmp_path / 'thermostat-output-add-evidence.json')


def settings_cli(relay, evidence, specs, case, *, action='apply', expected=0, complete=True):
    start = len(relay.rows)
    argv = [sys.executable, '-m', 'cbus_toolkit', 'thermostat', 'settings', action, UNIT,
            '--host', relay.endpoint[0], '--port', str(relay.endpoint[1]), '--timeout', '5',
            '--exclusive-project', '--spec-dir', str(specs)]
    for operation in case['history']:
        # Shorthand selections on both sides of a JSON Add must retain their
        # actual command-line order. No mapping can represent this history.
        if operation['op'] == 'select-output-group':
            argv.extend(('--output-group', operation['parameter'] + '=' + str(operation['address'])))
        else:
            argv.extend(('--output-operation', json.dumps(operation, ensure_ascii=False)))
    for name, response in case.get('prompts', {}).items():
        argv.extend(('--' + name + '-levels', response))
    if action == 'apply':
        argv.extend(('--backup-project', BACKUP))
    process = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    call = {'argv': argv, 'exit': process.returncode, 'stdout': process.stdout, 'stderr': process.stderr}
    evidence['calls'].append(call)
    try:
        value = json.loads(process.stdout or process.stderr)
    except json.JSONDecodeError:
        pytest.fail('Public CLI did not emit JSON: ' + repr(call))
    call['result'] = value
    assert len(relay.rows) == start + 1 and relay.rows[start]['done'].wait(5)
    call.update(parse_wire(relay.rows[start], complete=complete), wire_index=start)
    assert process.returncode == expected, call
    assert not any(command.startswith(('NET OPEN ', 'PP PROGRAM ', 'DBDELETE')) for command in call['commands'])
    assert all('/db' + UNIT in command for command in call['commands'] if command.startswith('PP LOAD '))
    return value, call


def literal_levels(case):
    return levels.literal_levels({'roles': case.get('roles', []), 'groups': case['groups']})


def inspect_plan(preview, before, case):
    expected_levels = literal_levels(case)
    mutation = bool(case['changed'] or case['creates'] or expected_levels)
    assert {row['name']: row['after'] for row in preview['changed_parameters']} == case['changed']
    assert preview['apply_would_mutate'] is mutation
    assert preview['pp_save_count'] == int(bool(case['changed']))
    assert preview['target_project_save_count'] == int(mutation)
    remote = preview['remote_references']
    assert remote['output_operations'] == case['history']
    projection = preview['output_projection']
    assert projection == remote['output_projection']
    accepted = any(row.get('outcome') == 'accept' for row in case['history'])
    assert projection['project_tag_name'] == (PROJECT if accepted else None)
    assert [(row['position'], row['op'], row['parameter']) for row in projection['operations']] == [
        (position, row['op'], row['parameter']) for position, row in enumerate(case['history'], 1)]
    assert [(row['position'], row['outcome'], row['first_free_address'], row['seeded_name'],
             row['address'], row['name']) for row in projection['add_dialogs']] == case['dialogs']
    inventory = set(case['groups'][case.get('application', 56)])
    for row in projection['add_dialogs']:
        request = case['history'][row['position'] - 1]
        assert row['application'] == case.get('application', 56) and row['kind'] == 'Group'
        assert row['existing_group_count'] == len(inventory)
        assert row['free_address_count'] == 255 - len(inventory - {255})
        assert row['operator_address'] is ('address' in request)
        assert row['operator_name'] is ('name' in request)
        if row['outcome'] == 'cancel':
            assert row['identity'] == row['previous_identity']
            assert row['changed'] is False and row['object_created'] is False
            assert row['address_selected_name'] is None and row['entered_name'] is None
        else:
            assert row['identity'] != row['previous_identity']
            assert row['changed'] is True and row['object_created'] is True
            assert row['address'] not in inventory
            inventory.add(row['address'])
    assert [(row['application'], row['address'], row['name']) for row in remote['planned_creations']] == case['creates']
    assert all(row['kind'] == 'Group' for row in remote['planned_creations'])
    assert remote['planned_renames'] == []
    assert [(row['action'], row['application'], row['address'], row['name'])
            for row in remote['graph_operations']] == [('create', *row) for row in case['creates']]
    assert [(row['application'], row['group'], row['address'], row['value'], row['name'])
            for row in remote['planned_level_creations']] == [
        (row['application'], row['group'], row['address'], row['value'], row['tag']) for row in expected_levels]
    if expected_levels:
        assert len(expected_levels) == 30
        assert remote['level_prompts']['setback']['executed'] is True
        assert remote['level_prompts']['setback']['created_count'] == 30
        assert remote['level_prompts']['schedule']['executed'] is False
    if case.get('seed', {}).get('ControlledZones') == 0:
        assert projection['resolved_references']['DamperZone1Output']['address'] == 0
        assert projection['expected']['DamperZone1Output'] == 255
        assert preview['pp_save_count'] == 1  # inherited slave plant/zones normalization
    return expected_levels


# Explicit source-encoded wire literals, independent of the production encoder.
QUOTED_TAGS = {
    'Group 5': '"Group 5"', 'Fresh fan': '"Fresh fan"', 'Group 2': '"Group 2"',
    'éPump  Ω': '"éPump\\ \\ Ω"',
    'Enable Network Variable 2': '"Enable Network Variable 2"',
    'Group 0': '"Group 0"',
}


def application_oid(before, application):
    node = outputs.parse(before).find(
        "Project/Network[Address='11']/Application[Address='" + str(application) + "']/OID")
    assert node is not None
    return node.text


def add_commands(before, case):
    return ['DBADD !' + application_oid(before, app) + ' Group' for app, _address, _name in case['creates']]


def inspect_group_wire(call, before, case):
    commands = call['commands']
    indices = [index for index, command in enumerate(commands) if command.startswith('DBADD ')]
    assert [commands[index] for index in indices] == add_commands(before, case)
    assert not any(command.startswith('DBADDSAFE ') and ' Level ' not in command for command in commands)
    issued = {}
    prior = {node.text for node in outputs.parse(before).iter('OID')}
    objects = call['result']['objects']
    assert len(objects) == len(case['creates'])
    for row, index, receipt in zip(case['creates'], indices, objects):
        application, address, name = row
        parent = NETWORK + '/' + str(application)
        parent_oid = application_oid(before, application)
        assert commands[index - 1] == 'DBGET ' + parent + '/OID'
        assert call['statuses'][index - 1] == 342
        assert call['terminals'][index - 1] == parent + '/OID=' + parent_oid
        assert call['statuses'][index] == 301
        oid = levels.issued_oid(call['terminals'][index])
        assert oid not in prior and oid not in issued.values()
        assert commands[index + 1:index + 4] == [
            'DBGET !' + oid + '/OID', 'DBSET !' + oid + '/Address ' + str(address),
            'DBSET !' + oid + '/TagName ' + QUOTED_TAGS[name]]
        assert call['statuses'][index + 1:index + 4] == [342, 200, 200]
        assert call['terminals'][index + 1] == '!' + oid + '/OID=' + oid
        assert receipt['oid'] == oid and receipt['output_add'] is True
        assert all(receipt[flag] is True for flag in (
            'created', 'attempted', 'address_confirmed', 'tag_confirmed', 'confirmed'))
        assert receipt['field_attempted'] == 'TagName'
        issued[application, address] = oid
    return issued


def inspect_graph(before, after, case, level_rows, issued_levels, issued_groups):
    levels.inspect_graph(before, after, case, level_rows, issued_levels)
    root = outputs.parse(after)
    for (application, address), identity in issued_groups.items():
        group = outputs.group_at(root, application, address)
        assert group.tag == 'Group'
        assert group.findtext('OID') == identity


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('name', list(CASES))
def test_public_output_add_histories_and_one_save(backend, variable, name, tmp_path):
    case = CASES[name]
    with journey(backend, variable, tmp_path, name, case) as (owner, relay, evidence, specs, _endpoint):
        preview, preview_call = settings_cli(relay, evidence, specs, case, action='preview')
        expected_levels = inspect_plan(preview, evidence['before_xml'], case)
        outputs.assert_no_mutation(preview_call)
        assert refs.document(owner) == evidence['before_xml']
        result, call = settings_cli(relay, evidence, specs, case)
        assert result['complete'] is True
        assert result['plan'] == {key: value for key, value in preview.items() if key != 'scope'}
        issued_groups = inspect_group_wire(call, evidence['before_xml'], case)
        identities = levels.group_identities(evidence['before_xml'], {'creates': []}) | issued_groups
        issued_levels = levels.inspect_level_wire(call, expected_levels, identities)
        assert [command for command in call['commands'] if command.startswith(('DBADD ', 'DBADDSAFE '))] == add_commands(evidence['before_xml'], case) + [
            levels.level_command(row) for row in expected_levels]
        mutation = bool(case['changed'] or case['creates'] or expected_levels)
        assert call['commands'].count('PROJECT SAVE ' + PROJECT) == (2 if mutation else 0)
        assert call['commands'].count('PROJECT COPY ' + PROJECT + ' ' + BACKUP) == int(mutation)
        assert sum(command.startswith('PP SAVE_TO_SOURCE ') for command in call['commands']) == int(bool(case['changed']))
        if mutation:
            assert result['persistence_verified'] is True
            first_mutation = next(index for index, command in enumerate(call['commands'])
                                  if command.startswith(('DBADD ', 'DBADDSAFE ', 'PP SET ')))
            assert call['commands'].index('PROJECT COPY ' + PROJECT + ' ' + BACKUP) < first_mutation
            assert call['commands'].count('PROJECT CLOSE ' + PROJECT) == 1
            assert call['commands'].count('PROJECT LOAD ' + PROJECT) == 1
        else:
            outputs.assert_no_mutation(call)
        after, actual = refs.document(owner), refs.parameters(owner)
        refs.assert_values(evidence['before_parameters'], actual, case['changed'])
        inspect_graph(evidence['before_xml'], after, case, expected_levels, issued_levels, issued_groups)
        if mutation:
            for verb in ('SAVE', 'CLOSE', 'LOAD', 'USE'):
                assert owner.command('PROJECT ' + verb + ' ' + PROJECT).code == 200
        reopened, fresh = refs.document(owner), refs.parameters(owner)
        refs.assert_values(evidence['before_parameters'], fresh, case['changed'])
        inspect_graph(evidence['before_xml'], reopened, case, expected_levels, issued_levels, issued_groups)
        assert graph(after) == graph(reopened)
        evidence.update(preview=preview, result=result, after_xml=after, reopened_xml=reopened,
                        after_parameters=actual, reopened_parameters=fresh, literal_levels=expected_levels,
                        issued_groups=[{'application': app, 'address': address, 'oid': oid}
                                       for (app, address), oid in issued_groups.items()],
                        issued_levels=[{'application': app, 'group': group, 'address': address, 'oid': oid}
                                       for (app, group, address), oid in issued_levels.items()],
                        independent_reopen=mutation, preservation_verified=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('name', list(REFUSALS))
def test_public_output_add_history_refused_before_backup(backend, variable, name, tmp_path):
    case = REFUSALS[name]
    with journey(backend, variable, tmp_path, name, case) as (owner, relay, evidence, specs, _endpoint):
        result, call = settings_cli(relay, evidence, specs, case, expected=1)
        assert case['error_contains'] in result['error']
        assert result['thermostat_template_evidence']['outcome_uncertain'] is False
        outputs.assert_no_mutation(call)
        assert refs.document(owner) == evidence['before_xml']
        assert refs.parameters(owner) == evidence['before_parameters']
        evidence.update(result=result, after_xml=refs.document(owner),
                        after_parameters=refs.parameters(owner), refusal_before_backup=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_output_add_lost_successful_creation_never_replays(backend, variable, tmp_path):
    case = CASES['basic-interleaved-add-retained-after-reselection']
    with journey(backend, variable, tmp_path, 'lost-successful-output-add', case) as (owner, _relay, evidence, specs, endpoint):
        # The numeric associated Project export omits unfinished objects.
        # Inspect the issued OID directly and retain existing leaf readbacks;
        # do not delete or complete the uncertain object to obtain an export.
        paths = [UNIT, NETWORK + '/21', '//' + PROJECT + '/12',
                 NETWORK + '/172', NETWORK + '/203', NETWORK + '/202']
        paths += [NETWORK + '/56/' + str(address) for address in (20, 30, 255)]
        before_subtrees = {path: refs.document(owner, path) for path in paths}
        with FaultGate(endpoint, 'DBADD', 'drop') as fault:
            result, call = settings_cli(fault, evidence, specs, case, expected=1, complete=False)
        wires = fault.evidence()
        evidence['fault_wires'] = wires
        state = result['thermostat_template_evidence']
        assert fault.matches == 1
        assert state['complete'] is False and state['outcome_uncertain'] is True
        assert state['graph_mutation_outcome_uncertain'] is True
        assert state['automatic_retries'] == 0 and state['rollback_performed'] is False
        assert state['pp_save_attempted'] is False and state['target_save_attempted'] is False
        assert len(state['objects']) == 1
        assert state['objects'][0]['attempted'] is True and state['objects'][0]['confirmed'] is False
        expected_create = add_commands(evidence['before_xml'], case)[0]
        assert [command for command in call['commands'] if command.startswith(('DBADD ', 'DBADDSAFE '))] == [expected_create]
        assert call['commands'][-1] == expected_create and call['statuses'][-1] is None
        assert call['commands'].count('PROJECT SAVE ' + PROJECT) == 1
        assert call['commands'].count('PROJECT COPY ' + PROJECT + ' ' + BACKUP) == 1
        assert not any(command.startswith(('PP SET ', 'PP SAVE', 'DBSET ', 'DBDELETE', 'PROJECT CLOSE ', 'PROJECT LOAD '))
                       for command in call['commands'])
        lost = [wire for wire in wires if 'lost_backend_terminal_hex' in wire]
        assert len(lost) == 1
        terminal = bytes.fromhex(lost[0]['lost_backend_terminal_hex']).decode()
        match = re.fullmatch(r'\[[^]]+\] 301 OID=([0-9a-f-]+)\r\n', terminal)
        assert match is not None, terminal
        assert lost[0]['lost_backend_terminal_hex'] not in lost[0]['response_hex']
        identity = levels.issued_oid('OID=' + match[1])
        before_ids = {node.text for node in outputs.parse(evidence['before_xml']).iter('OID')}
        assert identity not in before_ids
        observations = []
        for field, expected_status in (('OID', 342), ('Address', 401), ('TagName', 401)):
            command = 'DBGET !' + identity + '/' + field
            response = complete_response(owner, command)
            observations.append({'command': command, 'code': response.code, 'lines': list(response.lines)})
            assert response.code == expected_status
            if field == 'OID':
                assert list(response.lines) == ['342 !' + identity + '/OID=' + identity]
        pending = refs.document(owner, '!' + identity)
        parsed_pending = outputs.parse(pending)
        assert parsed_pending.tag == 'Group'
        assert parsed_pending.findtext('OID') == identity
        assert parsed_pending.find('Address') is None and parsed_pending.find('TagName') is None
        export = complete_response(owner, 'DBGETXML //' + PROJECT)
        assert export.code == 344
        observations.append({'command': 'DBGETXML //' + PROJECT, 'code': export.code,
                             'lines': list(export.lines)})
        after = refs.xml_text(export)
        assert identity not in {node.text for node in outputs.parse(after).iter('OID')}
        assert graph(after) == graph(evidence['before_xml'])
        after_subtrees = {path: refs.document(owner, path) for path in paths}
        assert {path: graph(value) for path, value in after_subtrees.items()} == {
            path: graph(value) for path, value in before_subtrees.items()}
        actual = refs.parameters(owner)
        assert actual == evidence['before_parameters']
        evidence.update(result=result, fault_wires=wires, after_xml=after, after_parameters=actual,
                        pending_oid=identity, pending_xml=pending,
                        pending_readback=observations, before_subtrees=before_subtrees,
                        after_subtrees=after_subtrees, existing_subtrees_preserved=True,
                        full_graph_readback_available=True, pending_in_project_export=False,
                        full_graph_readback_limitation='Numeric associated Project export omits the pending Group; its existence and absent Address/TagName are verified separately by OID.',
                        creation_response_lost=True, replay_count=0,
                        preservation_verified=True)
