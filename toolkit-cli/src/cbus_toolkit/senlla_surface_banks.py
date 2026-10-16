"""Fresh SENLLA surface bank-frame transitions on explicit component state.

The caller supplies eight existing banks after its independently owned load
and callback history, including the surface loader's low-threshold changes.
This component neither constructs that history nor admits a complete unit save.
Its initial widget binding preserves Active, Allowed and EnableGroupOff.
"""
from dataclasses import asdict, dataclass

from .senlla_banks import BankState, bank_parameters
from .senlla_surface import logical_bank_level_overlay
from .sensors import SensorError


def _banks(values):
    if (not isinstance(values, (list, tuple)) or len(values) != 8
            or any(not isinstance(value, BankState) for value in values)):
        raise SensorError('Surface bank frame requires exactly eight BankState values')
    if any(bank.high_lux % 10 or bank.low_lux % 10 for bank in values):
        raise SensorError('Surface bank frame requires byte-derived lux in multiples of ten')
    return tuple(values)


def _flags(values, name):
    if (not isinstance(values, (list, tuple)) or len(values) != 8
            or any(type(value) is not bool for value in values)):
        raise SensorError(f'{name} requires exactly eight Boolean values')
    return tuple(values)


@dataclass(frozen=True)
class SurfaceBankResult:
    banks: tuple[BankState, ...]
    use_low: tuple[bool, ...]
    use_high: tuple[bool, ...]

    def __post_init__(self):
        if any(type(value) is not tuple for value in (self.banks, self.use_low, self.use_high)):
            raise SensorError('Surface bank result requires immutable tuples')
        _banks(self.banks)
        _flags(self.use_low, 'use_low')
        _flags(self.use_high, 'use_high')

    def parameters(self):
        """Project detached post-frame state; later save overrides are separate."""
        result = bank_parameters(self.banks)
        result['BankSwitchGroupUsed'] = [int(low or high)
                                         for low, high in zip(self.use_low, self.use_high)]
        return result

    def save_overlay(self):
        """Return indexed surface serializer writes applied after frame parameters.

        This is the existing logical bank serializer, composed with supplied
        post-frame state. It excludes global group/behavior and all other unit
        save phases. Equal frame setters can preserve inconsistent supplied
        stored bytes; the later serializer's explicit writes still occur.
        """
        indexed = {}
        for index, (bank, low, high) in enumerate(zip(self.banks, self.use_low, self.use_high)):
            overlay = logical_bank_level_overlay(index, use_low=low, use_high=high,
                                                  high_lux=bank.high_lux if low else None)
            for name, values in overlay['indexed_parameters'].items():
                indexed.setdefault(name, {}).update(values)
        return {'format': 'cbus-senlla-surface-bank-save-overlay-v1',
                'indexed_parameters': indexed, 'logical_state_only': True,
                'raw_loader_binding_verified': False, 'complete_toolkit_save': False,
                'saved': False, 'physical_acceptance': False}

    def as_dict(self):
        return {'format': 'cbus-senlla-fresh-surface-banks-v1',
                'banks': [asdict(bank) for bank in self.banks],
                'use_low': list(self.use_low), 'use_high': list(self.use_high),
                'parameters': self.parameters(), 'save_overlay': self.save_overlay(),
                'complete_toolkit_save': False, 'saved': False,
                'physical_acceptance': False}


def fresh_surface_banks(banks, *, use_low, use_high):
    """Replay bank binding in order, then the final global normalization.

    Each inactive row clears its Low then High use flags before globally
    normalizing every row. Later inactive rows can therefore have thresholds
    changed while their supplied flags are still present. Allowed does not
    replace Active. Exact Lux equality preserves the supplied stored byte.
    """
    result = list(_banks(banks))
    low, high = list(_flags(use_low, 'use_low')), list(_flags(use_high, 'use_high'))

    def normalize():
        for index in range(8):
            if low[index]:
                result[index] = result[index].set_high_lux(2550)
            if high[index]:
                result[index] = result[index].set_low_lux(0)

    for index in range(8):
        if not result[index].switch_active:
            low[index] = False
            high[index] = False
            normalize()
    normalize()
    return SurfaceBankResult(tuple(result), tuple(low), tuple(high))


__all__ = ['SurfaceBankResult', 'fresh_surface_banks']
