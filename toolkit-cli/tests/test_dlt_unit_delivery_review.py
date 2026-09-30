"""Independent whole-unit DLT branch, failure, cache and replay review."""
from copy import deepcopy

import pytest

from cbus_toolkit.dlt_unit_delivery import (assess_unit_delivery, compile_unit_delivery,
                                          validate_unit_delivery_plan)


def flavour(**changes):
    result = {'format': 'cbus-classic-dlt-broadcast-request-v1', 'project': 'LAB',
              'network': 254, 'application': 56, 'application_oid': None,
              'group': 20, 'level': None, 'language': 1, 'variant': 1,
              'tag_type': 'TEXT', 'tag_value': 'Kitchen', 'already_broadcast': False,
              'bitmap': None}
    result.update(changes)
    return result


def key(number=1, **changes):
    result = {'key': number, 'kfi': number, 'role': 'ordinary',
              'target_state': 'present', 'flavour': flavour()}
    result.update(changes)
    return result


def request(**changes):
    result = {'format': 'cbus-classic-dlt-unit-delivery-request-v1',
              'project': 'LAB', 'network': 254, 'unit_application': 56, 'unit_address': 20,
              'default_language': 1, 'save_labels': True, 'transfer': False,
              'block_dynamic_updates': True, 'kfi_enabled': False,
              'reblock_session_open': True, 'keys': [key()]}
    result.update(changes)
    return result


def compile_plan(**changes):
    return compile_unit_delivery(request(**changes)).as_dict()


def operation(plan, identifier):
    return next(row for row in plan['operations'] if row['id'] == identifier)


def returned(plan, identifier):
    return {'id': identifier, 'operation_sha256': operation(plan, identifier)['operation_sha256'],
            'outcome': 'returned'}


def raised(plan, identifier, error_class='cgate_command'):
    return {**returned(plan, identifier), 'outcome': 'raised',
            'error_class': error_class, 'message': 'Synthetic command failure'}


def uncertain(plan, identifier):
    return {**returned(plan, identifier), 'outcome': 'uncertain', 'reason': 'timeout'}


def assess(plan, *operations):
    return assess_unit_delivery(plan, {'format': 'cbus-classic-dlt-unit-delivery-outcomes-v1',
                                      'plan_sha256': plan['plan_sha256'], 'operations': list(operations)})


def dynamic_key(number=1, **changes):
    return key(number, flavour=flavour(tag_type='DYNAMIC', tag_value='258',
                                     bitmap={'width': 1, 'data_hex': '0000'}), **changes)


def assert_no_execution_or_acceptance(result):
    for field in ('io_performed', 'native_accepted', 'device_verified', 'rendering_verified',
                  'persistence_verified'):
        assert result[field] is False
    assert result['recovery']['automatic_retry'] is False
    assert result['recovery']['automatic_resume'] is False
    assert result['recovery']['physical_state_known'] is False
    assert result['outcome_provenance'] == 'caller-supplied; not independently observed or authenticated'


@pytest.mark.parametrize('changes', [
    {'network': True}, {'unit_application': 56.0}, {'unit_address': '20'},
    {'default_language': 0}, {'default_language': 256}, {'default_language': True},
    {'save_labels': 1}, {'transfer': 0}, {'block_dynamic_updates': 1.0},
    {'kfi_enabled': 'no'}, {'reblock_session_open': 1},
    {'project': 'LAB\nPROJECT USE OTHER'}, {'extra': 'injected'},
])
def test_request_identity_and_control_types_are_exact(changes):
    with pytest.raises(ValueError):
        compile_unit_delivery(request(**changes))


@pytest.mark.parametrize('keys', [
    [key(0)], [key(9)], [key(True)], [key(1.0)], [key(1), key(1)], [key(2)],
    [key(i) for i in range(1, 10)], [key(kfi=True)], [key(kfi=1.0)],
    [key(kfi='1')], [key(kfi=-1)], [key(kfi=16)],
    [key(role='unknown')], [key(target_state='unknown')],
])
def test_key_numbering_and_kfi_reject_aliases_and_whole_unit_clear_expansion(keys):
    with pytest.raises(ValueError):
        compile_unit_delivery(request(keys=keys))


