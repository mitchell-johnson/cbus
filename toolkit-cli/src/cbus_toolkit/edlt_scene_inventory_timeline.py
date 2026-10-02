"""Private, source-bound causal inventories for native SceneManager replay.

The serialized cache remains a declaration of facts, never an issuer of this
capability.  Native resolution issues the timeline from a complete snapshot and
an exact history; the owning editor consumes it without database I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json

from .edlt import EdltError


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise EdltError('Invalid native scene inventory binding') from error


def _digest(value):
    return hashlib.sha256(_json(value).encode('ascii')).hexdigest()


@dataclass(frozen=True)
class SceneInventory:
    """Only object identities; names/labels come from the issued final template."""
    applications: tuple[int, ...]
    groups: tuple[tuple[int, int], ...]
    levels: tuple[tuple[int, int, tuple[int, ...]], ...]
    refresh_generation: int = 0

    def as_dict(self):
        return {'applications': list(self.applications),
                'groups': [list(row) for row in self.groups],
                'levels': [[app, group, list(rows)] for app, group, rows in self.levels],
                'refresh_generation': self.refresh_generation}

    def union(self, other):
        levels = {(a, g): list(rows) for a, g, rows in self.levels}
        created = sum(row not in self.applications for row in other.applications)
        created += sum(row not in self.groups for row in other.groups)
        for app, group, rows in other.levels:
            present = levels.setdefault((app, group), [])
            created += sum(row not in present for row in rows)
            present.extend(row for row in rows if row not in present)
        return SceneInventory(
            tuple(dict.fromkeys((*self.applications, *other.applications))),
            tuple(dict.fromkeys((*self.groups, *other.groups))),
            tuple((a, g, tuple(rows)) for (a, g), rows in levels.items()),
            max(self.refresh_generation + created, other.refresh_generation))


@dataclass(frozen=True)
class SceneInventoryFrame:
    phase: str
    operation: str | None
    callback: int
    scene: int
    inventory: SceneInventory
    causes: tuple[str, ...] = ()

    def as_dict(self):
        return {'phase': self.phase,
                'operation': None if self.operation is None else json.loads(self.operation),
                'callback': self.callback, 'scene': self.scene,
                'refresh_generation': self.inventory.refresh_generation,
                'inventory': self.inventory.as_dict(), 'causes': list(self.causes)}


class _Seal:
    def __init__(self, owner):
        self.owner, self.fingerprint = owner, None
        # Identity memo only. Values are copied exclusively from the sealed
        # template, and the same generation always returns the same objects.
        self.labels = {}


def _narrow(template, inventory, label_rows):
    # The separate parent cache can keep later positives. This cache describes
    # the actual SceneManager position, including non-202 choices.
    from .edlt_application_cache import ApplicationCache, CachedGroupList
    from .edlt_lifecycle import LifecycleCache
    from .edlt_scene_manager import SceneManagerCache
    from .edlt_scene_selector_views import SceneActionList
    apps, groups = set(inventory.applications), set(inventory.groups)
    levels = {(a, g): rows for a, g, rows in inventory.levels}
    outer = template.application_cache
    facts = []
    for row in outer.lifecycle.groups:
        if row.application not in apps:
            continue
        if (row.application, row.group) not in groups and row.group != 255:
            continue
        if row.application == 202:
            if row.levels is not None:
                row = replace(row, levels=tuple(v for v in row.levels
                                                if v in levels.get((202, row.group), ())))
        facts.append(row)
    lifecycle = LifecycleCache(tuple(a for a in outer.lifecycle.applications if a in apps), tuple(facts))
    application_cache = ApplicationCache(lifecycle, outer.applications_complete,
        tuple(row for row in outer.applications if row.address in apps),
        tuple(CachedGroupList(row.application, row.complete,
            tuple(v for v in row.groups if (row.application, v.address) in groups or v.address == 255))
            for row in outer.group_lists if row.application in apps))
    labels = tuple(row for row in label_rows
                   if row.action in levels.get((202, row.group), ()))
    if template.trigger_list is None:
        return SceneManagerCache(application_cache, labels)
    trigger = CachedGroupList(202, template.trigger_list.complete,
        tuple(row for row in template.trigger_list.groups if (202, row.address) in groups))
    actions = tuple(SceneActionList(row.group, row.complete,
        tuple(v for v in row.actions if v.address in levels.get((202, row.group), ())))
        for row in template.action_lists if (202, row.group) in groups)
    return SceneManagerCache(application_cache, labels, trigger, actions)


@dataclass(frozen=True)
class SceneInventoryTimeline:
    _template: object
    _initial: SceneInventory
    _frames: tuple[SceneInventoryFrame, ...]
    _save_frames: tuple[SceneInventoryFrame, ...]
    _validation_targets: tuple[tuple[int, int], ...]
    _initial_scene_bindings: tuple[tuple[int, int, int], ...]
    _label_epochs: tuple[tuple[int, tuple], ...]
    _binding: str
    _source_values: str
    _seal: _Seal

    @property
    def fingerprint(self):
        return _digest(self._payload())

    def _payload(self):
        return {'binding': json.loads(self._binding),
                'source_values': json.loads(self._source_values),
                'template': self._template.as_dict(),
                'initial': self._initial.as_dict(),
                'frames': [row.as_dict() for row in self._frames],
                'save_frames': [row.as_dict() for row in self._save_frames],
                'validation_targets': self._validation_targets,
                'initial_scene_bindings': self._initial_scene_bindings,
                'label_epochs': [[generation, [row.as_dict() for row in rows]]
                                 for generation, rows in self._label_epochs]}

    def as_dict(self):
        check_timeline(self)
        return {'format': 'cbus-native-scene-inventory-timeline-v1',
                'sha256': self.fingerprint,
                'binding': json.loads(self._binding),
                'source_values_sha256': _digest(json.loads(self._source_values)),
                'initial': self._initial.as_dict(),
                'frames': [row.as_dict() for row in self._frames],
                'save_frames': [row.as_dict() for row in self._save_frames],
                'validation_targets': [list(row) for row in self._validation_targets],
                'initial_scene_bindings': [list(row) for row in self._initial_scene_bindings],
                'label_epochs': [[generation, [row.as_dict() for row in rows]]
                                 for generation, rows in self._label_epochs],
                'serialized_input_capability': False,
                'database_execution': False, 'original_execution': False}

    def start(self, cache, *, source_values, owner):
        check_timeline(self, owner)
        if cache.as_dict() != self._template.as_dict() or _json(source_values) != self._source_values:
            raise EdltError('Native scene inventory source/cache differs from its issued timeline')
        return _cursor(self, self._initial)

    def rebase_outer(self, cache):
        """Carry the parent's outer facts without widening phase inventories."""
        check_timeline(self)
        from .edlt_scene_manager import SceneManagerCache
        if type(cache) is not SceneManagerCache:
            raise EdltError('Native timeline outer rebase requires an issued typed cache')
        old, new = self._template.as_dict(), cache.as_dict()
        if any(old.get(key) != new.get(key) for key in ('level_labels', 'trigger_list', 'action_lists')):
            raise EdltError('Native timeline outer rebase cannot change selector/label facts')
        original = self._template.application_cache
        outer = cache.application_cache
        def extends(row):
            current = outer.lifecycle.find(row.application, row.group)
            return (current is not None
                and (not row.exists or current.exists)
                and (not row.dynamic_images_known or current.dynamic_images_known
                     and current.dynamic_images == row.dynamic_images)
                and (row.levels is None or current.levels is not None
                     and set(row.levels) <= set(current.levels)))
        if (not set(original.lifecycle.applications) <= set(outer.lifecycle.applications)
                or any(not extends(row) for row in original.lifecycle.groups)
                or any(outer.find_application(row.address) != row for row in original.applications)):
            raise EdltError('Native timeline outer rebase cannot replace issued lifecycle facts')
        template = replace(cache, _inventory_timeline=None)
        return issue_timeline(template, initial=self._initial, frames=self._frames,
            save_frames=self._save_frames, validation_targets=self._validation_targets,
            initial_scene_bindings=self._initial_scene_bindings,
            label_epochs=self._label_epochs,
            label_seeds=tuple(self._seal.labels.items()),
            binding=json.loads(self._binding), source_values=json.loads(self._source_values),
            owner=self._seal.owner)

    def labels_at(self, generation):
        check_timeline(self)
        maximum = max(row.inventory.refresh_generation for row in self._save_frames)
        if type(generation) is not int or not 0 <= generation <= maximum:
            raise EdltError('Native scene label generation exceeds its issued creation history')
        if generation not in self._seal.labels:
            source = self.label_template_at(generation)
            self._seal.labels[generation] = tuple(
                replace(row, labels=tuple(replace(label) for label in row.labels))
                for row in source)
        return self._seal.labels[generation]

    def label_template_at(self, generation):
        # The XML/default-language fact belongs to its causal refresh epoch.
        # A future text refresh must never replace earlier label facts.
        return next(rows for start, rows in reversed(self._label_epochs)
                    if start <= generation)

    def label_owner(self, labels):
        """Resolve retained DataStore references from any issued refresh epoch."""
        check_timeline(self)
        matches = [(generation, row) for generation, rows in self._seal.labels.items() for row in rows
                   if len(row.labels) == len(labels)
                   and all(a is b for a, b in zip(row.labels, labels))]
        if len(matches) != 1:
            raise EdltError('Retained native label references have no unique issued owner')
        generation, row = matches[0]
        original = next(v for v in self.label_template_at(generation)
                        if (v.group, v.action) == (row.group, row.action))
        if row.as_dict() != original.as_dict():
            raise EdltError('Retained native label generation was modified')
        return row


