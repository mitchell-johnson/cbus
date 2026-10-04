"""Complete synthetic family PP temperature ownership on owned backends.

Expected byte128/129/cap127 values come from retained arithmetic captures.
The profile keeps Celsius15/32/Guard0 and settled time initialization. It does
not establish slider, original window, native device or hardware acceptance.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from test_cgate_barcode_database_interop import FaultGate, graph, selected_binary
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend,
)
import test_thermostat_quick_zone_controls_backends as inherited

BACKENDS = inherited.BACKENDS
PROJECT, UNIT, BACKUP = inherited.PROJECT, inherited.UNIT, inherited.BACKUP
ALIASES = ('PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5')
GUARDS = {'GuardMinimumUpperTemperature': 126, 'GuardLowerTemperature': 127,
          'GuardUpperTemperature': 126, 'GuardMaximumUpperTemperature': 127}
SAVE1 = {'GuardMinimumUpperTemperature': 128, 'GuardLowerTemperature': 128,
         'GuardUpperTemperature': 127, 'GuardMaximumUpperTemperature': 127}
SAVE2 = {'GuardMinimumUpperTemperature': 129, 'GuardLowerTemperature': 129,
         'GuardUpperTemperature': 127, 'GuardMaximumUpperTemperature': 127}
# Basic source tail uses retained user-enabled/sensor-enabled booleans and
# OperationZone1 after master initialization. These are unrelated to the codec.
BASIC_TAIL = {'ZoneTemperatureDisplay': 0, 'UIAllocatedZones': 1, 'InstalledZones': 1,
    'ControlledZones': 1, 'InternalPlantZones': 1, 'HeatingPlantInstalledZones': 1,
    'CoolingPlantInstalledZones': 1, 'VentingPlantInstalledZones': 1}


def case_for(kind, *, guards=True):
    return inherited.make_case('temperature-encode-once-' + kind.lower(), kind,
        seed=(GUARDS if guards else {}) | {'TemperatureUnits': 1},
        history=[{'op': 'quick-zone-view'}], changed=({n: v for n, v in SAVE1.items()
            if v != GUARDS[n]} if guards else {}) |
            (BASIC_TAIL if kind.startswith('PC_TSB') else {}))


def input_pins():
    result = inherited.input_pins()
    for name in ('thermostat_temperature_model',):
        origin = importlib.util.find_spec('cbus_toolkit.' + name).origin
        raw = Path(origin).read_bytes()
        result['cbus_toolkit.' + name] = {'origin': origin, 'sha256': hashlib.sha256(raw).hexdigest(),
                                       'bytes': len(raw)}
    return result


@contextmanager
def journey(backend, variable, tmp_path, case):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'backend')
    specs = tmp_path / 'synthetic-specs'; specs.mkdir()
    inherited.prepare_specs(specs)
    pins = input_pins()
    evidence = {'format': 'cbus-thermostat-temperature-owner-backend-v1', 'backend': backend,
        'case': case['id'], 'input': deepcopy(case['input']),
        'source_derived_expected_changes': deepcopy(case['changed']),
        'original_execution': False, 'physical_acceptance': False,
        'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
        'specification_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in specs.iterdir()},
        'test_module_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'implementation_inputs': pins, 'calls': [], 'wires': [], 'processes': []}
    relay = None
    try:
        with no_contact_trap() as trap, owned_backend(backend, binary, work, extra_args=(
                '--unitspec' if backend == 'cgate-mock' else '--cgate-unitspec', specs)) as (endpoint, process):
            evidence['processes'].append(process)
            with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                fixture, setup = inherited.seed(owner, work, trap, case, evidence)
                current = os.environ['PYTEST_CURRENT_TEST']
                assert current.endswith(' (call)')
                nodeid = current.rsplit(' (', 1)[0]
                assert 'test_thermostat_temperature_owner_backends.py::' in nodeid
                evidence.update(fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                    before_xml=inherited.refs.document(owner), before_parameters=inherited.refs.parameters(owner),
                    fixture_numeric_to_opaque_setup=setup, actual_nodeid=nodeid,
                    pytest_current_test=current, source_pp_scope='complete synthetic family roster',
                    expected_pp_names=sorted(inherited.pp_names(case['input']['unit_type'])))
                assert set(evidence['before_parameters']) == inherited.pp_names(case['input']['unit_type'])
                yield owner, relay, evidence, specs, endpoint
        evidence['closed_graph_trap_contacts'] = 0
    finally:
        if relay is not None:
            evidence['wires'] = relay.evidence()
        evidence['implementation_inputs_after'] = input_pins()
        associated_evidence(tmp_path / 'thermostat-temperature-owner-evidence.json', evidence)
        assert evidence['implementation_inputs_after'] == pins


def invoke(relay, evidence, specs, case, *, backup=BACKUP, **kwargs):
    # The inherited invoker supplies exact call/node identity and recorded
    # tagged command receipts. A distinct backup is required on the second save.
    original = inherited.BACKUP
    try:
        inherited.BACKUP = backup
        return inherited.invoke(relay, evidence, specs, case, **kwargs)
    finally:
        inherited.BACKUP = original


def assert_temperature_projection(plan, raw, final, *, accepted_raw_edit=False):
    model = plan['output_projection']['quick_zone_controls']
    facts = model['temperature_model']
    assert facts['preference'] == 'celsius' and facts['device_units_used_as_preference'] is False
    assert facts['load_conversions_are_not_control_notifications'] is True
    assert {n: facts['raw'][n] for n in GUARDS} == raw
    assert {n: facts['encoded'][n] for n in GUARDS} == final
    assert facts['loaded'] == facts['live']
    if accepted_raw_edit:
        # Independent captured120 -> live50 -> stored120 in Celsius.
        assert facts['raw']['GuardMaximumLowerTemperature'] == 120
        assert facts['loaded']['GuardMaximumLowerTemperature'] == 50
        assert facts['encoded']['GuardMaximumLowerTemperature'] == 120
    assert model['full_toolkit_parity'] is False and model['original_form_executed'] is False
    assert model['native_control_scheduling_reproduced'] is False
    assert plan['graph_operations'] == [] and plan['planned_level_creations'] == []


def assert_preserved(owner, before_xml, before_pp, changed):
    actual, after = inherited.refs.parameters(owner), inherited.refs.document(owner)
    inherited.refs.assert_values(before_pp, actual, changed)
    assert set(actual) == set(before_pp)
    inherited.damper.preserve(before_xml, after, {'changed': changed, 'operations': [],
                                                'final_creations': [], 'graph_ledger': []})
    return actual, after


def copied_project_graph(before, backup):
    """Owned COPY changes only Project Address/TagName to this selected backup."""
    root = inherited.outputs.parse(before)
    project = root.find('Project')
    assert project is not None
    for name in ('Address', 'TagName'):
        field = project.find(name)
        assert field is not None and field.text == PROJECT
        field.text = backup
    return graph(ET.tostring(root, encoding='unicode'))


def successful_save(owner, result, call, before_xml, before_pp, changed, backup):
    assert result['complete'] and result['persistence_verified']
    assert result['pp_save_count'] == result['target_project_save_count'] == 1
    commands = call['commands']
    assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands) == 1
    assert commands.count('PROJECT SAVE ' + PROJECT) == 2
    assert commands.count('PROJECT COPY ' + PROJECT + ' ' + backup) == 1
    assert commands.count('PROJECT CLOSE ' + PROJECT) == commands.count('PROJECT LOAD ' + PROJECT) == 1
    assert not any(c.startswith(('DBADD', 'DBSET', 'DBDELETE')) for c in commands)
    first = next(i for i, c in enumerate(commands) if c.startswith(('PP SET ', 'PP SAVE')))
    assert commands.index('PROJECT SAVE ' + PROJECT) < commands.index(
        'PROJECT COPY ' + PROJECT + ' ' + backup) < first
    copied = inherited.refs.document(owner, '//' + backup)
    assert graph(copied) == copied_project_graph(before_xml, backup)
    actual, after = assert_preserved(owner, before_xml, before_pp, changed)
    for verb in ('CLOSE', 'LOAD', 'USE'):
        assert owner.command('PROJECT ' + verb + ' ' + PROJECT).code == 200
    fresh, reopened = assert_preserved(owner, before_xml, before_pp, changed)
    assert actual == fresh and graph(after) == graph(reopened)
    return {'parameters': fresh, 'xml': reopened, 'backup_xml': copied,
            'full_pp_and_graph_preserved': True, 'independent_reopen': True}


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
@pytest.mark.parametrize('kind', ALIASES, ids=['pc_tsa','pc_tsa5','pc_tsb','pc_tsb5'])
def test_public_temperature_owner_chained_saves(backend, variable, kind, tmp_path):
    case = case_for(kind)
    case['edits'] = {'GuardMaximumLowerTemperature': 120}
    case['changed']['GuardMaximumLowerTemperature'] = 120
    with journey(backend, variable, tmp_path, case) as (owner, relay, evidence, specs, _):
        preview, peek = invoke(relay, evidence, specs, case, action='preview')
        assert {r['name']: r['after'] for r in preview['changed_parameters']} == case['changed']
        assert_temperature_projection(preview, GUARDS, SAVE1, accepted_raw_edit=True)
        inherited.damper.assert_no_mutation(peek)
        assert inherited.refs.parameters(owner) == evidence['before_parameters']
        assert inherited.refs.document(owner) == evidence['before_xml']
        first, call1 = invoke(relay, evidence, specs, case)
        assert_temperature_projection(first['plan'], GUARDS, SAVE1, accepted_raw_edit=True)
        accepted1 = successful_save(owner, first, call1, evidence['before_xml'],
                                   evidence['before_parameters'], case['changed'], BACKUP)
        case2 = deepcopy(case)
        case2.update(id=case['id'] + '-new-raw-load', changed={
            'GuardMinimumUpperTemperature': 129, 'GuardLowerTemperature': 129})
        backup2 = 'THBACK2'
        preview2, peek2 = invoke(relay, evidence, specs, case2, action='preview')
        assert {r['name']: r['after'] for r in preview2['changed_parameters']} == case2['changed']
        assert_temperature_projection(preview2, SAVE1, SAVE2, accepted_raw_edit=True)
        inherited.damper.assert_no_mutation(peek2)
        second, call2 = invoke(relay, evidence, specs, case2, backup=backup2)
        assert_temperature_projection(second['plan'], SAVE1, SAVE2, accepted_raw_edit=True)
        accepted2 = successful_save(owner, second, call2, accepted1['xml'],
                                   accepted1['parameters'], case2['changed'], backup2)
        evidence.update(first_result=first, first_acceptance=accepted1,
            second_result=second, second_acceptance=accepted2, distinct_raw_owner_loads=2,
            target_saves=2, one_pp_save_per_apply=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
@pytest.mark.parametrize('kind', ALIASES, ids=['pc_tsa','pc_tsa5','pc_tsb','pc_tsb5'])
@pytest.mark.parametrize('name,edits,error', [
    ('raw-set-rewritten', {'GuardMinimumUpperTemperature': 126}, 'GuardMinimumUpperTemperature=128'),
    ('unsigned-overflow', {'EvapComfortStartTemp': 254}, 'EvapComfortStartTemp save result cannot be represented by one PP byte: 256'),
], ids=['raw-set-rewritten','unsigned-overflow'])
def test_public_temperature_owner_refuses_before_backup(backend, variable, kind, name, edits, error, tmp_path):
    case = case_for(kind, guards=False)
    case.update(id=name + '-' + kind.lower(), edits=edits)
    with journey(backend, variable, tmp_path, case) as (owner, relay, evidence, specs, _):
        result, call = invoke(relay, evidence, specs, case, expected=1)
        assert error in result['error']
        inherited.damper.assert_no_mutation(call)
        assert inherited.refs.parameters(owner) == evidence['before_parameters']
        assert inherited.refs.document(owner) == evidence['before_xml']
        state = result['thermostat_template_evidence']
        assert not state['outcome_uncertain'] and not state['backup_source_save_attempted']
        assert not state['pp_save_attempted'] and not state['target_save_attempted']
        evidence.update(result=result, refusal_before_backup=True)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
@pytest.mark.parametrize('kind', ALIASES, ids=['pc_tsa','pc_tsa5','pc_tsb','pc_tsb5'])
@pytest.mark.parametrize('phase', ['PP SAVE_TO_SOURCE','PROJECT SAVE'], ids=['lost-pp-save','lost-project-save'])
def test_public_temperature_owner_lost_successful_save(backend, variable, kind, phase, tmp_path):
    case = case_for(kind)
    case['id'] = phase.lower().replace(' ', '-') + '-' + kind.lower()
    with journey(backend, variable, tmp_path, case) as (owner, _, evidence, specs, endpoint):
        occurrence = 2 if phase == 'PROJECT SAVE' else 1
        with FaultGate(endpoint, phase, 'drop', occurrence=occurrence) as fault:
            result, call = invoke(fault, evidence, specs, case, expected=1, complete=False)
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
        lost = [r for r in evidence['fault_wires'] if 'lost_backend_terminal_hex' in r]
        assert len(lost) == 1
        terminal = bytes.fromhex(lost[0]['lost_backend_terminal_hex'])
        assert re.fullmatch(rb'\[[^]]+\] 200 OK\r\n', terminal)
        assert terminal in bytes.fromhex(lost[0]['backend_response_hex'])
        assert terminal not in bytes.fromhex(lost[0]['response_hex'])
        actual, after = assert_preserved(owner, evidence['before_xml'], evidence['before_parameters'], case['changed'])
        evidence.update(result=result, after_parameters=actual, after_xml=after,
            replay_count=0, successful_backend_response_lost=True,
            full_pp_and_graph_preserved=True, independent_reopen=False)