@pytest.mark.parametrize('changes', [
    {'project': 'OTHER'}, {'network': 253}, {'language': 2},
])
def test_resolved_flavour_cannot_escape_bound_project_network_or_language(changes):
    with pytest.raises(ValueError):
        compile_unit_delivery(request(keys=[key(flavour=flavour(**changes))]))


@pytest.mark.parametrize('role', ['ordinary', 'scene_modify'])
def test_present_group_255_contradicts_original_unused_group_predicate(role):
    with pytest.raises(ValueError):
        compile_plan(keys=[key(role=role, flavour=flavour(group=255))])


def test_scene_level_does_not_inherit_unused_group_predicate():
    plan = compile_plan(keys=[key(role='scene', flavour=flavour(application=202, group=255, level=42))])
    assert operation(plan, 'key.1.broadcast.1')['command'].startswith('TRIGGER LABEL //LAB/254/202 1 255 42 F0 ')


def test_canonical_plan_rejects_metadata_and_typed_request_forgery_without_mutation():
    source = request()
    model = compile_unit_delivery(source)
    saved = model.as_dict()
    source['keys'][0]['flavour']['tag_value'] = 'Changed caller input'
    assert model.as_dict() == saved
    copies = []
    changed = deepcopy(saved)
    changed['request']['network'] = 254.0
    copies.append(changed)
    changed = deepcopy(saved)
    changed['request']['save_labels'] = 1
    copies.append(changed)
    changed = deepcopy(saved)
    changed['operations'][0]['extra'] = 'injected'
    copies.append(changed)
    copies.append({**saved, 'plan_sha256': '0' * 64})
    copies.append({**saved, 'extra': 'injected'})
    for forged in copies:
        with pytest.raises(ValueError):
            validate_unit_delivery_plan(forged)
    assert validate_unit_delivery_plan(saved).as_dict() == saved


@pytest.mark.parametrize('failed', [raised, uncertain])
def test_initial_save_failure_or_uncertainty_prevents_after_save_and_final_save(failed):
    plan = compile_plan(kfi_enabled=True)
    result = assess(plan, failed(plan, 'initial_save'))
    assert result['status'] == ('aborted' if failed is raised else 'uncertain')
    assert result['reached_operations'] == ['initial_save']
    assert result['stopped_at'] == 'initial_save'
    assert result['initial_save_returned'] is False and result['reblock_returned'] is False
    assert result['predicted_enable_dynamic_labels'] is None
    assert not any(row['event'] == 'reset_broadcast' for row in result['trace'])
    assert_no_execution_or_acceptance(result)
    with pytest.raises(ValueError):
        assess(plan, failed(plan, 'initial_save'), returned(plan, 'kfi'))


@pytest.mark.parametrize('failed', [raised, uncertain])
@pytest.mark.parametrize('session_open', [False, True])
def test_final_save_failure_retains_label_progress_but_not_reblock_or_cleanup_claim(failed, session_open):
    plan = compile_plan(reblock_session_open=session_open)
    final = operation(plan, 'reblock')
    assert final['saves_existing_session'] is True and final['timeout_ms'] == 30000
    assert final['sequence'] == ([] if session_open else ['LOCK', 'START', 'LOAD']) + [
        'SET EnableDynamicLabels=0', 'SAVE']
    assert final['owned_cleanup'] == ([] if session_open else ['END', 'UNLOCK'])
    result = assess(plan, returned(plan, 'initial_save'), returned(plan, 'key.1.broadcast.1'),
                    failed(plan, 'reblock'))
    assert result['initial_save_returned'] is True and result['reblock_returned'] is False
    assert result['per_key_cache_marked'] == {'1': True}
    assert result['predicted_enable_dynamic_labels'] is None
    assert result['reblock_cleanup_verified'] is False
    assert result['stopped_at'] == 'reblock'
    assert_no_execution_or_acceptance(result)


