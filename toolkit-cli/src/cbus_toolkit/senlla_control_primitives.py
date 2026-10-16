"""Source-backed, persistent programmatic FlashCx control primitives.

This module supplies the normal unmasked Proflat control path. It owns actual
lookup keys, Text/EditValue, item update counters, controller bindings and
source-ordered collection delivery. Windows linguistic comparison is executed
by Windows itself; another host refuses a comparison it cannot establish.
"""
from dataclasses import dataclass, field
import ctypes
import sys

from .senlla_key_controls import (
    ComboState, ControlBindings, ControlDependency, ControlDependencyRequired,
    FunctionChoice, FunctionRoot, SENLLAKeyControls, _text_equal,
)
from .senlla_key_events import SENLLAKeyEvents
from .senlla_lifecycle import FlashObject
from .sensors import SensorError


SENLLA_FUNCTIONS = (16, *range(14), 34, *range(17, 25), 26)
NO_OCCUPANCY_FUNCTIONS = (16, *range(14), *range(17, 23), 26)


def no_occupancy_functions(application):
    if type(application) is not int or not 0 <= application <= 255:
        raise SensorError('No-occupancy subset requires CURRENT primary application address')
    if application == 255:
        return (16,)
    if application == 202:
        return (16, *range(16), *range(17, 23), 26)
    return NO_OCCUPANCY_FUNCTIONS


def _units(value):
    return value.encode('utf-16-le', 'surrogatepass')


def _prefix(value, count):
    return _units(value)[:count * 2].decode('utf-16-le', 'surrogatepass')


@dataclass(frozen=True)
class NativeTextRequest:
    operation: str
    first: str
    second: str | None = None
    source: str = '0x618cb0'


class NativeTextRequired(SensorError):
    def __init__(self, request):
        self.request = request
        super().__init__(f'Windows text primitive required: {request.operation}')


class WindowsTextPrimitives:
    """Actual CompareStringW and CharUpperBuffW; no host-locale substitution."""
    def __init__(self):
        if sys.platform != 'win32':
            raise SensorError('Windows text primitives require Windows')
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel.CompareStringW.argtypes = (
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_int,
        )
        self.kernel.CompareStringW.restype = ctypes.c_int
        self.user.CharUpperBuffW.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        self.user.CharUpperBuffW.restype = ctypes.c_uint32

    @staticmethod
    def _buffer(value):
        data = value.encode('utf-16-le', 'surrogatepass')
        count = len(data) // 2
        return (ctypes.c_uint16 * (count + 1)).from_buffer_copy(data + b'\0\0'), count

    def compare_ignore_case(self, first, second):
        left, left_count = self._buffer(first)
        right, right_count = self._buffer(second)
        # Delphi returns CompareStringW's result minus CSTR_EQUAL, including
        # -2 on API failure. IndexOf tests only the resulting equality.
        return self.kernel.CompareStringW(0x400, 1, left, left_count,
                                          right, right_count) - 2

    def uppercase(self, value):
        buffer, count = self._buffer(value)
        if count:
            self.user.CharUpperBuffW(buffer, count)
        return bytes(buffer)[:count * 2].decode('utf-16-le', 'surrogatepass')


class NativeText:
    """Execute each source NLS call, including identical or empty strings."""
    def __init__(self, windows=None):
        if windows is not None and not isinstance(windows, WindowsTextPrimitives):
            raise SensorError('NLS authority requires actual WindowsTextPrimitives')
        self.windows = windows
        if self.windows is None and sys.platform == 'win32':
            self.windows = WindowsTextPrimitives()
        self.requests = []

    def compare(self, first, second):
        request = NativeTextRequest('CompareStringW', first, second)
        self.requests.append(request)
        if self.windows is None:
            raise NativeTextRequired(request)
        return self.windows.compare_ignore_case(first, second)

    def equal_uppercase(self, first, second):
        if _text_equal(first, second):
            return True
        # CharUpperBuffW transforms the supplied buffer in place; it cannot
        # change the number of UTF-16 units. Unequal lengths cannot be equal.
        if len(_units(first)) != len(_units(second)):
            return False
        request = NativeTextRequest('CharUpperBuffW', first, second, '0x8dd450')
        self.requests.append(request)
        if self.windows is None:
            raise NativeTextRequired(request)
        return _text_equal(self.windows.uppercase(first), self.windows.uppercase(second))

    def index_of(self, items, text):
        count = len(items)
        for index in range(count):
            if self.compare(items[index], text) == 0:
                return index
        return -1

    def sorted_indices(self, labels):
        """TStringList.QuickSort, including its moving midpoint index."""
        rows = list(enumerate(labels))
        def sort(left, right):
            while left < right:
                low, high, pivot = left, right, (left + right) // 2
                while low <= high:
                    while self.compare(rows[low][1], rows[pivot][1]) < 0:
                        low += 1
                    while self.compare(rows[high][1], rows[pivot][1]) > 0:
                        high -= 1
                    if low <= high:
                        if low != high:
                            rows[low], rows[high] = rows[high], rows[low]
                        if low == pivot:
                            pivot = high
                        elif high == pivot:
                            pivot = low
                        low += 1
                        high -= 1
                if left < high:
                    sort(left, high)
                left = low
        if len(rows) > 1:
            sort(0, len(rows) - 1)
        return tuple(index for index, _ in rows)


