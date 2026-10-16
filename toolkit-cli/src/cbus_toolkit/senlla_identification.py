"""Persistent identification name cache and source-ordered direct Exit.

The fresh DFM name-change handler reaches GetHandle/EM_GETSEL. That native
window lifetime is an explicit boundary, including when the text is valid.
This component does not pretend that a portable selection cache closes it.
"""
from copy import deepcopy

from .senlla_control_primitives import _text_equal
from .senlla_inherited_owner import SENLLAInheritedOwner, UnitStringAttribute
from .sensors import SensorError


def _units(value):
    if type(value) is not str:
        raise SensorError('Identification control requires UTF-16 text')
    raw = value.encode('utf-16le', 'surrogatepass')
    return tuple(int.from_bytes(raw[index:index + 2], 'little')
                 for index in range(0, len(raw), 2))


def cbus_name_character(unit):
    """CharIsCBusName's bounds and exclusion bitset, per UTF-16 unit."""
    if type(unit) is not int or not 0 <= unit <= 65535:
        raise SensorError('CBus name predicate requires a UTF-16 code unit')
    return 33 <= unit <= 96 and unit not in (60, 62)


def filter_cbus_name(text):
    """Pure character predicate; neither uppercase, trim nor native edit input."""
    return ''.join(chr(unit) for unit in _units(text) if cbus_name_character(unit))


class IdentificationWindowRequired(SensorError):
    def __init__(self, operation, source):
        self.operation, self.source = operation, source
        super().__init__('Identification requires the actual Windows edit ' +
                         operation + ' at ' + source)


class StringController:
    """Concrete TStringAttribute cache, renderer and umExit Apply gates.

    The expression resolves to one retained actual attribute. General root
    rebinding and reference expressions are separate controller contracts.
    """
    def __init__(self, attribute, renderer, *, events=None):
        if not isinstance(attribute, UnitStringAttribute) or not callable(renderer):
            raise SensorError('String controller requires the SAME string attribute and renderer')
        self.attribute, self.renderer = attribute, renderer
        self.events = [] if events is None else events
        self.active = False
        self.read_only = False
        self.depth = 0
        self.cache = ''
        self.dirty = False
        self._receiver = lambda _: self.refresh()
        attribute.publisher.subscribe(self._receiver)

    def _event(self, operation, **facts):
        self.events.append(dict(operation=operation, depth=self.depth, **facts))

    def set_active(self, value):
        if type(value) is not bool:
            raise SensorError('String controller Active requires a Boolean')
        self.active = value
        if value:
            # Native SetActive calls Changed even for an equal true request.
            # Changed holds an outer lock through its initial handle refresh.
            self.depth += 1
            try:
                self.refresh()
            finally:
                self.depth -= 1

    def refresh(self):
        if not self.active:
            return
        self.depth += 1
        try:
            self.dirty = False
            current = self.attribute.value
            self._event('controller_render', value=current)
            self.renderer(current)
            # The CURRENT representation is read again after the callback.
            # Cache restoration does not reset dirty a second time.
            self.cache = self.attribute.value
            self._event('controller_cache_restored', value=self.cache, dirty=self.dirty)
        finally:
            self.depth -= 1

    def get(self):
        return self.cache if self.dirty else self.attribute.value

    def set(self, value):
        _units(value)
        if self.read_only or _text_equal(self.cache, value):
            return
        self.cache, self.dirty = value, True
        self._event('controller_cache_changed', value=value)

    def apply(self):
        if self.dirty and not self.read_only and self.active and self.depth == 0:
            try:
                self._event('controller_apply', value=self.cache)
                self.attribute.set(self.cache)
            except Exception:
                self.refresh()
                raise
        self.dirty = False

    def state(self):
        return dict(active=self.active, read_only=self.read_only, depth=self.depth,
                    cache=self.cache, dirty=self.dirty, update_mode='umExit')