def test_dynamic_first_command_exception_skips_icon_but_continues_later_key_and_reblock():
    plan = compile_plan(keys=[dynamic_key(), key(2)])
    prefix = [returned(plan, 'initial_save'), raised(plan, 'key.1.broadcast.1')]
    result = assess(plan, *prefix, returned(plan, 'key.2.broadcast.1'), returned(plan, 'reblock'))
    assert result['status'] == 'completed_with_label_errors'
    assert result['skipped_operations'] == ['key.1.broadcast.2']
    assert result['per_key_cache_marked'] == {'1': False, '2': True}
    assert result['predicted_enable_dynamic_labels'] == 0
    assert result['collected_label_errors'][0]['operation'] == 'key.1.broadcast.1'
    assert_no_execution_or_acceptance(result)
    with pytest.raises(ValueError):
        assess(plan, *prefix, returned(plan, 'key.1.broadcast.2'))


def test_dynamic_second_exception_keeps_mark_and_continues_but_generic_exception_aborts():
    plan = compile_plan(keys=[dynamic_key(), key(2)])
    prefix = [returned(plan, 'initial_save'), returned(plan, 'key.1.broadcast.1')]
    result = assess(plan, *prefix, raised(plan, 'key.1.broadcast.2'),
                    returned(plan, 'key.2.broadcast.1'), returned(plan, 'reblock'))
    assert result['status'] == 'completed_with_label_errors'
    assert result['per_key_cache_marked'] == {'1': True, '2': True}
    generic = raised(plan, 'key.1.broadcast.2', 'other')
    aborted = assess(plan, *prefix, generic)
    assert aborted['status'] == 'aborted' and aborted['stopped_at'] == 'key.1.broadcast.2'
    assert aborted['per_key_cache_marked']['1'] is True
    assert aborted['collected_label_errors'] == [] and aborted['reblock_returned'] is False
    with pytest.raises(ValueError):
        assess(plan, *prefix, generic, returned(plan, 'key.2.broadcast.1'))


def test_label_uncertainty_never_uses_the_known_exception_continuation_path():
    plan = compile_plan(keys=[dynamic_key(), key(2)])
    for first_returned in (False, True):
        current = 'key.1.broadcast.2' if first_returned else 'key.1.broadcast.1'
        prefix = [returned(plan, 'initial_save')]
        if first_returned:
            prefix.append(returned(plan, 'key.1.broadcast.1'))
        result = assess(plan, *prefix, uncertain(plan, current))
        assert result['status'] == 'uncertain' and result['stopped_at'] == current
        assert result['per_key_cache_marked']['1'] is (True if first_returned else None)
        assert result['reblock_returned'] is False
        assert_no_execution_or_acceptance(result)
        with pytest.raises(ValueError):
            assess(plan, *prefix, uncertain(plan, current), returned(plan, 'key.2.broadcast.1'))


def test_missing_flavour_clear_is_outside_catch_but_retained_clear_is_inside():
    for retained in (False, True):
        plan = compile_plan(keys=[key(flavour=flavour(tag_value='') if retained else None), key(2)])
        clear = operation(plan, 'key.1.clear')
        assert clear['command'] == 'label clear 254/56 20 1'
        assert clear['relative_project_context'] == 'LAB'
        assert clear['error_policy'] == ('collect_cgate_command' if retained else 'abort')
        prefix = [returned(plan, 'initial_save'), raised(plan, 'key.1.clear')]
        result = assess(plan, *prefix)
        assert result['per_key_cache_marked']['1'] is (False if retained else None)
        assert result['status'] == ('awaiting_outcomes' if retained else 'aborted')
        if retained:
            completed = assess(plan, *prefix, returned(plan, 'key.2.broadcast.1'), returned(plan, 'reblock'))
            assert completed['status'] == 'completed_with_label_errors'
        else:
            with pytest.raises(ValueError):
                assess(plan, *prefix, returned(plan, 'reblock'))


