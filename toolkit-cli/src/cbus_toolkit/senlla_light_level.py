"""Loaded SENLLA light-level scalars and explicit fresh-form initialization.

Margin percentage is captured from the original target before the fresh form
caps its loaded target. Display clamping does not replace the source margin.
This component has no bank/key/group creation or whole-unit save authority.
"""
from dataclasses import dataclass, replace

from .senlla_surface import SurfaceView
from .sensors import SensorError, saved_margin


def _integer(value, maximum, name):
    if type(value) is not int or not 0 <= value <= maximum:
        raise SensorError(f'{name} requires an integer in 0..{maximum}')
    return value


@dataclass(frozen=True)
class SurfaceLightState:
    target_group: int
    margin_group: int
    target_byte: int
    margin_percent: int
    target_power_state: int
    margin_power_state: int
    target_preset: int
    margin_preset: int

    def __post_init__(self):
        for name in ('target_group', 'margin_group', 'target_byte',
                     'target_preset', 'margin_preset'):
            _integer(getattr(self, name), 255, name)
        _integer(self.margin_percent, 25500, 'Margin percent')
        for name in ('target_power_state', 'margin_power_state'):
            _integer(getattr(self, name), 1, name)
        if self.target_group != 255 and self.margin_group != 255:
            raise SensorError('Loaded target-group usage requires an unused margin group')

    @classmethod
    def from_surface_view(cls, view):
        """Capture the proven surface raw-load result before form callbacks."""
        if not isinstance(view, SurfaceView):
            raise SensorError('Light-level loading requires a SENLLA SurfaceView')
        try:
            loaded, raw = view.loaded, view.expected
            return cls(loaded['target_group'], loaded['margin_group'],
                       loaded['target_byte'], loaded['margin_percent'],
                       loaded['power_up']['target']['state'],
                       loaded['power_up']['margin']['state'],
                       raw['PowerUpTargetGroupLevel'][0], raw['PowerUpMarginGroupLevel'][0])
        except (KeyError, IndexError, TypeError):
            raise SensorError('Incomplete SENLLA surface light-level state') from None

    def fresh_initialize(self):
        """Replay the unconditional SetTargetLuxEditText upper-cap setter.

        The bound margin renderer clamps only its display and restores its
        source cache. The captured percentage therefore remains unchanged.
        """
        return replace(self, target_byte=200) if self.target_byte > 200 else self

    def as_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__} | {
            'margin_display_position': max(1, min(self.margin_percent, 100))}

    def parameters(self):
        """Project only the eight owned surface light-level scalar fields."""
        target_used, margin_used = self.target_group != 255, self.margin_group != 255
        target = 200 if target_used else self.target_byte
        margin = (2 * self.margin_percent if target_used else
                  target if margin_used else saved_margin(target, self.margin_percent))
        _integer(margin, 255, 'Saved PECMarginLux')
        target_store = int(target_used and self.target_power_state == 1)
        return {
            'LightLevelTargetGroup': [self.target_group],
            'LightLevelMarginGroup': [self.target_group if target_used else self.margin_group],
            'PECTargetLux': [target], 'PECMarginLux': [margin],
            'LightLevelTargetGroupLevelStore': [target_store],
            'LightLevelMarginGroupLevelStore': [target_store if target_used else
                                               int(margin_used and self.margin_power_state == 1)],
            'PowerUpTargetGroupLevel': [self.target_preset],
            'PowerUpMarginGroupLevel': [self.target_preset if target_used else self.margin_preset],
        }


__all__ = ['SurfaceLightState']
