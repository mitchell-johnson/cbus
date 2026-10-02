"""Causal SceneManager inventories and replaced native collection bindings.

All source objects here are explicitly invented. XML is supplied by the pure
test model; no C-Gate process, Toolkit instruction or physical endpoint runs.
The assertions use literal phase inventories and callback targets, separately
from the resolver's creation receipts and final cache.
"""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from cbus_toolkit.edlt import EdltError, _render
from cbus_toolkit.edlt_display_model import EdltDisplayPreferences
from cbus_toolkit.edlt_scene_manager import EdltSceneManager, SceneManagerCache
from cbus_toolkit.edlt_scene_metadata import resolve_native_scene_metadata
from cbus_toolkit.edlt_scene_selector_views import action_choices, dynamic_label_rows
from tests.test_edlt_lifecycle import fixture
from tests.test_edlt_scene_metadata import SceneMetadataClient
from tests.test_edlt_scene_selectors import VECTOR, selector_fixture


ADDRESS_ORDER = EdltDisplayPreferences.from_registry(
    {'SortModeGroups': 1, 'SortModeLevels': 1})


def view(scene=1):
    return {'op': 'get-selector-view', 'scene': scene}


def control(*events, scene=1):
    return {'op': 'scene-selector-control', 'scene': scene,
            'events': list(events)}


BIND = {'event': 'scene-current-changed', 'current': True}
REFRESH = {'event': 'trigger-current-changed'}


def select_action(value, index, group=42):
    return {'event': 'action-selected', 'value': value, 'choice_index': index,
            'choice_identity': f'action:202/{group}/{value}'}


def model(operations, *, levels=None, source=None):
    """Complete synthetic native snapshot with four actual Trigger groups."""
    spec = fixture()
    editor = EdltSceneManager(spec)
    client = SceneMetadataClient(spec)
    actual = {42: (0, 1, 7), 43: (0, 9), 44: (0, 9), 45: ()}
    if levels is not None:
        actual.update(levels)
    original = client.applications[202]['groups']
    client.applications[202]['groups'] = {
        address: deepcopy(original[address]) for address in actual}
    for address, values in actual.items():
        group = client.applications[202]['groups'][address]
        group['tag'] = f'Trigger {address}'
        group['levels'] = values
        group['level_names'] = {value: f'Existing {address}/{value}' for value in values}
        group['level_tags'] = {
            value: tuple({'variant': variant, 'type': 'TEXT',
                          'value': f'Label {address}/{value}/{variant}'}
                         for variant in range(4)) for value in values}
    raw = {**client.values, **VECTOR['fixture']['consumer_pp_parameters']}
    if source is not None:
        raw.update(source)
    values = editor.snapshot(raw)
    client.values = {name: _render(value) for name, value in values.items()}
    xml = client.xml().replace('<Address>TEST</Address>',
                               '<Address>TEST</Address><TagName>Inventory Model</TagName>', 1)
    resolved = resolve_native_scene_metadata(
        xml, '//TEST/254/p/20', values, editor, operations,
        display_preferences=ADDRESS_ORDER)
    state = editor.load(values, metadata=resolved.cache)
    return editor, state, resolved, values


def results(outcome):
    return outcome.as_dict()['operation_results']


def actions(row):
    return [v['value'] for v in row['action_choices']]


def creations(resolved):
    return [(row['kind'], row.get('group'), row['address'], row['name'])
            for row in resolved.as_dict()['planned_creations']]


def test_later_add_does_not_enter_earlier_view_and_explicit_rebind_selects_it():
    operations = [control(BIND), view(), {'op': 'add-action-dialog', 'scene': 1},
                  view(), control(REFRESH, select_action(2, 2)), view()]
    editor, initial, resolved, _ = model(operations)
    before = initial.as_dict()
    outcome = editor.edit(initial, operations=resolved.operations)
    rows = results(outcome)
    assert actions(rows[1]['view']) == [0, 1, 7]
    assert actions(rows[3]['view']) == [0, 1, 2, 7]
    assert rows[3]['view']['dynamic_labels'] == [
        {'identity': f'label:202/42/2/{i}', 'value': i, 'name': '',
         'raw_value': str(i), 'image_present': False} for i in range(4)]
    assert actions(rows[4]['scene_selector_control']['state']['view']) == [0, 1, 2, 7]
    assert outcome.state.scenes[0].raw_action == 2
    assert creations(resolved) == [('Level', 42, 2, 'Level 2')]
    assert initial.as_dict() == before