def test_each_shared_flavour_is_reset_and_reemitted_without_deduplication():
    same = flavour(already_broadcast=True)
    plan = compile_plan(keys=[key(flavour=same), key(2, flavour=same)])
    first = operation(plan, 'key.1.broadcast.1')
    second = operation(plan, 'key.2.broadcast.1')
    assert first['command'] == second['command'] and first['id'] != second['id']
    assert [row['key'] for row in plan['events'] if row['event'] == 'reset_broadcast'] == [1, 2]
    partial = assess(plan, returned(plan, 'initial_save'), returned(plan, first['id']))
    assert partial['per_key_cache_marked'] == {'1': True, '2': False}
    assert partial['next_operation'] == second['id']
    failed_second = assess(plan, returned(plan, 'initial_save'), returned(plan, first['id']),
                           raised(plan, second['id']), returned(plan, 'reblock'))
    assert failed_second['per_key_cache_marked'] == {'1': True, '2': False}
    assert 'no alias reconstruction' in failed_second['cache_scope']


def test_kfi_precedes_gate_and_uses_ordered_zero_padding_with_relative_context():
    plan = compile_plan(keys=[key(kfi=15), key(2, kfi=0)], save_labels=False, transfer=False, kfi_enabled=True)
    assert [row['id'] for row in plan['operations']] == ['initial_save', 'kfi', 'reblock']
    kfi = operation(plan, 'kfi')
    assert kfi['values'] == [15, 0, 0, 0, 0, 0, 0, 0]
    assert kfi['command'] == 'label kfiset 254/56 20 15 0 0 0 0 0 0 0'
    assert plan['relative_commands_require_active_project'] == 'LAB'
    assert plan['active_project_binding_verified'] is False
    result = assess(plan, returned(plan, 'initial_save'), raised(plan, 'kfi'))
    assert result['status'] == 'aborted' and result['collected_label_errors'] == []
    assert result['reblock_returned'] is False
    assert not any(row['event'] == 'reset_label_errors' for row in result['trace'])
    override = compile_plan(save_labels=False, transfer=True)
    assert 'key.1.broadcast.1' in [row['id'] for row in override['operations']]


def test_unicode_suppression_marks_after_initial_save_without_a_label_operation():
    plan = compile_plan(keys=[key(flavour=flavour(tag_value='A' * 14 + '漢'))])
    assert [row['id'] for row in plan['operations']] == ['initial_save', 'reblock']
    untouched = assess(plan)
    assert untouched['per_key_cache_marked']['1'] is not True
    partial = assess(plan, returned(plan, 'initial_save'))
    assert partial['per_key_cache_marked'] == {'1': True}
    assert partial['next_operation'] == 'reblock'
    assert_no_execution_or_acceptance(partial)


def test_outcomes_are_exact_typed_hash_bound_and_reachable_with_no_raw_response_inference():
    plan = compile_plan()
    initial = returned(plan, 'initial_save')
    bad_rows = [
        [{**initial, 'operation_sha256': '0' * 64}], [initial, initial],
        [{**initial, 'id': True}], [{**initial, 'responses': ['200 OK']}],
        [{**raised(plan, 'initial_save'), 'error_class': 'unknown'}],
        [{**raised(plan, 'initial_save'), 'message': 'line\nbreak'}],
        [{**uncertain(plan, 'initial_save'), 'reason': True}],
        [returned(plan, 'key.1.broadcast.1')],
    ]
    for rows in bad_rows:
        with pytest.raises(ValueError):
            assess(plan, *rows)
    with pytest.raises(ValueError):
        assess_unit_delivery(plan, {'format': 'cbus-classic-dlt-unit-delivery-outcomes-v1',
                                   'plan_sha256': '0' * 64, 'operations': [initial]})
