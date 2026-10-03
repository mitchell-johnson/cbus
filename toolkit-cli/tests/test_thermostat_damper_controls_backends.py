"""Explicit thermostat damper callbacks on two owned synthetic backends.

Expectations come from retained source literals. No host callback scheduling,
application migration, vendor execution or physical programming is inferred.
"""
from copy import deepcopy
from contextlib import contextmanager
import json
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

import pytest
import test_thermostat_output_add_backends as adds
from test_cgate_barcode_database_interop import FaultGate, graph, parse_wire

outputs, refs = adds.outputs, adds.refs
BACKENDS = adds.BACKENDS
PROJECT, UNIT, BACKUP = adds.PROJECT, adds.UNIT, adds.BACKUP
VECTOR = Path(__file__).resolve().parents[1] / 'research' / 'fixtures' / 'thermostat-damper-controls-public-literals.json'
DATA = json.loads(VECTOR.read_bytes())
assert DATA['schema'] == 'cbus-thermostat-damper-public-literals-v1'
assert DATA['independent_source_literals'] is True
assert DATA['implicit_host_callbacks'] is False
assert {c['input']['unit_type'] for c in DATA['positive']} == {
    'PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5'}
assert DATA['cli_event_flag'] == '--output-operation'
assert DATA['projection_key'] == 'damper_controls'
assert DATA['positive'] and DATA['refusals'] and DATA['losses']


def input_pins():
    """Pin current loaded package inputs, independently of generic wire maps."""
    result = {}
    for name in ('thermostat_damper_controls', 'thermostat_settings',
                 'thermostat_output_groups', 'thermostat_remote_references',
                 'thermostat_templates_cli', 'thermostat_templates', 'thermostat_post_load',
                 'thermostat_settings_guard', 'native', 'cgate', 'programming', 'unitspec'):
        module = 'cbus_toolkit.' + name
        spec = importlib.util.find_spec(module)
        assert spec is not None and spec.origin is not None, module
        origin = Path(spec.origin)
        assert origin.name == name + '.py' and origin.parent.name == 'cbus_toolkit'
        content = origin.read_bytes()
        result[module] = {'sha256': hashlib.sha256(content).hexdigest(),
            'bytes': len(content), 'origin': str(origin)}
    return result


def fixture_input(case):
    """Decode JSON numeric map keys only, without projecting an expectation."""
    result = deepcopy(case['input'])
    if 'groups' in result:
        result['groups'] = {int(key): value for key, value in result['groups'].items()}
    if 'group_tags' in result:
        result['group_tags'] = {int(app): {int(address): tag for address, tag in rows.items()}
            for app, rows in result['group_tags'].items()}
    return result


@contextmanager
def journey(backend, variable, tmp_path, case):
    try:
        with adds.journey(backend, variable, tmp_path, case['id'], fixture_input(case)) as data:
            owner, relay, evidence, specs, endpoint = data
            assert len(evidence['before_parameters']) == 109
            current_test = os.environ.get('PYTEST_CURRENT_TEST')
            assert current_test and current_test.endswith(' (call)'), current_test
            nodeid = current_test.rsplit(' (', 1)[0]
            assert 'test_thermostat_damper_controls_backends.py::' in nodeid
            pins = input_pins()
            evidence.update(format='cbus-thermostat-damper-zone-owned-v1',
                source_literal=case['id'], pytest_current_test=current_test, actual_nodeid=nodeid,
                implementation_inputs=pins, explicit_callbacks_only=True,
                original_execution=False, physical_acceptance=False)
            try:
                yield owner, relay, evidence, specs, endpoint
            finally:
                evidence['implementation_inputs_after'] = input_pins()
                assert evidence['implementation_inputs_after'] == pins
    finally:
        old = tmp_path / 'thermostat-output-add-evidence.json'
        if old.exists():
            old.rename(tmp_path / 'thermostat-damper-controls-evidence.json')


