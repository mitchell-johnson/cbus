"""Source-backed ordered selector views and retained global form callbacks."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_manager import EdltSceneManager, SceneManagerCache
from cbus_toolkit.edlt_scene_selector_views import action_choices, trigger_choices
from tests.test_edlt import Session
from tests.test_edlt_lifecycle import fixture


VECTOR_PATH = Path(__file__).resolve().parents[1] / 'research/fixtures/edlt-scene-selector-vectors.json'
VECTOR = json.loads(VECTOR_PATH.read_text())


def selector_fixture(override=None, *, metadata=None):
    spec = fixture()
    editor = EdltSceneManager(spec)
    session = Session(spec)
    values = {**session.current, **VECTOR['fixture']['consumer_pp_parameters']}
    cache = deepcopy(VECTOR['fixture']['cache']) if metadata is None else deepcopy(metadata)
    if override == 'explicit255':
        cache['trigger_list']['groups'].insert(0, {
            'address': 255, 'name': 'Group 255',
            'formatted_display': '255 - Group 255'})
        cache['action_lists'].append({'group': 255, 'complete': True, 'actions': [
            {'address': 255, 'name': 'Unused level', 'formatted_display': '255 - Unused level'}]})
    elif override == 'secondary-unused':
        values['SecondaryApplication'] = '0xff'
    elif override == 'missing-actions-42':
        cache['action_lists'] = [row for row in cache['action_lists'] if row['group'] != 42]
    elif override is not None:
        raise AssertionError(override)
    return editor, editor.load(values, metadata=cache)


def scene_rows(state):
    return [{'scene': s.slot, 'application_selector': s.primary_secondary,
             'can_edit': s.can_edit, 'raw_trigger': s.raw_trigger, 'raw_action': s.raw_action,
             'name_index': s.name_index, 'name': state.names_view()[s.slot - 1]['scene_name'],
             'label_value_index': s.label_value_index,
             'dynamic_labels': [row.as_dict() for row in s.dynamic_labels],
             'items': [row.as_dict() for row in s.items]} for s in state.scenes]


@pytest.mark.parametrize('case', VECTOR['cases'], ids=lambda row: row['name'])
def test_independent_literal_scene_callback_and_complete_pp(case):
    editor, state = selector_fixture(case.get('cache_override'))
    before = state.as_dict()
    outcome = editor.edit(state, operations=case['operations'])
    assert scene_rows(outcome.state) == case['expected_scenes_after_callbacks']
    composition = editor.prepare_composition(outcome.state)
    assert scene_rows(composition.terminal) == case['expected_scenes_after_before_save']
    assert bytes(composition.fields['SceneBucket']).hex() == case['expected_scene_bucket_hex']
    assert composition.fields['SceneCount'] == (case['expected_scene_count'],)
    assert [composition.fields[f'Scene{i}StartAddress'][0] for i in range(1, 9)] == case['expected_scene_starts']
    staged = {**state.loaded.after_load, **composition.fields}
    assert [bytes(staged[f'StaticTextString{i}']).hex() for i in range(64)] == case['expected_static_rows_hex']
    assert state.as_dict() == before
    controls = [row['scene_selector_control'] for row in outcome.as_dict()['operation_results']
                if 'scene_selector_control' in row]
    if controls:
        observed = controls[-1]['state']
        assert {key: observed[key] for key in case['expected_control_binding']} == case['expected_control_binding']
        if observed['bound_scene'] is None:
            assert observed['view'] == {}
        else:
            assert observed['view']['application_choices'] == case['expected_application_choices']
            assert observed['view']['trigger_choices'] == case['expected_trigger_choices']
        assert controls[-1]['implicit_read_value_inferred'] is False
        assert controls[-1]['host_gui_executed'] is False


@pytest.mark.parametrize('case', VECTOR['refusals'], ids=lambda row: row['name'])
def test_literal_refusal_preserves_prior_issued_state(case):
    editor, state = selector_fixture(case.get('cache_override'))
    before = state.as_dict()
    with pytest.raises(EdltError):
        editor.edit(state, operations=case['operations'])
    assert state.as_dict() == before
    editor.retained_names(state)


def test_actual_order_no_synthetic_trigger_and_duplicate_action_identity():
    editor, state = selector_fixture()
    outcome = editor.selector_view(state, scene=1)
    view = outcome.as_dict()['view']
    expected = VECTOR['fixture']['exact_source_choices']
    assert view['application_choices'] == expected['applications']
    assert view['trigger_choices'] == expected['triggers']
    assert view['action_choices'] == expected['actions_by_group']['42']
    assert view['dynamic_labels'] == expected['dynamic_labels_by_level']['42/7']
    assert [row['value'] for row in view['trigger_choices']] == [44, 42, 43, 45]
    assert view['action_selector'] == view['raw_action_selector'] == 7
    assert view['action_getter_observed'] is True
    assert view['automatic_host_scheduling_inferred'] is False
    assert state.selector_control is None


def test_valid_action_getter_preserves_old_labels_then_explicit_handler_refreshes():
    editor, state = selector_fixture()
    changed = editor.edit(state, operations=[{'op': 'set-trigger', 'scene': 1, 'group': 43}]).state
    viewed = editor.selector_view(changed, scene=1)
    view = viewed.as_dict()['view']
    assert view['action_selector'] == 7
    assert view['dynamic_labels'] == VECTOR['fixture']['exact_source_choices']['dynamic_labels_by_level']['42/7']
    refreshed = editor.edit(viewed.state, operations=[{'op': 'scene-selector-control', 'scene': 1, 'events': [
        {'event': 'scene-current-changed', 'current': True}, {'event': 'trigger-current-changed'}]}])
    control = refreshed.as_dict()['operation_results'][0]['scene_selector_control']
    assert control['state']['view']['dynamic_labels'] == VECTOR['fixture']['exact_source_choices']['dynamic_labels_by_level']['43/7']
    actions = [row['action'] for row in control['binding_callbacks'] if row['event'] == 'trigger-current-changed']
    assert actions == ['ClearActionBindings', 'ResolveAvailableActionSelectors', 'SetActionDataSource',
                       'BindActionSelectedValue', 'ActionSelectorGetterThenRefreshDynamicLables', 'RefreshDynamicLables']


def test_disabled_getter_distinguishes_returned_minus_one_from_retained_raw_action():
    editor, state = selector_fixture('explicit255')
    changed = editor.edit(state, operations=[{'op': 'set-trigger', 'scene': 1, 'group': 255}]).state
    viewed = editor.selector_view(changed, scene=1)
    view = viewed.as_dict()['view']
    assert view['action_selector'] == -1
    assert view['raw_action_selector'] == 7
    assert viewed.state.scenes[0].raw_action == 7
    assert view['action_choices'] == []
    assert view['dynamic_labels'] == VECTOR['fixture']['exact_source_choices']['dynamic_labels_by_level']['42/7']


def test_global_stale_binding_survives_across_edit_calls_and_outer_scene():
    editor, state = selector_fixture()
    first = editor.edit(state, operations=[{'op': 'scene-selector-control', 'scene': 1, 'events': [
        {'event': 'scene-current-changed', 'current': True},
        {'event': 'scene-current-changed', 'current': False}]}]).state
    second = editor.edit(first, operations=[{'op': 'scene-selector-control', 'scene': 2, 'events': [
        {'event': 'level-current-changed', 'value': 1, 'choice_index': 2, 'choice_identity': 'action:202/42/1'},
        {'event': 'label-selected', 'index': 3, 'choice_identity': 'label:202/42/1/3'}]}]).state
    assert second.scenes[0].raw_action == 1 and second.scenes[0].label_value_index == 3
    assert second.scenes[1].raw_action == 9 and second.scenes[1].label_value_index == 0
    assert second.selector_control.current_scene is None
    assert second.selector_control.bound_scene == 1
    assert first.scenes[0].raw_action == 7


def test_old_bound_action_objects_remain_until_explicit_trigger_handler():
    editor, state = selector_fixture()
    outcome = editor.edit(state, operations=[{'op': 'scene-selector-control', 'scene': 1, 'events': [
        {'event': 'scene-current-changed', 'current': True},
        {'event': 'trigger-selected', 'value': 43, 'choice_index': 2, 'choice_identity': 'trigger:202/43'},
        {'event': 'action-selected', 'value': 7, 'choice_index': 0, 'choice_identity': 'action:202/42/7'}]}])
    view = outcome.state.selector_control.as_dict()['view']
    assert view['action_choices'] == VECTOR['fixture']['exact_source_choices']['actions_by_group']['42']
    assert view['dynamic_labels'] == VECTOR['fixture']['exact_source_choices']['dynamic_labels_by_level']['43/7']
    assert outcome.state.scenes[0].raw_trigger == 43


def test_later_outer_lifecycle_facts_cannot_enter_actual_choice_inventory():
    cache = deepcopy(VECTOR['fixture']['cache'])
    cache['application_cache']['lifecycle']['groups'].append({
        'application': 202, 'group': 99, 'exists': True, 'levels': [99]})
    row = next(row for row in cache['application_cache']['lifecycle']['groups'] if row['application'] == 202 and row['group'] == 42)
    row['levels'].append(99)
    cache['application_cache']['group_lists'][2]['complete'] = False
    editor, state = selector_fixture(metadata=cache)
    changed = editor.edit(state, operations=[{'op': 'set-trigger', 'scene': 1, 'group': 99}]).state
    viewed = editor.selector_view(changed, scene=1)
    assert viewed.state.scenes[0].raw_trigger == 255
    assert viewed.as_dict()['view']['action_selector'] == -1
    assert 99 not in [row['value'] for row in action_choices(state.cache, 42)]
    assert 99 not in [row['value'] for row in trigger_choices(state.cache)]


def test_before_save_cannot_borrow_later_level_zero_from_outer_lifecycle():
    cache = deepcopy(VECTOR['fixture']['cache'])
    actual = next(row for row in cache['action_lists'] if row['group'] == 44)
    actual['actions'] = [row for row in actual['actions'] if row['address'] != 0]
    # The declared outer lifecycle still contains0 (a later parent panel's
    # object); the original position's complete action collection does not.
    editor, state = selector_fixture(metadata=cache)
    edited = editor.edit(state, operations=[{'op': 'set-trigger', 'scene': 1, 'group': 44},
        {'op': 'get-selector-view', 'scene': 1}]).state
    assert edited.scenes[0].raw_action == -1
    assert editor.validate(edited).state.scenes[0].raw_action == -1
    composed = editor.prepare_composition(edited)
    assert composed.terminal.scenes[0].raw_action == -1
    assert composed.fields['SceneBucket'][3] == 255
    assert state.cache.application_cache.lifecycle.find(202, 44).levels == (9, 0)


def test_binding_available_actions_does_not_invoke_action_getter_implicitly():
    editor, state = selector_fixture()
    changed = editor.edit(state, operations=[{'op': 'set-trigger', 'scene': 1, 'group': 44}]).state
    bound = editor.edit(changed, operations=[{'op': 'scene-selector-control', 'scene': 1,
        'events': [{'event': 'scene-current-changed', 'current': True}]}]).state
    assert bound.scenes[0].raw_action == 7
    view = bound.selector_control.as_dict()['view']
    assert view['action_getter_observed'] is False
    assert view['action_choices'] == VECTOR['fixture']['exact_source_choices']['actions_by_group']['44']
    assert view['dynamic_labels'] == VECTOR['fixture']['exact_source_choices']['dynamic_labels_by_level']['42/7']
    observed = editor.selector_view(bound, scene=1)
    assert observed.state.scenes[0].raw_action == -1
    assert observed.as_dict()['view']['dynamic_labels'] == []


def test_copy_and_paste_preserve_source_property_and_target_label_semantics():
    editor, state = selector_fixture()
    edited = editor.edit(state, operations=[{'op': 'scene-selector-control', 'scene': 1,
        'events': [{'event': 'scene-current-changed', 'current': True}]},
        {'op': 'copy', 'scene': 1}, {'op': 'paste', 'scene': 2}]).state
    assert edited.clipboard.dynamic_labels == ()
    assert (edited.scenes[1].raw_trigger, edited.scenes[1].raw_action) == (42, 7)
    # CopyFrom assigns private trigger/action fields; it does not refresh the
    # destination's prior DynamicAll object collection.
    assert [row.name for row in edited.scenes[1].dynamic_labels] == ['Nine first', 'Nine second', 'Nine third', 'Nine fourth']
    assert edited.selector_control.bound_scene == 1


def test_unconsumed_partial_choice_facts_do_not_block_no_binding_noop():
    cache = deepcopy(VECTOR['fixture']['cache'])
    cache['trigger_list']['complete'] = False
    cache['action_lists'] = []
    editor, state = selector_fixture(metadata=cache)
    edited = editor.edit(state, operations=[{'op': 'scene-selector-control', 'scene': 1,
        'events': [{'event': 'level-current-changed'}]}]).state
    assert scene_rows(edited) == scene_rows(state)
    assert edited.selector_control.bound_scene is None
    with pytest.raises(EdltError, match='actual TriggerGroups'):
        editor.selector_view(edited, scene=1)


def test_pending_scene_name_survives_selector_rebinding_and_blocks_composition():
    editor, state = selector_fixture()
    pending = editor.edit(state, operations=[{'op': 'scene-name-control', 'scene': 1,
        'events': [{'event': 'input', 'text': 'Pending'}]}]).state
    switched = editor.edit(pending, operations=[{'op': 'scene-selector-control', 'scene': 2,
        'events': [{'event': 'scene-current-changed', 'current': True}]}]).state
    assert switched.name_controls[0].pending is True
    assert switched.name_controls[0].text == 'Pending'
    assert editor.scene_name(switched, scene=1) == 'Evening'
    with pytest.raises(EdltError, match='Pending SceneName'):
        editor.prepare_composition(switched)


def test_name_callback_targets_retained_form_binding_before_commit():
    editor, state = selector_fixture()
    pending = editor.edit(state, operations=[{'op': 'scene-name-control', 'scene': 1,
        'events': [{'event': 'input', 'text': 'Pending'}]}]).state
    switched = editor.edit(pending, operations=[{'op': 'scene-selector-control', 'scene': 2,
        'events': [{'event': 'scene-current-changed', 'current': True}]}]).state
    before = switched.as_dict()
    with pytest.raises(EdltError, match='retained selector form binding'):
        editor.edit(switched, operations=[{'op': 'scene-name-control', 'scene': 1,
            'events': [{'event': 'leave'}]}])
    assert switched.as_dict() == before
    assert switched.name_controls[0].pending is True
    assert editor.scene_name(switched, scene=1) == 'Evening'
    with pytest.raises(EdltError, match='Pending SceneName'):
        editor.prepare_composition(switched)
    rebound = editor.edit(switched, operations=[{'op': 'scene-selector-control', 'scene': 1,
        'events': [{'event': 'scene-current-changed', 'current': True}]},
        {'op': 'scene-name-control', 'scene': 1, 'events': [{'event': 'leave'}]}]).state
    assert editor.scene_name(rebound, scene=1) == 'Pending'
    assert editor.scene_name(rebound, scene=2) == 'Second'
    assert rebound.name_controls[0].pending is False
    assert rebound.selector_control.bound_scene == 1
    editor.prepare_composition(rebound)


def test_disabled_name_binding_keeps_prior_target_and_fresh_owner_is_unbound():
    editor, state = selector_fixture()
    disabled = editor.edit(state, operations=[{'op': 'scene-selector-control', 'scene': 1,
        'events': [{'event': 'scene-current-changed', 'current': True},
                   {'event': 'scene-current-changed', 'current': False}]}]).state
    with pytest.raises(EdltError, match='retained selector form binding'):
        editor.edit(disabled, operations=[{'op': 'scene-name-control', 'scene': 2,
            'events': [{'event': 'input', 'text': 'Wrong target'}]}])
    assert disabled.selector_control.bound_scene == 1
    assert disabled.selector_control.controls_enabled is False
    assert editor.load(state.loaded.expected, metadata=state.cache).selector_control is None


def test_owner_and_fingerprint_protect_internal_global_state():
    editor, state = selector_fixture()
    issued = editor.edit(state, operations=[{'op': 'scene-selector-control', 'scene': 1,
        'events': [{'event': 'scene-current-changed', 'current': True}]}]).state
    forged = replace(state, selector_control=issued.selector_control)
    with pytest.raises(EdltError, match='intact scene object'):
        editor.edit(forged, operations=[])
    second, _ = selector_fixture()
    with pytest.raises(EdltError, match='intact scene object'):
        second.selector_view(issued, scene=1)
    exported = issued.as_dict()
    exported['scene_selector_control']['view']['action_choices'].clear()
    assert len(issued.selector_control.as_dict()['view']['action_choices']) == 3


def test_v1_cache_roundtrip_and_legacy_setters_remain_available():
    cache = deepcopy(VECTOR['fixture']['cache'])
    cache['format'] = 'cbus-edlt-scene-manager-cache-v1'
    del cache['trigger_list'], cache['action_lists']
    parsed = SceneManagerCache.from_dict(cache)
    assert parsed.as_dict() == cache
    editor, state = selector_fixture(metadata=cache)
    legacy = editor.edit(state, operations=[{'op': 'set-action', 'scene': 1, 'action': 1}]).state
    assert legacy.scenes[0].raw_action == 1
    with pytest.raises(EdltError, match='actual TriggerGroups'):
        editor.selector_view(state, scene=1)


@pytest.mark.parametrize('damage', ['partial-trigger', 'partial-actions', 'missing-trigger', 'foreign-action', 'unknown-field', 'duplicate-action'])
def test_new_cache_requires_explicit_consistent_bounded_facts(damage):
    cache = deepcopy(VECTOR['fixture']['cache'])
    if damage == 'partial-trigger': cache['trigger_list']['complete'] = False
    elif damage == 'partial-actions': cache['action_lists'][1]['complete'] = False
    elif damage == 'missing-trigger': cache['trigger_list']['groups'][0]['address'] = 99
    elif damage == 'foreign-action': cache['action_lists'][1]['actions'][0]['address'] = 99
    elif damage == 'unknown-field': cache['action_lists'][0]['state'] = {}
    elif damage == 'duplicate-action': cache['action_lists'][1]['actions'].append(cache['action_lists'][1]['actions'][0])
    with pytest.raises(EdltError):
        editor, state = selector_fixture(metadata=cache)
        editor.selector_view(state, scene=1)
