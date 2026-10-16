"""Live SENLLA occupancy attributes on the shared, synchronous owner.

This constructs the native four Boolean attributes before PP loading.  Bank
refresh, JoinActive and late decision handlers are actual owner dependencies;
this component never substitutes a detached flag tuple for those operations.
"""
from dataclasses import dataclass

from .senlla_lifecycle import (AttributeManager, BooleanAttribute, FlashObject,
                               ObjectReferenceAttribute, TrackedReferenceHandle)
from .sensors import SensorError


FLAG_NAMES = ('LightAndMovement', 'DarkAndMovement', 'AnyMovement', 'Sunset')


def _index(value, label):
    if type(value) is not int or not 0 <= value < 8:
        raise SensorError(f'{label} requires an integer in 0..7')
    return value


def _boolean(value, label):
    if type(value) is not bool:
        raise SensorError(f'{label} requires a Boolean')
    return value


def _flag(value):
    if isinstance(value, str) and value in FLAG_NAMES:
        return FLAG_NAMES.index(value)
    if type(value) is int and 0 <= value < 4:
        return value
    raise SensorError('Occupancy flag requires its native name or ordinal in 0..3')


class MacroOccupancyDecision:
    """The actual mutable source bytes94/95, not a detached decision result."""
    def __init__(self, occupancy):
        self.occupancy = occupancy

    @property
    def decision_pending(self):
        return self.occupancy.decision_pending

    @decision_pending.setter
    def decision_pending(self, value):
        self.occupancy.decision_pending = _boolean(value, 'Decision byte94')

    @property
    def refresh_from_macro(self):
        return self.occupancy.refresh_from_macro

    @refresh_from_macro.setter
    def refresh_from_macro(self, value):
        self.occupancy.refresh_from_macro = _boolean(value, 'Refresh byte95')


@dataclass
class EventTemplateDecision:
    refresh_template: bool = False


