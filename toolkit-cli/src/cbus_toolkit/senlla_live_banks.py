"""Live SENLLA formula3 bank attributes on the owning shared object graph.

The tracked Block expression delivers native bank callbacks. The key kernel's
live dispatcher observes those callbacks and supplies one current occupancy
event at a time. Detached numeric bank projections never deliver notifications.
"""
from dataclasses import replace
from copy import deepcopy

from .senlla_banks import BankState
from .senlla_key_references import SENLLAKeyReferences
from .senlla_lifecycle import (AttributeManager, BooleanAttribute, FlashObject,
                               IntegerAttribute, ObjectReferenceAttribute,
                               TrackedReferenceHandle)
from .sensors import SensorError


def _index(value, label):
    if type(value) is not int or not 0 <= value < 8:
        raise SensorError(f'{label} requires an integer in 0..7')
    return value


def _lux_byte(value):
    # Native signed IntegerAttribute is unbounded; the formula3 converter
    # clamps outside 0..2550 and uses Ceil within that interval.
    return 0 if value < 0 else 255 if value > 2550 else (value + 9) // 10


def _byte_lux(value):
    # Stores are actual signed IntegerAttributes too. Conversion clamps the
    # input; a same-lux result does not itself rewrite the original Store.
    return 0 if value < 0 else 2550 if value > 255 else value * 10


