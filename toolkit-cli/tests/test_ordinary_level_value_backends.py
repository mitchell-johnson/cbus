"""Ordinary numeric Level Value coherence through two owned public backends.

These are authored model regressions based on the maintained issued-LevelOID
byte initializer and source-owned project/mirror dispatch. No original server,
physical bus, arbitrary native raw/NULL grammar or full parity is asserted.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import re
from xml.etree import ElementTree as ET

import pytest

import test_cgl_application_order_backends as inherited
from test_application_safe_set_backends import (
    issued_oid, unrelated_unit_document, assert_unrelated_pp,
)
from test_cgate_barcode_database_interop import graph
from test_cgate_named_database_interop import STARTUP, associated_evidence

BACKENDS = inherited.BACKENDS
PROJECT = inherited.PROJECT
COPY = 'LVCOPY'
APP_PATH = f'//{PROJECT}/254/80'
LEVEL_PATH = APP_PATH + '/8/4'
LEVEL_OID = 'aaaaaaaa-aaaa-4aaa-8aaa-000000000004'
APPLICATION_XML = (
    '<Application><OID>aaaaaaaa-aaaa-4aaa-8aaa-000000000080</OID>'
    '<TagName>Application eighty</TagName><Address>80</Address>'
    '<Group><OID>aaaaaaaa-aaaa-4aaa-8aaa-000000000008</OID>'
    '<TagName>Group eight</TagName><Address>8</Address>'
    '<Level Value="77"><OID>' + LEVEL_OID + '</OID>'
    '<TagName>Selected byte</TagName><Address>4</Address>'
    '<TagsDLT><TagDLT><OID>dddddddd-dddd-4ddd-8ddd-000000000804</OID>'
    '<LanguageID>1</LanguageID><FlavourID>1</FlavourID>'
    '<TagType>TEXT</TagType><TagValue>Literal &amp; retained</TagValue>'
    '</TagDLT></TagsDLT></Level>'
    '<Level Value="88"><OID>aaaaaaaa-aaaa-4aaa-8aaa-000000000005</OID>'
    '<TagName>Unrelated byte</TagName><Address>5</Address><TagsDLT/></Level>'
    '<TagsDLT/></Group>'
    '<NetVar><OID>aaaaaaaa-aaaa-4aaa-8aaa-000000000009</OID>'
    '<TagName>Variable nine</TagName><Address>9</Address>'
    '<Level Value="66"><OID>aaaaaaaa-aaaa-4aaa-8aaa-000000000006</OID>'
    '<TagName>Nested byte</TagName><Address>6</Address><TagsDLT/></Level>'
    '</NetVar></Application>'
)


def parse(text):
    return ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(
        insert_comments=True, insert_pis=True)))


def serialize(root):
    return ET.tostring(root, encoding='unicode')


def identities(text):
    rows = [node.text for node in parse(text).iter('OID')]
    assert len(rows) == len(set(rows))
    assert all(re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',
                           value or '') for value in rows)
    return rows


def network(root):
    nodes = [n for n in root.iter('Network') if n.findtext('Address') == '254']
    assert len(nodes) == 1
    return nodes[0]


def application(root, address):
    nodes = [n for n in network(root).findall('Application')
             if n.findtext('Address') == str(address)]
    assert len(nodes) == 1
    return nodes[0]


def append_application(root, node):
    # The maintained Network formatter emits Applications before Units.
    # Preserve every existing child and its relative order, inserting only
    # the new Application immediately before the first existing Unit.
    parent = network(root)
    units = parent.findall('Unit')
    index = list(parent).index(units[0]) if units else len(parent)
    parent.insert(index, node)


def level(root, app=80, group=8, address=4):
    parent = application(root, app)
    groups = [n for n in parent if n.tag in ('Group', 'NetVar')
              and n.findtext('Address') == str(group)]
    assert len(groups) == 1
    rows = [n for n in groups[0].findall('Level') if n.findtext('Address') == str(address)]
    assert len(rows) == 1
    return rows[0]


def expected_byte(before, value, *, app=80, group=8, address=4):
    # Build the complete expected graph before sending any setter. Only the
    # exact selected Value attribute may differ; all OIDs/metadata/order remain.
    root = parse(before)
    selected = level(root, app, group, address)
    selected.set('Value', str(value))
    result = serialize(root)
    assert identities(result) == identities(before)
    return result


def xml(s, path=None, *, project=PROJECT):
    path = path or '//' + project
    value, call = s.db('get-xml', path, project=project)
    assert value['status'] == 344
    assert call['commands'] == ['PROJECT USE ' + project, 'DBGETXML ' + path]
    assert call['statuses'] == [200, 344]
    rows = [row[4:] for row in value['lines'] if row.startswith('347-')]
    # The retained native TCP formatter emits declaration and document rows.
    assert len(rows) == 2
    assert rows[0] == '<?xml version="1.0" encoding="utf-8"?>'
    assert value['final'] == '344 End XML snippet'
    assert value['lines'] == ['343-Begin XML snippet',
                              '347-' + rows[0], '347-' + rows[1], value['final']]
    text = '\n'.join(rows)
    parse(text)
    return text


def assert_graph(s, expected, *, project=PROJECT):
    actual = xml(s, project=project)
    assert graph(actual) == graph(expected)
    assert identities(actual) == identities(expected)
    s.evidence.setdefault('whole_graph_checkpoints', []).append({
        'project': project, 'expected_xml': expected, 'observed_xml': actual,
        'all_fields_order_metadata_and_oids_verified': True,
    })
    return actual


def read_value(s, path, expected, *, project=PROJECT):
    value, call = s.db('get', path + '/Value', project=project)
    final = f'342 {path}/Value={expected}'
    assert value['status'] == 342 and value['final'] == final
    assert value['lines'] == [final]
    assert call['commands'] == ['PROJECT USE ' + project, 'DBGET ' + path + '/Value']
    assert call['statuses'] == [200, 342]
    assert call['reply_lines'][-1] == [final]


def write_value(s, path, value, *, project=PROJECT, terminal='200 OK'):
    result, call = s.db('set', path + '/Value', str(value), project=project)
    assert result['status'] == 200 and result['final'] == terminal
    assert result['lines'] == [terminal]
    assert call['commands'] == ['PROJECT USE ' + project,
                               f'DBSETSAFE {path}/Value {value}']
    assert call['statuses'] == [200, 200]
    assert call['documents'] == []
    assert not any(c.startswith(('DBADD', 'DBDELETE', 'PROJECT SAVE', 'PP '))
                   for c in call['commands'])
    return result, call


def public_raw(s, command, code):
    # Same-session raw constructor through the public CLI, explicitly distinct
    # from NativeDatabase.add(Level), which initializes Value=Address.
    s.sequence += 1
    path = s.work / f'raw-owner-{s.sequence}.txt'
    commands = ['PROJECT USE ' + PROJECT, command]
    path.write_text('\n'.join(commands) + '\n')
    rows, call = s.cli('run', path)
    assert [row['status'] for row in rows] == [200, code]
    assert call['commands'] == commands and call['statuses'] == [200, code]
    assert len(rows) == 2
    return rows[-1], call


def save_reload(s, expected, *, project=PROJECT):
    _, call = s.project('save', project)
    assert call['reply_lines'] == [['200 OK']]
    assert_graph(s, expected, project=project)
    s.project('close', project)
    s.project('load', project)
    assert_graph(s, expected, project=project)


@contextmanager
def journey(backend, variable, tmp_path):
    module_pin = inherited.pin(Path(__file__))
    evidence = None
    try:
        with inherited.journey(backend, variable, tmp_path) as values:
            evidence = values[-1]
            evidence.update(format='cbus-ordinary-level-value-owned-v1',
                proposed_test_module=module_pin,
                source_basis='Existing issued-LevelOID byte owner and project-scoped mirror checks',
                native_mutation_execution=False, physical_acceptance=False,
                original_raw_null_lexical_policy_proven=False,
                limits=['Authored owned-model regressions; original mutation/native parity not established.',
                        'Plain NULL and Languages association use explicit same-session raw public commands.',
                        'Legacy arbitrary relative scalar caches are not reconstructed by public diagnostics.'])
            yield values
        assert evidence['closed_graph_trap_contacts'] == 0
        for row in evidence['processes']:
            assert all(row[key] for key in ('listener_owned', 'process_cleanup',
                'listener_closed', 'pci_closed', 'broker_closed'))
            expected = [('rx', frame) for frame in STARTUP] if backend == 'cmqttd' else []
            assert [(r['direction'], bytes.fromhex(r['hex'])) for r in row['pci_wire']] == expected
        evidence.update(no_later_pci=True, explicit_closed_graph_trap_zero=True,
                        every_owned_process_reaped_and_listeners_closed=True)
    finally:
        if evidence is not None:
            evidence['proposed_test_module_after'] = inherited.pin(Path(__file__))
            associated_evidence(tmp_path / 'ordinary-level-value-evidence.json', evidence)
            assert evidence['proposed_test_module_after'] == module_pin


def seed(s, trap):
    inherited.seed(s, trap)
    empty = xml(s)
    expected = parse(empty)
    assert network(expected).findall('Application') == []
    assert network(expected).findall('Unit') == []
    unit, call = s.db('add', f'//{PROJECT}/254', 'unit', 20, 'Unrelated unit')
    unit_oid = issued_oid(unit, call)
    unit_document = unrelated_unit_document(unit_oid)
    unit_file = s.work / 'unrelated-unit.xml'
    unit_file.write_text(unit_document)
    network(expected).append(parse(unit_document))
    replacement, call = s.db('set-xml', f'//{PROJECT}/254/p/20', unit_file)
    assert replacement['accepted'] is True
    assert replacement['project_save_requested'] is False
    assert replacement['response']['status'] == 301
    assert replacement['response']['final'] == '301 OID=' + unit_oid
    assert call['commands'] == ['PROJECT USE ' + PROJECT,
                               f'DBSETXML //{PROJECT}/254/p/20']
    assert call['statuses'] == [200, 301] and len(call['documents']) == 1
    assert graph(call['documents'][0]['body']) == graph(unit_document)
    append_application(expected, parse(APPLICATION_XML))
    expected = serialize(expected)
    # The expected complete tree is fixed before either Application mutation.
    created, call = s.db('add', f'//{PROJECT}/254', 'application', 80, 'Application eighty')
    created_oid = issued_oid(created, call)
    path = s.work / 'application-eighty.xml'
    path.write_text(APPLICATION_XML)
    result, call = s.db('set-xml', APP_PATH, path)
    assert result['accepted'] is True and result['project_save_requested'] is False
    assert result['response']['status'] == 301
    assert result['response']['final'] == '301 OID=aaaaaaaa-aaaa-4aaa-8aaa-000000000080'
    assert call['commands'] == ['PROJECT USE ' + PROJECT, 'DBSETXML ' + APP_PATH]
    assert call['statuses'] == [200, 301] and len(call['documents']) == 1
    assert graph(call['documents'][0]['body']) == graph(APPLICATION_XML)
    assert created_oid not in identities(APPLICATION_XML)
    assert_graph(s, expected)
    assert_unrelated_pp(s, expected)
    read_value(s, LEVEL_PATH, '77')
    read_value(s, '!' + LEVEL_OID, '77')
    s.evidence['independent_complete_seed'] = {
        'literal_application_xml': APPLICATION_XML, 'expected_project_xml': expected,
        'retired_constructor_oid': created_oid, 'replacement_received_301': True,
    }
    return expected


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_numeric_level_byte_edit_readbacks_save_reload(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        before = seed(s, trap)
        expected = expected_byte(before, 99)
        write_value(s, LEVEL_PATH, 99)
        assert_graph(s, expected)
        read_value(s, LEVEL_PATH, '99')
        read_value(s, '254/80/8/4', '99')
        read_value(s, '!' + LEVEL_OID, '99')
        save_reload(s, expected)
        assert_unrelated_pp(s, expected)
        read_value(s, LEVEL_PATH, '99')
        read_value(s, '!' + LEVEL_OID, '99')
        evidence['numeric_byte_save_reload_verified'] = True


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_invalid_numeric_level_bytes_refuse_atomically(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        before = seed(s, trap)
        for raw in ('-1', '256', 'oops', 'null', '1.5', '9223372036854775808'):
            value, call = s.db('set', LEVEL_PATH + '/Value', raw, expected=1)
            assert '400 Invalid level value' in value['error']
            assert call['commands'] == ['PROJECT USE ' + PROJECT,
                                       f'DBSETSAFE {LEVEL_PATH}/Value {raw}']
            assert call['statuses'] == [200, 400]
            assert call['reply_lines'][-1] == ['400 Invalid level value']
            assert not any(c.startswith(('DBDELETE', 'PROJECT SAVE', 'PP '))
                           for c in call['commands'])
            assert_graph(s, before)
            read_value(s, LEVEL_PATH, '77')
            read_value(s, '!' + LEVEL_OID, '77')
        save_reload(s, before)
        evidence['six_invalid_byte_refusals_preserved_complete_graph'] = True


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_plain_and_copied_null_levels_become_bytes(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        before = seed(s, trap)
        value, call = public_raw(s, f'DBADDSAFE {APP_PATH}/8 Level 7 Null level', 301)
        null_oid = issued_oid(value, call)
        expected = parse(before)
        group = application(expected, 80).find("Group[Address='8']")
        assert group is not None and group[-1].tag == 'TagsDLT'
        null = ET.Element('Level')
        for name, text in [('OID', null_oid), ('TagName', 'Null level'), ('Address', '7')]:
            ET.SubElement(null, name).text = text
        group.insert(len(group) - 1, null)
        plain = serialize(expected)
        assert_graph(s, plain)
        read_value(s, APP_PATH + '/8/7', 'null')
        read_value(s, '!' + null_oid, 'null')

        copied_result, call = s.db('copy', APP_PATH, f'//{PROJECT}/254', 81, 'Copied NULL')
        assert copied_result['status'] == 301
        assert call['commands'] == ['PROJECT USE ' + PROJECT, 'DBGETXML ' + APP_PATH,
                                   f'DBCOPYSAFE {APP_PATH} //{PROJECT}/254 81 Copied NULL']
        assert call['statuses'] == [200, 344, 301]
        copy_root_oid = copied_result['final'].removeprefix('301 OID=')
        copied = parse(xml(s, f'//{PROJECT}/254/81'))
        source = deepcopy(application(parse(plain), 80))
        assert len(list(source.iter('OID'))) == len(list(copied.iter('OID'))) == 8
        fresh = identities(serialize(copied))
        assert set(fresh).isdisjoint(identities(plain))
        source.find('Address').text = '81'
        source.find('TagName').text = 'Copied NULL'
        for old, new in zip(source.iter('OID'), copied.iter('OID')):
            old.text = new.text
        # Dynamic identities are admitted only in the unchanged literal tree.
        assert graph(serialize(copied)) == graph(serialize(source))
        assert source.findtext('OID') == copy_root_oid
        expected = parse(plain)
        append_application(expected, source)
        both_null = serialize(expected)
        assert_graph(s, both_null)
        copied_null_oid = level(expected, 81, 8, 7).findtext('OID')
        read_value(s, f'//{PROJECT}/254/81/8/7', 'null')
        read_value(s, '!' + copied_null_oid, 'null')
        plain_byte = expected_byte(both_null, 9, address=7)
        both_bytes = expected_byte(plain_byte, 11, app=81, address=7)
        write_value(s, APP_PATH + '/8/7', 9)
        assert_graph(s, plain_byte)
        write_value(s, f'//{PROJECT}/254/81/8/7', 11)
        assert_graph(s, both_bytes)
        read_value(s, '!' + null_oid, '9')
        read_value(s, '!' + copied_null_oid, '11')
        # Only the copied pending Level receives the source-owned empty label
        # collection on LOAD; the original plain constructor remains separate.
        loaded = parse(both_bytes)
        copied_null = level(loaded, 81, 8, 7)
        assert [n.tag for n in copied_null] == ['OID', 'TagName', 'Address']
        ET.SubElement(copied_null, 'TagsDLT')
        s.project('save', PROJECT)
        assert_graph(s, both_bytes)
        s.project('close', PROJECT);s.project('load', PROJECT)
        assert_graph(s, serialize(loaded))
        read_value(s, APP_PATH + '/8/7', '9')
        read_value(s, f'//{PROJECT}/254/81/8/7', '11')
        evidence.update(plain_null_transport='raw public run DBADDSAFE without initializer',
            copied_null_issued_oid_count=8, original_and_copy_byte_owners_isolated=True,
            copied_only_load_empty_tags_collection_verified=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_numeric_then_issued_oid_keeps_coherent_aliases(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        before = seed(s, trap)
        first = expected_byte(before, 99)
        final = expected_byte(first, 100)
        write_value(s, '254/80/8/4', 99)
        assert_graph(s, first)
        write_value(s, '!' + LEVEL_OID, 100)
        assert_graph(s, final)
        for path in (LEVEL_PATH, '254/80/8/4', '!' + LEVEL_OID):
            read_value(s, path, '100')
        write_value(s, LEVEL_PATH, 100)
        assert_graph(s, final)
        save_reload(s, final)
        for path in (LEVEL_PATH, '!' + LEVEL_OID):
            read_value(s, path, '100')
        evidence['numeric_then_oid_and_same_value_noop_coherent'] = True


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_selected_project_copy_retained_oid_bytes_are_isolated(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        original = seed(s, trap)
        expected_copy = parse(original)
        project = expected_copy.find('Project')
        assert project is not None
        project.find('Address').text = COPY
        project.find('TagName').text = COPY
        copied = serialize(expected_copy)
        s.project('copy', PROJECT, COPY)
        assert_graph(s, original)
        assert_graph(s, copied, project=COPY)
        assert identities(copied) == identities(original)
        copied_byte = expected_byte(copied, 99)
        source_byte = expected_byte(original, 100)
        copy_path = f'//{COPY}/254/80/8/4'
        write_value(s, copy_path, 99, project=COPY)
        assert_graph(s, copied_byte, project=COPY)
        assert_graph(s, original)
        save_reload(s, copied_byte, project=COPY)
        # The conflicting global !OID cache belongs to the other coherent
        # loaded copy. Read the selected owner's byte without rebinding it.
        read_value(s, LEVEL_PATH, '77')
        read_value(s, '!' + LEVEL_OID, '77')
        assert_graph(s, original)
        assert_graph(s, copied_byte, project=COPY)
        write_value(s, LEVEL_PATH, 100)
        assert_graph(s, source_byte)
        assert_graph(s, copied_byte, project=COPY)
        read_value(s, copy_path, '99', project=COPY)
        read_value(s, '!' + LEVEL_OID, '99', project=COPY)
        save_reload(s, source_byte)
        assert_graph(s, source_byte)
        assert_graph(s, copied_byte, project=COPY)
        evidence.update(project_copy_same_oid_source77_destination99_source100=True,
                        whole_project_graphs_and_metadata_isolated=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_associated_raw_level_owner_keeps_its_lexemes(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        before = seed(s, trap)
        expected = parse(before)
        assert expected.tag == 'Installation'
        assert [child.tag for child in expected] == ['Project']
        selected_network = network(expected)
        network_oid = selected_network.findtext('OID')
        value, call = public_raw(s, f'DBADD !{network_oid} Languages', 301)
        # DBADD uses the same actual native 301 envelope, without pretending
        # it was a typed DBADDSAFE receipt or a JSON oid property.
        assert value['status'] == 301 and value['lines'] == [value['final']]
        match = re.fullmatch(r'301 OID=([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})', value['final'])
        assert match is not None and call['reply_lines'][-1] == [value['final']]
        language_oid = match[1]
        assert language_oid not in identities(before)
        schema = ET.Element('DBVersion');schema.text = '2.3'
        expected.insert(0, schema)
        ET.SubElement(ET.SubElement(selected_network, 'Languages'), 'OID').text = language_oid
        associated = serialize(expected)
        assert_graph(s, associated)
        raw_expected = expected_byte(associated, 'oops')
        result, call = write_value(s, LEVEL_PATH, 'oops', terminal='200 OK.')
        assert_graph(s, raw_expected)
        read_value(s, LEVEL_PATH, 'oops')
        read_value(s, '!' + LEVEL_OID, 'oops')
        save_reload(s, raw_expected)
        read_value(s, LEVEL_PATH, 'oops')
        read_value(s, '!' + LEVEL_OID, 'oops')
        evidence.update(associated_raw_owner_preserved=True,
            associated_project_dbversion='2.3', raw_value='oops',
            ordinary_byte_adapter_did_not_intercept_associated_owner=True)