class LiveOccupancyKey:
    """One SAME native occupancy object, manager, key reference and flags."""
    def __init__(self, owner, index):
        self.owner, self.index = owner, index
        self.native_state = 1
        self.object = FlashObject(f'occupancy:{index}', trace=owner.trace)
        self.manager = AttributeManager(self.object, trace=owner.trace)
        self.input_key = ObjectReferenceAttribute(self.manager,
                name=f'occupancy:{index}.InputKey', trace=owner.trace)
        self.attributes = {'InputKey': self.input_key}
        for flag, name in enumerate(FLAG_NAMES):
            self.attributes[name] = BooleanAttribute(self.manager,
                    name=f'occupancy:{index}.{name}',
                    after_change=lambda attr, flag=flag: owner._run(
                        lambda: self._flag_changed(flag, attr)), trace=owner.trace)
        self.decision_pending = self.refresh_from_macro = True
        self.refreshing_template = self.refreshing_flags = False  # bytes96/97
        self._key = self._link = self._root_callback = None

    def bind_input_key(self, key):
        if self._key is not None:
            raise SensorError('Fresh occupancy InputKey binding is performed once')
        self.input_key.set(key.object)
        # Native getter follows the completed reference setter before binding.
        if self.input_key.value is not key.object:
            raise SensorError('Occupancy requires the SAME current InputKey')
        self._key = key
        self._link = TrackedReferenceHandle(key.template,
                lambda _: self.owner._run(self.macro_changed))
        self._root_callback = lambda _: self._link._update() if self._link.active else None
        key.object.publisher.subscribe(self._root_callback)
        self._link.activate()

    def attribute(self, flag):
        if flag == 'InputKey':
            return self.input_key
        return self.attributes[FLAG_NAMES[_flag(flag)]]

    def get_flag(self, flag):
        return self.attribute(_flag(flag)).value

    def set_flag(self, flag, value):
        self.attribute(_flag(flag)).set(_boolean(value, 'Occupancy flag'))

    def _flag_changed(self, flag, sender):
        if flag < 3 and self.get_flag(flag):
            # Nested false setters publish and deliver their own events first.
            for other in ((2, 1), (0, 2), (0, 1))[flag]:
                self.set_flag(other, False)
        self._event_flag_changed(sender)

    def _event_flag_changed(self, sender):
        decision = EventTemplateDecision()
        if self.owner.event_template_callback is not None:
            self.owner._event('event_template_callback', key=self.index,
                              source='0xd010d2')
            result = self.owner.event_template_callback(self, decision)
            if result is not None:
                raise SensorError('Native event callback uses its mutable Boolean argument')
            _boolean(decision.refresh_template, 'Event-to-template decision')
        if decision.refresh_template and not self.refreshing_flags:
            self.refreshing_template = True
            try:
                self.refresh_macro_from_flags()
            finally:
                self.refreshing_template = False
        self.owner._event('bank_refresh', key=self.index, source='0xd0112c')
        if self.owner.bank_refresh(self) is not None:
            raise SensorError('Occupancy bank refresh must finish its actual setters')

    def _template(self):
        current_key = self.input_key.value
        if current_key is None:
            return None
        if self._key is None or current_key is not self._key.object:
            raise SensorError('Occupancy requires its SAME bound InputKey')
        return self._key.template.value

    def _type(self, current):
        value = getattr(current, 'identity', None)
        if type(value) is not int or not 0 <= value <= 58:
            raise SensorError('Occupancy requires its actual native template in 0..58')
        return value

    def _is_scene_key(self):
        # d00c7d reads InputKey once before d115bc separately reads CURRENT
        # Template for its nil guard and each 23/24/25 comparison.
        current_key = self.input_key.value
        if current_key is not self._key.object:
            raise SensorError('Occupancy Scene predicate requires its SAME InputKey')
        if self._key.template.value is None:
            return False
        for candidate in (23, 24, 25):
            if self._type(self._key.template.value) == candidate:
                return True
        return False

    def _joined_upper_key(self):
        return _boolean(self.owner.join_active(self), 'Native JoinActive') and self.index >= 4

    def macro_changed(self):
        # This profile admits a normal live owner1, not object destruction2.
        if self.refreshing_template:
            return
        self.refreshing_flags = True
        try:
            self.refresh_flags_smart()
        finally:
            self.refreshing_flags = False

    def refresh_flags_smart(self):
        if self._joined_upper_key():
            return
        current = self._template()
        if current is None:
            return
        kind = self._type(self._template())
        if kind in (29, 30, 33, 34) or self._is_scene_key():
            self.decision_pending = True
            self.refresh_flags()
            return
        if self.decision_pending:
            if self.owner.macro_decision_callback is None:
                self.refresh_from_macro = False
            else:
                block = self.owner.broadcast_block(self)
                present = _boolean(self.owner.has_block(self, block), 'Native HasBlock')
                if present and _boolean(self.owner.broadcast_active(self), 'Native BroadcastActive'):
                    self.refresh_from_macro = True
                else:
                    self.owner._event('macro_decision_callback', key=self.index,
                                      source='0xd00dee')
                    result = self.owner.macro_decision_callback(self, MacroOccupancyDecision(self))
                    if result is not None:
                        raise SensorError('Native macro decision mutates source bytes94/95')
                    _boolean(self.decision_pending, 'Decision byte94')
                    _boolean(self.refresh_from_macro, 'Refresh byte95')
        if self.refresh_from_macro:
            self.refresh_flags()
        self.decision_pending = False

    def refresh_flags(self):
        # QuickSet rereads CURRENT template after the Smart decision callback.
        if self.input_key.value is None or self._template() is None:
            return
        if self._joined_upper_key():
            return
        kind = self._type(self._template())
        for flag, expected in enumerate((29, 30, 33, 34)):
            self.set_flag(flag, kind == expected)

    def refresh_macro_from_flags(self):
        kind = 16
        for flag, candidate in enumerate((29, 30, 33, 34)):
            if self.get_flag(flag):
                kind = candidate
                break
        if self.input_key.value is None:
            raise SensorError('Native occupancy template setter dereferences nil InputKey')
        if self.owner.set_template(self, kind) is not None:
            raise SensorError('Native template setter must finish its actual callbacks')

    def compatible_with_broadcast(self):
        return not any(self.get_flag(flag) for flag in range(4))

    def snapshot(self):
        # Inspection is deliberately not a native getter/Resolve operation.
        return {'index': self.index,
                'flags': [self.attributes[name]._value for name in FLAG_NAMES],
                'decision_pending': self.decision_pending,
                'refresh_from_macro': self.refresh_from_macro,
                'refreshing_template': self.refreshing_template,
                'refreshing_flags': self.refreshing_flags,
                'object': self.object.snapshot(),
                'attributes': {name: attr.snapshot() for name, attr in self.attributes.items()}}


