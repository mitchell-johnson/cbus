"""Exact native causal scenes, with in-memory owned snapshot fixtures only."""
import json
from dataclasses import replace
import pytest

from cbus_toolkit.edlt import EdltError, _render
from cbus_toolkit.edlt_scene_metadata import SceneLevelCreation, resolve_native_scene_metadata
from tests import test_edlt_scene_metadata as scene_support
from tests.test_edlt_scene_add_dialog import add_project_tag


@pytest.fixture
def native():
    support = scene_support.SceneMetadataTests()
    support.setUp()
    add_project_tag(support.client)
    groups = support.client.applications[202]['groups']
    support.client.applications[202]['groups'] = {n: groups[n] for n in (42, 43)}
    group = groups[42]
    group['levels'] = (1, 2)
    group['level_tags'] = {n: group['level_tags'][n] for n in (1, 2)}
    return support


def resolve(native, rows):
    return resolve_native_scene_metadata(native.client.xml(), '//TEST/254/p/20',
        native.values, native.editor.engine, rows)


def replay(native, rows):
    metadata = resolve(native, rows)
    engine = native.editor.engine
    state = engine.load(native.values, metadata=metadata.cache)
    result = engine.edit(state, operations=metadata.operations)
    return metadata, result


def result_views(outcome):
    return [json.loads(row)['view'] for row in outcome.operation_results
            if json.loads(row)['operation']['op'] == 'get-selector-view']


def control(events, scene=1):
    return {'op': 'scene-selector-control', 'scene': scene, 'events': events}


def test_post_load_getter_creates_requested_group_and_action_at_exact_operation(native):
    rows = [{'op': 'set-trigger', 'scene': 1, 'group': 200},
            {'op': 'get-selector-view', 'scene': 1}]
    metadata, outcome = replay(native, rows)
    timeline = metadata.cache._inventory_timeline
    assert (202, 200) not in timeline._initial.groups
    assert (202, 200) not in timeline._frames[1].inventory.groups
    assert (202, 200) in timeline._frames[2].inventory.groups
    assert [(row.as_dict()['kind'], row.address, row.name) for row in metadata.creations] == [
        ('Group', 200, 'Group 200'), ('Level', 1, 'Action Selector 1')]
    assert result_views(outcome)[0]['action_choices'][0]['identity'] == 'action:202/200/1'
    assert native.client.commands == []


def test_getter_twice_creates_once_and_preserves_old_dynamic_label_owner(native):
    rows = [{'op': 'set-trigger', 'scene': 1, 'group': 43},
            {'op': 'get-selector-view', 'scene': 1}, {'op': 'get-selector-view', 'scene': 1}]
    metadata, outcome = replay(native, rows)
    assert [(row.group, row.address) for row in metadata.creations] == [(43, 1)]
    views = result_views(outcome)
    assert views[0] == views[1]
    assert views[0]['dynamic_labels'][0]['identity'] == 'label:202/42/1/0'


def test_add_action_is_invisible_earlier_and_appears_at_qualified_lowered_effect(native):
    rows = [{'op': 'get-selector-view', 'scene': 1},
            {'op': 'add-action-dialog', 'scene': 1}, {'op': 'get-selector-view', 'scene': 1}]
    metadata, outcome = replay(native, rows)
    views = result_views(outcome)
    assert [row['value'] for row in views[0]['action_choices']] == [1, 2]
    assert [row['value'] for row in views[1]['action_choices']] == [1, 2, 0]
    assert metadata.requested_operations[1]['op'] == 'add-action-dialog'
    assert metadata.operations[1] == {'op': 'set-action', 'scene': 1, 'action': 0}
    assert metadata.creations[0].name == 'Level 0'
    assert metadata.as_dict()['inventory_timeline']['binding']['add_dialogs'][0]['outcome'] == 'accepted'


