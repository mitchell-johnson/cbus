"""Ordered DIN controls through the public CLI and two owned database adapters.

Literal expectations come from the retained slider/callback source review.
The projects/specifications are synthetic; no vendor instructions or hardware
execute in these journeys. A Toolkit-save history owns exactly one PP save.
"""
from contextlib import contextmanager
import json

import pytest

from test_cgate_barcode_database_interop import FaultGate, cli
from test_cgate_din_save_interop import (
    BACKENDS, TYPES, assert_preservation, din_cli, document, fresh_parameters,
    journey, normalized_changes, offline_plan, saved_once,
)


CHANNELS = {'RELDN4': 4, 'RELDN8': 8, 'RELDN8B': 8, 'RELDN12': 12,
            'DIMDN4': 4, 'DIMDN4F': 4, 'DIMDN8': 8, 'DIMDN8F': 8}
DELAY_BYTES = {
    5: [5, 10, 15, 20, 25, 30, 35, 40],
    10: [10, 20, 30, 40, 50, 60, 61, 62],
    20: [20, 40, 60, 62, 64, 66, 68, 70],
    30: [30, 60, 63, 66, 69, 72, 75, 78],
}


@contextmanager
def controls_journey(backend, variable, unit_type, tmp_path):
    """Keep the existing owned lifecycle and give this feature its own receipt."""
    try:
        with journey(backend, variable, unit_type, tmp_path) as context:
            context[2]['format'] = 'cbus-din-output-controls-owned-v1'
            yield context
    finally:
        original = tmp_path / 'din-save-evidence.json'
        if original.exists():
            original.rename(tmp_path / 'din-controls-evidence.json')


def control_file(tmp_path, operations, name='controls'):
    path = tmp_path / (name + '.json')
    path.write_text(json.dumps(operations))
    return path


def history(unit_type):
    controls = [{'op': 'synchronise', 'tab': 'turn-on', 'enabled': True}]
    if unit_type.startswith('REL'):
        controls.extend([
            {'op': 'minimum', 'channel': 1, 'percent': 40},
            {'op': 'stagger-turn-on', 'step_percent': {4: 25, 8: 12, 12: 8}[CHANNELS[unit_type]]},
            {'op': 'minimum', 'channel': 1, 'percent': 20},
        ])
    else:
        controls.extend([
            # The first change couples maximum to91; the second couples
            # minimum to39. Both callbacks propagate while synchronised.
            {'op': 'minimum', 'channel': 1, 'percent': 90},
            {'op': 'maximum', 'channel': 2, 'percent': 40},
            {'op': 'stagger-minimum', 'step_percent': 1},
            {'op': 'minimum', 'channel': 1, 'percent': 20},
            {'op': 'stagger-maximum', 'step_percent': 1},
            {'op': 'synchronise', 'tab': 'recovery', 'enabled': True},
            {'op': 'recovery-delay', 'channel': 2, 'raw': 60},
            {'op': 'stagger-recovery-delay', 'step_seconds': 30},
            {'op': 'recovery-delay', 'channel': 1, 'raw': 7},
        ])
    return controls


def final_changes(unit_type):
    """Source literals, including the owning save's mapped RELDN8 tail rules."""
    expected = normalized_changes(unit_type)
    if unit_type.startswith('REL'):
        expected['MinDimmingLevel'] = {
            'RELDN4': '51 127 191 255',
            'RELDN8': '0 51 61 91 122 0 0 153 183 214 255 31',
            'RELDN8B': '51 61 91 122 153 183 214 255 28 29 30 31',
            'RELDN12': '51 40 61 81 102 122 142 163 183 204 224 255',
        }[unit_type]
    else:
        count = CHANNELS[unit_type]
        expected.update({
            'MinDimmingLevel': {4: '51 5 7 10', 8: '51 5 7 10 12 15 17 20'}[count],
            'MaxDimmingLevel': {
                4: '247 249 252 255', 8: '237 239 242 244 247 249 252 255',
            }[count],
            'PowerUpDelay': {4: '7 60 63 66', 8: '7 60 63 66 69 72 75 78'}[count],
        })
    return expected


