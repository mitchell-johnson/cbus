"""Private ordinary-parent time-date callbacks on both owned services.

Literal expectations are independently transcribed source effects. Explicit
bindings establish no host notifications, clock setting or physical result.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
from test_edlt_parent_time_date_controls import fixture
from xml.etree import ElementTree as ET

import pytest

from test_cgate_barcode_database_interop import FaultGate, graph, parse_wire
from test_cgate_edlt_global_images_interop import assert_lost_successful_save
import test_cgate_edlt_parent_add_dialog_interop as parent
from test_cgate_edlt_scene_add_dialog_interop import snapshot

VECTOR = Path(__file__).with_name('time-date-public-literals.json')
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
    """Complete invented input. Output expectations are separate source literals."""
    root=tree(snapshot(owner));unit=root.find("Project/Network/Unit[Address='20']")
    changes={'NavWidgetType':[1],'LevelBarStyle':[1],'Widget6RestoreLevel':[213]}
    changes.update({field(6,i):[value] for i,value in enumerate(bytes.fromhex(LITERALS['fixture']['record_hex']))})
    for slot,literal in case['source_records_hex'].items():
        changes.update({field(slot,i):[v] for i,v in enumerate(bytes.fromhex(literal))})
        if int(slot)>=6: changes[f'Widget{slot}RestoreLevel']=[213]
    active=[int(k) for k in case['source_records_hex'] if int(k)>=6]
    changes[field(max(active)+1 if active else 7)]=[255]
    changes.update({name:[value] for name,value in case['source_globals'].items()})
    for index,literal in LITERALS['source_rows_hex'].items(): changes['StaticTextString'+index]=list(bytes.fromhex(literal))
    rows={row.get('Name'):row for row in unit.findall('PP')}
    assert set(changes)<=set(rows)
    for name,values in changes.items(): rows[name].set('Value',' '.join(map(str,values)))
    document=ET.tostring(unit,encoding='unicode')
    assert owner.command_document('DBSETXML //TEST/254/p/20',document).code==301
    for command in ('PROJECT SAVE TEST','PROJECT CLOSE TEST','PROJECT LOAD TEST'): assert owner.command(command).code==200
    source=parent.values(tree(snapshot(owner)))
    assert len(source)==844
    for name,values in changes.items(): assert source[name]==values
    evidence['fixture_input']={'vector_sha256':hashlib.sha256(VECTOR.read_bytes()).hexdigest(),
        'unit_document_sha256':hashlib.sha256(document.encode()).hexdigest(),
        'source_parameters':844,'static_rows':64,'source_records_hex':case['source_records_hex'],
        'seed_commands_separate_from_cli':True,'LevelBarStyle_named_sibling_preserved':True}


def arguments(specs, tmp_path, case):
    ops = tmp_path / 'time-date-operations.json'
    ops.write_text(json.dumps(case['operations']))
    preferences = tmp_path / 'time-date-preferences.json'
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
    document=result.get('plan',result)['parent_transaction']
    assert document['execution_counts']['terminal_crc_passes']==1
    phase=dict(parent.values(tree(before)))
    for key in ('after_load','controls'):
        for name,values in document['phases'][key].items(): phase[name]=values['after'] if isinstance(values,dict) else values
    for slot,literal in case['expected_records_hex'].items():
        assert bytes(phase[field(slot,i)][0] for i in range(32)).hex()==literal
    for name,value in case['expected_globals'].items(): assert phase[name]==[value]
    assert phase['LevelBarStyle']==[1]
    rows=[row for row in document['operation_results'] if row.get('time_date_controls')]
    assert len(rows)==sum('time_date_controls' in row for row in case['operations'])
    assert all(not row['time_date_controls']['pending'] for row in rows)
    assert [row['reserved_widget_slots'] for row in rows]==case['expected_reserved_slots']
    assert len(document['time_date_control_bindings'])==len(rows)
    if case['id']=='retained-raw-readonly':
        assert not rows[0]['time_date_control_base']['converted']
        assert rows[0]['time_date_control_base']['mode']=='retained callbacks without ordinary mutation getters'


def preserve(before, after, case):
    old,new=tree(before),tree(after);previous,current=parent.values(old),parent.values(new)
    assert set(previous)==set(current) and len(current)==844
    owning=set()
    for slot,literal in case['expected_records_hex'].items():
        assert bytes(current[field(slot,i)][0] for i in range(32)).hex()==literal,case['id']
        owning.update(field(slot,i) for i in range(32))
        if int(slot)>=6:
            assert current[f'Widget{slot}RestoreLevel']==[case['restore_levels'][slot]]
            owning.add(f'Widget{slot}RestoreLevel')
    for name,value in case['expected_globals'].items(): assert current[name]==[value];owning.add(name)
    assert current['LevelBarStyle']==previous['LevelBarStyle']==[1]
    for index,literal in LITERALS['expected_rows_hex'].items(): assert bytes(current['StaticTextString'+index]).hex()==literal
    allowed=owning|CRC_FIELDS
    changed={name for name in current if current[name]!=previous[name]}
    assert changed<=allowed,changed-allowed
    for row in new.find("Project/Network/Unit[Address='20']").findall('PP'):
        if row.get('Name') in allowed:
            prior=old.find("Project/Network/Unit[Address='20']/PP[@Name='"+row.get('Name')+"']")
            row.set('Value',prior.get('Value'))
    assert graph(ET.tostring(new,encoding='unicode'))==graph(before)


def journey(backend, variable, case, tmp_path, *, lost=False):
    with patch.object(parent,'fixture',fixture), parent.journey(backend, variable, tmp_path, {}) as (owner, relay, evidence, specs, endpoint):
        evidence.update(format='private-cbus-edlt-time-date-public-v1', profile=case['id'],
                        no_host_notification_or_clock_claim=True)
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
                result, call = invoke(fault, evidence, [*argv, '--backup-project', 'TIMELOST'], expected=1, complete=False)
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
            result, call = invoke(relay, evidence, [*argv, '--backup-project', 'TIMEBACK'])
            assert result['saved'] and result['persistence_verified'] and result['pp_readback_verified']
            assert sum(command.startswith('PP SAVE_TO_SOURCE ') for command in call['commands']) == 1
            assert call['commands'].count('PROJECT COPY TEST TIMEBACK') == 1
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
def test_public_time_date_callbacks_one_save_and_preservation(backend, variable, case, tmp_path):
    journey(backend, variable, case, tmp_path)


@pytest.mark.parametrize('backend,variable', parent.BACKENDS, ids=('mock', 'daemon'))
@pytest.mark.parametrize('case', REFUSALS, ids=lambda case: case['id'])
def test_public_time_date_preconnection_refusals(backend, variable, case, tmp_path):
    journey(backend, variable, case, tmp_path)


@pytest.mark.parametrize('backend,variable', parent.BACKENDS, ids=('mock', 'daemon'))
def test_public_time_date_lost_successful_save_is_not_replayed(backend, variable, tmp_path):
    case = next(case for case in POSITIVE if case['id'] == 'functional-all-bindings')
    journey(backend, variable, case, tmp_path, lost=True)