@dataclass(frozen=True)
class SourceDisplayPreferences:
    use_address: bool
    use_hex: bool

    def __post_init__(self):
        if type(self.use_address) is not bool or type(self.use_hex) is not bool:
            raise SensorError('Source display preferences require actual Booleans')

    def address(self, value):
        if type(value) is not int or not 0 <= value <= 255:
            raise SensorError('Source simple address requires byte 0..255')
        decimal = f'{value:03d}'
        # Delphi Format's x conversion uses uppercase hexadecimal digits.
        return f'{decimal} ({value:02X}h)' if self.use_address and self.use_hex else decimal

    def object_text(self, kind, *, address, tag_name, level_extended=False):
        if kind not in ('application', 'group', 'level') or not isinstance(tag_name, str):
            raise SensorError('Display requires an actual supported object and current TagName')
        self.address(address)
        if type(level_extended) is not bool:
            raise SensorError('Level display flag requires its actual Boolean')
        extended = ((kind != 'level' and address != 255)
                    or (kind == 'level' and level_extended))
        if extended and self.use_address:
            return self.address(address) + ' - ' + tag_name
        return tag_name

    @staticmethod
    def block_text(index, group_text):
        if type(index) is not int or not 0 <= index < 8 or not isinstance(group_text, str):
            raise SensorError('Input block text requires current ordinal and current group text')
        return f'{index + 1} : {group_text}'

    @staticmethod
    def scene_text(index):
        if type(index) is not int or not 0 <= index < 8:
            raise SensorError('Neo Scene text requires current ordinal 0..7')
        return f'Scene {index + 1}'


@dataclass(frozen=True)
class SourceControlStrings:
    """Actual source resource/catalog strings, never completed control state.

    Templates are source object Description values. The source English
    catalogue or another actual loaded resource catalogue must supply them;
    a translated/constructed string is not an inferred native description.
    """
    descriptions: tuple[FunctionChoice, ...]
    group_nil: str
    group_multiple: str
    group_modify: str
    modify_display: str

    def __post_init__(self):
        values = FunctionRoot._validate(self.descriptions)
        if not set(SENLLA_FUNCTIONS).issubset({item.template for item in values}):
            raise SensorError('Source descriptions must include the complete SENLLA subset')
        if any(not isinstance(value, str) for value in
               (self.group_nil, self.group_multiple, self.group_modify, self.modify_display)):
            raise SensorError('Source group representations require actual resource strings')
        object.__setattr__(self, 'descriptions', values)

    def description(self, template):
        for choice in self.descriptions:
            if choice.template == template:
                return choice.text
        raise SensorError('Current template description is absent from the actual source catalogue')

    def choices(self, templates):
        return tuple(FunctionChoice(template, self.description(template)) for template in templates)


@dataclass(frozen=True)
class SourceObjectChoice:
    """An actual manager object and its CURRENT source display string."""
    native: object
    text: str

    def __post_init__(self):
        if (self.native is None or not hasattr(self.native, 'publisher')
                or not hasattr(self.native, 'identity') or not isinstance(self.text, str)):
            raise SensorError('Source choice requires canonical managed object and current text')


@dataclass(frozen=True)
class SourceObjectCollection:
    """Lazy CURRENT canonical manager reads; no Text/index/control outcomes.

    get_item executes the object's actual ToString at that source ordinal.
    describe executes CURRENT ToString for the supplied object, including an
    object absent from the current list. collection is the actual managed
    collection pointer, or actual nil; get_count/get_item reread its contents.
    get_object rereads the pointer without executing an extra ToString.
    """
    collection: object | None
    get_count: object
    get_item: object
    describe: object
    get_object: object

    def __post_init__(self):
        if self.collection is not None and not hasattr(self.collection, 'publisher'):
            raise SensorError('Object collection requires its actual managed identity')
        if any(not callable(value) for value in
               (self.get_count, self.get_item, self.describe, self.get_object)):
            raise SensorError('Object collection requires causal count/item/description reads')

    def count(self):
        if self.collection is not None:
            self.collection.resolve_change()
        count = self.get_count()
        if type(count) is not int or count < 0 or (self.collection is None and count != 0):
            raise SensorError('Source collection count is invalid')
        return count

    def item(self, index):
        row = self.get_item(index)
        if type(row) is not SourceObjectChoice:
            raise SensorError('Source ordinal requires canonical object and actual ToString')
        row.native.resolve_change()
        return row

    def text(self, native):
        value = self.describe(native)
        if not isinstance(value, str):
            raise SensorError('Source ToString requires actual text')
        native.resolve_change()
        return value

    def object(self, index):
        value = self.get_object(index)
        if value is None or not hasattr(value, 'publisher'):
            raise SensorError('Source ordinal requires its actual canonical object pointer')
        return value


