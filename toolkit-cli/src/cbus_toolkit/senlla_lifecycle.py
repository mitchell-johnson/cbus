"""Internal synchronous update/attribute dispatch for the SENLLA owner.

Callbacks run immediately and may call another setter before returning. An
attribute's manager keeps its parent key or block updating throughout the
attribute's dedicated callback. No deferred direct refresh is synthesized.
This module models the retained enabled attributes and balanced owner calls;
it does not install unit, application, Scene or form handlers on its own.
"""
from dataclasses import dataclass

from .sensors import SensorError


def _callback(value, label):
    if value is not None and not callable(value):
        raise SensorError(f'{label} must be callable or None')
    return value


@dataclass(frozen=True)
class LifecycleEvent:
    object_name: str
    operation: str
    depth: int

    def as_dict(self):
        return {'object': self.object_name, 'operation': self.operation, 'depth': self.depth}


class UpdateObject:
    """The native base counter and one generic OnChange callback.

    Returning to zero publishes even if no setter changed a value. The
    callback is synchronous. Counter imbalance refuses; it is not a valid
    owning lifecycle and cannot be converted to an invented notification.
    """

    def __init__(self, name, on_changed=None, *, trace=None):
        if not isinstance(name, str) or not name:
            raise SensorError('Lifecycle object name must be a nonempty string')
        self.name = name
        self.on_changed = _callback(on_changed, 'Generic callback')
        self._trace = _callback(trace, 'Lifecycle trace')
        self._depth = 0

    @property
    def depth(self):
        return self._depth

    @property
    def updating(self):
        return self._depth > 0

    def _record(self, operation):
        if self._trace is not None:
            self._trace(LifecycleEvent(self.name, operation, self.depth))

    def begin_update(self):
        self._depth += 1
        self._record('begin')

    def end_update(self):
        if self._depth == 0:
            raise SensorError(f'Unbalanced EndUpdate for {self.name}')
        self._depth -= 1
        self._record('end')
        if self._depth == 0:
            self.changed()

    def changed(self):
        self._record('changed')
        if self._depth == 0 and self.on_changed is not None:
            self._record('generic')
            self.on_changed(self)

    def snapshot(self):
        return {'name': self.name, 'depth': self.depth, 'updating': self.updating}


class AttributeManager(UpdateObject):
    """Begin parent before self; End self before parent, without finally."""

    def __init__(self, parent, name=None, on_changed=None, *, trace=None):
        if parent is not None and not isinstance(parent, UpdateObject):
            raise SensorError('Attribute manager parent must be an UpdateObject or None')
        super().__init__(name or (parent.name + '.attributes' if parent else 'attributes'),
                         on_changed, trace=trace)
        self.parent = parent

    def begin_update(self):
        if self.parent is not None:
            self.parent.begin_update()
        super().begin_update()

    def end_update(self):
        super().end_update()
        if self.parent is not None:
            self.parent.end_update()

    def changed(self):
        super().changed()
        if self.parent is not None:
            self.parent.changed()


class NotificationPublisher:
    """Explicit managed subscriptions, visited newest first.

    The native loop captures its upper index once, then reads the current
    item at each index. A callback may add or remove subscriptions; a removed
    index that is subsequently accessed refuses like the native list error.
    """

    def __init__(self, subscribers=()):
        self._subscribers = []
        for callback in subscribers:
            self.subscribe(callback)

    def subscribe(self, callback):
        if callback is None:
            raise SensorError('Managed subscriber must be callable')
        callback = _callback(callback, 'Managed subscriber')
        if not any(item is callback for item in self._subscribers):
            self._subscribers.append(callback)

    def unsubscribe(self, callback):
        for index, item in enumerate(self._subscribers):
            if item is callback:
                del self._subscribers[index]
                return

    def notify(self, sender):
        for index in range(len(self._subscribers) - 1, -1, -1):
            if index >= len(self._subscribers):
                raise SensorError('Native managed publisher index became unavailable')
            self._subscribers[index](sender)


