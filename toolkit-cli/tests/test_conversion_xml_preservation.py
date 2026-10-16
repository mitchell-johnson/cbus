"""Literal XML contract and conversion lifecycle ownership regressions.

These are software preservation tests, not original Toolkit/XML observations.
Public backend save/reopen/fault cases are authored independently in a separate
module. XML rules: https://www.w3.org/TR/xml/#sec-white-space.
"""
from argparse import Namespace
from copy import deepcopy
import hashlib
import json
from xml.dom import minidom

import pytest

from cbus_toolkit import conversion_xml_preservation as semantic
from cbus_toolkit import toolkit_tweaker_lifecycle as life
from cbus_toolkit import toolkit_tweaker_workflow as creation
from cbus_toolkit.project import ProjectDocument


# Expected equality is transcribed from the XML preservation policy, not from
# any producer/comparator output. Default container indentation is explicit.
LITERALS = [
    ('<R>\n <A/>\n</R>', '<R><A/></R>', True),
    ('<R xml:space="preserve"> <A/> </R>', '<R xml:space="preserve"><A/> </R>', False),
    ('<R xml:space="preserve"><C> <A/> </C></R>', '<R xml:space="preserve"><C><A/></C></R>', False),
    ('<R xml:space="preserve"><C xml:space="default"> <A/> </C> </R>',
     '<R xml:space="preserve"><C xml:space="default"><A/></C> </R>', True),
    ('<R xml:space="preserve"><C xml:space="default"><A/></C> </R>',
     '<R xml:space="preserve"><C xml:space="default"><A/></C></R>', False),
    ('<R>a<A/> <B/>b</R>', '<R>a<A/><B/>b</R>', False),
    ('<R><A/> <B/>tail</R>', '<R><A/><B/>tail</R>', False),
    ('<R><A> </A></R>', '<R><A/></R>', False),
    ('<R><![CDATA[ ]]><A/> </R>', '<R><![CDATA[ ]]><A/></R>', False),
    ('<R>\u00a0<A/></R>', '<R><A/></R>', False),
    ('<R>\u2003<A/></R>', '<R><A/></R>', False),
    ('<R x="1" y="2"><A/></R>', '<R y="2" x="1"><A/></R>', True),
    ('<R><!-- keep --><A/></R>', '<R><!-- lost --><A/></R>', False),
    ('<R><?owner keep?><A/></R>', '<R><?owner lost?><A/></R>', False),
    ('<R xmlns:s="urn:one"><s:A/></R>', '<R xmlns:s="urn:two"><s:A/></R>', False),
]


def node(text):
    return minidom.parseString(text).documentElement


@pytest.mark.parametrize('before,after,equal', LITERALS, ids=[
    'format-indentation', 'preserve-direct', 'preserve-inherited', 'default-reset',
    'parent-tail-owned', 'mixed-separator', 'mixed-tail', 'leaf-whitespace',
    'CDATA-whitespace', 'NBSP-not-XML-whitespace', 'EM-space-not-XML-whitespace',
    'attribute-order', 'comment', 'PI', 'namespace',
])
def test_literal_xml_semantic_equality(before, after, equal):
    assert (semantic.shape(node(before)) == semantic.shape(node(after))) is equal


@pytest.mark.parametrize('mode', ['Preserve', 'unknown', ' preserve ', ''])
def test_invalid_xml_space_has_no_invented_valid_meaning(mode):
    with pytest.raises(ValueError, match='xml:space'):
        semantic.shape(node('<R xml:space="' + mode + '"><A/></R>'))


def test_detached_unit_clone_uses_its_actual_parent_scope():
    root = node('<R xml:space="preserve"><Unit> <Opaque><Child/> </Opaque> </Unit></R>')
    unit = root.getElementsByTagName('Unit')[0]
    clone = unit.cloneNode(deep=True)
    assert semantic.xml_space(unit.parentNode) == 'preserve'
    assert semantic.shape(clone, inherited_xml_space=semantic.xml_space(unit.parentNode)) == semantic.shape(unit)
    assert semantic.shape(clone) != semantic.shape(unit)
    assert semantic.unit_shape(unit.toxml().encode(), inherited_xml_space='preserve') == semantic.shape(unit)