def test_new_action_is_not_selectable_from_replaced_old_bound_collection():
    prefix = [control(BIND), {'op': 'add-action-dialog', 'scene': 1}]
    operations = [*prefix, control(select_action(2, 2))]
    with pytest.raises(EdltError, match='identity|choice'):
        model(operations)
    # A separately issued valid history establishes that the stale source
    # stays0/1/7, despite the fresh inventory now containing2.
    editor, initial, resolved, _ = model([*prefix, view()])
    first = editor.edit(initial, operations=resolved.operations[:2]).state
    assert actions(first.selector_control.as_dict()['view']) == [0, 1, 7]
    assert [row['value'] for row in action_choices(first.cache, 42)] == [0, 1, 2, 7]
    assert initial.scenes[0].raw_action == 7


def test_missing_action_getter_keeps_pre_creation_binding_until_rebind():
    operations = [{'op': 'set-trigger', 'scene': 1, 'group': 44},
                  control(BIND, REFRESH), view(), control(REFRESH, select_action(7, 1, 44))]
    editor, initial, resolved, _ = model(operations)
    outcome = editor.edit(initial, operations=resolved.operations)
    rows = results(outcome)
    first = rows[1]['scene_selector_control']
    assert actions(first['state']['view']) == [0, 9]
    assert actions(rows[2]['view']) == [0, 7, 9]
    assert actions(rows[3]['scene_selector_control']['state']['view']) == [0, 7, 9]
    assert outcome.state.scenes[0].raw_action == 7
    assert creations(resolved) == [('Level', 44, 7, 'Action Selector 7')]
    assert [row['action'] for row in first['binding_callbacks']
            if row['event'] == 'trigger-current-changed'] == [
        'ClearActionBindings', 'ResolveAvailableActionSelectors', 'SetActionDataSource',
        'BindActionSelectedValue', 'ActionSelectorGetterThenRefreshDynamicLables',
        'RefreshDynamicLables']


def test_old_group_choice_writes_through_new_raw_trigger_without_rebinding():
    operations = [control(BIND,
        {'event': 'trigger-selected', 'value': 43, 'choice_index': 1,
         'choice_identity': 'trigger:202/43'}, select_action(1, 1)), view()]
    editor, initial, resolved, _ = model(operations)
    outcome = editor.edit(initial, operations=resolved.operations)
    bound = outcome.state.selector_control.as_dict()['view']
    assert actions(bound) == [0, 1, 7]
    assert all(row['identity'].startswith('action:202/42/') for row in bound['action_choices'])
    assert (outcome.state.scenes[0].raw_trigger, outcome.state.scenes[0].raw_action) == (43, 1)
    assert bound['dynamic_labels'][0]['identity'] == 'label:202/43/1/0'
    assert actions(results(outcome)[1]['view']) == [0, 1, 9]
    assert creations(resolved) == [('Level', 43, 1, 'Action Selector 1')]


def test_unrelated_creation_replaces_every_bound_collection_generation():
    operations = [control(BIND), {'op': 'set-action', 'scene': 2, 'action': 5},
                  view(), control(select_action(1, 1)), control(REFRESH)]
    editor, initial, resolved, _ = model(operations)
    bound = editor.edit(initial, operations=resolved.operations[:1]).state
    original_token = bound._selector_bound_collection[1]
    changed = editor.edit(bound, operations=resolved.operations[1:2]).state
    assert changed._inventory_cursor.collection_generation(42) != original_token
    assert actions(changed.selector_control.as_dict()['view']) == [0, 1, 7]
    assert changed.scenes[0].dynamic_labels is bound.scenes[0].dynamic_labels
    terminal = editor.edit(changed, operations=resolved.operations[2:]).state
    assert terminal._selector_bound_collection[1] != original_token
    assert terminal._selector_bound_collection[1] == terminal._inventory_cursor.collection_generation(42)
    assert creations(resolved) == [('Level', 43, 5, 'Action Selector 5')]


