"""Source-owned label/status type properties, without automatic UI dispatch.

The image flags describe one observed DynamicAll list.  They do not establish
image lookup, device rendering, or a framework notification schedule.
"""
from __future__ import annotations

from dataclasses import dataclass

from .edlt import EdltError


def _integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise EdltError(f'{name} must be an integer in {minimum}..{maximum}')
    return value


def _images(values):
    if (not isinstance(values, (tuple, list)) or len(values) > 4
            or any(type(value) is not bool for value in values)):
        raise EdltError('Label type needs an observed DynamicAll list of at most four image flags')
    return tuple(values)


@dataclass(frozen=True)
class LabelTypeState:
    byte_value: int
    label_index: int = 0
    status_index: int = 0
    scene_data: bool = False

    def __post_init__(self):
        _integer(self.byte_value, 'Widget label/status byte', 0, 255)
        for field in ('label_index', 'status_index'):
            _integer(getattr(self, field), field, -2**31, 2**31-1)
        if type(self.scene_data) is not bool:
            raise EdltError('SceneData type identity must be boolean')

    def display_type(self, target):
        if target == 'label':
            value = (self.byte_value >> 4) & 7
            return 10 if not self.scene_data and value in (1, 2) else value
        if target == 'status':
            value = self.byte_value & 15
            return 10 if not self.scene_data and value in (6, 7) else value
        raise EdltError('Label type target must be label or status')

    def as_dict(self):
        return {'byte_value': self.byte_value, 'label_index': self.label_index,
                'status_index': self.status_index, 'scene_data': self.scene_data,
                'label_display_type': self.display_type('label'),
                'status_display_type': self.display_type('status')}


@dataclass(frozen=True)
class LabelTypeResult:
    state: LabelTypeState
    target: str
    requested_type: int
    resolved_type: int
    variant_index_normalized: bool
    changed: bool
    notifications: tuple[str, ...]

    def as_dict(self):
        return {'format': 'cbus-edlt-label-type-control-v1',
                'state': self.state.as_dict(), 'target': self.target,
                'requested_type': self.requested_type, 'resolved_type': self.resolved_type,
                'variant_index_normalized': self.variant_index_normalized,
                'changed': self.changed, 'property_changed': list(self.notifications),
                'automatic_binding_refresh_inferred': False,
                'original_host_executed': False, 'physical_device_verified': False}


def apply_label_type(state, *, target, value, image_flags):
    """Apply the exact StatusLabelTypeData property setter and image getter.

    For non-SceneData, type10 resolves against the currently selected variant.
    The original getter first tests Count > index, then normalizes a negative
    index.  An empty list with a negative index therefore has an original
    out-of-range access; this profile refuses rather than inventing a label.
    """
    if type(state) is not LabelTypeState:
        raise EdltError('Label type requires an exact typed state')
    if target not in ('label', 'status'):
        raise EdltError('Label type target must be label or status')
    # These are actual exposed property values. Unsupported nibble values do
    # not become a made-up widget type or an unchecked byte overflow.
    allowed = (0, 1, 2, 3, 10) if target == 'label' else (0, 1, 2, 3, 4, 5, 6, 7, 10)
    if type(value) is not int or value not in allowed:
        raise EdltError('Unsupported label/status display type')
    images = _images(image_flags)
    label_index, status_index = state.label_index, state.status_index
    index = label_index if target == 'label' else status_index
    resolved, normalized = value, False
    if not state.scene_data and value == 10:
        icon = False
        if len(images) > index:
            if index < 0 or index > 3:
                index, normalized = 0, True
                if target == 'label':
                    label_index = 0
                else:
                    status_index = 0
            if index >= len(images):
                raise EdltError('Original DynamicAll index access is outside the observed list')
            icon = images[index]
        resolved = (2 if icon else 1) if target == 'label' else (7 if icon else 6)
    elif state.scene_data and value == 10:
        raise EdltError('SceneData has no generic dynamic type10 alias')

    old_type = state.display_type(target)
    proposed = ((resolved << 4) + (state.byte_value & 0x8f) if target == 'label'
                else resolved + (state.byte_value & 0xf0))
    changed = proposed != state.byte_value
    notifications = []
    if changed:
        notifications.append('LabelDisplayType' if target == 'label' else 'StatusDisplayType')
        updated = LabelTypeState(proposed, label_index, status_index, state.scene_data)
        if old_type != updated.display_type(target):
            if target == 'label':
                label_index = 0
            else:
                status_index = 0
            dynamic = not state.scene_data and updated.display_type(target) == 10
            notifications.append(('LabelValueIndex' if target == 'label' else 'StatusValueIndex')
                                 if dynamic else ('LabelValueText' if target == 'label' else 'StatusValueText'))
    final = LabelTypeState(proposed, label_index, status_index, state.scene_data)
    return LabelTypeResult(final, target, value, resolved, normalized, changed, tuple(notifications))