def test_child_default_does_not_reset_parent_tail_scope():
    root = node('<R xml:space="preserve"><C xml:space="default"> <A/> </C> </R>')
    child = root.getElementsByTagName('C')[0]
    assert semantic.xml_space(child) == 'default'
    assert semantic.xml_space(child.parentNode) == 'preserve'
    assert semantic.shape(child) == semantic.shape(node('<C xml:space="default"><A/></C>'))
    assert semantic.shape(root) != semantic.shape(node('<R xml:space="preserve"><C xml:space="default"><A/></C></R>'))


def project(contents, *, address='WFTEST'):
    return ('<Project><Address>' + address + '</Address><TagName>' + address + '</TagName>'
            '<Network><Address>11</Address>' + contents + '</Network></Project>')


@pytest.mark.parametrize('opaque,lost', [
    ('<Opaque xml:space="preserve"><C> <A/> </C></Opaque>', '<Opaque xml:space="preserve"><C><A/></C></Opaque>'),
    ('<Opaque>a<A/> <B/>b</Opaque>', '<Opaque>a<A/><B/>b</Opaque>'),
    ('<Opaque>\u00a0<A/></Opaque>', '<Opaque><A/></Opaque>'),
], ids=['inherited-preserve', 'mixed-separator', 'NBSP-character'])
def test_backup_preserves_semantic_character_data_before_any_source_delete(opaque, lost):
    before = project(opaque).encode()
    good = project(opaque, address='BACKUP').encode()
    bad = project(lost, address='BACKUP').encode()
    life._backup_matches(good, before, 'BACKUP')
    with pytest.raises(RuntimeError, match='complete original tree'):
        life._backup_matches(bad, before, 'BACKUP')


def test_invalid_snapshot_refuses_in_document_boundary_before_mutation(monkeypatch):
    raw = project('<Opaque xml:space="unknown"><C/></Opaque>')
    calls = []
    class Database:
        def get(self, path, *, xml):
            calls.append(('get', path, xml))
            return raw
    monkeypatch.setattr(creation, 'NativeDatabase', lambda client: Database())
    monkeypatch.setattr(creation, 'xml_text', lambda response: response)
    with pytest.raises(ValueError, match='xml:space'):
        creation._document(object(), 'WFTEST')
    assert calls == [('get', '//WFTEST', True)]


def journal_with_inherited_unit():
    from test_toolkit_tweaker_lifecycle import valid_journal
    value = valid_journal()
    unit = '<Unit><Address>20</Address><OID>source</OID><Opaque><Child/> \t</Opaque></Unit>'
    before = ('<Project><Address>WFTEST</Address><Network xml:space="preserve"><Address>11</Address>'
              + unit + '</Network></Project>')
    plan = value['plan']
    plan['project_sha256'] = hashlib.sha256(before.encode()).hexdigest()
    plan['lifecycle'].update(before_project_xml=before, source_xml=unit)
    value['plan_sha256'] = creation._digest(plan)
    return value


def test_journal_unit_extraction_retains_ancestor_semantics():
    value = journal_with_inherited_unit()
    assert life._validate_journal(value) is value
    poisoned = deepcopy(value)
    poisoned['plan']['lifecycle']['source_xml'] = poisoned['plan']['lifecycle']['source_xml'].replace('<Child/> \t', '<Child/>')
    poisoned['plan_sha256'] = creation._digest(poisoned['plan'])
    with pytest.raises(ValueError, match='source metadata differs'):
        life._validate_journal(poisoned)


@pytest.mark.parametrize('where', ['project', 'backup'])
def test_read_only_recovery_does_not_accept_semantic_whitespace_loss(tmp_path, monkeypatch, where):
    value = journal_with_inherited_unit()
    path = tmp_path / 'attempt.json'
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    args = Namespace(journal=path, host='127.0.0.1', port=1234, auth_token_file=None)
    life.prepare_recovery(args)
    before = value['plan']['lifecycle']['before_project_xml']
    backup = before.replace('<Address>WFTEST</Address>', '<Address>BACKUP</Address>', 1)
    lost = lambda text: text.replace('<Child/> \t', '<Child/>')
    snapshots = {'WFTEST': lost(before) if where == 'project' else before,
                 'BACKUP': lost(backup) if where == 'backup' else backup}
    reads = []
    def document(client, project):
        reads.append(project)
        raw = snapshots[project].encode()
        return raw, ProjectDocument.from_bytes(raw)
    monkeypatch.setattr(creation, '_document', document)
    class Client:
        host = '127.0.0.1'
        port = 1234
        def command(self, command):
            raise AssertionError('Snapshot-only recovery test must not send: ' + command)
    original = path.read_bytes()
    result = life.recover(args, Client())
    assert reads == ['WFTEST', 'BACKUP'] and path.read_bytes() == original
    assert result['commands'] == [] and result['read_only_recovery_only'] and not result['replay_authorized']
    assert result['project_saved'] is None and not result['persistence_verified']
    assert result['disposition'] == ('conflict' if where == 'project' else 'observed_before')
    assert result['backup_verified_fresh'] is (where == 'project')