def test_valid_getter_retains_historical_labels_but_setter_refreshes_objects():
    operations = [view(), {'op': 'set-action', 'scene': 2, 'action': 5},
                  view(), {'op': 'set-action', 'scene': 1, 'action': 7}, view()]
    editor, initial, resolved, _ = model(operations)
    old = initial.scenes[0].dynamic_labels
    first = editor.edit(initial, operations=resolved.operations[:3]).state
    assert first.scenes[0].dynamic_labels is old
    assert dynamic_label_rows(first.cache, first.scenes[0])[0] == {
        'identity': 'label:202/42/7/0', 'value': 0,
        'name': 'Label 42/7/0', 'raw_value': '0', 'image_present': False}
    assert first.cache.labels(42, 7) is not old
    final = editor.edit(first, operations=resolved.operations[3:]).state
    assert final.scenes[0].dynamic_labels is final.cache.labels(42, 7)
    assert final.scenes[0].dynamic_labels is not old


def test_direct_trigger_setter_does_not_create_until_the_declared_getter():
    operations = [{'op': 'set-trigger', 'scene': 1, 'group': 99}, view(), view()]
    editor, initial, resolved, _ = model(operations)
    set_state = editor.edit(initial, operations=resolved.operations[:1]).state
    assert 99 not in [row.address for row in set_state.cache.trigger_list.groups]
    viewed = editor.edit(set_state, operations=resolved.operations[1:2]).state
    assert actions(action_choices_view(viewed, 99)) == [7]
    generation = viewed._inventory_cursor.inventory.refresh_generation
    repeated = editor.edit(viewed, operations=resolved.operations[2:]).state
    assert repeated._inventory_cursor.inventory.refresh_generation == generation
    assert creations(resolved) == [('Group', None, 99, 'Group 99'),
                                  ('Level', 99, 7, 'Action Selector 7')]


def action_choices_view(state, group):
    return {'action_choices': action_choices(state.cache, group)}


def test_getter_reservation_changes_later_first_free_add():
    operations = [{'op': 'set-action', 'scene': 1, 'action': 2}, view(),
                  control(BIND), {'op': 'add-action-dialog', 'scene': 1}, view()]
    editor, initial, resolved, _ = model(operations)
    outcome = editor.edit(initial, operations=resolved.operations)
    assert actions(results(outcome)[1]['view']) == [0, 1, 2, 7]
    assert json.loads(resolved.add_dialogs[0])['first_free_address'] == 3
    assert creations(resolved) == [('Level', 42, 2, 'Action Selector 2'),
                                  ('Level', 42, 3, 'Level 3')]
    assert actions(results(outcome)[4]['view']) == [0, 1, 2, 3, 7]


def test_requested_getter_creation_precedes_add_allocator_without_borrowing_future_rows():
    prefix = [{'op': 'set-trigger', 'scene': 1, 'group': 43}]
    getter_first = [*prefix, view(), control(BIND),
                    {'op': 'add-action-dialog', 'scene': 1}, view()]
    editor, initial, resolved, _ = model(getter_first, levels={43: tuple(range(7))})
    edited = editor.edit(initial, operations=resolved.operations)
    assert actions(results(edited)[1]['view']) == [0, 1, 2, 3, 4, 5, 6, 7, 9]
    assert json.loads(resolved.add_dialogs[0])['first_free_address'] == 8
    assert creations(resolved) == [('Level', 43, 9, 'Action Selector 9'),
                                  ('Level', 43, 7, 'Action Selector 7'),
                                  ('Level', 43, 8, 'Level 8')]
    add_first = [*prefix, control(BIND), {'op': 'add-action-dialog', 'scene': 1}, view()]
    other, loaded, reversed_history, _ = model(add_first, levels={43: tuple(range(7))})
    outcome = other.edit(loaded, operations=reversed_history.operations)
    assert json.loads(reversed_history.add_dialogs[0])['first_free_address'] == 7
    assert creations(reversed_history) == [('Level', 43, 9, 'Action Selector 9'),
                                          ('Level', 43, 7, 'Level 7')]
    assert actions(results(outcome)[3]['view']) == [0, 1, 2, 3, 4, 5, 6, 7, 9]


def test_initial_getter_reservations_are_visible_before_the_first_dialog():
    operations = [view(), control(BIND), {'op': 'add-action-dialog', 'scene': 1}, view()]
    editor, initial, resolved, _ = model(operations, levels={42: (0, 1)})
    assert [row['value'] for row in action_choices(initial.cache, 42)] == [0, 1, 7]
    assert initial._inventory_cursor.inventory.refresh_generation == 1
    outcome = editor.edit(initial, operations=resolved.operations)
    assert actions(results(outcome)[0]['view']) == [0, 1, 7]
    assert json.loads(resolved.add_dialogs[0])['first_free_address'] == 2
    assert creations(resolved) == [('Level', 42, 7, 'Action Selector 7'),
                                  ('Level', 42, 2, 'Level 2')]


