"""Original KEYGL5 HVAC Temperature Display settings in database PP.

Application172 group references are numeric settings. This workflow neither
creates database groups nor sends HVAC control or measurement messages.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .edlt import EdltLighting, EdltError, EdltApplyError, _field, _int, _render

TEMPERATURE_UNITS = MappingProxyType({'celsius': 0, 'fahrenheit': 1})
# Exact original graphics DLL selector: nonempty0xFF icon buffers, plus blank0.
BUILTIN_ICON_INDICES = frozenset((*range(39), *range(128, 142), 252, 253, 254))
_STANDBY_TYPES = frozenset((0, 10, 11, 12, 13, 255))
_FUNCTION_TYPES = frozenset((0, *range(2, 11), *range(12, 17), 255))


@dataclass(frozen=True)
class HVACTemperatureWidgetPlan:
    page: int
    position: int
    widget: int
    page_mode: str
    group: int
    zone: int
    decimal_places: int
    units: str
    icon_index: int
    icon_editable: bool
    restore_level: int | None
    record_before: bytes
    record: bytes
    allocations: Mapping
    expected: Mapping
    changes: Mapping
    options: Mapping

    def __post_init__(self):
        for name in ('allocations', 'expected', 'changes', 'options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def as_dict(self):
        return {'format': 'cbus-edlt-hvac-temperature-plan-v1', 'unit_type': 'KEYGL5',
                'catalog_number': '5055EDL', 'firmware': '5.5.00', 'page': self.page,
                'position': self.position, 'widget': self.widget, 'page_mode': self.page_mode,
                'application': 172, 'group': self.group, 'zone': self.zone,
                'decimal_places': self.decimal_places, 'units': self.units,
                'icon_index': self.icon_index, 'icon_editable': self.icon_editable,
                'label_index': self.record[6], 'restore_level': self.restore_level,
                'record_before_hex': self.record_before.hex(), 'record_hex': self.record.hex(),
                'allocations': {name: item.as_dict() if item else None for name, item in self.allocations.items()},
                'changes': {name: list(value) if isinstance(value, tuple) else value
                            for name, value in self.changes.items()},
                'group_metadata_verified': False, 'database_group_created': False,
                'hvac_control_sent': False, 'saved': False, 'physical_device_verified': False}


class EdltHVACTemperatureWidget:
    def __init__(self, spec, *, catalog_number='5055EDL', firmware='5.5.00'):
        self.common = EdltLighting(spec, catalog_number=catalog_number, firmware=firmware)
        self.spec, self.codec = self.common.spec, self.common.codec
        try:
            layout = self.codec.layout('UseBigIcon')
        except (ValueError, KeyError) as error:
            raise EdltError('Unsupported HVAC UseBigIcon layout') from error
        if ((layout.address, layout.array_size, layout.array_skip, layout.bit_address,
             layout.bit_size, layout.parameter.type) != (0x118, 1, 0, 4, 1, 'bit')):
            raise EdltError('Unsupported HVAC UseBigIcon layout')

    def snapshot(self, values):
        return self.common.snapshot(values)

    def crcs(self, values):
        return self.common.crcs(values)

    def plan(self, current, *, page, position, group, zone=None, decimal_places=None,
             units=None, icon_index=None, page_mode=None, label_text=None, label_index=None):
        options = dict(page=page, position=position, group=group, zone=zone, decimal_places=decimal_places,
                       units=units, icon_index=icon_index, page_mode=page_mode,
                       label_text=label_text, label_index=label_index)
        _int(group, 'HVAC communication group', 0, 255)
        if zone is not None:
            _int(zone, 'HVAC zone', 0, 4)
        if decimal_places is not None:
            _int(decimal_places, 'HVAC decimal places', 0, 2)
        if units is not None and (not isinstance(units, str) or units not in TEMPERATURE_UNITS):
            raise EdltError('units must be celsius or fahrenheit')
        if icon_index is not None:
            _int(icon_index, 'HVAC icon index')
            if icon_index not in BUILTIN_ICON_INDICES:
                raise EdltError('Icon is not offered by the original built-in selector')
        if label_text is not None and (not isinstance(label_text, str) or label_index is not None):
            raise EdltError('label_text must be a string and cannot accompany label_index')
        if label_index is not None:
            _int(label_index, 'HVAC label index')
            if label_index not in range(64) and label_index != 255:
                raise EdltError('HVAC label index must be0..63 or255')
        original = self.snapshot(current)
        self.common.static_references(original)
        for index in range(1, 22):
            kind = original[_field(index)][0]
            allowed = _STANDBY_TYPES if index < 6 else _FUNCTION_TYPES
            if kind not in allowed or (index == 5 and kind == 11):
                raise EdltError(f'Existing widget{index} type is outside the original UI placements')
        nav = original['NavWidgetType'][0]
        if nav not in (0, 1, 255):
            raise EdltError('Unsupported navigation widget mode')
        if page_mode is None:
            page_mode = 'multiple' if nav == 1 else 'single'
        if page_mode not in ('single', 'multiple'):
            raise EdltError('page_mode must be single or multiple')
        _int(page, 'Page', 0, 1 if page_mode == 'single' else 4)
        _int(position, 'Position', 1, 5 if page == 0 or page_mode == 'single' else 4)
        widget = position if page == 0 else 6 + (page - 1) * 4 + position - 1
        if page == 0 and position > 1 and original[_field(widget - 1)] == (11,):
            raise EdltError('This standby slot is covered by the previous two-slice widget; shrink it first')
        use_icon = _int(original['UseBigIcon'][0], 'Existing UseBigIcon', 0, 1)
        icon_editable = widget >= 6 and use_icon == 1
        if icon_index is not None and not icon_editable:
            raise EdltError('Icon editing requires a functional widget and existing UseBigIcon1')
        before = bytes(original[_field(widget, offset)][0] for offset in range(32))
        record = bytearray(before)
        updates = dict(original)
        restore = original[f'Widget{widget}RestoreLevel'][0] if widget >= 6 else None
        allocations = {'default_label': None, 'label': None}
        if record[0] != 13:
            # Original defaults retain byte6 until Temperature is allocated,
            # so its temporary reference participates in allocation capacity.
            record[:6] = (13, 255, 0, 0, 0, 135)
            view = self.common._place_record(updates, widget, record)
            allocation = self.common.allocate_static_text(view, 'Temperature')
            allocations['default_label'] = allocation
            updates.update(allocation.changes)
            record[6] = allocation.index
            if widget >= 6:
                restore = 0
        record[1] = group
        for offset, value in ((2, zone), (3, decimal_places),
                              (4, TEMPERATURE_UNITS[units] if units is not None else None),
                              (5, icon_index), (6, label_index)):
            if value is not None:
                record[offset] = value
        _int(record[2], 'Existing HVAC zone; supply zone to repair', 0, 4)
        _int(record[3], 'Existing HVAC precision; supply decimal_places to repair', 0, 2)
        _int(record[4], 'Existing HVAC units; supply units to repair', 0, 1)
        units = next(name for name, value in TEMPERATURE_UNITS.items() if value == record[4])
        if label_text is not None:
            if not label_text.strip():
                record[6] = 255
            else:
                view = self.common._place_record(updates, widget, record)
                allocation = self.common.allocate_static_text(view, label_text)
                allocations['label'] = allocation
                updates.update(allocation.changes)
                record[6] = allocation.index
        updates = self.common._place_record(updates, widget, record)
        if widget >= 6:
            updates[f'Widget{widget}RestoreLevel'] = (restore,)
        updates['NavWidgetType'] = (1 if page_mode == 'multiple' else 0,)
        for name, value in (('ConfigVersionMajor', 1), ('ConfigVersionMinor', 0)):
            if original[name] == (255,):
                updates[name] = (value,)
        updates['Application'] = (original['PrimaryApplication'][0], original['SecondaryApplication'][0])
        self.common.static_references(updates)
        updates.update(self.crcs(updates))
        changes = {name: value for name, value in updates.items() if value != original[name]}
        return HVACTemperatureWidgetPlan(page, position, widget, page_mode, group, record[2], record[3],
                                         units, record[5], icon_editable, restore, before, bytes(record),
                                         allocations, original, changes, options)

    def apply(self, session, plan):
        if not isinstance(plan, HVACTemperatureWidgetPlan) or not isinstance(plan.options, Mapping):
            raise EdltError('Use an HVAC plan returned by EdltHVACTemperatureWidget.plan')
        for value, name, low, high in ((plan.widget, 'Plan widget', 1, 21), (plan.page, 'Plan page', 0, 4),
                                      (plan.position, 'Plan position', 1, 5), (plan.group, 'Plan group', 0, 255),
                                      (plan.zone, 'Plan zone', 0, 4), (plan.decimal_places, 'Plan precision', 0, 2),
                                      (plan.icon_index, 'Plan icon index', 0, 255)):
            _int(value, name, low, high)
        if type(plan.icon_editable) is not bool:
            raise EdltError('Plan icon_editable must be boolean')
        if plan.widget >= 6:
            _int(plan.restore_level, 'Plan restore level')
        elif plan.restore_level is not None:
            raise EdltError('Standby widgets have no RestoreLevel parameter')
        if any(not isinstance(record, bytes) or len(record) != 32 for record in (plan.record, plan.record_before)):
            raise EdltError('Plan records must contain32 bytes')
        try:
            canonical = self.plan(plan.expected, **plan.options)
        except TypeError as error:
            raise EdltError('Invalid HVAC plan settings') from error
        if canonical != plan:
            raise EdltError('Plan differs from its validated HVAC settings')
        expected = {**plan.expected, **plan.changes}
        self.common._verify_session(session)
        if self.snapshot(session.values()) != dict(plan.expected):
            raise EdltError('PP values changed since the HVAC plan was made')
        attempted = []
        try:
            for name, value in plan.changes.items():
                attempted.append(name)
                session.set(name, _render(value))
            if self.snapshot(session.values()) != expected:
                raise EdltError('Native PP readback differs from the HVAC plan')
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