def issue_timeline(template, *, initial, frames, save_frames,
                   validation_targets, binding, source_values, owner,
                   initial_scene_bindings=None, label_epochs=None, label_seeds=()):
    """Native resolver factory; no from_dict/import or caller operation exists."""
    if (type(initial) is not SceneInventory
            or len(validation_targets) != 8 or len(save_frames) != 8
            or len(frames) > 256 * (2 + 2 * 512)
            or any(type(row) is not SceneInventoryFrame for row in (*frames, *save_frames))):
        raise EdltError('Invalid native inventory timeline issuance')
    if initial_scene_bindings is None:
        initial_scene_bindings = tuple((group, action, initial.refresh_generation)
                                      for group, action in validation_targets)
    if len(initial_scene_bindings) != 8:
        raise EdltError('Native timeline requires eight initial scene label owners')
    from .edlt_scene_manager import SceneLevelLabels
    if label_epochs is None:
        label_epochs = ((0, template.level_labels),)
    if (type(label_epochs) is not tuple or not label_epochs or label_epochs[0][0] != 0
            or any(type(epoch) is not tuple or len(epoch) != 2
                   or type(epoch[0]) is not int or epoch[0] < 0
                   or type(epoch[1]) is not tuple
                   or any(type(row) is not SceneLevelLabels for row in epoch[1])
                   or len({(row.group, row.action) for row in epoch[1]}) != len(epoch[1])
                   for epoch in label_epochs)
            or tuple(start for start, _ in label_epochs) != tuple(sorted(set(start for start, _ in label_epochs)))):
        raise EdltError('Native timeline label epochs are invalid')
    value = SceneInventoryTimeline(template, initial, tuple(frames), tuple(save_frames),
        tuple(validation_targets), tuple(initial_scene_bindings),
        label_epochs,
        _json(binding), _json(source_values), _Seal(owner))
    value._seal.fingerprint = value.fingerprint
    maximum = max(row.inventory.refresh_generation for row in save_frames)
    for generation, rows in label_seeds:
        if (type(generation) is not int or not 0 <= generation <= maximum
                or type(rows) is not tuple
                or [row.as_dict() for row in rows] != [row.as_dict() for row in value.label_template_at(generation)]
                or generation in value._seal.labels):
            raise EdltError('Native timeline retained label seed differs from its epoch')
        value._seal.labels[generation] = rows
    return value