@dataclass
class _ObjectBinding:
    key: int
    kind: str
    combo: object
    bound: bool = False
    collection: object | None = None
    current: object | None = None
    index_map: tuple[int, ...] = ()
    rendering: bool = False
    scalar_receiver: object = None
    target_receiver: object = None
    list_receiver: object = None
    path_receiver: object = None


class ProgrammaticCollection(FlashObject):
    """Actual standalone reference-array identity for the light-frame list.

    InternalClear deletes rows descending, including each Changed call; an
    empty clear emits none. Begin/End retain managed depth suppression and
    native End's publication even when the supplied rows were unchanged.
    """
    def __init__(self, name, rows=()):
        super().__init__(name)
        self.items = list(rows)

    def clear(self):
        while self.items:
            self.items.pop()
            self.changed()

    def append(self, value):
        if value is None:
            raise SensorError('Native reference collection rejects nil append')
        self.items.append(value)
        self.changed()


@dataclass
class ProgrammaticCombo:
    """One actual fresh, unmasked, unfocused lsEditFixedList control."""
    identity: str
    text_authority: NativeText
    nil_text: str = ''
    items: list = field(default_factory=list)
    item_index: int = -1
    display_index: int = -1
    text: str = ''
    edit_value: str | None = None
    edit_value_kind: str = 'empty'
    update_depth: int = 0
    click_depth: int = 0
    modified: bool = False
    selection: tuple[int, int] = (0, 0)
    invalidated: bool = False
    visible: bool = True
    enabled: bool = True
    list_active: bool = True
    scalar_active: bool = True
    dirty: bool = True
    drop_down_style: int = 1
    property_on_change: object = None
    events: list = field(default_factory=list)

    def __post_init__(self):
        if self.property_on_change is not None and not callable(self.property_on_change):
            raise SensorError('Properties.OnChange requires its actual synchronous handler')

    def _event(self, operation, **values):
        self.events.append(dict(operation=operation, **values))

    def begin_items(self):
        self.update_depth += 1
        self._event('items_begin', depth=self.update_depth)

    def end_items(self):
        if self.update_depth <= 0:
            raise SensorError('Source TStringList EndUpdate requires an open update')
        self.update_depth -= 1
        self._event('items_end', depth=self.update_depth)
        if self.update_depth == 0:
            self._items_changed()

    def _items_changed(self):
        # Actual fresh lookup popup/list-area pointer is nil. PropertiesChanged
        # invokes ListChanged, whose visual-area guard returns; no index edit.
        self._event('lookup_properties_changed', popup=None)

    def clear_items(self):
        self.items.clear()
        self._event('items_clear')
        if not self.update_depth:
            self._items_changed()

    def add_item(self, identity, text):
        if not isinstance(text, str):
            raise SensorError('Lookup item requires actual display text')
        self.items.append((identity, text))
        self._event('items_add', ordinal=len(self.items) - 1)
        if not self.update_depth:
            self._items_changed()

    def set_index(self, requested):
        if type(requested) is not int:
            raise SensorError('Programmatic item index requires integer')
        old = self.item_index
        self.click_depth += 1
        try:
            # LookupData.SetCurrentKey ignores values outside [-1, Count-1].
            if -1 <= requested < len(self.items):
                self.item_index = requested
                self.display_index = requested
            label = self.items[self.item_index][1] if 0 <= self.item_index < len(self.items) else ''
            if self.edit_value is None or not _text_equal(self.edit_value, label):
                self.edit_value = label
                self.edit_value_kind = 'string'
                self._write_inner_text(label)
                self.modified = False
                self._event('edit_value_changed', value=label)
            self._event('item_index', requested=requested, actual=self.item_index)
        finally:
            self.click_depth -= 1
        if self.item_index != old:
            self.modified = False
            # Dynamic -20 Click follows unlock. Fresh OnClick/action and
            # Properties.OnChange/OnEditValueChanged are nil; no DoIndexChange.
            if self.click_depth:
                self._event('click_lock_guard', depth=self.click_depth)
            else:
                self._event('click', on_click=None, action=None)

    def set_text(self, value):
        if not isinstance(value, str):
            raise SensorError('Programmatic Text requires actual text')
        if _text_equal(self.text, value):
            self._event('text_equal_no_set')
            return
        # Updated, previously unbound ordinary group controls use style0.
        # Its editing-style1 validator accepts empty text or a complete label.
        if self.drop_down_style == 0 and value:
            if not any(self.text_authority.equal_uppercase(value, label)
                       for _, label in self.items):
                self._event('display_validation_refused', value=value)
                return
        self._commit_text(value)

    def _commit_text(self, value):
        """InnerDisplayValue followed by its unmasked TextChanged route."""
        self._write_inner_text(value)
        # InternalSetDisplayValue synchronizes EditValue only AFTER the inner
        # Change callback, using CURRENT inner text, including nested edits.
        self.edit_value = self.text
        self.edit_value_kind = 'string'
        self.modified = False

    def _write_inner_text(self, value):
        if _text_equal(self.text, value):
            return
        self.text = value
        self._event('text', value=value)
        # The fresh single-line, no-HWND inner control's SetTextBuf sends
        # WM_SETTEXT then CM_TEXTCHANGED. TCustomEdit.CMTextChanged explicitly
        # invokes Change when no handle exists. Combo.ChangeHandler coalesces
        # its inherited Change calls, updates lookup data, then invokes the
        # installed Properties.OnChange before the outer setter resumes.
        self._lookup_text_changed()
        if self.property_on_change is not None:
            self._event('property_on_change', click_depth=self.click_depth,
                        index=self.item_index, edit_value_kind=self.edit_value_kind)
            self.property_on_change(self)

    def _lookup_text_changed(self):
        value = self.text
        # Fresh raw style1 maps to editing style0; string display validation
        # and empty-mask PrepareEditValue preserve the supplied value.
        current = self.items[self.display_index][1] if 0 <= self.display_index < len(self.items) else ''
        if self.display_index < len(self.items) and self.text_authority.equal_uppercase(value, current):
            return
        # Fresh LookupItemsSorted+c0 is false. InternalLocate scans prefixes
        # from ordinal0; text length counts UTF-16 units, including surrogates.
        found = -1
        if value:
            length = len(_units(value)) // 2
            for index, (_, label) in enumerate(self.items):
                if self.text_authority.equal_uppercase(value, _prefix(label, length)):
                    found = index
                    break
        self.item_index = self.display_index = found

    def replace_empty_selection(self, value):
        """Source Clear(null) then unmasked SetSelText with display validation."""
        # Clear uses SetEditValue under LockClick. In the unfocused profile,
        # its inner Change still updates the lookup key before its callback.
        # SetSelText then writes InnerDisplayValue
        # directly after CanChangeSelText's display validation. Its inner write
        # bypasses Control.SetText's equality guard.
        self.click_depth += 1
        try:
            self.edit_value, self.edit_value_kind = None, 'null'
            self._write_inner_text('')
            self.modified = False
        finally:
            self.click_depth -= 1
        if self.drop_down_style == 0 and value:
            if not any(self.text_authority.equal_uppercase(value, label)
                       for _, label in self.items):
                self._event('selection_validation_refused', value=value)
                return
        self._commit_text(value)
        self.selection = (len(_units(self.text)) // 2, 0)
        self._event('clear_then_set_sel_text', value=value)

    def state(self):
        return dict(identity=self.identity, item_index=self.item_index,
                    display_index=self.display_index, text=self.text,
                    edit_value=self.edit_value, update_depth=self.update_depth,
                    edit_value_kind=self.edit_value_kind,
                    click_depth=self.click_depth, modified=self.modified,
                    selection=list(self.selection), invalidated=self.invalidated,
                    visible=self.visible, enabled=self.enabled,
                    list_active=self.list_active, scalar_active=self.scalar_active,
                    dirty=self.dirty, drop_down_style=self.drop_down_style,
                    items=[dict(identity=x, text=y) for x, y in self.items])


class PersistentControlPrimitives:
    """Source-owned primitive executor for one live SENLLA key/control graph.

    initial_controls executes the source per-key function binding phase. It
    replaces the isolated engine fresh_function_bindings phase, then returns
    the same persistent general-control kernel for install_m8_hooks.
    """
    def __init__(self, strings, *, text=None, group_objects=None):
        if type(strings) is not SourceControlStrings:
            raise SensorError('Primitive provider requires actual source control strings')
        if text is not None and type(text) is not NativeText:
            raise SensorError('Primitive provider requires NativeText authority')
        if group_objects is not None and not callable(group_objects):
            raise SensorError('Group reads require a live source object adapter')
        self.strings = strings
        self.text = NativeText() if text is None else text
        self.group_objects = group_objects
        self.controls = None
        self.engine = None
        self.combos = [ProgrammaticCombo(f'cmbKey{key + 1}MacroFunction', self.text) for key in range(8)]
        self.groups = [ProgrammaticCombo(f'cmbKey{key + 1}Group', self.text) for key in range(8)]
        self.scene_visible = [False] * 8
        self.scenes = [None] * 8
        self._roots = {}
        self._link_followers = {}
        self._handle_followers = {}
        self._list_active = [True] * 8
        self._bound_roots = [None] * 8
        self._object_bindings = {(key, 'group'): _ObjectBinding(key, 'group', combo)
                                 for key, combo in enumerate(self.groups)}
        self._object_list_order = []
        self._key_followers = [[] for _ in range(8)]
        self._key_link_receivers = []
        self._unit_link_receiver = None
        self.events = []
        self.pending = []
        self.broadcast_depth = 0
        self.broadcast_collection = None

    def _event(self, operation, **values):
        self.events.append(dict(operation=operation, **values))

    def initial_controls(self, engine):
        if self.engine is not None or not isinstance(engine, SENLLAKeyEvents):
            raise SensorError('Initial controls bind once to the actual key owner')
        if engine.phase != 'fresh_function_bindings' or engine.hooks_installed or engine.failed:
            raise SensorError('Initial controls require the actual fresh function-binding phase')
        primary = FunctionRoot('director.primary_functions', self.strings.choices(SENLLA_FUNCTIONS))
        secondary = FunctionRoot('director.secondary_functions', self.strings.choices(SENLLA_FUNCTIONS))
        self._roots = {root.identity: root for root in (primary, secondary)}
        bindings = ControlBindings(primary, secondary, None, self.strings.group_nil,
                                   self.strings.group_multiple, self.strings.group_modify)
        controls = SENLLAKeyControls(
            bindings, roots=[None] * 8,
            combo_states=[ComboState((), -1, '', True) for _ in range(8)],
            group_text=[self.strings.group_nil] * 8, extension_visible=[True] * 8,
            subset_names=[''] * 8, allow_other_keys=[False, False], dependency_executor=self,
        )
        self.engine, self.controls = engine, controls
        # New owning bootstrap executes the native binding phase before the
        # frozen kernel's later M8-entry boundary. Bind its actual owner now;
        # register each scalar observer at its own native ordinal below.
        controls.engine = engine
        try:
            # Fixed source RootKeyLinks exist before Group/Function bindings.
            # Their value notification visits controller followers in actual
            # binding order. Parsed scalar members separately watch the final
            # reference ATTRIBUTE, so publication at parentdepth1 is visible.
            for key, owner in enumerate(engine.keys):
                receiver = lambda _, key=key: self._root_key_changed(key)
                self._key_link_receivers.append(receiver)
                owner.object.publisher.subscribe(receiver)
            self._unit_link_receiver = lambda _: self._root_unit_changed()
            engine.unit.publisher.subscribe(self._unit_link_receiver)
            for key in range(8):
                self._initial_group(key)
            controls.group_text[:] = [combo.nil_text for combo in self.groups]
            for key, owner in enumerate(engine.keys):
                state = owner.application_state.value
                root = primary if state == 0 else secondary
                controls._set_root(key, root, '0xf95c3f')
                if owner.template.value is not None:
                    found = False
                    for choice in root.choices:
                        if engine.templates[choice.template] is owner.template.value:
                            found = True
                    if not found:
                        engine.set_template(key, 16)
                receiver = lambda _, key=key: controls._scalar_changed(key)
                target_receiver = lambda _, key=key: controls._run(lambda: controls._render(key))
                controls._receivers.append(receiver)
                controls._target_receivers.append(target_receiver)
                owner.template.publisher.subscribe(receiver)
                self._key_followers[key].append(('function', key))
                self._event('scalar_bound', key=key)
                controls._scalar_changed(key)
            engine.phase = 'm8_hooks'
            controls._event('source_initial_binding_complete')
        except Exception:
            controls.failed = engine.failed = True
            raise
        return controls

    def _initial_group(self, key):
        template = self.engine._template_type(key)
        group = self.groups[key]
        if template in (23, 24):
            group.visible = False
            self.scene_visible[key] = True
            self.scenes[key] = ProgrammaticCombo(f'cmbKey{key + 1}Scene', self.text,
                                                 drop_down_style=0)
            self._object_bindings[key, 'scene'] = _ObjectBinding(key, 'scene', self.scenes[key])
            self._event('initial_scene_binding', key=key)
            self._prepare_object(key, 'scene', initial=True)
        elif template == 25:
            group.replace_empty_selection(self.strings.modify_display)
            group.enabled = group.list_active = group.scalar_active = False
            self._event('initial_modify_group', key=key)
        else:
            self._prepare_object(key, 'group', initial=True)

    def _objects(self, binding):
        if self.group_objects is None:
            raise ControlDependencyRequired(ControlDependency(
                'source_objects', 'ReadCurrentGroupObjects', '0xc103a4', binding.key, binding.kind))
        value = self.group_objects(self.engine, binding.key, binding.kind)
        if type(value) is not SourceObjectCollection:
            raise SensorError('Object adapter must return lazy CURRENT canonical reads')
        return value

    def _object_current(self, binding):
        if not binding.bound:
            return None
        owner = self.engine.keys[binding.key]
        return owner.scene.value if binding.kind == 'scene' else owner.primary_group.value

    def _prepare_object(self, key, kind, *, initial=False):
        binding = self._object_bindings[key, kind]
        if binding.bound:
            return
        combo, owner = binding.combo, self.engine.keys[key]
        combo.list_active = combo.scalar_active = False
        combo.nil_text = self.strings.group_nil if kind == 'group' or initial else ''
        binding.bound = True
        self._object_list_order.append(binding)
        self._key_followers[key].append(('object', binding))
        binding.list_receiver = lambda _: self.controls._run(lambda: self._object_list_changed(binding))
        binding.scalar_receiver = lambda _: self.controls._run(lambda: self._object_scalar_changed(binding))
        binding.target_receiver = lambda _: self.controls._run(lambda: self._render_object(binding))
        binding.path_receiver = lambda _: self.controls._run(lambda: self._object_path_changed(binding))
        if kind == 'group':
            owner.application.publisher.subscribe(binding.path_receiver)
            owner.primary_group.publisher.subscribe(binding.scalar_receiver)
        else:
            owner._scene.publisher.subscribe(binding.scalar_receiver)
        combo.list_active = True
        self._object_path_changed(binding)
        self._object_list_changed(binding)
        combo.scalar_active = True
        self._object_scalar_changed(binding)
        combo.drop_down_style = 1 if kind == 'group' and initial else 0
        # PrepareGroup has a final RenderDisplay. PrepareActionLevel omits it;
        # an initially nil Scene keeps its original Text until a value event.
        if kind == 'group':
            self._display_object(binding)
        self._event('object_prepared', key=key, kind=kind, initial=initial)

    def _object_path_changed(self, binding):
        if not binding.bound:
            return
        context = self._objects(binding)
        if binding.collection is context.collection:
            return
        if binding.collection is not None:
            binding.collection.publisher.unsubscribe(binding.list_receiver)
        binding.collection = context.collection
        if binding.collection is not None:
            binding.collection.publisher.subscribe(binding.list_receiver)
        self._object_list_changed(binding)

    def _object_list_changed(self, binding):
        if not binding.combo.list_active:
            return
        if not binding.bound:
            binding.index_map = ()
            binding.combo.dirty = True
            return
        context = self._objects(binding)
        count = context.count()
        # Tracked.IndexList always caches CURRENT descriptions in source row
        # order before TStringList.Sort. Scene controller Sort=true; ordinary
        # group Sort=false keeps the actual GroupManager order.
        labels = tuple(context.item(index).text for index in range(count))
        if binding.kind == 'scene':
            binding.index_map = self.text.sorted_indices(labels)
        else:
            binding.index_map = tuple(range(count))
        binding.combo.dirty = True
        self._event('object_list_dirty', key=binding.key, kind=binding.kind, count=count)

    def _object_scalar_changed(self, binding):
        if not binding.combo.scalar_active:
            return
        current = self._object_current(binding)
        previous = binding.current
        if previous is current:
            return
        if previous is not None:
            previous.publisher.unsubscribe(binding.target_receiver)
        binding.current = current
        if current is not None:
            current.publisher.subscribe(binding.target_receiver)
        self._event('object_current_changed', key=binding.key, kind=binding.kind,
                    parent_depth=self.engine.keys[binding.key].object.depth)
        self._render_object(binding)

    def _root_key_changed(self, key):
        def execute():
            followers = self._key_followers[key]
            count = len(followers)
            for ordinal in range(count):
                if ordinal >= len(followers):
                    raise SensorError('Native RootKeyLink follower index disappeared')
                kind, value = followers[ordinal]
                self._event('root_key_delivery', key=key, ordinal=ordinal, kind=kind)
                if kind == 'object':
                    self._object_scalar_changed(value)
                else:
                    self.controls._scalar_changed(value)
        return self.controls._run(execute)

    def _root_unit_changed(self):
        def execute():
            count = len(self._object_list_order)
            for ordinal in range(count):
                if ordinal >= len(self._object_list_order):
                    raise SensorError('Native RootUnitLink follower index disappeared')
                binding = self._object_list_order[ordinal]
                self._object_path_changed(binding)
                self._object_list_changed(binding)
        return self.controls._run(execute)

    def _display_object(self, binding):
        combo = binding.combo
        current = self._object_current(binding)
        if current is None:
            combo.set_text(combo.nil_text)
            return
        text = self._objects(binding).text(current)
        combo.set_index(self.text.index_of(tuple(label for _, label in combo.items), text))
        current = self._object_current(binding)
        if current is None:
            raise SensorError('Native RenderDisplay dereferences post-index nil object')
        combo.set_text(self._objects(binding).text(current))

    def _render_object(self, binding):
        combo = binding.combo
        if binding.rendering or not combo.scalar_active:
            return
        binding.rendering = True
        try:
            previous_text = combo.text
            combo.list_active = False
            combo.list_active = True
            self._object_list_changed(binding)
            combo.begin_items()
            try:
                combo.set_index(-1)
                combo.clear_items()
                count = len(binding.index_map)
                for ordinal in range(count):
                    item = self._objects(binding).item(binding.index_map[ordinal])
                    combo.add_item(item.native.identity, item.text)
                    # Source rereads CURRENT tracked ordinal and scalar after
                    # actual Items.AddObject, rather than capturing selected.
                    selected = self._objects(binding).object(binding.index_map[ordinal])
                    if selected is self._object_current(binding):
                        combo.set_index(len(combo.items) - 1)
                if self._object_current(binding) is None:
                    combo.set_text(combo.nil_text)
                elif not combo.text:
                    combo.set_text(previous_text)
            finally:
                combo.end_items()
            combo.selection = (0, len(combo.text.encode('utf-16-le', 'surrogatepass')) // 2)
            self._display_object(binding)
            combo.dirty = False
            combo.invalidated = True
        finally:
            binding.rendering = False

    def _sync(self, key):
        combo = self.combos[key]
        controls = self.controls
        controls.item_index[key] = combo.item_index
        controls.text[key] = combo.text
        combo.dirty = controls.dirty[key]

    def _followers(self, root):
        identity = None if root is None else root.identity
        return (self._link_followers.setdefault(identity, []),
                self._handle_followers.setdefault(identity, []))

    def _root_changed(self, key):
        root = self.controls.roots[key]
        old = self._bound_roots[key]
        if old is root:
            return
        for followers in self._followers(old):
            if key in followers:
                followers.remove(key)
        self._bound_roots[key] = root
        for followers in self._followers(root):
            if key not in followers:
                followers.append(key)
        if self._list_active[key] and root is not None:
            self.controls.list_changed(key, root)

    def _deliver_collection(self, root):
        # The source root handle rebuilds its IndexList before either follower
        # pass. Even unsorted function roots execute every template ToString.
        count = len(root.choices)
        for ordinal in range(count):
            if ordinal >= len(root.choices):
                raise SensorError('Native function IndexList ordinal disappeared')
            self.engine.templates[root.choices[ordinal].template].resolve_change()
        # Native root-handle DoListChanged first calls its own FlashLink event,
        # which iterates Link followers. It then iterates handle followers.
        # Both loops capture Count and read CURRENT index after callbacks.
        for route, followers in zip(('link', 'handle'), self._followers(root)):
            count = len(followers)
            for ordinal in range(count):
                if ordinal >= len(followers):
                    raise SensorError('Native collection follower index disappeared')
                key = followers[ordinal]
                if self._list_active[key]:
                    self._event('list_delivery', route=route, key=key, ordinal=ordinal)
                    self.controls.list_changed(key, self.controls.roots[key])

    def load_function_root(self, root, templates):
        if self.controls is None or self.engine.failed:
            raise SensorError('Function collection load requires live controls')
        if not any(root is value for value in self._roots.values()):
            raise SensorError('Function collection requires its actual persistent source root')
        if not isinstance(templates, (list, tuple)) or any(type(x) is not int for x in templates):
            raise SensorError('Function collection load requires ordered canonical template numbers')
        choices = self.strings.choices(templates)
        # InternalClear removes original rows descending; its GUI expression
        # lock does not suppress tracked root-array list notifications.
        self._event('gui_expression_lock', locked=True)
        try:
            while root.choices:
                self.controls.collection_changed(root, root.choices[:-1])
        finally:
            self._event('gui_expression_lock', locked=False)
        for choice in choices:
            self.controls.collection_changed(root, (*root.choices, choice))

    def create_broadcast_root(self):
        if self.controls is None or self.controls.bindings.broadcast is not None:
            raise SensorError('Broadcast root is created once after actual M8 initialization')
        if not self.engine.hooks_installed:
            raise SensorError('ST7 broadcast collection follows M8 hook installation')
        root = FunctionRoot('director.broadcast_functions', ())
        self._roots[root.identity] = root
        self.controls.bind_broadcast_root(root)
        primary = self.engine.application_object(False)
        if primary is not None:
            self.load_function_root(root, no_occupancy_functions(primary.identity))
        return root

    def bind_light_frame(self, *, broadcast_items):
        """Own the actual source collection at the later frame binding point."""
        self.controls.bind_light_frame(broadcast_items=broadcast_items)
        self.broadcast_collection = ProgrammaticCollection('frame.broadcast_blocks',
                    (self.engine.blocks[index].object for index in broadcast_items))
        return self.broadcast_collection

    def __call__(self, request, engine):
        if type(request) is not ControlDependency or engine is not self.engine or self.controls is None:
            raise SensorError('Primitive requires its actual control request and live owner')
        key, operation = request.key, request.operation
        combo = None if key is None else self.combos[key]
        self._event('primitive', primitive=operation, key=key, source=request.source)
        if operation == 'SetFunctionListRoot':
            self._root_changed(key)
        elif operation == 'SetListControllerActive':
            self._list_active[key] = combo.list_active = request.value
            if request.value and self.controls.roots[key] is not None:
                self.controls.list_changed(key, self.controls.roots[key])
        elif operation == 'DeliverFunctionListNotifications':
            self._deliver_collection(self._roots[request.value])
        elif operation == 'ItemsBeginUpdate':
            combo.begin_items()
        elif operation == 'ItemsEndUpdate':
            combo.end_items()
        elif operation == 'ItemsClear':
            combo.clear_items()
        elif operation == 'ItemsAddObject':
            template, label, _ = request.value
            self.engine.templates[template].resolve_change()
            combo.add_item(template, label)
        elif operation == 'SetItemIndex':
            combo.set_index(request.value)
        elif operation == 'SetText':
            current = self.engine.keys[key].template.value
            if current is not None:
                current.resolve_change()
            combo.set_text(request.value)
        elif operation == 'FinalizePopulateText':
            current = self.engine.keys[key].template.value
            if current is None:
                combo.set_text(combo.nil_text)
            elif not combo.text:
                combo.set_text(request.value)
        elif operation == 'RenderNilFunctionText':
            combo.set_text(combo.nil_text)
        elif operation == 'ItemsIndexOf':
            current = self.engine.keys[key].template.value
            if current is not None:
                current.resolve_change()
            return self.text.index_of(request.value[0], request.value[1])
        elif operation == 'DescribeCurrentTemplate':
            current = self.engine.keys[key].template.value
            if current is None:
                raise SensorError('Native current template description dereferences nil')
            current.resolve_change()
            return self.strings.description(self.engine._template_type(key))
        elif operation == 'SelectAll':
            combo.selection = (0, len(combo.text.encode('utf-16-le', 'surrogatepass')) // 2)
        elif operation == 'InvalidateFunctionControl':
            combo.invalidated = True
        elif operation == 'UpdateFunctionEnableState':
            # Constructor AutoEnable=false. Native guard returns before any
            # Enabled assignment, model setter or additional controller read.
            self._event('auto_enable_guard', key=key, auto_enable=False)
        elif operation == 'SetGroupNilRepresentation':
            group = self.groups[key]
            old = group.nil_text
            group.nil_text = request.value
            # SetNilRepresentation invokes DoFlashHandleChanged only when
            # text differs AND the controller's CURRENT scalar pointer is nil.
            binding = self._object_bindings[key, 'group']
            if not _text_equal(old, request.value) and self._object_current(binding) is None:
                self._render_object(binding)
        elif operation == 'SetExtensionVisible':
            self._event('extension_visibility', key=key, visible=request.value)
        elif operation == 'UpdateGroupCombo':
            self._update_group(key)
        elif operation == 'SetPairedKeyBlockOverrides':
            raise ControlDependencyRequired(request)
        elif operation == 'BroadcastItemsBeginUpdate':
            if self.broadcast_collection is None:
                raise ControlDependencyRequired(request)
            self.broadcast_depth += 1
            self.broadcast_collection.begin_update()
        elif operation == 'BroadcastItemsEndUpdate':
            if self.broadcast_depth <= 0:
                raise SensorError('Broadcast EndUpdate requires actual open update')
            self.broadcast_depth -= 1
            self.broadcast_collection.end_update()
        elif operation == 'BroadcastCollectionClear':
            if self.broadcast_collection is None:
                raise ControlDependencyRequired(request)
            self.broadcast_collection.clear()
        elif operation == 'BroadcastCollectionAdd':
            if self.broadcast_collection is None:
                raise ControlDependencyRequired(request)
            self.broadcast_collection.append(self.engine.blocks[request.value].object)
        elif operation == 'PostWM0x426':
            self.pending.append(key)
        elif operation == 'HandleComboChange':
            if key not in self.pending:
                raise SensorError('Native combo callback requires actual posted message')
            self.pending.remove(key)
            # Manual events require actual BeforeChange, current selector and
            # FunctionComboChange ownership; never acknowledge or auto-drain.
            raise ControlDependencyRequired(request)
        else:
            raise ControlDependencyRequired(request)
        if key is not None:
            self._sync(key)
        return None

    def _update_group(self, key):
        template = self.engine._template_type(key)
        group = self.groups[key]
        if template in (23, 24):
            previously_visible = group.visible
            group.visible = False
            self.scene_visible[key] = True
            if self.scenes[key] is None:
                self.scenes[key] = ProgrammaticCombo(f'cmbKey{key + 1}Scene', self.text,
                                                     drop_down_style=0)
                self._object_bindings[key, 'scene'] = _ObjectBinding(key, 'scene', self.scenes[key])
            self._prepare_object(key, 'scene')
            if previously_visible:
                scene_count = len(self.engine.scenes)
                for scene in range(scene_count):
                    unused = True
                    for other in range(8):
                        if other == key or self.engine._template_type(other) not in (23, 24):
                            continue
                        if self.engine.keys[other].scene.value is self.engine.scenes[scene]:
                            unused = False
                            break
                    if unused:
                        self.engine.keys[key].scene.set(self.engine.scenes[scene])
                        break
        elif template == 25:
            group.replace_empty_selection(self.strings.modify_display)
            self.scene_visible[key] = False
            group.visible, group.enabled = True, False
        else:
            self.scene_visible[key] = False
            group.visible = group.enabled = True
            self._prepare_object(key, 'group')

    def snapshot(self):
        return dict(functions=[combo.state() for combo in self.combos],
                    groups=[combo.state() for combo in self.groups],
                    scene_visible=list(self.scene_visible),
                    scenes=[None if combo is None else combo.state() for combo in self.scenes],
                    pending=list(self.pending), broadcast_depth=self.broadcast_depth,
                    broadcast_items=None if self.broadcast_collection is None else
                    [value.name for value in self.broadcast_collection.items],
                    roots={name: [choice.template for choice in root.choices]
                           for name, root in self._roots.items()}, events=list(self.events))