def invoke(relay, evidence, specs, case, *, action='apply', expected=0, complete=True):
    """Own the outer process budget; retain actual partial wire on timeout."""
    start = len(relay.rows)
    argv = [sys.executable, '-m', 'cbus_toolkit', 'thermostat', 'settings',
        action, UNIT, '--host', relay.endpoint[0], '--port', str(relay.endpoint[1]),
        '--timeout', '3', '--exclusive-project', '--spec-dir', str(specs)]
    # One flat list retains actual Select/Add/Edit/callback control order.
    for event in case['history']:
        argv += ['--output-operation', json.dumps(event, ensure_ascii=False)]
    for name, response in case.get('prompts', {}).items():
        argv += ['--' + name + '-levels', response]
    for name, value in case.get('edits', {}).items():
        argv += ['--set', name + '=' + str(value)]
    if action == 'apply':
        argv += ['--backup-project', BACKUP]
    call = dict(argv=argv, action=action, accepted_terminal=False,
        call_id=evidence['actual_nodeid'] + ':' + str(len(evidence['calls']) + 1) + ':' + action,
        owning_nodeid=evidence['actual_nodeid'])
    evidence['calls'].append(call)
    try:
        process = subprocess.run(argv, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired as error:
        def text(value):
            return value.decode(errors='replace') if isinstance(value, bytes) else value
        call.update(timeout_expired=True, stdout=text(error.stdout), stderr=text(error.stderr))
        if len(relay.rows) > start:
            partial = relay.rows[start]
            partial['done'].wait(5)
            call.update(parse_wire(partial, complete=False), wire_index=start)
        raise
    call.update(exit=process.returncode, stdout=process.stdout, stderr=process.stderr)
    result = json.loads(process.stdout or process.stderr)
    call['result'] = result
    if case.get('preconnect'):
        assert len(relay.rows) == start, call
        call.update(commands=[], statuses=[], tags=[], preconnection_refusal=True)
    else:
        assert len(relay.rows) == start + 1 and relay.rows[start]['done'].wait(5)
        call.update(parse_wire(relay.rows[start], complete=complete), wire_index=start)
    assert process.returncode == expected, call
    call['accepted_terminal'] = complete
    assert not any(c.startswith(('NET OPEN ', 'PP PROGRAM ')) for c in call['commands'])
    assert all('/db' + UNIT in c for c in call['commands'] if c.startswith('PP LOAD '))
    return result, call


def literal_object(address, case, before):
    if address is None:
        return None
    created = {r['address']:r['name'] for r in case['final_creations']}
    if address in created:
        identity, name = 'planned-group:56:'+str(address), created[address]
    else:
        node = outputs.group_at(outputs.parse(before),56,address)
        identity, name = node.findtext('OID'),node.findtext('TagName')
    return {'application':56, 'address':address, 'identity':identity, 'name':name}


def assert_state(state, expected, case, before):
    for key in ('warnings','checked','model_modulation','installed_zones','shown',
                'after_show_installed','help_bound'):
        if key in expected:
            assert state[key] == expected[key], (key,state,expected)
    for key,actual in (('references','model_references'),('caches','caches')):
        if key in expected:
            assert state[actual] == [literal_object(a,case,before) for a in expected[key]]


def assert_projection(plan, case, before):
    assert {r['name']:r['after'] for r in plan['changed_parameters']} == case['changed']
    projection = plan[DATA['projection_key']]
    expected = case['expected_projection']
    assert_state(projection,expected,case,before)
    assert projection['expected'] == expected['expected']
    assert [r['code'] for r in projection['alerts']] == expected['alert_codes']
    assert all(r['context'] == 'WHITE' and r['result_consumed'] is False for r in projection['alerts'])
    assert [(r['position'],r['op']) for r in projection['operations']] == [
        (i,r['op']) for i,r in enumerate(case['history'],1) if r['op'].startswith('damper-')]
    assert [(r['position'],r['op']) for r in plan['output_projection']['operations']] == [
        (i,r['op']) for i,r in enumerate(case['history'],1)]
    indexed = {r['position']:r for r in projection['operations']}
    if case['callback_before'] is not None:
        row = case['callback_before']
        assert_state(indexed[row['position']]['before'],row,case,before)
    for row in case['intermediate']:
        state = indexed[row['position']]['after']
        assert_state(state,row,case,before)
    assert projection['automatic_subscriber_dispatch_reproduced'] is False
    assert projection['detached_receipt_continuation_admitted'] is False
    assert projection['application_migration_reproduced'] is False
    assert projection['physical_device_programmed'] is False
    assert plan['output_projection']['damper_controls'] == projection
    mutation = bool(case['changed'] or case['operations'])
    assert plan['apply_would_mutate'] is mutation
    assert plan['pp_save_count'] == int(bool(case['changed']))
    assert plan['target_project_save_count'] == int(mutation)
    assert plan['backup_source_save_count'] == int(mutation)
    assert [(row['action'], row['application'], row['address'], row['name'])
            for row in plan['graph_operations']] == [tuple(row) for row in case['operations']]
    assert plan['planned_level_creations'] == []


def assert_graph_wire(call, before, case):
    commands = call['commands']
    expected = []
    identities = {int(n.findtext('Address')):n.findtext('OID') for n in
        refs.groups(outputs.parse(before).find("Project/Network[Address='11']/Application[Address='56']"))}
    for row in case['graph_ledger']:
        address,name = row['address'],row['name']
        if row['action'] == 'create':
            command = refs.expected_creates({'creates':[(56,address,name)]})[0]
            expected.append(command)
            index = commands.index(command)
            assert call['statuses'][index] == 301
            terminal = call['terminals'][index]
            assert terminal.startswith('OID=')
            oid = terminal[4:]
            assert str(uuid.UUID(oid)) == oid and oid not in identities.values()
            identities[address] = oid
            assert commands[index+1] == 'DBGET !'+oid+'/OID'
            assert call['statuses'][index+1] == 342
            assert call['terminals'][index+1] == '!'+oid+'/OID='+oid
        else:
            oid = identities[address]
            command = 'DBSETSAFE !'+oid+'/TagName '+name
            expected.append(command)
            index = commands.index(command)
            assert commands[index-2:index] == ['DBGET !'+oid+'/OID','DBGET !'+oid+'/TagName']
            assert call['statuses'][index-2:index] == [342,342]
            assert call['terminals'][index-2:index] == ['!'+oid+'/OID='+oid,
                '!'+oid+'/TagName='+row['previous_name']]
            assert call['statuses'][index] == 200
    assert [c for c in commands if c.startswith(('DBADD','DBSET','DBDELETE'))] == expected


def preserve(before, after, case):
    old,new = outputs.parse(before),outputs.parse(after)
    created_addresses = {r['address'] for r in case['final_creations']}
    renamed = []
    for row in case['graph_ledger']:
        if row['action'] != 'rename' or row['address'] in created_addresses:
            continue
        original = outputs.group_at(old,56,row['address'])
        actual = outputs.group_at(new,56,row['address'])
        assert actual.findtext('OID') == original.findtext('OID')
        assert actual.findtext('TagName') == row['name']
        actual.find('TagName').text = original.findtext('TagName')
        renamed.append(original.findtext('OID'))
    created = refs.assert_preserved(before,ET.tostring(new,encoding='unicode'),{
        'creates':[(56,r['address'],r['name']) for r in case['final_creations']],
        'changed':case['changed']})
    original_levels = {n.findtext('OID'):n for n in old.iter('Level')}
    retained_levels = {n.findtext('OID'):n for n in new.iter('Level')}
    assert original_levels.keys() == retained_levels.keys()
    assert all(graph(ET.tostring(node,encoding='unicode')) ==
        graph(ET.tostring(retained_levels[oid],encoding='unicode'))
        for oid,node in original_levels.items())
    assert any(n.get('Value') == 'oops' for n in retained_levels.values())
    return created,renamed


def assert_no_mutation(call):
    assert not any(command.startswith(('DBADD', 'DBSET', 'DBDELETE', 'PP SET ',
        'PP SAVE', 'PP PROGRAM ', 'PROJECT SAVE ', 'PROJECT COPY ', 'PROJECT NEW ',
        'PROJECT DELETE ', 'PROJECT RESTORE ', 'NET OPEN ')) for command in call['commands'])


def copied_project_graph(before):
    """Owned COPY changes only Project Address/TagName; keep comments and PIs."""
    root = outputs.parse(before)
    project = root.find('Project')
    assert project is not None
    for name in ('Address', 'TagName'):
        field = project.find(name)
        assert field is not None and field.text == PROJECT
        field.text = BACKUP
    return graph(ET.tostring(root, encoding='unicode'))


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
@pytest.mark.parametrize('case', DATA['positive'], ids=lambda c:c['id'])
def test_public_explicit_damper_zone_history(backend, variable, case, tmp_path):
    with journey(backend, variable, tmp_path, case) as (owner, relay, evidence, specs, _):
        preview, peek = invoke(relay, evidence, specs, case, action='preview')
        assert_projection(preview, case, evidence['before_xml'])
        assert_no_mutation(peek)
        assert refs.document(owner) == evidence['before_xml']
        assert refs.parameters(owner) == evidence['before_parameters']
        result, call = invoke(relay, evidence, specs, case)
        mutation = bool(case['changed'] or case['operations'])
        assert result['complete']
        assert result['plan'] == {k:v for k,v in preview.items() if k != 'scope'}
        assert_graph_wire(call, evidence['before_xml'], case)
        commands = call['commands']
        assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands) == int(bool(case['changed']))
        assert commands.count('PROJECT SAVE '+PROJECT) == 2 * int(mutation)
        assert commands.count('PROJECT COPY '+PROJECT+' '+BACKUP) == int(mutation)
        assert commands.count('PROJECT CLOSE '+PROJECT) == int(mutation)
        assert commands.count('PROJECT LOAD '+PROJECT) == int(mutation)
        assert result['pp_save_count'] == int(bool(case['changed']))
        assert result['target_project_save_count'] == int(mutation)
        if mutation:
            assert result['persistence_verified'] is True
            first = next(i for i,c in enumerate(commands) if c.startswith(('DBADD','DBSET','PP SET ','PP SAVE')))
            assert commands.index('PROJECT SAVE '+PROJECT) < commands.index('PROJECT COPY '+PROJECT+' '+BACKUP) < first
            backup = refs.document(owner, '//'+BACKUP)
            assert graph(backup) == copied_project_graph(evidence['before_xml'])
            evidence.update(backup_xml=backup, backup_preapply_graph_verified=True)
        else:
            assert result['state'] == 'already_applied' and result['backup_project'] is None
            assert not any(c.startswith(('DBADD','DBSET','DBDELETE','PP SET ','PP SAVE','PROJECT NEW ')) for c in commands)
        actual, after = refs.parameters(owner), refs.document(owner)
        refs.assert_values(evidence['before_parameters'], actual, case['changed'])
        preserve(evidence['before_xml'], after, case)
        # A successful owner already saved; independently close/load without
        # an extra SAVE that could conceal a missing durable target commit.
        for verb in ('CLOSE','LOAD','USE'):
            assert owner.command('PROJECT '+verb+' '+PROJECT).code == 200
        fresh, reopened = refs.parameters(owner), refs.document(owner)
        assert fresh == actual and graph(reopened) == graph(after)
        preserve(evidence['before_xml'], reopened, case)
        evidence.update(preview=preview, result=result, after_xml=after,
            after_parameters=actual, reopened_xml=reopened,
            reopened_parameters=fresh, preservation_verified=True, independent_reopen=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
@pytest.mark.parametrize('case', DATA['refusals'], ids=lambda c:c['id'])
def test_public_damper_history_refuses_before_backup(backend, variable, case, tmp_path):
    with journey(backend, variable, tmp_path, case) as (owner, relay, evidence, specs, _):
        result, call = invoke(relay, evidence, specs, case, expected=1)
        assert case['error_contains'] in result['error']
        if not case.get('preconnect'):
            assert not result['thermostat_template_evidence']['outcome_uncertain']
        assert_no_mutation(call)
        assert refs.document(owner) == evidence['before_xml']
        assert refs.parameters(owner) == evidence['before_parameters']
        evidence.update(result=result, refusal_before_backup=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
@pytest.mark.parametrize('case', DATA['losses'], ids=lambda c:c['id'])
@pytest.mark.parametrize('phase', ['PP SAVE_TO_SOURCE', 'PROJECT SAVE'])
def test_public_damper_lost_successful_save_never_replays(backend, variable, case, phase, tmp_path):
    assert case['changed']  # A source-literal PP-changing positive, not invented effects.
    with journey(backend, variable, tmp_path, case) as (owner, _, evidence, specs, endpoint):
        occurrence = 2 if phase == 'PROJECT SAVE' else 1
        with FaultGate(endpoint, phase, 'drop', occurrence=occurrence) as fault:
            result, call = invoke(fault, evidence, specs, case, expected=1, complete=False)
        evidence['fault_wires'] = fault.evidence()
        assert fault.matches == occurrence
        state = result['thermostat_template_evidence']
        assert not state['complete'] and state['outcome_uncertain']
        assert state['automatic_retries'] == 0 and state['rollback_performed'] is False
        assert state['pp_save_attempted'] is True
        assert state['pp_save_confirmed'] is (phase == 'PROJECT SAVE')
        assert state['target_save_attempted'] is (phase == 'PROJECT SAVE')
        assert state['target_save_confirmed'] is False
        assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in call['commands']) == 1
        assert call['commands'].count('PROJECT SAVE '+PROJECT) == occurrence
        assert not any(c.startswith(('DBDELETE', 'PROJECT CLOSE ', 'PROJECT LOAD ')) for c in call['commands'])
        assert call['commands'].count('PROJECT COPY '+PROJECT+' '+BACKUP) == 1
        wires = evidence['fault_wires']; lost = [w for w in wires if 'lost_backend_terminal_hex' in w]
        assert len(lost) == 1
        terminal = bytes.fromhex(lost[0]['lost_backend_terminal_hex'])
        assert re.fullmatch(rb'\[[^]]+\] 200 OK\r\n', terminal)
        assert terminal in bytes.fromhex(lost[0]['backend_response_hex'])
        assert terminal not in bytes.fromhex(lost[0]['response_hex'])
        assert call['commands'][-1].startswith(phase) and call['statuses'][-1] is None
        assert_graph_wire(call,evidence['before_xml'],case)
        actual, after = refs.parameters(owner), refs.document(owner)
        refs.assert_values(evidence['before_parameters'], actual, case['changed'])
        preserve(evidence['before_xml'], after, case)
        evidence.update(result=result, fault_wires=wires, after_xml=after,
            after_parameters=actual, replay_count=0, saved_response_lost=True,
            preservation_verified=True, independent_reopen=False)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
def test_public_damper_opaque_level_stale_refuses_before_backup(backend,variable,tmp_path):
    case = DATA['stale']
    with journey(backend,variable,tmp_path,case) as (owner,_,evidence,specs,endpoint):
        original = outputs.parse(evidence['before_xml'])
        group = outputs.group_at(original,56,40)
        level = next(n for n in group.findall('Level') if n.findtext('Address') == '7')
        oid = level.findtext('OID')
        assert level.get('Value') == 'oops'
        def mutate():
            assert owner.command('DBSETSAFE !'+oid+'/Value externally changed opaque value').code == 200
        with FaultGate(endpoint,'PROJECT USE','change',occurrence=4,callback=mutate) as fault:
            result,call = invoke(fault,evidence,specs,case,expected=1)
        assert fault.matches >= 4 and any(r.get('controlled_change_completed') for r in fault.rows)
        assert 'changed since planning' in result['error']
        assert result['thermostat_template_evidence']['outcome_uncertain'] is False
        assert_no_mutation(call)
        after = refs.document(owner)
        actual = refs.parameters(owner)
        assert actual == evidence['before_parameters']
        level.set('Value','externally changed opaque value')
        assert graph(ET.tostring(original,encoding='unicode')) == graph(after)
        evidence.update(result=result,fault_wires=fault.evidence(),after_xml=after,
            after_parameters=actual,controlled_change={'oid':oid,'field':'Value',
                'before':'oops','after':'externally changed opaque value'},refusal_before_backup=True)
