"""Explicit SENLLA occupancy flag and bank-event transitions.

This internal component models the nil event-to-template handler used during
raw loading and the suppressed event-to-template handler inside macro refresh.
An owning lifecycle supplies resolved block references and bank state. Direct
GUI flag edits with the later event-to-template handler are outside this API.
"""
from dataclasses import dataclass, replace

from .senlla_banks import BankState
from .sensors import SensorError


def _boolean(value, label):
    if type(value) is not bool:
        raise SensorError(f'{label} requires a Boolean value')
    return value


def _block(value, label):
    if type(value) is not int or not 0 <= value < 8:
        raise SensorError(f'{label} requires a block index in 0..7')
    return value


@dataclass(frozen=True)
class OccupancyBankEvent:
    """Flags observed by one native EventFlagChanged bank refresh."""
    flags: tuple[bool, bool, bool, bool]

    def __post_init__(self):
        if type(self.flags) is not tuple or len(self.flags) != 4:
            raise SensorError('A bank event requires an immutable four-flag tuple')
        for flag in self.flags:
            _boolean(flag, 'Bank event flag')


@dataclass(frozen=True)
class OccupancyState:
    light: bool = False
    dark: bool = False
    any_movement: bool = False
    sunset: bool = False
    decision_pending: bool = True       # Native field 0x94.
    refresh_from_macro: bool = True     # Native field 0x95.

    def __post_init__(self):
        for name in ('light', 'dark', 'any_movement', 'sunset',
                     'decision_pending', 'refresh_from_macro'):
            _boolean(getattr(self, name), name)
        if sum(self.flags[:3]) > 1:
            raise SensorError('A stable occupancy state has one movement flag at most')

    @property
    def flags(self):
        return self.light, self.dark, self.any_movement, self.sunset

    def _set_flags(self, assignments):
        flags = list(self.flags)
        events = []

        def set_flag(index, value):
            if flags[index] == value:
                return
            flags[index] = value
            if value and index < 3:
                # Each unequal nested clear delivers its own event before the
                # initiating flag delivers an event, even if snapshots repeat.
                for other in ((2, 1), (0, 2), (0, 1))[index]:
                    set_flag(other, False)
            events.append(OccupancyBankEvent(tuple(flags)))

        for index, value in assignments:
            set_flag(index, value)
        return OccupancyTransition(replace(self, light=flags[0], dark=flags[1],
                                           any_movement=flags[2], sunset=flags[3]),
                                   tuple(events))

    def load_raw(self, light, dark, sunset):
        """Replay one key's raw masks with the pre-director nil handler.

        Macro-derived flags already in this state remain significant: equal
        Boolean writes have no callback. Raw loading does not change 0x94/0x95.
        """
        light = _boolean(light, 'Raw light movement')
        dark = _boolean(dark, 'Raw dark movement')
        sunset = _boolean(sunset, 'Raw sunset')
        movement = ((2, True),) if light and dark else (
            (0, light), (1, dark), (2, False))
        return self._set_flags((*movement, (3, sunset)))

    def macro_changed(self, template, *, decision_handler_installed,
                      macro_decision=None, broadcast_key=False):
        """Replay Smart refresh with explicit handler and decision facts.

        None represents a nil template. Types 0..58 are the recovered internal
        macro enum, distinct from wire nibbles. Flag changes here occur under
        native guard 0x97, so they emit bank events without rewriting a macro.
        """
        if template is not None and (type(template) is not int or not 0 <= template <= 58):
            raise SensorError('Macro template requires None or an integer in 0..58')
        installed = _boolean(decision_handler_installed, 'Decision handler installation')
        broadcast = _boolean(broadcast_key, 'Active broadcast key')
        if macro_decision is not None:
            _boolean(macro_decision, 'Macro decision')
            if not installed:
                raise SensorError('A macro decision requires an installed handler')
        if template is None:
            return OccupancyTransition(self, ())
        special = template in (29, 30, 33, 34, 24, 25)
        refresh = self.refresh_from_macro
        if not special and self.decision_pending:
            if not installed:
                refresh = False
            elif broadcast:
                refresh = True
            elif macro_decision is None:
                raise SensorError('Macro change requires the explicit native 307d decision')
            else:
                refresh = macro_decision
        state = replace(self, decision_pending=special, refresh_from_macro=refresh)
        if not special and not refresh:
            return OccupancyTransition(state, ())
        flags = (template == 29, template == 30, template == 33, template == 34)
        return state._set_flags(tuple(enumerate(flags)))

    def as_dict(self):
        return {'flags': list(self.flags), 'decision_pending': self.decision_pending,
                'refresh_from_macro': self.refresh_from_macro}


@dataclass(frozen=True)
class OccupancyTransition:
    state: OccupancyState
    bank_events: tuple[OccupancyBankEvent, ...]

    def __post_init__(self):
        if not isinstance(self.state, OccupancyState):
            raise SensorError('An occupancy transition requires an OccupancyState')
        if (type(self.bank_events) is not tuple
                or any(not isinstance(event, OccupancyBankEvent) for event in self.bank_events)):
            raise SensorError('An occupancy transition requires immutable bank events')

    def as_dict(self):
        return {'state': self.state.as_dict(),
                'bank_events': [list(event.flags) for event in self.bank_events]}


def apply_bank_events(banks, references, events, *, maintenance_active, maintenance_block):
    """Replay events on explicitly resolved banks in supplied reference order.

    The source examines this key's flags for each referenced block. It does not
    aggregate other keys. Any true flag directly clears Active, then Allowed is
    assigned from those flags and the declared maintenance-block dependency.
    None is an explicitly absent maintenance block, rather than an unknown one.
    """
    if (not isinstance(banks, (list, tuple)) or len(banks) != 8
            or any(not isinstance(bank, BankState) for bank in banks)):
        raise SensorError('Occupancy events require exactly eight existing BankState values')
    if not isinstance(references, (list, tuple)) or len(references) > 8:
        raise SensorError('Block references require an ordered sequence of at most eight indices')
    refs = tuple(_block(index, 'Block reference') for index in references)
    if len(set(refs)) != len(refs):
        raise SensorError('Block references must be unique')
    if (not isinstance(events, (list, tuple))
            or any(not isinstance(event, OccupancyBankEvent) for event in events)):
        raise SensorError('Bank events require an ordered sequence of OccupancyBankEvent values')
    active = _boolean(maintenance_active, 'Maintenance active')
    if maintenance_block is not None:
        _block(maintenance_block, 'Maintenance block')
    result = list(banks)
    for event in events:
        occupied = any(event.flags)
        for index in refs:
            bank = result[index]
            if occupied:
                bank = bank.set_active(False)
            allowed = not occupied and not (active and index == maintenance_block)
            result[index] = bank.set_allowed(allowed)
    return tuple(result)


def occupancy_parameters(states):
    """Return three detached scalar byte masks for eight occupancy states."""
    if (not isinstance(states, (list, tuple)) or len(states) != 8
            or any(not isinstance(state, OccupancyState) for state in states)):
        raise SensorError('Occupancy parameters require exactly eight OccupancyState values')
    return {'PIRLightMovement': [sum(1 << index for index, state in enumerate(states)
                                     if state.light or state.any_movement)],
            'PIRDarkMovement': [sum(1 << index for index, state in enumerate(states)
                                    if state.dark or state.any_movement)],
            'PIRDark': [sum(1 << index for index, state in enumerate(states)
                            if state.sunset)]}


__all__ = ['OccupancyBankEvent', 'OccupancyState', 'OccupancyTransition',
           'apply_bank_events', 'occupancy_parameters']