def test_creation_and_lifecycle_receipts_describe_the_same_exact_policy():
    literal = {'formatting_only_container_indentation_compared': False,
               'xml_space_preserve_override_enforced': True,
               'mixed_content_text_whitespace_compared': True,
               'whitespace_only_leaf_values_compared': True}
    assert creation._initial()['xml_comparison'] == life._initial()['xml_comparison'] == literal


def semantic_completed_journal():
    from test_toolkit_tweaker_lifecycle import completed_journal
    value = completed_journal()
    oid = value['destination_oid']
    source = '<Unit><Address>20</Address><OID>source</OID><Opaque><Child/> \t</Opaque></Unit>'
    unrelated = '<Extension><A/> \t</Extension>'
    prefix = '<Project><Address>WFTEST</Address><Network xml:space="preserve"><Address>11</Address>'
    before = prefix + source + unrelated + '</Network></Project>'
    staged = '<Unit><Address>1</Address><OID>' + oid + '</OID><Target><C/> \t</Target></Unit>'
    final = prefix + staged.replace('<Address>1</Address>', '<Address>20</Address>') + unrelated + '</Network></Project>'
    plan = value['plan']
    plan['project_sha256'] = hashlib.sha256(before.encode()).hexdigest()
    plan['lifecycle'].update(before_project_xml=before, source_xml=source)
    value.update(plan_sha256=creation._digest(plan), staged_unit_xml=staged,
                 staged_unit_parent_xml_space='preserve', expected_final_project_xml=final,
                 backup_xml=before.replace('<Address>WFTEST</Address>', '<Address>BACKUP</Address>', 1),
                 xml_preservation_profile=life.XML_PRESERVATION_PROFILE)
    value['creation']['plan'] = deepcopy(plan)
    return value


def test_completed_journal_proves_detached_stage_final_and_whole_backup_closure():
    value = semantic_completed_journal()
    assert life._validate_journal(value) is value
    assert life._journal_xml_preserved(value)


@pytest.mark.parametrize('damage,message', [
    ('target', 'staged/final Unit'), ('unrelated', 'final unrelated'),
    ('backup', 'backup semantic'), ('parent', 'ancestor scope'),
], ids=['target-preserve-loss', 'unrelated-preserve-loss', 'backup-preserve-loss', 'forged-stage-scope'])
def test_completed_journal_cannot_certify_a_lost_or_forged_xml_closure(damage, message):
    value = semantic_completed_journal()
    if damage == 'target':
        value['expected_final_project_xml'] = value['expected_final_project_xml'].replace('<C/> \t', '<C/>')
    elif damage == 'unrelated':
        value['expected_final_project_xml'] = value['expected_final_project_xml'].replace('<A/> \t', '<A/>')
    elif damage == 'backup':
        value['backup_xml'] = value['backup_xml'].replace('<A/> \t', '<A/>')
    else:
        value['staged_unit_parent_xml_space'] = 'default'
    with pytest.raises(ValueError, match=message):
        life._validate_journal(value)


def test_new_completed_journal_missing_stage_refuses_before_connection():
    value = semantic_completed_journal()
    value.pop('staged_unit_xml')
    with pytest.raises(ValueError, match='lacks semantic XML closure'):
        life._validate_journal(value)


