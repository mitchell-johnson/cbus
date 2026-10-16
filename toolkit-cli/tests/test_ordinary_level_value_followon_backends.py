"""Ordinary owned Level byte loss, NetVar-child and daemon restart regressions.

These are authored public-CLI checks of the admitted owned byte policy. They
do not establish native mutation grammar, physical I/O or broad parity. The
historical twelve-body ordinary-Level module is imported without modification.
"""
from contextlib import contextmanager
from pathlib import Path
import re

import pytest

import test_cgl_application_order_backends as inherited
import test_ordinary_level_value_backends as ordinary
from test_cgate_barcode_database_interop import FaultGate, selected_binary
from test_cgate_named_database_interop import (
    STARTUP, associated_evidence, associated_work, no_contact_trap,
)

BACKENDS = ordinary.BACKENDS
PROJECT = ordinary.PROJECT
GROUP_PATH = ordinary.LEVEL_PATH
GROUP_OID = ordinary.LEVEL_OID
NETVAR_CHILD_PATH = ordinary.APP_PATH + '/9/6'
NETVAR_CHILD_OID = 'aaaaaaaa-aaaa-4aaa-8aaa-000000000006'
EVIDENCE_NAME = 'ordinary-level-value-followon-evidence.json'


def assert_closed_processes(evidence):
    rows = evidence['processes']
    assert rows, 'No owned backend process was recorded'
    for row in rows:
        assert row['backend'] == evidence['backend']
        assert all(row[key] for key in ('listener_owned', 'process_cleanup',
            'listener_closed', 'pci_closed', 'broker_closed'))
        expected = [('rx', frame) for frame in STARTUP] if row['backend'] == 'cmqttd' else []
        assert [(r['direction'], bytes.fromhex(r['hex'])) for r in row['pci_wire']] == expected


@contextmanager
def evidence_owner(backend, variable, tmp_path):
    binary = selected_binary(variable)
    module_pin = inherited.pin(Path(__file__))
    ordinary_pin = inherited.pin(Path(ordinary.__file__))
    evidence = inherited.new_evidence(backend, binary)
    # The shared harness journals transport; this feature has no CGL/native
    # chronology oracle and must not adopt its unrelated fixture declaration.
    evidence.pop('fixture')
    evidence.pop('literal_expected_application_order')
    evidence.update(format='cbus-ordinary-level-value-followon-owned-v1',
        proposed_test_module=module_pin, historical_ordinary_test_module=ordinary_pin,
        source_basis='Admitted project-scoped ordinary byte owner; owned relay and JSON repository',
        native_mutation_execution=False, physical_acceptance=False,
        limits=['Authored owned-model byte regressions, not original server mutation acceptance.',
                'NetVar child Levels are byte owners; the NetVar root is not a byte owner.',
                'Lost receipts use one actual forwarded request and upstream terminal; no fault is synthesized.',
                'Restart proves the owned daemon JSON repository, not mock or native disk persistence.'])
    try:
        with no_contact_trap() as trap:
            yield binary, trap, evidence
        evidence['closed_graph_trap_contacts'] = 0
        assert_closed_processes(evidence)
        evidence.update(no_later_pci=True, explicit_closed_graph_trap_zero=True,
                        every_owned_process_reaped_and_listeners_closed=True)
    finally:
        evidence['input_pins_after'] = inherited.input_pins()
        evidence['binary_after'] = inherited.pin(binary)
        evidence['proposed_test_module_after'] = inherited.pin(Path(__file__))
        evidence['historical_ordinary_test_module_after'] = inherited.pin(Path(ordinary.__file__))
        associated_evidence(tmp_path / EVIDENCE_NAME, evidence)
        assert evidence['input_pins_after'] == evidence['input_pins']
        assert evidence['binary_after'] == evidence['binary']
        assert evidence['proposed_test_module_after'] == module_pin
        assert evidence['historical_ordinary_test_module_after'] == ordinary_pin


