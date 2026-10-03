"""Source-pinned SENLL Global initialization on owned loopback services."""
import json
import subprocess
import sys

import pytest

from cbus_toolkit.light_level_sensors import INVENTORY_LAYOUTS, LAYOUTS
from test_cgate_barcode_database_interop import FaultGate, cli, graph
from test_cgate_senll_controls_interop import (
    BACKENDS, NETWORK, SOURCE, assert_graph_changes, document, journey as legacy_journey,
    parameter_map,
)
from test_cgate_senll_inventory_interop import journey as complete_journey


PROFILES = [('legacy43', legacy_journey, 43), ('complete47', complete_journey, 47)]
# Literal Global control values, independent of the planner under test. The
# inherited journey's NORMAL baseline makes every other forced-save field stable.
CASES = [
    ('stored-0', 0, None, 3),
    ('stored-1', 1, None, 3),
    ('stored-2', 2, None, 3),
    ('preserved-3', 3, None, 3),
    ('preserved-255', 255, None, 255),
    ('override-0-to-17', 0, 17, 17),
]


def global_cli(relay, evidence, specs, *, interval=None, dry_run=False, expected=0, complete=True):
    arguments = ['unit', '--lock-address', NETWORK, '--source', SOURCE]
    if dry_run:
        arguments.append('--dry-run')
    arguments.extend(('sensor-light-level', '--spec-dir', specs))
    if interval is not None:
        arguments.extend(('--status-report-interval', interval))
    result, call = cli(relay, evidence['calls'], *arguments, expected=expected, complete=complete)
    assert not any(command.startswith(('NET OPEN ', 'PROJECT SAVE ', 'PP PROGRAM '))
                   for command in call['commands']), call
    return result, call


def offline_plan(tmp_path, specs, evidence, values, *, interval=None, expected=0):
    snapshot = tmp_path / 'global-sensor.json'
    snapshot.write_text(json.dumps({
        'format': 'cbus-cli-parameters-v1', 'unit_type': 'SENLL', 'firmware': '2.3.00',
        'catalog_number': '5031PE', 'parameters': values,
    }), encoding='utf-8')
    original_snapshot = snapshot.read_bytes()
    original_specs = {path.name: path.read_bytes() for path in specs.iterdir()}
    arguments = [sys.executable, '-m', 'cbus_toolkit', 'sensors', '--spec-dir', str(specs),
                 'light-level-plan', str(snapshot)]
    if interval is not None:
        arguments.extend(('--status-report-interval', str(interval)))
    run = subprocess.run(arguments, capture_output=True, text=True, timeout=30)
    evidence.setdefault('offline_calls', []).append({
        'argv': arguments, 'exit': run.returncode, 'stdout': run.stdout, 'stderr': run.stderr,
    })
    assert run.returncode == expected, run.stdout + run.stderr
    planned = json.loads(run.stdout or run.stderr)
    assert snapshot.read_bytes() == original_snapshot
    assert {path.name: path.read_bytes() for path in specs.iterdir()} == original_specs
    return planned, snapshot, original_snapshot, original_specs


def assert_inputs_preserved(snapshot, original_snapshot, specs, original_specs):
    assert snapshot.read_bytes() == original_snapshot
    assert {path.name: path.read_bytes() for path in specs.iterdir()} == original_specs


