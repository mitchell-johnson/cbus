"""Observed ordered SceneManager selector lists, separate from legacy sentinels.

These are declared cache facts, not a WinForms binding or database existence
proof. In particular the actual TriggerGroups list never gains an invented 255
object from the legacy lifecycle's synthetic unused-group record.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from .edlt import EdltError, _int
from .edlt_application_cache import CachedDisplay, CachedGroupList
from .edlt_lifecycle import LifecycleMetadataError


@dataclass(frozen=True)
class SceneActionList:
    group: int
    complete: bool
    actions: tuple[CachedDisplay, ...]

    def __post_init__(self):
        _int(self.group, 'Scene action-list group')
        if (type(self.complete) is not bool or type(self.actions) is not tuple
                or len(self.actions) > 256
                or any(type(row) is not CachedDisplay for row in self.actions)
                or len({row.address for row in self.actions}) != len(self.actions)):
            raise EdltError('Scene action lists require bounded unique ordered display objects and completeness')

    def as_dict(self):
        return {'group': self.group, 'complete': self.complete,
                'actions': [row.as_dict() for row in self.actions]}


def parse_selector_lists(trigger, actions):
    if (not isinstance(trigger, Mapping)
            or set(trigger) != {'application', 'complete', 'groups'}
            or not isinstance(trigger['groups'], (list, tuple))):
        raise EdltError('Invalid actual SceneManager trigger list')
    trigger = CachedGroupList(trigger['application'], trigger['complete'],
                              tuple(CachedDisplay.from_dict(row) for row in trigger['groups']))
    if not isinstance(actions, (list, tuple)) or len(actions) > 256:
        raise EdltError('Scene action lists require at most 256 group records')
    parsed = []
    for row in actions:
        if (not isinstance(row, Mapping) or set(row) != {'group', 'complete', 'actions'}
                or not isinstance(row['actions'], (list, tuple))):
            raise EdltError('Invalid SceneManager action-list fields')
        parsed.append(SceneActionList(row['group'], row['complete'],
                                     tuple(CachedDisplay.from_dict(v) for v in row['actions'])))
    return trigger, tuple(parsed)


def validate_selector_lists(application_cache, trigger, actions):
    if trigger is None and actions is None:
        return
    if (type(trigger) is not CachedGroupList or trigger.application != 202
            or type(actions) is not tuple or len(actions) > 256
            or any(type(row) is not SceneActionList for row in actions)
            or len({row.group for row in actions}) != len(actions)
            or sum(len(row.actions) for row in actions) > 8192):
        raise EdltError('SceneManager v2 requires actual application 202 trigger and bounded action lists')
    for row in trigger.groups:
        fact = application_cache.lifecycle.find(202, row.address)
        if fact is None or not fact.exists:
            raise EdltError('Actual trigger objects require explicit positive lifecycle facts')
    for row in actions:
        fact = application_cache.lifecycle.find(202, row.group)
        if (fact is None or not fact.exists or fact.levels is None
                or not {v.address for v in row.actions} <= set(fact.levels)):
            raise EdltError('Named actions require positive complete lifecycle level facts')
        if not any(v.address == row.group for v in trigger.groups):
            raise EdltError('Named action lists require an actual trigger-list object')
    # The outer native parent may retain later-created lifecycle objects. Only
    # these ordered display lists describe the actual SceneManager position;
    # their complete sets must not be widened to the outer inventory.


def _missing(message, **fact):
    raise LifecycleMetadataError(message, fact, original_stage='scene-selector-view')


def application_choices(cache, primary, secondary):
    rows = []
    for selector, address, prefix in ((0, primary, '(P) '), (1, secondary, '(S) ')):
        if selector == 1 and address == 255:
            continue
        observed = cache.application_cache.find_application(address)
        if observed is None:
            _missing('Explicit application display is required', application=address,
                     field='application_display')
        text = prefix + observed.formatted_display
        rows.append({'identity': f'application:{selector}/{address}', 'value': selector,
                     'application': address, 'name': text, 'formatted_display': text})
    return rows


def trigger_choices(cache):
    row = cache.trigger_list
    if row is None or not row.complete:
        _missing('Complete actual TriggerGroups are required', application=202,
                 field='actual_trigger_list_complete')
    return [{'identity': f'trigger:202/{v.address}', 'value': v.address,
             'name': v.name, 'formatted_display': v.formatted_display}
            for v in row.groups]


def action_choices(cache, group):
    if group == 255:
        return []
    rows = cache.action_lists
    row = None if rows is None else next((v for v in rows if v.group == group), None)
    if row is None or not row.complete:
        _missing('Complete ordered named actions are required', application=202,
                 group=group, field='action_list_complete')
    return [{'identity': f'action:202/{group}/{v.address}', 'value': v.address,
             'name': v.name, 'formatted_display': v.formatted_display}
            for v in row.actions]


def dynamic_label_rows(cache, scene):
    labels = scene.dynamic_labels
    if not labels:
        return []
    # CurrentDynamicLabels contains actual DataStore object references. A
    # trigger setter can leave old labels attached; their identity must not be
    # silently relabelled using the new trigger number.
    owners = [row for row in cache.level_labels if len(row.labels) == len(labels)
              and all(a is b for a, b in zip(row.labels, labels))]
    if len(owners) != 1:
        _missing('Retained dynamic-label object ownership is ambiguous', application=202,
                 field='dynamic_label_identity')
    owner = owners[0]
    return label_choices(owner.group, owner.action, labels)


def label_choices(group, action, labels):
    """Rows for an observed DynamicAll collection, preserving actual ordinal."""
    _int(group, 'Dynamic-label owner group'); _int(action, 'Dynamic-label owner action')
    if not isinstance(labels, (tuple, list)) or len(labels) > 4:
        raise EdltError('Dynamic label choices require at most four observed rows')
    return [{'identity': f'label:202/{group}/{action}/{index}',
             'value': index, 'name': row.name, 'raw_value': row.value,
             'image_present': row.image_present}
            for index, row in enumerate(labels)]


def retained_view(cache, scene, *, primary, secondary, actions=None):
    """Read retained fields without invoking extra property getters."""
    return {'scene': scene.slot, 'application_selector': scene.primary_secondary,
            'can_edit': scene.can_edit,
            'trigger_group': scene.raw_trigger, 'action_selector': scene.raw_action,
            'raw_action_selector': scene.raw_action, 'action_getter_observed': False,
            'label_value_index': scene.label_value_index,
            'application_choices': application_choices(cache, primary, secondary),
            'trigger_choices': trigger_choices(cache),
            'action_choices': action_choices(cache, scene.raw_trigger) if actions is None else actions,
            'dynamic_labels': dynamic_label_rows(cache, scene),
            'retained_fields_only': True, 'automatic_host_scheduling_inferred': False}
