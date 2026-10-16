"""SENLLA bank dependencies in the owning loader's callback order.

Observed block changes, bank-owned lux writes and per-key occupancy events
have distinct effects. Application/Scene/template owners supply references
and events at their actual causal position. This internal dependency engine
does not implement the complete unit save transaction.
"""
from dataclasses import dataclass, replace

from .senlla_banks import BankState, bank_parameters
from .senlla_key_references import SENLLAKeyReferences
from .senlla_occupancy import OccupancyState, OccupancyTransition, apply_bank_events
from .sensors import SensorError


def _index(value, label='Block index'):
    if type(value) is not int or not 0 <= value < 8:
        raise SensorError(f'{label} requires an integer in 0..7')
    return value


def _byte(value, label):
    if type(value) is not int or not 0 <= value <= 255:
        raise SensorError(f'{label} requires an integer in 0..255')
    return value


def _eight(values, value_type, label):
    if (not isinstance(values, (list, tuple)) or len(values) != 8
            or any(type(value) is not value_type for value in values)):
        raise SensorError(f'{label} requires exactly eight {value_type.__name__} values')
    return tuple(values)


@dataclass(frozen=True)
class SENLLABankGraph:
    banks: tuple[BankState, ...]
    occupancy: tuple[OccupancyState, ...]
    references: SENLLAKeyReferences
    maintenance_active: bool = False
    maintenance_block: int | None = None

    def __post_init__(self):
        object.__setattr__(self, 'banks', _eight(self.banks, BankState, 'Banks'))
        object.__setattr__(self, 'occupancy', _eight(self.occupancy, OccupancyState, 'Occupancy'))
        if not isinstance(self.references, SENLLAKeyReferences):
            raise SensorError('Bank graph requires resolved SENLLA key references')
        if type(self.maintenance_active) is not bool:
            raise SensorError('Maintenance active requires a Boolean')
        if self.maintenance_block is not None:
            _index(self.maintenance_block, 'Maintenance block')

    @classmethod
    def fresh(cls):
        """Construct after eight fresh banks bind to their zero-valued blocks."""
        return cls((BankState(0, 0, False, True, False, 0, 0),) * 8,
                   (OccupancyState(),) * 8, SENLLAKeyReferences(((),) * 8))

    def with_references(self, references):
        """Bind owner-resolved references without an aggregate Allowed refresh.

        The broadcast/template owner replays any unequal occupancy callbacks.
        Equal occupancy flags deliver no event merely because references move.
        """
        return replace(self, references=references)

    def with_maintenance(self, *, active, block):
        """Assign raw attributes whose dedicated callbacks are nil.

        Later UI handlers may explicitly request aggregate refreshes. These
        two attribute assignments do not themselves refresh banks.
        """
        return replace(self, maintenance_active=active, maintenance_block=block)

    def aggregate_allowed(self, block):
        block = _index(block)
        if self.maintenance_active and block == self.maintenance_block:
            return False
        return not any(block in row and any(state.flags)
                       for row, state in zip(self.references.ordered_references, self.occupancy))

    def _bank(self, index, state):
        values = list(self.banks)
        values[index] = state
        return replace(self, banks=values)

    def refresh_allowed(self, block):
        """Replay an explicit aggregate-only UI refresh, without lux loading."""
        block = _index(block)
        return self._bank(block, self.banks[block].set_allowed(self.aggregate_allowed(block)))

    def block_changed(self, block):
        """Observe an external block change: aggregate Allowed, then High, Low.

        Both current stored bytes are captured after Allowed. Bank-owned byte
        feedback is suppressed, including EndUpdate re-evaluation of the same
        block object; those writes use the lux methods instead.
        """
        block = _index(block)
        bank = self.banks[block]
        return self._bank(block, bank.refresh_block(bank.store1, bank.store2,
                                                   allowed=self.aggregate_allowed(block)))

    def write_stored_level(self, block, store, value):
        """Apply an external stored-level setter and its unequal notification."""
        block = _index(block)
        if type(store) is not int or store not in (1, 2):
            raise SensorError('Stored-level selector requires integer 1 or 2')
        value = _byte(value, 'Stored level')
        bank = self.banks[block]
        name = f'store{store}'
        if getattr(bank, name) == value:
            return self
        return self._bank(block, replace(bank, **{name: value})).block_changed(block)

    def load_stored_levels(self, first, second):
        """Replay CoreKey's ascending blocks, Store1 before Store2 per block."""
        first = _eight(first, int, 'LightLevelStore1')
        second = _eight(second, int, 'LightLevelStore2')
        for value in (*first, *second):
            _byte(value, 'Stored level')
        graph = self
        for block in range(8):
            graph = graph.write_stored_level(block, 1, first[block])
            graph = graph.write_stored_level(block, 2, second[block])
        return graph

    def set_high_lux(self, block, value):
        block = _index(block)
        return self._bank(block, self.banks[block].set_high_lux(value))

    def set_low_lux(self, block, value):
        block = _index(block)
        return self._bank(block, self.banks[block].set_low_lux(value))

    def load_active_and_enable_off(self, active, enable_off):
        """Replay ST7's later ascending bank loop, Active before Off per bank."""
        active = _eight(active, bool, 'Bank Active')
        enable_off = _eight(enable_off, bool, 'Bank EnableGroupOff')
        graph = self
        for block in range(8):
            graph = graph._bank(block, graph.banks[block].load_active_and_enable_off(
                active[block], enable_off[block]))
        return graph

    def apply_occupancy_transition(self, key, transition):
        """Replay one key's ordered direct events against its current references."""
        key = _index(key, 'Key index')
        if not isinstance(transition, OccupancyTransition):
            raise SensorError('Bank graph requires an OccupancyTransition')
        banks = apply_bank_events(
            self.banks, self.references.ordered_references[key], transition.bank_events,
            maintenance_active=self.maintenance_active, maintenance_block=self.maintenance_block)
        states = list(self.occupancy)
        states[key] = transition.state
        return replace(self, banks=banks, occupancy=states)

    def macro_changed(self, key, template, **decision_context):
        key = _index(key, 'Key index')
        transition = self.occupancy[key].macro_changed(template, **decision_context)
        return self.apply_occupancy_transition(key, transition)

    def refresh_event_flags(self, key, template, *, join_active,
                            event_template_handler_installed):
        """Replay the direct refresh after owner-controlled broadcast callbacks."""
        key = _index(key, 'Key index')
        transition = self.occupancy[key].refresh_event_flags(
            template, key_index=key, join_active=join_active,
            event_template_handler_installed=event_template_handler_installed)
        return self.apply_occupancy_transition(key, transition)

    def load_raw_occupancy(self, light, dark, sunset):
        """Load raw scalar masks after bank/maintenance/broadcast loading."""
        light = _byte(light, 'PIRLightMovement')
        dark = _byte(dark, 'PIRDarkMovement')
        sunset = _byte(sunset, 'PIRDark')
        graph = self
        for key in range(8):
            bit = 1 << key
            transition = graph.occupancy[key].load_raw(
                bool(light & bit), bool(dark & bit), bool(sunset & bit))
            graph = graph.apply_occupancy_transition(key, transition)
        return graph

    def parameters(self):
        return bank_parameters(self.banks)

    def as_dict(self):
        return {
            'banks': [dict(high_lux=bank.high_lux, low_lux=bank.low_lux,
                           switch_active=bank.switch_active, switch_allowed=bank.switch_allowed,
                           enable_group_off=bank.enable_group_off,
                           store1=bank.store1, store2=bank.store2) for bank in self.banks],
            'occupancy': [state.as_dict() for state in self.occupancy],
            'references': self.references.as_dict(),
            'maintenance_active': self.maintenance_active,
            'maintenance_block': self.maintenance_block,
        }
