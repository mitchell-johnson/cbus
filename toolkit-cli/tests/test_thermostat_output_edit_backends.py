"""Literal ordered output Edit journeys against two explicitly owned backends.

The backend XML profile admits Network opaque metadata and Level/DLT records.
Custom Group/TagName attributes and arbitrary Project metadata are covered by
pure preservation tests; the retained importer refuses those group attributes
and its Project export omits the synthetic project-level opaque node.
"""
from contextlib import contextmanager
import re
from xml.etree import ElementTree as ET

import pytest

import test_thermostat_output_add_backends as adds
from test_cgate_barcode_database_interop import FaultGate, graph


outputs, refs, levels = adds.outputs, adds.refs, adds.levels
BACKENDS = adds.BACKENDS
NETWORK, PROJECT, UNIT, BACKUP = adds.NETWORK, adds.PROJECT, adds.UNIT, adds.BACKUP
LONG_NAME = 'Loaded ' + 'x' * 40


def edit(parameter, outcome='accept', **fields):
    return dict(op='edit-output-group', parameter=parameter, outcome=outcome, **fields)


# These are literal source-encoded TagName command tails, not calls to the
# production encoder. NBSP is a name by itself and is not source Trim space.
QUOTED = {
    'éPump  Ω': r'"éPump\ \ Ω"',
    'Quote " slash \\ #': r'"Quote \" slash \\ #"',
    '\u00a0': '"\u00a0"', 'Alpha': '"Alpha"', 'Beta': '"Beta"',
    'Fresh added': '"Fresh added"', 'Edited  issued': r'"Edited\ \ issued"',
}

CASES = {
    'shared-object-repeated-quoted-edits': {
        'unit_type': 'PC_TSA5', 'groups': {56: [20, 30, 255], 172: [1], 203: [20, 255]},
        'group_tags': {56: {20: 'Original shared', 30: 'Other peer'}},
        'seed': {'CoolStage1Output': 20, 'HeatStage1Output': 20,
                 'RemoteSetbackControlSource': 1, 'RemoteSetbackOnGroup': 20,
                 'RemoteSetbackOffGroup': 255},
        'history': [edit('CoolStage1Output', name=' \téPump  Ω\t '),
                    edit('HeatStage1Output', name='Quote " slash \\ #')],
        'renames': [(1, 'CoolStage1Output', 56, 20, 'Original shared', 'éPump  Ω'),
                    (2, 'HeatStage1Output', 56, 20, 'éPump  Ω', 'Quote " slash \\ #')],
        'creates': [], 'changed': {},
    },
    'nbsp-temporary-name-swap': {
        'unit_type': 'PC_TSB', 'groups': {56: [20, 30, 255], 172: [1], 203: []},
        'group_tags': {56: {20: 'Alpha', 30: 'Beta'}},
        'seed': {'HeatStage1Output': 20, 'HeatStage2Output': 30},
        'history': [edit('HeatStage1Output', name='\u00a0'),
                    edit('HeatStage2Output', name='Alpha'), edit('HeatStage1Output', name='Beta')],
        'renames': [(1, 'HeatStage1Output', 56, 20, 'Alpha', '\u00a0'),
                    (2, 'HeatStage2Output', 56, 30, 'Beta', 'Alpha'),
                    (3, 'HeatStage1Output', 56, 20, '\u00a0', 'Beta')],
        'creates': [], 'changed': {},
    },
    'add-edit-issued-identity-and-reselect-original': {
        'unit_type': 'PC_TSB', 'groups': {56: [20, 30, 255], 172: [1], 203: []},
        'seed': {'HeatStage1Output': 30},
        'history': [adds.add('HeatStage1Output', address=4, name='Fresh added'),
                    edit('HeatStage1Output', name='Edited  issued'), adds.select('HeatStage1Output', 30)],
        'renames': [(2, 'HeatStage1Output', 56, 4, 'Fresh added', 'Edited  issued')],
        'creates': [(56, 4, 'Fresh added')], 'changed': {},
    },
    'cancel-and-omitted-long-name-noop': {
        'unit_type': 'PC_TSB', 'groups': {56: [20, 30, 255], 172: [1], 203: []},
        'group_tags': {56: {20: LONG_NAME}}, 'seed': {'HeatStage1Output': 20},
        'history': [edit('HeatStage1Output', 'cancel'), edit('HeatStage1Output')],
        'renames': [], 'creates': [], 'changed': {},
    },
}

