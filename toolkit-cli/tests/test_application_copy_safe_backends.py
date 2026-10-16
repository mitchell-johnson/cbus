"""Whole Application SAFE-copy behavior through owned public CLI backends.

Literal field retention and new identities derive from target3.4 HELP*58.
Exact descendant/error receipts, external reference rewriting and Group/Level
chronology remain native acceptance gaps. These are owned-model assertions.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET

import pytest
from test_cgate_barcode_database_interop import FaultGate, graph, selected_binary
import test_cgl_application_order_backends as inherited
from test_cgate_named_database_interop import associated_evidence, associated_work, no_contact_trap

BACKENDS = inherited.BACKENDS
PROJECT = inherited.PROJECT
SOURCE_XML = '<Application><OID>aaaaaaaa-aaaa-4aaa-8aaa-000000000056</OID><TagName>Source</TagName><Address>56</Address><Group><OID>bbbbbbbb-bbbb-4bbb-8bbb-000000000007</OID><TagName>Heat</TagName><Address>7</Address><Level><OID>cccccccc-cccc-4ccc-8ccc-000000000073</OID><TagName>Null level</TagName><Address>3</Address></Level><TagsDLT><TagDLT><OID>dddddddd-dddd-4ddd-8ddd-000000000707</OID><LanguageID>1</LanguageID><FlavourID>1</FlavourID><TagType>TEXT</TagType><TagValue>Keep &amp; retain</TagValue></TagDLT></TagsDLT></Group><Group><OID>bbbbbbbb-bbbb-4bbb-8bbb-000000000008</OID><TagName>Cool</TagName><Address>8</Address><Level Value="77"><OID>cccccccc-cccc-4ccc-8ccc-000000000084</OID><TagName>Seventy seven</TagName><Address>4</Address><TagsDLT><TagDLT><OID>dddddddd-dddd-4ddd-8ddd-000000000804</OID><LanguageID>1</LanguageID><FlavourID>1</FlavourID><TagType>TEXT</TagType><TagValue>Literal</TagValue></TagDLT></TagsDLT></Level><TagsDLT/></Group><NetVar><OID>bbbbbbbb-bbbb-4bbb-8bbb-000000000009</OID><TagName>Variable</TagName><Address>9</Address><Level Value="200"><OID>cccccccc-cccc-4ccc-8ccc-000000000092</OID><TagName>Two hundred</TagName><Address>2</Address><TagsDLT/></Level></NetVar></Application>'
SOURCE_PATH = f'//{PROJECT}/254/56'
BASE_ORDER = [72, 0, 71, 66, 56]


def identity_set(xml):
    rows = [n.text for n in ET.fromstring(xml).iter('OID')]
    assert len(rows) == len(set(rows))
    return set(rows)


def semantic(element):
    # Preserve child/scalar/attribute order and every value; ignore only
    # source-to-copy OID text after independently checking all fresh identities.
    return (element.tag, tuple(element.attrib.items()),
            'IDENTITY' if element.tag == 'OID' else (element.text or ''),
            tuple(semantic(child) for child in element))


def literal_copied(address, name):
    expected = ET.fromstring(SOURCE_XML)
    expected.find('Address').text = str(address)
    expected.find('TagName').text = name
    return expected


def copied_null_level_after_load(xml, application_address):
    # Copy creates a pending XML owner; its empty label collection appears
    # on LOAD. The original plain NULL constructor remains a separate owner.
    # Insert exactly this one expected child, retaining the full graph/OIDs.
    expected = ET.fromstring(xml)
    applications = [n for n in expected.iter('Application')
                    if n.findtext('Address') == str(application_address)]
    assert len(applications) == 1
    levels = [level for group in applications[0].findall('Group')
              if group.findtext('Address') == '7' for level in group.findall('Level')
              if level.findtext('Address') == '3']
    assert len(levels) == 1
    level = levels[0]
    assert 'Value' not in level.attrib
    assert [child.tag for child in level] == ['OID', 'TagName', 'Address']
    ET.SubElement(level, 'TagsDLT')
    result = ET.tostring(expected, encoding='unicode')
    assert identity_set(result) == identity_set(xml)
    return result


@contextmanager
def journey(backend, variable, tmp_path):
    with inherited.journey(backend, variable, tmp_path) as values:
        s, _, _, evidence = values
        evidence.update(format='cbus-application-copy-safe-owned-v1',
            native_mutation_execution=False, target_help_profile='target_cgate_3_4',
            target_help_star_response_index=58,
            documented_contract_sha256='e2f07ed5de96e7d3c35607c7b7e1ec2b0c848de1feae600f983df5de7b32da8f',
            original_error_envelope_proven=False, external_reference_remapping_proven=False)
        try:
            yield values
        finally:
            associated_evidence(tmp_path / 'application-copy-safe-evidence.json', evidence)


def seed(s, trap):
    inherited.seed(s, trap)
    s.command(f'DBCREATENET 253 Other Cni {trap}')
    inherited.seed_typed_applications(s)
    s.command(f'DBADDSAFE //{PROJECT}/254 Application 56 Source', 301)
    null_level = ET.fromstring(SOURCE_XML).find('Group/Level')
    assert null_level.findtext('Address') == '3' and 'Value' not in null_level.attrib
    placeholder = null_level.findtext('OID')
    null_literal = ET.tostring(null_level, encoding='unicode')
    assert SOURCE_XML.count(null_literal) == 1
    # Import only complete numeric Levels, then use the public constructor
    # for NULL rather than weakening the complete XML admission grammar.
    uploaded = s.document('DBSETXML ' + SOURCE_PATH,
                          SOURCE_XML.replace(null_literal, '', 1), code=301)
    assert uploaded.final == '301 OID=aaaaaaaa-aaaa-4aaa-8aaa-000000000056'
    created = s.command(f'DBADDSAFE {SOURCE_PATH}/7 Level 3 Null level', 301)
    null_oid = created.final.removeprefix('301 OID=')
    assert re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', null_oid)
    assert null_oid not in identity_set(SOURCE_XML)
    assert s.command(f'DBGET !{null_oid}/OID', 342).final.endswith('=' + null_oid)
    assert s.command(f'DBGET !{null_oid}/Value', 342).final.endswith('=null')
    current = s.xml(path=SOURCE_PATH)
    assert semantic(ET.fromstring(current)) == semantic(ET.fromstring(SOURCE_XML))
    assert identity_set(current) == (identity_set(SOURCE_XML) - {placeholder}) | {null_oid}
    assert len(identity_set(current)) == 9
    s.evidence['null_level_seed'] = {'constructor': f'DBADDSAFE {SOURCE_PATH}/7 Level 3 Null level',
        'issued_oid': null_oid, 'getter_code': 342, 'getter_value': 'null',
        'complete_upload_omitted_only_null_level': True, 'other_eight_literal_oids_exact': True}
    s.export(BASE_ORDER)
    s.project('save', PROJECT)
    # Imported numeric Level label collections are already explicit. The
    # separate plain NULL constructor has no pending XML owner to mark on SAVE.
    s.project('close', PROJECT);s.project('load', PROJECT)
    source = s.xml(path=SOURCE_PATH)
    assert semantic(ET.fromstring(source)) == semantic(ET.fromstring(SOURCE_XML))
    return s.xml(), source


def copy(s, source=SOURCE_PATH, parent=None, address=80, name='Copied source', **kw):
    return s.db('copy', source, parent or f'//{PROJECT}/254', address, name, **kw)


def assert_copy(s, source, path, address, name, receipt=None, *, loaded=False):
    actual = s.xml(path=path)
    expected = literal_copied(address, name)
    if loaded:
        expected = ET.fromstring(copied_null_level_after_load(
            ET.tostring(expected, encoding='unicode'), address))
    assert semantic(ET.fromstring(actual)) == semantic(expected)
    if loaded:
        null_oid = ET.fromstring(actual).find('Group/Level/OID').text
        assert s.command(f'DBGET !{null_oid}/Value', 342).final.endswith('=null')
    old, new = identity_set(source), identity_set(actual)
    assert len(old) == len(new) == 9 and old.isdisjoint(new)
    if receipt:
        assert ET.fromstring(actual).findtext('OID') == receipt
    assert s.xml(path=SOURCE_PATH) == source
    return actual


def assert_copy_wire(call, source, parent, address, name, *, code=301):
    assert call['commands'] == [f'PROJECT USE {PROJECT}', f'DBGETXML {source}',
                               f'DBCOPYSAFE {source} {parent} {address} {name}']
    assert call['statuses'] == [200, 344, code]
    assert not any(c.startswith(('PROJECT SAVE', 'DBDELETE', 'PP ')) for c in call['commands'])


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_numeric_application_copy_complete_save_reload_isolation(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        before, source = seed(s, trap)
        value, call = copy(s)
        assert value['status'] == 301
        assert_copy_wire(call, SOURCE_PATH, f'//{PROJECT}/254', 80, 'Copied source')
        root = value['final'].rsplit('OID=', 1)[-1]
        copied = assert_copy(s, source, f'//{PROJECT}/254/80', 80, 'Copied source', root)
        s.export(BASE_ORDER + [80])
        # Every pre-existing Project child remains, with exactly one new root.
        expected = ET.fromstring(before)
        network = next(n for n in expected.iter('Network') if n.findtext('Address') == '254')
        network.append(ET.fromstring(copied))
        assert graph(s.xml()) == graph(ET.tostring(expected, encoding='unicode'))
        s.project('save', PROJECT);saved = s.xml()
        s.project('close', PROJECT);s.project('load', PROJECT)
        loaded_saved = copied_null_level_after_load(saved, 80)
        assert graph(s.xml()) == graph(loaded_saved)
        assert_copy(s, source, f'//{PROJECT}/254/80', 80, 'Copied source', root, loaded=True)
        s.export(BASE_ORDER + [80])
        # The original unassociated numeric Value alias is an existing
        # compatibility gap. The issued typed Level owns this byte mutation.
        loaded_application = ET.fromstring(s.xml(path=f'//{PROJECT}/254/80'))
        copied_byte_level = loaded_application.find("Group[Address='8']/Level[Address='4']")
        assert copied_byte_level is not None and copied_byte_level.attrib == {'Value': '77'}
        byte_oid = copied_byte_level.findtext('OID')
        assert byte_oid in identity_set(copied) and byte_oid not in identity_set(source)
        s.command(f'DBSETSAFE !{byte_oid}/Value 99')
        assert s.command(f'DBGET !{byte_oid}/Value', 342).final.endswith('=99')
        copied_byte_level.set('Value', '99')
        assert graph(s.xml(path=f'//{PROJECT}/254/80')) == graph(
            ET.tostring(loaded_application, encoding='unicode'))
        assert s.xml(path=SOURCE_PATH) == source
        assert 'Value="99"' in s.xml(path=f'//{PROJECT}/254/80/8/4')
        evidence['destination_byte_edit_owner'] = {'issued_level_oid': byte_oid,
            'route': 'DBSETSAFE !issuedLevelOID/Value byte',
            'legacy_unassociated_numeric_value_route_not_claimed': True}
        evidence.update(fresh_copy_oid_count=9, source_isolated_after_destination_change=True,
                        whole_graph_saved_reload_verified=True)
        state_path = s.work / 'state.json'
        restart_expected = loaded_saved
    if backend == 'cmqttd':
        # The original epoch is fully cleaned before this distinct service
        # uses its saved durable repository; binary and startup provenance are
        # independently retained by the same owning backend helper.
        try:
            with no_contact_trap():
                work = associated_work(tmp_path, 'restart')
                with inherited.session(backend, selected_binary(variable), work, evidence,
                                       state_path=state_path) as (fresh, _):
                    fresh.command('PROJECT USE ' + PROJECT)
                    fresh.project('close', PROJECT);fresh.project('load', PROJECT)
                    assert graph(fresh.xml()) == graph(restart_expected)
                    fresh.export(BASE_ORDER + [80])
                    assert_copy(fresh, source, f'//{PROJECT}/254/80', 80, 'Copied source', root, loaded=True)
            evidence['independent_daemon_restart_saved_graph_verified'] = True
        finally:
            associated_evidence(tmp_path / 'application-copy-safe-evidence.json', evidence)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_application_oid_copy_to_network_oid(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        _, source = seed(s, trap)
        source_oid = ET.fromstring(source).findtext('OID')
        parent_oid = ET.fromstring(s.xml(path=f'//{PROJECT}/253')).findtext('OID')
        value, call = copy(s, source='!' + source_oid, parent='!' + parent_oid, address=30, name='Copied  source')
        assert value['status'] == 301
        assert_copy_wire(call, '!' + source_oid, '!' + parent_oid, 30, 'Copied  source')
        assert_copy(s, source, f'//{PROJECT}/253/30', 30, 'Copied  source')
        s.export(BASE_ORDER);s.export([30], networks=(253,))
        evidence['unique_oid_application_and_network_owner_verified'] = True


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_application_cross_project_copy_preserves_source(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        before, source = seed(s, trap)
        s.command('PROJECT NEW OTHER');s.command(f'DBCREATENET 1 Target Cni {trap}')
        value, call = copy(s, parent='//OTHER/1', address=0, name='Cross')
        assert value['status'] == 301
        assert_copy_wire(call, SOURCE_PATH, '//OTHER/1', 0, 'Cross')
        # This getter uses the explicit selected source project; fully qualified
        # destination reads are separately selected through the existing API.
        s.command('PROJECT USE OTHER')
        actual = s.xml(project='OTHER', path='//OTHER/1/0')
        assert semantic(ET.fromstring(actual)) == semantic(literal_copied(0, 'Cross'))
        assert identity_set(actual).isdisjoint(identity_set(source))
        s.export([0], project='OTHER', networks=(1,))
        s.project('save', 'OTHER');saved = s.xml('OTHER')
        s.project('close', 'OTHER');s.project('load', 'OTHER')
        assert graph(s.xml('OTHER')) == graph(copied_null_level_after_load(saved, 0))
        loaded_copy = ET.fromstring(s.xml(project='OTHER', path='//OTHER/1/0'))
        null_oid = loaded_copy.find('Group/Level/OID').text
        assert s.command(f'DBGET !{null_oid}/Value', 342).final.endswith('=null')
        assert graph(s.xml()) == graph(before)
        evidence['cross_project_source_and_destination_isolated'] = True


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_application_copy_sibling_conflicts_do_not_mutate(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        _, source = seed(s, trap);copy(s)
        before = s.xml()
        for address, name in [(80, 'Other'), (81, 'Copied source')]:
            value, call = copy(s, address=address, name=name, expected=1)
            assert '409' in value['error']
            assert_copy_wire(call, SOURCE_PATH, f'//{PROJECT}/254', address, name, code=409)
            assert graph(s.xml()) == graph(before)
            assert s.xml(path=SOURCE_PATH) == source
        s.export(BASE_ORDER + [80])
        evidence['owned_conflict_envelope_not_native_capture'] = True


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_application_copy_wrong_parent_and_raw_level_refuse(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        _, source = seed(s, trap);before = s.xml()
        value, call = copy(s, parent=SOURCE_PATH, expected=1)
        assert '408' in value['error']
        assert_copy_wire(call, SOURCE_PATH, SOURCE_PATH, 80, 'Copied source', code=408)
        assert graph(s.xml()) == graph(before)
        # The existing public Languages constructor associates this owned
        # numeric Network without re-admitting its NULL/incomplete children.
        # Verify its sole new child before constructing a real raw Value.
        network_oid = ET.fromstring(s.xml(path=f'//{PROJECT}/254')).findtext('OID')
        language = s.command(f'DBADD !{network_oid} Languages', 301)
        language_oid = language.final.removeprefix('301 OID=')
        assert re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', language_oid)
        expected_associated = ET.fromstring(before)
        # Associating the first tag Network also selects the source Project
        # envelope. Require its sole schema addition in the exact first slot.
        assert expected_associated.tag == 'Installation'
        assert [child.tag for child in expected_associated] == ['Project']
        schema = ET.Element('DBVersion');schema.text = '2.3'
        expected_associated.insert(0, schema)
        network = next(n for n in expected_associated.iter('Network') if n.findtext('Address') == '254')
        assert network.find('Languages') is None
        assert language_oid not in {n.text for n in expected_associated.iter('OID')}
        ET.SubElement(ET.SubElement(network, 'Languages'), 'OID').text = language_oid
        assert graph(s.xml()) == graph(ET.tostring(expected_associated, encoding='unicode'))
        assert s.xml(path=SOURCE_PATH) == source
        # Preserve an authoritative opaque Level instead of a generic alias
        # or NULL. The associated owner synchronizes its typed/pending value.
        source_level = ET.fromstring(source).find("Group[Address='8']/Level[Address='4']")
        assert source_level is not None and source_level.attrib == {'Value': '77'}
        raw_oid = source_level.findtext('OID')
        s.command(f'DBSETSAFE !{raw_oid}/Value oops')
        assert s.command(f'DBGET !{raw_oid}/Value', 342).final.endswith('=oops')
        assert s.command(f'DBGET {SOURCE_PATH}/8/4/Value', 342).final.endswith('=oops')
        expected_raw = expected_associated.find(".//Application[Address='56']/Group[Address='8']/Level[Address='4']")
        assert expected_raw is not None and expected_raw.attrib == {'Value': '77'}
        expected_raw.set('Value', 'oops')
        raw_before = s.xml()
        assert graph(raw_before) == graph(ET.tostring(expected_associated, encoding='unicode'))
        evidence['authoritative_raw_level_seed'] = {'association': 'DBADD !issuedNetworkOID Languages',
            'language_oid': language_oid, 'issued_level_oid': raw_oid,
            'setter': 'DBSETSAFE !issuedLevelOID/Value oops', 'getters_code': 342,
            'associated_project_dbversion': '2.3',
            'whole_graph_only_schema_language_child_and_raw_value_changed': True}
        value, call = copy(s, expected=1)
        assert '408' in value['error']
        assert_copy_wire(call, SOURCE_PATH, f'//{PROJECT}/254', 80, 'Copied source', code=408)
        assert graph(s.xml()) == graph(raw_before)
        assert 'oops' in raw_before
        s.export(BASE_ORDER)
        evidence['raw_level_is_explicit_unsupported_copy_not_null'] = True


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_application_copy_unsaved_close_drops_only_destination(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        before, source = seed(s, trap);copy(s)
        assert_copy(s, source, f'//{PROJECT}/254/80', 80, 'Copied source')
        s.project('close', PROJECT);s.project('load', PROJECT)
        assert graph(s.xml()) == graph(before)
        s.export(BASE_ORDER)
        evidence['no_implicit_project_save_verified'] = True


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_application_copy_lost_301_no_replay_or_inverse_cleanup(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, endpoint, trap, evidence):
        before, source = seed(s, trap)
        with FaultGate(endpoint, 'DBCOPYSAFE', 'drop') as fault:
            value, call = copy(s, relay=fault, complete=False, expected=1)
        evidence['fault_wires'] = fault.evidence()
        assert 'error' in value and fault.matches == 1
        assert call['commands'] == [f'PROJECT USE {PROJECT}', 'DBGETXML ' + SOURCE_PATH,
                                   f'DBCOPYSAFE {SOURCE_PATH} //{PROJECT}/254 80 Copied source']
        assert call['statuses'] == [200, 344, None]
        losses = [r for r in evidence['fault_wires'] if r.get('lost_backend_terminal_hex')]
        assert len(losses) == 1
        terminal = bytes.fromhex(losses[0]['lost_backend_terminal_hex']).decode()
        assert re.fullmatch(r'\[[^]]+\] 301 OID=[0-9a-f-]+\r\n', terminal)
        assert not any(c.startswith(('DBDELETE', 'PROJECT SAVE', 'PROJECT CLOSE', 'PROJECT LOAD'))
                       for c in call['commands'])
        copied = assert_copy(s, source, f'//{PROJECT}/254/80', 80, 'Copied source')
        expected = ET.fromstring(before)
        next(n for n in expected.iter('Network') if n.findtext('Address') == '254').append(ET.fromstring(copied))
        assert graph(s.xml()) == graph(ET.tostring(expected, encoding='unicode'))
        s.export(BASE_ORDER + [80])
        evidence.update(actual_301_dropped=1, no_automatic_replay_or_inverse_cleanup=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_application_copy_lost_project_save_preserves_complete_copy(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (s, endpoint, trap, evidence):
        _, source = seed(s, trap);copy(s)
        before = s.xml()
        with FaultGate(endpoint, 'PROJECT SAVE', 'drop') as fault:
            value, call = s.cli('project', 'save', PROJECT, relay=fault, complete=False, expected=1)
        evidence['fault_wires'] = fault.evidence()
        assert 'error' in value and fault.matches == 1
        assert call['commands'] == ['PROJECT SAVE ' + PROJECT] and call['statuses'] == [None]
        losses = [r for r in evidence['fault_wires'] if r.get('lost_backend_terminal_hex')]
        assert len(losses) == 1
        assert re.fullmatch(r'\[[^]]+\] 200 OK\r\n', bytes.fromhex(losses[0]['lost_backend_terminal_hex']).decode())
        assert graph(s.xml()) == graph(before)
        s.project('close', PROJECT);s.project('load', PROJECT)
        assert graph(s.xml()) == graph(copied_null_level_after_load(before, 80))
        assert_copy(s, source, f'//{PROJECT}/254/80', 80, 'Copied source', loaded=True)
        s.export(BASE_ORDER + [80])
        evidence.update(actual_200_dropped=1, no_automatic_save_replay=True, complete_readback_after_new_load=True)