class LiveBank:
    """One real bank manager, its eight attributes and active Block follower."""

    def __init__(self, owner, index):
        self.owner = owner
        self.index = index
        self.native_state = 1
        trace = owner.runtime._trace
        self.object = FlashObject(f'bank:{index}', trace=trace)
        self.manager = AttributeManager(self.object, trace=trace)
        prefix = f'bank:{index}.'
        self.block = ObjectReferenceAttribute(self.manager, name=prefix + 'Block', trace=trace)
        self.active = BooleanAttribute(self.manager, name=prefix + 'SwitchActive',
                after_change=lambda _: self._active_changed(), trace=trace)
        self.allowed = BooleanAttribute(self.manager, name=prefix + 'SwitchAllowed',
                after_change=lambda _: self._allowed_changed(), trace=trace)
        self.off = BooleanAttribute(self.manager, name=prefix + 'EnableGroupOff', trace=trace)
        self.high_lux = IntegerAttribute(self.manager, name=prefix + 'HighLevelLux',
                after_change=lambda _: self._level_changed(True), trace=trace)
        self.low_lux = IntegerAttribute(self.manager, name=prefix + 'LowLevelLux',
                after_change=lambda _: self._level_changed(False), trace=trace)
        self.use_low = BooleanAttribute(self.manager, name=prefix + 'UseLowLevelGroup', trace=trace)
        self.use_high = BooleanAttribute(self.manager, name=prefix + 'UseHighLevelGroup', trace=trace)
        self.attributes = dict(Block=self.block, SwitchActive=self.active,
                SwitchAllowed=self.allowed, EnableGroupOff=self.off,
                HighLevelLux=self.high_lux, LowLevelLux=self.low_lux,
                UseLowLevelGroup=self.use_low, UseHighLevelGroup=self.use_high)
        self._link = TrackedReferenceHandle(self.block, self._block_changed)
        # Native expression's owning root follower reevaluates on bank Changed.
        # The same Block pointer suppresses a deferred current-value callback.
        self._root_callback = lambda _: self._link._update() if self._link.active else None
        self.object.publisher.subscribe(self._root_callback)

    def set_block(self, block_object):
        if block_object is not None and block_object not in self.owner.runtime._block_indices:
            raise SensorError('Bank Block requires a canonical SAME-runtime block object')
        self.block.set(block_object)
        # SetBlock enables the expression AFTER the reference setter completes.
        self._link.activate()

    def current_block(self):
        current = self.block.value
        if current is None:
            raise SensorError('Native bank setter requires a nonnil current Block')
        index = self.owner.runtime._block_indices.get(current)
        if index is None or self.owner.runtime.blocks[index].object is not current:
            raise SensorError('Bank Block is not the canonical SAME-runtime object')
        return self.owner.runtime.blocks[index]

    def _active_changed(self):
        if self.active.value and self.high_lux.value < self.low_lux.value:
            self.low_lux.set(self.high_lux.value)

    def _allowed_changed(self):
        if not self.allowed.value and self.active.value:
            self.active.set(False)

    def _level_changed(self, high):
        self.object.begin_update()
        try:
            self.current_block().object.begin_update()
            try:
                value = (self.high_lux if high else self.low_lux).value
                # Formula3 is the literal ST7 virtual GetLuxFormula result.
                target = self.current_block()
                (target.store1 if high else target.store2).set(_lux_byte(value))
            finally:
                # Source rereads Block for EndUpdate rather than retaining the
                # earlier local. A callback-induced unbalanced rebind refuses.
                self.current_block().object.end_update()
        finally:
            self.object.end_update()
        if self.active.value:
            if high and self.high_lux.value < self.low_lux.value:
                self.low_lux.set(self.high_lux.value)
            elif not high and self.low_lux.value > self.high_lux.value:
                self.high_lux.set(self.low_lux.value)

    def _block_changed(self, handle):
        if (handle.current is None or self.native_state == 2
                or self.object.updating or self.block.value is None):
            self.owner._event('live_bank_block_suppressed', bank=self.index)
            return
        self.owner._event('live_bank_block_refresh', bank=self.index)
        self.refresh_allowed()
        # BOTH values are captured after Allowed, before either logical setter.
        first = _byte_lux(self.current_block().store1.value)
        second = _byte_lux(self.current_block().store2.value)
        if self.high_lux.value != first:
            self.high_lux.set(first)
        if self.low_lux.value != second:
            self.low_lux.set(second)

    def refresh_allowed(self):
        blocked = False
        # Native captures Key.Count once and rereads each current key/Block.
        count = len(self.owner.runtime.keys)
        for ordinal in range(count):
            if ordinal >= len(self.owner.runtime.keys):
                raise SensorError('Native key collection ordinal became unavailable')
            if (self.owner.maintenance_block.value is self.block.value
                    and self.owner.maintenance_active.value):
                blocked = True
                continue
            key = self.owner.runtime.keys[ordinal]
            current = self.block.value
            index = self.owner.runtime._block_indices.get(current)
            if index is not None and index in key.refs and self.owner._occupied(ordinal):
                blocked = True
        self.allowed.set(not blocked)

    def snapshot(self):
        # Instrumentation reads storage, not native getters: observing the
        # graph must not rearm Boolean/reference publication guards.
        current = self.block._value
        index = self.owner.runtime._block_indices.get(current)
        block = self.owner.runtime.blocks[index] if index is not None else None
        return dict(block=index, high_lux=self.high_lux._value, low_lux=self.low_lux._value,
                switch_active=self.active._value, switch_allowed=self.allowed._value,
                enable_group_off=self.off._value, use_low=self.use_low._value,
                use_high=self.use_high._value, store1=block.store1.value if block else None,
                store2=block.store2.value if block else None,
                object=self.object.snapshot(), manager=self.manager.snapshot(),
                attributes={name: attr.snapshot() for name, attr in self.attributes.items()})