def assert_roles(s, expected, *, group_value):
    """Both public identities and the complete independent Unit/PP are retained."""
    ordinary.assert_graph(s, expected)
    for path in (GROUP_PATH, '254/80/8/4', '!' + GROUP_OID):
        ordinary.read_value(s, path, str(group_value))
    for path in (NETVAR_CHILD_PATH, '254/80/9/6', '!' + NETVAR_CHILD_OID):
        ordinary.read_value(s, path, '42')
    ordinary.read_value(s, ordinary.APP_PATH + '/8/5', '88')
    ordinary.assert_unrelated_pp(s, expected)
    root = ordinary.parse(expected)
    variable = ordinary.application(root, 80).find("NetVar[Address='9']")
    assert variable is not None and 'Value' not in variable.attrib
    assert variable.findtext('OID') == 'aaaaaaaa-aaaa-4aaa-8aaa-000000000009'
    assert ordinary.level(root, group=9, address=6).findtext('OID') == NETVAR_CHILD_OID
    s.evidence.setdefault('public_role_checkpoints', []).append({
        'group_numeric_and_issued_oid': str(group_value),
        'netvar_child_numeric_and_issued_oid': '42',
        'netvar_root_is_not_byte_owner': True,
        'unrelated_group_level': '88', 'unrelated_unit_three_PP_retained': True,
    })


def initialize_netvar_child(s, before):
    # Construct both complete graphs before sending the first setter. Dynamic
    # project/Unit identities came only from the validated original seed.
    nested = ordinary.expected_byte(before, 42, group=9, address=6)
    final = ordinary.expected_byte(nested, 99)
    assert ordinary.identities(before) == ordinary.identities(nested) == ordinary.identities(final)
    ordinary.write_value(s, NETVAR_CHILD_PATH, 42)
    assert_roles(s, nested, group_value=77)
    s.evidence.update(before_xml=before, expected_after_netvar_xml=nested,
                      expected_after_group_xml=final,
                      public_netvar_child_66_to_42_verified=True)
    return nested, final


def tagged_commands(rows, key='request_hex'):
    commands = []
    for row in rows:
        for line in bytes.fromhex(row[key]).decode().splitlines():
            match = re.fullmatch(r'\[([^]]+)\] (.+)', line)
            if match:
                commands.append(match[2])
    return commands


def assert_dropped_success(fault, evidence, call, exact_commands):
    # Called only after FaultGate has closed/reaped its relay workers.
    rows = evidence['fault_wires']
    assert len(rows) == 1 and rows[0]['closed'] is True
    row = rows[0]
    assert fault.matches == 1
    assert row['fault']['command'] == exact_commands[-1]
    assert row['fault']['mode'] == 'drop' and row['fault']['occurrence'] == 1
    assert tagged_commands(rows) == exact_commands
    assert tagged_commands(rows, 'forwarded_request_hex') == exact_commands
    assert row['request_hex'] == row['forwarded_request_hex']
    assert call['commands'] == exact_commands and call['documents'] == []
    assert call['statuses'] == ([200, None] if len(exact_commands) == 2 else [None])
    terminal = f"[{row['fault']['tag']}] 200 OK\r\n".encode()
    assert bytes.fromhex(row['lost_backend_terminal_hex']) == terminal
    backend_bytes = bytes.fromhex(row['backend_response_hex'])
    caller_bytes = bytes.fromhex(row['response_hex'])
    assert backend_bytes.count(terminal) == 1 and terminal not in caller_bytes
    assert backend_bytes == caller_bytes + terminal
    assert call['reply_lines'][-1] == []
    evidence.update(actual_upstream200_dropped=1, caller_receipt_uncertain=True,
                    exact_target_forwarded_once=True)