@pytest.mark.parametrize('cancel', [False, True])
def test_trigger_add_and_cancel_do_not_shadow_inventory_capture(native, cancel):
    rows = [{'op': 'get-selector-view', 'scene': 1},
            {'op': 'add-trigger-dialog', 'scene': 1, 'cancel': cancel},
            {'op': 'get-selector-view', 'scene': 1}]
    metadata, outcome = replay(native, rows)
    views = result_views(outcome)
    assert [row['value'] for row in views[0]['trigger_choices']] == [42, 43]
    if cancel:
        assert metadata.creations == ()
        assert views[0] == views[1]
    else:
        assert [row['value'] for row in views[1]['trigger_choices']] == [42, 43, 0]
        assert [(row.as_dict()['kind'], row.address, row.name) for row in metadata.creations] == [
            ('Group', 0, 'Trigger Group 0'), ('Level', 1, 'Action Selector 1')]


def test_cancelled_add_has_no_phase_effect_or_generation_change(native):
    rows = [{'op': 'get-selector-view', 'scene': 1},
            {'op': 'add-action-dialog', 'scene': 1, 'cancel': True},
            {'op': 'get-selector-view', 'scene': 1}]
    metadata, outcome = replay(native, rows)
    assert metadata.creations == ()
    assert len(metadata.operations) == 2
    assert result_views(outcome)[0] == result_views(outcome)[1]
    assert {row.inventory.refresh_generation for row in metadata.cache._inventory_timeline._frames} == {0}
    assert json.loads(metadata.add_dialogs[0])['outcome'] == 'cancelled'


def test_initial_loader_reservations_precede_first_free_add(native):
    group = native.client.applications[202]['groups'][42]
    group['levels'], group['level_tags'] = (), {}
    metadata, _ = replay(native, [{'op': 'get-selector-view', 'scene': 1},
                                  {'op': 'add-action-dialog', 'scene': 1}])
    assert next(rows for app, group, rows in metadata.cache._inventory_timeline._initial.levels
                if (app, group) == (202, 42)) == (1, 2)
    assert [(row.address, row.name) for row in metadata.creations] == [
        (1, 'Action Selector 1'), (2, 'Action Selector 2'), (0, 'Level 0')]


def test_later_initial_getter_preserves_earlier_scene_label_epoch(native):
    bucket = list(native.values['SceneBucket'])
    bucket[native.values['Scene2StartAddress'][0] + 3] = 9
    native.values['SceneBucket'] = tuple(bucket)
    native.client.values['SceneBucket'] = _render(tuple(bucket))
    metadata = resolve(native, [{'op': 'get-selector-view', 'scene': 1}])
    state = native.editor.engine.load(native.values, metadata=metadata.cache)
    assert metadata.cache._inventory_timeline._initial_scene_bindings[:2] == ((42, 1, 0), (42, 9, 1))
    old = state.scenes[0].dynamic_labels
    current = state.cache.labels(42, 1)
    assert all(a is not b for a, b in zip(old, current))
    assert [row.as_dict() for row in old] == [row.as_dict() for row in current]
    outcome = native.editor.engine.edit(state, operations=metadata.operations)
    assert outcome.state.scenes[0].dynamic_labels is old
    assert result_views(outcome)[0]['dynamic_labels'][0]['identity'] == 'label:202/42/1/0'


def test_parent_initializer_preserves_loader_epochs_before_genuine_prior_add(native):
    bucket = list(native.values['SceneBucket'])
    bucket[native.values['Scene2StartAddress'][0] + 3] = 9
    native.values['SceneBucket'] = tuple(bucket)
    native.client.values['SceneBucket'] = _render(tuple(bucket))
    source = resolve(native, [{'op': 'get-selector-view', 'scene': 1}]).cache._inventory_timeline
    projected = (SceneLevelCreation(42, 9, 'Action Selector 9', ('Scene2 initial getter',)),
                 SceneLevelCreation(42, 100, 'Prior parent Add', ('prior parent Add',)))
    metadata = resolve_native_scene_metadata(native.client.xml(), '//TEST/254/p/20',
        native.values, native.editor.engine, [{'op': 'get-selector-view', 'scene': 1}],
        _projected_levels=projected, _initialization_timeline=source)
    state = native.editor.engine.load(native.values, metadata=metadata.cache)
    assert metadata.cache._inventory_timeline._initial.refresh_generation == 2
    assert metadata.cache._inventory_timeline._initial_scene_bindings[:2] == ((42, 1, 0), (42, 9, 1))
    assert all(a is not b for a, b in zip(state.scenes[1].dynamic_labels, state.cache.labels(42, 9)))
    assert [row.address for row in state.cache.action_lists[0].actions] == [1, 2, 9, 100]
    assert metadata.creations == ()
    assert metadata.as_dict()['inventory_timeline']['binding']['initialization_timeline_sha256'] == source.fingerprint


