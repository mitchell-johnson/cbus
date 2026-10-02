"""Capability and causal-phase guards independent of the native producer."""
from dataclasses import replace
import json
import pytest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_application_cache import ApplicationCache, CachedDisplay, CachedGroupList
from cbus_toolkit.edlt_lifecycle import LifecycleCache, LifecycleGroup
from cbus_toolkit.edlt_scene_manager import SceneDynamicLabel, SceneLevelLabels, SceneManagerCache
from cbus_toolkit.edlt_scene_selector_views import SceneActionList
from cbus_toolkit.edlt_scene_inventory_timeline import (
    SceneInventory, SceneInventoryFrame, check_cursor, check_timeline, issue_timeline,
)


def issued():
    owner = object()
    display = lambda n: CachedDisplay(n, str(n), str(n))
    app = ApplicationCache(LifecycleCache((56, 202), (
        LifecycleGroup(202, 42, True, levels=(0, 1, 8)),)), True,
        (display(56), display(202)), (CachedGroupList(202, True, (display(42),)),))
    labels = tuple(SceneLevelLabels(42, action, tuple(
        SceneDynamicLabel(str(index), f'Label {action}/{index}', False)
        for index in range(4))) for action in (0, 1, 8))
    template = SceneManagerCache(app, labels, CachedGroupList(202, True, (display(42),)),
        (SceneActionList(42, True, tuple(display(n) for n in (0, 1, 8))),))
    initial = SceneInventory((56, 202), ((202, 42),), ((202, 42, (1,)),))
    changed = SceneInventory((56, 202), ((202, 42),), ((202, 42, (1, 8)),), 1)
    final = SceneInventory((56, 202), ((202, 42),), ((202, 42, (1, 8, 0)),), 2)
    operation = {'op': 'set-action', 'scene': 1, 'action': 8}
    encoded = json.dumps(operation, sort_keys=True, separators=(',', ':'))
    frames = (SceneInventoryFrame('operation-start', encoded, 0, 1, changed, ('created8',)),
              SceneInventoryFrame('operation-end', None, 0, 1, changed))
    save = tuple(SceneInventoryFrame('before-save-scene', None, 0, scene, final)
                 for scene in range(1, 9))
    timeline = issue_timeline(template, initial=initial, frames=frames,
        save_frames=save, validation_targets=((42, 8),) * 8,
        binding={'unit': '//TEST/1/p/20', 'requested_operations': [operation]},
        source_values={'PrimaryApplication': (56,)}, owner=owner)
    return owner, template, timeline, operation


def start():
    owner, template, timeline, op = issued()
    return owner, timeline, timeline.start(template, source_values={'PrimaryApplication': (56,)}, owner=owner), op


def complete(cursor, op):
    return cursor.advance(operation=op, phase='operation-start', scene=1).advance(phase='operation-end', scene=1)


def actions(cursor):
    return tuple(row.address for row in cursor.cache.action_lists[0].actions)


def test_initial_inventory_excludes_future_operation_and_terminal_fallback():
    _, _, cursor, op = start()
    assert actions(cursor) == (1,)
    cursor = complete(cursor, op)
    assert actions(cursor) == (1, 8)
    terminal = cursor.before_save().advance(phase='before-save-scene', scene=1)
    assert actions(terminal) == (0, 1, 8)
    assert actions(cursor) == (1, 8)


@pytest.mark.parametrize('kwargs', [
    {'phase': 'operation-end', 'scene': 1},
    {'phase': 'operation-start', 'scene': 2},
    {'phase': 'operation-start', 'scene': 1, 'callback': 1},
    {'phase': 'bind-scene', 'scene': 1},
])
def test_exact_phase_scene_and_callback_are_required(kwargs):
    _, _, cursor, op = start()
    with pytest.raises(EdltError, match='out of order'):
        cursor.advance(operation=op, **kwargs)
    assert actions(cursor) == (1,)


def test_wrong_history_source_owner_and_cache_refuse():
    owner, template, timeline, _ = issued()
    for values, issuer in (({'PrimaryApplication': (57,)}, owner), ({'PrimaryApplication': (56,)}, object())):
        with pytest.raises(EdltError):
            timeline.start(template, source_values=values, owner=issuer)
    _, _, cursor, op = start()
    with pytest.raises(EdltError, match='differs'):
        cursor.advance(operation={**op, 'action': 7}, phase='operation-start', scene=1)
    with pytest.raises(EdltError, match='source/cache'):
        timeline.start(replace(template, level_labels=template.level_labels[:-1]),
                       source_values={'PrimaryApplication': (56,)}, owner=owner)


def test_replaced_cursor_or_frame_fails_issuer_seal():
    _, timeline, cursor, _ = start()
    with pytest.raises(EdltError, match='modified'):
        check_cursor(replace(cursor, position=1))
    with pytest.raises(EdltError, match='modified'):
        check_timeline(replace(timeline, _frames=()))
    with pytest.raises(EdltError):
        check_timeline(timeline.as_dict())


def test_complete_history_required_before_validation_or_save():
    _, _, cursor, _ = start()
    for branch in (cursor.validation, cursor.before_save):
        with pytest.raises(EdltError, match='complete edit history'):
            branch()


