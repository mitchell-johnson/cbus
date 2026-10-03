"""Persistent SENLLA general-key control kernel with causal native boundaries.

This is the programmatic FlashCx/director slice. Framework effects, exact
Windows list comparison, group-combo rebinding and deferred messages remain
explicit synchronous owner work. It cannot acknowledge a final-state array
in place of executing those effects.
"""
from dataclasses import dataclass, replace

from .senlla_key_events import KeyControlRequest, SENLLAKeyEvents
from .sensors import SensorError


def _index(value):
    if type(value) is not int or not 0 <= value < 8:
        raise SensorError('Control key requires integer 0..7')
    return value


def _text_equal(first, second):
    return first.encode('utf-16-le', 'surrogatepass') == second.encode('utf-16-le', 'surrogatepass')


@dataclass(frozen=True)
class FunctionChoice:
    template: int
    text: str

    def __post_init__(self):
        if type(self.template) is not int or not 0 <= self.template <= 58:
            raise SensorError('Function choice requires native template 0..58')
        if not isinstance(self.text, str):
            raise SensorError('Function choice requires actual description text')


class FunctionRoot:
    """One actual source collection/link identity, distinct from its contents."""
    def __init__(self, identity, choices):
        if not isinstance(identity, str) or not identity:
            raise SensorError('Function root requires a canonical source identity')
        self.identity = identity
        self._choices = self._validate(choices)

    @staticmethod
    def _validate(choices):
        if not isinstance(choices, (list, tuple)) or any(type(x) is not FunctionChoice for x in choices):
            raise SensorError('Function root requires ordered actual FunctionChoices')
        values = tuple(choices)
        if len({x.template for x in values}) != len(values):
            raise SensorError('A function root cannot duplicate the same canonical template object')
        return values

    @property
    def choices(self):
        return self._choices


@dataclass(frozen=True)
class ControlDependency:
    kind: str
    operation: str
    source: str
    key: int | None = None
    value: object = None

    def as_dict(self):
        return dict(kind=self.kind, operation=self.operation, source=self.source,
                    key=self.key, value=self.value)


class ControlDependencyRequired(SensorError):
    def __init__(self, request):
        self._request = request
        super().__init__(f'Native control dependency required: {request.operation}')

    @property
    def request(self):
        return self._request.as_dict()


@dataclass(frozen=True)
class ControlBindings:
    """Source-established roots and resource strings at the actual entry phase.

    Root identities must be actual persistent links, not inferred application
    numbers. Broadcast is nil before its later ST7 construction. Descriptions
    and resource strings come from the owning source/profile, without a host
    locale assumption. No original control execution is implied by this data.
    """
    primary: FunctionRoot
    secondary: FunctionRoot
    broadcast: FunctionRoot | None
    group_nil_text: str
    group_multiple_text: str
    group_modify_text: str

    def __post_init__(self):
        if not isinstance(self.primary, FunctionRoot) or not isinstance(self.secondary, FunctionRoot):
            raise SensorError('Primary and secondary require actual function-root objects')
        if self.broadcast is not None and not isinstance(self.broadcast, FunctionRoot):
            raise SensorError('Broadcast requires an actual function root or actual nil')
        roots = (self.primary, self.secondary, self.broadcast)
        if any(a is not b and a.identity == b.identity for a in roots if a is not None
               for b in roots if b is not None):
            raise SensorError('One root identity cannot name different source objects')
        if any(not isinstance(x, str) for x in
               (self.group_nil_text, self.group_multiple_text, self.group_modify_text)):
            raise SensorError('Group nil representations require actual resource text')
        descriptions = {}
        for root in roots:
            if root is not None:
                for choice in root.choices:
                    previous = descriptions.setdefault(choice.template, choice.text)
                    if not _text_equal(previous, choice.text):
                        raise SensorError('One canonical template requires one actual description')


