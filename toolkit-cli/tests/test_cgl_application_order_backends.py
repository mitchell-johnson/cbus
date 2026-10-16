"""Application chronology through public CLI and owned Rust label databases.

The unchanged native fixture proves the four-element export literal. Its
malformed prefix imports use raw document transport, explicitly separate from
the Python CLI's stricter preflight. Lifecycle cases are owned-model regression
checks; they do not recover unknown legacy/native archive chronology, prove
Group/Level chronology, or exercise an original server/physical network.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from xml.etree import ElementTree as ET
from uuid import uuid4

import pytest

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import xml_text
from test_cgate_barcode_database_interop import FaultGate, graph, selected_binary
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend,
)

BACKENDS = [('cgate-mock', 'CBUS_CGATE_MOCK_BIN'), ('cmqttd', 'CBUS_CMQTTD_BIN')]
PROJECT = 'CGLP'
FIXTURE_SHA = '3a818506368c6eb6311125cb7f5a1272b5de6526b653d67b7ae197e043369490'
EXPECTED = [72, 0, 71, 66]
NAMES = {72: 'A72', 0: 'Zero', 71: 'A71', 255: 'A255', 66: 'A66'}


def pin(path):
    raw = path.read_bytes()
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def native_fixture():
    path = Path(__file__).resolve().parents[2] / 'rust/testdata/fixtures/native_cgate_cgl_routes.json'
    assert pin(path) == {'sha256': FIXTURE_SHA, 'bytes': 67552}
    value = json.loads(path.read_text())
    validation = next(row for row in value['scenarios'] if row['name'] == 'validation')['steps']
    literal = json.loads(validation[23]['reply'][1][4:])
    assert [a['address'] for a in literal['networks'][0]['applications']] == EXPECTED
    assert literal['networks'][0]['applications'] == [
        {'address': 72, 'type': 56, 'name': 'A72'},
        {'address': 0, 'type': 56, 'name': 'Zero'},
        {'address': 71, 'type': 56, 'name': 'A71'},
        {'address': 66, 'type': 56, 'name': 'A66', 'groups': [{'address': 1, 'name': 'G'}]},
    ]
    assert all(validation[i]['reply'][-1].startswith('408 ') for i in (15, 17, 18))
    return validation, literal


def input_pins():
    result = {'test_module': pin(Path(__file__))}
    for name in ('cgate', 'cgl', 'native', 'cli'):
        origin = Path(importlib.util.find_spec('cbus_toolkit.' + name).origin)
        result['cbus_toolkit.' + name] = {'origin': str(origin), **pin(origin)}
    return result


def new_evidence(backend, binary):
    return {'format': 'cbus-cgl-application-order-owned-v1', 'backend': backend,
        'actual_nodeid': os.environ.get('PYTEST_CURRENT_TEST', '').rsplit(' (', 1)[0],
        'binary': pin(binary), 'fixture': {'sha256': FIXTURE_SHA, 'bytes': 67552},
        'input_pins': input_pins(), 'literal_expected_application_order': EXPECTED,
        'original_execution': False, 'physical_acceptance': False,
        'group_level_native_order_proven': False, 'calls': [], 'direct_calls': [],
        'processes': [], 'wires': [], 'checkpoints': [],
        'limits': ['Malformed retained prefix cases are raw transport, not admitted CLI imports.',
                   'Lifecycle assertions are owned-model regression; legacy/archive order remains unknown.']}


def parse_cli_wire(row, *, complete):
    """Pin request identities and literal document framing without JSON sorting."""
    request = bytes.fromhex(row['request_hex']).decode().splitlines()
    commands, tags, documents = [], [], []
    index = 0
    while index < len(request):
        match = re.fullmatch(r'\[([^]]+)\] (.+)', request[index])
        assert match is not None, request
        tag, command = match.groups()
        if ' << ' in command:
            command, delimiter = command.rsplit(' << ', 1)
            assert command.startswith(('CGL IMPORT ', 'DBSETXML '))
            start = index + 1
            while index + 1 < len(request) and request[index + 1] != delimiter:
                index += 1
            assert index + 1 < len(request), 'Unterminated document'
            body = '\n'.join(request[start:index + 1]) + '\n'
            documents.append({'command': command, 'body': body, 'tag': tag,
                              'sha256': hashlib.sha256(body.encode()).hexdigest()})
            index += 1
        commands.append(command);tags.append(tag);index += 1
    assert tags and len(tags) == len(set(tags))
    terminals, payloads = {}, {tag: [] for tag in tags}
    for line in bytes.fromhex(row['response_hex']).decode().splitlines():
        match = re.fullmatch(r'\[([^]]+)\] (.*)', line)
        if match and match[1] in payloads:
            payloads[match[1]].append(match[2])
        terminal = re.fullmatch(r'\[([^]]+)\] (\d{3}) (.*)', line)
        if terminal and terminal[1] in payloads:
            assert terminal[1] not in terminals
            terminals[terminal[1]] = int(terminal[2]), terminal[3]
    assert set(terminals) <= set(tags)
    if complete:
        assert set(terminals) == set(tags)
    return {'commands': commands, 'tags': tags, 'documents': documents,
        'statuses': [terminals[t][0] if t in terminals else None for t in tags],
        'reply_lines': [payloads[t] for t in tags]}


class Session:
    def __init__(self, owner, relay, evidence, work):
        self.owner, self.relay, self.evidence, self.work = owner, relay, evidence, work
        self.sequence = 0

    def command(self, body, code=200):
        try:
            result = self.owner.command(body)
        except CGateError as exc:
            result = exc.response
        self.evidence['direct_calls'].append({'transport': 'raw-command', 'command': body,
            'lines': list(result.lines), 'code': result.code})
        assert result.code == code, result
        return result

    def document(self, command, text, code=200):
        try:
            result = self.owner.command_document(command, text)
        except CGateError as exc:
            result = exc.response
        self.evidence['direct_calls'].append({'transport': 'raw-document', 'command': command,
            'document': text, 'lines': list(result.lines), 'code': result.code})
        assert result.code == code, result
        return result

    def cli(self, *arguments, expected=0, relay=None, complete=True):
        relay = relay or self.relay
        first = len(relay.rows)
        argv = [sys.executable, '-m', 'cbus_toolkit', 'cgate', '--host', relay.endpoint[0],
            '--port', str(relay.endpoint[1]), '--timeout', '3', *map(str, arguments)]
        result = subprocess.run(argv, text=True, capture_output=True, timeout=30)
        call = {'transport': 'public-cli', 'argv': argv, 'exit': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr}
        self.evidence['calls'].append(call)
        value = json.loads(result.stdout or result.stderr)
        call['result'] = value
        assert result.returncode == expected, call
        rows = relay.rows[first:]
        assert len(rows) <= 1, 'One CLI invocation opened multiple connections'
        if rows:
            row = rows[0]
            assert row['done'].wait(5), 'CLI connection not closed'
            if row['request_hex']:
                call.update(parse_cli_wire(row, complete=complete))
            else:
                call.update(commands=[], statuses=[], documents=[], reply_lines=[])
            call['wire_index'] = first
        else:
            call.update(commands=[], statuses=[], documents=[], reply_lines=[])
        return value, call

    def export(self, expected, *, project=PROJECT, networks=(254,), applications=None):
        self.sequence += 1
        path = self.work / f'export-{self.sequence}.json'
        argv = ['cgl', 'export', project, path]
        for n in networks:
            argv += ['--network', n]
        for a in applications or ():
            argv += ['--application', a]
        value, call = self.cli(*argv)
        document = json.loads(path.read_text())
        assert value['version'] == document['cglVersion'] == '1.1'
        assert value['local_network'] == document['localNetwork'] == networks[0]
        current = next(n for n in document['networks'] if n['address'] == networks[0])
        assert [a['address'] for a in current.get('applications', [])] == expected
        assert all(a['address'] != 255 for n in document['networks'] for a in n.get('applications', []))
        assert call['commands'] == [f'CGL EXPORT {project} ' + ','.join(map(str, networks)) +
                                   ' ' + (','.join(map(str, applications)) if applications else '*')]
        assert call['statuses'] == [344]
        self.evidence['checkpoints'].append({'kind': 'public-export', 'document': document,
            'expected_local_application_order': list(expected), 'file': pin(path)})
        return document, call

    def import_labels(self, addresses, *, network=254, project=PROJECT, names=None):
        names = names or NAMES
        document = {'cglVersion': '1.1', 'localNetwork': 254, 'networks': [
            {'address': network, 'applications': [{'address': a, 'name': names.get(a, f'A{a}')}
                                                for a in addresses]}]}
        return self.import_document(document, project=project)

    def import_document(self, document, *, project=PROJECT, expected=0, relay=None, complete=True):
        self.sequence += 1
        path = self.work / f'import-{self.sequence}.json'
        path.write_text(json.dumps(document))
        return self.cli('cgl', 'import', project, path, '--no-backup', expected=expected,
                        relay=relay, complete=complete)

    def xml(self, project=PROJECT, path=None):
        self.command('PROJECT USE ' + project)
        result = NativeDatabase(self.owner).get(path or '//' + project, xml=True)
        text = xml_text(result)
        self.evidence['direct_calls'].append({'transport': 'raw-command',
            'command': 'DBGETXML ' + (path or '//' + project), 'code': result.code, 'xml': text})
        return text

    def db(self, action, *arguments, project=PROJECT, **kwargs):
        return self.cli('database', action, *arguments, '--project', project, **kwargs)

    def project(self, action, *names):
        value, call = self.cli('project', action, *names)
        assert call['commands'] == ['PROJECT ' + action.upper() + ' ' + ' '.join(names)]
        assert call['statuses'] == [200]
        return value, call


@contextmanager
def session(backend, binary, work, evidence, *, state_path=None):
    with owned_backend(backend, binary, work, state_path=state_path) as (endpoint, process):
        evidence['processes'].append(process)
        relay = None
        try:
            with RecordedGate(endpoint) as relay:
                with CGateClient(*relay.endpoint, timeout=15) as owner:
                    yield Session(owner, relay, evidence, work), endpoint
        finally:
            if relay is not None:
                evidence['wires'].extend(relay.evidence())


@contextmanager
def journey(backend, variable, tmp_path):
    binary = selected_binary(variable)
    evidence = new_evidence(backend, binary)
    try:
        with no_contact_trap() as trap:
            work = associated_work(tmp_path, 'backend')
            with session(backend, binary, work, evidence) as (s, endpoint):
                yield s, endpoint, trap, evidence
        evidence['closed_graph_trap_contacts'] = 0
    finally:
        evidence['input_pins_after'] = input_pins()
        associated_evidence(tmp_path / 'cgl-application-order-evidence.json', evidence)
        assert evidence['input_pins_after'] == evidence['input_pins']


def seed(s, trap, *, chain=False):
    s.command('PROJECT NEW ' + PROJECT)
    s.command('PROJECT USE ' + PROJECT)
    s.command(f'DBCREATENET 254 Local Cni {trap}', 200)
    if chain:
        for parent, child in zip(range(254, 247, -1), range(253, 246, -1)):
            s.command(f'DBCREATENET {child} Hop{254-child} Bridge {parent}/p/{child}', 200)
            s.command(f'DBADDSAFE //{PROJECT}/{parent} Unit {child} Bridge{child}', 301)
            s.command(f'DBSETSAFE //{PROJECT}/{parent}/p/{child}/UnitType BRIDGE')
            s.command(f'DBSETSAFE //{PROJECT}/{parent}/p/{child}/UnitName BRIDGE')
        s.command(f'DBCREATENET 240 Island Cni {trap}', 200)
    s.command('NET LOAD DB')
    # Deliberately never NET OPEN/SYNC: export routes use the closed label graph.


def seed_typed_applications(s):
    # CGL label creation itself need not issue a typed database OID. These
    # lifecycle cases start with actual public DBADDSAFE-owned identities.
    for address in EXPECTED:
        value, call = s.db('add', f'//{PROJECT}/254', 'application', address, NAMES[address])
        assert value['status'] == 301
        assert call['commands'] == ['PROJECT USE ' + PROJECT,
            f'DBADDSAFE //{PROJECT}/254 Application {address} {NAMES[address]}']


def payload(document):
    return {k: v for k, v in document.items() if k not in {'createdBy', 'createdTime'}}


def project_shape(text):
    """Copy/archive comparisons retain full graph shape except regenerated OIDs.

    OID identity on the source is separately checked; archives deliberately
    regenerate Config/Property identities. No label/list order is sorted here.
    """
    root = ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    project = root if root.tag == 'Project' else root.find('Project')
    assert project is not None
    for element in root.iter():
        if element.tag == 'OID':
            element.text = '<identity>'
    for tag in ('Address', 'TagName'):
        project.find(tag).text = '<project>'
    return graph(ET.tostring(root, encoding='unicode'))


def assert_foreign_xml_archive_shape(source, restored):
    """Admit only one source-owned plain DBVersion default outside Project."""
    def parse(text):
        return ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(
            insert_comments=True, insert_pis=True)))
    original, actual = parse(source), parse(restored)
    assert original.tag == actual.tag == 'Installation'
    assert original.findall('DBVersion') == []
    versions = actual.findall('DBVersion')
    assert len(versions) == 1
    version = versions[0]
    assert version.attrib == {} and version.text == '2.3' and list(version) == []
    assert not (version.tail or '').strip()
    original_oids = [node.text for node in original.iter('OID')]
    assert len(original_oids) == len(set(original_oids)) == 8
    assert [node.text for node in actual.iter('OID')] == original_oids
    # Every project field/list and issued identity remains exact, subject only
    # to the already-declared destination Project name/address change.
    assert len(original.findall('Project')) == len(actual.findall('Project')) == 1
    assert project_shape(ET.tostring(original.find('Project'), encoding='unicode')) == project_shape(
        ET.tostring(actual.find('Project'), encoding='unicode'))
    # Remove exactly the validated archive-only leaf from a copy, retaining
    # every remaining envelope node/attribute/order/comment/PI/opaque value.
    remaining = deepcopy(actual)
    remaining.remove(remaining.find('DBVersion'))
    assert project_shape(ET.tostring(remaining, encoding='unicode')) == project_shape(source)


def app_node(text, address):
    root = ET.fromstring(text)
    matches = [a for a in root.iter('Application') if a.findtext('Address') == str(address)]
    assert len(matches) == 1
    return matches[0]


def retained_child(s):
    """Exercise complete child copying/preservation without changing app order."""
    for args in [('add', f'//{PROJECT}/254/72', 'group', 9, 'Retained group'),
                 ('add', f'//{PROJECT}/254/72/9', 'level', 7, 'Retained level'),
                 ('set', f'//{PROJECT}/254/72/9/7/Value', 77)]:
        value, _ = s.db(*args)
        assert value['status'] == (301 if args[0] == 'add' else 200)


def application_content(element):
    element = deepcopy(element)
    for node in element.iter('OID'):
        node.text = '<issued identity>'
    for name in ('Address', 'TagName'):
        element.find(name).text = '<application>'
    return graph(ET.tostring(element, encoding='unicode'))


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_cgl_retained_native_prefix_order_filters_and_routes(backend, variable, tmp_path):
    validation, expected_document = native_fixture()
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        seed(s, trap, chain=True)
        s.import_labels([70], network=252, names={70: 'B'})
        for i, code in [(13, 200), (15, 408), (17, 408), (18, 408)]:
            reply = s.document('CGL IMPORT ' + PROJECT, validation[i]['document'], code)
            assert list(reply.lines) == validation[i]['reply']
        document, _ = s.export(EXPECTED, applications=[0, 66, 70, 71, 72, 255])
        assert payload(document) == payload(expected_document)
        reverse, _ = s.export(EXPECTED, applications=[72, 71, 66, 0, 255, 70])
        assert payload(reverse) == payload(document)
        selected, _ = s.export([71, 66], applications=[66, 71])
        assert [a['name'] for a in selected['networks'][0]['applications']] == ['A71', 'A66']
        assert [n['address'] for n in document['networks']] == [254, 253, 252, 251, 250, 249, 248]
        assert [n.get('route') for n in document['networks'][1:]] == [list(range(253, n-1, -1)) for n in range(253, 247, -1)]
        assert 247 not in [n['address'] for n in document['networks']]  # maximum six hops
        evidence['retained_raw_prefix_indices'] = [13, 15, 17, 18]
        evidence['public_export_literal_match'] = True


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_cgl_saved_load_runtime_reannouncement_preserves_order(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        seed(s, trap)
        s.import_labels([72, 0, 71, 255, 66])
        before, _ = s.export(EXPECTED)
        s.project('save', PROJECT)
        frozen = s.xml()
        s.import_labels([66, 71, 0, 72], names={a: 'MUST NOT RENAME' for a in EXPECTED})
        assert payload(s.export(EXPECTED)[0]) == payload(before)
        assert graph(s.xml()) == graph(frozen)
        for op in ('close', 'load', 'use'):
            s.project(op, PROJECT)
        s.command('NET LOAD DB')
        s.import_labels([66, 71, 0, 72], names={a: 'STILL NOT RENAME' for a in EXPECTED})
        assert payload(s.export(EXPECTED)[0]) == payload(before)
        assert graph(s.xml()) == graph(frozen)
        s.import_labels([64])
        s.export(EXPECTED + [64])
        evidence.update(runtime_reannouncement_did_not_move_or_rename=True, fresh_load_verified=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_cgl_typed_replace_readdress_copy_delete_recreate(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        seed(s, trap)
        seed_typed_applications(s)
        retained_child(s)
        baseline = s.xml()
        old0 = app_node(baseline, 0).findtext('OID')
        target = app_node(baseline, 71)
        oid71 = target.findtext('OID')
        target.find('TagName').text = 'Replacement seventy one'
        xml = s.work / 'replacement.xml'; xml.write_text(ET.tostring(target, encoding='unicode'))
        result, call = s.db('set-xml', '!' + oid71, xml)
        assert result['accepted'] and result['response']['status'] == 301
        assert result['project_save_requested'] is False
        assert any(c.startswith('DBSETXML !' + oid71) for c in call['commands'])
        s.export(EXPECTED)
        replacement = app_node(s.xml(), 71)
        assert replacement.findtext('OID') == oid71
        assert replacement.findtext('TagName') == 'Replacement seventy one'
        # SAFE Address writes do not implement this move. The admitted raw
        # command runs after same-session project selection, not a typed claim.
        readdress_commands = ['PROJECT USE ' + PROJECT, f'DBSET !{oid71}/Address 69']
        readdress_file = s.work / 'readdress-application.txt'
        readdress_file.write_text('\n'.join(readdress_commands) + '\n')
        result, call = s.cli('run', readdress_file)
        assert [row['status'] for row in result] == [200, 200]
        assert call['commands'] == readdress_commands and call['statuses'] == [200, 200]
        evidence['readdress_transport_scope'] = 'raw public cgate run DBSET issued Application OID after project selection'
        evidence['typed_safe_application_readdress_proven'] = False
        s.db('set', '!' + oid71 + '/TagName', 'Renamed in place')
        s.export([72, 0, 69, 66])
        renamed = app_node(s.xml(), 69)
        assert renamed.findtext('OID') == oid71
        assert renamed.findtext('TagName') == 'Renamed in place'
        # Existing complete Network DBCOPY uses same-session raw cgate run;
        # numeric whole-Application DBCOPYSAFE is a separate unimplemented scope.
        source_before_copy = s.xml()
        s.project('new', 'CGLOTHER')
        copy_command = f'DBCOPY //{PROJECT}/254 CGLOTHER'
        copy_commands = ['PROJECT USE ' + PROJECT, copy_command]
        copy_file = s.work / 'copy-network.txt'
        copy_file.write_text('\n'.join(copy_commands) + '\n')
        result, call = s.cli('run', copy_file)
        assert [row['status'] for row in result] == [200, 301]
        assert call['commands'] == copy_commands and call['statuses'] == [200, 301]
        s.export([72, 0, 69, 66], project='CGLOTHER')
        copied = s.xml('CGLOTHER')
        assert application_content(app_node(copied, 72)) == application_content(app_node(baseline, 72))
        assert graph(s.xml()) == graph(source_before_copy)
        original_oids = {n.text for n in app_node(baseline, 72).iter('OID')}
        copied_oids = {n.text for n in app_node(copied, 72).iter('OID')}
        assert len(original_oids) == len(copied_oids) == 3 and original_oids.isdisjoint(copied_oids)
        s.import_labels([60], project='CGLOTHER')
        s.export([72, 0, 69, 66, 60], project='CGLOTHER')
        assert graph(s.xml()) == graph(source_before_copy)
        evidence['copy_transport_scope'] = 'raw public cgate run PROJECT USE then complete cross-project Network DBCOPY'
        evidence['numeric_whole_application_dbcopy_safe_proven'] = False
        s.db('delete', '!' + old0)
        s.export([72, 69, 66])
        result, _ = s.db('add', f'//{PROJECT}/254', 'application', 0, 'Zero recreated')
        assert result['status'] == 301
        s.export([72, 69, 66, 0])
        assert app_node(s.xml(), 0).findtext('OID') != old0
        evidence['typed_order_checkpoints'] = [[72, 0, 71, 66], [72, 0, 69, 66],
            [72, 69, 66], [72, 69, 66, 0]]


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_cgl_complete_network_replacement_retains_and_appends(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        seed(s, trap)
        seed_typed_applications(s)
        network = ET.fromstring(s.xml(path=f'//{PROJECT}/254'))
        assert network.tag == 'Network'
        existing = list(network.findall('Application'))
        existing_oids = {a.findtext('Address'): a.findtext('OID') for a in existing}
        for a in existing:
            network.remove(a)
        for a in reversed(existing):
            network.append(a)
        new_oids = {address: str(uuid4()) for address in (80, 2)}
        assert len(set(new_oids.values())) == 2 and set(new_oids.values()).isdisjoint(existing_oids.values())
        for address in (80, 2):
            child = ET.SubElement(network, 'Application')
            ET.SubElement(child, 'OID').text = new_oids[address]
            ET.SubElement(child, 'TagName').text = f'New{address}'
            ET.SubElement(child, 'Address').text = str(address)
        path = s.work / 'network-replacement.xml';path.write_text(ET.tostring(network, encoding='unicode'))
        value, _ = s.db('set-xml', f'//{PROJECT}/254', path)
        assert value['accepted'] and value['response']['status'] == 301
        assert value['project_save_requested'] is False
        s.export(EXPECTED + [80, 2])
        after = s.xml()
        assert {a: app_node(after, int(a)).findtext('OID') for a in existing_oids} == existing_oids
        assert {a: app_node(after, a).findtext('OID') for a in new_oids} == new_oids
        evidence['submitted_new_application_order'] = [80, 2]
        evidence['submitted_new_application_oids'] = new_oids


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_cgl_project_copy_native_archive_and_graph_isolation(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        seed(s, trap)
        seed_typed_applications(s)
        retained_child(s)
        s.project('save', PROJECT)
        source = s.xml()
        s.project('copy', PROJECT, 'CGLCOPY')
        s.export(EXPECTED, project='CGLCOPY')
        assert project_shape(s.xml('CGLCOPY')) == project_shape(source)
        s.import_labels([60], project='CGLCOPY')
        s.export(EXPECTED + [60], project='CGLCOPY')
        s.export(EXPECTED)
        assert graph(s.xml()) == graph(source)
        s.command('FILE MKDIR Projects')
        s.command('FILE MKDIR Projects/archived')
        s.project('archive', PROJECT, 'application-order.xml')
        s.project('restore', 'CGLREST', 'application-order.xml')
        # The native-file XML archive has no chronology extension: do not fabricate it.
        s.export([0, 66, 71, 72], project='CGLREST')
        assert_foreign_xml_archive_shape(source, s.xml('CGLREST'))
        s.import_labels([90], project='CGLREST')
        s.export([0, 66, 71, 72, 90], project='CGLREST')
        assert graph(s.xml()) == graph(source)
        evidence.update(copy_order_retained=True, foreign_xml_archive_history_unknown=True,
                        source_graph_unchanged_after_independent_destination_mutations=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_cgl_lost_import_success_is_not_replayed_or_rolled_back(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, endpoint, trap, evidence):
        seed(s, trap)
        s.import_labels(EXPECTED)
        with FaultGate(endpoint, 'CGL IMPORT', 'drop') as fault:
            value, call = s.import_document({'cglVersion': '1.1', 'localNetwork': 254,
                'networks': [{'address': 254, 'applications': [{'address': 64, 'name': 'A64'}]}]},
                expected=1, relay=fault, complete=False)
            evidence['fault_wires'] = fault.evidence()
            assert 'error' in value and fault.matches == 1
            assert sum(c.startswith('CGL IMPORT ') for c in call['commands']) == 1
            assert not any(c.startswith(('DBDELETE', 'PROJECT SAVE', 'PROJECT CLOSE', 'PROJECT LOAD'))
                           for c in call['commands'])
            losses = [r for r in evidence['fault_wires'] if r.get('lost_backend_terminal_hex')]
            assert len(losses) == 1
            terminal = bytes.fromhex(losses[0]['lost_backend_terminal_hex']).decode().strip()
            assert re.fullmatch(r'\[[^]]+\] 200 OK\.', terminal)
        s.export(EXPECTED + [64])  # observation only; never import a second time
        evidence.update(actual_upstream_200_dropped=1, caller_receipt_uncertain=True,
                        automatic_replay_or_inverse_cleanup=False)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_cgl_invalid_python_document_has_no_prefix_mutation(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        seed(s, trap)
        s.import_labels(EXPECTED)
        before = s.xml()
        malformed = {'cglVersion': '1.1', 'localNetwork': 254, 'networks': [
            {'address': 254, 'applications': [{'address': 80, 'name': 'Must not appear'},
                                             {'address': 256, 'name': 'Invalid'}]}]}
        value, call = s.import_document(malformed, expected=1)
        assert 'Entity address must be an integer in 0..255' in value['error']
        assert not any(c.startswith(('CGL IMPORT', 'DBADD', 'DBSET', 'PROJECT SAVE', 'PROJECT COPY'))
                       for c in call['commands'])
        assert graph(s.xml()) == graph(before)
        s.export(EXPECTED)
        evidence['python_preflight_entire_document_before_import'] = True


def remove_legacy_order_fields(value):
    removed = []
    if isinstance(value, dict):
        if 'application_creation_order' in value:
            removed.append(value.pop('application_creation_order'))
        for child in value.values():
            removed.extend(remove_legacy_order_fields(child))
    elif isinstance(value, list):
        for child in value:
            removed.extend(remove_legacy_order_fields(child))
    return removed


@pytest.mark.parametrize('mode', ['recorded-restart', 'legacy-missing-field'])
def test_public_cmqttd_cgl_durable_restart_and_explicit_legacy_fallback(mode, tmp_path):
    backend = 'cmqttd';binary = selected_binary('CBUS_CMQTTD_BIN')
    evidence = new_evidence(backend, binary)
    state = tmp_path / 'durable-state.json'
    try:
        with no_contact_trap() as trap:
            work = associated_work(tmp_path, 'initial')
            with session(backend, binary, work, evidence, state_path=state) as (s, _):
                seed(s, trap)
                s.import_labels(EXPECTED)
                s.project('save', PROJECT)
                before = s.xml()
                capability, call = s.cli('exec', 'CMQTT CAPABILITIES')
                assert call['commands'] == ['CMQTT CAPABILITIES']
                capability_text = call['reply_lines'][0]
                combined = '\n'.join(capability_text)
                assert '"cgl_application_export_order":"tracked-creation-with-unknown-legacy-prefix"' in combined.replace(' ', '')
                assert '"cgl_group_level_export_order":"address-order-native-order-unverified"' in combined.replace(' ', '')
                if mode == 'recorded-restart':
                    s.project('archive', PROJECT, 'cmqttd:application-order')
            frozen_state = pin(state)
            if mode == 'legacy-missing-field':
                old = json.loads(state.read_text());removed = remove_legacy_order_fields(old)
                assert any(row['addresses'] == EXPECTED and not row['historical_prefix_unknown'] for row in removed)
                state.write_text(json.dumps(old))
                evidence['legacy_fixture_transform'] = {'before': frozen_state, 'after': pin(state),
                    'removed_order_fields': len(removed), 'only_missing_field_simulated': True}
            restart = associated_work(tmp_path, 'restart')
            with session(backend, binary, restart, evidence, state_path=state) as (s, _):
                s.command('PROJECT USE ' + PROJECT)
                expected = EXPECTED if mode == 'recorded-restart' else [0, 66, 71, 72]
                s.export(expected)
                assert graph(s.xml()) == graph(before)
                if mode == 'recorded-restart':
                    s.project('restore', 'CGLREST', 'cmqttd:application-order')
                    s.export(EXPECTED, project='CGLREST')
                    assert project_shape(s.xml('CGLREST')) == project_shape(before)
                s.import_labels([80, 2])
                s.export(expected + [80, 2])
            persisted = json.loads(state.read_text())
            rows = remove_legacy_order_fields(deepcopy(persisted))
            assert any(row['historical_prefix_unknown'] == (mode == 'legacy-missing-field')
                       and row['addresses'][-2:] == [80, 2] for row in rows)
        evidence.update(closed_graph_trap_contacts=0, restart_order_verified=True,
                        historical_order_unknown=mode == 'legacy-missing-field')
    finally:
        evidence['input_pins_after'] = input_pins()
        associated_evidence(tmp_path / 'cgl-application-order-evidence.json', evidence)
        assert evidence['input_pins_after'] == evidence['input_pins']