@pytest.mark.parametrize('legacy', [False, True], ids=['new-closure', 'legacy-observation-only'])
def test_recovery_credit_requires_current_closure_without_promoting_old_acceptance(tmp_path, monkeypatch, legacy):
    value = semantic_completed_journal()
    if legacy:
        value['xml_comparison'] = dict(life.LEGACY_XML_COMPARISON)
        value.pop('xml_preservation_profile')
        # Precisely the historical erasure: it was accepted by the old shape.
        value['plan']['lifecycle']['source_xml'] = value['plan']['lifecycle']['source_xml'].replace('<Child/> \t', '<Child/>')
        value['plan_sha256'] = creation._digest(value['plan'])
        value['creation']['plan'] = deepcopy(value['plan'])
        value['expected_final_project_xml'] = value['expected_final_project_xml'].replace('<A/> \t', '<A/>')
    path = tmp_path / 'complete.json'
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    args = Namespace(journal=path, host='127.0.0.1', port=1234, auth_token_file=None, tls=False)
    life.prepare_recovery(args)
    retained = path.read_bytes()
    reads = []
    def document(client, project):
        reads.append(project)
        raw = value['expected_final_project_xml'] if project == 'WFTEST' else value['backup_xml']
        return raw.encode(), ProjectDocument.from_bytes(raw.encode())
    class Session:
        unit_type, firmware, catalog_number = 'DIMDU4', '2.7.00', 'TARGET'
        def __enter__(self): return self
        def values(self): return {'X': '1'}
        def __exit__(self, *unused): pass
    class Programmer:
        def __init__(self, client): pass
        def load(self, network, source):
            assert (network, source) == ('//WFTEST/11', '/db//WFTEST/11/p/20')
            return Session()
    monkeypatch.setattr(creation, '_document', document)
    monkeypatch.setattr(life, 'Programmer', Programmer)
    result = life.recover(args, object())
    assert result['disposition'] == 'observed_replaced'
    assert result['fresh_pp_verified'] and result['backup_verified_fresh']
    assert result['journal_xml_preservation_verified'] is (not legacy)
    assert result['persistence_verified'] is (not legacy)
    assert result['project_saved'] is (True if not legacy else None)
    assert result['commands'] == [] and reads == ['WFTEST', 'BACKUP']
    assert path.read_bytes() == retained and not result['replay_authorized']


def test_final_readdress_clone_retains_actual_ancestor_context(monkeypatch):
    value = semantic_completed_journal()
    raw = value['expected_final_project_xml'].encode()
    monkeypatch.setattr(creation, '_document', lambda client, project: (raw, ProjectDocument.from_bytes(raw)))
    monkeypatch.setattr(life, '_pp', lambda client, prepared, source: ({'X': '1'}, {'X': 1}))
    state = {'creation': {'oid': value['destination_oid'], 'verified_expected_parameters': {'X': 1}}}
    prepared = Namespace(project='WFTEST', network='//WFTEST/11', source='//WFTEST/11/p/20', address=1)
    staged = semantic.unit_shape(value['staged_unit_xml'].encode(), inherited_xml_space='preserve')
    assert life._verified_project(object(), prepared, state, value['plan']['lifecycle']['before_project_xml'].encode(), staged) == raw
    assert state['verified_final_pp'] == {'X': '1'}


@pytest.mark.parametrize('where', ['project', 'network', 'shadowed'], ids=['project-xmlns', 'network-xmlns', 'nearest-xmlns-wins'])
def test_journal_detached_unit_borrows_real_ancestor_namespace_bindings(where):
    value = journal_with_inherited_unit()
    source = '<Unit><Address>20</Address><OID>source</OID><x:Opaque x:mode="kept"><x:Child/> \t</x:Opaque></Unit>'
    project_attribute = ' xmlns:x="urn:outer"' if where != 'network' else ''
    network_attribute = ' xmlns:x="urn:inner"' if where != 'project' else ''
    before = ('<Project' + project_attribute + '><Address>WFTEST</Address><Network' + network_attribute
              + ' xml:space="preserve"><Address>11</Address>' + source + '</Network></Project>')
    document = ProjectDocument.from_bytes(before.encode())
    actual = document.resolve('/network/11/unit/20')
    assert actual.getElementsByTagName('x:Opaque')[0].namespaceURI == ('urn:outer' if where == 'project' else 'urn:inner')
    with pytest.raises(ValueError, match='valid XML'):
        semantic.unit_shape(source.encode(), inherited_xml_space='preserve')
    assert semantic.unit_shape(source.encode(), context_node=actual) == semantic.shape(actual)
    plan = value['plan']
    plan['project_sha256'] = hashlib.sha256(before.encode()).hexdigest()
    plan['lifecycle'].update(before_project_xml=before, source_xml=source)
    value['plan_sha256'] = creation._digest(plan)
    retained = value['plan']['lifecycle']['source_xml']
    assert life._validate_journal(value) is value
    assert value['plan']['lifecycle']['source_xml'] == retained
    historical = deepcopy(value)
    historical['xml_comparison'] = dict(life.LEGACY_XML_COMPARISON)
    assert life._validate_journal(historical) is historical
    assert not life._journal_xml_preserved(historical)


