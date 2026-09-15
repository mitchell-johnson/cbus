"""Explicit KEYGL5 scene-table replacement using Toolkit SaveScenes packing.

Database-only authoring: assigned trigger bindings, output items, names and CRCs.
No physical invocation, learning, implicit slot compaction or widget rewriting.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltLighting, EdltError, EdltApplyError, RAMP_SECONDS, _field, _int, _render
from .edlt_scene import EdltSceneWidget


def _boolean(value, name):
    if not isinstance(value, bool):
        raise EdltError(name + ' must be a boolean')
    return value


def _from_dict(cls, value, allowed):
    if not isinstance(value, Mapping) or set(value) - set(allowed):
        raise EdltError('Invalid ' + cls.__name__ + ' fields')
    try:
        return cls(**value)
    except TypeError as error:
        raise EdltError('Missing or invalid ' + cls.__name__ + ' fields') from error


@dataclass(frozen=True)
class SceneItem:
    group: int
    level: int
    ramp_seconds: int = 0
    editable: bool = True

    def __post_init__(self):
        _int(self.group, 'Item group', 0, 254)
        _int(self.level, 'Item level')
        _int(self.ramp_seconds, 'Item ramp seconds', 0, 1020)
        if self.ramp_seconds not in RAMP_SECONDS:
            raise EdltError('Unsupported scene item ramp time')
        _boolean(self.editable, 'Item editable')

    def as_dict(self):
        return dict(group=self.group, level=self.level, ramp_seconds=self.ramp_seconds, editable=self.editable)

    @classmethod
    def from_dict(cls, value):
        return _from_dict(cls, value, ('group', 'level', 'ramp_seconds', 'editable'))


@dataclass(frozen=True)
class SceneDefinition:
    application: str
    trigger_group: int
    action_selector: int
    items: tuple[SceneItem, ...] = ()
    name_index: int | None = None
    name_text: str | None = None
    editable: bool = True

    def __post_init__(self):
        if self.application not in ('primary', 'secondary'):
            raise EdltError('Scene application must be primary or secondary')
        _int(self.trigger_group, 'Trigger group', 0, 254)
        _int(self.action_selector, 'Action selector')
        _boolean(self.editable, 'Scene editable')
        if not isinstance(self.items, (tuple, list)) or any(not isinstance(item, SceneItem) for item in self.items):
            raise EdltError('Scene items must be a list of SceneItem values')
        object.__setattr__(self, 'items', tuple(self.items))
        if len({item.group for item in self.items}) != len(self.items):
            raise EdltError('A scene cannot contain duplicate output groups')
        if self.name_index is not None:
            _int(self.name_index, 'Scene name index', 0, 63)
        if self.name_text is not None:
            if self.name_index is not None or not isinstance(self.name_text, str) or not self.name_text.strip() or '\0' in self.name_text:
                raise EdltError('name_text must be nonblank, contain no NUL and cannot accompany name_index')
            try:
                if len(self.name_text.encode('utf-8')) > 63:
                    raise EdltError('Scene name exceeds 63 UTF-8 bytes')
            except UnicodeEncodeError as error:
                raise EdltError('Scene name must be valid Unicode') from error

    def as_dict(self):
        return dict(application=self.application, trigger_group=self.trigger_group, action_selector=self.action_selector,
                    items=[item.as_dict() for item in self.items], name_index=self.name_index,
                    name_text=self.name_text, editable=self.editable)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping):
            raise EdltError('Scene definition must be an object')
        value = dict(value)
        if 'items' in value:
            if not isinstance(value['items'], (tuple, list)):
                raise EdltError('Scene items must be a list')
            value['items'] = tuple(SceneItem.from_dict(item) for item in value['items'])
        return _from_dict(cls, value, ('application', 'trigger_group', 'action_selector', 'items', 'name_index', 'name_text', 'editable'))


@dataclass(frozen=True)
class SceneTablePlan:
    expected: Mapping
    changes: Mapping
    requested: tuple[SceneDefinition, ...]
    scenes: tuple[SceneDefinition, ...]
    bucket: bytes
    pointers: tuple[int, ...]
    name_allocations: tuple
    references: Mapping

    def __post_init__(self):
        for name in ('expected', 'changes', 'references'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
        for name in ('requested', 'scenes', 'pointers', 'name_allocations'):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    def as_dict(self):
        return {'format': 'cbus-edlt-scene-table-plan-v1', 'unit_type': 'KEYGL5', 'catalog_number': '5055EDL',
                'firmware': '5.5.00', 'scene_count': len(self.scenes), 'item_count': sum(len(s.items) for s in self.scenes),
                'scenes': [dict(scene=i + 1, **scene.as_dict()) for i, scene in enumerate(self.scenes)],
                'pointers': list(self.pointers), 'bucket_hex': self.bucket.hex(),
                'name_allocations': [a.as_dict() if a else None for a in self.name_allocations],
                'referenced_slots': {str(k): list(v) for k, v in self.references.items()},
                'changes': {k: list(v) if isinstance(v, tuple) else v for k, v in self.changes.items()},
                'saved': False, 'physical_device_verified': False}


class EdltSceneTable:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.widget = EdltSceneWidget(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        layout = self.codec.layout('SceneCount')
        if (layout.parameter.type, layout.address, layout.array_size, layout.bit_size, layout.bit_address, layout.array_skip) != ('int', 0x2100, 1, 8, 0, 0):
            raise EdltError('Unsupported SceneCount layout')

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def read(self, values):
        """Read contiguous configured slots; never compact holes or normalize unknown records."""
        values = self.snapshot(values)
        self.common.static_references(values)
        bucket, scenes, hole = values['SceneBucket'], [], False
        for index in range(1, 9):
            pointer = values[f'Scene{index}StartAddress'][0]
            if pointer in (255, 65535) or bucket[pointer] == 255:
                hole = True
                continue
            if hole:
                raise EdltError('Scene table has a middle hole; implicit scene-slot compaction is not supported')
            ref = self.widget.scene_reference(values, index)
            if ref.trigger_group is None:
                raise EdltError('Scene authoring currently requires assigned trigger bindings in existing records')
            flags = bucket[pointer]
            items = []
            for item in range(ref.item_count):
                control, group, level = bucket[pointer + 5 + 3 * item:pointer + 8 + 3 * item]
                items.append(SceneItem(group, level, RAMP_SECONDS[control & 15], bool(control & 16)))
            scenes.append(SceneDefinition('secondary' if flags & 1 else 'primary', ref.trigger_group,
                                          ref.action_selector, tuple(items), ref.name_index, editable=bool(flags & 2)))
        self._validate_scenes(scenes, values)
        return tuple(scenes)

    @staticmethod
    def _validate_scenes(scenes, values):
        if not isinstance(scenes, (tuple, list)) or any(not isinstance(scene, SceneDefinition) for scene in scenes):
            raise EdltError('scenes must be an ordered list of SceneDefinition values')
        if len(scenes) > 8 or sum(len(scene.items) for scene in scenes) > 64:
            raise EdltError('Scene table supports at most 8 scenes and 64 total output items')
        for scene in scenes:
            application = values['SecondaryApplication' if scene.application == 'secondary' else 'PrimaryApplication'][0]
            if not 48 <= application <= 95:
                raise EdltError('Scene requires an assigned Lighting application in 48..95')

    @staticmethod
    def _pack(scenes):
        bucket, pointers = bytearray(), []
        for scene in scenes:
            pointers.append(len(bucket))
            bucket.extend(((2 if scene.editable else 0) | (scene.application == 'secondary'), len(scene.items),
                           scene.trigger_group, scene.action_selector, 255 if scene.name_index is None else scene.name_index))
            for item in scene.items:
                bucket.extend(((16 if item.editable else 0) | RAMP_SECONDS.index(item.ramp_seconds), item.group, item.level))
        # Original SaveScenes appends an extra FF when data occupies all232 bytes.
        # Native PP SET drops that surplus padding byte; all232 data bytes persist.
        if len(bucket) > 232:
            raise EdltError('Scene table exceeds the 232-byte bucket of record data')
        return bytes(bucket).ljust(232, b'\xff'), tuple(pointers + [255] * (8 - len(pointers)))

    @classmethod
    def _place(cls, values, scenes):
        bucket, pointers = cls._pack(scenes)
        result = dict(values)
        result.update(SceneCount=(len(scenes),), SceneBucket=tuple(bucket))
        result.update({f'Scene{i + 1}StartAddress': (pointer,) for i, pointer in enumerate(pointers)})
        return result

    @staticmethod
    def _references(values):
        refs = {}
        for widget in range(1, 22):
            if values[_field(widget)] != (6,):
                continue
            macro = tuple(values[_field(widget, i)][0] for i in (7, 8))
            if macro in ((26, 27), (28, 29), (32, 33)):
                indexes = [(6, values[_field(widget, 6)][0])]
            elif macro == (30, 31):
                indexes = []
                for offset in range(13, 22):
                    value = values[_field(widget, offset)][0]
                    if value == 255:
                        break
                    indexes.append((offset, value))
            else:
                raise EdltError('Cannot safely enumerate references in unsupported Scene widget macros')
            for offset, index in indexes:
                _int(index, 'Existing widget scene index', 0, 7)
                refs.setdefault(index + 1, []).append(_field(widget, offset))
        return {key: tuple(value) for key, value in refs.items()}

    def plan(self, current, *, scenes):
        original = self.snapshot(current)
        self._validate_scenes(scenes, original)
        requested = tuple(scenes)
        previous = self.read(original)
        refs = self._references(original)
        for number, origins in refs.items():
            if number > len(previous) or number > len(requested):
                raise EdltError(f'Referenced scene slot {number} cannot be removed or left unconfigured')
            before, after = previous[number - 1], requested[number - 1]
            if (before.application, before.trigger_group, before.action_selector) != (after.application, after.trigger_group, after.action_selector):
                raise EdltError(f'Referenced scene slot {number} must retain its application and trigger/action identity')
            if after.name_index is None and after.name_text is None:
                for origin in origins:
                    widget = int(origin.split('Widget')[1])
                    if original[_field(widget, 1)][0] >> 4 & 7 == 3:
                        raise EdltError(f'Referenced scene slot {number} must retain a name for its scene label')
        # As with original model property edits, replace the explicit scene list
        # first, then allocate/bind names in scene order. All pending direct name
        # references and unrelated unit text references remain reserved.
        resolved = [replace(scene, name_text=None) for scene in requested]
        updates = self._place(original, resolved)
        allocations = []
        for index, scene in enumerate(requested):
            allocation = None
            if scene.name_text is not None:
                allocation = self.common.allocate_static_text(updates, scene.name_text)
                updates.update(allocation.changes)
                resolved[index] = replace(resolved[index], name_index=allocation.index)
                updates = self._place(updates, resolved)
            allocations.append(allocation)
        for name, value in (('ConfigVersionMajor', 1), ('ConfigVersionMinor', 0)):
            if original[name] == (255,):
                updates[name] = (value,)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        bucket, pointers = self._pack(resolved)
        return SceneTablePlan(original, changes, requested, tuple(resolved), bucket, pointers, tuple(allocations), refs)

    def apply(self, session, plan):
        if not isinstance(plan, SceneTablePlan) or not isinstance(plan.bucket, bytes) or len(plan.bucket) != 232:
            raise EdltError('Use a scene table plan returned by EdltSceneTable.plan')
        if len(plan.pointers) != 8:
            raise EdltError('Scene table plan requires eight pointers')
        for pointer in plan.pointers:
            _int(pointer, 'Plan scene pointer')
        for number in plan.references:
            _int(number, 'Referenced scene slot', 1, 8)
        for allocation in plan.name_allocations:
            if allocation is not None:
                _int(allocation.index, 'Allocated scene name index', 0, 63)
        canonical = self.plan(plan.expected, scenes=plan.requested)
        if canonical != plan:
            raise EdltError('Scene table plan differs from validated settings')
        expected = dict(plan.expected); expected.update(plan.changes)
        self.snapshot(expected)
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the scene table plan was made')
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the scene table plan')
        except Exception as error:
            rollback_errors = []
            for name in reversed(attempted):
                if not getattr(session.programmer.client, 'connected', True):
                    rollback_errors.append('Connection lost; rollback stopped without recovery I/O; PP state is uncertain')
                    break
                try:
                    session.set(name, _render(plan.expected[name]))
                except Exception as rollback:
                    rollback_errors.append(str(rollback))
            if getattr(session.programmer.client, 'connected', True):
                try:
                    if self.snapshot(session.values()) != dict(plan.expected):
                        rollback_errors.append('Original PP values could not be verified')
                except Exception as rollback:
                    rollback_errors.append(str(rollback))
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, **options):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), **options))