def check_timeline(value, owner=None):
    if (type(value) is not SceneInventoryTimeline or type(value._seal) is not _Seal
            or owner is not None and value._seal.owner is not owner
            or value._seal.fingerprint != value.fingerprint):
        raise EdltError('Native scene inventory timeline is foreign or modified')
    return value


@dataclass(frozen=True)
class SceneInventoryCursor:
    timeline: SceneInventoryTimeline
    inventory: SceneInventory
    cache: object
    position: int
    branch: str
    branch_position: int
    journal: tuple[str, ...]
    _seal: _Seal

    @property
    def fingerprint(self):
        return _digest({'timeline': self.timeline.fingerprint, 'inventory': self.inventory.as_dict(),
                        'cache': self.cache.as_dict(), 'position': self.position,
                        'branch': self.branch, 'branch_position': self.branch_position,
                        'journal': self.journal})

    def as_dict(self):
        check_cursor(self)
        return {'timeline_sha256': self.timeline.fingerprint, 'sha256': self.fingerprint,
                'position': self.position, 'branch': self.branch,
                'branch_position': self.branch_position,
                'visible_inventory': self.inventory.as_dict(),
                'journal': [json.loads(row) for row in self.journal]}

    def _branch(self, kind):
        check_cursor(self)
        if self.position != len(self.timeline._frames) or self.branch == 'save':
            raise EdltError('Native scene inventory requires its complete edit history before validation/save')
        return _cursor(self.timeline, self.inventory, position=self.position,
                       branch=kind, journal=self.journal)

    def validation(self):
        return self._branch('validation')

    def before_save(self):
        return self._branch('save')

    def collection_generation(self, group):
        """Conservative creation boundary, not a native BindingList identity.

        A changed collection inventory requires explicit rebinding unless the
        source proves mutation of the previously bound list. Group Address
        alone never authorizes adopting its replacement collection.
        """
        check_cursor(self)
        return _digest([self.inventory.refresh_generation, group,
                       next((rows for app, address, rows in self.inventory.levels
                                    if app == 202 and address == group), None)])

    def initial_scene_labels(self, slot):
        check_cursor(self)
        if type(slot) is not int or not 1 <= slot <= 8:
            raise EdltError('Native initial label binding requires scene1..8')
        group, action, generation = self.timeline._initial_scene_bindings[slot - 1]
        if group == 255 or action < 0:
            return ()
        row = next((row for row in self.timeline.labels_at(generation)
                    if (row.group, row.action) == (group, action)), None)
        if row is None:
            raise EdltError('Native initial scene labels lack an issued level owner')
        return row.labels

    def advance(self, *, operation=None, phase, callback=0, scene=0):
        check_cursor(self)
        if type(callback) is not int or type(scene) is not int:
            raise EdltError('Native inventory callback/scene must be exact integers')
        if self.branch == 'edit':
            if self.position >= len(self.timeline._frames):
                raise EdltError('Native scene inventory history is already consumed')
            frame = self.timeline._frames[self.position]
            if ((phase, callback, scene) != (frame.phase, frame.callback, frame.scene)
                    or frame.operation is not None and _json(operation) != frame.operation):
                raise EdltError('Native scene inventory operation/callback is out of order or differs')
            return _cursor(self.timeline, frame.inventory, position=self.position + 1,
                journal=(*self.journal, _json({'phase': phase, 'callback': callback,
                                              'scene': scene, 'causes': frame.causes})))
        if operation is not None or callback != 0 or not 1 <= scene <= 8:
            raise EdltError('Invalid native scene inventory branch callback')
        if self.branch == 'save':
            if (phase != 'before-save-scene' or scene != self.branch_position + 1
                    or self.branch_position >= 8):
                raise EdltError('Native BeforeSave inventory must consume scenes1..8 in order')
            frame = self.timeline._save_frames[self.branch_position]
            inventory = self.inventory.union(frame.inventory)
            causes = frame.causes
        elif self.branch == 'validation':
            if phase not in ('validate-trigger', 'validate-action') or self.branch_position >= 512:
                raise EdltError('Invalid or excessive native validation getter')
            trigger, action = self.timeline._validation_targets[scene - 1]
            groups = () if trigger == 255 else ((202, trigger),)
            levels = () if trigger == 255 or action < 0 or phase == 'validate-trigger' else ((202, trigger, (action,)),)
            old_groups = set(self.inventory.groups)
            old_levels = {(a, g): set(rows) for a, g, rows in self.inventory.levels}
            created = int(202 not in self.inventory.applications)
            created += sum(row not in old_groups for row in groups)
            created += sum(value not in old_levels.get((a, g), ())
                           for a, g, values in levels for value in values)
            inventory = self.inventory.union(SceneInventory((202,), groups, levels,
                self.inventory.refresh_generation + created))
            causes = (f'Scene{scene} validation {phase}',)
        else:
            raise EdltError('Invalid native scene inventory branch')
        return _cursor(self.timeline, inventory, position=self.position, branch=self.branch,
            branch_position=self.branch_position + 1,
            journal=(*self.journal, _json({'phase': phase, 'scene': scene, 'causes': causes})))


def _cursor(timeline, inventory, *, position=0, branch='edit', branch_position=0, journal=()):
    cache = replace(_narrow(timeline._template, inventory,
                           timeline.labels_at(inventory.refresh_generation)),
                    _inventory_timeline=timeline)
    value = SceneInventoryCursor(timeline, inventory, cache,
                                 position, branch, branch_position, tuple(journal), _Seal(timeline._seal.owner))
    value._seal.fingerprint = value.fingerprint
    return value


def check_cursor(value, owner=None):
    if (type(value) is not SceneInventoryCursor or type(value._seal) is not _Seal
            or owner is not None and value._seal.owner is not owner
            or value._seal.fingerprint != value.fingerprint):
        raise EdltError('Native scene inventory cursor is foreign or modified')
    check_timeline(value.timeline, owner)
    return value
