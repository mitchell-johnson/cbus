"""Retained, database-only eDLT scene edits using declared cache objects.

Model scope is deliberate: no WinForms binding, group creation, network I/O,
or physical invocation is performed here. Static scene names use the shared
Toolkit-compatible allocator. Supplied capture observations use a separate
immutable, verification-aware transition.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
import hashlib
import json
from types import MappingProxyType
from typing import Mapping
import weakref

from .edlt import EdltError, EdltApplyError, _int, _render
from .edlt_application_cache import ApplicationCache
from .edlt_lifecycle import EdltLifecycle, LoadedEdlt, LifecycleCache, LifecycleGroup, LifecycleMetadataError, _changes, _delta, _error_text
from .edlt_scene_selector_views import (SceneActionList, action_choices, parse_selector_lists,
    retained_view, trigger_choices, validate_selector_lists)
from .edlt_scene_names import (FIXED_SUGGESTION_NAMES, assign_name, checked_names, isolated_additive_cache,
    load_names, save_names, scene_name, scene_names_view)

MAX_OPERATIONS = 256


def _json(value): return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
def _array(value, maximum, name):
    if not isinstance(value, (tuple, list)) or len(value) > maximum:
        raise EdltError(name + ' must be a bounded array')
    return value


@dataclass(frozen=True)
class SceneDynamicLabel:
    """The three observed DataStore fields; image pixels are not modeled."""
    value: str
    name: str
    image_present: bool

    def __post_init__(self):
        if any(not isinstance(v, str) or len(v) > 1024 for v in (self.value, self.name)) or type(self.image_present) is not bool:
            raise EdltError('Dynamic label value/name must be bounded strings and image_present boolean')

    def as_dict(self): return dict(value=self.value, name=self.name, image_present=self.image_present)


@dataclass(frozen=True)
class SceneLevelLabels:
    group: int
    action: int
    labels: tuple[SceneDynamicLabel, ...]

    def __post_init__(self):
        _int(self.group, 'Trigger group'); _int(self.action, 'Action selector')
        if not isinstance(self.labels, tuple) or len(self.labels) > 4 or any(type(v) is not SceneDynamicLabel for v in self.labels):
            raise EdltError('DynamicAll must be an explicit array of at most four label objects')

    def as_dict(self): return dict(group=self.group, action=self.action, labels=[v.as_dict() for v in self.labels])


@dataclass(frozen=True)
class SceneManagerCache:
    application_cache: ApplicationCache
    level_labels: tuple[SceneLevelLabels, ...]
    trigger_list: object | None = None
    action_lists: tuple[SceneActionList, ...] | None = None
    _inventory_timeline: object | None = field(default=None, repr=False, compare=False, kw_only=True)

    def __post_init__(self):
        if type(self.application_cache) is not ApplicationCache:
            raise EdltError('Scene cache requires ApplicationCache')
        if not isinstance(self.level_labels, tuple) or len(self.level_labels) > 8192 or any(type(v) is not SceneLevelLabels for v in self.level_labels):
            raise EdltError('Scene level-label cache exceeds 8192 records or contains invalid records')
        if len({(v.group, v.action) for v in self.level_labels}) != len(self.level_labels):
            raise EdltError('Duplicate scene level-label cache key')
        for row in self.level_labels:
            fact = self.application_cache.lifecycle.find(202, row.group)
            if fact is None or not fact.exists or fact.levels is None or row.action not in fact.levels:
                raise EdltError('DynamicAll requires an explicitly present trigger group and level')
        validate_selector_lists(self.application_cache, self.trigger_list, self.action_lists)
        if self._inventory_timeline is not None:
            from .edlt_scene_inventory_timeline import check_timeline
            check_timeline(self._inventory_timeline)

    def as_dict(self):
        result = dict(format='cbus-edlt-scene-manager-cache-v1', application_cache=self.application_cache.as_dict(),
                      level_labels=[v.as_dict() for v in self.level_labels])
        if self.trigger_list is not None:
            result.update(format='cbus-edlt-scene-manager-cache-v2', trigger_list=self.trigger_list.as_dict(),
                          action_lists=[v.as_dict() for v in self.action_lists])
        return result

    @classmethod
    def from_dict(cls, value):
        common = {'format', 'application_cache', 'level_labels'}
        if (not isinstance(value, Mapping)
                or not (value.get('format') == 'cbus-edlt-scene-manager-cache-v1' and set(value) == common
                        or value.get('format') == 'cbus-edlt-scene-manager-cache-v2'
                        and set(value) == common | {'trigger_list', 'action_lists'})):
            raise EdltError('Invalid SceneManager cache format or fields')
        rows = []
        for row in _array(value['level_labels'], 8192, 'Level labels'):
            if not isinstance(row, Mapping) or set(row) != {'group', 'action', 'labels'}:
                raise EdltError('Invalid level-label record')
            labels = []
            for label in _array(row['labels'], 4, 'DynamicAll'):
                if not isinstance(label, Mapping) or set(label) != {'value', 'name', 'image_present'}:
                    raise EdltError('Invalid DynamicAll fields')
                labels.append(SceneDynamicLabel(**label))
            rows.append(SceneLevelLabels(row['group'], row['action'], tuple(labels)))
        lists = ((None, None) if value['format'].endswith('-v1') else
                 parse_selector_lists(value['trigger_list'], value['action_lists']))
        return cls(ApplicationCache.from_dict(value['application_cache']), tuple(rows), *lists)

    def labels(self, group, action):
        row = next((v for v in self.level_labels if (v.group, v.action) == (group, action)), None)
        if row is None:
            raise LifecycleMetadataError('Explicit DynamicAll facts are required',
                {'application': 202, 'group': group, 'action': action, 'field': 'dynamic_all'}, original_stage='scene-label-refresh')
        return row.labels


@dataclass(frozen=True)
class SceneManagerItem:
    item_id: int
    group: LifecycleGroup
    ramp_rate: int
    can_edit: bool
    level: int

    def as_dict(self):
        return dict(item_id=self.item_id, group_reference={'application': self.group.application, 'group': self.group.group},
                    ramp_rate=self.ramp_rate, can_edit=self.can_edit, level=self.level, percent=100 * (self.level + 2) // 255)


@dataclass(frozen=True)
class SceneCaptureLevel:
    """One supplied capture observation; verification is separate from its value."""
    item_id: int
    level: int
    verified: bool

    def __post_init__(self):
        _int(self.item_id, 'Item identity', 1, 65536)
        _int(self.level, 'Captured level')
        if type(self.verified) is not bool:
            raise EdltError('Capture verification must be boolean')

    def as_dict(self):
        return dict(item_id=self.item_id, level=self.level, verified=self.verified)


@dataclass(frozen=True)
class SceneManagerScene:
    slot: int
    primary_secondary: int
    can_edit: bool
    raw_trigger: int
    raw_action: int
    name_index: int
    items: tuple[SceneManagerItem, ...]
    label_value_index: int = 0
    dynamic_labels: tuple[SceneDynamicLabel, ...] = ()

    def as_dict(self):
        return dict(identity='scene:' + str(self.slot), slot=self.slot, primary_secondary=self.primary_secondary,
            can_edit=self.can_edit, raw_trigger=self.raw_trigger, raw_action=self.raw_action, name_index=self.name_index,
            items=[v.as_dict() for v in self.items], label_value_index=self.label_value_index,
            dynamic_labels=[v.as_dict() for v in self.dynamic_labels])


class _Origin:
    def __init__(self, owner): self.owner, self.reference, self.fingerprint = owner, None, None


@dataclass(frozen=True)
class SceneManagerState:
    loaded: LoadedEdlt
    cache: SceneManagerCache
    scenes: tuple[SceneManagerScene, ...]
    clipboard: SceneManagerScene | None
    next_item_id: int
    complete: bool
    history: tuple[str, ...]
    validation: str | None
    static_text_overlay: Mapping
    name_allocations: tuple[str, ...]
    static_names: tuple[str, ...]
    name_controls: tuple
    selector_control: object | None
    _retained_parent_names: bool = field(repr=False, compare=False)
    _source_profile_identity_verified: bool = field(repr=False, compare=False)
    _origin: _Origin = field(repr=False, compare=False)
    _inventory_cursor: object | None = field(default=None, repr=False, compare=False, kw_only=True)
    _selector_bound_collection: tuple[int, str] | None = field(default=None, repr=False, compare=False, kw_only=True)
    _button_selected_trigger: tuple[str, str] | None = field(default=None, repr=False, compare=False, kw_only=True)

    def __post_init__(self):
        object.__setattr__(self, 'static_text_overlay', MappingProxyType(dict(self.static_text_overlay)))
        object.__setattr__(self, 'name_allocations', tuple(self.name_allocations))
        checked_names(self.static_names)
        from .edlt_scene_name_control import SceneNameControlState
        if (type(self.name_controls) is not tuple or len(self.name_controls) != 8
                or any(control is not None and type(control) is not SceneNameControlState
                       for control in self.name_controls)):
            raise EdltError('SceneManager requires eight internal name-control states')
        from .edlt_scene_selector_control import SceneSelectorControlState
        if self.selector_control is not None and type(self.selector_control) is not SceneSelectorControlState:
            raise EdltError('SceneManager requires an internal global selector-control state')
        if self._inventory_cursor is not None:
            from .edlt_scene_inventory_timeline import check_cursor
            check_cursor(self._inventory_cursor, owner=self._origin.owner)
        if self._selector_bound_collection is not None:
            row = self._selector_bound_collection
            if (self._inventory_cursor is None or type(row) is not tuple or len(row) != 2
                    or type(row[0]) is not int or not 0 <= row[0] <= 255
                    or type(row[1]) is not str or len(row[1]) != 64
                    or any(char not in '0123456789abcdef' for char in row[1])):
                raise EdltError('SceneManager requires an internal source-bound collection generation')
        if self._button_selected_trigger is not None:
            row = self._button_selected_trigger
            if type(row) is not tuple or len(row) != 2 or any(type(v) is not str or not v or '\0' in v for v in row):
                raise EdltError('SceneManager requires an internal selected CBusGroup identity')

    def static_text_evidence(self):
        overlay = {name: list(value) for name, value in self.static_text_overlay.items()}
        allocations = [json.loads(value) for value in self.name_allocations]
        document = {'overlay_changes': overlay, 'allocations': allocations}
        return {**document, 'fingerprint': hashlib.sha256(_json(document).encode()).hexdigest(),
                'allocation_order': 'scene operation order',
                'allocator': 'historical additive or source SceneName property, as recorded per allocation'}

    def names_view(self):
        return scene_names_view(self.static_names, tuple(scene.name_index for scene in self.scenes))

    def as_dict(self):
        total = sum(len(s.items) for s in self.scenes)
        result = dict(format='cbus-edlt-scene-manager-state-v1', scope='model', complete=self.complete,
            scenes=[{**s.as_dict(), 'scene_name': scene_name(self.static_names, s.name_index)} for s in self.scenes],
            static_names=list(self.static_names), scene_names_view=list(self.names_view()),
            fixed_suggestion_names=list(FIXED_SUGGESTION_NAMES), suggestion_order_inferred=False,
            scene_name_controls=[None if control is None else control.as_dict() for control in self.name_controls],
            pending_name_controls=any(control is not None and control.pending for control in self.name_controls),
            scene_selector_control=None if self.selector_control is None else self.selector_control.as_dict(),
            button_selected_trigger=(None if self._button_selected_trigger is None else
                {'identity': self._button_selected_trigger[0], 'address': self._button_selected_trigger[1]}),
            clipboard=None if self.clipboard is None else self.clipboard.as_dict(),
            item_count=total, storage_used_percent=100 * total * 3 // 191,
            operations=[json.loads(v) for v in self.history], validation=None if self.validation is None else json.loads(self.validation),
            static_text=self.static_text_evidence(), static_text_allocated=bool(self.name_allocations),
            retained_group_references=True, metadata_created=False, cache_freshness_verified=False,
            full_form_validation_verified=False, physical_device_verified=False, model_state_resumption_supported=False, saved=False)
        if self._inventory_cursor is not None:
            result['inventory_timeline'] = self._inventory_cursor.as_dict()
        return result


@dataclass(frozen=True)
class SceneEditOutcome:
    state: SceneManagerState
    complete: bool
    operation_results: tuple[str, ...]

    def as_dict(self):
        return dict(complete=self.complete, state=self.state.as_dict(), operation_results=[json.loads(v) for v in self.operation_results], saved=False)


@dataclass(frozen=True)
class SceneSelectorViewOutcome:
    state: SceneManagerState
    _view_json: str

    def as_dict(self):
        return {'view': json.loads(self._view_json), 'state': self.state.as_dict(), 'saved': False}


@dataclass(frozen=True)
class SceneValidationOutcome:
    state: SceneManagerState
    valid: bool
    warnings: tuple[str, ...]
    skipped_slots: tuple[int, ...]

    def as_dict(self):
        return dict(valid=self.valid, warnings=list(self.warnings), skipped_slots=list(self.skipped_slots),
            state=self.state.as_dict(), validation_scope='original ValidateScenes only', save_blocking=False,
            full_form_validation_verified=False, saved=False)


@dataclass(frozen=True)
class SceneManagerPlan:
    source: SceneManagerState
    terminal: SceneManagerState
    expected: Mapping
    after_load: Mapping
    before_save: Mapping
    changes: Mapping
    validation: str
    _origin: _Origin = field(repr=False, compare=False)

    def __post_init__(self):
        for key in ('expected', 'after_load', 'before_save', 'changes'):
            object.__setattr__(self, key, MappingProxyType(dict(getattr(self, key))))

    def as_dict(self):
        static_text = self.terminal.static_text_evidence()
        return dict(format='cbus-edlt-scene-manager-plan-v1', scope='model', unit_type='KEYGL5', catalog_number='5055EDL', firmware='5.5.00',
            source=self.source.as_dict(), terminal=self.terminal.as_dict(), validation=json.loads(self.validation),
            phases={'after_load': _delta(self.expected, self.after_load), 'before_save': _delta(self.after_load, self.before_save),
                    'crc': _delta(self.before_save, {**self.expected, **self.changes})},
            changes={k: list(v) if isinstance(v, tuple) else v for k, v in self.changes.items()},
            crc_projection={'original_scene_bucket_tokens': 233 if sum(len(s.items) for s in self.terminal.scenes) == 64 else 232,
                'native_scene_bucket_bytes': 232, 'original_trailing_ff_in_crc_image': sum(len(s.items) for s in self.terminal.scenes) == 64,
                'temporary_crc_tail_logical_address': 0x21fa if sum(len(s.items) for s in self.terminal.scenes) == 64 else None,
                'native_pp_only_crc_matches_original': sum(len(s.items) for s in self.terminal.scenes) != 64},
            scene_pointers=[self.before_save[f'Scene{slot}StartAddress'][0] for slot in range(1, 9)],
            static_text=static_text, metadata_created=False, static_text_allocated=bool(static_text['allocations']), physical_device_verified=False,
            full_form_validation_verified=False, incomplete_edit_persisted=False, saved=False)


@dataclass(frozen=True)
class SceneManagerComposition:
    """Issued scene-only projection for one enclosing parent transaction."""
    source: SceneManagerState
    terminal: SceneManagerState
    fields: Mapping
    validation: str
    item_count: int
    _origin: _Origin = field(repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, 'fields', MappingProxyType(dict(self.fields)))

    def as_dict(self):
        return {
            'format': 'cbus-edlt-scene-manager-composition-v1',
            'scope': 'retained scene graph and static-name control projection',
            'scene_fields': {
                name: list(value) if isinstance(value, tuple) else value
                for name, value in self.fields.items()
            },
            'scene_pointers': [
                self.fields[f'Scene{slot}StartAddress'][0]
                for slot in range(1, 9)
            ],
            'item_count': self.item_count,
            'full_capacity_temporary_crc_tail': self.item_count == 64,
            'validation': json.loads(self.validation),
            'static_text': self.terminal.static_text_evidence(),
            'terminal_scene_models': [
                {**scene.as_dict(), 'scene_name': scene_name(self.terminal.static_names, scene.name_index)}
                for scene in self.terminal.scenes
            ],
            'static_names': list(self.terminal.static_names),
            'scene_names_view': list(self.terminal.names_view()),
            'scene_selector_control': (None if self.terminal.selector_control is None
                                       else self.terminal.selector_control.as_dict()),
            'terminal_save_deferred_to_parent': True,
            'terminal_crc_deferred_to_parent': True,
            'complete_scene_cache_required': True,
            'full_form_validation_verified': False,
            'physical_device_verified': False,
            'saved': False,
        }


class EdltSceneManager:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.lifecycle = EdltLifecycle(spec, catalog_number=catalog_number, firmware=firmware)
        self.common, self.spec, self.codec = self.lifecycle.common, spec, self.lifecycle.codec
        self._owner = object()
        self.last_evidence = None

    def snapshot(self, values): return self.lifecycle.snapshot(values)

    def _fingerprint(self, value):
        extra = {'expected': dict(value.loaded.expected), 'cache': value.cache.as_dict(),
                 'next_item_id': value.next_item_id,
                 'retained_parent_names': value._retained_parent_names,
                 'source_profile_identity_verified': value._source_profile_identity_verified,
                 'inventory_cursor': None if value._inventory_cursor is None else value._inventory_cursor.fingerprint,
                 'selector_bound_collection': value._selector_bound_collection,
                 'button_selected_trigger': value._button_selected_trigger} if type(value) is SceneManagerState else {}
        return hashlib.sha256(_json({'value': value.as_dict(), **extra}).encode()).hexdigest()

    def _check(self, value, expected_type=SceneManagerState):
        if (type(value) is not expected_type or type(value._origin) is not _Origin or value._origin.owner is not self._owner
                or value._origin.reference is None or value._origin.reference() is not value
                or value._origin.fingerprint != self._fingerprint(value)):
            raise EdltError('Use an intact scene object issued by this EdltSceneManager instance; exports are review-only')

    def _seal(self, value):
        value._origin.reference = weakref.ref(value); value._origin.fingerprint = self._fingerprint(value)
        return value

    def _next(self, state, **kwargs):
        return self._seal(replace(state, _origin=_Origin(self._owner), **kwargs))

    @staticmethod
    def _inventory_advance(state, *, phase, operation=None, callback=0, scene=0):
        """Observe one admitted causal boundary without issuing a new model."""
        cursor = state._inventory_cursor
        if cursor is None:
            return state
        cursor = cursor.advance(operation=operation, phase=phase,
                                callback=callback, scene=scene)
        return replace(state, cache=cursor.cache, _inventory_cursor=cursor)

    @staticmethod
    def _inventory_branch(state, phase):
        cursor = state._inventory_cursor
        if cursor is None:
            return state
        cursor = cursor.validation() if phase == 'validation' else cursor.before_save()
        return replace(state, cache=cursor.cache, _inventory_cursor=cursor)

    def load(self, values, *, metadata, scope='model'):
        if scope != 'model': raise EdltError('Only retained model scope is implemented; full SceneManager control binding is separate')
        cursor = None
        if type(metadata) is SceneManagerCache and metadata._inventory_timeline is not None:
            from .edlt_scene_inventory_timeline import check_timeline
            check_timeline(metadata._inventory_timeline)
            cursor = metadata._inventory_timeline.start(
                metadata, source_values=self.snapshot(values), owner=self._owner)
            cache = cursor.cache
        else:
            cache = SceneManagerCache.from_dict(metadata.as_dict() if type(metadata) is SceneManagerCache else metadata)
        loaded = self.lifecycle.load(values, metadata=cache.application_cache.lifecycle)
        from .edlt_static_grid import current as current_static_grid
        parent_grid = current_static_grid(loaded.after_load)
        names = load_names(loaded.after_load) if parent_grid is None else tuple(parent_grid.names)
        scenes, next_id = [], 1
        for s in loaded.scenes:
            # LoadScenes attaches DynamicAll at each scene's action setter. A
            # later native creation can replace every Level without refreshing
            # an earlier scene's retained object list.
            labels = (cursor.initial_scene_labels(s.slot) if cursor is not None
                      else cache.labels(s.trigger.group, s.action_selector)
                      if s.trigger.group != 255 and s.action_selector >= 0 else ())
            items = tuple(SceneManagerItem(next_id + i, v.group, v.ramp_rate, v.can_edit, v.level) for i, v in enumerate(s.items))
            next_id += len(items)
            scenes.append(SceneManagerScene(s.slot, s.primary_secondary, s.can_edit, s.trigger.group, s.action_selector, s.name_index, items, 0, labels))
        state = SceneManagerState(loaded, cache, tuple(scenes), None, next_id, True,
                                  (), None, {}, (), names, (None,) * 8, None, parent_grid is not None,
                                  False, _Origin(self._owner), _inventory_cursor=cursor)
        return self._seal(state)

    def retained_names(self, state):
        """Return the complete name table only from this owner's intact model."""
        self._check(state)
        return state.static_names

    def scene_name(self, state, *, scene):
        self._check(state); _int(scene, 'Scene', 1, 8)
        return scene_name(state.static_names, state.scenes[scene - 1].name_index)

    def load_export(self, document, *, metadata, scope='model'):
        """Load an exact identity-bearing KEYGL5 parameter export.

        The ordinary model loader accepts raw mappings for offline editing. A
        live retained-scene trigger requires the export envelope so its profile
        evidence comes from supplied identity fields rather than the selected
        decoder alone.
        """
        fields = {'format', 'unit_type', 'firmware', 'catalog_number', 'parameters'}
        profile = tuple(document.get(name) for name in
                        ('format', 'unit_type', 'firmware', 'catalog_number')) \
            if isinstance(document, Mapping) else ()
        if (not isinstance(document, Mapping) or set(document) != fields or
                profile != ('cbus-cli-parameters-v1', 'KEYGL5', '5.5.00', '5055EDL') or
                not isinstance(document.get('parameters'), Mapping)):
            raise EdltError('Live scene trigger requires an exact identity-bearing parameter export for KEYGL5 / 5055EDL / 5.5.00')
        state = self.load(document['parameters'], metadata=metadata, scope=scope)
        return self._next(state, _source_profile_identity_verified=True)

    @staticmethod
    def _scene_static_view(state, scenes, overlay):
        """Place current scene names into a full after-load snapshot for allocation."""
        values = dict(state.loaded.after_load); values.update(overlay)
        bucket, pointers = bytearray(), []
        for scene in scenes:
            pointers.append(len(bucket))
            action = 255 if scene.raw_action < 0 else scene.raw_action
            bucket.extend((scene.primary_secondary + 2 * int(scene.can_edit), len(scene.items),
                           scene.raw_trigger, action, scene.name_index))
            for item in scene.items:
                bucket.extend((16 * int(item.can_edit) + item.ramp_rate, item.group.group, item.level))
        if len(bucket) > 232:
            raise EdltError('Retained scene data exceeds the 232-byte native PP layout')
        values['SceneCount'] = (8,); values['SceneBucket'] = tuple(bucket.ljust(232, b'\xff'))
        for slot, pointer in enumerate(pointers, 1): values[f'Scene{slot}StartAddress'] = (pointer,)
        return values

    @staticmethod
    def _group(state, application, group):
        fact = (state.cache.application_cache.lifecycle.find(application, group)
                if state._inventory_cursor is not None else state.loaded.metadata.find(application, group))
        if fact is None:
            presence = state.cache.application_cache.group_presence(application, group)
            if presence is False: return None
            raise LifecycleMetadataError('Explicit group presence facts are required', {'application': application, 'group': group}, original_stage='scene-group-getter')
        return fact if fact.exists else None

    def _trigger(self, state, scene):
        group = self._group(state, 202, scene.raw_trigger)
        if group is None: scene = replace(scene, raw_trigger=255)
        return scene, scene.raw_trigger

    def _set_action(self, state, scene, value):
        scene, trigger = self._trigger(state, scene)
        if trigger == 255: return scene
        group = self._group(state, 202, trigger)
        if group.levels is None:
            raise LifecycleMetadataError('Explicit complete trigger levels are required', {'application': 202, 'group': trigger, 'field': 'levels'}, original_stage='scene-action-getter')
        action = value if value in group.levels else -1
        return replace(scene, raw_action=action, dynamic_labels=() if action < 0 else state.cache.labels(trigger, action))

    def _action(self, state, scene):
        scene, trigger = self._trigger(state, scene)
        if trigger == 255: return scene, -1
        group = self._group(state, 202, trigger)
        if group.levels is None:
            raise LifecycleMetadataError('Explicit complete trigger levels are required', {'application': 202, 'group': trigger, 'field': 'levels'}, original_stage='scene-action-getter')
        if scene.raw_action == -1 or scene.raw_action not in group.levels: scene = self._set_action(state, scene, -1)
        return scene, scene.raw_action

    @staticmethod
    def _selector_context(state, scene):
        """Limit new selector getters to the actual ordered inventory position.

        The outer parent lifecycle may include later objects. Those positive
        facts cannot establish the earlier SceneManager choice collection.
        This temporary getter context is never issued as a loaded model.
        """
        choices = trigger_choices(state.cache)
        trigger = scene.raw_trigger
        if trigger == 255:
            return state
        present = any(row['value'] == trigger for row in choices)
        old = state.loaded.metadata.find(202, trigger)
        if present:
            action_list = next((row for row in state.cache.action_lists if row.group == trigger), None)
            levels = (tuple(row.address for row in action_list.actions)
                      if action_list is not None and action_list.complete else None)
            fact = LifecycleGroup(202, trigger, True,
                old.dynamic_images if old is not None else None,
                old.dynamic_images_known if old is not None else False, levels)
        else:
            fact = LifecycleGroup(202, trigger, False)
        groups = tuple(row for row in state.loaded.metadata.groups
                       if (row.application, row.group) != (202, trigger)) + (fact,)
        metadata = LifecycleCache(state.loaded.metadata.applications, groups)
        return replace(state, loaded=replace(state.loaded, metadata=metadata))

    def _selector_observation(self, state, scene, *, getter=False, refresh=False, actions=None):
        context = self._selector_context(state, scene)
        scene, _ = self._trigger(context, scene)
        observed = scene.raw_action
        if getter:
            scene, observed = self._action(context, scene)
        if refresh:
            # The trigger CurrentChanged handler refreshes even when the
            # action getter was valid and therefore did not call its setter.
            labels = (() if scene.raw_trigger == 255 or observed < 0
                      else state.cache.labels(scene.raw_trigger, observed))
            scene = replace(scene, dynamic_labels=labels)
        view = retained_view(state.cache, scene,
            primary=state.loaded.after_load['PrimaryApplication'][0],
            secondary=state.loaded.after_load['SecondaryApplication'][0], actions=actions)
        if getter:
            view.update(action_selector=observed, action_getter_observed=True,
                        retained_fields_only=False, trigger_editable=scene.raw_trigger != 255,
                        action_editable=scene.raw_trigger != 255 and observed >= 0,
                        property_getters=['TriggerGroup', 'ActionSelector'])
        return scene, view

    def selector_view(self, state, *, scene):
        """Issue a complete selector view after the source property getters."""
        outcome = self.edit(state, operations=[{'op': 'get-selector-view', 'scene': scene}])
        view = json.loads(outcome.operation_results[0])['view']
        return SceneSelectorViewOutcome(outcome.state, _json(view))

    @staticmethod
    def _uses_selector_inventory(state):
        return any(json.loads(row)['op'] in ('get-selector-view', 'scene-selector-control', 'scene-button-control')
                   for row in state.history)

    def available_groups(self, state, *, scene):
        self._check(state); _int(scene, 'Scene', 1, 8)
        selected = state.scenes[scene - 1]
        app = state.loaded.after_load['PrimaryApplication' if selected.primary_secondary == 0 else 'SecondaryApplication'][0]
        choices = state.cache.application_cache.group_choices(app)
        used = {(v.group.application, v.group.group) for v in selected.items}
        return tuple(v for v in choices if v.address != 255 and (app, v.address) not in used)

    def live_items(self, state, *, scene):
        """Return intact retained references without resolving the scene selector."""
        self._check(state); _int(scene, 'Scene', 1, 8)
        if not state.complete:
            raise EdltError('An incomplete scene state is review-only')
        return state.scenes[scene - 1].items

    def live_trigger(self, state, *, scene):
        """Resolve one retained Trigger Control binding for live invocation.

        The resolution deliberately follows the retained model's trigger and
        action getters.  It performs no metadata creation, state mutation or
        network I/O.
        """
        self._check(state); _int(scene, 'Scene', 1, 8)
        if state._source_profile_identity_verified is not True:
            raise EdltError('Live scene trigger requires an exact identity-bearing parameter export')
        if not state.complete:
            raise EdltError('An incomplete scene state is review-only')
        selected, trigger = self._trigger(state, state.scenes[scene - 1])
        if trigger == 255:
            raise EdltError('The selected scene has no enabled trigger group')
        selected, action = self._action(state, selected)
        if action < 0:
            raise EdltError('The selected scene has no valid action selector')
        _int(trigger, 'Trigger group', 0, 254)
        _int(action, 'Action selector')
        return trigger, action

    def capture_levels(self, state, *, scene, readings, finished):
        """Issue an immutable captured prefix; failed observations block saving.

        This pure transition does no network I/O. The caller supplies observed
        levels and their verification facts in the exact retained item order.
        """
        items = self.live_items(state, scene=scene)
        if type(finished) is not bool:
            raise EdltError('Capture finished must be boolean')
        rows = tuple(_array(readings, 64, 'Capture readings'))
        if any(type(v) is not SceneCaptureLevel for v in rows):
            raise EdltError('Capture readings require SceneCaptureLevel records')
        for row in rows:
            # Recheck fields even if a frozen record was modified by reflection.
            SceneCaptureLevel(row.item_id, row.level, row.verified)
        if (len(rows) > len(items) or any(row.item_id != item.item_id for row, item in zip(rows, items))
                or finished and len(rows) != len(items)):
            raise EdltError('Capture readings must match the selected scene item prefix')
        if len(state.history) >= MAX_OPERATIONS:
            raise EdltError('Scene history exceeds 256 operations')
        replacement = tuple(replace(item, level=rows[i].level) if i < len(rows) else item
                            for i, item in enumerate(items))
        scenes = list(state.scenes)
        scenes[scene - 1] = replace(scenes[scene - 1], items=replacement)
        complete = finished and all(row.verified for row in rows)
        record = dict(op='capture-levels', scene=scene, readings=[row.as_dict() for row in rows],
                      finished=finished, complete=complete, observation_source='supplied', physical_device_verified=False)
        return self._next(state, scenes=tuple(scenes), complete=complete,
                          history=(*state.history, _json(record)), validation=None)

    @staticmethod
    def _operation(operation):
        if not isinstance(operation, Mapping) or not isinstance(operation.get('op'), str): raise EdltError('Scene operation requires an op field')
        op = dict(operation); kind = op['op']
        if kind in ('add-trigger-dialog', 'add-action-dialog'):
            from .edlt_scene_add_dialog import normalize
            return normalize(op)
        if kind == 'scene-name-control':
            from .edlt_scene_name_control import normalize_operation
            return normalize_operation(op)
        if kind == 'scene-selector-control':
            from .edlt_scene_selector_control import normalize_operation
            return normalize_operation(op)
        if kind == 'scene-button-control':
            from .edlt_scene_button_control import normalize_operation
            return normalize_operation(op)
        fields = {'set-application': ('selector',), 'add-groups': ('groups',), 'remove-items': ('item_ids',),
            'clear-items': (), 'copy': (), 'paste': (), 'clear-scene': (), 'set-level': ('item_id', 'level'),
            'set-percent': ('item_id', 'percent'), 'set-ramp': ('item_id', 'ramp_rate'), 'sync-levels': ('item_id',),
            'set-trigger': ('group',), 'set-action': ('action',), 'set-name-index': ('index',),
            'set-name-text': ('text',), 'get-name': (), 'get-trigger': (), 'get-action': (),
            'get-selector-view': ()}
        if kind not in fields or set(op) != {'op', 'scene', *fields[kind]}: raise EdltError('Invalid scene operation or fields')
        _int(op['scene'], 'Scene', 1, 8)
        for key, maximum in (('selector', 1), ('level', 255), ('percent', 100), ('ramp_rate', 15), ('group', 255), ('action', 255), ('index', 255)):
            if key in op: _int(op[key], key, 0, maximum)
        if 'index' in op and 64 <= op['index'] < 255: raise EdltError('Scene name index must be 0..63 or 255')
        if 'text' in op:
            text = op['text']
            if not isinstance(text, str) or not text.strip() or '\0' in text:
                raise EdltError('Static label text must be nonblank and contain no NUL; use set-name-index 255 to detach')
            try: encoded = text.encode('utf-8')
            except UnicodeEncodeError as error: raise EdltError('Static label text must be valid Unicode') from error
            if len(encoded) > 63:
                from .edlt_static_grid import _parent_history_active
                if not _parent_history_active():
                    raise EdltError('Static label text exceeds63UTF-8 bytes; truncation is not permitted')
                # A parent shape pass runs before its actual ordered cache.
                # Allocation later admits only a real earlier retained Name;
                # an unmatched or future long name still fails the63-byte gate.
        if 'item_id' in op: _int(op['item_id'], 'Item identity', 1, 65536)
        for key, maximum in (('groups', 254), ('item_ids', 65536)):
            if key in op:
                vals = tuple(_array(op[key], 256, key))
                if not vals: raise EdltError(key + ' cannot be empty')
                for v in vals: _int(v, key, 1 if key == 'item_ids' else 0, maximum)
                if len(set(vals)) != len(vals): raise EdltError('Duplicate ' + key)
                op[key] = vals
        return op

    def edit(self, state, *, operations):
        self._check(state)
        if not state.complete: raise EdltError('Incomplete scene state is review-only; branch from a prior complete state')
        ops = tuple(self._operation(v) for v in _array(operations, MAX_OPERATIONS, 'Scene operations'))
        if any(row['op'] in ('add-trigger-dialog', 'add-action-dialog') for row in ops):
            raise EdltError('SceneManager Add dialogs require the automatic --project-xml/--auto-metadata workflow')
        if len(state.history) + len(ops) > MAX_OPERATIONS: raise EdltError('Scene history exceeds 256 operations')
        scenes, clipboard, next_id, results, complete = list(state.scenes), state.clipboard, state.next_item_id, [], True
        overlay, allocations = dict(state.static_text_overlay), list(state.name_allocations)
        names, controls = list(state.static_names), list(state.name_controls)
        selector_control = state.selector_control
        bound_collection = state._selector_bound_collection
        button_selected_trigger = state._button_selected_trigger
        selector_inventory = (self._uses_selector_inventory(state)
                              or any(row['op'] in ('get-selector-view', 'scene-selector-control', 'scene-button-control') for row in ops))
        def getter_state(scene):
            return self._selector_context(state, scene) if selector_inventory else state
        for op in ops:
            kind, slot = op['op'], op['scene']
            state = self._inventory_advance(state, phase='operation-start', operation=op, scene=slot)
            s = scenes[slot - 1]; result = {'operation': op, 'complete': True}
            if kind == 'set-application':
                if op['selector'] == 1 and state.loaded.after_load['SecondaryApplication'] == (255,): raise EdltError('Secondary scene application is disabled')
                s = replace(s, primary_secondary=op['selector'])
            elif kind == 'add-groups':
                app = state.loaded.after_load['PrimaryApplication' if s.primary_secondary == 0 else 'SecondaryApplication'][0]
                choices = state.cache.application_cache.group_choices(app)
                allowed = {g.address for g in choices if g.address != 255} - {v.group.group for v in s.items if v.group.application == app}
                if not set(op['groups']) <= allowed: raise EdltError('Requested group is unavailable or already used as the same cache object')
                groups = [self._group(state, app, n) for n in op['groups']]
                if any(g is None for g in groups): raise EdltError('Available group has no present cache object')
                added = []
                for group in groups:
                    if sum(len(v.items) for v in scenes) - len(scenes[slot - 1].items) + len(s.items) >= 64: complete = False; break
                    item = SceneManagerItem(next_id, group, 0, True, 0); next_id += 1; added.append(item.item_id)
                    s = replace(s, items=(*s.items, item))
                result.update(added_item_ids=added, requested_count=len(groups), applied_count=len(added))
            elif kind == 'remove-items':
                if not set(op['item_ids']) <= {v.item_id for v in s.items}: raise EdltError('Removed item identity is not in the selected scene')
                s = replace(s, items=tuple(v for v in s.items if v.item_id not in op['item_ids']))
            elif kind == 'clear-items': s = replace(s, items=())
            elif kind in ('copy', 'paste', 'clear-scene'):
                if kind == 'paste' and clipboard is None: raise EdltError('Copy a scene before pasting')
                source = s if kind == 'copy' else clipboard if kind == 'paste' else SceneManagerScene(256, 0, True, 255, -1, 255, ())
                context = getter_state(source)
                source, trigger = self._trigger(context, source); source, action = self._action(context, source)
                if kind == 'copy': scenes[slot - 1] = source
                target = SceneManagerScene(256, 0, True, 255, -1, 255, ()) if kind == 'copy' else s
                target = replace(target, primary_secondary=source.primary_secondary, can_edit=source.can_edit,
                    raw_trigger=trigger, raw_action=action, name_index=source.name_index, items=())
                copied = []
                for item in source.items:
                    if kind != 'copy' and sum(len(v.items) for v in scenes) - len(s.items) + len(target.items) >= 64: complete = False; break
                    new = replace(item, item_id=next_id, can_edit=True); next_id += 1; copied.append(new.item_id)
                    target = replace(target, items=(*target.items, new))
                result.update(copied_item_ids=copied, requested_count=len(source.items), applied_count=len(copied))
                if kind == 'copy': clipboard = target; s = source
                else: s = target
            elif kind in ('set-level', 'set-percent', 'set-ramp', 'sync-levels'):
                index = next((i for i, v in enumerate(s.items) if v.item_id == op['item_id']), None)
                if index is None: raise EdltError('Item identity is not in the selected scene')
                items = list(s.items)
                if kind == 'sync-levels': items = [replace(v, level=items[index].level) for v in items]
                else:
                    key, value = ('ramp_rate', op['ramp_rate']) if kind == 'set-ramp' else ('level', op['level'] if kind == 'set-level' else op['percent'] * 255 // 100)
                    items[index] = replace(items[index], **{key: value})
                s = replace(s, items=tuple(items))
            elif kind == 'set-trigger': s = replace(s, raw_trigger=op['group'])
            elif kind == 'set-action': s = self._set_action(getter_state(s), s, op['action'])
            elif kind == 'set-name-index': s = replace(s, name_index=op['index'])
            elif kind == 'set-name-text':
                # Match ordered model-property edits. Detach this scene's old
                # reference before allocation; unrelated and earlier operation
                # references remain reserved in the staged current view.
                scenes[slot - 1] = replace(s, name_index=255)
                view = self._scene_static_view(state, scenes, overlay)
                with isolated_additive_cache(view, tuple(names), retained=state._retained_parent_names) as local:
                    allocation = self.common.allocate_static_text(view, op['text'])
                    if local is not None:
                        names[:] = local.names
                    elif not allocation.reused:
                        names[allocation.index] = op['text']
                overlay.update(allocation.changes)
                s = replace(scenes[slot - 1], name_index=allocation.index)
                evidence = {'sequence': len(allocations) + 1,
                            'operation_number': len(state.history) + len(results) + 1,
                            'scene': slot, **allocation.as_dict()}
                allocations.append(_json(evidence)); result['static_text_allocation'] = evidence
            elif kind == 'get-name':
                result['value'] = scene_name(tuple(names), s.name_index)
            elif kind == 'get-selector-view':
                s, result['view'] = self._selector_observation(state, s, getter=True)
            elif kind == 'scene-button-control':
                from .edlt_scene_button_control import issue_button_context, run_scene_button_control
                if state._inventory_cursor is None:
                    raise EdltError('Scene Add buttons require an owner-issued automatic native inventory timeline')
                binding = json.loads(state._inventory_cursor.timeline._binding)
                number = len(state.history) + len(results) + 1
                recorded = [row for row in binding['add_dialogs']
                            if row.get('operation_number') == number and row.get('button_operation') == op]
                if len(recorded) != 1:
                    raise EdltError('Scene Add button lacks its exact owner-issued callback history')
                expected_button = recorded[0]['button_control']
                current = None if selector_control is None else selector_control.current_scene
                owner_view = {} if selector_control is None else selector_control.as_dict()['view']
                def items(field):
                    if field == 'trigger_items':
                        rows = trigger_choices(state.cache)
                    else:
                        rows = owner_view.get('action_choices' if field == 'action_items' else 'application_choices', [])
                    return [{'identity': row['identity'], 'value': str(row['value']), 'name': row['name']} for row in rows]
                source_pin = hashlib.sha256(_json(dict(state.loaded.expected)).encode()).hexdigest()
                history_pin = hashlib.sha256(_json({'operation': op, 'operation_number': number}).encode()).hexdigest()
                context = issue_button_context(owner=self._owner, source_fingerprint=source_pin,
                    history_fingerprint=history_pin, scene=slot,
                    current_scene=current, selected_scene_count=len(op.get('selected_scenes', [slot])),
                    primary_application=state.loaded.after_load['PrimaryApplication'][0],
                    secondary_application=state.loaded.after_load['SecondaryApplication'][0],
                    application_selector=0 if current is None else scenes[current - 1].primary_secondary,
                    raw_trigger_group=s.raw_trigger,
                    selected_trigger_group=(None if button_selected_trigger is None else
                        {'identity': button_selected_trigger[0], 'address': button_selected_trigger[1]}),
                    trigger_items=items('trigger_items'), action_items=items('action_items'), application_items=items('application_items'))
                callback_number = 0
                def request(action, *arguments):
                    nonlocal state, callback_number
                    expected = expected_button['request']
                    if expected is None or expected['action'] != action or expected['arguments'] != list(arguments):
                        raise EdltError('Scene Add button request differs from its issued source callback')
                    callback_number += 1
                    state = self._inventory_advance(state, phase='button-request', callback=callback_number, scene=slot)
                    return expected['returned_value']
                def button_ui(action, facts):
                    nonlocal state, callback_number, button_selected_trigger, selector_control
                    if action == 'SetSelectedIndex' and facts['control'] == 'trigger':
                        button_selected_trigger = (facts['item']['identity'], facts['item']['value'])
                    if action == 'WriteValue':
                        target = facts['binding_scene']
                        if target is None:
                            raise EdltError('Button SelectedValue needs an explicit current Scene binding')
                        trigger = facts['control'] == 'trigger'
                        callback_number += 1
                        state = self._inventory_advance(state,
                            phase='button-write-trigger' if trigger else 'button-write-application', callback=callback_number, scene=target)
                        scenes[target - 1] = replace(scenes[target - 1],
                            **({'raw_trigger': int(facts['item']['value'])} if trigger
                               else {'primary_secondary': int(facts['item']['value'])}))
                        if selector_control is not None:
                            from .edlt_scene_selector_control import update_selector_properties
                            selector_control = update_selector_properties(selector_control, target,
                                trigger_group=scenes[target - 1].raw_trigger if trigger else None,
                                application_selector=scenes[target - 1].primary_secondary if not trigger else None)
                button = run_scene_button_control(op, context=context, owner=self._owner,
                    source_fingerprint=source_pin, history_fingerprint=history_pin,
                    request_add_group=lambda app: request('AddGroupRequest', app),
                    request_add_level=lambda app, group: request('AddLevelRequest', app, group),
                    ui_callback=button_ui, observe_items=items)
                if button.as_dict() != expected_button:
                    raise EdltError('Scene Add button replay differs from its issued callback receipt')
                result['scene_button_control'] = button.as_dict()
                s = scenes[slot - 1]
            elif kind == 'scene-selector-control':
                from .edlt_scene_selector_control import run_scene_selector_control
                # One source form retains one direct scene binding. A later
                # outer operation can have a different scene while WriteValue
                # still targets the old bound scene after Current becomes null.
                bound_actions = ([] if selector_control is None else
                                 selector_control.as_dict()['view'].get('action_choices', []))
                callback_number = 0
                def advance(phase, target):
                    nonlocal state, callback_number
                    callback_number += 1
                    state = self._inventory_advance(state, phase=phase,
                        callback=callback_number, scene=target)
                def observe(target, *, getter=False, refresh=False, rebind=False):
                    nonlocal bound_actions
                    current, view = self._selector_observation(state, scenes[target - 1],
                        getter=getter, refresh=refresh,
                        actions=None if rebind else bound_actions)
                    scenes[target - 1] = current
                    if rebind:
                        bound_actions = view['action_choices']
                    return view
                def bind_scene(target):
                    nonlocal bound_collection
                    advance('bind-scene', target)
                    view = observe(target, rebind=True)
                    if state._inventory_cursor is not None:
                        group = scenes[target - 1].raw_trigger
                        bound_collection = (group, state._inventory_cursor.collection_generation(group))
                    return view
                def bound_rows():
                    if (state._inventory_cursor is not None and bound_collection is not None
                            and state._inventory_cursor.collection_generation(bound_collection[0]) == bound_collection[1]):
                        return action_choices(state.cache, bound_collection[0])
                    return bound_actions
                def trigger_current(target):
                    nonlocal bound_actions
                    advance('trigger-current', target)
                    # A native creation may replace the collection already
                    # bound by this handler. Only an explicit rebind admits
                    # rows from the new generation; no host refresh is guessed.
                    if state._inventory_cursor is not None:
                        bound_actions = bound_rows()
                    return observe(target, getter=True, refresh=True)
                def write_application(target, value):
                    advance('write-application', target)
                    if value not in (0, 1) or value == 1 and state.loaded.after_load['SecondaryApplication'] == (255,):
                        raise EdltError('Secondary scene application is disabled')
                    scenes[target - 1] = replace(scenes[target - 1], primary_secondary=value)
                    return retained(target)
                def retained(target, *, actions=None):
                    return retained_view(state.cache, scenes[target - 1],
                        primary=state.loaded.after_load['PrimaryApplication'][0],
                        secondary=state.loaded.after_load['SecondaryApplication'][0],
                        actions=bound_actions if actions is None else actions)
                def write_trigger(target, value):
                    nonlocal button_selected_trigger
                    advance('write-trigger', target)
                    button_selected_trigger = (f'trigger:202/{value}', str(value))
                    scenes[target - 1] = replace(scenes[target - 1], raw_trigger=value)
                    return retained(target)
                def write_action(target, value):
                    advance('write-action', target)
                    current = scenes[target - 1]
                    context = self._selector_context(state, current)
                    scenes[target - 1] = self._set_action(context, current, value)
                    actions = (None if state._inventory_cursor is None else bound_rows())
                    return retained(target, actions=actions)
                def write_label_index(target, value):
                    advance('write-label', target)
                    scenes[target - 1] = replace(scenes[target - 1], label_value_index=value)
                    return retained(target)
                def observe_choices(field, target, source_trigger):
                    if field == 'action_choices':
                        if state._inventory_cursor is not None:
                            return bound_rows()
                        return action_choices(state.cache, source_trigger)
                    return retained(target)[field]
                control = run_scene_selector_control(op['events'], scene=slot,
                    bind_scene=bind_scene, trigger_current=trigger_current,
                    write_application=write_application, write_trigger=write_trigger,
                    write_action=write_action, write_label_index=write_label_index,
                    observe_choices=observe_choices, initial_state=selector_control)
                selector_control = control.state
                result['scene_selector_control'] = control.as_dict()
                s = scenes[slot - 1]
            elif kind == 'scene-name-control':
                from .edlt_scene_name_control import run_scene_name_control
                if selector_control is not None and selector_control.bound_scene is not None and selector_control.bound_scene != slot:
                    raise EdltError('SceneName callbacks must match the retained selector form binding; explicitly rebind the scene first')
                known_names = [*names, *FIXED_SUGGESTION_NAMES, '']
                def get_name():
                    return scene_name(tuple(names), s.name_index)
                def set_name(text):
                    nonlocal s
                    # Source GetUsedStaticText observes the old reference until
                    # the property setter receives its allocation result.
                    scenes[slot - 1] = s
                    view = self._scene_static_view(state, scenes, overlay)
                    assignment = assign_name(tuple(names), s.name_index, text,
                        values=view, used_indices=lambda: self.common.static_references(view))
                    names[:] = assignment.names
                    known_names[:] = [*names, *FIXED_SUGGESTION_NAMES, '']
                    overlay.update(assignment.changes)
                    s = replace(s, name_index=assignment.index)
                    scenes[slot - 1] = s
                    evidence = {'sequence': len(allocations) + 1,
                        'operation_number': len(state.history) + len(results) + 1,
                        'scene': slot, **assignment.as_dict()}
                    allocations.append(_json(evidence))
                    return evidence
                control = run_scene_name_control(op['events'], get_name=get_name,
                    set_name=set_name, known_names=known_names, initial_state=controls[slot - 1])
                controls[slot - 1] = control.state
                result['scene_name_control'] = {**control.as_dict(),
                    'known_name_profile': 'retained64 plus source FixedStrings64 plus empty',
                    'suggestion_order_inferred': False}
            elif kind == 'get-trigger': s, result['value'] = self._trigger(getter_state(s), s)
            elif kind == 'get-action': s, result['value'] = self._action(getter_state(s), s)
            state = self._inventory_advance(state, phase='operation-end', scene=slot)
            scenes[slot - 1] = s; result['complete'] = complete; results.append(_json(result))
            if not complete: result['reason'] = 'original scene capacity reached'; results[-1] = _json(result); break
        issued = self._next(state, scenes=tuple(scenes), clipboard=clipboard, next_item_id=next_id, complete=complete,
            history=(*state.history, *(_json(op) for op in ops[:len(results)])), validation=None,
            static_text_overlay=overlay, name_allocations=tuple(allocations),
            static_names=tuple(names), name_controls=tuple(controls), selector_control=selector_control,
            _selector_bound_collection=bound_collection, _button_selected_trigger=button_selected_trigger)
        return SceneEditOutcome(issued, complete, tuple(results))

    def validate(self, state):
        self._check(state)
        state = self._inventory_branch(state, 'validation')
        scenes = list(state.scenes); duplicate_trigger = duplicate_name = missing_trigger = missing_name = False; skipped = []
        selector_inventory = self._uses_selector_inventory(state)
        def context(scene):
            return self._selector_context(state, scene) if selector_inventory else state
        def trigger(i):
            nonlocal state
            state = self._inventory_advance(state, phase='validate-trigger', scene=i + 1)
            scenes[i], value = self._trigger(context(scenes[i]), scenes[i]); return value
        def action(i):
            nonlocal state
            state = self._inventory_advance(state, phase='validate-action', scene=i + 1)
            scenes[i], value = self._action(context(scenes[i]), scenes[i]); return value
        for i in range(8):
            if missing_name and missing_trigger: skipped.append(i + 1); continue
            if scenes[i].items:
                if scenes[i].name_index == 255: missing_name = True
                if trigger(i) == 255 or action(i) < 0: missing_trigger = True
            for j in range(i + 1, 8):
                if scenes[i].name_index != 255 and scenes[i].name_index == scenes[j].name_index: duplicate_name = True
                if trigger(i) != 255 and trigger(i) == trigger(j) and action(i) != 255 and action(i) == action(j): duplicate_trigger = True
        warnings = tuple(name for name, present in (('duplicate-trigger-action', duplicate_trigger), ('populated-missing-trigger-action', missing_trigger),
            ('populated-missing-name', missing_name), ('duplicate-name', duplicate_name)) if present)
        record = dict(valid=not warnings, warnings=list(warnings), skipped_slots=skipped, save_blocking=False,
                      validation_scope='original ValidateScenes only', full_form_validation_verified=False)
        issued = self._next(state, scenes=tuple(scenes), validation=_json(record))
        return SceneValidationOutcome(issued, not warnings, warnings, tuple(skipped))

    def prepare_composition(self, state):
        """Serialize retained scene controls without a lifecycle or CRC pass.

        The returned receipt is deliberately scene-only.  An enclosing
        :class:`EdltParentTransaction` enters these exact fields into its
        validated control state and owns the one terminal lifecycle pass.
        """
        self._check(state)
        if not state.complete:
            raise EdltError('An incomplete scene edit or capture cannot be persisted')
        if any(control is not None and control.pending for control in state.name_controls):
            raise EdltError('Pending SceneName input requires an established commit or read callback before saving')
        edited = state
        state = self._inventory_branch(state, 'before-save')
        values = dict(state.static_text_overlay)
        static_values = {**state.loaded.after_load, **values}
        static_changes, _ = save_names(static_values, state.static_names)
        values.update(static_changes)
        scenes = list(state.scenes)
        selector_inventory = self._uses_selector_inventory(state)
        bucket = bytearray()
        pointers = []
        for index, scene in enumerate(scenes):
            state = self._inventory_advance(state, phase='before-save-scene', scene=index + 1)
            context = self._selector_context(state, scene) if selector_inventory else state
            scene, trigger = self._trigger(context, scene)
            scene, action = self._action(context, scene)
            if action == -1:
                scene = self._set_action(context, scene, 0)
            scene, action = self._action(context, scene)
            scenes[index] = scene
            pointers.append(len(bucket))
            bucket.extend((
                scene.primary_secondary + 2 * int(scene.can_edit),
                len(scene.items), trigger, 255 if action < 0 else action,
                scene.name_index,
            ))
            for item in scene.items:
                bucket.extend((
                    16 * int(item.can_edit) + item.ramp_rate,
                    item.group.group, item.level,
                ))
        if len(bucket) > 232:
            raise EdltError('Retained scene data exceeds the 232-byte native PP layout')
        values['SceneCount'] = (8,)
        values['SceneBucket'] = tuple(bucket.ljust(232, b'\xff'))
        for slot, pointer in enumerate(pointers, 1):
            values[f'Scene{slot}StartAddress'] = (pointer,)
        terminal = self._next(state, scenes=tuple(scenes))
        warning = self.validate(edited).as_dict()
        warning.pop('state')
        origin = _Origin(self._owner)
        result = SceneManagerComposition(
            edited, terminal, values, _json(warning),
            sum(len(scene.items) for scene in scenes), origin)
        return self._seal(result)

    def prepare_save(self, state):
        composition = self.prepare_composition(state)
        # Run the already loaded baseline's non-scene BeforeSave rules exactly
        # once; then insert the issued scene-only projection without reloading.
        baseline = self.lifecycle.prepare_save(state.loaded)
        values = dict(baseline.before_save)
        values.update(composition.fields)
        crcs = self.lifecycle.scene_manager_crcs(
            values, item_count=composition.item_count)
        final = {**values, **crcs}
        plan = SceneManagerPlan(
            state, composition.terminal, state.loaded.expected,
            state.loaded.after_load, values,
            _changes(state.loaded.expected, final), composition.validation,
            _Origin(self._owner))
        return self._seal(plan)

    def _interrupted(self, error, plan, attempted, original_error=None):
        evidence = {'verified': False, 'saved': False, 'attempted_parameters': list(attempted),
                    'pp_state_uncertain': bool(attempted), 'automatic_retries': 0}
        try: evidence = {**plan.as_dict(), **evidence}
        except BaseException as secondary:
            evidence.update(evidence_export_complete=False, evidence_error=_error_text(secondary))
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': _error_text(original_error)}
        try:
            cleanup = getattr(original_error if original_error is not None else error, 'cgate_cleanup_errors', None)
            if cleanup is not None: evidence['cgate_cleanup_errors'] = cleanup
        except BaseException: pass
        self.last_evidence = evidence
        try: error.edlt_scene_manager_evidence = evidence
        except BaseException: pass
        return evidence

    def apply(self, session, plan):
        self.last_evidence = None
        self._check(plan, SceneManagerPlan); self._check(plan.source); self._check(plan.terminal)
        canonical = self.prepare_save(plan.source)
        if canonical.as_dict() != plan.as_dict(): raise EdltError('Scene plan differs from canonical retained serialization')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected): raise EdltError('PP values changed since the scene plan was made')
        expected = {**plan.expected, **plan.changes}; attempted = []
        try:
            for name, value in plan.changes.items(): attempted.append(name); session.set(name, _render(value))
            if self.snapshot(session.values()) != expected: raise EdltError('Native PP readback differs from the scene plan')
        except (KeyboardInterrupt, SystemExit) as error:
            self._interrupted(error, plan, attempted); raise
        except Exception as error:
            rollback_errors = []
            try:
                for name in reversed(attempted):
                    if not getattr(session.programmer.client, 'connected', True):
                        rollback_errors.append('Connection lost; rollback stopped without recovery I/O; PP state is uncertain'); break
                    try: session.set(name, _render(plan.expected[name]))
                    except Exception as rollback: rollback_errors.append(_error_text(rollback))
                if getattr(session.programmer.client, 'connected', True):
                    try:
                        if self.snapshot(session.values()) != dict(plan.expected): rollback_errors.append('Original PP values could not be verified')
                    except Exception as rollback: rollback_errors.append(_error_text(rollback))
            except (KeyboardInterrupt, SystemExit) as interrupted:
                evidence = self._interrupted(interrupted, plan, attempted, error); evidence['rollback_errors'] = rollback_errors; raise
            wrapped = EdltApplyError(error, rollback_errors, attempted)
            evidence = self._interrupted(wrapped, plan, attempted, error)
            evidence['rollback_errors'] = rollback_errors; evidence['rollback_verified'] = not rollback_errors
            raise wrapped from error
        self.last_evidence = {**plan.as_dict(), 'verified': True}
        return self.last_evidence