def consumed_values(values, profile, field_count):
    names = set(LAYOUTS)
    if profile == 'complete47':
        names.update(INVENTORY_LAYOUTS)
    assert len(names) == field_count
    # The authored specification also has unconsumed PP fields. They remain in
    # the full result/graph checks but are outside the bound sensor plan input.
    return {name: list(map(int, values[name].split())) for name in names}


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('profile,make_journey,field_count', PROFILES, ids=[row[0] for row in PROFILES])
@pytest.mark.parametrize('case,stored,interval,selected', CASES, ids=[row[0] for row in CASES])
def test_public_senll_global_save_and_reopen(backend, variable, profile, make_journey, field_count,
                                           case, stored, interval, selected, tmp_path):
    with make_journey(backend, variable, tmp_path, {'StatusReportInterval': str(stored)}) as (
            owner, relay, evidence, specs, _endpoint):
        evidence['global_status_case'] = {
            'profile': profile, 'case': case, 'stored': stored, 'explicit': interval, 'selected': selected,
        }
        before = document(owner)
        original_values = parameter_map(before)
        expected_snapshot = consumed_values(original_values, profile, field_count)
        assert original_values['StatusReportInterval'] == str(stored)
        expected_changes = {} if selected == stored else {'StatusReportInterval': [selected]}
        expected_values = {**original_values, 'StatusReportInterval': str(selected)}
        expected_graph_changes = {} if selected == stored else {'StatusReportInterval': str(selected)}

        planned, snapshot, original_snapshot, original_specs = offline_plan(
            tmp_path, specs, evidence, original_values, interval=interval)
        assert planned['changes'] == expected_changes
        assert len(planned['expected']) == field_count
        assert planned['expected'] == expected_snapshot
        assert planned['expected']['StatusReportInterval'] == [stored]
        assert planned['dialog']['status_report_interval'] == selected
        assert planned['dialog']['status_report_interval_unit'] == 'seconds'

        preview, preview_call = global_cli(relay, evidence, specs, interval=interval, dry_run=True)
        assert preview['changes'] == planned['changes'] == expected_changes
        assert preview['expected'] == planned['expected']
        assert preview['dialog']['status_report_interval'] == selected
        assert preview['verified'] and preview['saved'] is False and preview['device_verified'] is False
        assert preview['parameters'] == expected_values
        assert not any(command.startswith('PP SAVE') for command in preview_call['commands'])
        assert graph(document(owner)) == graph(before)

        result, call = global_cli(relay, evidence, specs, interval=interval)
        assert result['changes'] == expected_changes
        assert result['expected'] == planned['expected']
        assert result['verified'] and result['saved'] is True and result['device_verified'] is False
        assert result['parameters'] == expected_values
        saves = [command for command in call['commands'] if command.startswith('PP SAVE')]
        assert len(saves) == 1 and saves[0].startswith('PP SAVE_TO_SOURCE '), call
        assert_graph_changes(before, document(owner), expected_graph_changes)

        evidence['project_lifecycle'] = []
        for command in ('PROJECT SAVE SENLL', 'PROJECT CLOSE SENLL', 'PROJECT LOAD SENLL'):
            response = owner.command(command)
            evidence['project_lifecycle'].append({'command': command, 'status': response.code})
            assert response.code == 200
        assert_graph_changes(before, document(owner), expected_graph_changes)
        fresh, fresh_call = cli(relay, evidence['calls'], 'unit', '--lock-address', NETWORK,
                               '--source', SOURCE, 'show')
        assert fresh == expected_values
        assert not any(command.startswith(('PP SET ', 'PP SAVE')) for command in fresh_call['commands'])
        assert_inputs_preserved(snapshot, original_snapshot, specs, original_specs)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('profile,make_journey,field_count', PROFILES, ids=[row[0] for row in PROFILES])
def test_public_senll_global_invalid_override_is_read_only(backend, variable, profile, make_journey,
                                                         field_count, tmp_path):
    with make_journey(backend, variable, tmp_path, {'StatusReportInterval': '0'}) as (
            owner, relay, evidence, specs, _endpoint):
        evidence['global_status_case'] = {'profile': profile, 'stored': 0, 'explicit': 0, 'refused': True}
        before = document(owner)
        original_values = parameter_map(before)
        assert len(consumed_values(original_values, profile, field_count)) == field_count
        planned, snapshot, original_snapshot, original_specs = offline_plan(
            tmp_path, specs, evidence, original_values, interval=0, expected=1)
        assert '3..255' in planned['error']
        result, call = global_cli(relay, evidence, specs, interval=0, expected=1)
        assert '3..255' in result['error']
        assert not any(command.startswith(('PP SET ', 'PP SAVE', 'PROJECT SAVE ', 'DBSET',
                                           'DBADD', 'DBDELETE')) for command in call['commands'])
        assert graph(document(owner)) == graph(before)
        assert_inputs_preserved(snapshot, original_snapshot, specs, original_specs)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
def test_public_senll_global_lost_save_is_not_replayed(backend, variable, tmp_path):
    with complete_journey(backend, variable, tmp_path, {'StatusReportInterval': '0'}) as (
            owner, _relay, evidence, specs, endpoint):
        evidence['global_status_case'] = {'profile': 'complete47', 'stored': 0, 'lost_save': True}
        before = document(owner)
        with FaultGate(endpoint, 'PP SAVE_TO_SOURCE', 'drop') as fault:
            try:
                result, call = global_cli(fault, evidence, specs, expected=1, complete=False)
                assert 'error' in result
                assert fault.matches == 1
                saves = [command for command in call['commands'] if command.startswith('PP SAVE')]
                assert len(saves) == 1 and saves[0].startswith('PP SAVE_TO_SOURCE '), call
                assert not any(command.startswith(('PROJECT SAVE ', 'DBSET', 'DBADD', 'DBDELETE'))
                               for command in call['commands'])
                assert bytes.fromhex(fault.rows[0]['lost_backend_terminal_hex']).decode().split()[1] == '200'
            finally:
                evidence['wires'].extend(fault.evidence())
        # This separate observer establishes the owned backend's applied state;
        # the failed public invocation never reconnects, rolls back or replays.
        assert_graph_changes(before, document(owner), {'StatusReportInterval': '3'})