def update_label_types(state, *, image_flags):
    """Source UpdateLabelTypes: status setter precedes label setter."""
    status = apply_label_type(state, target='status', value=state.display_type('status'), image_flags=image_flags)
    label = apply_label_type(status.state, target='label', value=status.state.display_type('label'), image_flags=image_flags)
    return label.state, (status, label)


@dataclass(frozen=True)
class LightingLabelState:
    """LightingData's three stored bytes, distinct from its index getters."""
    byte_value: int
    raw_label_index: int
    raw_status_index: int

    def __post_init__(self):
        for key in ('byte_value', 'raw_label_index', 'raw_status_index'):
            _integer(getattr(self, key), key, 0, 255)

    def display_type(self, target):
        return LabelTypeState(self.byte_value).display_type(target)

    def index(self, target):
        if target == 'label':
            kind, index = (self.byte_value >> 4) & 7, self.raw_label_index
            return index if (kind not in (1, 2, 3) or index < (64 if kind == 3 else 4)) else 0
        if target == 'status':
            kind, index = self.byte_value & 7, self.raw_status_index
            return index if (kind not in (5, 6, 7) or index < (64 if kind == 5 else 4)) else 0
        raise EdltError('Label type target must be label or status')

    def as_dict(self):
        return {'byte_value': self.byte_value, 'raw_label_index': self.raw_label_index,
                'raw_status_index': self.raw_status_index,
                'label_index': self.index('label'), 'status_index': self.index('status'),
                'label_display_type': self.display_type('label'),
                'status_display_type': self.display_type('status')}


@dataclass(frozen=True)
class LightingLabelTypeResult:
    state: LightingLabelState
    notifications: tuple[str, ...]
    requested_type: int | None
    resolved_type: int | None
    target: str
    changed: bool

    def as_dict(self):
        return {'format': 'cbus-edlt-lighting-label-type-v1', 'state': self.state.as_dict(),
                'target': self.target, 'requested_type': self.requested_type,
                'resolved_type': self.resolved_type, 'changed': self.changed,
                'property_changed': list(self.notifications),
                'virtual_index_setter_reused': True,
                'automatic_binding_refresh_inferred': False}


def _lighting(state, *, target, image_flags, value=None, index=None):
    if type(state) is not LightingLabelState or target not in ('label', 'status'):
        raise EdltError('Lighting label control requires its exact typed bytes and label/status target')
    images = _images(image_flags)
    work = [state.byte_value, state.raw_label_index, state.raw_status_index]
    notifications, resolutions = [], []

    def current():
        return LightingLabelState(*work)

    def assign_index(selected, number):
        offset = 1 if selected == 'label' else 2
        changed = work[offset] != number
        work[offset] = number
        # LightingData's label setter only refreshes on changed storage; its
        # status setter refreshes even when the stored index is unchanged.
        if (changed or selected == 'status') and current().display_type(selected) == 10:
            assign_type(selected, 10, suppressed=True)

    def assign_type(selected, number, *, suppressed=False):
        old = current()
        resolved = number
        if number == 10:
            selected_index = old.index(selected)
            icon = len(images) > selected_index and images[selected_index]
            resolved = (2 if icon else 1) if selected == 'label' else (7 if icon else 6)
        resolutions.append(resolved)
        proposed = ((resolved << 4) + (work[0] & 0x8f) if selected == 'label'
                    else resolved + (work[0] & 0xf0))
        if proposed == work[0]:
            return
        before = old.display_type(selected)
        work[0] = proposed
        if not suppressed:
            notifications.append('LabelDisplayType' if selected == 'label' else 'StatusDisplayType')
        if before != current().display_type(selected):
            assign_index(selected, 0)
            if not suppressed:
                dynamic = current().display_type(selected) == 10
                notifications.append(('LabelValueIndex' if selected == 'label' else 'StatusValueIndex')
                    if dynamic else ('LabelValueText' if selected == 'label' else 'StatusValueText'))

    if value is not None:
        allowed = (0, 3, 10) if target == 'label' else (0, 1, 2, 3, 5, 10)
        if type(value) is not int or value not in allowed:
            raise EdltError('Lighting display type is outside the source CommonConstants choices')
        assign_type(target, value)
    else:
        assign_index(target, _integer(index, 'Lighting label/status index', 0, 255))
    final = current()
    return LightingLabelTypeResult(final, tuple(notifications), value,
                                   resolutions[0] if resolutions else None,
                                   target, final != state)


def apply_lighting_label_type(state, *, target, value, image_flags):
    """Exact LightingData virtual index callbacks during a type setter."""
    return _lighting(state, target=target, value=value, image_flags=image_flags)


def set_lighting_label_index(state, *, target, index, image_flags):
    """Exact LightingData index setter, including its suppression distinction."""
    return _lighting(state, target=target, index=index, image_flags=image_flags)