def test_parent_initializer_refuses_changed_xml_owner_or_scene_identity(native):
    source = resolve(native, [{'op': 'get-selector-view', 'scene': 1}]).cache._inventory_timeline
    rows = [{'op': 'get-selector-view', 'scene': 1}]
    with pytest.raises(EdltError, match='another XML/unit'):
        resolve_native_scene_metadata(native.client.xml() + '\n', '//TEST/254/p/20',
            native.values, native.editor.engine, rows, _initialization_timeline=source)
    from cbus_toolkit.edlt_scene_manager import EdltSceneManager
    with pytest.raises(EdltError, match='foreign'):
        resolve_native_scene_metadata(native.client.xml(), '//TEST/254/p/20',
            native.values, EdltSceneManager(native.spec), rows, _initialization_timeline=source)
    projected = dict(native.values)
    bucket = list(projected['SceneBucket'])
    bucket[projected['Scene1StartAddress'][0] + 3] = 2
    projected['SceneBucket'] = tuple(bucket)
    with pytest.raises(EdltError, match='issued retained-model provenance'):
        resolve_native_scene_metadata(native.client.xml(), '//TEST/254/p/20',
            native.values, native.editor.engine, rows,
            _projected_values=projected, _initialization_timeline=source)


def test_getter_before_add_reserves_address_but_reverse_history_does_not(native):
    forward = [{'op': 'set-trigger', 'scene': 1, 'group': 43},
               {'op': 'get-selector-view', 'scene': 1}, {'op': 'add-action-dialog', 'scene': 1}]
    backward = [{'op': 'set-trigger', 'scene': 1, 'group': 43},
                {'op': 'add-action-dialog', 'scene': 1}, {'op': 'get-selector-view', 'scene': 1}]
    assert [(row.group, row.address) for row in resolve(native, forward).creations] == [(43, 1), (43, 0)]
    assert [(row.group, row.address) for row in resolve(native, backward).creations] == [(43, 0)]


def test_trigger_handler_creation_keeps_old_collection_until_explicit_rebind(native):
    rows = [{'op': 'set-trigger', 'scene': 1, 'group': 43},
            control([{'event': 'scene-current-changed', 'current': True},
                     {'event': 'trigger-current-changed'}]),
            control([{'event': 'trigger-current-changed'},
                     {'event': 'action-selected', 'value': 1, 'choice_index': 0,
                      'choice_identity': 'action:202/43/1'}])]
    metadata, outcome = replay(native, rows)
    first = json.loads(outcome.operation_results[1])['scene_selector_control']['state']['view']
    final = json.loads(outcome.operation_results[2])['scene_selector_control']['state']['view']
    assert first['action_choices'] == []
    assert final['action_choices'][0]['identity'] == 'action:202/43/1'
    assert [(row.group, row.address) for row in metadata.creations] == [(43, 1)]
    frames = metadata.as_dict()['inventory_timeline']['frames']
    assert [row['phase'] for row in frames[2:6]] == [
        'operation-start', 'bind-scene', 'bind-scene', 'trigger-current']


def test_new_row_cannot_be_selected_from_replaced_old_bound_collection(native):
    rows = [{'op': 'set-trigger', 'scene': 1, 'group': 43}, control([
        {'event': 'scene-current-changed', 'current': True},
        {'event': 'trigger-current-changed'},
        {'event': 'action-selected', 'value': 1, 'choice_index': 0,
         'choice_identity': 'action:202/43/1'}])]
    with pytest.raises(EdltError, match='outside'):
        resolve(native, rows)
    assert native.client.commands == []


def test_old_source_choice_writes_current_trigger_and_adopts_its_labels(native):
    rows = [control([{'event': 'scene-current-changed', 'current': True},
        {'event': 'trigger-selected', 'value': 43, 'choice_index': 1,
         'choice_identity': 'trigger:202/43'},
        {'event': 'action-selected', 'value': 2, 'choice_index': 1,
         'choice_identity': 'action:202/42/2'}])]
    metadata, outcome = replay(native, rows)
    view = json.loads(outcome.operation_results[0])['scene_selector_control']['state']['view']
    assert view['trigger_group'] == 43 and view['action_selector'] == 2
    assert [row['identity'] for row in view['action_choices']] == ['action:202/42/1', 'action:202/42/2']
    assert view['dynamic_labels'][0]['identity'] == 'label:202/43/2/0'
    assert [(row.group, row.address) for row in metadata.creations] == [(43, 2)]


