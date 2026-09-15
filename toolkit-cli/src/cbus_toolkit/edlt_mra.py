"""Original eDLT multiroom-audio settings and distributed zone globals.

This module operates on PP values. It does not transmit Audio Control messages
or configure a matrix switcher/amplifier.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltError, _field, _int

MRA_WIDGET_TYPES = MappingProxyType({'zone-control': 7, 'source-select': 8, 'source-control': 9})


@dataclass(frozen=True)
class MRAPropagation:
    multiplexer: int
    zone: int
    source_widget: int | None
    widgets: tuple[int, ...]
    previous: Mapping
    changes: Mapping

    def __post_init__(self):
        for name in ('previous', 'changes'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'multiplexer': self.multiplexer, 'zone': self.zone,
                'multiplexer_raw': self.multiplexer - 1, 'zone_raw': self.zone - 1,
                'multiplexer_ui_canonical': self.multiplexer in (1, 2, 3),
                'source_widget': self.source_widget, 'widgets': list(self.widgets),
                'previous': {str(widget): {'multiplexer_raw': old[0], 'zone_raw': old[1],
                                          'status_bits': old[2]}
                             for widget, old in self.previous.items()},
                'changes': {name: list(value) for name, value in self.changes.items()},
                'distributed_across_mra_widgets': True}


def _mra_records(current, *, allow_stored_placement=False):
    if not isinstance(current, Mapping):
        raise EdltError('MRA normalization requires a normalized PP mapping')
    result = {}
    for widget in range(1, 22):
        name = _field(widget)
        try:
            value = current[name]
            if not isinstance(value, (tuple, list)) or len(value) != 1:
                raise EdltError('MRA normalization requires scalar numeric PP tuples: ' + name)
            kind = _int(value[0], name)
            if kind not in MRA_WIDGET_TYPES.values():
                continue
            if widget < 6 and not allow_stored_placement:
                raise EdltError('MRA widgets are not offered in standby positions')
            name = _field(widget, 1)
            value = current[name]
            if not isinstance(value, (tuple, list)) or len(value) != 1:
                raise EdltError('MRA normalization requires scalar numeric PP tuples: ' + name)
            result[widget] = _int(value[0], name)
        except KeyError as error:
            raise EdltError('MRA normalization is missing ' + name) from error
    return result


def normalize_mra_globals(current, *, source=None, multiplexer=None, zone=None,
                          _preserve_stored_multiplexer=False, _preserve_stored_placement=False):
    """Plan exact original global propagation using normalized numeric PP values.

    Public multiplexer1..3 and zone1..8 match UI labels. By default the first
    existing MRA record supplies both settings; with none, they default to1/1.
    ``source`` is the snapshot before a new widget's type conversion, matching
    original InitializeMRAGlobalValues timing. Only byte1 upper bits change.
    There is no persistent setting when no MRA widget exists.
    """
    if type(_preserve_stored_placement) is not bool:
        raise EdltError('Internal placement preservation flag must be boolean')
    if type(_preserve_stored_multiplexer) is not bool:
        raise EdltError('Internal preservation flag must be boolean')
    if multiplexer is not None:
        _int(multiplexer, 'MRA multiplexer', 1, 3)
    if zone is not None:
        _int(zone, 'MRA zone', 1, 8)
    targets = _mra_records(current, allow_stored_placement=_preserve_stored_placement)
    originals = _mra_records(current if source is None else source, allow_stored_placement=_preserve_stored_placement)
    source_widget = next(iter(originals), None)
    initial = originals[source_widget] if source_widget is not None else 0
    if multiplexer is None:
        multiplexer = (initial >> 6) + 1
        if multiplexer > 3 and not _preserve_stored_multiplexer:
            raise EdltError('First existing MRA multiplexer is outside UI1..3; supply an explicit multiplexer')
    if zone is None:
        zone = ((initial >> 3) & 7) + 1
    upper = ((multiplexer - 1) << 6) | ((zone - 1) << 3)
    changes, previous = {}, {}
    for widget, control in targets.items():
        previous[widget] = (control >> 6, (control >> 3) & 7, control & 7)
        value = upper | (control & 7)
        if value != control:
            changes[_field(widget, 1)] = (value,)
    return MRAPropagation(multiplexer, zone, source_widget, tuple(targets), previous, changes)

from .edlt import EdltLighting, EdltApplyError, StaticTextAllocation, RAMP_SECONDS, _render

MRA_VARIANTS = MappingProxyType({
    'zone-control': MappingProxyType({'volume': 0, 'treble': 1, 'bass': 2, 'balance': 3}),
    'source-select': MappingProxyType({'next-previous': 0, 'one-absolute': 1, 'two-absolute': 2}),
    'source-control': MappingProxyType({'dynamic-1': 0, 'dynamic-2': 1, 'dynamic-1-and-2': 2})})
MRA_KEY_MODES = MappingProxyType({'decrease-increase': (15, 16), 'nudge': (21, 22)})
MRA_STATUS_TYPES = MappingProxyType({'blank': 0, 'bar': 3, 'level': 1, 'percent': 2, 'static': 5})
BUILTIN_ICON_INDICES = frozenset((*range(39), *range(128, 142), 252, 253, 254))


def _record(current, widget):
    return bytes(current[_field(widget, offset)][0] for offset in range(32))


@dataclass(frozen=True)
class MRAWidgetPlan:
    action: str
    kind: str | None
    page: int | None
    position: int | None
    widget: int | None
    page_mode: str
    variant: str | None
    key_mode: str | None
    record_before: bytes | None
    record: bytes | None
    restore_level: int | None
    propagation: MRAPropagation
    default_status_allocation: StaticTextAllocation | None
    label_allocation: StaticTextAllocation | None
    status_allocation: StaticTextAllocation | None
    macro_normalized: bool
    expected: Mapping
    changes: Mapping
    options: Mapping

    def __post_init__(self):
        for name in ('expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-mra-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00', 'action': self.action,
                'kind': self.kind, 'page': self.page, 'position': self.position, 'widget': self.widget,
                'page_mode': self.page_mode, 'variant': self.variant, 'key_mode': self.key_mode,
                'record_before_hex': None if self.record_before is None else self.record_before.hex(),
                'record_hex': None if self.record is None else self.record.hex(),
                'restore_level': self.restore_level, 'globals': self.propagation.as_dict(),
                'macro_normalized': self.macro_normalized,
                'ramp_seconds': RAMP_SECONDS[self.record[9]] if self.kind == 'zone-control'
                                and self.key_mode == 'decrease-increase' else None,
                'offset_raw': self.record[10] if self.kind == 'zone-control' else None,
                'source_bytes': list(self.record[7:9]) if self.kind == 'source-select' else None,
                'default_status_allocation': None if self.default_status_allocation is None else self.default_status_allocation.as_dict(),
                'label_allocation': None if self.label_allocation is None else self.label_allocation.as_dict(),
                'status_allocation': None if self.status_allocation is None else self.status_allocation.as_dict(),
                'changes': {name: list(value) if isinstance(value, tuple) else value for name, value in self.changes.items()},
                'saved': False, 'physical_device_verified': False, 'audio_control_sent': False}


class EdltMRAWidget:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        try:
            layout = self.codec.layout('UseBigIcon')
        except (ValueError, KeyError) as error:
            raise EdltError('Unsupported MRA UseBigIcon layout') from error
        if ((layout.address, layout.array_size, layout.array_skip, layout.bit_address,
             layout.bit_size, layout.parameter.type) != (0x118, 1, 0, 4, 1, 'bit')):
            raise EdltError('Unsupported MRA UseBigIcon layout')

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def _source_default(self, view, widget, transient_index):
        if transient_index in range(64) or transient_index == 255:
            return self.common.allocate_static_text(view, 'Source')
        # During original SetToDefault, the old opaque byte10 still appears
        # in GetUsedStaticText until StatusValueText replaces it. It counts
        # toward capacity even though the intermediate reference is not a
        # selectable string slot. Keep this allowance local to that transition.
        shadow = {**view, _field(widget, 10): (255,)}
        allocation = self.common.allocate_static_text(shadow, 'Source')
        if allocation.reused:
            return allocation
        used = tuple(sorted({*allocation.used_indices, transient_index}))
        if len(used) > 63:
            raise EdltError('Static text table is full during original MRA Source default allocation')
        return StaticTextAllocation(allocation.index, allocation.text, False, allocation.changes, used)

    def _finish(self, original, updates, widget=None, record=None, page_mode=None, source=None,
                multiplexer=None, zone=None):
        if widget is None:
            # This only invokes the shared save normalization; no selected
            # defaults or macro getters are evaluated for a global-only edit.
            widget = next(iter(_mra_records(updates)))
            record = _record(updates, widget)
        updates = self.common._place_record(updates, widget, record, normalize_mra=False)
        propagation = normalize_mra_globals(updates, source=original if source is None else source,
                                            multiplexer=multiplexer, zone=zone)
        updates.update(propagation.changes)
        if page_mode is not None:
            updates['NavWidgetType'] = (1 if page_mode == 'multiple' else 0,)
        for name, value in (('ConfigVersionMajor', 1), ('ConfigVersionMinor', 0)):
            if original[name] == (255,):
                updates[name] = (value,)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        self.common.static_references(updates)
        updates.update(self.crcs(updates))
        return updates, propagation

    def plan(self, current, *, page, position, kind, variant=None, multiplexer=None, zone=None,
             page_mode=None, key_mode=None, ramp_seconds=None, source1=None, source2=None,
             label_text=None, label_index=None, status_type=None, status_text=None, status_index=None,
             on_icon=None, off_icon=None):
        options = dict(page=page, position=position, kind=kind, variant=variant, multiplexer=multiplexer,
                       zone=zone, page_mode=page_mode, key_mode=key_mode, ramp_seconds=ramp_seconds,
                       source1=source1, source2=source2, label_text=label_text, label_index=label_index,
                       status_type=status_type, status_text=status_text, status_index=status_index,
                       on_icon=on_icon, off_icon=off_icon)
        if not isinstance(kind, str) or kind not in MRA_WIDGET_TYPES:
            raise EdltError('kind must be zone-control/source-select/source-control')
        variants = MRA_VARIANTS[kind]
        if variant is not None and (not isinstance(variant, str) or variant not in variants):
            raise EdltError('Unsupported MRA variant for ' + kind)
        if kind != 'zone-control' and any(value is not None for value in (key_mode, ramp_seconds, status_type, off_icon)):
            raise EdltError('key_mode/ramp_seconds/status_type/off_icon apply only to Zone Control')
        if kind != 'source-select' and any(value is not None for value in (source1, source2)):
            raise EdltError('Absolute sources apply only to Source Select')
        if kind == 'source-control' and (status_text is not None or status_index is not None):
            raise EdltError('Source Control has no status text field')
        if key_mode is not None and (not isinstance(key_mode, str) or key_mode not in MRA_KEY_MODES):
            raise EdltError('key_mode must be decrease-increase/nudge')
        if ramp_seconds is not None:
            _int(ramp_seconds, 'Ramp seconds', 0, 1020)
            if ramp_seconds not in RAMP_SECONDS:
                raise EdltError('Unsupported MRA ramp duration')
        if status_type is not None and (not isinstance(status_type, str) or status_type not in MRA_STATUS_TYPES):
            raise EdltError('Unsupported MRA Zone status type')
        for value in (source1, source2):
            if value is not None:
                _int(value, 'Absolute source', 1, 7)
        for name, text, index in (('label', label_text, label_index), ('status', status_text, status_index)):
            if text is not None and (not isinstance(text, str) or index is not None):
                raise EdltError(name + '_text must be a string and cannot accompany an index')
            if index is not None:
                _int(index, name + ' index')
                if index not in range(64) and index != 255:
                    raise EdltError('MRA text indexes must be0..63 or255')
        for value in (on_icon, off_icon):
            if value is not None:
                _int(value, 'Icon index')
                if value not in BUILTIN_ICON_INDICES:
                    raise EdltError('Icon is not offered by the original Toolkit chooser')
        original = self.snapshot(current)
        self.common.static_references(original)
        initial_globals = normalize_mra_globals(original, multiplexer=multiplexer, zone=zone)
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
        before = _record(original, widget)
        if before[0] not in (0, *range(2, 11), *range(12, 17), 255):
            raise EdltError('Selected source widget is outside original functional UI types')
        if any(value is not None for value in (on_icon, off_icon)) and original.get('UseBigIcon') != (1,):
            raise EdltError('Explicit icon edits require the unit UseBigIcon setting enabled')
        updates, record = dict(original), bytearray(before)
        default_allocation = None
        if before[0] != MRA_WIDGET_TYPES[kind]:
            record[0] = MRA_WIDGET_TYPES[kind]
            record[1] &= 248
            record[6] = 0
            updates[f'Widget{widget}RestoreLevel'] = (0,)
            if kind == 'zone-control':
                record[2:4] = (30, 29)
                record[7:13] = (15, 16, 3, 13, 255, 255)
            elif kind == 'source-select':
                record[2:4] = (136, 136)
                record[9] = 255
                view = self.common._place_record(updates, widget, record, normalize_mra=False)
                default_allocation = self._source_default(view, widget, record[10])
                updates.update(default_allocation.changes)
                record[10] = default_allocation.index
            else:
                record[2:4] = (138, 138)
                record[7] = 255
        if variant is not None:
            record[6] = variants[variant]
        if record[6] not in variants.values():
            raise EdltError('Invalid existing MRA variant; supply an explicit variant')
        variant = next(name for name, value in variants.items() if value == record[6])
        macro_normalized = False
        if kind == 'zone-control':
            if key_mode is not None:
                record[7:9] = MRA_KEY_MODES[key_mode]
            elif tuple(record[7:9]) not in MRA_KEY_MODES.values():
                record[7:9] = MRA_KEY_MODES['decrease-increase']
                macro_normalized = True
            key_mode = next(name for name, value in MRA_KEY_MODES.items() if value == tuple(record[7:9]))
            if ramp_seconds is not None:
                if key_mode != 'decrease-increase':
                    raise EdltError('Ramp duration is hidden for Nudge; change key_mode first')
                record[9] = RAMP_SECONDS.index(ramp_seconds)
            if key_mode == 'decrease-increase' and record[9] >= len(RAMP_SECONDS):
                raise EdltError('Invalid existing ramp code; supply an explicit ramp duration')
            if status_type is not None:
                record[1] = (record[1] & 248) | MRA_STATUS_TYPES[status_type]
            if record[1] & 7 not in MRA_STATUS_TYPES.values():
                raise EdltError('Invalid existing Zone status; supply an explicit status_type')
            if (status_text is not None or status_index is not None) and record[1] & 7 != 5:
                raise EdltError('Status text is hidden unless Zone status_type is static')
            label_slot, status_slot = 11, 12
        elif kind == 'source-select':
            for slot, value, active in ((7, source1, record[6] > 0), (8, source2, record[6] > 1)):
                if value is not None:
                    if not active:
                        raise EdltError('Absolute source is hidden for this variant')
                    record[slot] = value - 1
                if active and record[slot] > 6:
                    raise EdltError('Invalid existing absolute source; supply an explicit source')
            if (status_text is not None or status_index is not None) and record[6] == 0:
                raise EdltError('Status text is hidden for next-previous')
            label_slot, status_slot = 9, 10
        else:
            label_slot, status_slot = 7, None
        if on_icon is not None:
            record[2] = on_icon
            if kind != 'zone-control':
                record[3] = on_icon
        if off_icon is not None:
            record[3] = off_icon
        allocations = []
        for slot, text, index in ((label_slot, label_text, label_index), (status_slot, status_text, status_index)):
            allocation = None
            if slot is not None:
                if index is not None:
                    record[slot] = index
                if text is not None:
                    if not text.strip():
                        record[slot] = 255
                    else:
                        view = self.common._place_record(updates, widget, record, normalize_mra=False)
                        allocation = self.common.allocate_static_text(view, text)
                        updates.update(allocation.changes)
                        record[slot] = allocation.index
            allocations.append(allocation)
        updates, propagation = self._finish(original, updates, widget, record, page_mode,
            multiplexer=initial_globals.multiplexer, zone=initial_globals.zone)
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return MRAWidgetPlan('widget', kind, page, position, widget, page_mode, variant, key_mode,
            before, _record(updates, widget), updates[f'Widget{widget}RestoreLevel'][0], propagation,
            default_allocation, *allocations, macro_normalized, original, changes, options)

    def plan_globals(self, current, *, multiplexer=None, zone=None):
        options = dict(multiplexer=multiplexer, zone=zone)
        original = self.snapshot(current)
        self.common.static_references(original)
        if not _mra_records(original):
            raise EdltError('Create an MRA widget before storing distributed MRA globals')
        nav = original['NavWidgetType'][0]
        if nav not in (0, 1, 255):
            raise EdltError('Unsupported navigation widget mode')
        mode = 'multiple' if nav == 1 else 'single'
        updates, propagation = self._finish(original, dict(original), multiplexer=multiplexer, zone=zone)
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return MRAWidgetPlan('globals', None, None, None, None, mode, None, None, None, None, None,
                             propagation, None, None, None, False, original, changes, options)

    @staticmethod
    def _interrupted(error, plan, attempted, original_error=None):
        evidence = {**plan.as_dict(), 'verified': False, 'saved': False,
                    'attempted_parameters': list(attempted), 'pp_state_uncertain': bool(attempted),
                    'automatic_retries': 0}
        if original_error is not None:
            evidence['original_error'] = {'type': type(original_error).__name__, 'error': str(original_error)}
        error.edlt_mra_evidence = evidence

    def apply(self, session, plan):
        if not isinstance(plan, MRAWidgetPlan) or not isinstance(plan.options, Mapping):
            raise EdltError('Use an MRA plan returned by EdltMRAWidget')
        if type(plan.macro_normalized) is not bool:
            raise EdltError('Plan macro_normalized must be boolean')
        if plan.action == 'widget':
            for value, name, high in ((plan.widget, 'widget', 21), (plan.page, 'page', 4),
                                     (plan.position, 'position', 5)):
                _int(value, 'Plan ' + name, 1, high)
            _int(plan.restore_level, 'Plan restore level')
            if not isinstance(plan.record, bytes) or len(plan.record) != 32:
                raise EdltError('Plan MRA record must contain32 bytes')
        try:
            canonical = self.plan(plan.expected, **plan.options) if plan.action == 'widget' else (
                self.plan_globals(plan.expected, **plan.options) if plan.action == 'globals' else None)
        except TypeError as error:
            raise EdltError('Invalid MRA plan options') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated MRA settings')
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the MRA plan was made')
        expected = {**plan.expected, **plan.changes}
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the MRA plan')
        except (KeyboardInterrupt, SystemExit) as error:
            self._interrupted(error, plan, attempted)
            raise
        except Exception as error:
            rollback_errors = []
            try:
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
            except (KeyboardInterrupt, SystemExit) as interrupted:
                self._interrupted(interrupted, plan, attempted, error)
                interrupted.edlt_mra_evidence['rollback_errors'] = rollback_errors
                raise
            raise EdltApplyError(error, rollback_errors, attempted) from error
        return {**plan.as_dict(), 'verified': True}

    def configure(self, session, **options):
        self.common._verify_identity(session)
        return self.apply(session, self.plan(session.values(), **options))

    def configure_globals(self, session, **options):
        self.common._verify_identity(session)
        return self.apply(session, self.plan_globals(session.values(), **options))