@dataclass(frozen=True)
class ComboState:
    """Actual completed initial binding state; no empty-state inference."""
    items: tuple[FunctionChoice, ...]
    item_index: int
    text: str
    dirty: bool

    def __post_init__(self):
        if type(self.items) is not tuple or any(type(x) is not FunctionChoice for x in self.items):
            raise SensorError('Combo state requires actual ordered item objects and labels')
        if type(self.item_index) is not int or not -1 <= self.item_index < len(self.items):
            raise SensorError('Combo state requires its actual index or -1')
        if not isinstance(self.text, str) or type(self.dirty) is not bool:
            raise SensorError('Combo state requires actual text and dirty flag')


class SENLLAKeyControls:
    """Callable general-key executor; attach before M8 general subscriptions.

    Existing control state is supplied at the completed initial function
    binding position. This constructor does not replay native form creation.
    A dependency executor receives one typed primitive and the live engine,
    executes its notifications synchronously, and returns None. IndexOf and
    description reads return their actual scalar results. No final graph or
    replacement context is accepted as a result.
    """
    _EXTENSION = frozenset((3, 6, *range(12, 16), 23, 24, *range(29, 35)))

    def __init__(self, bindings, *, roots, combo_states, group_text, extension_visible,
                 subset_names, allow_other_keys, broadcast_items=None,
                 dependency_executor=None, initializing=True, light_frame=False):
        if not isinstance(bindings, ControlBindings):
            raise SensorError('Controls require source-established ControlBindings')
        if not isinstance(roots, (list, tuple)) or len(roots) != 8:
            raise SensorError('Controls require eight actual current root links')
        allowed = (bindings.primary, bindings.secondary, bindings.broadcast)
        if any(root is not None and not any(root is value for value in allowed) for root in roots):
            raise SensorError('Current combo roots must use the actual bound source objects')
        if (not isinstance(combo_states, (list, tuple)) or len(combo_states) != 8
                or any(type(x) is not ComboState for x in combo_states)):
            raise SensorError('Controls require eight actual completed combo binding states')
        if (not isinstance(group_text, (list, tuple)) or len(group_text) != 8
                or any(not isinstance(x, str) for x in group_text)):
            raise SensorError('Controls require eight actual group-controller nil strings')
        if (not isinstance(extension_visible, (list, tuple)) or len(extension_visible) != 8
                or any(type(x) is not bool for x in extension_visible)):
            raise SensorError('Controls require eight actual extension visibility flags')
        if type(initializing) is not bool or type(light_frame) is not bool:
            raise SensorError('Control lifecycle flags require Booleans')
        if (not isinstance(subset_names, (list, tuple)) or len(subset_names) != 8
                or any(not isinstance(x, str) for x in subset_names)):
            raise SensorError('Controls require eight actual current subset names')
        if (not isinstance(allow_other_keys, (list, tuple)) or len(allow_other_keys) != 2
                or any(type(x) is not bool for x in allow_other_keys)):
            raise SensorError('Controls require actual key0/key1 override flags')
        if light_frame:
            self._validate_broadcast_items(broadcast_items)
        elif broadcast_items is not None:
            raise SensorError('Broadcast items require the actual completed light frame')
        if dependency_executor is not None and not callable(dependency_executor):
            raise SensorError('Dependency executor requires an internal callable')
        self.bindings = bindings
        self.roots = list(roots)
        self.group_text = list(group_text)
        self.extension_visible = list(extension_visible)
        self.initializing, self.light_frame = initializing, light_frame
        self.dependency_executor = dependency_executor
        self.engine = None
        self.failed = False
        self.events = []
        self.dirty = [x.dirty for x in combo_states]
        self.rendering = [False] * 8
        self.items = [x.items for x in combo_states]
        self.item_index = [x.item_index for x in combo_states]
        self.text = [x.text for x in combo_states]
        self.current = [None] * 8
        self.subset_name = list(subset_names)
        self.allow_other_keys = list(allow_other_keys)
        self.broadcast_items = None if broadcast_items is None else list(broadcast_items)
        self.deferred = []
        self._receivers = []
        self._target_receivers = []

    @staticmethod
    def _validate_broadcast_items(values):
        if (not isinstance(values, (list, tuple)) or any(type(x) is not int or not 0 <= x < 8 for x in values)
                or len(set(values)) != len(values)):
            raise SensorError('Broadcast list requires its actual ordered block indices')

    def _event(self, operation, **values):
        self.events.append(dict(operation=operation, **values))

    def _dependency(self, kind, operation, source, *, key=None, value=None):
        request = ControlDependency(kind, operation, source, key, value)
        self._event('dependency', request=request.as_dict())
        if self.dependency_executor is None:
            raise ControlDependencyRequired(request)
        result = self.dependency_executor(request, self.engine)
        if kind == 'comparison':
            if type(result) is not int or not -1 <= result < len(self.items[key]):
                raise SensorError('Native Items.IndexOf must return an actual index or -1')
            return result
        if kind == 'description':
            if not isinstance(result, str):
                raise SensorError('Current template description requires actual native text')
            return result
        if result is not None:
            raise SensorError('Control dependency must execute callbacks, not return final state')
        return None

    def attach(self, engine):
        if self.engine is not None or not isinstance(engine, SENLLAKeyEvents):
            raise SensorError('Controls attach once to the actual key-event owner')
        if engine.phase != 'm8_hooks' or engine.hooks_installed or engine.failed:
            raise SensorError('Controls attach after initial function binding and before M8 hooks')
        if not self.initializing or self.light_frame or self.bindings.broadcast is not None:
            raise SensorError('Fresh M8 entry precedes the ST7 broadcast collection and light frame')
        self.engine = engine
        for key, owner in enumerate(engine.keys):
            self.current[key] = owner.template.value
            receiver = lambda _, key=key: self._scalar_changed(key)
            self._receivers.append(receiver)
            owner.object.publisher.subscribe(receiver)
            target_receiver = lambda _, key=key: self._run(lambda: self._render(key))
            self._target_receivers.append(target_receiver)
            if self.current[key] is not None:
                self.current[key].publisher.subscribe(target_receiver)
        self._event('attached_before_m8')
        return self

    def _check(self, engine=None):
        if self.failed or self.engine is None or self.engine.failed:
            raise SensorError('Interrupted or unattached controls cannot execute')
        if engine is not None and engine is not self.engine:
            raise SensorError('Controls require the same live source owner')

    def _run(self, action):
        self._check()
        try:
            return action()
        except Exception:
            self.failed = True
            self.engine.failed = True
            raise

    def __call__(self, request, engine):
        self._check(engine)
        if (type(request) is not KeyControlRequest or request.operation != 'general_key_controls'
                or request.classification is not False):
            raise SensorError('Controls admit only the native actual-Key general branch')
        key = _index(request.key)
        return self._run(lambda: self._general(key))

    def _set_root(self, key, root, source):
        if self.roots[key] is root:
            return
        self.roots[key] = root
        self._event('root_changed', key=key, root=None if root is None else root.identity, source=source)
        # Root choice/equality is closed. Actual controller notifications can
        # have multiple listeners; their executor must issue list_changed at
        # each delivered native position rather than assume one callback.
        self._dependency('binding', 'SetFunctionListRoot', '0x84dfa8', key=key,
                         value=None if root is None else root.identity)

    def _general(self, key):
        engine = self.engine
        first, second = engine.keys[:2]
        enabled = (engine._template_type(0) == 29 and engine._template_type(1) == 30
                   and 1 in first.refs and 1 in second.refs)
        previous_enabled = any(self.allow_other_keys)
        self.allow_other_keys[:] = [enabled, enabled]
        if enabled or previous_enabled:
            # The ordinary SENLLA subset cannot retain the paired29/30 state.
            # An explicitly supplied existing pair needs the actual key/b1
            # consumer binding, which the model kernel does not fabricate.
            self._dependency('model_binding', 'SetPairedKeyBlockOverrides', '0xcfc5cf', value=enabled)
        self.subset_name[key] = 'SENLLA'
        if not self.initializing:
            self._dependency('binding', 'UpdateGroupCombo', '0xf9567c', key=key)
        state = engine.keys[key].application_state.value
        self._set_root(key, self.bindings.primary if state == 0 else self.bindings.secondary, '0xf91f28')
        root = self.roots[key]
        # Count is captured once, but native template and collection elements
        # are reread at every ordinal after nested callbacks.
        if engine.keys[key].template.value is not None:
            if root is None:
                raise SensorError('Native RefreshFunction dereferences its current collection root')
            found = False
            for ordinal in range(len(root.choices)):
                if ordinal >= len(root.choices):
                    raise SensorError('Native function collection index disappeared')
                if engine.templates[root.choices[ordinal].template] is engine.keys[key].template.value:
                    found = True
            if not found:
                self._event('template_reset', key=key, template=16)
                engine.set_template(key, 16)
        self.subset_name[key] = 'SENLLA'
        template = engine._template_type(key)
        representation = (self.bindings.group_modify_text if template == 25 else
                          self.bindings.group_multiple_text if len(engine.keys[key].refs) > 1 else
                          self.bindings.group_nil_text)
        if not _text_equal(self.group_text[key], representation):
            self.group_text[key] = representation
            self._dependency('framework', 'SetGroupNilRepresentation', '0xf964d8', key=key,
                             value=representation)
        template = engine._template_type(key)
        if template is None:
            raise SensorError('Native extension visibility dereferences the current template')
        visible = template in self._EXTENSION
        if self.extension_visible[key] != visible:
            self.extension_visible[key] = visible
            self._dependency('framework', 'SetExtensionVisible', '0xfb7298', key=key, value=visible)
        # PopulateKeyPairings is empty, and actual ST7 IsNeoMultisensor=true
        # returns before PrimaryGroupOrSceneComboAfterChange model setters.
        active = engine.broadcast_active.value
        current_block = engine.broadcast_block.value
        if active and current_block is not None and any(
                engine.blocks[index].object is current_block for index in engine.keys[key].refs):
            root = self.bindings.broadcast
        else:
            state = engine.keys[key].application_state.value
            root = self.bindings.primary if state == 0 else self.bindings.secondary
        self._set_root(key, root, '0xfb7da4')
        if self.light_frame:
            self._populate_broadcast()

    def _scalar_changed(self, key):
        def execute():
            current = self.engine.keys[key].template.value
            if self.current[key] is current:
                return
            if self.current[key] is not None:
                self.current[key].publisher.unsubscribe(self._target_receivers[key])
            self.current[key] = current
            if current is not None:
                current.publisher.subscribe(self._target_receivers[key])
            self._event('scalar_current_changed', key=key, template=None if current is None else current.identity)
            self._render(key)
        return self._run(execute)

    def _description(self, key, current, source):
        choices = [x for root in (self.bindings.primary, self.bindings.secondary, self.bindings.broadcast)
                   if root is not None for x in root.choices
                   if self.engine.templates[x.template] is current]
        if choices:
            return choices[0].text
        return self._dependency('description', 'DescribeCurrentTemplate', source,
                                key=key, value=current.identity)

    def _render(self, key):
        if self.rendering[key]:
            return
        self.rendering[key] = True
        try:
            previous_text = self.text[key]
            self._dependency('binding', 'SetListControllerActive', '0xbbc34e', key=key, value=False)
            self._dependency('binding', 'SetListControllerActive', '0xbbc35e', key=key, value=True)
            self._dependency('framework', 'ItemsBeginUpdate', '0xbbc36b', key=key)
            try:
                self.item_index[key] = -1
                self._dependency('framework', 'SetItemIndex', '0xbbc383', key=key, value=-1)
                self.items[key] = ()
                self._dependency('framework', 'ItemsClear', '0xbbc39e', key=key)
                root = self.roots[key]
                # The stable tracked list handle remains nonnil when its root
                # element is nil; GetCount returns0 in that case.
                count = 0 if root is None else len(root.choices)
                for ordinal in range(count):
                    root = self.roots[key]
                    if root is None:
                        raise SensorError('Native combo current list root became nil')
                    if ordinal >= len(root.choices):
                        raise SensorError('Native combo source ordinal disappeared')
                    choice = root.choices[ordinal]
                    self.items[key] += (choice,)
                    self._dependency('framework', 'ItemsAddObject', '0xbbc532', key=key,
                                     value=(choice.template, choice.text, ordinal))
                    current_root = self.roots[key]
                    if current_root is None or ordinal >= len(current_root.choices):
                        raise SensorError('Native selected-item lookup lost its current source ordinal')
                    if (self.engine.templates[current_root.choices[ordinal].template]
                            is self.engine.keys[key].template.value):
                        self.item_index[key] = len(self.items[key]) - 1
                        self._dependency('framework', 'SetItemIndex', '0xbbc57c', key=key,
                                         value=self.item_index[key])
                self.dirty[key] = False
                # The real Text getter/cache can have changed during SetIndex
                # and Add callbacks. Its nil/empty fallback is a framework
                # primitive, not a target-text versus old-text guess.
                self._dependency('framework', 'FinalizePopulateText', '0xbbc598', key=key,
                                 value=previous_text)
            finally:
                self._dependency('framework', 'ItemsEndUpdate', '0xbbc5f9', key=key)
            self._dependency('framework', 'SelectAll', '0xbbc60b', key=key)
            self._dependency('framework', 'InvalidateFunctionControl', '0xbbc7a8', key=key)
            current = self.engine.keys[key].template.value
            if current is None:
                # Nil representation and preserving actual pre-population
                # Text require the complete control owner, not inferred text.
                self._dependency('framework', 'RenderNilFunctionText', '0xbbc6aa', key=key)
            else:
                description = self._description(key, current, '0xbbc6c7')
                actual_index = self._dependency('comparison', 'ItemsIndexOf', '0xbbc6ec', key=key,
                                                value=(tuple(x.text for x in self.items[key]), description))
                self.item_index[key] = actual_index
                self._dependency('framework', 'SetItemIndex', '0xbbc6f6', key=key, value=actual_index)
                current = self.engine.keys[key].template.value
                if current is None:
                    raise SensorError('Native RenderDisplay dereferences the post-index current template')
                description = self._description(key, current, '0xbbc712')
                self.text[key] = description
                self._dependency('framework', 'SetText', '0xbbc729', key=key, value=description)
            self._dependency('framework', 'UpdateFunctionEnableState', '0xbbc7ba', key=key)
        finally:
            self.rendering[key] = False

    def _populate_broadcast(self):
        engine = self.engine
        self._dependency('framework', 'BroadcastItemsBeginUpdate', '0xfa8049')
        try:
            self.broadcast_items.clear()
            self._dependency('collection', 'BroadcastCollectionClear', '0xfa8062')
            for block in range(8):
                include = not (engine.graph.maintenance_active and engine.broadcast_active.value
                               and block == engine.graph.maintenance_block)
                if include:
                    for key in range(8):
                        if block not in engine.keys[key].refs:
                            continue
                        if engine._template_type(key) in (23, 24, 25) or any(engine.graph.occupancy[key].flags):
                            include = False
                            break
                if include:
                    self.broadcast_items.append(block)
                    self._dependency('collection', 'BroadcastCollectionAdd', '0xfa81a3', value=block)
        finally:
            self._dependency('framework', 'BroadcastItemsEndUpdate', '0xfa81d7')

    def finish_m8_guard(self):
        self._check()
        if not self.engine.hooks_installed:
            raise SensorError('M8 initializing flag clears only after the actual hook sequence')
        self.initializing = False

    def bind_broadcast_root(self, root):
        """Bind the actual later-created f8 object without changing combo roots."""
        self._check()
        if self.bindings.broadcast is not None:
            raise SensorError('Existing broadcast root replacement requires its owning lifetime route')
        if not isinstance(root, FunctionRoot):
            raise SensorError('Broadcast creation requires the actual collection/link object')
        self.bindings = replace(self.bindings, broadcast=root)
        self._event('broadcast_root_created', root=root.identity)

    def bind_light_frame(self, *, broadcast_items):
        """Owner binds the completed frame at its actual ST7 constructor point."""
        self._check()
        if self.light_frame:
            raise SensorError('Light frame is already bound at this lifetime position')
        if self.bindings.broadcast is None:
            raise SensorError('SENLLA light frame follows actual ST7 broadcast collection construction')
        self._validate_broadcast_items(broadcast_items)
        self.broadcast_items = list(broadcast_items)
        self.light_frame = True

    def collection_changed(self, root, choices):
        """One actual Clear/Add event's CURRENT contents and listener delivery.

        The owner must deliver list_changed at each actual native callback
        position. A key-index loop cannot reconstruct current subscriber
        ordering after root rebinding and other listeners. This is not a
        final-contents replacement for LoadFromCollection's multiple events.
        """
        if not any(root is value for value in
                   (self.bindings.primary, self.bindings.secondary, self.bindings.broadcast)):
            raise SensorError('Collection notification requires an actual bound function root')
        values = FunctionRoot._validate(choices)
        known = {x.template: x.text for other in
                 (self.bindings.primary, self.bindings.secondary, self.bindings.broadcast)
                 if other is not None and other is not root for x in other.choices}
        if any(x.template in known and not _text_equal(known[x.template], x.text) for x in values):
            raise SensorError('Canonical template descriptions cannot diverge between roots')
        def execute():
            root._choices = values
            self._dependency('collection', 'DeliverFunctionListNotifications', '0xbbc108', value=root.identity)
        return self._run(execute)

    def list_changed(self, key, root):
        """One owner-issued actual list/root controller callback."""
        key = _index(key)
        def execute():
            if self.roots[key] is not root:
                raise SensorError('List notification requires the actual CURRENT bound root')
            self.dirty[key] = True
            self._dependency('framework', 'UpdateFunctionEnableState', '0xbbc108', key=key)
        return self._run(execute)

    def post_combo_change(self, key):
        """Owner calls this at actual DoIndexChange's post-setter position.

        It does not invent a manual selection, a posted message drain, or the
        source BeforeChange/CanChange setter execution that preceded posting.
        """
        key = _index(key)
        def execute():
            self.deferred.append(key)
            self._dependency('scheduler', 'PostWM0x426', '0xbbbfdf', key=key)
        return self._run(execute)

    def deliver_combo_change(self, key):
        """Explicit owner-issued native delivery, never an inferred queue order."""
        key = _index(key)
        def execute():
            if key not in self.deferred:
                raise SensorError('Deferred combo delivery requires an actual pending owner-issued message')
            self.deferred.remove(key)
            self._dependency('callback', 'HandleComboChange', '0xbbc158', key=key)
        return self._run(execute)

    def snapshot(self):
        return dict(failed=self.failed, initializing=self.initializing,
                    roots=[None if x is None else x.identity for x in self.roots],
                    dirty=list(self.dirty), items=[[dict(template=x.template, text=x.text) for x in row]
                                                 for row in self.items],
                    item_index=list(self.item_index), text=list(self.text),
                    group_text=list(self.group_text), extension_visible=list(self.extension_visible),
                    subset_name=list(self.subset_name), allow_other_keys=list(self.allow_other_keys),
                    broadcast_items=None if self.broadcast_items is None else list(self.broadcast_items),
                    deferred=list(self.deferred))