def test_action_add_accepts_explicit_trigger_selection_but_refuses_raw_setter_divergence(native):
    begin = control([{'event': 'scene-current-changed', 'current': True}])
    raw = [begin, {'op': 'set-trigger', 'scene': 1, 'group': 43},
           {'op': 'add-action-dialog', 'scene': 1}]
    with pytest.raises(EdltError, match='stale host combo'):
        resolve(native, raw)
    selected = [control([{'event': 'scene-current-changed', 'current': True},
        {'event': 'trigger-selected', 'value': 43, 'choice_index': 1,
         'choice_identity': 'trigger:202/43'}]), {'op': 'add-action-dialog', 'scene': 1}]
    assert [(row.group, row.address) for row in resolve(native, selected).creations] == [(43, 0)]


def test_save_fallback_zero_is_not_visible_to_earlier_view_or_validation(native):
    rows = [{'op': 'clear-scene', 'scene': 1}, {'op': 'set-trigger', 'scene': 1, 'group': 43},
            {'op': 'get-selector-view', 'scene': 1}]
    metadata, outcome = replay(native, rows)
    assert result_views(outcome)[0]['action_choices'] == []
    validated = native.editor.engine.validate(outcome.state).state
    assert next(row for row in validated.cache.action_lists if row.group == 43).actions == ()
    saved = native.editor.engine.prepare_composition(validated)
    assert saved.terminal.scenes[0].raw_action == 0
    assert [row.address for row in next(row for row in saved.terminal.cache.action_lists if row.group == 43).actions] == [0]
    assert [(row.group, row.address, row.name) for row in metadata.creations] == [(43, 0, 'Action Selector 0')]


def test_callback_frames_are_exact_and_source_bound(native):
    rows = [control([{'event': 'scene-current-changed', 'current': True},
                     {'event': 'trigger-current-changed'}])]
    metadata, outcome = replay(native, rows)
    timeline = metadata.cache._inventory_timeline
    assert [row.phase for row in timeline._frames] == [
        'operation-start', 'bind-scene', 'bind-scene', 'trigger-current', 'operation-end']
    assert [row.callback for row in timeline._frames] == [0, 1, 2, 3, 0]
    assert outcome.state._inventory_cursor.position == 5
    source = dict(native.values)
    source['PrimaryApplication'] = (57,)
    with pytest.raises(EdltError, match='source/cache'):
        native.editor.engine.load(source, metadata=metadata.cache)


def test_same_phase_foreign_owner_and_replaced_frame_refuse(native):
    from cbus_toolkit.edlt_scene_manager import EdltSceneManager
    metadata = resolve(native, [{'op': 'get-selector-view', 'scene': 1}])
    with pytest.raises(EdltError, match='foreign'):
        EdltSceneManager(native.spec).load(native.values, metadata=metadata.cache)
    timeline = metadata.cache._inventory_timeline
    with pytest.raises(EdltError, match='modified'):
        replace(metadata.cache, _inventory_timeline=replace(timeline, _frames=()))


def test_conflicting_value_address_remains_new_profile_refusal(native):
    native.client.applications[202]['groups'][42]['level_values'] = {1: 9}
    with pytest.raises(EdltError, match='matching native action Address and Value'):
        resolve(native, [{'op': 'get-selector-view', 'scene': 1}])
    plain = resolve(native, [{'op': 'get-action', 'scene': 1}])
    assert plain.cache._inventory_timeline is None
    assert plain.cache.as_dict()['format'].endswith('-v1')


def test_timeline_review_is_detached_and_cannot_change_capability(native):
    metadata = resolve(native, [{'op': 'get-selector-view', 'scene': 1}])
    review = metadata.as_dict()['inventory_timeline']
    review['frames'].clear()
    assert len(metadata.cache._inventory_timeline._frames) == 2
    assert metadata.as_dict()['inventory_timeline']['serialized_input_capability'] is False
