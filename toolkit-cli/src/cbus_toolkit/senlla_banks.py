"""Explicit SENLLA bank transitions in the native formula3 lux domain.

The owning loader supplies an existing bank state and ordered dependency
events. This component does not infer key/occupancy/maintenance callbacks,
initial object construction or the complete unit/form/save lifecycle.
"""
from dataclasses import dataclass, replace

from .sensors import SensorError


def _integer(value, maximum, label):
    if type(value) is not int or not 0 <= value <= maximum:
        raise SensorError(f'{label} requires an integer in 0..{maximum}')
    return value


def _boolean(value, label):
    if type(value) is not bool:
        raise SensorError(f'{label} requires a Boolean value')
    return value


@dataclass(frozen=True)
class BankState:
    high_lux: int
    low_lux: int
    switch_active: bool
    switch_allowed: bool
    enable_group_off: bool
    store1: int
    store2: int

    def __post_init__(self):
        for name in ('high_lux', 'low_lux'):
            _integer(getattr(self, name), 2550, name)
        for name in ('store1', 'store2'):
            _integer(getattr(self, name), 255, name)
        for name in ('switch_active', 'switch_allowed', 'enable_group_off'):
            _boolean(getattr(self, name), name)

    def set_high_lux(self, value):
        value = _integer(value, 2550, 'High lux')
        if value == self.high_lux:
            return self
        state = replace(self, high_lux=value, store1=(value + 9) // 10)
        if state.switch_active and state.high_lux < state.low_lux:
            state = state.set_low_lux(state.high_lux)
        return state

    def set_low_lux(self, value):
        value = _integer(value, 2550, 'Low lux')
        if value == self.low_lux:
            return self
        state = replace(self, low_lux=value, store2=(value + 9) // 10)
        if state.switch_active and state.low_lux > state.high_lux:
            state = state.set_high_lux(state.low_lux)
        return state

    def set_active(self, value):
        value = _boolean(value, 'Switch Active')
        if value == self.switch_active:
            return self
        # The native setter does not consult SwitchAllowed. Its unequal true
        # callback lowers an inverted Low to High, including its Store2 write.
        state = replace(self, switch_active=value)
        if value and state.high_lux < state.low_lux:
            state = state.set_low_lux(state.high_lux)
        return state

    def set_allowed(self, value):
        value = _boolean(value, 'Switch Allowed')
        if value == self.switch_allowed:
            return self
        state = replace(self, switch_allowed=value)
        return state.set_active(False) if not value else state

    def load_active_and_enable_off(self, active, enable_off):
        """The raw bank loop assigns Active before its EnableGroupOff value."""
        _boolean(enable_off, 'Enable group off')
        return replace(self.set_active(active), enable_group_off=enable_off)

    def refresh_block(self, store1, store2, *, allowed):
        """Handle a declared block change after its external dependency scan.

        ``allowed`` is the owning unit's computed maintenance/occupancy result.
        The source refreshes Allowed before capturing both raw byte levels and
        setting High then Low. A High callback can mutate Store2, but the later
        Low assignment still uses its captured byte.
        """
        first = _integer(store1, 255, 'LightLevelStore1')
        second = _integer(store2, 255, 'LightLevelStore2')
        state = replace(self, store1=first, store2=second).set_allowed(allowed)
        return state.set_high_lux(first * 10).set_low_lux(second * 10)


def bank_parameters(banks):
    """Return detached eight-block arrays for these explicit component states."""
    if (not isinstance(banks, (list, tuple)) or len(banks) != 8
            or any(not isinstance(bank, BankState) for bank in banks)):
        raise SensorError('Bank parameters require exactly eight BankState values')
    return {
        'LightLevelStore1': [bank.store1 for bank in banks],
        'LightLevelStore2': [bank.store2 for bank in banks],
        'BlockBankSwitchActive': [int(bank.switch_active) for bank in banks],
        'BlockGroupLogic': [int(bank.enable_group_off) for bank in banks],
    }
