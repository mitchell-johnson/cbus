"""KEYGL5 Scene widgets referencing existing configured local scenes.

Exact Toolkit1.18 SceneData properties; no scene-table creation or editing.
Database PP staging is verified, with Toolkit CRCs and shared static status text.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltLighting, EdltError, EdltApplyError, StaticTextAllocation, RAMP_SECONDS, _field, _int, _render

SCENE_MODES = MappingProxyType({'off-on': (26, 27), 'ramp': (28, 29), 'nudge': (32, 33), 'cycle': (30, 31)})
SCENE_LABEL_TYPES = MappingProxyType({'blank': 0, 'dynamic-text': 1, 'dynamic-icon': 2, 'scene': 3})
SCENE_STATUS_TYPES = MappingProxyType({'blank': 0, 'static': 5, 'dynamic-text': 6, 'dynamic-icon': 7})


@dataclass(frozen=True)
class SceneReference:
    scene: int
    pointer: int
    application: int
    item_count: int
    trigger_group: int | None
    action_selector: int | None
    name_index: int | None

    def __post_init__(self):
        for value, name, minimum, maximum in ((self.scene, 'Scene', 1, 8), (self.pointer, 'Scene pointer', 0, 231),
                (self.application, 'Scene application', 48, 95), (self.item_count, 'Scene item count', 0, 75)):
            _int(value, name, minimum, maximum)
        for value, name, maximum in ((self.trigger_group, 'Trigger group', 254),
                                    (self.action_selector, 'Action selector', 255), (self.name_index, 'Name index', 63)):
            if value is not None:
                _int(value, name, 0, maximum)

    def as_dict(self):
        return dict(scene=self.scene, pointer=self.pointer, application=self.application,
                    item_count=self.item_count, trigger_group=self.trigger_group,
                    action_selector=self.action_selector, name_index=self.name_index)


@dataclass(frozen=True)
class SceneWidgetPlan:
    page: int
    position: int
    widget: int
    page_mode: str
    reference: SceneReference | None
    expected: Mapping
    changes: Mapping
    record: bytes
    status_allocation: StaticTextAllocation | None
    options: Mapping
    mode: str = 'off-on'
    cycle_references: tuple[SceneReference, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'cycle_references', tuple(self.cycle_references))
        for name in ('expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-scene-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00', 'mode': self.mode,
                'page': self.page, 'position': self.position, 'widget': self.widget,
                'page_mode': self.page_mode, 'scene_reference': self.reference.as_dict() if self.reference else None,
                'cycle_references': [ref.as_dict() for ref in self.cycle_references],
                'record_hex': self.record.hex(),
                'changes': {k: list(v) if isinstance(v, tuple) else v for k, v in self.changes.items()},
                'status_allocation': self.status_allocation.as_dict() if self.status_allocation else None,
                'saved': False, 'physical_device_verified': False}


class EdltSceneWidget:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def scene_reference(self, current, scene):
        """Read and validate a configured scene; human scene numbers are1..8."""
        scene = _int(scene, 'Scene', 1, 8)
        values = self.snapshot(current)
        # Independently checked full-unit pointers and static-reference layouts.
        self.common.static_references(values)
        pointer = values[f'Scene{scene}StartAddress'][0]
        bucket = values['SceneBucket']
        if pointer in (255, 65535) or bucket[pointer] == 255:
            raise EdltError('Selected scene is not configured')
        flags, count, trigger, action, name = bucket[pointer:pointer + 5]
        if flags > 3:
            raise EdltError('Selected scene uses unsupported header flags')
        application = values['SecondaryApplication' if flags & 1 else 'PrimaryApplication'][0]
        if not 48 <= application <= 95:
            raise EdltError('Selected scene requires an assigned Lighting application in 48..95')
        if count == 0 and trigger == 255:
            raise EdltError('Selected scene has neither output items nor an assigned trigger')
        for item in range(count):
            control, group, _ = bucket[pointer + 5 + item * 3:pointer + 8 + item * 3]
            if control > 31 or group == 255:
                raise EdltError('Selected scene has an unsupported output item')
        # Aliased/overlapping nonempty records cannot be safely interpreted as
        # separate configured scenes. Never normalize or rewrite those pointers.
        end = pointer + 5 + count * 3
        for other in range(1, 9):
            start = values[f'Scene{other}StartAddress'][0]
            if other == scene or start in (255, 65535) or bucket[start] == 255:
                continue
            other_end = start + 5 + bucket[start + 1] * 3
            if max(pointer, start) < min(end, other_end):
                raise EdltError('Selected scene overlaps another scene record')
        return SceneReference(scene, pointer, application, count, None if trigger == 255 else trigger,
                              None if trigger == 255 else action, None if name == 255 else name)

    def plan(self, current, *, page, position, scene=None, page_mode=None, label_type=None,
             label_index=None, status_type=None, status_index=None, status_text=None,
             mode='off-on', ramp_seconds=None, offset=None, scenes=None, cycle_variant=None):
        if isinstance(scenes, (tuple, list)):
            scenes = tuple(scenes)
        options = dict(page=page, position=position, scene=scene, page_mode=page_mode,
                       label_type=label_type, label_index=label_index, status_type=status_type,
                       status_index=status_index, status_text=status_text, mode=mode,
                       ramp_seconds=ramp_seconds, offset=offset, scenes=scenes, cycle_variant=cycle_variant)
        original = self.snapshot(current)
        if not isinstance(mode, str) or mode not in SCENE_MODES:
            raise EdltError('Scene mode must be off-on, ramp, nudge or cycle')
        if mode == 'cycle':
            if scene is not None or not isinstance(scenes, tuple) or not 1 <= len(scenes) <= 8:
                raise EdltError('Cycle mode requires 1..8 ordered scenes and cannot accompany scene')
            references = tuple(self.scene_reference(original, number) for number in scenes)
            reference = None
        else:
            if scenes is not None or cycle_variant is not None:
                raise EdltError('scenes and cycle_variant are only used by cycle mode')
            reference = self.scene_reference(original, scene)
            references = (reference,)
        updates = dict(original)
        nav = original['NavWidgetType'][0]
        if nav not in (0, 1, 255):
            raise EdltError('Unsupported navigation widget mode')
        if page_mode is None:
            page_mode = 'multiple' if nav == 1 else 'single'
        if page_mode not in ('single', 'multiple'):
            raise EdltError('page_mode must be single or multiple')
        _int(page, 'Page', 1, 1 if page_mode == 'single' else 4)
        _int(position, 'Position', 1, 5 if page_mode == 'single' else 4)
        widget = 6 + (page - 1) * 4 + position - 1
        terminated = False
        for index in range(6, 22):
            kind = original[_field(index)][0]
            if kind == 255:
                terminated = True
            elif kind and terminated:
                raise EdltError('An active widget follows a terminator; repair this existing layout first')
        record = [original[_field(widget, i)][0] for i in range(32)]
        if record[0] not in (0, 6, 255):
            raise EdltError('Selected widget is another type; replacing it is outside this workflow')
        fresh = record[0] != 6
        if fresh:
            # SceneData.SetToDefault does not zero opaque bytes, reset indexes,
            # select a scene, or clear all nine cycle-list bytes. Base index
            # properties are hidden by SceneData, rather than overridden.
            record[0], record[1], record[2], record[3], record[13] = 6, record[1] & 128, 38, 37, 255
            updates[f'Widget{widget}RestoreLevel'] = (0,)
        record[7:9] = SCENE_MODES[mode]
        if mode != 'cycle':
            record[6] = scene - 1
        else:
            # Original UI edits up to eight entries of the nine-byte storage;
            # the remaining bytes terminate the list. Repeated scenes remain.
            record[13:22] = [number - 1 for number in scenes] + [255] * (9 - len(scenes))
            if cycle_variant is not None:
                if cycle_variant not in ('cycle', 'select'):
                    raise EdltError('cycle_variant must be cycle or select')
                record[1] = (record[1] & 127) | (128 if cycle_variant == 'select' else 0)
        if ramp_seconds is not None:
            _int(ramp_seconds, 'Ramp seconds', 0, 1020)
            if mode != 'ramp' or ramp_seconds not in RAMP_SECONDS:
                raise EdltError('ramp_seconds is only valid for ramp mode and must use a supported ramp time')
            record[9] = RAMP_SECONDS.index(ramp_seconds)
        if mode == 'ramp' and record[9] >= len(RAMP_SECONDS):
            raise EdltError('Invalid existing ramp index; supply ramp_seconds')
        if offset is not None:
            if mode != 'nudge':
                raise EdltError('offset is only used by nudge mode')
            record[10] = _int(offset, 'Nudge offset')
        # Other inactive fields are preserved, including the single-scene byte
        # in cycle mode and cycle storage/variant in the single-scene modes.
        if label_type is not None:
            if not isinstance(label_type, str) or label_type not in SCENE_LABEL_TYPES:
                raise EdltError('Scene label type must be blank, dynamic-text, dynamic-icon or scene')
            record[1] = (record[1] & 0x8f) | (SCENE_LABEL_TYPES[label_type] << 4)
        label = (record[1] >> 4) & 7
        if label not in SCENE_LABEL_TYPES.values():
            raise EdltError('Unsupported existing scene label type')
        if label_index is not None:
            if label not in (1, 2):
                raise EdltError('Only dynamic scene labels use a label_index')
            record[11] = _int(label_index, 'Label index', 0, 3)
        if label in (1, 2) and (record[11] > 3 or any(ref.trigger_group is None for ref in references)):
            raise EdltError('Dynamic scene label requires an assigned trigger and index 0..3')
        if label == 3 and any(ref.name_index is None for ref in references):
            raise EdltError('Scene label requires the selected scene to have a name reference')
        if status_text is not None:
            if status_type not in (None, 'static') or status_index is not None or not isinstance(status_text, str):
                raise EdltError('status_text selects static status and cannot be combined with status_index')
            status_type = 'static'
        if status_type is not None:
            if not isinstance(status_type, str) or status_type not in SCENE_STATUS_TYPES:
                raise EdltError('Scene status type must be blank, static, dynamic-text or dynamic-icon')
            record[1] = (record[1] & 0xf0) | SCENE_STATUS_TYPES[status_type]
        status = record[1] & 15
        if status not in SCENE_STATUS_TYPES.values():
            raise EdltError('Unsupported existing scene status type')
        if status_index is not None:
            if status not in (5, 6, 7):
                raise EdltError('Blank scene status does not use an index')
            record[12] = _int(status_index, 'Status index', 0, 63 if status == 5 else 3)
        allocation = None
        if status_text is not None:
            view = self.common._place_record(updates, widget, record)
            allocation = self.common.allocate_static_text(view, status_text)
            updates.update(allocation.changes)
            record[12] = allocation.index
        if status == 5 and record[12] > 63:
            raise EdltError('Static scene status requires an index 0..63')
        if status in (6, 7) and (record[12] > 3 or any(ref.trigger_group is None for ref in references)):
            raise EdltError('Dynamic scene status requires an assigned trigger and index 0..3')
        updates = self.common._place_record(updates, widget, record)
        updates['NavWidgetType'] = (1 if page_mode == 'multiple' else 0,)
        for name, value in (('ConfigVersionMajor', 1), ('ConfigVersionMinor', 0)):
            if original[name] == (255,):
                updates[name] = (value,)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return SceneWidgetPlan(page, position, widget, page_mode, reference, original, changes,
                               bytes(record), allocation, options, mode, references if mode == 'cycle' else ())

    def apply(self, session, plan):
        if not isinstance(plan, SceneWidgetPlan) or not isinstance(plan.options, Mapping):
            raise EdltError('Use a scene widget plan returned by EdltSceneWidget.plan')
        _int(plan.widget, 'Plan widget', 6, 21)
        _int(plan.page, 'Plan page', 1, 4)
        _int(plan.position, 'Plan position', 1, 5)
        if not isinstance(plan.record, bytes) or len(plan.record) != 32:
            raise EdltError('Plan widget record must contain 32 bytes')
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError('Invalid scene plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated scene settings')
        expected = dict(plan.expected)
        expected.update(plan.changes)
        self.snapshot(expected)
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the scene plan was made')
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the scene plan')
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