class ManagedUpdateObject(UpdateObject):
    """Managed publication guard, separate from the base update counter."""

    def __init__(self, name, on_changed=None, *, generic_subscribers=(),
                 managed=True, enabled=True, reference_notification=None, trace=None):
        super().__init__(name, on_changed, trace=trace)
        if type(managed) is not bool or type(enabled) is not bool:
            raise SensorError('Managed lifecycle flags require Booleans')
        self.managed = managed
        self.enabled = enabled
        self.publisher = NotificationPublisher(generic_subscribers)
        self.reference_notification = _callback(reference_notification, 'Reference notification')
        self._published = False

    def resolve_change(self):
        self._published = False
        self._record('resolve')

    def changed(self):
        if not self.updating and self.managed and self.enabled and not self._published:
            self._published = True
            self._record('managed')
            self.publisher.notify(self)
            if self.reference_notification is not None:
                self._record('references')
                self.reference_notification(self)
        super().changed()

    def snapshot(self):
        return {**super().snapshot(), 'published': self._published,
                'managed': self.managed, 'enabled': self.enabled}


class FlashObject(ManagedUpdateObject):
    """Key/block custom-object route rearms before Managed.Changed."""

    def changed(self):
        self.resolve_change()
        super().changed()


class FlashAttribute(ManagedUpdateObject):
    """Enabled flash attribute generic/manager/dedicated notification order.

    The dedicated AfterChange callback is not gated by the attribute counter.
    The manager notification is gated. This distinction matters when clearing
    a non-nil object reference resets its observer during the setter.
    """

    def __init__(self, manager, value=None, *, name=None, after_change=None,
                 on_changed=None, enabled=True, generic_subscribers=(), trace=None):
        if manager is not None and not isinstance(manager, AttributeManager):
            raise SensorError('Flash attribute manager must be an AttributeManager or None')
        if type(enabled) is not bool:
            raise SensorError('Flash attribute enabled state requires a Boolean')
        super().__init__(name or 'attribute', on_changed, enabled=enabled,
                         generic_subscribers=generic_subscribers, managed=manager is not None,
                         trace=trace)
        self.manager = manager
        self.after_change = _callback(after_change, 'Dedicated callback')
        self.enabled = enabled
        self._value = value

    def resolve_change(self):
        super().resolve_change()
        if self.manager is not None and isinstance(self.manager.parent, ManagedUpdateObject):
            self.manager.parent.resolve_change()

    @property
    def value(self):
        return self._value

    def begin_update(self):
        if self.manager is not None:
            self.manager.begin_update()
        super().begin_update()

    def end_update(self):
        super().end_update()
        if self.manager is not None:
            self.manager.end_update()

    def changed(self):
        super().changed()
        if not self.updating and self.enabled and self.manager is not None:
            self.manager.changed()
        if self.enabled and self.after_change is not None:
            self._record('dedicated')
            self.after_change(self)


class BooleanAttribute(FlashAttribute):
    """Equal Boolean writes return before beginning any update."""

    def __init__(self, manager, value=False, **kwargs):
        if type(value) is not bool:
            raise SensorError('Boolean attribute requires a Boolean')
        super().__init__(manager, value, **kwargs)

    @property
    def value(self):
        self.resolve_change()
        return self._value

    def set(self, value):
        if type(value) is not bool:
            raise SensorError('Boolean attribute requires a Boolean')
        if self._value == value:
            return
        self.begin_update()
        try:
            self._value = value
            self._record('assign')
        finally:
            self.end_update()


def _signed_integer(value):
    if type(value) is not int or not -(1 << 31) <= value < (1 << 31):
        raise SensorError('Integer attribute requires a signed 32-bit integer')
    return value


@dataclass
class IntegerChange:
    previous: int
    proposed: int
    changed: bool


