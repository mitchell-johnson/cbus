"""Target-HELP-guided Application SAFE setters on owned Rust backends.

Actual native Address/status/no-op/case mutation receipts remain unproved.
These are proposed owning public-CLI regressions, not historical acceptance.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET

import pytest

from test_cgl_application_order_backends import (
    BACKENDS, PROJECT, app_node, journey, pin, seed, seed_typed_applications,
    Session, session, new_evidence, input_pins,
)
from cbus_toolkit.cgate import CGateClient
from test_cgate_barcode_database_interop import FaultGate, graph, selected_binary
from test_cgate_named_database_interop import (
    associated_evidence, associated_work, no_contact_trap,
)

ROSTER = [72, 0, 71, 66, 50]
MOVED_ROSTER = [72, 0, 70, 66, 50]


@contextmanager
def proposed_journey(backend, variable, tmp_path):
    before = pin(Path(__file__))
    with journey(backend, variable, tmp_path) as payload:
        evidence = payload[-1]
        evidence.update(format='cbus-application-safe-set-owned-v1',
            target_Address_mutation_native_acceptance=False,
            source_basis='target3.4 HELP* business rules; modeled status/no-op policy',
            proposed_test_module=before)
        try:
            yield payload
        finally:
            evidence['proposed_test_module_after'] = pin(Path(__file__))
            assert evidence['proposed_test_module_after'] == before


def issued_oid(value, call):
    """Use the actual public JSON/native 301 receipt, not an invented key."""
    assert call['exit'] == 0
    assert value['status'] == 301
    match = re.fullmatch(
        r'301 OID=([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})',
        value['final'],
    )
    assert match is not None, value
    assert value['lines'] == [value['final']]
    assert len(call['statuses']) == len(call['reply_lines'])
    created = [lines for code, lines in zip(call['statuses'], call['reply_lines'])
               if code == 301]
    assert created == [[value['final']]], call
    assert sum(command.startswith('DBADDSAFE ') for command in call['commands']) == 1
    return match[1]


def unrelated_unit_document(oid):
    """Independent complete Unit/PP fixture through admitted DBSETXML."""
    unit = ET.Element('Unit')
    for name, value in (
        ('OID', oid), ('TagName', 'Unrelated unit'), ('Address', '20'),
        ('UnitType', 'PC_TSA'), ('UnitName', 'Unrelated unit scalar'),
        ('SerialNumber', '123456.7'), ('FirmwareVersion', '5.4.01'),
    ):
        ET.SubElement(unit, name).text = value
    for name, value in (
        ('Application', '71'), ('UnitAddress', '20'), ('UnrelatedParameter', '173'),
    ):
        ET.SubElement(unit, 'PP', Name=name, Value=value)
    # The plain native Unit mapper serializes CatalogNumber after all PP rows.
    ET.SubElement(unit, 'CatalogNumber').text = '5070THP,BK'
    return ET.tostring(unit, encoding='unicode')


def assert_unrelated_pp(s, expected_document):
    root = ET.fromstring(expected_document)
    expected = root.find("Project/Network[Address='254']/Unit[Address='20']")
    assert expected is not None
    assert expected.findtext('UnitType') == 'PC_TSA'
    assert expected.findtext('FirmwareVersion') == '5.4.01'
    assert [(row.attrib, row.text, list(row)) for row in expected.findall('PP')] == [
        ({'Name': 'Application', 'Value': '71'}, None, []),
        ({'Name': 'UnitAddress', 'Value': '20'}, None, []),
        ({'Name': 'UnrelatedParameter', 'Value': '173'}, None, []),
    ]
    # The complete retained Unit is independent of Application chronology.
    observed = s.xml(path=f'//{PROJECT}/254/p/20')
    assert graph(observed) == graph(ET.tostring(expected, encoding='unicode'))
    for name, value in [('Application', '71'), ('UnitAddress', '20'),
                        ('UnrelatedParameter', '173')]:
        result = s.command(f'PP QUICKGET //{PROJECT}/254/p/20 {name}', code=315)
        assert result.lines == (f'315 {name}={value}',)
    s.evidence.setdefault('unrelated_unit_pp_checks', []).append({
        'expected_unit_xml': ET.tostring(expected, encoding='unicode'),
        'observed_unit_xml': observed,
        'parameters': {'Application': '71', 'UnitAddress': '20',
                       'UnrelatedParameter': '173'},
        'physical_programming': False,
    })


def seed_graph(s, trap):
    seed(s, trap)
    seed_typed_applications(s)
    value, call = s.db('add', f'//{PROJECT}/254', 'application', 50, 'Neighbor50')
    issued_oid(value, call)
    group, call = s.db('add', f'//{PROJECT}/254/71', 'group', 1, 'Group one')
    group_oid = issued_oid(group, call)
    level, call = s.db('add', f'//{PROJECT}/254/71/1', 'level', 7, 'Level seven')
    level_oid = issued_oid(level, call)
    s.db('set', '!' + level_oid + '/Value', '77')
    variable, call = s.db('add', f'//{PROJECT}/254/71', 'netvar', 2, 'Variable two')
    issued_oid(variable, call)
    nested, call = s.db('add', f'//{PROJECT}/254/71/2', 'level', 8, 'Level eight')
    nested_oid = issued_oid(nested, call)
    s.db('set', '!' + nested_oid + '/Value', '88')
    # Unrelated PP and database-only fields remain independently visible.
    unit, call = s.db('add', f'//{PROJECT}/254', 'unit', 20, 'Unrelated unit')
    unit_oid = issued_oid(unit, call)
    unit_document = unrelated_unit_document(unit_oid)
    unit_path = s.work / 'unrelated-unit.xml'
    unit_path.write_text(unit_document)
    replacement, call = s.db('set-xml', f'//{PROJECT}/254/p/20', unit_path)
    assert replacement['accepted'] is True
    assert replacement['project_save_requested'] is False
    assert replacement['response']['status'] == 301
    assert replacement['response']['final'] == '301 OID=' + unit_oid
    assert call['commands'] == ['PROJECT USE ' + PROJECT,
                               f'DBSETXML //{PROJECT}/254/p/20']
    assert call['statuses'] == [200, 301]
    assert len(call['documents']) == 1
    assert graph(call['documents'][0]['body']) == graph(unit_document)
    s.db('set', '!' + group_oid + '/Description', 'Preserve description')
    before = s.xml()
    root = app_node(before, 71)
    assert len(list(root.iter('OID'))) == 5
    assert len({node.text for node in root.iter('OID')}) == 5
    assert root.find('Group/Level').attrib['Value'] == '77'
    assert root.find('NetVar/Level').attrib['Value'] == '88'
    seeded_unit = ET.fromstring(before).find("Project/Network[Address='254']/Unit[Address='20']")
    assert seeded_unit is not None
    assert graph(ET.tostring(seeded_unit, encoding='unicode')) == graph(unit_document)
    assert_unrelated_pp(s, before)
    return before, root.findtext('OID'), group_oid, unit_oid


def moved_document(before, destination, name=None):
    root = ET.fromstring(before)
    application = next(node for node in root.iter('Application')
                       if node.findtext('Address') == '71')
    application.find('Address').text = str(destination)
    if name is not None:
        application.find('TagName').text = name
    return ET.tostring(root, encoding='unicode')


def scalar(s, path):
    value, call = s.db('get', path)
    assert call['commands'] == ['PROJECT USE ' + PROJECT, 'DBGET ' + path]
    assert call['statuses'] == [200, 342]
    return value


@pytest.mark.parametrize('selector', ['numeric', 'oid'])
@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_application_safe_move_preserves_full_graph(selector, backend, variable, tmp_path):
    with proposed_journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        before, oid, group_oid, unit_oid = seed_graph(s, trap)
        target = f'//{PROJECT}/254/71' if selector == 'numeric' else '!' + oid
        result, call = s.db('set', target + '/Address', '70')
        assert result['status'] == 200
        assert call['commands'] == ['PROJECT USE ' + PROJECT, 'DBSETSAFE ' + target + '/Address 70']
        assert call['statuses'] == [200, 200]
        assert not any(command.startswith(('DBADD', 'DBDELETE', 'PP ', 'PROJECT SAVE')) for command in call['commands'])
        observed = s.xml()
        assert graph(observed) == graph(moved_document(before, 70))
        assert app_node(observed, 70).findtext('OID') == oid
        s.export(MOVED_ROSTER)
        assert scalar(s, '!' + group_oid + '/Description')['final'] == '342 !' + group_oid + '/Description=Preserve description'
        assert scalar(s, '!' + unit_oid + '/Application')['final'] == '342 !' + unit_oid + '/Application=71'
        assert_unrelated_pp(s, before)
        for path in (f'//{PROJECT}/254/71', f'//{PROJECT}/254/71/1'):
            # Typed XML selectors prove the old graph is absent. Generic
            # numeric DBGET scalar fallback is a separate legacy boundary.
            _, denied = s.db('get-xml', path, expected=1)
            assert denied['commands'] == ['PROJECT USE ' + PROJECT, 'DBGETXML ' + path]
            assert denied['statuses'] == [200, 401]
        assert graph(s.xml()) == graph(observed)
        s.project('save', PROJECT)
        for action in ('close', 'load', 'use'):
            s.project(action, PROJECT)
        loaded = s.xml()
        # These directly SAFE-created Levels have no pending XML mirror or
        # deferred saved-Level marker. That source branch preserves the full
        # XML on LOAD; imported pending Levels are a separate captured profile.
        assert graph(loaded) == graph(observed)
        assert_unrelated_pp(s, before)
        s.export(MOVED_ROSTER)
        evidence.update(selector=selector, before_xml=before, after_xml=observed,
            reloaded_xml=loaded, expected_xml=moved_document(before, 70),
            root_oid=oid, descendant_description_oid=group_oid,
            unrelated_unit_oid=unit_oid, PP_application_migration=False)


REFUSALS = [
    ('plus', 'Address', '+70', 408), ('minus', 'Address', '-0', 408),
    ('hex', 'Address', '0x46', 408), ('overflow', 'Address', '256', 408),
    ('text', 'Address', 'oops', 408), ('occupied', 'Address', '72', 408),
    ('name-collision', 'TagName', 'A72', 408), ('blank-name', 'TagName', '', 400),
]


@pytest.mark.parametrize('reason,field,value,code', REFUSALS, ids=[r[0] for r in REFUSALS])
@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_application_safe_refusal_is_atomic(reason, field, value, code, backend, variable, tmp_path):
    with proposed_journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        before, oid, _, _ = seed_graph(s, trap)
        _, call = s.db('set', '!' + oid + '/' + field, value, expected=1)
        command = 'DBSETSAFE !' + oid + '/' + field + ' ' + value
        assert call['commands'] == ['PROJECT USE ' + PROJECT, command.rstrip()]
        assert call['statuses'] == [200, code]
        assert graph(s.xml()) == graph(before)
        s.export(ROSTER)
        evidence.update(refusal_reason=reason, before_xml=before, refusal_after_xml=s.xml())


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_application_safe_noop_rename_and_replacement_share_identity(backend, variable, tmp_path):
    with proposed_journey(backend, variable, tmp_path) as (s, _, trap, evidence):
        before, oid, _, _ = seed_graph(s, trap)
        s.db('set', '!' + oid + '/Address', '71')
        assert graph(s.xml()) == graph(before)
        s.db('set', '!' + oid + '/TagName', 'Unicode Ω renamed')
        assert graph(s.xml()) == graph(moved_document(before, 71, 'Unicode Ω renamed'))
        s.db('set', '!' + oid + '/Address', '70')
        current = s.xml()
        assert graph(current) == graph(moved_document(before, 70, 'Unicode Ω renamed'))
        replacement = deepcopy(app_node(current, 70))
        replacement.find('Address').text = '69'
        path = s.work / 'application.xml'
        path.write_text(ET.tostring(replacement, encoding='unicode'))
        value, call = s.db('set-xml', '!' + oid, path)
        assert value['accepted'] and value['response']['status'] == 301
        assert value['project_save_requested'] is False
        assert graph(s.xml()) == graph(moved_document(before, 69, 'Unicode Ω renamed'))
        s.export([72, 0, 69, 66, 50])
        evidence.update(before_xml=before, after_xml=s.xml(), same_oid=oid, true_address_noop=True)


@pytest.mark.parametrize('phase', ['lost-move', 'lost-save'])
@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_application_safe_lost_success_is_not_replayed(phase, backend, variable, tmp_path):
    with proposed_journey(backend, variable, tmp_path) as (s, endpoint, trap, evidence):
        before, oid, _, _ = seed_graph(s, trap)
        if phase == 'lost-save':
            s.db('set', '!' + oid + '/Address', '70')
        match = 'DBSETSAFE !' + oid + '/Address' if phase == 'lost-move' else 'PROJECT SAVE'
        with FaultGate(endpoint, match, 'drop') as fault:
            if phase == 'lost-move':
                value, call = s.db('set', '!' + oid + '/Address', '70', expected=1, relay=fault, complete=False)
            else:
                value, call = s.cli('project', 'save', PROJECT, expected=1, relay=fault, complete=False)
            evidence['fault_wires'] = fault.evidence()
            assert 'error' in value and fault.matches == 1
            assert sum(command.startswith(match) for command in call['commands']) == 1
            assert not any(command.startswith(('DBDELETE', 'DBADD', 'PROJECT CLOSE', 'PROJECT LOAD')) for command in call['commands'])
            losses = [row for row in evidence['fault_wires'] if row.get('lost_backend_terminal_hex')]
            assert len(losses) == 1
            expected_terminal = '200 OK'
            assert re.fullmatch(r'\[[^]]+\] ' + re.escape(expected_terminal) + r'\r\n',
                bytes.fromhex(losses[0]['lost_backend_terminal_hex']).decode())
        with CGateClient(*s.relay.endpoint, timeout=15) as fresh:
            observed = Session(fresh, s.relay, evidence, s.work).xml()
        assert graph(observed) == graph(moved_document(before, 70))
        s.export(MOVED_ROSTER)
        evidence.update(loss_phase=phase, actual_upstream200_dropped=1,
            before_xml=before, observed_after_uncertain_xml=observed,
            caller_receipt_uncertain=True, automatic_replay_or_inverse_cleanup=False)


def test_public_application_safe_cmqttd_restart_preserves_address_and_oid(tmp_path):
    backend = 'cmqttd'
    binary = selected_binary('CBUS_CMQTTD_BIN')
    evidence = new_evidence(backend, binary)
    own_pin = pin(Path(__file__))
    evidence['proposed_test_module'] = own_pin
    state = tmp_path / 'state.json'
    try:
        with no_contact_trap() as trap:
            with session(backend, binary, associated_work(tmp_path, 'before'), evidence, state_path=state) as (s, _):
                before, oid, _, _ = seed_graph(s, trap)
                s.db('set', '!' + oid + '/Address', '70')
                s.project('save', PROJECT)
                observed = s.xml()
            with session(backend, binary, associated_work(tmp_path, 'restart'), evidence, state_path=state) as (s, _):
                after = s.xml()
                assert graph(after) == graph(observed)
                assert app_node(after, 70).findtext('OID') == oid
                s.export(MOVED_ROSTER)
        evidence.update(format='cbus-application-safe-set-owned-v1', before_xml=before,
            after_xml=observed, restart_xml=after, root_oid=oid,
            closed_graph_trap_contacts=0, target_Address_mutation_native_acceptance=False)
    finally:
        evidence['input_pins_after'] = input_pins()
        evidence['proposed_test_module_after'] = pin(Path(__file__))
        associated_evidence(tmp_path / 'application-safe-set-evidence.json', evidence)
        assert evidence['input_pins_after'] == evidence['input_pins']
        assert evidence['proposed_test_module_after'] == own_pin
