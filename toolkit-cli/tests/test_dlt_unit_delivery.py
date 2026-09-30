"""Bounded original unit delivery phases, catches and canonical replay plans."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from cbus_toolkit.dlt_unit_delivery import (
    DltUnitDeliveryError, assess_unit_delivery, compile_unit_delivery,
    validate_unit_delivery_plan,
)


def flavour(**changes):
    result = {'format': 'cbus-classic-dlt-broadcast-request-v1', 'project': 'LAB',
              'network': 254, 'application': 56, 'application_oid': None,
              'group': 20, 'level': None, 'language': 1, 'variant': 1,
              'tag_type': 'TEXT', 'tag_value': 'Kitchen', 'already_broadcast': False,
              'bitmap': None}
    result.update(changes)
    return result


def bitmap():
    return {'width': 64, 'data_hex': '8100' * 64}


def key(number=1, **changes):
    result = {'key': number, 'kfi': 0, 'role': 'ordinary', 'target_state': 'present',
              'flavour': flavour()}
    result.update(changes)
    return result


def request(**changes):
    result = {'format': 'cbus-classic-dlt-unit-delivery-request-v1', 'project': 'LAB',
              'network': 254, 'unit_application': 56, 'unit_address': 10,
              'default_language': 1, 'save_labels': True, 'transfer': False,
              'block_dynamic_updates': True, 'kfi_enabled': False,
              'reblock_session_open': False, 'keys': [key()]}
    result.update(changes)
    return result


def outcomes(plan, entries=None):
    if entries is None:
        entries = [(op['id'], 'returned') for op in plan['operations']]
    by_id = {op['id']: op for op in plan['operations']}
    rows = []
    for identifier, outcome in entries:
        base = {'id': identifier, 'operation_sha256': by_id[identifier]['operation_sha256']}
        if isinstance(outcome, dict):
            rows.append({**base, **outcome})
        else:
            rows.append({**base, 'outcome': outcome})
    return {'format': 'cbus-classic-dlt-unit-delivery-outcomes-v1',
            'plan_sha256': plan['plan_sha256'], 'operations': rows}


def raised(kind='cgate_command'):
    return {'outcome': 'raised', 'error_class': kind, 'message': 'Supplied operation failure'}


def test_two_save_boundary_exact_commands_and_no_acceptance_claims():
    plan = compile_unit_delivery(request(kfi_enabled=True, keys=[key(kfi=15)])).as_dict()
    assert [row['id'] for row in plan['operations']] == ['initial_save', 'kfi', 'key.1.broadcast.1', 'reblock']
    assert plan['operations'][0]['enable_dynamic_labels'] == 1
    assert 'ProjectSave and LoadStatus' in plan['operations'][0]['boundary']
    assert plan['operations'][0]['whole_pp_serialized'] is False
    assert plan['operations'][1]['command'] == 'label kfiset 254/56 10 15 0 0 0 0 0 0 0'
    assert plan['operations'][2]['command'] == 'LIGHTING LABEL //LAB/254/56 1 20 - F0 00 4B69746368656E'
    final = plan['operations'][-1]
    assert final['sequence'] == ['LOCK', 'START', 'LOAD', 'SET EnableDynamicLabels=0', 'SAVE']
    assert final['owned_cleanup'] == ['END', 'UNLOCK'] and final['timeout_ms'] == 30000
    result = assess_unit_delivery(plan, outcomes(plan))
    assert result['status'] == 'completed'
    assert result['initial_save_returned'] is result['reblock_returned'] is True
    assert result['predicted_enable_dynamic_labels'] == 0
    assert result['per_key_cache_marked'] == {'1': True}
    for field in ('io_performed', 'native_accepted', 'device_verified', 'rendering_verified',
                  'persistence_verified', 'reblock_cleanup_verified'):
        assert result[field] is False
    assert result['outcome_provenance'] == 'caller-supplied; not independently observed or authenticated'


def test_existing_reblock_session_still_saves_without_end_unlock():
    plan = compile_unit_delivery(request(reblock_session_open=True)).as_dict()
    final = plan['operations'][-1]
    assert final['sequence'] == ['SET EnableDynamicLabels=0', 'SAVE']
    assert final['owned_cleanup'] == [] and final['opens_session'] is False
    assert final['saves_existing_session'] is True


@pytest.mark.parametrize('save,transfer,block', [(False, False, True), (False, True, True),
                                               (True, False, False), (True, True, True)])
def test_save_labels_independent_block_and_transfer_override(save, transfer, block):
    plan = compile_unit_delivery(request(save_labels=save, transfer=transfer, block_dynamic_updates=block)).as_dict()
    assert plan['delivery_gate'] == (save or transfer)
    assert any(op['kind'] == 'broadcast' for op in plan['operations']) == (save or transfer)
    assert any(op['kind'] == 'reblock' for op in plan['operations']) == block


def test_kfi_before_label_gate_zero_keys_and_abort_before_error_reset():
    plan = compile_unit_delivery(request(keys=[], save_labels=False, kfi_enabled=True)).as_dict()
    assert plan['delivery_gate'] is False
    assert plan['operations'][1]['command'] == 'label kfiset 254/56 10 0 0 0 0 0 0 0 0'
    report = assess_unit_delivery(plan, outcomes(plan, [('initial_save', 'returned'), ('kfi', raised())]))
    assert report['status'] == 'aborted' and report['stopped_at'] == 'kfi'
    assert not any(e['event'] == 'reset_label_errors' for e in report['trace'])
    assert report['reblock_returned'] is False


@pytest.mark.parametrize('role,state,action', [
    ('ordinary', 'missing', 'clear_without_flavour'), ('ordinary', 'unused', 'clear_without_flavour'),
    ('scene', 'missing', 'target_skipped'), ('scene_modify', 'missing', 'target_skipped'),
    ('scene_modify', 'unused', 'target_skipped'), ('ordinary', 'present', 'clear_without_flavour'),
])
def test_source_role_target_difference(role, state, action):
    plan = compile_unit_delivery(request(keys=[key(role=role, target_state=state, flavour=None)])).as_dict()
    assert plan['keys'][0]['action'] == action
    clears = [op for op in plan['operations'] if op['kind'] == 'clear']
    if action == 'clear_without_flavour':
        assert clears[0]['command'] == 'label clear 254/56 10 1'
        assert clears[0]['error_policy'] == 'abort'
    else:
        assert clears == []


@pytest.mark.parametrize('kind', ['TEXT', 'ICON', 'DYNAMIC', 'FONT'])
@pytest.mark.parametrize('value', ['', '<Default>'])
def test_outer_empty_default_clears_all_types_before_payload_validation(kind, value):
    f = flavour(tag_type=kind, tag_value=value)
    plan = compile_unit_delivery(request(keys=[key(role='scene_modify', flavour=f)])).as_dict()
    assert plan['keys'][0]['action'] == 'clear_retained_flavour'
    assert plan['operations'][1]['command'] == 'label clear 254/56 10 1'
    report = assess_unit_delivery(plan, outcomes(plan))
    assert report['per_key_cache_marked'] == {'1': True}


@pytest.mark.parametrize('kind', ['DYNAMIC', 'FONT'])
def test_empty_bitmap_primary_requires_lookup_but_scene_does_not_load(kind):
    f = flavour(tag_type=kind, tag_value='malformed but never broadcast')
    with pytest.raises(DltUnitDeliveryError, match='LoadDLTBitmap'):
        compile_unit_delivery(request(keys=[key(flavour=f)]))
    plan = compile_unit_delivery(request(keys=[key(role='scene_modify', flavour=f)])).as_dict()
    assert plan['keys'][0]['action'] == 'clear_retained_flavour'
    gated = compile_unit_delivery(request(save_labels=False, keys=[key(flavour=f)])).as_dict()
    assert gated['keys'][0]['action'] == 'gate_skipped'


def test_each_duplicate_snapshot_resets_cache_and_rebroadcasts():
    f = flavour(already_broadcast=True)
    plan = compile_unit_delivery(request(keys=[key(flavour=f), key(2, flavour=f)])).as_dict()
    sends = [op for op in plan['operations'] if op['kind'] == 'broadcast']
    assert len(sends) == 2 and sends[0]['command'] == sends[1]['command']
    assert [e['key'] for e in plan['events'] if e['event'] == 'reset_broadcast'] == [1, 2]
    report = assess_unit_delivery(plan, outcomes(plan))
    assert report['per_key_cache_marked'] == {'1': True, '2': True}


def test_unicode_suppression_marks_without_command_and_no_blank_dle_broadcast():
    plan = compile_unit_delivery(request(keys=[key(flavour=flavour(tag_value='x' * 14 + '漢'))])).as_dict()
    assert [op['kind'] for op in plan['operations']] == ['initial_save', 'reblock']
    partial = assess_unit_delivery(plan, outcomes(plan, [('initial_save', 'returned')]))
    assert partial['per_key_cache_marked'] == {'1': True} and partial['native_accepted'] is False
    assert partial['next_operation'] == 'reblock'


def dynamic_plan():
    return compile_unit_delivery(request(keys=[key(flavour=flavour(tag_type='DYNAMIC', tag_value='1', bitmap=bitmap())),
                                               key(2)])).as_dict()


def test_first_dynamic_cgate_failure_skips_icon_continues_next_key_and_reblocks():
    plan = dynamic_plan()
    report = assess_unit_delivery(plan, outcomes(plan, [
        ('initial_save', 'returned'), ('key.1.broadcast.1', raised()),
        ('key.2.broadcast.1', 'returned'), ('reblock', 'returned')]))
    assert report['status'] == 'completed_with_label_errors'
    assert report['skipped_operations'] == ['key.1.broadcast.2']
    assert report['per_key_cache_marked'] == {'1': False, '2': True}
    assert report['reblock_returned'] is True and len(report['collected_label_errors']) == 1


def test_second_dynamic_cgate_failure_retains_mark_and_other_exception_aborts():
    plan = dynamic_plan()
    report = assess_unit_delivery(plan, outcomes(plan, [
        ('initial_save', 'returned'), ('key.1.broadcast.1', 'returned'),
        ('key.1.broadcast.2', raised()), ('key.2.broadcast.1', 'returned'), ('reblock', 'returned')]))
    assert report['per_key_cache_marked']['1'] is True
    assert report['status'] == 'completed_with_label_errors'
    aborted = assess_unit_delivery(plan, outcomes(plan, [
        ('initial_save', 'returned'), ('key.1.broadcast.1', raised('other'))]))
    assert aborted['status'] == 'aborted' and aborted['reblock_returned'] is False
    assert aborted['collected_label_errors'] == []
    assert aborted['per_key_cache_marked'] == {'1': False, '2': None}


@pytest.mark.parametrize('has_flavour,expected', [(True, 'completed_with_label_errors'), (False, 'aborted')])
def test_clear_catch_scope_depends_on_retained_flavour(has_flavour, expected):
    plan = compile_unit_delivery(request(keys=[key(flavour=flavour(tag_value='') if has_flavour else None)])).as_dict()
    entries = [('initial_save', 'returned'), ('key.1.clear', raised())]
    if has_flavour:
        entries.append(('reblock', 'returned'))
    report = assess_unit_delivery(plan, outcomes(plan, entries))
    assert report['status'] == expected
    assert report['per_key_cache_marked']['1'] is (False if has_flavour else None)


@pytest.mark.parametrize('where,mark', [('key.1.broadcast.1', None), ('key.1.broadcast.2', True)])
def test_uncertainty_stops_without_automatic_retry_or_resume(where, mark):
    plan = dynamic_plan()
    entries = [('initial_save', 'returned')]
    if where.endswith('.2'):
        entries.append(('key.1.broadcast.1', 'returned'))
    entries.append((where, {'outcome': 'uncertain', 'reason': 'timeout'}))
    report = assess_unit_delivery(plan, outcomes(plan, entries))
    assert report['status'] == 'uncertain' and report['stopped_at'] == where
    assert report['per_key_cache_marked']['1'] is mark
    assert report['recovery']['automatic_retry'] is report['recovery']['automatic_resume'] is False
    with pytest.raises(DltUnitDeliveryError, match='unreachable'):
        assess_unit_delivery(plan, outcomes(plan, entries + [('reblock', 'returned')]))


@pytest.mark.parametrize('stage', ['initial_save', 'reblock'])
@pytest.mark.parametrize('outcome', [raised(), {'outcome': 'uncertain', 'reason': 'unknown'}])
def test_save_failure_keeps_physical_and_cleanup_state_unknown(stage, outcome):
    plan = compile_unit_delivery(request(keys=[])).as_dict()
    entries = [] if stage == 'initial_save' else [('initial_save', 'returned')]
    report = assess_unit_delivery(plan, outcomes(plan, entries + [(stage, outcome)]))
    assert report['predicted_enable_dynamic_labels'] is None
    assert report['reblock_cleanup_verified'] is False and report['native_accepted'] is False


def test_plan_immutable_canonical_nested_commands_and_outcome_reachability():
    data = request()
    model = compile_unit_delivery(data)
    plan = model.as_dict()
    data['keys'][0]['flavour']['tag_value'] = 'changed'
    assert model.as_dict() == plan
    with pytest.raises(FrozenInstanceError):
        model._json = '{}'
    assert validate_unit_delivery_plan(plan).as_dict() == plan
    tampered = deepcopy(plan)
    tampered['operations'][1]['command'] += ' injected'
    with pytest.raises(DltUnitDeliveryError, match='canonical'):
        validate_unit_delivery_plan(tampered)
    with pytest.raises(DltUnitDeliveryError, match='reachable operation order'):
        assess_unit_delivery(plan, outcomes(plan, [('reblock', 'returned')]))


ORIGINAL = json.loads((Path(__file__).resolve().parents[1] /
                       'research/fixtures/classic-dlt-delivery-original.json').read_text())


@pytest.mark.parametrize('row', ORIGINAL['observations']['gates'])
def test_retained_original_gate_receipt(row):
    plan = compile_unit_delivery(request(save_labels=row['save_labels'], transfer=row['transfer'],
                                         keys=[key(i + 1) for i in range(row['key_count'])])).as_dict()
    assert plan['delivery_gate'] is row['result']['eligible']


@pytest.mark.parametrize('row', ORIGINAL['observations']['decisions'])
def test_retained_original_decision_receipt_without_original_cpu_execution(row):
    number = row['key_index'] + 1
    if row.get('flavour_present') is False:
        f = None
    else:
        kind = ('TEXT', 'ICON', 'DYNAMIC', 'FONT')[row['tag_type']]
        f = flavour(tag_type=kind, tag_value=row['tag_value'],
                    bitmap=bitmap() if kind in ('DYNAMIC', 'FONT') and row['dynamic_data'] else None)
    # The retained original fragment begins after role/owner/cache resolution.
    # Scene-modify selects that same fragment without introducing a missing
    # primary bitmap-load prerequisite. Invalid active image IDs remain outside
    # the portable inner command compiler, even though the original forwarded them.
    keys = [key(i + 1, role='scene_modify', target_state='missing', flavour=None) for i in range(number - 1)]
    keys.append(key(number, role='scene_modify', flavour=f))
    expected = row['result']['actions'][0]['target']
    if expected == 'flavour' and f['tag_type'] != 'TEXT':
        with pytest.raises(DltUnitDeliveryError):
            compile_unit_delivery(request(keys=keys))
        return
    plan = compile_unit_delivery(request(keys=keys)).as_dict()
    assert plan['keys'][-1]['action'] == ('broadcast' if expected == 'flavour' else
                                        'clear_without_flavour' if f is None else 'clear_retained_flavour')
    if expected == 'unit':
        clear = next(op for op in plan['operations'] if op['kind'] == 'clear')
        assert clear['command'] == f'label clear 254/56 10 {number}'
        report = assess_unit_delivery(plan, outcomes(plan))
        assert report['per_key_cache_marked'][str(number)] is (True if f is not None else None)