def test_validation_branch_never_borrows_save_fallback_and_is_repeatable():
    _, _, cursor, op = start()
    cursor = complete(cursor, op)
    branch = cursor.validation().advance(phase='validate-action', scene=1)
    assert actions(branch) == (1, 8)
    assert actions(cursor) == (1, 8)
    assert branch.validation().advance(phase='validate-trigger', scene=1).cache.as_dict() == branch.cache.as_dict()
    with pytest.raises(EdltError, match='validation getter'):
        branch.advance(phase='write-action', scene=1)


def test_save_requires_numbered_scenes_and_cannot_reenter_terminal_branch():
    _, _, cursor, op = start()
    cursor = complete(cursor, op).before_save()
    with pytest.raises(EdltError, match='scenes1..8'):
        cursor.advance(phase='before-save-scene', scene=2)
    for scene in range(1, 9):
        cursor = cursor.advance(phase='before-save-scene', scene=scene)
    with pytest.raises(EdltError):
        cursor.before_save()


def test_refresh_generations_keep_old_labels_and_collection_ownership():
    _, timeline, initial, op = start()
    old_labels = initial.cache.labels(42, 1)
    old_generation = initial.collection_generation(42)
    edited = complete(initial, op)
    assert edited.collection_generation(42) != old_generation
    assert edited.cache.labels(42, 1) is not old_labels
    assert timeline.label_owner(old_labels).action == 1
    assert timeline.label_owner(edited.cache.labels(42, 1)).action == 1
    assert initial.cache.labels(42, 1) is initial.timeline.start(initial.timeline._template,
        source_values={'PrimaryApplication': (56,)}, owner=initial._seal.owner).cache.labels(42, 1)


def test_serialized_cache_cannot_recreate_timeline_capability():
    _, _, cursor, _ = start()
    clone = SceneManagerCache.from_dict(cursor.cache.as_dict())
    assert clone._inventory_timeline is None
    with pytest.raises(EdltError, match='fields'):
        SceneManagerCache.from_dict({**clone.as_dict(), 'inventory_timeline': cursor.timeline.as_dict()})


def test_outer_rebase_never_promotes_future_application_or_group_choices():
    owner, template, timeline, _ = issued()
    outer = template.application_cache
    future = CachedDisplay(57, 'Future', 'Future')
    new_app = ApplicationCache(LifecycleCache((*outer.lifecycle.applications, 57),
        (*outer.lifecycle.groups, LifecycleGroup(56, 99, True), LifecycleGroup(57, 1, True))),
        True, (*outer.applications, future),
        (*outer.group_lists, CachedGroupList(56, True, (CachedDisplay(99, 'Future Group', 'Future Group'),)),
         CachedGroupList(57, True, (CachedDisplay(1, 'One', 'One'),))))
    cache = replace(template, application_cache=new_app)
    rebased = timeline.rebase_outer(cache)
    cursor = rebased.start(cache, source_values={'PrimaryApplication': (56,)}, owner=owner)
    assert cursor.cache.application_cache.find_application(57) is None
    assert cursor.cache.application_cache.find_group_list(56).groups == ()
    assert cache.application_cache.find_group_list(56).groups[0].address == 99


def test_branch_union_refreshes_each_distinct_creation_once():
    initial = SceneInventory((202,), ((202, 42),), ((202, 42, (1,)),))
    validated = initial.union(SceneInventory((202,), ((202, 42),), ((202, 42, (2,)),), 1))
    saved = validated.union(SceneInventory((202,), ((202, 42),), ((202, 42, (1, 3)),), 1))
    assert saved.refresh_generation == 2
    assert saved.union(saved).refresh_generation == 2


def test_outer_same_group_later_levels_and_new_images_stay_outside_initial_choices():
    owner, template, timeline, _ = issued()
    outer = template.application_cache
    final_group = replace(outer.lifecycle.groups[0], levels=(0, 1, 8, 100),
                          dynamic_images_known=True, dynamic_images=(False,) * 4)
    cache = replace(template, application_cache=replace(outer,
        lifecycle=replace(outer.lifecycle, groups=(final_group,))))
    rebased = timeline.rebase_outer(cache)
    cursor = rebased.start(cache, source_values={'PrimaryApplication': (56,)}, owner=owner)
    assert actions(cursor) == (1,)
    assert cursor.cache.application_cache.lifecycle.find(202, 42).levels == (1,)
    assert cache.application_cache.lifecycle.find(202, 42).levels[-1] == 100


def test_outer_rebase_refuses_loss_of_issued_positive_levels_or_known_images():
    _, template, timeline, _ = issued()
    outer = template.application_cache
    with pytest.raises(EdltError):
        timeline.rebase_outer(replace(template, application_cache=replace(outer,
            lifecycle=replace(outer.lifecycle, groups=(replace(outer.lifecycle.groups[0], levels=(1,)),)))))
    original = replace(template, application_cache=replace(outer, lifecycle=replace(
        outer.lifecycle, groups=(replace(outer.lifecycle.groups[0], dynamic_images_known=True,
                                        dynamic_images=(False,) * 4),))))
    rebased = timeline.rebase_outer(original)
    changed = replace(original, application_cache=replace(original.application_cache,
        lifecycle=replace(original.application_cache.lifecycle,
            groups=(replace(original.application_cache.lifecycle.groups[0], dynamic_images=(True,) * 4),))))
    with pytest.raises(EdltError, match='replace issued lifecycle'):
        rebased.rebase_outer(changed)