class SENLLALiveOccupancy:
    """Source constructor and synchronous flag/controller operations.

    Callbacks consume the SAME objects at actual source positions.  A missing
    late decision is nil until explicitly installed. An installed callback
    must implement the actual owner decision or raise; no default ack exists.
    """
    def __init__(self, unit, keys, *, bank_refresh, join_active, broadcast_active,
                 broadcast_block, has_block, set_template, trace=None, owner_state=1):
        if not isinstance(unit, FlashObject) or owner_state != 1 or type(owner_state) is not int:
            raise SensorError('Occupancy construction requires actual live Unit state 1')
        if (not isinstance(keys, (tuple, list)) or len(keys) != 8
                or any(not isinstance(getattr(key, 'object', None), FlashObject)
                       or not isinstance(getattr(key, 'template', None), ObjectReferenceAttribute)
                       or getattr(key.template.manager, 'parent', None) is not key.object
                       for key in keys)
                or len({id(key.object) for key in keys}) != 8):
            raise SensorError('Occupancy requires eight SAME distinct native InputKey objects')
        if any(key.template._value is not None for key in keys):
            raise SensorError('Live occupancy must be constructed before key PP loading')
        if any(getattr(getattr(key, 'smart', None), 'active', False) for key in keys):
            raise SensorError('Owning factory must defer the historical Smart observer')
        callbacks = (bank_refresh, join_active, broadcast_active, broadcast_block, has_block, set_template)
        if any(not callable(callback) for callback in callbacks):
            raise SensorError('Live occupancy requires concrete owning getter/setter executors')
        self.unit, self.trace = unit, trace
        self.bank_refresh, self.join_active = bank_refresh, join_active
        self.broadcast_active, self.broadcast_block = broadcast_active, broadcast_block
        self.has_block, self.set_template = has_block, set_template
        self.failed = False
        self.events = []
        self.macro_decision_callback = self.event_template_callback = None
        self.keys = tuple(LiveOccupancyKey(self, index) for index in range(8))
        for occupancy, key in zip(self.keys, keys):
            self._run(lambda occupancy=occupancy, key=key: occupancy.bind_input_key(key))

    def _run(self, operation):
        if self.failed:
            raise SensorError('Interrupted live occupancy cannot be resumed')
        try:
            return operation()
        except BaseException:
            self.failed = True
            raise

    def _event(self, operation, **facts):
        self.events.append(dict(operation=operation, **facts))

    def key(self, index):
        return self.keys[_index(index, 'Occupancy key')]

    def get_flag(self, key, flag):
        return self._run(lambda: self.key(key).get_flag(flag))

    def set_flag(self, key, flag, value):
        return self._run(lambda: self.key(key).set_flag(flag, value))

    def current_flags(self, key):
        """Explicit four native getters; predicates should short-circuit instead."""
        return tuple(self.get_flag(key, flag) for flag in range(4))

    def refresh_flags(self, key):
        return self._run(self.key(key).refresh_flags)

    def macro_changed(self, key):
        return self._run(self.key(key).macro_changed)

    def install_macro_decision(self, callback):
        if not callable(callback):
            raise SensorError('Installed source330 decision requires its actual callback')
        self.macro_decision_callback = callback

    def install_event_template_callback(self, callback):
        if not callable(callback):
            raise SensorError('Installed source338 decision requires its actual callback')
        self.event_template_callback = callback

    def snapshot(self):
        return {'failed': self.failed, 'keys': [key.snapshot() for key in self.keys],
                'macro_decision_installed': self.macro_decision_callback is not None,
                'event_template_installed': self.event_template_callback is not None,
                'events': [dict(event) for event in self.events]}


__all__ = ['FLAG_NAMES', 'MacroOccupancyDecision', 'EventTemplateDecision',
           'LiveOccupancyKey', 'SENLLALiveOccupancy']
