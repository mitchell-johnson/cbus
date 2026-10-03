"""Literal whole-parent dual-key callback and owner/replay regressions."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from cbus_toolkit.edlt import EdltError, _field, _render
from cbus_toolkit.edlt_parent_metadata import plan_native_parent_metadata
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction, normalize_operations
from tests.test_edlt import Session
from tests.test_edlt_parent_cache_panels import fixture
from tests.test_edlt_parent_metadata import MetadataClient
from tests.test_edlt_scene import prepared

LITERALS = json.loads(Path(__file__).with_name('dual-key-public-literals.json').read_text())
CASES = LITERALS['positive_profiles']
UNIT = '//TEST/254/p/20'


def model(case):
    spec = fixture()
    editor = EdltParentTransaction(spec)
    source = editor.snapshot(prepared(spec.defaults()))
    source['NavWidgetType'] = (1,)
    source['UseBigIcon'] = (1,)
    # A retained active widget7 cannot follow the source Widget6 terminator.
    source[_field(6)] = (0,)
    for slot, record in case['source_records'].items():
        for offset, value in enumerate(record):
            source[_field(int(slot), offset)] = (value,)
        source[f'Widget{slot}RestoreLevel'] = (213,)
    source[_field(max(map(int, case['source_records'])) + 1)] = (255,)
    for index, row in case['source_rows_hex'].items():
        source['StaticTextString' + index] = tuple(bytes.fromhex(row))
    client = MetadataClient(spec)
    client.applications[56]['groups'][0] = {'oid': '00000000-0000-0000-0000-000000000600', 'tag': 'Declared group', 'levels': ()}
    client.values = {name: _render(value) for name, value in source.items()}
    client.saved_values = deepcopy(client.values)
    return editor, client, source


def native(case):
    editor, client, source = model(case)
    return editor, client, source, plan_native_parent_metadata(
        client.xml(), UNIT, source, editor, case['operations'])


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_complete_records_and_static_rows_follow_literal_callback_phase(case):
    editor, client, source, plan = native(case)
    controls, terminal = plan.parent_plan.after_controls, plan.parent_plan.before_save
    for slot, record in case.get('expected_controls_records', case['expected_records']).items():
        assert bytes(controls[_field(int(slot), i)][0] for i in range(32)) == bytes(record)
    for slot, record in case['expected_records'].items():
        assert bytes(terminal[_field(int(slot), i)][0] for i in range(32)) == bytes(record)
        assert terminal[f'Widget{slot}RestoreLevel'] == (case['restore_levels'][slot],)
    for index, literal in case['expected_rows_hex'].items():
        assert bytes(terminal['StaticTextString' + index]).hex() == literal
    document = plan.parent_plan.as_dict()
    assert document['execution_counts']['terminal_crc_passes'] == 1
    assert len(plan.parent_plan.dual_key_control_bindings) == sum('dual_key_controls' in row for row in case['operations'])
    assert all(row['dual_key_controls']['pending'] is False for row in document['operation_results'] if 'dual_key_controls' in row)
    assert client.commands == []


@pytest.mark.parametrize('family', ('timer', 'shutter', 'room-courtesy'))
def test_retained_readonly_never_runs_ordinary_field_repairs(family):
    case = next(row for row in CASES if row['id'] == family + '-readonly')
    _, _, source, plan = native(case)
    after = plan.parent_plan.after_controls
    assert all(after[_field(7, i)] == source[_field(7, i)] for i in range(32))
    row = plan.parent_plan.as_dict()['operation_results'][0]
    assert row['dual_key_control_base']['mode'] == 'retained callbacks without ordinary mutation getters'
    assert row['dual_key_control_base']['converted'] is False
    assert row['reserved_widget_slots'] == [7]
    # Each family has an invalid raw mode that is preserved by view-only use.
    assert after[_field(7, 7)] == source[_field(7, 7)]


def test_canonical_apply_requires_exact_binding_and_never_writes_a_parameter_twice():
    case = next(row for row in CASES if row['id'] == 'mixed-three-callbacks')
    editor, _, source, native_plan = native(case)
    plan = native_plan.parent_plan
    session = Session(editor.spec); session.current = dict(source)
    result = editor.apply(session, plan)
    assert result['verified'] is True
    assert len(session.calls) == len({name for name, _value in session.calls})
    copied = replace(plan, dual_key_control_bindings=(replace(plan.dual_key_control_bindings[0]), *plan.dual_key_control_bindings[1:]))
    with pytest.raises(EdltError, match='issued|issuer|owner'):
        editor.apply(session, copied)


@pytest.mark.parametrize('mutation', ('owner', 'number', 'widget', 'source'))
def test_original_capability_cannot_be_rebound_to_another_parent_context(mutation):
    case = next(row for row in CASES if row['id'] == 'timer-callbacks')
    editor, _, source, native_plan = native(case)
    binding = native_plan.parent_plan.dual_key_control_bindings[0]
    if mutation == 'owner': binding = replace(binding, _owner=EdltParentTransaction(editor.spec))
    elif mutation == 'number': binding = replace(binding, operation_number=2)
    elif mutation == 'widget': binding = replace(binding, widget=8)
    else:
        source = {**source, _field(1, 4): (123,)}
    with pytest.raises(EdltError, match='issued|issuer|owner|binding|source|context|snapshot'):
        editor.plan(source, metadata=native_plan.cache,
            operations=native_plan.parent_plan.operations, _dual_key_control_bindings=(binding,))


@pytest.mark.parametrize('case', LITERALS['refusal_profiles'], ids=lambda case: case['id'])
def test_caller_state_is_rejected_by_the_shared_preconnection_normalizer(case):
    with pytest.raises(EdltError, match='Unsupported dual-key callback'):
        normalize_operations(case['operations'])


def test_manual_metadata_cannot_issue_control_callbacks():
    case = next(row for row in CASES if row['id'] == 'shutter-callbacks')
    editor, _, source, native_plan = native(case)
    with pytest.raises(EdltError, match='owner-issued'):
        editor.plan(source, metadata=native_plan.cache, operations=case['operations'])


def test_old_ordinary_timer_group_requirement_is_unchanged():
    with pytest.raises(EdltError, match='group'):
        normalize_operations([{'op':'timer','page':1,'position':2}, {'op':'activation'}])


def test_label_callbacks_share_full_retained_names_with_numeric_owners():
    case = deepcopy(next(row for row in CASES if row['id'] == 'mixed-three-callbacks'))
    text = 'Retained wide ' + 'é' * 40
    for op in case['operations'][:2]:
        op['label_controls'] = [{'target':'label','type':3,'events':[
            {'event':'input','text':text},{'event':'enter'}]}]
    _editor, _client, _source, plan = native(case)
    after = plan.parent_plan.after_controls
    assert after[_field(7, 17)] == after[_field(8, 10)] == (63,)
    assert bytes(after['StaticTextString63']) == (text.encode('utf8')[:63] + b'\0').ljust(64,b'\0')
    assert len(plan.parent_plan.app_group_label_bindings) == 2
    assert len(plan.parent_plan.dual_key_control_bindings) == 3
    rows = plan.parent_plan.as_dict()['operation_results']
    assert rows[1]['label_controls']['allocations'][0]['reused'] is True


def test_pending_label_history_cannot_be_committed_by_later_numeric_callbacks():
    case = deepcopy(next(row for row in CASES if row['id'] == 'timer-callbacks'))
    case['operations'][0]['label_controls'] = [{'target':'label','type':3,'events':[
        {'event':'input','text':'Still pending'}]}]
    editor, client, source = model(case)
    with pytest.raises(EdltError, match='pending'):
        plan_native_parent_metadata(client.xml(), UNIT, source, editor, case['operations'])
    assert client.commands == []
    assert client.values == {name:_render(value) for name,value in source.items()}


def test_conversion_never_invents_a_group_for_callback_only_json():
    case = deepcopy(next(row for row in CASES if row['id'] == 'shutter-default-then-callbacks'))
    del case['operations'][0]['group']
    editor, client, source = model(case)
    with pytest.raises(EdltError, match='conversion requires explicit group'):
        plan_native_parent_metadata(client.xml(), UNIT, source, editor, case['operations'])
    assert client.commands == []


def test_timer_conversion_uses_source_default_flags_without_hidden_getters():
    retained = next(row for row in CASES if row['id'] == 'timer-readonly')
    converted = next(row for row in CASES if row['id'] == 'timer-default-then-callbacks')
    for case, expected, mode in ((retained, [True] * 4, 'constructor'),
                                 (converted, [False] * 4, 'source-default')):
        _, _, _, plan = native(case)
        binding = plan.parent_plan.dual_key_control_bindings[0]
        assert binding.as_dict()['model_initialization'] == mode
        receipt = plan.parent_plan.as_dict()['operation_results'][0]['dual_key_controls']
        assert receipt['state']['source_editable_flags'] == expected


def test_group_omission_cannot_turn_invalid_placement_into_an_unowned_record():
    case = deepcopy(next(row for row in CASES if row['id'] == 'timer-readonly'))
    case['operations'][0]['position'] = 99
    editor, client, source = model(case)
    with pytest.raises(EdltError, match=r'^Position must be an integer in 1\.\.4$'):
        plan_native_parent_metadata(client.xml(), UNIT, source, editor, case['operations'])
    assert client.commands == []