@pytest.mark.parametrize('first_missing', [False, True], ids=['existing-first', 'created-first'])
def test_later_initial_getter_refresh_preserves_earlier_scene_label_epoch(first_missing):
    levels = {43: (0,)}
    if first_missing:
        levels[42] = (0, 1)
    operations = [view(), control(BIND, REFRESH), view()]
    editor, initial, resolved, _ = model(operations, levels=levels)
    old = initial.scenes[0].dynamic_labels
    assert initial._inventory_cursor.inventory.refresh_generation == (2 if first_missing else 1)
    assert old is not initial.cache.labels(42, 7)
    assert initial.scenes[1].dynamic_labels is initial.cache.labels(43, 9)
    expected_name = '' if first_missing else 'Label 42/7/0'
    assert dynamic_label_rows(initial.cache, initial.scenes[0])[0] == {
        'identity': 'label:202/42/7/0', 'value': 0, 'name': expected_name,
        'raw_value': '0', 'image_present': False}
    viewed = editor.edit(initial, operations=resolved.operations[:1]).state
    assert viewed.scenes[0].dynamic_labels is old
    refreshed = editor.edit(viewed, operations=resolved.operations[1:]).state
    assert refreshed.scenes[0].dynamic_labels is refreshed.cache.labels(42, 7)
    assert refreshed.scenes[0].dynamic_labels is not old
    assert initial.scenes[0].dynamic_labels is old


def test_cancel_has_no_frame_creation_or_collection_refresh():
    operations = [control(BIND), {'op': 'add-action-dialog', 'scene': 1, 'cancel': True}, view()]
    editor, initial, resolved, _ = model(operations)
    assert len(resolved.operations) == 2
    bound = editor.edit(initial, operations=resolved.operations[:1]).state
    after = editor.edit(bound, operations=resolved.operations[1:]).state
    assert after._selector_bound_collection == bound._selector_bound_collection
    assert after._inventory_cursor.inventory.refresh_generation == 0
    assert creations(resolved) == []
    assert json.loads(resolved.add_dialogs[0])['outcome'] == 'cancelled'


def test_before_save_fallback_is_absent_from_edit_and_validation_views():
    # The empty third scene retains internal -1. Changing only its Trigger
    # cannot create an action; BeforeSave later assigns its source fallback0.
    operations = [{'op': 'set-trigger', 'scene': 3, 'group': 42}, view(3)]
    editor, initial, resolved, _ = model(operations, levels={42: (1, 7)})
    edited = editor.edit(initial, operations=resolved.operations).state
    assert [row['value'] for row in action_choices(edited.cache, 42)] == [1, 7]
    assert edited.scenes[2].raw_action == -1
    checked = editor.validate(edited).state
    assert [row['value'] for row in action_choices(checked.cache, 42)] == [1, 7]
    composed = editor.prepare_composition(checked)
    assert composed.terminal.scenes[2].raw_action == 0
    assert composed.fields['SceneBucket'][13] == 0
    assert [row['value'] for row in action_choices(composed.terminal.cache, 42)] == [0, 1, 7]
    assert composed.source is checked
    assert creations(resolved) == [('Level', 42, 0, 'Action Selector 0')]
    assert composed.source.scenes[2].raw_action == -1


@pytest.mark.parametrize('change', ['omit', 'different', 'extra', 'source', 'owner', 'cache'])
def test_history_source_owner_and_cache_mismatch_refuse_without_mutating_state(change):
    operations = [view(), {'op': 'set-action', 'scene': 1, 'action': 2}, view()]
    editor, initial, resolved, values = model(operations)
    before = initial.as_dict()
    with pytest.raises(EdltError):
        if change == 'omit':
            editor.edit(initial, operations=resolved.operations[1:])
        elif change == 'different':
            editor.edit(initial, operations=[view(2)])
        elif change == 'extra':
            edited = editor.edit(initial, operations=resolved.operations).state
            editor.edit(edited, operations=[view()])
        elif change == 'source':
            editor.load({**values, 'PrimaryApplication': (57,)}, metadata=resolved.cache)
        elif change == 'owner':
            EdltSceneManager(fixture()).load(values, metadata=resolved.cache)
        else:
            changed = replace(resolved.cache, level_labels=resolved.cache.level_labels[:-1])
            editor.load(values, metadata=changed)
    assert initial.as_dict() == before