REFUSAL = {
    'unit_type': 'PC_TSB', 'groups': {56: [20, 30, 255], 172: [1], 203: []},
    'group_tags': {56: {20: 'Alpha', 30: 'Beta'}}, 'seed': {'HeatStage1Output': 20},
    'history': [edit('HeatStage1Output', name='beta')], 'changed': {}, 'creates': [],
}


@contextmanager
def journey(backend, variable, tmp_path, name, case):
    """Reuse the admitted public fixture without changing frozen helpers."""
    try:
        with adds.journey(backend, variable, tmp_path, name, case) as data:
            owner, relay, evidence, specs, endpoint = data
            root = outputs.parse(evidence['before_xml'])
            loaded = outputs.group_at(root, 56, 20)
            network_opaque = root.find("Project/Network[Address='12']/{urn:cbus:synthetic:thermostat}RetainedNetworkMetadata")
            assert network_opaque.attrib == {'note': 'unrelated'} and network_opaque.text == 'unchanged'
            assert loaded.find("Level[Address='7']").get('Value') == '207'
            assert loaded.find("Level[Address='200']").get('Value') == '1'
            assert loaded.find("Level[Address='7']/TagsDLT/TagDLT/TagValue").text == 'Retain Ω 20'
            evidence.update(format='cbus-thermostat-output-edit-owned-v1',
                            opaque_preservation_scope='Admitted Network metadata and complete emitted graph. Custom Group/TagName attributes are refused; synthetic Project opaque node is omitted by export. Arbitrary metadata preservation is covered by pure tests.')
            yield owner, relay, evidence, specs, endpoint
    finally:
        original = tmp_path / 'thermostat-output-add-evidence.json'
        if original.exists():
            original.rename(tmp_path / 'thermostat-output-edit-evidence.json')


def group_ids(before):
    return levels.group_identities(before, {'creates': []})


def assert_plan(preview, before, case):
    assert preview['changed_parameters'] == [] and preview['pp_save_count'] == 0
    mutation = bool(case['renames'] or case['creates'])
    assert preview['apply_would_mutate'] is mutation
    assert preview['target_project_save_count'] == int(mutation)
    remote, projection = preview['remote_references'], preview['output_projection']
    assert remote['output_operations'] == case['history']
    assert projection == remote['output_projection']
    assert [(row['position'], row['op'], row['parameter']) for row in projection['operations']] == [
        (n, row['op'], row['parameter']) for n, row in enumerate(case['history'], 1)]
    assert [(row['application'], row['address'], row['previous_name'], row['name'], row['reason'])
            for row in remote['planned_renames']] == [
        (app, address, old, new, 'output_edit:' + str(position) + ':' + parameter)
        for position, parameter, app, address, old, new in case['renames']]
    assert all(row['output_edit'] is True for row in remote['planned_renames'])
    assert [(row['application'], row['address'], row['name']) for row in remote['planned_creations']] == case['creates']
    assert remote['planned_level_creations'] == []
    assert [row['action'] for row in remote['graph_operations']] == (
        ['create'] * len(case['creates']) + ['rename'] * len(case['renames']))
    changes = {row[0]: row for row in case['renames']}
    known = group_ids(before)
    for receipt in projection['edit_dialogs']:
        position = receipt['position']
        request = case['history'][position - 1]
        assert request['op'] == 'edit-output-group'
        assert receipt['parameter'] == request['parameter'] and receipt['outcome'] == request['outcome']
        assert receipt['identity'] == receipt['previous_identity']
        assert receipt['object_created'] is False and receipt['kind'] == 'Group'
        assert receipt['operator_name'] is ('name' in request)
        if position in changes:
            _n, _parameter, app, address, old, new = changes[position]
            assert (receipt['application'], receipt['address'], receipt['shown_name'],
                    receipt['previous_name'], receipt['name']) == (app, address, old, old, new)
            assert receipt['changed'] is True and receipt['entered_name'] == request['name']
            if (app, address) in known:
                assert receipt['identity'] == known[app, address]
        else:
            assert receipt['shown_name'] == receipt['previous_name'] == receipt['name'] == LONG_NAME
            assert receipt['entered_name'] == (None if request['outcome'] == 'cancel' else LONG_NAME)
            assert receipt['changed'] is False and receipt['identity'] == known[56, 20]
    if case is CASES['shared-object-repeated-quoted-edits']:
        shared = projection['resolved_references']
        for parameter in ('CoolStage1Output', 'HeatStage1Output'):
            assert shared[parameter] == dict(address=20, identity=known[56, 20], name='Quote " slash \\ #')
        assert remote['resolved_roles']['setback_on'] == dict(
            application=56, address=20, identity=known[56, 20], unused=False)


