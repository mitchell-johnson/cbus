"""Accepted optional thermostat level prompts through one owning transaction.

These synthetic public CLI journeys use only direct, owned Rust backends.
Expected level addresses, values and names come from the recovered source
rules, not the production planner. No vendor instructions or hardware run.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import re
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.file_transfer import prepare_upload, upload
from test_cgate_barcode_database_interop import FaultGate, graph, parse_wire
import test_thermostat_remote_references_backends as refs


BACKENDS = refs.BACKENDS
NETWORK, PROJECT, UNIT, BACKUP = refs.NETWORK, refs.PROJECT, refs.UNIT, refs.BACKUP
# Literal zone strings retained independently from the production label helper.
ZONES = ('Zone:unsw', 'Zone:1', 'Zones:unsw,1', 'Zone:2', 'Zones:unsw,2',
         'Zones:1,2', 'Zones:unsw,1,2', 'Zone:3', 'Zones:unsw,3', 'Zones:1,3',
         'Zones:unsw,1,3', 'Zones:2,3', 'Zones:unsw,2,3', 'Zones:1,2,3',
         'Zones:unsw,1,2,3', 'Zone:4', 'Zones:unsw,4', 'Zones:1,4',
         'Zones:unsw,1,4', 'Zones:2,4', 'Zones:unsw,2,4', 'Zones:1,2,4',
         'Zones:unsw,1,2,4', 'Zones:3,4', 'Zones:unsw,3,4', 'Zones:1,3,4',
         'Zones:unsw,1,3,4', 'Zones:2,3,4', 'Zones:unsw,2,3,4',
         'Zones:1,2,3,4', 'Zones:unsw,1,2,3,4')
SETBACK = [(203, 21, 'Setbk', 'Enable'), (203, 22, 'Setbk', 'Disable')]
SCHEDULE = [(203, 12, 'Sched', 'Enable'), (203, 13, 'Sched', 'Disable'),
            (203, 14, 'Sched', 'Overrd')]
EXISTING = {56: [], 203: [21, 22, 12, 13, 14]}
CASES = {
    'accept-both-new-groups': {
        **deepcopy(refs.CASES['programmable-joined']),
        'prompts': {'setback': 'accept', 'schedule': 'accept'},
        'roles': SETBACK + SCHEDULE,
    },
    'accept-setback-decline-schedule': {
        **deepcopy(refs.CASES['programmable-alias-cross-application']),
        'prompts': {'setback': 'accept', 'schedule': 'decline'},
        'roles': [(56, 12, 'Setbk', 'Enable'), (56, 13, 'Setbk', 'Disable')],
        'prompt_roles': [(56, 12, 'Setbk', 'Enable'), (56, 13, 'Setbk', 'Disable')] + SCHEDULE,
    },
    'decline-setback-accept-schedule-graph-only': {
        'unit_type': 'PC_TSA', 'seed': refs.SAVED_REMOTE, 'groups': EXISTING,
        'edits': {}, 'changed': {}, 'creates': [],
        'prompts': {'setback': 'decline', 'schedule': 'accept'}, 'roles': SCHEDULE,
    },
    'decline-both-missing-levels-noop': {
        'unit_type': 'PC_TSA5', 'seed': refs.SAVED_REMOTE, 'groups': EXISTING,
        'edits': {}, 'changed': {}, 'creates': [],
        'prompts': {'setback': 'decline', 'schedule': 'decline'}, 'roles': [],
    },
    'basic-accept-complete-addresses-noop': {
        'unit_type': 'PC_TSB', 'groups': {56: [7, 8]},
        'seed': {'RemoteSetbackControlSource': 1, 'RemoteSetbackOnGroup': 7,
                 'RemoteSetbackOffGroup': 8},
        'edits': {}, 'changed': {}, 'creates': [], 'complete_levels': True,
        'prompts': {'setback': 'accept', 'schedule': 'decline'}, 'roles': [],
        'prompt_roles': [(56, 7, 'Setbk', 'Enable'), (56, 8, 'Setbk', 'Disable')],
    },
    'basic-alias-accept-group-zero-skip-unused': {
        'unit_type': 'PC_TSB5', 'groups': {56: [], 203: [0, 255]},
        'seed': {'RemoteSetbackControlSource': 2, 'RemoteSetbackOnGroup': 0,
                 'RemoteSetbackOffGroup': 255},
        'edits': {}, 'changed': {}, 'creates': [],
        'prompts': {'setback': 'accept', 'schedule': 'decline'},
        'roles': [(203, 0, 'Setbk', 'Enable')],
        'prompt_roles': [(203, 0, 'Setbk', 'Enable'), (203, 255, 'Setbk', 'Disable')],
    },
}


def parse(text):
    return ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(
        insert_comments=True, insert_pis=True)))


def selected_group(root, app, group):
    application = root.find("Project/Network[Address='11']/Application[Address='" + str(app) + "']")
    matches = [node for node in refs.groups(application) if node.findtext('Address') == str(group)]
    assert len(matches) == 1
    return matches[0]


def seed_levels(owner, work, case):
    """Extend only declared synthetic fixture inputs, before the workflow."""
    root = parse(refs.document(owner))
    network = root.find("Project/Network[Address='11']")
    for app in network.findall('Application'):
        for group in refs.groups(app):
            for node in list(group):
                if node.tag == 'Level':
                    group.remove(node)
            for address in ([*range(1, 32), 200] if case.get('complete_levels') else [7, 200]):
                value = 207 if address == 7 else 1 if address == 200 else 255 - address
                node = ET.SubElement(group, 'Level', Value=str(value))
                for name, content in (('OID', uuid.uuid4()), ('Address', address),
                                      ('TagName', 'Retained unusual level ' + str(address))):
                    refs.scalar(node, name, content)
                # Existing labels are independent from generated level names.
                tags = ET.SubElement(node, 'TagsDLT')
                tag = ET.SubElement(tags, 'TagDLT')
                for name, content in (('LanguageID', 1), ('FlavourID', 1),
                                      ('TagType', 'TEXT'), ('TagValue', 'Keep Ω ' + str(address))):
                    refs.scalar(tag, name, content)
    path = work / 'remote-levels-synthetic.xml'
    path.write_bytes(ET.tostring(root))
    assert upload(prepare_upload('Projects/archived/' + path.name, path), owner)['upload_completed']
    for command in ('PROJECT CLOSE ' + PROJECT, 'PROJECT DELETE ' + PROJECT,
                    'PROJECT RESTORE ' + PROJECT + ' ' + path.name,
                    'PROJECT USE ' + PROJECT, 'PROJECT SAVE ' + PROJECT):
        assert owner.command(command).code == 200
    return path


@contextmanager
def journey(backend, variable, tmp_path, name, case):
    try:
        with refs.journey(backend, variable, tmp_path, name, case) as data:
            owner, relay, evidence, specs, endpoint = data
            fixture = seed_levels(owner, tmp_path, case)
            evidence.update(format='cbus-thermostat-remote-levels-owned-v1',
                fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                before_xml=refs.document(owner), before_parameters=refs.parameters(owner))
            yield owner, relay, evidence, specs, endpoint
    finally:
        original = tmp_path / 'thermostat-remote-references-evidence.json'
        if original.exists():
            original.rename(tmp_path / 'thermostat-remote-levels-evidence.json')


def settings_cli(relay, evidence, specs, case, *, action='apply', expected=0, complete=True):
    before = len(relay.rows)
    argv = [sys.executable, '-m', 'cbus_toolkit', 'thermostat', 'settings', action, UNIT,
            '--host', relay.endpoint[0], '--port', str(relay.endpoint[1]), '--timeout', '5',
            '--exclusive-project', '--spec-dir', str(specs),
            '--setback-levels', case['prompts']['setback'],
            '--schedule-levels', case['prompts']['schedule']]
    for name, value in case['edits'].items():
        argv.extend(('--set', name + '=' + str(value)))
    if action == 'apply':
        argv.extend(('--backup-project', BACKUP))
    process = subprocess.run(argv, capture_output=True, text=True, timeout=45)
    result = json.loads(process.stdout or process.stderr)
    call = {'argv': argv, 'exit': process.returncode, 'stdout': process.stdout,
            'stderr': process.stderr, 'result': result}
    evidence['calls'].append(call)
    assert process.returncode == expected, call
    assert len(relay.rows) == before + 1
    wire = relay.rows[before]
    assert wire['done'].wait(5)
    call.update(parse_wire(wire, complete=complete), wire_index=before)
    assert not any(command.startswith(('NET OPEN ', 'PP PROGRAM ', 'DBDELETE '))
                   for command in call['commands'])
    assert all('/db' + UNIT in c for c in call['commands'] if c.startswith('PP LOAD '))
    return result, call


def literal_levels(case):
    rows = []
    for app, group, prefix, action in case['roles']:
        existing = group in case.get('groups', {56: []}).get(app, [])
        for address, zone in enumerate(ZONES, 1):
            if existing and address == 7:
                continue
            rows.append({'application': app, 'group': group, 'address': address,
                         'value': address, 'tag': prefix + ' ' + action + ' ' + zone})
    return rows


def group_identities(before, case, call=None):
    root = parse(before)
    result = {(int(app.findtext('Address')), int(group.findtext('Address'))): group.findtext('OID')
              for app in root.findall("Project/Network[Address='11']/Application")
              for group in refs.groups(app)}
    for (app, group, _tag), command in zip(case['creates'], refs.expected_creates(case)):
        if group is not None:
            if call is None:
                result[app, group] = 'planned-group:' + str(app) + ':' + str(group)
            else:
                index = call['commands'].index(command)
                assert call['statuses'][index] == 301
                result[app, group] = issued_oid(call['terminals'][index])
    return result


def issued_oid(terminal):
    match = re.fullmatch(r'OID=([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})', terminal)
    assert match is not None
    return match[1]


def role_name(prefix, action):
    return ('setback' if prefix == 'Setbk' else 'schedule') + '_' + {
        'Enable': 'on', 'Disable': 'off', 'Overrd': 'override'}[action]


def inspect_plan(preview, before, case, rows):
    identities = group_identities(before, case)
    remote = preview['remote_references']
    assert remote['planned_level_creations'] == [
        dict(kind='Level', application=row['application'], group=row['group'],
             group_identity=identities[row['application'], row['group']],
             address=row['address'], value=row['value'], initial_name='Level ' + str(row['address']),
             name=row['tag'], role=role_name(*row['tag'].split(' ')[:2]),
             phase='setback' if row['tag'].startswith('Setbk ') else 'schedule') for row in rows]
    expected_roles = case.get('prompt_roles', SETBACK + SCHEDULE)
    for phase, prefix, actions in (('setback', 'Setbk', ('Enable', 'Disable')),
                                   ('schedule', 'Sched', ('Enable', 'Disable', 'Overrd'))):
        records = []
        for action in actions:
            matches = [(a, g) for a, g, p, operation in expected_roles if p == prefix and operation == action]
            if not matches:
                records.append(dict(role=role_name(prefix, action), application=None, group=None,
                                    group_identity=None, unused=True, missing_addresses=[], created_addresses=[]))
                continue
            app, group = matches[0]
            existing = group in case.get('groups', {56: []}).get(app, [])
            missing = ([] if group == 255 or case.get('complete_levels') else
                       [n for n in range(1, 32) if not (existing and n == 7)])
            created = [row['address'] for row in rows if row['application'] == app and row['group'] == group]
            records.append(dict(role=role_name(prefix, action), application=app, group=group,
                                group_identity=identities[app, group], unused=group == 255,
                                missing_addresses=missing, created_addresses=created))
        required = any(record['missing_addresses'] for record in records)
        count = sum(len(record['created_addresses']) for record in records)
        assert remote['level_prompts'][phase] == dict(
            requested=case['prompts'][phase], required=required, offered=required,
            response_used=case['prompts'][phase] if required else None,
            executed=bool(count), created_count=count, roles=records)


def group_path(row):
    return NETWORK + '/' + str(row['application']) + '/' + str(row['group'])


def level_command(row):
    return ('DBADDSAFE ' + group_path(row)
            + ' Level ' + str(row['address']) + ' Level ' + str(row['address']))


def inspect_level_wire(call, rows, identities):
    issued = {}
    for row in rows:
        command = level_command(row)
        index = call['commands'].index(command)
        assert call['commands'].count(command) == 1 and call['statuses'][index] == 301
        assert call['commands'][index-1] == 'DBGET ' + group_path(row) + '/OID'
        assert call['statuses'][index-1] == 342
        assert call['terminals'][index-1] == group_path(row) + '/OID=' + identities[row['application'], row['group']]
        identity = issued_oid(call['terminals'][index])
        assert identity not in issued.values()
        assert call['commands'][index+1:index+4] == [
            'DBGET !' + identity + '/OID',
            'DBSETSAFE !' + identity + '/Value ' + str(row['value']),
            'DBSETSAFE !' + identity + '/TagName ' + row['tag']]
        assert call['statuses'][index+1:index+4] == [342, 200, 200]
        assert call['terminals'][index+1] == '!' + identity + '/OID=' + identity
        issued[(row['application'], row['group'], row['address'])] = identity
    assert [command for command in call['commands'] if command.startswith('DBSETSAFE ')] == [
        command for row in rows for command in (
            'DBSETSAFE !' + issued[(row['application'], row['group'], row['address'])] + '/Value ' + str(row['value']),
            'DBSETSAFE !' + issued[(row['application'], row['group'], row['address'])] + '/TagName ' + row['tag'])]
    return issued


def inspect_graph(before, after, case, rows, issued):
    old, current = parse(before), parse(after)
    old_oids = {node.text for node in old.iter('OID')}
    assert not set(issued.values()) & old_oids
    for row in rows:
        group = selected_group(current, row['application'], row['group'])
        found = [level for level in group.findall('Level') if level.findtext('Address') == str(row['address'])]
        assert len(found) == 1
        level = found[0]
        assert level.get('Value') == str(row['value'])
        assert level.findtext('TagName') == row['tag']
        assert level.findtext('OID') == issued[(row['application'], row['group'], row['address'])]
        group.remove(level)
    # This retains complete existing level records, DLT text, PP strings and
    # unrelated metadata while allowing only the source-declared additions.
    refs.assert_preserved(before, ET.tostring(current, encoding='unicode'), case)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('name', list(CASES))
def test_public_accepted_remote_level_choices(backend, variable, name, tmp_path):
    case = CASES[name]
    expected = literal_levels(case)
    with journey(backend, variable, tmp_path, name, case) as (owner, relay, evidence, specs, _endpoint):
        preview, first = settings_cli(relay, evidence, specs, case, action='preview')
        inspect_plan(preview, evidence['before_xml'], case, expected)
        assert {r['name']: r['after'] for r in preview['changed_parameters']} == case['changed']
        assert not any(c.startswith(('DBADD', 'DBSET', 'PP SET ', 'PP SAVE', 'PROJECT SAVE ', 'PROJECT COPY '))
                       for c in first['commands'])
        assert refs.document(owner) == evidence['before_xml']
        result, call = settings_cli(relay, evidence, specs, case)
        assert result['complete'] is True
        assert result['plan'] == {k: v for k, v in preview.items() if k != 'scope'}
        identities = group_identities(evidence['before_xml'], case, call)
        assert refs.creates_from_commands(call['commands']) == refs.expected_creates(case) + [level_command(row) for row in expected]
        mutation = bool(case['changed'] or case['creates'] or expected)
        assert call['commands'].count('PROJECT SAVE ' + PROJECT) == (2 if mutation else 0)
        assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in call['commands']) == bool(case['changed'])
        assert call['commands'].count('PROJECT COPY ' + PROJECT + ' ' + BACKUP) == int(mutation)
        if mutation:
            assert result['persistence_verified'] is True
            first_mutation = next(i for i, c in enumerate(call['commands']) if c.startswith(('DBADDSAFE ', 'PP SET ')))
            assert call['commands'].index('PROJECT COPY ' + PROJECT + ' ' + BACKUP) < first_mutation
            assert call['commands'].count('PROJECT CLOSE ' + PROJECT) == call['commands'].count('PROJECT LOAD ' + PROJECT) == 1
        issued = inspect_level_wire(call, expected, identities)
        assert len(result['levels']) == len(expected)
        for level, row in zip(result['levels'], expected):
            assert level['created'] and level['value_confirmed'] and level['tag_confirmed']
            assert level['oid'] == issued[row['application'], row['group'], row['address']]
        after, values = refs.document(owner), refs.parameters(owner)
        refs.assert_values(evidence['before_parameters'], values, case['changed'])
        inspect_graph(evidence['before_xml'], after, case, expected, issued)
        if mutation:
            for verb in ('SAVE', 'CLOSE', 'LOAD', 'USE'):
                assert owner.command('PROJECT ' + verb + ' ' + PROJECT).code == 200
        reopened, fresh = refs.document(owner), refs.parameters(owner)
        refs.assert_values(evidence['before_parameters'], fresh, case['changed'])
        inspect_graph(evidence['before_xml'], reopened, case, expected, issued)
        assert graph(after) == graph(reopened)
        evidence.update(preview=preview, result=result, literal_levels=expected,
            issued_levels=[dict(application=a, group=g, address=n, oid=identity)
                           for (a, g, n), identity in issued.items()],
            after_xml=after, after_parameters=values, reopened_xml=reopened,
            reopened_parameters=fresh, explicit_extra_reopen=mutation,
            preservation_verified=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('phase', ['setback-value', 'schedule-tag'])
def test_public_lost_successful_level_set_never_deletes_or_replays(backend, variable, phase, tmp_path):
    case = deepcopy(CASES['decline-setback-accept-schedule-graph-only'])
    if phase == 'setback-value':
        case.update(prompts={'setback': 'accept', 'schedule': 'decline'},
                    roles=SETBACK, edits={'PlantCycleTime': 23}, changed={'PlantCycleTime': 23})
    first_level = literal_levels(case)[0]
    with journey(backend, variable, tmp_path, 'lost-' + phase, case) as (owner, _relay, evidence, specs, endpoint):
        occurrence = 1 if phase == 'setback-value' else 2
        with FaultGate(endpoint, 'DBSETSAFE', 'drop', occurrence=occurrence) as fault:
            result, call = settings_cli(fault, evidence, specs, case, expected=1, complete=False)
        state = result['thermostat_template_evidence']
        assert state['complete'] is False and state['outcome_uncertain'] is True
        assert state['automatic_retries'] == 0 and state['rollback_performed'] is False
        assert not state['pp_save_attempted'] and not state['target_save_attempted']
        assert state['backup_created'] is True and fault.matches == occurrence
        identities = group_identities(evidence['before_xml'], case, call)
        command = level_command(first_level)
        assert refs.creates_from_commands(call['commands']) == [command]
        assert call['commands'].count('PROJECT SAVE ' + PROJECT) == 1
        assert not any(c.startswith(('PP SET ', 'PP SAVE', 'DBDELETE ', 'PROJECT CLOSE ', 'PROJECT LOAD ')) for c in call['commands'])
        index = call['commands'].index(command)
        assert call['commands'][index-1] == 'DBGET ' + group_path(first_level) + '/OID'
        assert call['statuses'][index-1] == 342
        assert call['terminals'][index-1] == group_path(first_level) + '/OID=' + identities[first_level['application'], first_level['group']]
        assert call['statuses'][index] == 301
        identity = issued_oid(call['terminals'][index])
        assert len(state['levels']) == 1
        level = state['levels'][0]
        assert level['oid'] == identity and level['created'] is True
        assert level['value_confirmed'] is (phase == 'schedule-tag')
        assert level['tag_confirmed'] is False
        assert level['field_attempted'] == ('Value' if phase == 'setback-value' else 'TagName')
        expected_tail = ['DBGET !' + identity + '/OID', 'DBSETSAFE !' + identity + '/Value 1']
        if phase == 'schedule-tag':
            expected_tail.append('DBSETSAFE !' + identity + '/TagName ' + first_level['tag'])
        assert call['commands'][index+1:] == expected_tail
        assert call['statuses'][index+1] == 342
        assert call['terminals'][index+1] == '!' + identity + '/OID=' + identity
        wires = fault.evidence()
        lost = [w for w in wires if 'lost_backend_terminal_hex' in w]
        assert len(lost) == 1
        assert ' 200 ' in bytes.fromhex(lost[0]['lost_backend_terminal_hex']).decode()
        assert lost[0]['lost_backend_terminal_hex'] not in lost[0]['response_hex']
        after, values = refs.document(owner), refs.parameters(owner)
        assert values == evidence['before_parameters']
        # Value loss retains the default tag; TagName loss retains the applied
        # final label. Neither case is a confirmed project save or auto-recovery.
        partial = dict(first_level, tag='Level 1') if phase == 'setback-value' else first_level
        key = (partial['application'], partial['group'], partial['address'])
        inspect_graph(evidence['before_xml'], after, dict(case, changed={}), [partial], {key: identity})
        evidence.update(result=result, fault_wires=wires, after_xml=after,
            after_parameters=values, partial_level=partial | {'oid': identity},
            replay_count=0, deletion_count=0, saved_response_lost=True,
            explicit_extra_reopen=False)