@pytest.mark.parametrize('phase', ['value', 'save'])
@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_numeric_level_lost_success_is_not_replayed(phase, backend, variable, tmp_path):
    with evidence_owner(backend, variable, tmp_path) as (binary, trap, evidence):
        with inherited.session(backend, binary, associated_work(tmp_path, 'backend'), evidence) as (s, endpoint):
            before = ordinary.seed(s, trap)
            _, final = initialize_netvar_child(s, before)
            group_command = f'DBSETSAFE {GROUP_PATH}/Value 99'
            if phase == 'save':
                ordinary.write_value(s, GROUP_PATH, 99)
                assert_roles(s, final, group_value=99)
            verb = f'DBSETSAFE {GROUP_PATH}/Value' if phase == 'value' else 'PROJECT SAVE'
            exact = ['PROJECT USE ' + PROJECT, group_command] if phase == 'value' else ['PROJECT SAVE ' + PROJECT]
            first_call = len(evidence['calls'])
            fault = FaultGate(endpoint, verb, 'drop')
            try:
                with fault:
                    if phase == 'value':
                        result, call = s.db('set', GROUP_PATH + '/Value', '99', expected=1,
                                            relay=fault, complete=False)
                    else:
                        result, call = s.cli('project', 'save', PROJECT, expected=1,
                                             relay=fault, complete=False)
            finally:
                # Even a failed caller assertion retains the literal fault row.
                evidence['fault_wires'] = fault.evidence()
            assert 'error' in result and call['exit'] == 1
            assert_dropped_success(fault, evidence, call, exact)
            # Every public read creates a fresh CLI connection to the ordinary
            # relay. No uncertain request is retried or replaced by an inverse.
            assert_roles(s, final, group_value=99)
            if phase == 'save':
                s.project('close', PROJECT)
                s.project('load', PROJECT)
                assert_roles(s, final, group_value=99)
            all_requests = tagged_commands(s.relay.evidence()) + tagged_commands(evidence['fault_wires'])
            assert all_requests.count(group_command) == 1
            assert all_requests.count(f'DBSETSAFE {NETVAR_CHILD_PATH}/Value 42') == 1
            assert all_requests.count('PROJECT SAVE ' + PROJECT) == (phase == 'save')
            later = [command for row in evidence['calls'][first_call + 1:] for command in row['commands']]
            assert not any(command.startswith(('DBSET', 'DBADD', 'DBDELETE', 'PP SAVE', 'PROJECT SAVE'))
                           for command in later)
            evidence.update(loss_phase=phase, observed_after_uncertain_xml=ordinary.xml(s),
                automatic_replay_or_inverse_cleanup=False,
                explicit_saved_image_close_load_verified=(phase == 'save'),
                after_loss_database_write_or_save_count=0)


def test_public_numeric_group_and_netvar_levels_survive_cmqttd_restart(tmp_path):
    with evidence_owner('cmqttd', 'CBUS_CMQTTD_BIN', tmp_path) as (binary, trap, evidence):
        state = tmp_path / 'ordinary-level-state.json'
        initial = associated_work(tmp_path, 'before')
        restart = associated_work(tmp_path, 'restart')
        assert initial != restart and not state.exists()
        with inherited.session('cmqttd', binary, initial, evidence, state_path=state) as (s, _):
            before = ordinary.seed(s, trap)
            _, final = initialize_netvar_child(s, before)
            ordinary.write_value(s, GROUP_PATH, 99)
            assert_roles(s, final, group_value=99)
            _, saved = s.project('save', PROJECT)
            assert saved['reply_lines'] == [['200 OK']]
            assert_roles(s, final, group_value=99)
        assert len(evidence['processes']) == 1
        assert_closed_processes(evidence)
        assert state.is_file() and not state.is_symlink()
        state_pin = inherited.pin(state)
        assert state_pin['bytes'] > 0
        evidence['disk_state_after_first_reap'] = state_pin
        restart_call_start = len(evidence['calls'])
        with inherited.session('cmqttd', binary, restart, evidence, state_path=state) as (s, _):
            # No reseed, write or SAVE can hide a failed repository restore.
            assert len(evidence['processes']) == 2
            first, second = evidence['processes']
            assert first['pid'] != second['pid'] and first['process_cleanup'] is True
            for process in (first, second):
                assert process['argv'][process['argv'].index('--cgate-state') + 1] == str(state)
            assert_roles(s, final, group_value=99)
            # The separately retained saved image must also preserve both
            # changes, with no setter or second SAVE in the restarted process.
            s.project('close', PROJECT)
            s.project('load', PROJECT)
            assert_roles(s, final, group_value=99)
            # Bind the second context's complete relay request stream directly,
            # rather than inferring process ownership from a CLI workdir.
            requests = tagged_commands(s.relay.evidence())
            assert not any(command.startswith(('DBSET', 'DBADD', 'DBDELETE', 'PROJECT NEW', 'PROJECT SAVE'))
                           for command in requests)
        assert len(evidence['processes']) == 2
        evidence.update(disk_state_after_second_reap=inherited.pin(state),
            restart_cli_call_range=[restart_call_start, len(evidence['calls'])],
            disk_backed_restart_verified=True, first_process_reaped_before_restart=True,
            same_explicit_state_file=True, distinct_processes_and_workdirs=True,
            restart_reseed_or_mutation_count=0,
            group_99_and_netvar_child_42_saved_image_restored=True)