class IntegerAttribute(FlashAttribute):
    """Native AsInteger setter; BeforeChange runs before bounds/update.

    Unlike the object-reference setter, this callback's proposed value is
    honored. Equal writes can be changed or cancelled by that callback. Equal
    min/max disables the native range check; otherwise bounds are inclusive.
    The direct AsInteger getter does not rearm managed publication.
    """

    def __init__(self, manager, value=0, *, minimum=0, maximum=0,
                 before_change=None, **kwargs):
        self.minimum = _signed_integer(minimum)
        self.maximum = _signed_integer(maximum)
        if self.minimum > self.maximum:
            raise SensorError('Integer attribute minimum exceeds maximum')
        super().__init__(manager, _signed_integer(value), **kwargs)
        self.before_change = _callback(before_change, 'Integer BeforeChange callback')

    def set(self, value):
        value = _signed_integer(value)
        decision = IntegerChange(self._value, value, self._value != value)
        if self.before_change is not None:
            self._record('before')
            self.before_change(self, decision)
            if type(decision.changed) is not bool:
                raise SensorError('Integer BeforeChange changed flag requires a Boolean')
        if not decision.changed:
            return
        candidate = _signed_integer(decision.proposed)
        if self.minimum != self.maximum and not self.minimum <= candidate <= self.maximum:
            raise SensorError('Integer attribute value is outside its native inclusive bounds')
        self.begin_update()
        try:
            self._value = candidate
            self._record('assign')
        finally:
            self.end_update()


@dataclass
class ReferenceChange:
    """Native BeforeChange arguments; replacement is advisory in this setter.

    The setter passes a mutable proposed pointer and changed flag. Its final
    assignment nevertheless uses the original setter argument, controlled by
    the resulting changed flag. Equality always compares object identity.
    """
    previous: object
    proposed: object
    changed: bool


class ObjectReferenceAttribute(FlashAttribute):
    """Equal references still notify; nonnil-to-nil resets notify twice."""

    def __init__(self, manager, value=None, *, before_change=None, **kwargs):
        super().__init__(manager, value, **kwargs)
        self.before_change = _callback(before_change, 'Reference BeforeChange callback')

    @property
    def value(self):
        self.resolve_change()
        return self._value

    def set(self, value):
        if self.updating:
            self._record('can_do_change_refused')
            return
        self.begin_update()
        try:
            decision = ReferenceChange(self._value, value, self._value is not value)
            if self.enabled and self.before_change is not None:
                self._record('before')
                self.before_change(self, decision)
                if type(decision.changed) is not bool:
                    raise SensorError('Reference BeforeChange changed flag requires a Boolean')
            if decision.changed:
                self._value = value
                self._record('assign')
                if value is None:
                    # Reference.Reset invokes ReferenceReset without the
                    # updating guard used by ReferenceChanged.
                    self._record('reference_reset')
                    self.changed()
        finally:
            self.end_update()


class TrackedReferenceHandle:
    """Stable active reference route used by installed macro expressions.

    The root publisher dereferences the current attribute on each delivery.
    Pointer changes replace the target subscription before the callback;
    equal pointers suppress it. Direct target notifications always deliver.
    Expression parsing and general control binding remain with the owner.
    """

    def __init__(self, root, on_current_changed):
        if not isinstance(root, ObjectReferenceAttribute):
            raise SensorError('Tracked reference root requires an object-reference attribute')
        self.root = root
        self.on_current_changed = _callback(on_current_changed, 'Tracked current callback')
        self._current = None
        self._active = False
        # Retain bound callback identities for native identity-unique lists.
        self._root_callback = self._root_changed
        self._target_callback = self._target_changed

    @property
    def current(self):
        return self._current

    @property
    def active(self):
        return self._active

    def activate(self):
        if self._active:
            return
        self._active = True
        self.root.publisher.subscribe(self._root_callback)
        self._update()

    def _root_changed(self, sender):
        if self._active:
            self._update()

    def _update(self):
        current = self.root.value
        if current is self._current:
            return
        if current is not None and not isinstance(current, ManagedUpdateObject):
            raise SensorError('Tracked current object requires its actual managed publisher')
        if self._current is not None:
            self._current.publisher.unsubscribe(self._target_callback)
        self._current = current
        if current is not None:
            current.publisher.subscribe(self._target_callback)
        self._deliver()

    def _target_changed(self, sender):
        self._deliver()

    def _deliver(self):
        if self._active and self.on_current_changed is not None:
            self.on_current_changed(self)
