"""Exact KEYGL5 Fan speed thresholds and shared status text in database PP."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import (EdltLighting, EdltError, EdltApplyError, StaticTextAllocation,
                   LABEL_TYPES, _field, _int, _render)

_APP_GROUP_TYPES = frozenset((2, 3, 4, 5, 14, 15, 16))
_STATUS_FIELDS = ('off', 'low', 'medium', 'high')


@dataclass(frozen=True)
class FanWidgetPlan:
    page: int
    position: int
    widget: int
    page_mode: str
    group: int
    application: int
    speeds: int
    restore_level: int
    restore_source_widget: int | None
    status_forced: bool
    expected: Mapping
    changes: Mapping
    record: bytes
    default_allocations: tuple[tuple[str, StaticTextAllocation], ...]
    static_allocation: StaticTextAllocation | None
    status_allocations: Mapping
    options: Mapping

    def __post_init__(self):
        for name in ('expected', 'changes', 'options', 'status_allocations'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
        object.__setattr__(self, 'default_allocations', tuple(self.default_allocations))

    def as_dict(self):
        return {'format': 'cbus-edlt-fan-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00',
                'page': self.page, 'position': self.position, 'widget': self.widget,
                'page_mode': self.page_mode, 'application': self.application, 'group': self.group,
                'speeds': self.speeds, 'low_threshold': self.record[7], 'high_threshold': self.record[8],
                'status_type': 'static', 'status_forced': self.status_forced,
                'status_indices': dict(zip(_STATUS_FIELDS, self.record[10:14])),
                'restore_level': self.restore_level, 'restore_source_widget': self.restore_source_widget,
                'record_hex': self.record.hex(),
                'changes': {k: list(v) if isinstance(v, tuple) else v for k, v in self.changes.items()},
                'default_allocations': [{'field': field, **allocation.as_dict()} for field, allocation in self.default_allocations],
                'static_allocation': self.static_allocation.as_dict() if self.static_allocation else None,
                'status_allocations': {k: v.as_dict() if v else None for k, v in self.status_allocations.items()},
                'saved': False, 'physical_device_verified': False}


class EdltFanWidget:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def plan(self, current, *, page, position, group, application='primary', speeds=None,
             low_threshold=None, high_threshold=None, page_mode=None,
             label_type=None, label_index=None, label_text=None,
             off_text=None, low_text=None, medium_text=None, high_text=None,
             off_index=None, low_index=None, medium_index=None, high_index=None):
        options = dict(page=page, position=position, group=group, application=application,
                       speeds=speeds, low_threshold=low_threshold, high_threshold=high_threshold,
                       page_mode=page_mode, label_type=label_type, label_index=label_index,
                       label_text=label_text, off_text=off_text, low_text=low_text,
                       medium_text=medium_text, high_text=high_text, off_index=off_index,
                       low_index=low_index, medium_index=medium_index, high_index=high_index)
        _int(group, 'Fan group', 0, 254)
        if application not in ('primary', 'secondary'):
            raise EdltError('application must be primary or secondary')
        if speeds is not None:
            _int(speeds, 'Fan speeds', 1, 3)
        for value in (low_threshold, high_threshold):
            if value is not None:
                _int(value, 'Fan threshold', 1, 254)
        requested_status = dict(zip(_STATUS_FIELDS, zip((off_text, low_text, medium_text, high_text),
                                                       (off_index, low_index, medium_index, high_index))))
        for name, (text, index) in requested_status.items():
            if text is not None and (not isinstance(text, str) or index is not None):
                raise EdltError(f'{name}_text and {name}_index are mutually exclusive; text must be a string')
            if index is not None:
                _int(index, name + ' status index', 0, 63)
        original = self.snapshot(current)
        self.common.static_references(original)
        app = original['PrimaryApplication' if application == 'primary' else 'SecondaryApplication'][0]
        if not 48 <= app <= 95:
            raise EdltError('Fan requires an assigned Lighting application in 48..95')
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
        if any(original[_field(index)][0] in _APP_GROUP_TYPES for index in range(1, 6)):
            raise EdltError('Unsupported AppGroup widget in a standby position')
        record = [original[_field(widget, i)][0] for i in range(32)]
        if record[0] not in (0, 4, 255):
            raise EdltError('Selected widget is another type; replacing it is outside this workflow')
        defaults = []

        def allocate(text, slot):
            view = self.common._place_record(updates, widget, record)
            allocation = self.common.allocate_static_text(view, text)
            updates.update(allocation.changes)
            record[slot] = allocation.index
            return allocation

        if record[0] != 4:
            # MultiLevelData defaults run before FanControllerData defaults.
            # Blank label's empty text returns255 without allocating a string.
            # Low/Medium/High are unconditional references even while hidden.
            record[0:4] = (4, 5, 134, 134)
            record[6:11] = (255, 84, 170, 255, 0)
            for name, slot, text in (('off', 10, 'Off'), ('low', 11, 'Low'),
                                      ('medium', 12, 'Medium'), ('high', 13, 'High')):
                defaults.append((name, allocate(text, slot)))
            record[1:4] = (0x35, 4, 3)
            record[9] = 0
            defaults.append(('label', allocate('Fan', 9)))
            for name, slot, text in (('off', 10, 'Off'), ('low', 11, 'Low'),
                                      ('medium', 12, 'Medium'), ('high', 13, 'High')):
                defaults.append((name, allocate(text, slot)))
        group_changed = record[6] != group
        application_changed = (record[1] >> 7) != (application == 'secondary')
        restore = original[f'Widget{widget}RestoreLevel'][0]
        restore_source = widget
        if group_changed:
            restore, restore_source = 0, None
            for index in range(6, 22):
                if (index != widget and original[_field(index)][0] in _APP_GROUP_TYPES
                        and original[_field(index, 6)] == (group,)):
                    restore, restore_source = original[f'Widget{index}RestoreLevel'][0], index
                    break
        record[1] = (record[1] & 127) | (128 if application == 'secondary' else 0)
        record[6] = group
        # Original BeforeSavePPData forces static status after all text edits.
        # An Off edit on a nonstatic source would be discarded by that forcing.
        # Require a normalization plan first instead of accepting a lost edit.
        status_forced = record[1] & 15 != 5
        if status_forced and (off_text is not None or off_index is not None):
            raise EdltError('Normalize existing nonstatic Fan status first, then edit its Off reference')
        if speeds is not None:
            record[7:9] = {1: (0, 0), 2: (127, 127), 3: (84, 170)}[speeds]
        else:
            low, high = record[7:9]
            speeds = 1 if low == high == 0 else 2 if 1 <= low == high <= 254 else 3 if 1 <= low < high <= 254 else None
            if speeds is None:
                raise EdltError('Invalid existing Fan thresholds; supply speeds to reset them')
        if speeds == 1:
            if low_threshold is not None or high_threshold is not None:
                raise EdltError('One-speed Fan does not use thresholds')
        elif speeds == 2:
            if high_threshold is not None:
                raise EdltError('Two-speed Fan uses low_threshold for both stored thresholds')
            if low_threshold is not None:
                record[7:9] = (low_threshold, low_threshold)
        else:
            if low_threshold is not None:
                record[7] = low_threshold
            if high_threshold is not None:
                record[8] = high_threshold
            if not 1 <= record[7] < record[8] <= 254:
                raise EdltError('Three-speed Fan requires 1 <= low_threshold < high_threshold <= 254')
        for name, minimum in (('low', 2), ('medium', 3)):
            if speeds < minimum and any(value is not None for value in requested_status[name]):
                raise EdltError(f'{name} status is hidden for this Fan speed count; existing reference is preserved')
        if label_text is not None:
            if label_type not in (None, 'static') or label_index is not None or not isinstance(label_text, str):
                raise EdltError('label_text selects static display and cannot accompany label_index')
            label_type = 'static'
        previous_code = (record[1] >> 4) & 7
        if label_type is None and previous_code in (1, 2) and (group_changed or application_changed or label_index is not None):
            raise EdltError('Changing a dynamic reference requires explicit label_type; network variant metadata is not in PP')
        if label_type is not None:
            if not isinstance(label_type, str) or label_type not in LABEL_TYPES:
                raise EdltError('Unsupported label display type')
            code = LABEL_TYPES[label_type]
            if previous_code != code and not (previous_code in (1, 2) and code in (1, 2)):
                record[9] = 0
            record[1] = (record[1] & 0x8f) | (code << 4)
        code = (record[1] >> 4) & 7
        if label_index is not None:
            if code not in (1, 2, 3):
                raise EdltError('This label display does not use an index')
            record[9] = _int(label_index, 'Label index', 0, 63 if code == 3 else 3)
        static_allocation = allocate(label_text, 9) if label_text is not None else None
        if code not in LABEL_TYPES.values() or (code == 3 and record[9] > 63) or (code in (1, 2) and record[9] > 3):
            raise EdltError('Invalid existing label type or index')
        status_allocations = {}
        for slot, (name, (text, index)) in enumerate(requested_status.items(), 10):
            if index is not None:
                record[slot] = index
            status_allocations[name] = allocate(text, slot) if text is not None else None
        if status_forced:
            record[1] = (record[1] & 240) | 5
            record[10] = 0
        updates = self.common._place_record(updates, widget, record)
        updates[f'Widget{widget}RestoreLevel'] = (restore,)
        updates['NavWidgetType'] = (1 if page_mode == 'multiple' else 0,)
        for name, value in (('ConfigVersionMajor', 1), ('ConfigVersionMinor', 0)):
            if original[name] == (255,):
                updates[name] = (value,)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        self.common.static_references(updates)
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return FanWidgetPlan(page, position, widget, page_mode, group, app, speeds, restore,
                             restore_source, status_forced, original, changes, bytes(record),
                             tuple(defaults), static_allocation, status_allocations, options)

    def apply(self, session, plan):
        if not isinstance(plan, FanWidgetPlan) or not isinstance(plan.options, Mapping):
            raise EdltError('Use a Fan widget plan returned by EdltFanWidget.plan')
        _int(plan.speeds, 'Plan speeds', 1, 3)
        if not isinstance(plan.status_forced, bool):
            raise EdltError('Plan status_forced must be boolean')
        _int(plan.widget, 'Plan widget', 6, 21)
        _int(plan.page, 'Plan page', 1, 4)
        _int(plan.position, 'Plan position', 1, 5)
        _int(plan.group, 'Plan group', 0, 254)
        _int(plan.application, 'Plan application', 48, 95)
        _int(plan.restore_level, 'Plan restore level')
        if plan.restore_source_widget is not None:
            _int(plan.restore_source_widget, 'Plan restore source widget', 6, 21)
        if not isinstance(plan.record, bytes) or len(plan.record) != 32:
            raise EdltError('Plan widget record must contain 32 bytes')
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError('Invalid Fan plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated Fan settings')
        expected = dict(plan.expected)
        expected.update(plan.changes)
        self.snapshot(expected)
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the Fan plan was made')
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the Fan plan')
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
