"""Prepared zone properties through one settings transaction on owned servers.

Independent literal mask/PP expectations are source transcriptions. The tests
do not assert native enabled/visible/focus/mouse admission or GUI execution.
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

import pytest

from cbus_toolkit.cgate import CGateClient
from test_cgate_barcode_database_interop import FaultGate, graph, selected_binary
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend)
import test_thermostat_quick_zone_controls_backends as full


BACKENDS = full.BACKENDS
PROJECT, UNIT, BACKUP = full.PROJECT, full.UNIT, full.BACKUP
FULL_MASKS = {name: 31 for name in ('UIAllocatedZones', 'InternalPlantZones', 'MeasuredZones',
    'HeatingPlantInstalledZones', 'CoolingPlantInstalledZones', 'VentingPlantInstalledZones',
    'ScheduleControlledZones', 'InstalledZones', 'ControlledZones', 'InternalPlantModes')}
PROPERTIES = (
    ('UIAllocatedZones', 'ui', ('UnswitchedZone', 'Zone1', 'Zone2', 'Zone3', 'Zone4'), 'Zone2', 27),
    ('InternalPlantZones', 'internal', ('UnswitchedZone', 'Zone1', 'Zone2', 'Zone3', 'Zone4'), 'Zone2', 27),
    ('InternalPlantModes', 'modes', ('Heat', 'Cool', 'HeatCool', 'Vent'), 'HeatCool', 23),
    ('MeasuredZones', 'measured', ('UnswitchedZone', 'Zone1', 'Zone2', 'Zone3', 'Zone4'), 'Zone2', 27),
    ('CoolingPlantInstalledZones', 'cooling', ('UnswitchedZone', 'Zone1', 'Zone2', 'Zone3', 'Zone4'), 'Zone2', 27),
    ('VentingPlantInstalledZones', 'venting', ('UnswitchedZone', 'Zone1', 'Zone2', 'Zone3', 'Zone4'), 'Zone2', 27),
    ('HeatingPlantInstalledZones', 'heating', ('UnswitchedZone', 'Zone1', 'Zone2', 'Zone3', 'Zone4'), 'Zone2', 27),
)


def binding(field, suffix, checked):
    return {'op': 'zone-checkbox-binding', 'binding': field + '.' + suffix, 'checked': checked}


def case(name, kind='PC_TSA5', *, history, changed, final_state=None, seed=None, creates=(), ledger=()):
    return full.make_case(name, kind, seed=FULL_MASKS | {
        'DamperZone1Output': 40, 'DamperZone2Output': 41,
        'DamperZone3Output': 42, 'DamperZone4Output': 43} | (seed or {}),
        history=history, changed=changed, creates=creates, ledger=ledger,
        final_state=final_state or {'loaded_master': True})


POSITIVES = []
for field, role, suffixes, final_suffix, final_mask in PROPERTIES:
    # Every retained prepared binding changes false, true, then same true.
    # Other populated role masks retain every quick zone throughout, so the
    # callback's actual Installed reset/reinclude has literal final31.
    history = [binding(field, suffix, checked)
               for suffix in suffixes for checked in (False, True, True)]
    history += [binding(field, final_suffix, False)]
    POSITIVES.append(case('all-prepared-' + field, history=history, changed={field: final_mask},
        final_state={'loaded_master': True, 'used_zones': 0 if role == 'ui' else 31,
                     'masks': {role: final_mask, 'cbus': 31, 'controlled': 31}}))
POSITIVES.append(case('empty-heating-callback-chain',
    history=[binding('HeatingPlantInstalledZones', 'Zone2', False)],
    seed={'HeatingPlantInstalledZones': 4},
    changed={'HeatingPlantInstalledZones': 0, 'HeatingPlantType': 0,
             'InternalPlantModes': 29, 'EvapProgramEnabled': 0},
    final_state={'loaded_master': True, 'used_zones': 31, 'modes': 29,
                 'masks': {'heating': 0, 'cbus': 31, 'controlled': 31}}))
POSITIVES.append(case('vent-mode-family-fan-save-tail',
    history=[binding('InternalPlantModes', 'Vent', False)],
    changed={'InternalPlantModes': 15, 'HeatingPlantFanSpeeds': 0, 'CoolingPlantFanSpeeds': 0},
    final_state={'loaded_master': True, 'used_zones': 31, 'modes': 15,
                 'masks': {'modes': 15, 'cbus': 31, 'controlled': 31}}))
for kind in ('PC_TSB', 'PC_TSB5'):
    history = [binding(field, suffix, checked) for field, _, suffixes, _, _ in PROPERTIES
               for suffix in suffixes for checked in (False, True)]
    history += [binding('MeasuredZones', 'Zone2', False)]
    POSITIVES.append(case('basic-operation-zone-tail-' + kind.lower(), kind,
        history=history, changed={'ZoneTemperatureDisplay': 0, 'UIAllocatedZones': 1,
            'MeasuredZones': 1, 'InternalPlantZones': 1, 'InstalledZones': 1,
            'ControlledZones': 1, 'HeatingPlantInstalledZones': 1,
            'CoolingPlantInstalledZones': 1, 'VentingPlantInstalledZones': 1,
            # Basic AfterLoad binds unused255 instead of raw damper 40..43.
            # The explicit installed-zone callbacks allocate absent generated
            # groups at the source manager's first free addresses 0..3.
            'DamperZone1Output': 0, 'DamperZone2Output': 1,
            'DamperZone3Output': 2, 'DamperZone4Output': 3},
        creates=((0, '[CG01] Damper Zone 1'), (1, '[CG01] Damper Zone 2'),
                 (2, '[CG01] Damper Zone 3'), (3, '[CG01] Damper Zone 4')),
        ledger=(
            {'action': 'create', 'address': 0, 'name': 'Group 0'},
            {'action': 'rename', 'address': 0, 'previous_name': 'Group 0', 'name': '[CG01] Damper Zone 1'},
            {'action': 'create', 'address': 1, 'name': 'Group 1'},
            {'action': 'rename', 'address': 1, 'previous_name': 'Group 1', 'name': '[CG01] Damper Zone 2'},
            {'action': 'create', 'address': 2, 'name': 'Group 2'},
            {'action': 'rename', 'address': 2, 'previous_name': 'Group 2', 'name': '[CG01] Damper Zone 3'},
            {'action': 'create', 'address': 3, 'name': 'Group 3'},
            {'action': 'rename', 'address': 3, 'previous_name': 'Group 3', 'name': '[CG01] Damper Zone 4'}),
        final_state={'loaded_master': True, 'used_zones': 31,
                     'masks': {'ui': 31, 'measured': 27, 'cbus': 31, 'controlled': 31}}))
assert len(POSITIVES) == 11
assert {row['binding'] for sample in POSITIVES[:7] for row in sample['history']} == {
    field + '.' + suffix for field, _, suffixes, _, _ in PROPERTIES for suffix in suffixes}
assert len({row['binding'] for sample in POSITIVES[:7] for row in sample['history']}) == 34


def input_pins():
    pins = full.input_pins()
    spec = importlib.util.find_spec('cbus_toolkit.thermostat_zone_controls')
    assert spec and spec.origin
    path = Path(spec.origin)
    assert path.name == 'thermostat_zone_controls.py' and path.parent.name == 'cbus_toolkit'
    raw = path.read_bytes()
    pins['cbus_toolkit.thermostat_zone_controls'] = {
        'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'origin': str(path)}
    return pins


@contextmanager
def journey(backend, variable, tmp_path, sample):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'backend')
    specs = tmp_path / 'synthetic-specs'; specs.mkdir()
    full.prepare_specs(specs)
    evidence = {'format': 'cbus-thermostat-prepared-zone-bindings-backend-v1',
        'backend': backend, 'case': sample['id'], 'input': deepcopy(sample['input']),
        'history': deepcopy(sample['history']), 'literal_expected_changes': sample['changed'],
        'original_execution': False, 'physical_acceptance': False,
        'native_enabled_visible_focus_mouse_admission': False,
        'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
        'test_module_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'calls': [], 'wires': [], 'processes': []}
    pins = input_pins()
    relay = None
    try:
        with no_contact_trap() as trap, owned_backend(backend, binary, work, extra_args=(
                '--unitspec' if backend == 'cgate-mock' else '--cgate-unitspec', specs)) as (endpoint, process):
            evidence['processes'].append(process)
            with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                fixture, setup = full.seed(owner, work, trap, sample, evidence)
                current = os.environ.get('PYTEST_CURRENT_TEST')
                assert current and current.endswith(' (call)')
                nodeid = current.rsplit(' (', 1)[0]
                assert 'test_thermostat_zone_controls_backends.py::' in nodeid
                evidence.update(fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                    before_xml=full.refs.document(owner), before_parameters=full.refs.parameters(owner),
                    fixture_numeric_to_opaque_setup=setup, actual_nodeid=nodeid,
                    pytest_current_test=current, implementation_inputs=pins,
                    expected_pp_names=sorted(full.pp_names(sample['input']['unit_type'])))
                assert set(evidence['before_parameters']) == full.pp_names(sample['input']['unit_type'])
                yield owner, relay, evidence, specs, endpoint
        evidence['closed_graph_trap_contacts'] = 0
    finally:
        if relay is not None:
            evidence['wires'] = relay.evidence()
        evidence['implementation_inputs_after'] = input_pins()
        associated_evidence(tmp_path / 'thermostat-zone-bindings-evidence.json', evidence)
        assert evidence['implementation_inputs_after'] == pins


def assert_projection(plan, sample, before):
    model = full.assert_projection(plan, sample, before)
    bindings = model['prepared_zone_bindings']
    assert bindings['binding_count'] == 34
    assert bindings['same_synchronous_settings_owner'] is True
    assert bindings['native_enabled_visible_focus_admission_verified'] is False
    assert bindings['native_mouse_or_click_dispatched'] is False
    assert bindings['caller_subscriber_registry_admitted'] is False
    assert [row['position'] for row in bindings['operations']] == list(range(1, len(sample['history']) + 1))
    assert [{key: row[key] for key in ('op', 'binding', 'checked')}
            for row in bindings['operations']] == sample['history']
    assert all(row['exact_owned_prepared_binding'] and row['native_click_dispatched'] is False
               for row in bindings['operations'])
    return model


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('sample', POSITIVES, ids=lambda row: row['id'])
def test_public_prepared_binding_history(backend, variable, sample, tmp_path):
    with journey(backend, variable, tmp_path, sample) as (owner, relay, evidence, specs, _):
        preview, peek = full.invoke(relay, evidence, specs, sample, action='preview')
        assert_projection(preview, sample, evidence['before_xml'])
        full.damper.assert_no_mutation(peek)
        assert full.refs.document(owner) == evidence['before_xml']
        assert full.refs.parameters(owner) == evidence['before_parameters']
        result, call = full.invoke(relay, evidence, specs, sample)
        assert result['complete'] and result['persistence_verified']
        assert result['plan'] == {key: value for key, value in preview.items() if key != 'scope'}
        full.assert_graph_wire(call, evidence['before_xml'], sample)
        commands = call['commands']
        assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands) == 1
        assert commands.count('PROJECT SAVE ' + PROJECT) == 2
        assert commands.count('PROJECT COPY ' + PROJECT + ' ' + BACKUP) == 1
        assert commands.count('PROJECT CLOSE ' + PROJECT) == commands.count('PROJECT LOAD ' + PROJECT) == 1
        assert result['pp_save_count'] == result['target_project_save_count'] == 1
        first = next(i for i, command in enumerate(commands) if command.startswith(('PP SET ', 'PP SAVE')))
        assert commands.index('PROJECT SAVE ' + PROJECT) < commands.index(
            'PROJECT COPY ' + PROJECT + ' ' + BACKUP) < first
        backup = full.refs.document(owner, '//' + BACKUP)
        assert graph(backup) == full.damper.copied_project_graph(evidence['before_xml'])
        actual, after = full.assert_after(owner, evidence, sample)
        for verb in ('CLOSE', 'LOAD', 'USE'):
            assert owner.command('PROJECT ' + verb + ' ' + PROJECT).code == 200
        fresh, reopened = full.assert_after(owner, evidence, sample)
        assert fresh == actual and graph(reopened) == graph(after)
        evidence.update(preview=preview, result=result, after_xml=after, after_parameters=actual,
            reopened_xml=reopened, reopened_parameters=fresh, backup_xml=backup,
            full_pp_and_graph_preserved=True, backup_preapply_graph_verified=True,
            independent_reopen=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('reason', ['unsettled-profile', 'pending-queue'])
def test_public_prepared_binding_refuses_before_backup(backend, variable, reason, tmp_path):
    sample = deepcopy(POSITIVES[0]); sample['id'] = reason
    if reason == 'unsettled-profile':
        sample['input']['seed']['MinimumSetTemperature'] = 20
        error = 'Settled'
    else:
        sample['history'] += [{'op': 'select-plant-type', 'value': 3}]
        error = 'pending'
    with journey(backend, variable, tmp_path, sample) as (owner, relay, evidence, specs, _):
        result, call = full.invoke(relay, evidence, specs, sample, expected=1)
        assert error in result['error']
        full.damper.assert_no_mutation(call)
        assert full.refs.document(owner) == evidence['before_xml']
        assert full.refs.parameters(owner) == evidence['before_parameters']
        assert not result['thermostat_template_evidence']['outcome_uncertain']
        evidence.update(result=result, refusal_before_backup=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_prepared_binding_failed_stage_never_saves_or_inverts(backend, variable, tmp_path):
    sample = deepcopy(POSITIVES[0]); sample['id'] = 'failed-pp-set-stage'
    with journey(backend, variable, tmp_path, sample) as (owner, _, evidence, specs, endpoint):
        with FaultGate(endpoint, 'PP SET', 'refuse') as fault:
            result, call = full.invoke(fault, evidence, specs, sample, expected=1)
        evidence['fault_wires'] = fault.evidence()
        assert fault.matches == 1
        state = result['thermostat_template_evidence']
        assert not state['complete'] and not state['outcome_uncertain']
        assert state['automatic_retries'] == 0 and state['rollback_performed'] is False
        assert not state['pp_save_attempted'] and not state['target_save_attempted']
        commands = call['commands']
        assert sum(c.startswith('PP SET ') for c in commands) == 1
        assert not any(c.startswith(('PP SAVE', 'DBADD', 'DBSET', 'DBDELETE')) for c in commands)
        assert commands.count('PROJECT SAVE ' + PROJECT) == 1
        assert commands.count('PROJECT COPY ' + PROJECT + ' ' + BACKUP) == 1
        assert not any(c.startswith(('PROJECT CLOSE ', 'PROJECT LOAD ')) for c in commands)
        assert full.refs.parameters(owner) == evidence['before_parameters']
        assert full.refs.document(owner) == evidence['before_xml']
        backup = full.refs.document(owner, '//' + BACKUP)
        assert graph(backup) == full.damper.copied_project_graph(evidence['before_xml'])
        evidence.update(result=result, after_xml=full.refs.document(owner),
                        after_parameters=full.refs.parameters(owner), backup_xml=backup,
                        failed_staging_saved_nothing=True, inverse_cleanup_count=0)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('phase', ['PP SAVE_TO_SOURCE', 'PROJECT SAVE'])
def test_public_prepared_binding_lost_successful_save_never_replays(backend, variable, phase, tmp_path):
    sample = deepcopy(POSITIVES[0]); sample['id'] = 'lost-' + phase.lower().replace(' ', '-')
    with journey(backend, variable, tmp_path, sample) as (owner, _, evidence, specs, endpoint):
        occurrence = 2 if phase == 'PROJECT SAVE' else 1
        with FaultGate(endpoint, phase, 'drop', occurrence=occurrence) as fault:
            result, call = full.invoke(fault, evidence, specs, sample, expected=1, complete=False)
        evidence['fault_wires'] = fault.evidence()
        assert fault.matches == occurrence
        state = result['thermostat_template_evidence']
        assert not state['complete'] and state['outcome_uncertain']
        assert state['automatic_retries'] == 0 and state['rollback_performed'] is False
        assert state['pp_save_attempted'] and not state['target_save_confirmed']
        assert state['pp_save_confirmed'] is (phase == 'PROJECT SAVE')
        assert state['target_save_attempted'] is (phase == 'PROJECT SAVE')
        commands = call['commands']
        assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands) == 1
        assert commands.count('PROJECT SAVE ' + PROJECT) == occurrence
        assert commands.count('PROJECT COPY ' + PROJECT + ' ' + BACKUP) == 1
        assert not any(c.startswith(('DBDELETE', 'PROJECT CLOSE ', 'PROJECT LOAD ')) for c in commands)
        assert commands[-1].startswith(phase) and call['statuses'][-1] is None
        lost = [row for row in evidence['fault_wires'] if 'lost_backend_terminal_hex' in row]
        assert len(lost) == 1
        terminal = bytes.fromhex(lost[0]['lost_backend_terminal_hex'])
        assert re.fullmatch(rb'\[[^]]+\] 200 OK\r\n', terminal)
        assert terminal in bytes.fromhex(lost[0]['backend_response_hex'])
        assert terminal not in bytes.fromhex(lost[0]['response_hex'])
        full.assert_graph_wire(call, evidence['before_xml'], sample)
        actual, after = full.assert_after(owner, evidence, sample)
        evidence.update(result=result, after_xml=after, after_parameters=actual,
            replay_count=0, saved_response_lost=True, full_pp_and_graph_preserved=True,
            independent_reopen=False)


@pytest.mark.parametrize('name,row,preference,error', [
    ('unprepared-schedule', binding('ScheduleControlledZones', 'Zone1', True), 'celsius', '34 prepared'),
    ('unprepared-standby', binding('InternalPlantModes', 'Standby', True), 'celsius', '34 prepared'),
    ('nonboolean', binding('UIAllocatedZones', 'Zone1', 1), 'celsius', 'Boolean'),
    ('missing-celsius', binding('MeasuredZones', 'Zone1', True), None, 'celsius'),
], ids=['unprepared-schedule', 'unprepared-standby', 'nonboolean', 'missing-celsius'])
def test_public_prepared_binding_schema_refuses_before_connection(name, row, preference, error, tmp_path):
    specs = tmp_path / 'synthetic-specs'; specs.mkdir(); full.prepare_specs(specs)
    with no_contact_trap() as endpoint:
        host, port = endpoint.rsplit(':', 1)
        argv = [sys.executable, '-m', 'cbus_toolkit', 'thermostat', 'settings', 'apply', UNIT,
            '--host', host, '--port', port, '--exclusive-project', '--spec-dir', str(specs),
            '--backup-project', BACKUP, '--output-operation', json.dumps(row)]
        if preference is not None:
            argv += ['--temperature-preference', preference]
        process = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        result = json.loads(process.stdout or process.stderr)
        assert process.returncode == 1 and error in result['error'], result
    (tmp_path / 'thermostat-zone-bindings-schema-evidence.json').write_text(json.dumps({
        'case': name, 'argv': argv, 'exit': process.returncode, 'result': result,
        'zero_tcp_contacts': True, 'original_execution': False, 'physical_acceptance': False},
        sort_keys=True), encoding='utf-8')
