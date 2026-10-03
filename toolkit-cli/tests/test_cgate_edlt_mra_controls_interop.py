"""Private ordinary-parent MRA callbacks on both owned services.

Literal expectations are independently transcribed source effects. Explicit
Index bindings establish no modal image picker, rendering or physical result.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from xml.etree import ElementTree as ET

import pytest

from test_cgate_barcode_database_interop import FaultGate, graph, parse_wire
from test_cgate_edlt_global_images_interop import assert_lost_successful_save
import test_cgate_edlt_parent_add_dialog_interop as parent
from test_cgate_edlt_scene_add_dialog_interop import snapshot

VECTOR = Path(__file__).with_name('mra-public-literals.json')
LITERALS = json.loads(VECTOR.read_text())
POSITIVE = LITERALS['positive_profiles']
REFUSALS = LITERALS['refusal_profiles']
PROCESS_BUDGET = 90
CRC_FIELDS = {'OverallCRC', 'GlobalParameterCRC', 'WidgetsCRC', 'StaticTextCRC', 'ScenesCheckSum'}
MUTATIONS = ('PP SET ', 'PP SAVE', 'DBADD', 'DBSET', 'DBDELETE',
             'PROJECT COPY ', 'PROJECT SAVE ', 'PROJECT DELETE ', 'PROJECT NEW ')


def field(slot, offset=0):
    return f'Widget{slot}WidgetType' if offset == 0 else f'Widget{slot}WidgetByteValue{offset}'


def tree(text):
    return ET.fromstring(text, parser=ET.XMLParser(
        target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))


def seed(owner, case, evidence):
    """Fixture-only input setup; never produce the public expected outputs."""
    root = tree(snapshot(owner))
    unit = root.find("Project/Network/Unit[Address='20']")
    changes = {'NavWidgetType': [1], 'UseBigIcon': [1]}
    for slot, record in case['source_records'].items():
        changes.update({field(slot, offset): [value] for offset, value in enumerate(record)})
        changes[f'Widget{slot}RestoreLevel'] = [213]
    # Keep the source model's last functional slot distinct from its terminator.
    changes[field(max(map(int, case['source_records'])) + 1)] = [255]
    for index, literal in case['source_rows_hex'].items():
        changes['StaticTextString' + index] = list(bytes.fromhex(literal))
    rows = {row.get('Name'): row for row in unit.findall('PP')}
    assert set(changes) <= set(rows)
    for name, values in changes.items():
        rows[name].set('Value', ' '.join(map(str, values)))
    document = ET.tostring(unit, encoding='unicode')
    response = owner.command_document('DBSETXML //TEST/254/p/20', document)
    assert response.code == 301, response
    assert owner.command('PROJECT SAVE TEST').code == 200
    for command in ('PROJECT CLOSE TEST', 'PROJECT LOAD TEST'):
        assert owner.command(command).code == 200
    source = parent.values(tree(snapshot(owner)))
    assert len(source) == 844
    for name, values in changes.items():
        assert source[name] == values, (name, source[name], values)
    evidence['fixture_input'] = {
        'vector_sha256': hashlib.sha256(VECTOR.read_bytes()).hexdigest(),
        'unit_document_sha256': hashlib.sha256(document.encode()).hexdigest(),
        'source_parameters': 844, 'static_rows': 64,
        'source_records': case['source_records'], 'seed_commands_separate_from_cli': True}


def arguments(specs, tmp_path, case):
    ops = tmp_path / 'mra-operations.json'
    ops.write_text(json.dumps(case['operations']))
    preferences = tmp_path / 'mra-preferences.json'
    preferences.write_text(json.dumps({'format': 'cbus-edlt-display-preferences-v1',
        'registry_key_present': True, 'values': {}}))
    return ['unit', '--lock-address', '//TEST/254', '--source', '/db//TEST/254/p/20',
            'edlt-parent-transaction', '--spec-dir', specs, '--auto-metadata',
            '--exclusive-project', '--operations', ops, '--display-preferences', preferences]


def invoke(relay, evidence, args, *, expected=0, complete=True, connections=1):
    start = len(relay.rows)
    argv = [sys.executable, '-m', 'cbus_toolkit', 'cgate', '--host', relay.endpoint[0],
            '--port', str(relay.endpoint[1]), '--timeout', '3', *map(str, args)]
    call = {'argv': argv, 'process_budget_seconds': PROCESS_BUDGET,
            'wire_timeout_seconds': 3, 'wire_index': start}
    evidence['calls'].append(call)
    begun = time.monotonic()
    try:
        process = subprocess.run(argv, capture_output=True, text=True, timeout=PROCESS_BUDGET)
    except subprocess.TimeoutExpired as error:
        def decoded(value):
            return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
        call.update(exit=None, stdout=decoded(error.stdout), stderr=decoded(error.stderr),
            wall_seconds=time.monotonic() - begun, outer_timeout=True,
            accepted_terminal=False, subprocess_error=type(error).__name__)
        if len(relay.rows) > start:
            wire = relay.rows[start]
            call['relay_closed_after_timeout'] = wire['done'].wait(5)
            call['partial_wire'] = {key: wire[key] for key in ('request_hex', 'response_hex')}
        raise
    call.update(exit=process.returncode, stdout=process.stdout, stderr=process.stderr,
        wall_seconds=time.monotonic() - begun, outer_timeout=False)
    assert process.returncode == expected, call
    value = json.loads(process.stdout or process.stderr)
    call['result'] = value
    assert len(relay.rows) == start + connections, call
    if connections:
        wire = relay.rows[start]
        assert wire['done'].wait(5), 'CLI relay connection did not close'
        call.update(parse_wire(wire, complete=complete))
    else:
        call.update(commands=[], statuses=[], terminals=[], tags=[], documents=[], reply_lines=[])
    call['accepted_terminal'] = complete
    return value, call


def readonly(call):
    assert not any(command.startswith(MUTATIONS) for command in call['commands']), call


def assert_phase_literals(result, before, case):
    document = result.get('plan', result)['parent_transaction']
    assert document['execution_counts']['terminal_crc_passes'] == 1
    phase = dict(parent.values(tree(before)))
    for name, values in document['phases']['after_load'].items():
        phase[name] = values['after'] if isinstance(values, dict) else values
    for name, values in document['phases']['controls'].items():
        phase[name] = values['after'] if isinstance(values, dict) else values
    controls_records = case.get('expected_controls_records', case['expected_records'])
    for slot, record in controls_records.items():
        assert [phase[field(slot, i)][0] for i in range(32)] == record
    rows = [row for row in document['operation_results'] if row.get('mra_controls')]
    assert len(rows) == len(case['operations']) - 1
    assert all(row['mra_controls']['pending'] is False for row in rows)
    if case['id'].endswith('-readonly'):
        assert rows[0]['macro_normalized'] is False
        assert rows[0]['mra_control_base']['converted'] is False
    if 'expected_intents' in case:
        assert rows[0]['mra_controls']['journal'][0]['assignment_intents'] == case['expected_intents']
    if 'expected_icon_intents' in case:
        assert rows[0]['mra_controls']['journal'][1]['assignment_intents'] == case['expected_icon_intents']
    if case.get('reused_operation'):
        assert rows[1]['mra_controls']['allocations'][0]['reused'] is True
    if case['id'] == 'new-select-deferred-globals':
        observed = rows[0]['mra_controls']['journal'][0]['observed']
        assert observed['Zone'] == 4 and observed['Multiplexer'] == 2
        assert rows[0]['mra_control_base']['converted'] is True


def preserve(before, after, case):
    old, new = tree(before), tree(after)
    previous, current = parent.values(old), parent.values(new)
    assert set(previous) == set(current) and len(current) == 844
    owning = set()
    for slot, record in case['expected_records'].items():
        assert [current[field(slot, i)][0] for i in range(32)] == record, case['id']
        assert current[f'Widget{slot}RestoreLevel'] == [case['restore_levels'][slot]]
        owning.update(field(slot, i) for i in range(32))
        owning.add(f'Widget{slot}RestoreLevel')
    for index, expected in case['expected_rows_hex'].items():
        name = 'StaticTextString' + index
        assert bytes(current[name]).hex() == expected, (case['id'], index)
        if expected != case['source_rows_hex'][index]:
            owning.add(name)
    # Every non-owning PP is exact except the five named terminal CRCs.
    # Selected complete records and all64 static rows use source literals.
    allowed = owning | CRC_FIELDS
    changed = {name for name in current if current[name] != previous[name]}
    assert changed <= allowed, changed - allowed
    for row in new.find("Project/Network/Unit[Address='20']").findall('PP'):
        if row.get('Name') in allowed:
            prior = old.find("Project/Network/Unit[Address='20']/PP[@Name='" + row.get('Name') + "']")
            row.set('Value', prior.get('Value'))
    assert graph(ET.tostring(new, encoding='unicode')) == graph(before)


def journey(backend, variable, case, tmp_path, *, lost=False):
    with parent.journey(backend, variable, tmp_path, {}) as (owner, relay, evidence, specs, endpoint):
        evidence.update(format='private-cbus-edlt-mra-public-v1', profile=case['id'],
                        no_modal_image_picker_claim=True)
        seed(owner, case, evidence)
        before = snapshot(owner)
        argv = arguments(specs, tmp_path, case)
        if case in REFUSALS:
            result, call = invoke(relay, evidence, argv, expected=1, connections=case['connections'])
            assert result['error'] == case['expected_error'], result
            readonly(call)
            after = snapshot(owner)
            assert graph(after) == graph(before)
            evidence.update(snapshots={'before': before, 'after': after}, refusal_verified=True)
            return
        preview, preview_call = invoke(relay, evidence, ['unit', '--dry-run', *argv[1:]])
        readonly(preview_call)
        assert graph(snapshot(owner)) == graph(before)
        assert_phase_literals(preview, before, case)
        if lost:
            with FaultGate(endpoint, 'PP SAVE_TO_SOURCE', 'drop') as fault:
                result, call = invoke(fault, evidence, [*argv, '--backup-project', 'MRALOST'], expected=1, complete=False)
                assert fault.matches == 1
                assert_lost_successful_save(fault)
                assert sum(command.startswith('PP SAVE_TO_SOURCE ') for command in call['commands']) == 1
                saved = next(i for i, command in enumerate(call['commands']) if command.startswith('PP SAVE_TO_SOURCE '))
                assert not any(command.startswith((*MUTATIONS, 'PROJECT CLOSE ', 'PROJECT LOAD '))
                               for command in call['commands'][saved + 1:])
                uncertainty = result['edlt_parent_metadata_evidence']
                assert uncertainty['state'] == 'uncertain'
                assert uncertainty['saved'] is False
                assert uncertainty['automatic_retries'] == 0
                assert uncertainty['rollback_attempted'] is False
                assert uncertainty['pp_save_attempted'] is True
                assert uncertainty['pp_save_confirmed'] is False
                assert uncertainty['pp_save_outcome_uncertain'] is True
                assert uncertainty['pp_state_uncertain'] is True
                assert uncertainty['database_state_uncertain'] is True
                assert uncertainty['database_persistence'] == 'uncertain'
                assert uncertainty['target_project_save_attempted'] is False
                assert uncertainty['persistence_verified'] is False
                assert_phase_literals(uncertainty, before, case)
                evidence['lost_save_wires'] = fault.evidence()
        else:
            result, call = invoke(relay, evidence, [*argv, '--backup-project', 'MRABACK'])
            assert result['saved'] and result['persistence_verified'] and result['pp_readback_verified']
            assert sum(command.startswith('PP SAVE_TO_SOURCE ') for command in call['commands']) == 1
            assert call['commands'].count('PROJECT COPY TEST MRABACK') == 1
            assert call['commands'].count('PROJECT SAVE TEST') == 2
            assert call['commands'].count('PROJECT CLOSE TEST') == 1
            assert call['commands'].count('PROJECT LOAD TEST') == 1
            assert not any(command.startswith(('DBADD', 'DBSET', 'DBDELETE')) for command in call['commands'])
            assert_phase_literals(result, before, case)
        after = snapshot(owner)
        preserve(before, after, case)
        evidence['snapshots'] = {'before': before, 'after': after}
        evidence['single_save_verified'] = True
        if not lost:
            commands = []
            for command in ('PROJECT CLOSE TEST', 'PROJECT LOAD TEST'):
                response = owner.command(command)
                commands.append({'command': command, 'status': response.code, 'lines': list(response.lines)})
                assert response.code == 200
            reopened = snapshot(owner)
            assert graph(reopened) == graph(after)
            evidence.update(reopen_commands=commands, reopened_snapshot=reopened,
                            fresh_close_load_verified=True)


@pytest.mark.parametrize('backend,variable', parent.BACKENDS, ids=('mock', 'daemon'))
@pytest.mark.parametrize('case', POSITIVE, ids=lambda case: case['id'])
def test_public_mra_callbacks_one_save_and_preservation(backend, variable, case, tmp_path):
    journey(backend, variable, case, tmp_path)


@pytest.mark.parametrize('backend,variable', parent.BACKENDS, ids=('mock', 'daemon'))
@pytest.mark.parametrize('case', REFUSALS, ids=lambda case: case['id'])
def test_public_mra_pending_and_preconnection_refusals(backend, variable, case, tmp_path):
    journey(backend, variable, case, tmp_path)


@pytest.mark.parametrize('backend,variable', parent.BACKENDS, ids=('mock', 'daemon'))
def test_public_mra_lost_successful_save_is_not_replayed(backend, variable, tmp_path):
    case = next(case for case in POSITIVE if case['id'] == 'zone-explicit-callbacks')
    journey(backend, variable, case, tmp_path, lost=True)
