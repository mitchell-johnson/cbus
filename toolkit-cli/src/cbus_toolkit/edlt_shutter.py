"""Exact KEYGL5 Shutter two-key widgets in database PP sessions.

Original ShutterRelayData uses byte7 as mode, not a dual macro pair. New
widgets allocate the default Blind text before subsequent label/status edits.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import (EdltLighting, EdltError, EdltApplyError, StaticTextAllocation,
                   LABEL_TYPES, STATUS_TYPES, _field, _int, _render)

# Exact subclasses of StatusLabelAppGroupData in the original model.
_APP_GROUP_TYPES = frozenset((2, 3, 4, 5, 14, 15, 16))
SHUTTER_MODES = MappingProxyType({'two-key': 0, 'two-key-presets': 1})


@dataclass(frozen=True)
class ShutterWidgetPlan:
    page: int
    position: int
    widget: int
    page_mode: str
    group: int
    application: int
    mode: str
    restore_level: int
    restore_source_widget: int | None
    expected: Mapping
    changes: Mapping
    record: bytes
    default_label_allocation: StaticTextAllocation | None
    static_allocation: StaticTextAllocation | None
    status_allocation: StaticTextAllocation | None
    options: Mapping

    def __post_init__(self):
        for name in ('expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-shutter-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00', 'mode': self.mode,
                'page': self.page, 'position': self.position, 'widget': self.widget,
                'page_mode': self.page_mode, 'application': self.application, 'group': self.group,
                'preset_left': self.record[8], 'preset_right': self.record[9], 'restore_level': self.restore_level,
                'restore_source_widget': self.restore_source_widget, 'record_hex': self.record.hex(),
                'changes': {k: list(v) if isinstance(v, tuple) else v for k, v in self.changes.items()},
                'default_label_allocation': self.default_label_allocation.as_dict() if self.default_label_allocation else None,
                'static_allocation': self.static_allocation.as_dict() if self.static_allocation else None,
                'status_allocation': self.status_allocation.as_dict() if self.status_allocation else None,
                'saved': False, 'physical_device_verified': False}


class EdltShutterWidget:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def plan(self, current, *, page, position, group, application='primary', mode='two-key',
             preset_left=None, preset_right=None, page_mode=None,
             label_type=None, label_index=None, label_text=None,
             status_type=None, status_index=None, status_text=None):
        options = dict(page=page, position=position, group=group, application=application, mode=mode,
                       preset_left=preset_left, preset_right=preset_right, page_mode=page_mode,
                       label_type=label_type, label_index=label_index, label_text=label_text,
                       status_type=status_type, status_index=status_index, status_text=status_text)
        _int(group, 'Shutter group', 0, 254)
        if not isinstance(mode, str) or mode not in SHUTTER_MODES:
            raise EdltError('Shutter mode must be two-key or two-key-presets')
        if application not in ('primary', 'secondary'):
            raise EdltError('application must be primary or secondary')
        for preset in (preset_left, preset_right):
            if preset is not None:
                if mode != 'two-key-presets':
                    raise EdltError('Presets are only set in two-key-presets mode')
                _int(preset, 'Shutter preset', 6, 248)
        original = self.snapshot(current)
        self.common.static_references(original)
        app = original['PrimaryApplication' if application == 'primary' else 'SecondaryApplication'][0]
        if not 48 <= app <= 95:
            raise EdltError('Shutter requires an assigned Lighting application in 48..95')
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
        # Such standby records are never offered by the original UI and have
        # no schema-backed RestoreLevel. Do not invent one during group lookup.
        if any(original[_field(index)][0] in _APP_GROUP_TYPES for index in range(1, 6)):
            raise EdltError('Unsupported AppGroup widget in a standby position')
        record = [original[_field(widget, i)][0] for i in range(32)]
        if record[0] not in (0, 3, 255):
            raise EdltError('Selected widget is another type; replacing it is outside this workflow')
        fresh = record[0] != 3
        default_allocation = None
        if fresh:
            # Original base category setters reset status only if nonblank;
            # Shutter's new static label always resets its index to zero.
            if record[1] & 0x0f:
                record[11] = 0
            record[0:4] = (3, 0x30, 18, 17)
            record[6:11] = (255, 0, 86, 170, 0)
            view = self.common._place_record(updates, widget, record)
            default_allocation = self.common.allocate_static_text(view, 'Blind')
            updates.update(default_allocation.changes)
            record[10] = default_allocation.index
        group_changed = record[6] != group
        application_changed = (record[1] >> 7) != (application == 'secondary')
        restore = original[f'Widget{widget}RestoreLevel'][0]
        restore_source = widget
        if group_changed:
            restore, restore_source = 0, None
            # Original GetRestoreLevelForGroup checks numeric group only,
            # including across application boundaries, in widget order.
            for index in range(6, 22):
                if (index != widget and original[_field(index)][0] in _APP_GROUP_TYPES
                        and original[_field(index, 6)] == (group,)):
                    restore = original[f'Widget{index}RestoreLevel'][0]
                    restore_source = index
                    break
        record[1] = (record[1] & 127) | (128 if application == 'secondary' else 0)
        record[6], record[7] = group, SHUTTER_MODES[mode]
        for slot, preset in ((8, preset_left), (9, preset_right)):
            if preset is not None:
                record[slot] = preset
            if not 6 <= record[slot] <= 248:
                raise EdltError('Invalid existing Shutter preset; supply a valid preset in two-key-presets mode')
        allocations = [None, None]
        for entry, (option, index, text, codes, shift, mask, slot, static_code, dynamic_codes) in enumerate((
                (label_type, label_index, label_text, LABEL_TYPES, 4, 0x70, 10, 3, (1, 2)),
                (status_type, status_index, status_text, STATUS_TYPES, 0, 0x0f, 11, 5, (6, 7)))):
            name = 'label' if entry == 0 else 'status'
            if text is not None:
                if option not in (None, 'static') or index is not None or not isinstance(text, str):
                    raise EdltError(f'{name}_text selects static display and cannot accompany {name}_index')
                option = 'static'
            previous_code = (record[1] & mask) >> shift
            if (option is None and previous_code in dynamic_codes
                    and (group_changed or application_changed or index is not None)):
                # Shutter's index setters always refresh network metadata,
                # even when assigning the same index. An omitted index is
                # the only way to retain it without a declared display type.
                raise EdltError(f'Changing a dynamic reference requires explicit {name}_type; network variant metadata is not in PP')
            if option is not None:
                if not isinstance(option, str) or option not in codes:
                    raise EdltError('Unsupported label or status display type')
                code = codes[option]
                if previous_code != code and not (previous_code in dynamic_codes and code in dynamic_codes):
                    record[slot] = 0
                record[1] = (record[1] & ~mask) | (code << shift)
            code = (record[1] & mask) >> shift
            if index is not None:
                if code != static_code and code not in dynamic_codes:
                    raise EdltError('This label/status display does not use an index')
                record[slot] = _int(index, 'Label/status index', 0, 63 if code == static_code else 3)
            if text is not None:
                # Sequential edits reserve the first reference before the
                # second allocation; whole-unit scene/page/widget refs apply.
                view = self.common._place_record(updates, widget, record)
                allocation = self.common.allocate_static_text(view, text)
                allocations[entry] = allocation
                updates.update(allocation.changes)
                record[slot] = allocation.index
            if code not in codes.values() or (code == static_code and record[slot] > 63) or (code in dynamic_codes and record[slot] > 3):
                raise EdltError('Invalid existing label/status type or index')
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
        return ShutterWidgetPlan(page, position, widget, page_mode, group, app, mode, restore,
                                 restore_source, original, changes, bytes(record), default_allocation, *allocations, options)

    def apply(self, session, plan):
        if not isinstance(plan, ShutterWidgetPlan) or not isinstance(plan.options, Mapping):
            raise EdltError('Use a Shutter widget plan returned by EdltShutterWidget.plan')
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
            raise EdltError('Invalid Shutter plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated Shutter settings')
        expected = dict(plan.expected)
        expected.update(plan.changes)
        self.snapshot(expected)
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the Shutter plan was made')
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the Shutter plan')
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
