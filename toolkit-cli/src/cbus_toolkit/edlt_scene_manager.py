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

from .edlt import EdltError, EdltApplyError, _int, _render, CRC_RANGES, configuration_crc
from .edlt_application_cache import ApplicationCache
from .edlt_lifecycle import EdltLifecycle, LoadedEdlt, LifecycleGroup, LifecycleMetadataError, _changes, _delta, _error_text

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

    def as_dict(self):
        return dict(format='cbus-edlt-scene-manager-cache-v1', application_cache=self.application_cache.as_dict(),
                    level_labels=[v.as_dict() for v in self.level_labels])

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping) or set(value) != {'format', 'application_cache', 'level_labels'} or value['format'] != 'cbus-edlt-scene-manager-cache-v1':
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
        return cls(ApplicationCache.from_dict(value['application_cache']), tuple(rows))

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
    _origin: _Origin = field(repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, 'static_text_overlay', MappingProxyType(dict(self.static_text_overlay)))
        object.__setattr__(self, 'name_allocations', tuple(self.name_allocations))

    def static_text_evidence(self):
        overlay = {name: list(value) for name, value in self.static_text_overlay.items()}
        allocations = [json.loads(value) for value in self.name_allocations]
        document = {'overlay_changes': overlay, 'allocations': allocations}
        return {**document, 'fingerprint': hashlib.sha256(_json(document).encode()).hexdigest(),
                'allocation_order': 'scene operation order',
                'allocator': 'EdltLighting.allocate_static_text'}

    def as_dict(self):
        total = sum(len(s.items) for s in self.scenes)
        return dict(format='cbus-edlt-scene-manager-state-v1', scope='model', complete=self.complete,
            scenes=[s.as_dict() for s in self.scenes], clipboard=None if self.clipboard is None else self.clipboard.as_dict(),
            item_count=total, storage_used_percent=100 * total * 3 // 191,
            operations=[json.loads(v) for v in self.history], validation=None if self.validation is None else json.loads(self.validation),
            static_text=self.static_text_evidence(), static_text_allocated=bool(self.name_allocations),
            retained_group_references=True, metadata_created=False, cache_freshness_verified=False,
            full_form_validation_verified=False, physical_device_verified=False, model_state_resumption_supported=False, saved=False)


@dataclass(frozen=True)
class SceneEditOutcome:
    state: SceneManagerState
    complete: bool
    operation_results: tuple[str, ...]

    def as_dict(self):
        return dict(complete=self.complete, state=self.state.as_dict(), operation_results=[json.loads(v) for v in self.operation_results], saved=False)


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