def assert_wire(call, before, case, *, lost=False):
    commands, statuses, terminals = call['commands'], call['statuses'], call['terminals']
    identities = group_ids(before)
    expected, issued = [], {}
    for app, address, name in case['creates']:
        parent = NETWORK + '/' + str(app)
        parent_oid = adds.application_oid(before, app)
        command = 'DBADD !' + parent_oid + ' Group'
        index = commands.index(command)
        assert commands[index - 1] == 'DBGET ' + parent + '/OID'
        assert statuses[index - 1:index + 1] == [342, 301]
        assert terminals[index - 1] == parent + '/OID=' + parent_oid
        oid = levels.issued_oid(terminals[index])
        assert oid not in identities.values()
        assert commands[index + 1] == 'DBGET !' + oid + '/OID'
        assert statuses[index + 1] == 342 and terminals[index + 1] == '!' + oid + '/OID=' + oid
        expected.extend([command, 'DBSET !' + oid + '/Address ' + str(address),
                         'DBSET !' + oid + '/TagName ' + QUOTED[name]])
        identities[app, address] = issued[app, address] = oid
    rename_rows = case['renames'][:1] if lost else case['renames']
    rename_indices = []
    for _position, _parameter, app, address, old, name in rename_rows:
        oid = identities[app, address]
        command = 'DBSET !' + oid + '/TagName ' + QUOTED[name]
        index = commands.index(command)
        assert commands[index - 2:index] == ['DBGET !' + oid + '/OID', 'DBGET !' + oid + '/TagName']
        assert statuses[index - 2:index] == [342, 342]
        assert terminals[index - 2:index] == ['!' + oid + '/OID=' + oid, '!' + oid + '/TagName=' + old]
        assert statuses[index] == (None if lost else 200)
        expected.append(command)
        rename_indices.append(index)
    assert rename_indices == sorted(rename_indices)
    assert [command for command in commands if command.startswith(('DBADD', 'DBSET', 'DBDELETE'))] == expected
    assert not any(command.startswith(('PP SET ', 'PP SAVE', 'NET OPEN ', 'PP PROGRAM ')) for command in commands)
    return issued