class ProgrammaticStringEdit:
    """Actual single-line TFlashEdit text/cache slice before HWND allocation.

    SetText compares exact UTF-16 text, then WM_SETTEXT and CM_TEXTCHANGED
    deliver Change synchronously. The source helper supplies no uppercase or
    MaxLength transformation. Those belong to the later actual edit window.
    """
    def __init__(self, attribute, *, initial_text='', on_change=None, events=None):
        _units(initial_text)
        if on_change is not None and not callable(on_change):
            raise SensorError('String edit OnChange requires its actual handler')
        self.text = initial_text
        self.on_change = on_change
        self.events = [] if events is None else events
        self.controller = StringController(attribute, self.set_text, events=self.events)

    def get_text(self):
        return self.text

    def set_text(self, value):
        _units(value)
        if _text_equal(self.get_text(), value):
            return
        self.text = value
        self.events.append(dict(operation='edit_wm_settext', value=value, hwnd=0))
        self.events.append(dict(operation='edit_cm_textchanged', hwnd=0))
        # FlashEdit.Change caches BEFORE inherited Change/OnChange.
        self.controller.set(self.get_text())
        self.events.append(dict(operation='edit_change', value=self.get_text()))
        if self.on_change is not None:
            self.on_change(self)


class SENLLAIdentificationName:
    """Same UnitName/TagName objects through binding and direct form Exit.

    This is the name position within SetupFlashComponents, not the entire
    identification form. Earlier firmware/catalog controls and application,
    area, root-link, native window and focus ownership remain uncomposed.
    """
    def __init__(self, inherited_owner, *, initial_control_text=''):
        if not isinstance(inherited_owner, SENLLAInheritedOwner):
            raise SensorError('Identification name requires its concrete inherited owner')
        self.inherited = inherited_owner
        self.runtime = inherited_owner.runtime
        self.events = []
        self.edit = ProgrammaticStringEdit(inherited_owner.unit_attribute('CBusUnitName'),
            initial_text=initial_control_text, on_change=self._name_change, events=self.events)
        self.prepared = False

    def _event(self, operation, source, **facts):
        self.events.append(dict(operation=operation, source=source, **facts))

    def _name_change(self, edit):
        if edit is not self.edit:
            raise SensorError('Name Change belongs to another actual control')
        self._event('name_change_selection_start', '0xdc162a')
        # GetSelStart first calls GetHandle, then SendMessage(EM_GETSEL).
        # A fresh no-HWND text change cannot skip this even for valid text.
        raise IdentificationWindowRequired('GetHandle_then_EM_GETSEL', '0x6855de')

    def prepare_name(self):
        """The actual dc0e42 binding position followed by direct form Exit."""
        def execute():
            if self.prepared:
                raise SensorError('Identification name binding cannot be replayed')
            self.prepared = True
            self._event('prepare_name_controller', '0xdc0e42')
            self.edit.controller.set_active(True)
            self._event('direct_name_exit', '0xdc0e4c')
            self._exit_handler()
            return self
        return self.runtime._run(execute)

    def _exit_handler(self):
        # Native Exit captures only the original length. It rereads Text at
        # each predicate and again for each accepted unit's actual append.
        length = len(_units(self.edit.get_text()))
        result = ''
        for index in range(length):
            current = _units(self.edit.get_text())
            if index >= len(current):
                raise SensorError('CURRENT identification text ordinal became unavailable')
            if cbus_name_character(current[index]):
                current = _units(self.edit.get_text())
                if index >= len(current):
                    raise SensorError('CURRENT identification text append became unavailable')
                result += chr(current[index])
        self._event('name_exit_set_text', '0xdc14a6' if result else '0xdc14bb',
                    value=result or 'NEWUNIT')
        self.edit.set_text(result or 'NEWUNIT')
        self._event('tag_name_getter', '0xdc14d3')
        empty = self.inherited.tag_name.value == ''
        if not empty:
            self._event('tag_name_getter', '0xdc14ef')
        if empty or self.inherited.tag_name.value == 'NEWUNIT':
            # Empty short-circuit must not perform the second getter.
            text = self.edit.get_text()
            self._event('tag_name_setter', '0xdc1532', value=text)
            self.inherited.tag_name.set(text)

    def exit_handler(self):
        """Direct form OnExit only; no FlashEdit ExitingControl/Apply."""
        return self.runtime._run(self._exit_handler)

    def do_exit(self):
        """Actual FlashEdit ordering: form OnExit, then umExit Apply."""
        def execute():
            self._exit_handler()
            self._event('controller_exiting_control', '0xae7ad8')
            self.edit.controller.apply()
        return self.runtime._run(execute)

    def state(self):
        return deepcopy(dict(text=self.edit.text, controller=self.edit.controller.state(),
            prepared=self.prepared, events=self.events, complete_identification=False,
            native_window_executed=False, complete_toolkit_save=False))


__all__ = ['IdentificationWindowRequired', 'ProgrammaticStringEdit',
           'SENLLAIdentificationName', 'StringController', 'cbus_name_character',
           'filter_cbus_name']
