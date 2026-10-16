"""Internal SENLLA indexed block loading and CoreKey level serialization.

Requests describe native getter/setter boundaries. The owning lifecycle must
resolve actual application/group/microfunction objects and execute callbacks
before continuing. This component does not construct a unit or apply a save.
"""
from dataclasses import dataclass

from .senlla_inputs import SENLLAInputSnapshot, SCHEMA, _value
from .sensors import SensorError


TIMER_EXPIRY_TYPES = (0, 15, 4, 9, 12, 6, 10)


def _integer(value, maximum, name):
    if type(value) is not int or not 0 <= value <= maximum:
        raise SensorError(f'{name} requires an integer in 0..{maximum}')
    return value


def _levels(values):
    if not isinstance(values, (tuple, list)) or len(values) != 8:
        raise SensorError('Current block levels require exactly eight unsigned bytes')
    return tuple(_integer(value, 255, 'Current block level') for value in values)


def current_light_levels(values):
    """Admit the bounded CURRENT native cache, before physical layout checks.

    The guarded raw profile has ten entries. Source indexed rebuilding can
    grow its cache to 255 prefix entries plus eight blocks; callbacks may retain
    that cache for later Count/indexed reads. Final programming is separate.
    """
    if not isinstance(values, (tuple, list)) or not 10 <= len(values) <= 263:
        raise SensorError('Current LightLevel cache requires 10..263 unsigned bytes')
    return [_integer(value, 255, 'Current LightLevel byte') for value in values]


def loaded_expiry_type(raw):
    """Return the post-membership type; raw0 is a real registered type0."""
    raw = _integer(raw, 15, 'Raw timer expiry')
    return raw if raw in TIMER_EXPIRY_TYPES else 15


def rebuild_light_levels(light_index, loaded_count, current_levels):
    """Rebuild the native array, retaining source growth beyond ten bytes.

    Canonical guarded SENLLA input captures ten raw entries. The native saver
    writes an unused255 prefix, all eight CURRENT block levels, and enough
    unused255 suffix entries to reach the captured count. A negative suffix
    repeat is empty. This replaces the original raw prefix and tail values.
    """
    index = _integer(light_index, 255, 'Current LightIndex')
    if type(loaded_count) is not int or not 10 <= loaded_count <= 263:
        raise SensorError('Current SENLLA load count requires 10..263 entries')
    levels = _levels(current_levels)
    return (255,) * index + levels + (255,) * max(loaded_count - index - 8, 0)


@dataclass(frozen=True)
class BlockLoadRequest:
    """An owner-executed boundary, rather than a detached model mutation."""
    operation: str
    field: str
    block: int | None
    value: int | bool | tuple
    source: str

    def as_dict(self):
        return {'operation': self.operation, 'field': self.field,
                'block': self.block,
                'value': list(self.value) if isinstance(self.value, tuple) else self.value,
                'source': self.source}