def prefix_changes(unit_type):
    """Actual Synchronise callbacks before Stagger disables each checkbox."""
    if unit_type.startswith('REL'):
        return {'MinDimmingLevel': {
            'RELDN4': [102, 102, 102, 102],
            'RELDN8': [20, 102, 102, 102, 102, 25, 26, 102, 102, 102, 102, 31],
            'RELDN8B': [102, 102, 102, 102, 102, 102, 102, 102, 28, 29, 30, 31],
            'RELDN12': [102, 102, 102, 102, 102, 102, 102, 102, 102, 102, 102, 102],
        }[unit_type]}
    return {'MinDimmingLevel': [99] * CHANNELS[unit_type],
            'MaxDimmingLevel': [102] * CHANNELS[unit_type]}


def no_persistent_write(call):
    assert not any(command.startswith(('PP SAVE', 'PROJECT SAVE ', 'PP PROGRAM '))
                   for command in call['commands']), call


def no_staged_write(call):
    no_persistent_write(call)
    assert not any(command.startswith('PP SET ') for command in call['commands']), call


def matching_preview(relay, evidence, specs, tmp_path, unit_type, current,
                     operations, name, *, toolkit_save=False):
    path = control_file(tmp_path, operations, name)
    options = ('--controls', str(path), *(('--toolkit-save',) if toolkit_save else ()))
    controls_before = path.read_bytes()
    plan = offline_plan(specs, tmp_path, unit_type, current, *options)
    snapshot = tmp_path / 'snapshot.json'
    snapshot_before = snapshot.read_bytes()
    assert json.loads(snapshot_before)['parameters'] == current
    preview, call = din_cli(relay, evidence, specs, *options, dry_run=True)
    assert plan['format'] == 'cbus-din-output-controls-plan-v1'
    assert plan['operations'] == operations
    for key, value in plan.items():
        assert preview[key] == value, (key, preview[key], value)
    assert preview['verified'] is True and preview['saved'] is False
    assert path.read_bytes() == controls_before
    assert snapshot.read_bytes() == snapshot_before
    no_persistent_write(call)
    return plan, path


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('unit_type', TYPES)
def test_public_din_ordered_controls_all_profiles(backend, variable, unit_type, tmp_path):
    with controls_journey(backend, variable, unit_type, tmp_path) as context:
        owner, relay, evidence, specs, _ = context
        before = document(owner)
        current = fresh_parameters(relay, evidence)
        operations = history(unit_type)

        # A real sync change is observed before the later Stagger overwrites
        # it. The dimmer prefix also proves callback order across both sliders.
        prefix = operations[:2 if unit_type.startswith('REL') else 3]
        preview, _ = matching_preview(relay, evidence, specs, tmp_path, unit_type,
                                      current, prefix, 'synchronised-prefix')
        assert preview['changes'] == prefix_changes(unit_type)
        if not unit_type.startswith('REL'):
            for step, expected in DELAY_BYTES.items():
                preview, _ = matching_preview(
                    relay, evidence, specs, tmp_path, unit_type, current,
                    [{'op': 'stagger-recovery-delay', 'step_seconds': step}], 'delay-' + str(step))
                assert preview['changes'] == {'PowerUpDelay': expected[:CHANNELS[unit_type]]}

        plan, _ = matching_preview(relay, evidence, specs, tmp_path, unit_type,
                                   current, operations, 'owning-history', toolkit_save=True)
        expected = final_changes(unit_type)
        expected_arrays = {name: list(map(int, values.split())) for name, values in expected.items()}
        assert plan['changes'] == expected_arrays
        assert plan['settings_plan']['changes'] == expected_arrays
        assert plan['settings_plan']['format'] == 'cbus-din-output-settings-plan-v2'
        assert plan['settings_plan']['normalization_passes'] == 1
        assert plan['toolkit_save'] is True
        assert plan['initial_controls']['synchronise'] == {'turn-on': False, 'recovery': False}
        assert plan['final_controls']['synchronise'] == {'turn-on': False, 'recovery': False}
        assert [row['operation'] for row in plan['control_history']] == operations
        if not unit_type.startswith('REL'):
            assert plan['control_history'][1]['controls']['positions']['maximum'] == [91] * CHANNELS[unit_type]
            assert plan['control_history'][7]['controls']['positions']['recovery-delay'] == [60] * CHANNELS[unit_type]
            assert plan['control_history'][7]['controls']['synchronise']['recovery'] is True
        assert document(owner) == before
        assert fresh_parameters(relay, evidence) == current

        # Replaying a saved history must bind the derived writes as well as
        # the ordered requests; arbitrary nested byte edits cannot bypass it.
        tampered = json.loads(json.dumps(plan))
        tampered['settings_plan']['changes']['MinDimmingLevel'][0] = 88
        tampered['changes']['MinDimmingLevel'][0] = 88
        refused, call = din_cli(relay, evidence, specs, '--plan',
                               control_file(tmp_path, tampered, 'tampered'), expected=1)
        assert refused['error']
        no_staged_write(call)

        unsupported = ('stagger-recovery-delay' if unit_type.startswith('REL')
                       else 'stagger-turn-on')
        field = 'step_seconds' if unit_type.startswith('REL') else 'step_percent'
        for label, bad_operations in (
            ('unsupported-profile-control', [{'op': unsupported, field: 5}]),
            ('invalid-boolean', [{'op': 'synchronise', 'tab': 'turn-on', 'enabled': 1}]),
        ):
            refused, call = din_cli(relay, evidence, specs, '--controls',
                                   control_file(tmp_path, bad_operations, label), expected=1)
            assert refused['error']
            no_staged_write(call)
        assert document(owner) == before

        saved_plan = control_file(tmp_path, plan, 'reviewed-plan')
        applied, call = din_cli(relay, evidence, specs, '--plan', saved_plan)
        assert applied['saved'] is True and applied['toolkit_save'] is True
        assert applied['operations'] == operations
        saved_once(call)
        after = document(owner)
        assert_preservation(before, after, expected)
        fresh = fresh_parameters(relay, evidence)
        assert fresh == applied['parameters']
        assert {name: fresh[name] for name in expected} == expected

        refused, call = din_cli(relay, evidence, specs, '--plan', saved_plan, expected=1)
        assert 'changed since' in refused['error']
        no_staged_write(call)
        assert document(owner) == after

        for action in ('save', 'close', 'load'):
            outcome, call = cli(relay, evidence['calls'], 'project', action, 'DINSAVE')
            assert outcome['status'] == 200
            assert call['commands'] == [f'PROJECT {action.upper()} DINSAVE']
        assert owner.command('PROJECT USE DINSAVE').code == 200
        assert document(owner) == after
        assert fresh_parameters(relay, evidence) == fresh
        evidence['operations'] = operations
        evidence['expected_changes'] = expected_arrays
        evidence['snapshots'] = {'before': before, 'after_controls': after}


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock', 'daemon'])
@pytest.mark.parametrize('unit_type', ['DIMDN8', 'RELDN8'])
def test_public_din_controls_lost_successful_save_is_not_replayed(
        backend, variable, unit_type, tmp_path):
    with controls_journey(backend, variable, unit_type, tmp_path) as context:
        owner, relay, evidence, specs, endpoint = context
        before = document(owner)
        operations = history(unit_type)
        path = control_file(tmp_path, operations)
        with FaultGate(endpoint, 'PP SAVE_TO_SOURCE', 'drop') as fault:
            failure, call = din_cli(fault, evidence, specs, '--controls', path,
                                    '--toolkit-save', expected=1, complete=False)
            assert 'error' in failure and not failure.get('saved', False)
            assert len(fault.rows) == 1 and fault.matches == 1
            terminal = bytes.fromhex(fault.rows[0]['lost_backend_terminal_hex']).decode()
            assert '] 200 ' in terminal, terminal
            saves = [command for command in call['commands'] if command.startswith('PP SAVE')]
            assert len(saves) == 1 and saves[0].startswith('PP SAVE_TO_SOURCE ')
            assert call['commands'][-1] == saves[0], call
            evidence['wires'].extend(fault.evidence())
        after = document(owner)
        expected = final_changes(unit_type)
        assert_preservation(before, after, expected)
        fresh = fresh_parameters(relay, evidence)
        assert {name: fresh[name] for name in expected} == expected
        assert document(owner) == after
        evidence['operations'] = operations
        evidence['expected_changes'] = expected
        evidence['snapshots'] = {'before': before, 'after_lost_successful_save': after}