def test_context_parser_preserves_local_namespace_override_without_added_unit_attributes():
    document = node('<R xmlns:x="urn:outer" xml:space="preserve"><Unit xmlns:x="urn:own"><x:C/> \t</Unit></R>')
    actual = document.getElementsByTagName('Unit')[0]
    parsed = semantic.contextual_unit(actual.toxml().encode(), actual)
    assert parsed.attributes.items() == actual.attributes.items()
    assert parsed.getElementsByTagName('x:C')[0].namespaceURI == 'urn:own'
    assert semantic.unit_shape(actual.toxml().encode(), context_node=actual) == semantic.shape(actual)


@pytest.mark.parametrize('raw', [
    '<!DOCTYPE Unit [<!ENTITY unsafe "expanded">]><Unit>&unsafe;</Unit>',
    '<x:Unit xmlns:x="urn:foreign"/>', '<Unit/><Unit/>', '<Unit/>outside',
], ids=['DTD-forbidden', 'foreign-unit-root', 'multiple-unit-roots', 'outside-text'])
def test_contextual_unit_parser_keeps_secure_single_plain_unit_boundary(raw):
    actual = node('<R xmlns:x="urn:x"><Unit/></R>').getElementsByTagName('Unit')[0]
    with pytest.raises(ValueError):
        semantic.contextual_unit(raw.encode(), actual)


def test_completed_stage_and_final_use_namespace_context_without_rewriting_journal():
    value = semantic_completed_journal()
    plan = value['plan']
    before = plan['lifecycle']['before_project_xml'].replace('<Network ', '<Network xmlns:x="urn:x" ', 1)
    source = plan['lifecycle']['source_xml'].replace('<Opaque>', '<x:Opaque>').replace('</Opaque>', '</x:Opaque>')
    before = before.replace(plan['lifecycle']['source_xml'], source)
    plan['lifecycle'].update(before_project_xml=before, source_xml=source)
    plan['project_sha256'] = hashlib.sha256(before.encode()).hexdigest()
    value['plan_sha256'] = creation._digest(plan)
    value['creation']['plan'] = deepcopy(plan)
    value['staged_unit_xml'] = value['staged_unit_xml'].replace('<Target>', '<x:Target>').replace('</Target>', '</x:Target>')
    value['expected_final_project_xml'] = value['expected_final_project_xml'].replace('<Network ', '<Network xmlns:x="urn:x" ', 1).replace('<Target>', '<x:Target>').replace('</Target>', '</x:Target>')
    value['backup_xml'] = before.replace('<Address>WFTEST</Address>', '<Address>BACKUP</Address>', 1)
    retained = deepcopy(value)
    assert life._validate_journal(value) is value
    assert life._journal_xml_preserved(value) and value == retained


def test_prepared_unrelated_invalid_scope_refuses_locally_without_upgrading_legacy(tmp_path):
    value = journal_with_inherited_unit()
    plan = value['plan']
    before = plan['lifecycle']['before_project_xml'].replace('</Network>',
        '<Unrelated xml:space="unknown"><Child/></Unrelated></Network>')
    plan['lifecycle']['before_project_xml'] = before
    plan['project_sha256'] = hashlib.sha256(before.encode()).hexdigest()
    value['plan_sha256'] = creation._digest(plan)
    path = tmp_path / 'new.json'
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    original = path.read_bytes()
    args = Namespace(journal=path, host='127.0.0.1', port=1234, auth_token_file=None, tls=False)
    with pytest.raises(ValueError, match='xml:space default or preserve'):
        life.prepare_recovery(args)
    assert path.read_bytes() == original and not hasattr(args, '_toolkit_tweaker_recovery')
    legacy = deepcopy(value)
    legacy['xml_comparison'] = dict(life.LEGACY_XML_COMPARISON)
    legacy_path = tmp_path / 'legacy.json'
    legacy_path.write_text(json.dumps(legacy))
    legacy_path.chmod(0o600)
    legacy_args = Namespace(journal=legacy_path, host='127.0.0.1', port=1234, auth_token_file=None, tls=False)
    assert life.prepare_recovery(legacy_args) is legacy_args._toolkit_tweaker_recovery[0]
    assert not life._journal_xml_preserved(legacy_args._toolkit_tweaker_recovery[0])
    assert legacy_path.read_text() == json.dumps(legacy)
