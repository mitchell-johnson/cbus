"""Internal SENLLA eight-key reference ordering, without owning callbacks.

Raw allocations load references in ascending block order. Native additions
append and removals extract; a collision adds its destination before removing
its source. Masks serialize membership and cannot recover later list order.
Mutation results record direct refresh requests for the owning lifecycle to
replay, rather than executing macro, bank, application or Scene callbacks.
"""
from dataclasses import dataclass

from .sensors import SensorError


def _index(value, label):
    if type(value) is not int or not 0 <= value <= 7:
        raise SensorError(f'{label} requires an integer in 0..7')
    return value


def _masks(values):
    if (not isinstance(values, (list, tuple)) or len(values) != 8
            or any(type(value) is not int or not 0 <= value <= 255 for value in values)):
        raise SensorError('Block allocation requires exactly eight integers in 0..255')
    return tuple(values)


def _updating(value):
    if type(value) is not bool:
        raise SensorError('Key updating state requires a Boolean')
    return value


def _update_states(values):
    if values is None:
        return (False,) * 8
    if not isinstance(values, (list, tuple)) or len(values) != 8:
        raise SensorError('Key updating states require exactly eight Booleans')
    return tuple(_updating(value) for value in values)


@dataclass(frozen=True)
class ReferenceMutation:
    operation: str
    key: int
    block: int
    before: tuple
    after: tuple
    changed: bool
    direct_refreshes: tuple

    def as_dict(self):
        return {
            'operation': self.operation, 'key': self.key, 'block': self.block,
            'before': list(self.before), 'after': list(self.after),
            'changed': self.changed, 'reference_list_changed': self.changed,
            'direct_refreshes': [
                {'method': method, 'target_kind': kind, 'target_index': index}
                for method, kind, index in self.direct_refreshes
            ],
        }


@dataclass(frozen=True)
class IndicatorRemapRequest:
    key: int
    from_block_number: int
    to_block_number: int
    after_event_count: int

    def as_dict(self):
        return {
            'key': self.key, 'from_block_number': self.from_block_number,
            'to_block_number': self.to_block_number,
            'after_event_count': self.after_event_count,
            'condition': 'current indicator block number equals from_block_number',
        }


@dataclass(frozen=True)
class ReferenceResult:
    state: 'SENLLAKeyReferences'
    events: tuple
    indicator_requests: tuple = ()

    def as_dict(self):
        return {
            'state': self.state.as_dict(),
            'events': [event.as_dict() for event in self.events],
            'indicator_requests': [request.as_dict() for request in self.indicator_requests],
        }


@dataclass(frozen=True)
class SENLLAKeyReferences:
    ordered_references: tuple

    def __post_init__(self):
        rows = self.ordered_references
        if not isinstance(rows, (list, tuple)) or len(rows) != 8:
            raise SensorError('Key references require exactly eight ordered rows')
        normalized = []
        for row in rows:
            if not isinstance(row, (list, tuple)):
                raise SensorError('Each key reference row requires a list or tuple')
            values = tuple(_index(block, 'Block reference') for block in row)
            if len(set(values)) != len(values):
                raise SensorError('A key cannot contain duplicate block references')
            normalized.append(values)
        object.__setattr__(self, 'ordered_references', tuple(normalized))

    @classmethod
    def from_masks(cls, masks):
        """Establish fresh raw-reference order from eight allocation bytes."""
        values = _masks(masks)
        return cls(tuple(tuple(block for block in range(8) if mask & (1 << block))
                         for mask in values))

    @classmethod
    def from_ordered(cls, rows, *, masks=None):
        """Validate an owning model's retained references; do not reconstruct them."""
        state = cls(rows)
        if masks is not None and tuple(state.masks()) != _masks(masks):
            raise SensorError('Ordered references do not match block allocation masks')
        return state

    def masks(self):
        return [sum(1 << block for block in row) for row in self.ordered_references]

    def parameters(self):
        return {'BlockAllocation': self.masks()}

    def primary_block(self, key):
        row = self.ordered_references[_index(key, 'Key index')]
        return row[0] if row else None

    def as_dict(self):
        return {
            'ordered_references': [list(row) for row in self.ordered_references],
            'masks': self.masks(),
            'primary_blocks': [self.primary_block(key) for key in range(8)],
        }

    def _mutate(self, operation, key, block, key_updating):
        key = _index(key, 'Key index')
        block = _index(block, 'Block index')
        key_updating = _updating(key_updating)
        before = self.ordered_references[key]
        if operation == 'add':
            after = before if block in before else (*before, block)
            refreshes = (('RefreshKeysSecondaryFromBlockSecondary', 'block', block),
                         ('RefreshPrimaryGroupFromBlockGroups', 'key', key))
        else:
            after = tuple(item for item in before if item != block)
            refreshes = (('RefreshPrimaryGroupFromBlockGroups', 'key', key),
                         ('RefreshKeysSecondaryFromBlockSecondary', 'block', block))
        changed = before != after
        rows = list(self.ordered_references)
        rows[key] = after
        state = SENLLAKeyReferences(rows) if changed else self
        event = ReferenceMutation(operation, key, block, before, after, changed,
                                  refreshes if changed and not key_updating else ())
        return ReferenceResult(state, (event,))

    def add_block(self, key, block, *, key_updating=False):
        return self._mutate('add', key, block, key_updating)

    def remove_block(self, key, block, *, key_updating=False):
        return self._mutate('remove', key, block, key_updating)

    def remove_all_blocks(self, key, *, key_updating=False):
        """Native RemoveAllBlocks scans the owning block collection ascending."""
        key = _index(key, 'Key index')
        key_updating = _updating(key_updating)
        state, events = self, []
        for block in range(8):
            if block in state.ordered_references[key]:
                result = state.remove_block(key, block, key_updating=key_updating)
                state = result.state
                events.extend(result.events)
        return ReferenceResult(state, tuple(events))

    def transfer_block(self, source, destination, *, key_updating=None):
        """Return the association portion of an already-established collision.

        The owner establishes the Boolean change, group-object collision and
        destination first. It must replay each event's nested callbacks against
        that event's graph position; this component does not compose them.
        """
        source = _index(source, 'Source block index')
        destination = _index(destination, 'Destination block index')
        if source == destination:
            raise SensorError('A native collision requires distinct source and destination blocks')
        updating = _update_states(key_updating)
        state, events = self, []
        for key in range(8):
            if source not in state.ordered_references[key]:
                continue
            for operation, block in (('add', destination), ('remove', source)):
                result = state._mutate(operation, key, block, updating[key])
                state = result.state
                events.extend(result.events)
        return ReferenceResult(state, tuple(events))

    def swap_mappings(self, first, second, *, key_updating=None):
        """Project only mapping swaps; block data and indicators remain owned.

        Indicator requests describe the source's conditional remap after each
        exclusive key's remove/add pair. They do not assume an indicator value.
        """
        first = _index(first, 'First block index')
        second = _index(second, 'Second block index')
        updating = _update_states(key_updating)
        state, events, indicators = self, [], []
        for key in range(8):
            row = state.ordered_references[key]
            if (first in row) == (second in row):
                continue
            source, destination = (first, second) if first in row else (second, first)
            for operation, block in (('remove', source), ('add', destination)):
                result = state._mutate(operation, key, block, updating[key])
                state = result.state
                events.extend(result.events)
            indicators.append(IndicatorRemapRequest(key, source + 1, destination + 1, len(events)))
        return ReferenceResult(state, tuple(events), tuple(indicators))
