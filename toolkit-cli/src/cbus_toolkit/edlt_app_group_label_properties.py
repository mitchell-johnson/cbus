"""Exact retained label properties of six AppGroup widget model classes.

The property API is distinct from the panel's type choices. It records source
notification intent, never an inferred WinForms notification schedule.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .edlt import EdltError


@dataclass(frozen=True)
class AppGroupLabelProfile:
    widget_type: int
    label_offset: int
    status_offset: int
    conditional_index_setter: bool
    status_choices: tuple[int, ...]
    static_status_targets: tuple[tuple[str, int], ...] = ()
    fixed_application: int | None = None


PROFILES = MappingProxyType({
    'enable': AppGroupLabelProfile(14, 11, 12, True, (0, 3, 10, 1, 2, 5), fixed_application=203),
    'timer': AppGroupLabelProfile(5, 17, 18, False, (0, 10, 5, 4)),
    'shutter': AppGroupLabelProfile(3, 10, 11, False, (0, 3, 10, 1, 2, 5)),
    'multilevel': AppGroupLabelProfile(16, 9, 10, False, (),
        (('status-low', 11), ('status-medium', 12), ('status-high', 13))),
    'fan': AppGroupLabelProfile(4, 9, 10, False, (),
        (('status-low', 11), ('status-medium', 12), ('status-high', 13))),
    'room-courtesy': AppGroupLabelProfile(15, 8, 9, False, (0, 10, 5)),
})


def profile(family):
    if type(family) is not str or family not in PROFILES:
        raise EdltError('AppGroup label family must be enable, timer, shutter, multilevel, fan or room-courtesy')
    return PROFILES[family]


@dataclass(frozen=True)
class AppGroupLabelState:
    family: str
    record: bytes

    def __post_init__(self):
        selected = profile(self.family)
        if type(self.record) is not bytes or len(self.record) != 32 or self.record[0] != selected.widget_type:
            raise EdltError('AppGroup labels require the exact family and its complete 32-byte record')

    def offset(self, target):
        selected = profile(self.family)
        offsets = {'label': selected.label_offset, 'status': selected.status_offset,
                   **dict(selected.static_status_targets)}
        if target not in offsets:
            raise EdltError('Label target is not present in this AppGroup model')
        return offsets[target]

    def display_type(self, target):
        if target == 'label':
            raw = (self.record[1] >> 4) & 7
            return 10 if raw in (1, 2) else raw
        if target == 'status':
            raw = self.record[1] & 15
            return 10 if raw in (6, 7) else raw
        self.offset(target)
        return 5

    def index(self, target):
        raw = self.record[self.offset(target)]
        if target == 'label':
            kind = (self.record[1] >> 4) & 7
            limit = 4 if kind in (1, 2) else 64 if kind == 3 else None
        elif target == 'status':
            # Every sibling getter tests the low THREE bits here. The display
            # type property's low-nibble interpretation is a separate fact.
            kind = self.record[1] & 7
            limit = 4 if kind in (6, 7) else 64 if kind == 5 else None
        else:
            limit = None
        return 0 if limit is not None and raw >= limit else raw

    def as_dict(self):
        selected = profile(self.family)
        result = {'family': self.family, 'record_hex': self.record.hex(),
                  'byte_value': self.record[1],
                  'raw_label_index': self.record[selected.label_offset],
                  'raw_status_index': self.record[selected.status_offset],
                  'label_index': self.index('label'), 'status_index': self.index('status'),
                  'label_display_type': self.display_type('label'),
                  'status_display_type': self.display_type('status')}
        result['static_status_indices'] = {
            target: self.record[offset] for target, offset in selected.static_status_targets}
        return result


@dataclass(frozen=True)
class AppGroupLabelPropertyResult:
    state: AppGroupLabelState
    target: str
    requested_type: int | None
    resolved_type: int | None
    changed: bool
    notifications: tuple[str, ...]

    def as_dict(self):
        return {'format': 'cbus-edlt-app-group-label-property-v1',
                'state': self.state.as_dict(), 'target': self.target,
                'requested_type': self.requested_type, 'resolved_type': self.resolved_type,
                'changed': self.changed, 'property_changed': list(self.notifications),
                'direct_model_property_profile': True,
                'automatic_framework_dispatch_inferred': False}


def _property(state, *, target, image_flags, value=None, index=None):
    if type(state) is not AppGroupLabelState:
        raise EdltError('AppGroup label properties need their exact typed record')
    selected = profile(state.family)
    state.offset(target)
    if (not isinstance(image_flags, (tuple, list)) or len(image_flags) > 4
            or any(type(flag) is not bool for flag in image_flags)):
        raise EdltError('AppGroup labels need at most four observed image flags')
    images = tuple(image_flags)
    if target not in ('label', 'status') and value is not None:
        raise EdltError('Named MultiLevel status text has no type selector')
    work = bytearray(state.record)
    notifications, resolutions = [], []

    def current():
        return AppGroupLabelState(state.family, bytes(work))

    def assign_index(which, number):
        position = current().offset(which)
        changed = work[position] != number
        work[position] = number
        if which in ('label', 'status') and (changed or not selected.conditional_index_setter):
            if current().display_type(which) == 10:
                assign_type(which, 10, suppressed=True)

    def assign_type(which, number, *, suppressed=False):
        previous = current()
        resolved = number
        if number == 10:
            number_index = previous.index(which)
            icon = len(images) > number_index and images[number_index]
            resolved = (2 if icon else 1) if which == 'label' else (7 if icon else 6)
        resolutions.append(resolved)
        proposed = ((resolved << 4) + (work[1] & 0x8f) if which == 'label'
                    else resolved + (work[1] & 0xf0))
        if proposed == work[1]:
            return
        before = previous.display_type(which)
        work[1] = proposed
        if not suppressed:
            notifications.append('LabelDisplayType' if which == 'label' else 'StatusDisplayType')
        if before != current().display_type(which):
            assign_index(which, 0)
            if not suppressed:
                dynamic = current().display_type(which) == 10
                notifications.append(('LabelValueIndex' if which == 'label' else 'StatusValueIndex')
                    if dynamic else ('LabelValueText' if which == 'label' else 'StatusValueText'))

    if value is not None:
        # This is the source model property profile, not a claim that every
        # sibling panel offers all these type values in its UI.
        allowed = (0, 1, 2, 3, 10) if target == 'label' else (0, 1, 2, 3, 4, 5, 6, 7, 10)
        if type(value) is not int or value not in allowed:
            raise EdltError('Unsupported direct AppGroup label/status property type')
        assign_type(target, value)
    else:
        if type(index) is not int or not 0 <= index <= 255:
            raise EdltError('AppGroup label/status index must be a byte')
        assign_index(target, index)
    final = current()
    return AppGroupLabelPropertyResult(final, target, value,
        resolutions[0] if resolutions else None, final != state, tuple(notifications))


def apply_app_group_label_type(state, *, target, value, image_flags):
    return _property(state, target=target, value=value, image_flags=image_flags)


def set_app_group_label_index(state, *, target, index, image_flags):
    return _property(state, target=target, index=index, image_flags=image_flags)


def update_app_group_label_types(state, *, image_flags):
    """Source UpdateLabelTypes explicitly updates status before label."""
    status = apply_app_group_label_type(state, target='status',
        value=state.display_type('status'), image_flags=image_flags)
    label = apply_app_group_label_type(status.state, target='label',
        value=status.state.display_type('label'), image_flags=image_flags)
    return label.state, (status, label)