class EdltSceneManager:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.lifecycle = EdltLifecycle(spec, catalog_number=catalog_number, firmware=firmware)
        self.common, self.spec, self.codec = self.lifecycle.common, spec, self.lifecycle.codec
        self._owner = object()
        self.last_evidence = None

    def snapshot(self, values): return self.lifecycle.snapshot(values)

    def _fingerprint(self, value):
        extra = {'expected': dict(value.loaded.expected), 'cache': value.cache.as_dict(), 'next_item_id': value.next_item_id} if type(value) is SceneManagerState else {}
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

    def load(self, values, *, metadata, scope='model'):
        if scope != 'model': raise EdltError('Only retained model scope is implemented; full SceneManager control binding is separate')
        cache = SceneManagerCache.from_dict(metadata.as_dict() if type(metadata) is SceneManagerCache else metadata)
        loaded = self.lifecycle.load(values, metadata=cache.application_cache.lifecycle)
        scenes, next_id = [], 1
        for s in loaded.scenes:
            labels = cache.labels(s.trigger.group, s.action_selector) if s.trigger.group != 255 and s.action_selector >= 0 else ()
            items = tuple(SceneManagerItem(next_id + i, v.group, v.ramp_rate, v.can_edit, v.level) for i, v in enumerate(s.items))
            next_id += len(items)
            scenes.append(SceneManagerScene(s.slot, s.primary_secondary, s.can_edit, s.trigger.group, s.action_selector, s.name_index, items, 0, labels))
        state = SceneManagerState(loaded, cache, tuple(scenes), None, next_id, True, (), None, {}, (), _Origin(self._owner))
        return self._seal(state)

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
        fact = state.loaded.metadata.find(application, group)
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
        fields = {'set-application': ('selector',), 'add-groups': ('groups',), 'remove-items': ('item_ids',),
            'clear-items': (), 'copy': (), 'paste': (), 'clear-scene': (), 'set-level': ('item_id', 'level'),
            'set-percent': ('item_id', 'percent'), 'set-ramp': ('item_id', 'ramp_rate'), 'sync-levels': ('item_id',),
            'set-trigger': ('group',), 'set-action': ('action',), 'set-name-index': ('index',),
            'set-name-text': ('text',), 'get-trigger': (), 'get-action': ()}
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
            if len(encoded) > 63: raise EdltError('Static label text exceeds63UTF-8 bytes; truncation is not permitted')
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
        if len(state.history) + len(ops) > MAX_OPERATIONS: raise EdltError('Scene history exceeds 256 operations')
        scenes, clipboard, next_id, results, complete = list(state.scenes), state.clipboard, state.next_item_id, [], True
        overlay, allocations = dict(state.static_text_overlay), list(state.name_allocations)
        for op in ops:
            kind, slot = op['op'], op['scene']; s = scenes[slot - 1]; result = {'operation': op, 'complete': True}
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
                source, trigger = self._trigger(state, source); source, action = self._action(state, source)
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
            elif kind == 'set-action': s = self._set_action(state, s, op['action'])
            elif kind == 'set-name-index': s = replace(s, name_index=op['index'])
            elif kind == 'set-name-text':
                # Match ordered model-property edits. Detach this scene's old
                # reference before allocation; unrelated and earlier operation
                # references remain reserved in the staged current view.
                scenes[slot - 1] = replace(s, name_index=255)
                allocation = self.common.allocate_static_text(
                    self._scene_static_view(state, scenes, overlay), op['text'])
                overlay.update(allocation.changes)
                s = replace(scenes[slot - 1], name_index=allocation.index)
                evidence = {'sequence': len(allocations) + 1,
                            'operation_number': len(state.history) + len(results) + 1,
                            'scene': slot, **allocation.as_dict()}
                allocations.append(_json(evidence)); result['static_text_allocation'] = evidence
            elif kind == 'get-trigger': s, result['value'] = self._trigger(state, s)
            elif kind == 'get-action': s, result['value'] = self._action(state, s)
            scenes[slot - 1] = s; result['complete'] = complete; results.append(_json(result))
            if not complete: result['reason'] = 'original scene capacity reached'; results[-1] = _json(result); break
        issued = self._next(state, scenes=tuple(scenes), clipboard=clipboard, next_item_id=next_id, complete=complete,
            history=(*state.history, *(_json(op) for op in ops[:len(results)])), validation=None,
            static_text_overlay=overlay, name_allocations=tuple(allocations))
        return SceneEditOutcome(issued, complete, tuple(results))

    def validate(self, state):
        self._check(state); scenes = list(state.scenes); duplicate_trigger = duplicate_name = missing_trigger = missing_name = False; skipped = []
        def trigger(i):
            scenes[i], value = self._trigger(state, scenes[i]); return value
        def action(i):
            scenes[i], value = self._action(state, scenes[i]); return value
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

    def prepare_save(self, state):
        self._check(state)
        if not state.complete: raise EdltError('An incomplete scene edit or capture cannot be persisted')
        # Run the already loaded baseline's non-scene BeforeSave rules exactly
        # once; then serialize edited retained scene objects, without reloading.
        baseline = self.lifecycle.prepare_save(state.loaded); values = dict(baseline.before_save)
        values.update(state.static_text_overlay)
        scenes = list(state.scenes); bucket = bytearray(); pointers = []
        for i, scene in enumerate(scenes):
            scene, trigger = self._trigger(state, scene); scene, action = self._action(state, scene)
            if action == -1: scene = self._set_action(state, scene, 0)
            scene, action = self._action(state, scene); scenes[i] = scene
            pointers.append(len(bucket)); bucket.extend((scene.primary_secondary + 2 * int(scene.can_edit), len(scene.items), trigger, 255 if action < 0 else action, scene.name_index))
            for item in scene.items: bucket.extend((16 * int(item.can_edit) + item.ramp_rate, item.group.group, item.level))
        if len(bucket) > 232: raise EdltError('Retained scene data exceeds the 232-byte native PP layout')
        values['SceneCount'] = (8,); values['SceneBucket'] = tuple(bucket.ljust(232, b'\xff'))
        for n, pointer in enumerate(pointers, 1): values[f'Scene{n}StartAddress'] = (pointer,)
        terminal = self._next(state, scenes=tuple(scenes))
        # Validation is observed separately on a branch; its mutating getters
        # must not silently change the serialization sequence.
        warning = self.validate(state).as_dict(); warning.pop('state')
        crcs = self.lifecycle.crcs(values)
        if len(bucket) == 232:
            # Original SaveScenes appends FF even when all 232 data bytes are
            # occupied. Original PPHelper's foreach consumes that extra token
            # into the temporary CRC image despite the declared ArraySize.
            memory = bytearray(9216)
            for name, value in self.snapshot(values).items():
                if self.codec.layout(name).address < 256: continue
                for edit in self.codec.encode(name, value).edits:
                    index = edit.address - 256; memory[index] = (memory[index] & ~edit.mask) | edit.value
            memory[0x21fa - 256] = 255
            crcs = {name: tuple(configuration_crc(bytes(memory[start:start + size])).to_bytes(2, 'big'))
                    for name, (start, size) in CRC_RANGES.items()}
        final = {**values, **crcs}
        plan = SceneManagerPlan(state, terminal, state.loaded.expected, state.loaded.after_load, values,
            _changes(state.loaded.expected, final), _json(warning), _Origin(self._owner))
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