def test_partial_history_refuses_validation_and_save_then_exact_continuation_succeeds():
    operations = [view(), {'op': 'set-action', 'scene': 1, 'action': 2}, view()]
    editor, initial, resolved, _ = model(operations)
    partial = editor.edit(initial, operations=resolved.operations[:1]).state
    before = partial.as_dict()
    with pytest.raises(EdltError, match='complete edit history'):
        editor.validate(partial)
    with pytest.raises(EdltError, match='complete edit history'):
        editor.prepare_composition(partial)
    assert partial.as_dict() == before
    complete = editor.edit(partial, operations=resolved.operations[1:]).state
    assert editor.prepare_composition(complete).terminal.scenes[0].raw_action == 2


def test_timeline_review_serialization_cannot_issue_a_cache_or_state():
    editor, initial, resolved, _ = model([view()])
    assert '_inventory_timeline' not in resolved.cache.as_dict()
    assert 'inventory_timeline' in initial.as_dict()
    review = resolved.cache.as_dict()
    review['_inventory_timeline'] = resolved.cache._inventory_timeline.as_dict()
    with pytest.raises(EdltError, match='format or fields'):
        SceneManagerCache.from_dict(review)
    with pytest.raises(EdltError, match='foreign or modified'):
        forged = replace(resolved.cache._inventory_timeline, _binding='{}')
        replace(resolved.cache, _inventory_timeline=forged)
    with pytest.raises(EdltError, match='intact scene object'):
        editor.edit(replace(initial, _selector_bound_collection=(42, '0' * 64)), operations=[view()])


def test_callback_order_and_forged_cursor_refuse_before_any_state_change():
    editor, initial, resolved, _ = model([control(BIND, REFRESH), view()])
    before = initial.as_dict()
    cursor = initial._inventory_cursor
    with pytest.raises(EdltError, match='out of order'):
        cursor.advance(phase='bind-scene', callback=1, scene=1)
    with pytest.raises(EdltError, match='foreign or modified'):
        replace(initial, _inventory_cursor=replace(cursor, position=1))
    with pytest.raises(EdltError, match='out of order'):
        editor.edit(initial, operations=[control(REFRESH, BIND)])
    assert initial.as_dict() == before
    assert editor.edit(initial, operations=resolved.operations).complete is True


def test_pending_scene_name_and_retained_target_guard_survive_creation():
    operations = [
        {'op': 'scene-name-control', 'scene': 1, 'events': [{'event': 'input', 'text': 'Pending'}]},
        {'op': 'set-action', 'scene': 2, 'action': 5},
        control(BIND, scene=2), view()]
    editor, initial, resolved, _ = model(operations)
    edited = editor.edit(initial, operations=resolved.operations).state
    assert edited.name_controls[0].pending is True
    assert edited.name_controls[0].text == 'Pending'
    assert edited.selector_control.bound_scene == 2
    with pytest.raises(EdltError, match='Pending SceneName'):
        editor.prepare_composition(edited)
    assert initial.name_controls[0] is None


def test_copy_paste_retains_destination_historical_labels_through_refresh():
    operations = [view(), {'op': 'copy', 'scene': 1},
                  {'op': 'set-action', 'scene': 1, 'action': 2},
                  {'op': 'paste', 'scene': 2}, view(2)]
    editor, initial, resolved, _ = model(operations)
    old = initial.scenes[1].dynamic_labels
    outcome = editor.edit(initial, operations=resolved.operations)
    assert outcome.state.scenes[1].dynamic_labels is old
    assert (outcome.state.scenes[1].raw_trigger, outcome.state.scenes[1].raw_action) == (42, 7)
    assert results(outcome)[4]['view']['dynamic_labels'][0]['identity'] == 'label:202/43/9/0'
    assert outcome.state.clipboard.dynamic_labels == ()


def test_manual_v2_cache_retains_existing_non_timeline_api():
    editor, initial = selector_fixture()
    edited = editor.edit(initial, operations=[view()]).state
    assert edited._inventory_cursor is None
    assert 'inventory_timeline' not in edited.as_dict()
    assert editor.prepare_composition(edited).terminal._inventory_cursor is None