@dataclass(frozen=True)
class BlockLoadPlan:
    """Raw immutable binding and ordered requests for the pre-key owner.

    A set_microfunction request resolves its byte to the canonical factory
    object, including NONNIL0. check_expiry reads the CURRENT object after the
    preceding setter/publication and sets canonical15 only when its type is
    absent from TIMER_EXPIRY_TYPES. get_group reads CURRENT block Secondary:
    true selects actual unit Application2 (nil gives nil Group), false selects
    CURRENT ApplicationForBlock. It then performs create=true lookup and the
    native group setter. Neither request invents an object or skips callbacks.
    """
    snapshot: SENLLAInputSnapshot

    def __post_init__(self):
        if not isinstance(self.snapshot, SENLLAInputSnapshot):
            raise SensorError('Block loading requires a guarded complete SENLLA snapshot')
        # Rebind and revalidate all raw values, keeping dataclass replacement
        # and the caller's independent snapshot equally detached.
        object.__setattr__(self, 'snapshot', SENLLAInputSnapshot(
            self.snapshot.identity, self.snapshot.expected))

    @property
    def light_index(self):
        return self.snapshot.expected['LightIndex'][0]

    @property
    def loaded_count(self):
        return len(self.snapshot.expected['LightLevel'])

    def level_for_block(self, block, *, light_index=None):
        """Read the raw array at the owner's CURRENT index plus block."""
        _integer(block, 7, 'Block index')
        current = self.light_index if light_index is None else light_index
        index = _integer(current, 255, 'Current LightIndex') + block
        levels = self.snapshot.expected['LightLevel']
        return levels[index] if index < len(levels) else 0

    def secondary_requests(self):
        """All eight bit setters precede any raw scalar/group block row."""
        mask = self.snapshot.expected['SecondApplicationBlocks'][0]
        return tuple(BlockLoadRequest('set', 'secondary', block,
                                      bool(mask & (1 << block)), '0xced02e')
                     for block in range(8))

    def value_requests(self):
        """GetBlockValues boundaries, including its live expiry/group reads.

        The level value records the guarded index projection. Its native
        boundary reads CURRENT LightIndex+i; a composed owner must preserve
        that getter position if another admitted callback changes LightIndex.
        Constructor TimerMin0, TimerCached0 and nil expiry override are not
        synthesized as PP load setters here.
        """
        raw = self.snapshot.expected
        requests = [BlockLoadRequest('set', 'light_index', None,
                                     self.light_index, '0xcc816c'),
                    BlockLoadRequest('capture', 'loaded_light_count', None,
                                     self.loaded_count, '0xcc81aa')]
        for block in range(8):
            value = self.level_for_block(block)
            timer = (raw['TimerHighByte'][block] << 8) | raw['TimerLowByte'][block]
            requests.extend((
                BlockLoadRequest('get_indexed_level_and_set', 'light_level', block,
                                 value, '0xcc823a'),
                BlockLoadRequest('set', 'store1', block,
                                 raw['LightLevelStore1'][block], '0xcc828c'),
                BlockLoadRequest('set', 'store2', block,
                                 raw['LightLevelStore2'][block], '0xcc82c7'),
                BlockLoadRequest('set', 'timer', block, timer, '0xcc82df'),
                BlockLoadRequest('set_microfunction', 'expiry', block,
                                 raw['TimerExpiryCommand'][block], '0xcc82f7'),
                BlockLoadRequest('check_expiry', 'expiry', block,
                                 TIMER_EXPIRY_TYPES, '0xcc8357'),
                BlockLoadRequest('get_group', 'group', block,
                                 raw['GroupAddress'][block], '0xcc83ba'),
            ))
        return tuple(requests)

    def requests(self):
        return self.secondary_requests() + self.value_requests()

    def current_requests(self, parameter_read):
        """Yield at each source setter, reading current PP only when reached.

        The secondary mask is captured once before its eight setters. Array
        store/timer/group getters are repeated per row after earlier callbacks.
        The indexed level itself is read by the executor using CURRENT index.
        Historical detached requests remain available through ``requests``.
        """
        if not callable(parameter_read):
            raise SensorError('Current block requests require a synchronous PP reader')
        def read(name, source):
            value = parameter_read(name, source)
            if name == 'LightLevel':
                return current_light_levels(value)
            if SCHEMA[name][0] != 'sixbit' and (not isinstance(value, (list, tuple))
                    or any(type(item) is not int for item in value)):
                raise SensorError('Current block PP requires exact unsigned integers')
            return _value(name, value)

        mask = read('SecondApplicationBlocks', '0xcecfb3')[0]
        for block in range(8):
            yield BlockLoadRequest('set', 'secondary', block,
                                   bool(mask & (1 << block)), '0xced02e')
        yield BlockLoadRequest('set', 'light_index', None,
                               read('LightIndex', '0xcc8159')[0], '0xcc816c')
        yield BlockLoadRequest('capture', 'loaded_light_count', None,
                               len(read('LightLevel', '0xcc8182')), '0xcc81aa')
        for block in range(8):
            yield BlockLoadRequest('get_indexed_level_and_set', 'light_level', block,
                                   self.level_for_block(block), '0xcc823a')
            yield BlockLoadRequest('set', 'store1', block,
                                   read('LightLevelStore1', '0xcc8267')[block], '0xcc828c')
            yield BlockLoadRequest('set', 'store2', block,
                                   read('LightLevelStore2', '0xcc82a2')[block], '0xcc82c7')
            high = read('TimerHighByte', '0xcc7dc6')[block]
            low = read('TimerLowByte', '0xcc7df7')[block]
            yield BlockLoadRequest('set', 'timer', block, (high << 8) | low, '0xcc82df')
            yield BlockLoadRequest('set_microfunction', 'expiry', block,
                                   read('TimerExpiryCommand', '0xcc7ea4')[block], '0xcc82f7')
            yield BlockLoadRequest('check_expiry', 'expiry', block,
                                   TIMER_EXPIRY_TYPES, '0xcc8357')
            yield BlockLoadRequest('get_group', 'group', block,
                                   read('GroupAddress', '0xcc7618')[block], '0xcc83ba')

    def parameters(self, current_levels, *, light_index=None):
        """CoreKey's two indexed level fields, before later ST7 power writes.

        The owner supplies its current index when it differs from the loaded
        value. Other block serializers and all callbacks remain owner duties.
        """
        index = self.light_index if light_index is None else light_index
        levels = rebuild_light_levels(index, self.loaded_count, current_levels)
        return {'LightIndex': [index], 'LightLevel': list(levels)}

    def as_dict(self):
        return {'format': 'cbus-senlla-block-load-plan-v1',
                'identity': list(self.snapshot.identity),
                'light_index': self.light_index, 'loaded_light_count': self.loaded_count,
                'expected': self.snapshot.parameters(),
                'requests': [request.as_dict() for request in self.requests()],
                'owner_executor_required': True, 'complete_toolkit_save': False,
                'original_execution': False, 'physical_acceptance': False}


def block_load_plan(snapshot):
    return BlockLoadPlan(snapshot)