class SENLLALiveBanks:
    """Construct before PP, bind SAME blocks, then attach the kernel dispatcher.

    Maintenance attributes belong to the actual Unit manager. Their setters
    have no native dedicated bank callback; this adapter only reads them at
    source aggregate/event positions. Persistent form controls can subscribe
    directly to bank attributes. No form bindings are installed here.
    """

    def __init__(self, runtime, *, maintenance_active, maintenance_block):
        if (not isinstance(maintenance_active, BooleanAttribute)
                or not isinstance(maintenance_block, ObjectReferenceAttribute)
                or maintenance_active.manager is not runtime.unit_manager
                or maintenance_block.manager is not runtime.unit_manager):
            raise SensorError('Live banks require SAME Unit maintenance attributes')
        if (runtime.phase != 'fresh_constructor' or runtime.unit.updating
                or len(runtime.blocks) != 8 or len(runtime.keys) != 8
                or getattr(runtime, 'live_bank_dispatch', None) is not None):
            raise SensorError('Live banks must attach once before owning PP loading')
        self.runtime = runtime
        self.maintenance_active = maintenance_active
        self.maintenance_block = maintenance_block
        self.graph_observation_available = True
        self.banks = tuple(LiveBank(self, index) for index in range(8))
        for bank, block in zip(self.banks, runtime.blocks):
            bank.set_block(block.object)
        self.attach()

    def _event(self, operation, **values):
        self.runtime._event(operation, **values)

    def _flag(self, key, flag):
        # One actual native Boolean getter, including its publication rearm.
        # A tuple inspection must not eagerly resolve the three unused attrs.
        value = self.runtime.get_occupancy_flag(key, flag)
        if type(value) is not bool:
            raise SensorError('Current occupancy requires an actual Boolean flag')
        return value

    def _occupied(self, key, order=(1, 0, 2, 3)):
        # The ST7 aggregate and two event predicates use different native
        # Boolean getter orders; each getter rereads current flags.
        return any(self._flag(key, index) for index in order)

    def attach(self):
        current = getattr(self.runtime, 'live_bank_dispatch', None)
        if current is not None and current is not self:
            raise SensorError('Runtime already has a live bank dispatcher')
        self.runtime.live_bank_dispatch = self
        self.sync_graph_observation()

    def _same_runtime(self, runtime):
        if runtime is not self.runtime:
            raise SensorError('Live bank dispatcher requires its SAME owning runtime')

    def block_changed(self, index, runtime):
        """Kernel observation hook; tracked listeners already executed setters."""
        self._same_runtime(runtime)
        _index(index, 'Block index')
        self.sync_graph_observation()

    def _bank_for_block(self, block):
        count = len(self.banks)
        for ordinal in range(count):
            if ordinal >= len(self.banks):
                raise SensorError('Native bank collection ordinal became unavailable')
            bank = self.banks[ordinal]
            if bank.block.value is block:
                return bank
        return None

    def occupancy_bank_event(self, key, runtime):
        """One native event, using CURRENT flags/ref items after each setter."""
        self._same_runtime(runtime)
        key = _index(key, 'Key index')
        # Both native InputKey getters are observable: the first precedes
        # captured Count, the second precedes each CURRENT reference item.
        count = len(runtime.occupancy_input_key(key).refs)
        for ordinal in range(count):
            refs = runtime.occupancy_input_key(key).refs
            if ordinal >= len(refs):
                raise SensorError('Native block-reference ordinal became unavailable')
            block = runtime.blocks[_index(refs[ordinal], 'Referenced block')].object
            bank = self._bank_for_block(block)
            if bank is None:
                continue
            if self._occupied(key, (0, 1, 2, 3)):
                bank.active.set(False)
            # Active's callbacks may change current flags and Block identity.
            blocked = self._occupied(key, (0, 2, 1, 3))
            if not blocked:
                blocked = (self.maintenance_block.value is bank.block.value
                           and self.maintenance_active.value)
            bank.allowed.set(not blocked)
        self.sync_graph_observation()

    def sync_graph_observation(self):
        """Refresh bounded numeric observation without invoking any callback.

        Native integer attrs permit signed32 outside BankState's 0..2550
        profile. Those values remain in snapshot(); the older bounded graph
        cannot describe them and is explicitly marked unavailable.
        """
        states = []
        for index, bank in enumerate(self.banks):
            values = bank.snapshot()
            if (values['block'] != index or not 0 <= values['high_lux'] <= 2550
                    or not 0 <= values['low_lux'] <= 2550
                    or not 0 <= values['store1'] <= 255
                    or not 0 <= values['store2'] <= 255):
                self.graph_observation_available = False
                return False
            states.append(BankState(values['high_lux'], values['low_lux'],
                    values['switch_active'], values['switch_allowed'],
                    values['enable_group_off'], values['store1'], values['store2']))
        refs = SENLLAKeyReferences(tuple(tuple(key.refs) for key in self.runtime.keys))
        maintenance = self.maintenance_block._value
        if maintenance is not None and maintenance not in self.runtime._block_indices:
            raise SensorError('Current maintenance block must be a SAME-runtime object')
        self.runtime.graph = replace(self.runtime.graph, banks=tuple(states), references=refs,
                maintenance_active=self.maintenance_active._value,
                maintenance_block=self.runtime._block_indices.get(maintenance))
        self.graph_observation_available = True
        return True

    def snapshot(self):
        return deepcopy(dict(banks=[bank.snapshot() for bank in self.banks],
                graph_observation_available=self.graph_observation_available))


__all__ = ['LiveBank', 'SENLLALiveBanks']