def assert_preserved(before, after, case, issued, *, first_rename_only=False):
    old, current = outputs.parse(before), outputs.parse(after)
    renames = case['renames'][:1] if first_rename_only else case['renames']
    final = {(app, address): name for _position, _parameter, app, address, _old, name in renames}
    created = {(app, address): name for app, address, name in case['creates']}
    for key, name in final.items():
        actual = outputs.group_at(current, *key)
        assert actual.findtext('TagName') == name
        if key in created:
            assert actual.findtext('OID') == issued[key]
        else:
            original = outputs.group_at(old, *key)
            assert actual.findtext('OID') == original.findtext('OID')
            actual.find('TagName').text = original.findtext('TagName')
    # Remove only the declared new objects with their final literal names.
    refs.assert_preserved(before, ET.tostring(current, encoding='unicode'),
                          {'changed': {}, 'creates': [(app, address, final.get((app, address), name))
                           for app, address, name in case['creates']]})


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('name', list(CASES))
def test_public_output_edit_histories_preserve_identity_and_graph(backend, variable, name, tmp_path):
    case = CASES[name]
    with journey(backend, variable, tmp_path, name, case) as (owner, relay, evidence, specs, _endpoint):
        preview, preview_call = adds.settings_cli(relay, evidence, specs, case, action='preview')
        assert_plan(preview, evidence['before_xml'], case)
        outputs.assert_no_mutation(preview_call)
        assert refs.document(owner) == evidence['before_xml']
        result, call = adds.settings_cli(relay, evidence, specs, case)
        assert result['complete'] is True
        assert result['plan'] == {key: value for key, value in preview.items() if key != 'scope'}
        issued = assert_wire(call, evidence['before_xml'], case)
        assert [(row['previous_name'], row['name'], row['confirmed']) for row in result['renames']] == [
            (old, name, True) for _position, _parameter, _app, _address, old, name in case['renames']]
        mutation = bool(case['renames'] or case['creates'])
        assert call['commands'].count('PROJECT SAVE ' + PROJECT) == (2 if mutation else 0)
        assert call['commands'].count('PROJECT COPY ' + PROJECT + ' ' + BACKUP) == int(mutation)
        assert call['commands'].count('PROJECT CLOSE ' + PROJECT) == int(mutation)
        assert call['commands'].count('PROJECT LOAD ' + PROJECT) == int(mutation)
        if mutation:
            assert result['persistence_verified'] is True
            first_write = next(index for index, command in enumerate(call['commands']) if command.startswith(('DBADD', 'DBSET')))
            assert call['commands'].index('PROJECT COPY ' + PROJECT + ' ' + BACKUP) < first_write
        else:
            outputs.assert_no_mutation(call)
        after, actual = refs.document(owner), refs.parameters(owner)
        assert actual == evidence['before_parameters']
        assert_preserved(evidence['before_xml'], after, case, issued)
        if mutation:
            for verb in ('SAVE', 'CLOSE', 'LOAD', 'USE'):
                assert owner.command('PROJECT ' + verb + ' ' + PROJECT).code == 200
        reopened, fresh = refs.document(owner), refs.parameters(owner)
        assert fresh == evidence['before_parameters'] and graph(reopened) == graph(after)
        assert_preserved(evidence['before_xml'], reopened, case, issued)
        evidence.update(preview=preview, result=result, after_xml=after, reopened_xml=reopened,
                        after_parameters=actual, reopened_parameters=fresh, preservation_verified=True,
                        independent_reopen=mutation,
                        issued_groups=[dict(application=app, address=address, oid=oid)
                                       for (app, address), oid in issued.items()])


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_output_edit_duplicate_refused_before_backup(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path, 'duplicate-name-refused', REFUSAL) as (owner, relay, evidence, specs, _endpoint):
        result, call = adds.settings_cli(relay, evidence, specs, REFUSAL, expected=1)
        assert '2203' in result['error']
        assert result['thermostat_template_evidence']['outcome_uncertain'] is False
        outputs.assert_no_mutation(call)
        assert refs.document(owner) == evidence['before_xml']
        assert refs.parameters(owner) == evidence['before_parameters']
        evidence.update(result=result, refusal_before_backup=True, after_xml=refs.document(owner),
                        after_parameters=refs.parameters(owner))


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_output_edit_lost_successful_set_never_replays(backend, variable, tmp_path):
    case = CASES['shared-object-repeated-quoted-edits']
    with journey(backend, variable, tmp_path, 'lost-successful-output-edit', case) as (owner, _relay, evidence, specs, endpoint):
        with FaultGate(endpoint, 'DBSET', 'drop') as fault:
            result, call = adds.settings_cli(fault, evidence, specs, case, expected=1, complete=False)
        wires = fault.evidence()
        evidence['fault_wires'] = wires
        assert fault.matches == 1
        state = result['thermostat_template_evidence']
        assert state['complete'] is False and state['outcome_uncertain'] is True
        assert state['graph_mutation_outcome_uncertain'] is True
        assert state['automatic_retries'] == 0 and state['rollback_performed'] is False
        assert state['pp_save_attempted'] is False and state['target_save_attempted'] is False
        assert len(state['renames']) == 1 and state['renames'][0]['attempted'] is True
        assert state['renames'][0]['confirmed'] is False
        assert_wire(call, evidence['before_xml'], case, lost=True)
        assert call['commands'][-1].startswith('DBSET ') and call['statuses'][-1] is None
        assert call['commands'].count('PROJECT SAVE ' + PROJECT) == 1
        assert call['commands'].count('PROJECT COPY ' + PROJECT + ' ' + BACKUP) == 1
        assert not any(command.startswith(('PROJECT CLOSE ', 'PROJECT LOAD ')) for command in call['commands'])
        lost = [wire for wire in wires if 'lost_backend_terminal_hex' in wire]
        assert len(lost) == 1
        terminal = bytes.fromhex(lost[0]['lost_backend_terminal_hex']).decode()
        assert re.fullmatch(r'\[[^]]+\] 200 OK\.\r\n', terminal), terminal
        assert lost[0]['lost_backend_terminal_hex'] not in lost[0]['response_hex']
        after, actual = refs.document(owner), refs.parameters(owner)
        assert actual == evidence['before_parameters']
        assert_preserved(evidence['before_xml'], after, case, {}, first_rename_only=True)
        evidence.update(result=result, after_xml=after, after_parameters=actual,
                        mutation_response_lost=True, replay_count=0, preservation_verified=True,
                        independent_reopen=False)
