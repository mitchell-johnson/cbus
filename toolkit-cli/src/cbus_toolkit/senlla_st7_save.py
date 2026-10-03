"""Inherited scalar save components from an explicit SENLLA load state.

Power state is captured before fresh controls can change enable-group logic.
The owning lifecycle supplies current logic to serialization. This component
does not construct the unit, initialize forms or admit a complete PP save.
"""
from dataclasses import dataclass

from .pir_sensors import power_up_state
from .sensors import SensorError


def _integer(value, maximum, name):
    if type(value) is not int or not 0 <= value <= maximum:
        raise SensorError(f'{name} requires an integer in 0..{maximum}')
    return value


@dataclass(frozen=True)
class ST7SaveState:
    light_levels: tuple
    light_power_state: int
    occupancy_power_state: int
    broadcast_active: bool

    def __post_init__(self):
        if not isinstance(self.light_levels, (list, tuple)) or len(self.light_levels) != 10:
            raise SensorError('LightLevel requires exactly ten unsigned bytes')
        object.__setattr__(self, 'light_levels', tuple(
            _integer(value, 255, 'LightLevel') for value in self.light_levels))
        _integer(self.light_power_state, 2, 'Light-level power state')
        _integer(self.occupancy_power_state, 2, 'Occupancy power state')
        if type(self.broadcast_active) is not bool:
            raise SensorError('Broadcast active requires a Boolean value')

    @classmethod
    def load(cls, light_levels, *, pec_level_store, pir_level_store,
             pec_enable_off, pir_enable_off, broadcast_mode):
        for name, value in (('PECLevelStore', pec_level_store), ('PIRLevelStore', pir_level_store),
                            ('PECEnablerGroupLogic', pec_enable_off), ('PIREnablerGroupLogic', pir_enable_off)):
            _integer(value, 1, name)
        _integer(broadcast_mode, 7, 'BroadcastActive')
        # Validate the array before reading either indexed power slot.
        initial = cls(light_levels, 0, 0, False)
        return cls(initial.light_levels,
                   power_up_state(initial.light_levels[9], pec_enable_off, pec_level_store),
                   power_up_state(initial.light_levels[8], pir_enable_off, pir_level_store),
                   1 <= broadcast_mode <= 6)

    def parameters(self, *, pec_enable_off, pir_enable_off, current_light_levels=None):
        """Overlay captured power states on the current serializer array.

        The owning save supplies CoreKey's rebuilt LightLevel array. Resume
        state2 performs no indexed write, so it retains that current value.
        Omitting the array selects the isolated component's original baseline.
        """
        _integer(pec_enable_off, 1, 'Current PECEnablerGroupLogic')
        _integer(pir_enable_off, 1, 'Current PIREnablerGroupLogic')
        if current_light_levels is None:
            levels = list(self.light_levels)
        else:
            if (not isinstance(current_light_levels, (list, tuple))
                    or not 10 <= len(current_light_levels) <= 263):
                raise SensorError('Current LightLevel requires 10..263 unsigned bytes from CoreKey save')
            levels = [_integer(value, 255, 'Current LightLevel') for value in current_light_levels]
        for index, state, off in ((9, self.light_power_state, pec_enable_off),
                                  (8, self.occupancy_power_state, pir_enable_off)):
            if state != 2:
                levels[index] = 255 if bool(state) != bool(off) else 0
        return {'LightLevel': levels, 'PECLevelStore': [int(self.light_power_state == 2)],
                'PIRLevelStore': [int(self.occupancy_power_state == 2)],
                'BroadcastActive': [4 if self.broadcast_active else 0],
                'PotentiometerBBankSwitchEnable': [0]}
