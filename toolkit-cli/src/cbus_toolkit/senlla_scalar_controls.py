"""Persistent scalar Flash controllers on the SAME SENLLA owning attributes.

Entry methods are native source positions, not a substitute for director
initialization, focus delivery, list/object controls or programming Save.
"""
from dataclasses import dataclass
from copy import deepcopy

from .senlla_control_primitives import NativeText, ProgrammaticCombo, _text_equal
from .senlla_inherited_owner import UnitEnumAttribute
from .senlla_lifecycle import BooleanAttribute, IntegerAttribute
from .sensors import SensorError


def _integer(value):
    if type(value) is not int or not -(1 << 31) <= value < (1 << 31):
        raise SensorError('Scalar control requires a signed 32-bit integer')
    return value


@dataclass(frozen=True)
class ScalarGetterRequest:
    """An unimplemented native getter at its causal source position."""
    kind: str
    source: str
    field: str
    identity: tuple | None = None
    ordinal: int | None = None

    def as_dict(self):
        return dict(kind=self.kind, source=self.source, field=self.field,
                    identity=list(self.identity) if self.identity is not None else None,
                    ordinal=self.ordinal)


class ScalarGetterRequired(SensorError):
    """Stops before a managed collection/address-cache getter is invented.

    There is no acknowledgment or detached-result executor. The owning
    component must implement the actual getter on the SAME source object.
    """
    def __init__(self, request):
        self.request = request
        super().__init__(f'Actual scalar {request.kind} getter required at {request.source}')


class ScalarController:
    """Actual controller cache, render lock, umExit/umChange and Apply gates.

    Numeric input is typed signed32. Arbitrary Delphi StrToInt text grammar
    is not emulated. Bound integer representation reads then rearms the SAME
    attribute, and the post-render representation is read again.
    """
    def __init__(self, attribute, renderer, *, mode='exit', boolean=False, events=None):
        expected = BooleanAttribute if boolean else IntegerAttribute
        if not isinstance(attribute, expected) or not callable(renderer):
            raise SensorError('Scalar controller requires its actual typed attribute and renderer')
        if mode not in ('exit', 'change', 'manual'):
            raise SensorError('Unknown native scalar controller update mode')
        self.attribute, self.renderer, self.mode = attribute, renderer, mode
        self.boolean = boolean
        self.active, self.read_only = True, False
        self.depth, self.dirty = 0, False
        self.cache = False if boolean else ''
        self.events = [] if events is None else events
        self._receiver = lambda _: self.refresh()
        attribute.publisher.subscribe(self._receiver)

    def _event(self, operation, **values):
        self.events.append(dict(operation=operation, attribute=self.attribute.name,
                                depth=self.depth, **values))

    def _representation(self):
        value = self.attribute.value
        if self.boolean:
            # TBooleanAttribute.GetAsString, like AsBoolean, resolves BEFORE
            # reading its stored byte. Its two constructor representations
            # distinguish true/false; no resource label is synthesized here.
            return value
        # Integer's representation wrapper resolves AFTER rendering the
        # concrete representation. This is separate from its typed getter.
        self.attribute.resolve_change()
        return str(value)

    def refresh(self):
        if not self.active:
            return
        self.depth += 1
        try:
            self.dirty = False
            before = self._representation()
            self._event('render', value=before)
            self.renderer(before)
            # Rendering may execute another setter and synchronous callbacks.
            self.cache = self._representation()
            self._event('cache_restored', value=self.cache, dirty=self.dirty)
        finally:
            self.depth -= 1

    def get(self):
        return self.cache if self.dirty else self._representation()

    def set(self, value):
        if self.boolean:
            if type(value) is not bool:
                raise SensorError('Boolean control requires a Boolean')
        else:
            value = str(_integer(value))
        if self.read_only:
            return
        # Boolean SetAsBoolean always marks dirty; String SetAsString compares
        # exact UTF16 cached text before changing it.
        if not self.boolean and _text_equal(self.cache, value):
            return
        self.cache, self.dirty = value, True
        self._event('cache_changed', value=value)
        if self.mode == 'change':
            self.apply()

    def apply(self):
        if self.dirty and not self.read_only and self.active and self.depth == 0:
            try:
                self._event('apply', value=self.cache)
                self.attribute.set(self.cache if self.boolean else int(self.cache))
            except Exception:
                self.refresh()
                raise
        # Base Apply clears dirty on every successful return, even when the
        # locked/read-only/inactive gate skipped the actual setter.
        self.dirty = False

    def exit(self):
        if self.mode == 'exit':
            self.apply()

    def state(self):
        return dict(cache=self.cache, dirty=self.dirty, depth=self.depth,
                    active=self.active, read_only=self.read_only, mode=self.mode)


class ScalarTrack:
    """Fresh raw/percent/lux track and TrackBarEdit render/feedback boundary."""
    def __init__(self, attribute, *, minimum=0, maximum=255, position=0,
                 kind='edit', flash_position=False, events=None):
        if (kind not in ('raw', 'edit', 'lux') or type(flash_position) is not bool
                or type(minimum) is not int or type(maximum) is not int or minimum > maximum):
            raise SensorError('Invalid native scalar track configuration')
        position = _integer(position)
        self.minimum, self.maximum = minimum, maximum
        self.position = max(minimum, min(maximum, position))
        self.kind, self.flash_position = kind, flash_position
        self.text = '' if kind == 'raw' else str(self._display_value())
        self.enabled = True
        self.controller = ScalarController(attribute, self._render, events=events)
        self.controller.refresh()

    def _position(self, value):
        if self.kind == 'lux':
            value = 0 if value < 0 else 255 if value > 2550 else (value + 9) // 10
        return max(self.minimum, min(self.maximum, value))

    def _display_value(self):
        return self.position * 10 if self.kind == 'lux' else self.position

    def _set_position(self, value):
        value = self._position(value)
        if value == self.position:
            return
        self.position = value
        if self.kind != 'raw':
            self.text = str(self._display_value())
        self.controller.set(self.position if self.flash_position or self.kind == 'raw'
                            else self._display_value())

    def _render(self, text):
        value = int(text)
        if self.kind == 'raw' or self.flash_position:
            self._set_position(value)
        else:
            # SetEditText -> UpdateTrackBarFromEdit, with native track/edit
            # recursion locks, then UpdateEditFromTrackBar at the tail.
            self.text = text
            self._set_position(value)
            self.text = str(self._display_value())
        if self.kind != 'raw':
            # Fresh TrackBarEdit.Create sets AutoEnable=true. Its actual bound
            # element is nonnil; later Restore UpdateEnables is a separate
            # source position and may disable it again.
            self.enabled = True

    def input_position(self, value):
        value = _integer(value)
        # Custom lux conversion receives the raw track POSITION here.
        if self.kind == 'lux':
            value *= 10
        self._set_position(value)

    def state(self):
        return dict(position=self.position, text=self.text, enabled=self.enabled,
                    controller=self.controller.state())


class ScalarCheckBox:
    """Bound Boolean controller and concrete Checked render state.

    Typed changes use the native umChange controller. HWND Click/message
    delivery and separately installed manual form handlers are caller-owned.
    """
    def __init__(self, attribute, *, checked_changed=None, events=None):
        if checked_changed is not None and not callable(checked_changed):
            raise SensorError('Checked state callback must be callable')
        self.checked, self.enabled, self.read_depth = False, True, 0
        self.checked_changed = checked_changed
        self.controller = ScalarController(attribute, self._render, mode='change',
                                           boolean=True, events=events)
        self.controller.refresh()

    def _render(self, _):
        self.read_depth += 1
        try:
            checked = self.controller.get()
            self.checked = checked
            self.enabled = True
            if self.checked_changed is not None:
                self.checked_changed(checked)
        finally:
            self.read_depth -= 1

    def input(self, value):
        if type(value) is not bool:
            raise SensorError('Checkbox requires a Boolean')
        self.checked = value
        if self.checked_changed is not None:
            self.checked_changed(value)
        self.controller.set(value)


class ScalarRadio:
    """Native direct Boolean/enum radio writes; no deferred cache Apply."""
    def __init__(self, attribute, *, count, inverse=False, index=0, events=None):
        if not isinstance(attribute, (BooleanAttribute, UnitEnumAttribute)):
            raise SensorError('Radio requires its SAME Boolean or enum attribute')
        if type(count) is not int or count < 1 or type(inverse) is not bool:
            raise SensorError('Radio requires actual item count and Boolean inverse')
        if type(index) is not int or not -1 <= index < count:
            raise SensorError('Radio requires its actual native initial index')
        self.attribute, self.count, self.inverse = attribute, count, inverse
        self.index, self.enabled = index, True
        self.events = [] if events is None else events
        self._receiver = lambda _: self.refresh()
        attribute.publisher.subscribe(self._receiver)
        self.refresh()

    def refresh(self):
        value = self.attribute.value
        if isinstance(self.attribute, BooleanAttribute):
            value = 1 if value == (not self.inverse) else 0
        self.set_index(value)
        # HandleFlashValueChanged restores Enabled after the index write and
        # any nested Click/setter callbacks. This binding always has a nonnil
        # current element, even when SetItemIndex itself was unchanged.
        self.enabled = True

    def set_index(self, value):
        value = _integer(value)
        value = max(-1, min(self.count - 1, value))
        if self.index == value:
            return
        self.index = value
        self.events.append(dict(operation='radio_click', attribute=self.attribute.name, index=value))
        # The inherited RadioGroup toggles a button while changing index.
        # FlashRadioGroup.Click writes directly even during source rendering.
        self.attribute.set((bool(value) == (not self.inverse))
                           if isinstance(self.attribute, BooleanAttribute) else value)


@dataclass(frozen=True)
class StatusResources:
    """Actual localized source suffix and zero-label reads, not UI defaults."""
    suffix: object
    zero_label: object

    def __post_init__(self):
        if not callable(self.suffix) or not callable(self.zero_label):
            raise SensorError('Status requires CURRENT native resource readers')

    def format(self, value):
        suffix = self.suffix()
        if type(suffix) is not str:
            raise SensorError('Native status resource must be text')
        return str(max(3, _integer(value))) + suffix

    def parse_generated(self, text):
        # Fixed-list initialization only supplies source-generated decimal
        # labels. No arbitrary StrToIntDef/Delphi input grammar is claimed.
        zero = self.zero_label()
        if type(zero) is not str:
            raise SensorError('Native status resource must be text')
        if _text_equal(text, zero):
            return 0
        token = text.split(' ', 1)[0]
        if not token or any(c not in '0123456789' for c in token):
            raise SensorError('Status fixed-list resource lacks a decimal first token')
        return _integer(int(token))


class SENLLAScalarControls:
    """Persistent concrete scalar bindings, invoked at separate source sites."""
    def __init__(self, late_unit):
        from .senlla_late_unit import SENLLALateUnit
        if not isinstance(late_unit, SENLLALateUnit):
            raise SensorError('Scalar controls require the actual SAME late Unit owner')
        self.late, self.inherited, self.runtime = late_unit, late_unit.inherited, late_unit.runtime
        self.controls, self.events = {}, []
        self.target_edit_text = ''
        self.status = None

    def _run(self, callback):
        return self.runtime._run(callback)

    def _attribute(self, name):
        return self.inherited.unit_attribute(name)

    def _add(self, name, factory):
        if name in self.controls:
            raise SensorError('Scalar binding already exists: ' + name)
        value = factory()
        self.controls[name] = value
        return value

    def bind_light_target(self):
        return self._run(lambda: self._add('LightLevelTargetLux', lambda: ScalarTrack(
            self._attribute('LightLevelTargetLux'), maximum=200, kind='raw', events=self.events)))

    def bind_light_margin(self):
        return self._run(lambda: self._add('LightLevelMarginPerc', lambda: ScalarTrack(
            self._attribute('LightLevelMarginPerc'), minimum=1, maximum=100, position=1,
            flash_position=True, events=self.events)))

    def initialize_light_target_text(self):
        """fa8c2e/fa8c38, or the earlier target hook's SAME helper call.

        Execute before maintenance Properties.OnChange installation. The edit
        text uses the captured clamp even if an actual BeforeChange cancels
        or transforms the model setter.
        """
        def execute():
            value = self._attribute('LightLevelTargetLux').value
            if value > 200:
                value = 200
                self.events.append(dict(operation='target_direct_clamp', source='0xfa8802', value=200))
                self._attribute('LightLevelTargetLux').set(200)
            lux = 0 if value < 0 else 2550 if value > 255 else value * 10
            self.target_edit_text = str(lux)
            return self.target_edit_text
        return self._run(execute)

    def bind_boolean(self, name, *, checked_changed=None):
        allowed = ('LightLevelMaintActive', 'LightLevelBroadcastActive',
                   'InfraredLightLevelActive', 'InfraredOccupancyActive')
        if name not in allowed:
            raise SensorError('Boolean field has no admitted scalar binding source')
        return self._run(lambda: self._add(name, lambda: ScalarCheckBox(
            self._attribute(name), checked_changed=checked_changed, events=self.events)))

    def bind_pec_polarity(self):
        return self._run(lambda: self._add('LightLevelMaintEnableGroupOff', lambda: ScalarRadio(
            self._attribute('LightLevelMaintEnableGroupOff'), count=2, events=self.events)))

    def bind_bank(self, index):
        """fc2e68..fc2f6d; caller next binds the low/high group controls."""
        def execute():
            if type(index) is not int or not 0 <= index < 8:
                raise SensorError('Bank scalar binding requires an ordinal in 0..7')
            bank, prefix = self.late.live_banks.banks[index], f'bank:{index}.'
            for name, factory in (
                ('SwitchActive', lambda: ScalarCheckBox(bank.active, events=self.events)),
                ('EnableGroupOff', lambda: ScalarRadio(bank.off, count=2, events=self.events)),
                ('LowLevelLux', lambda: ScalarTrack(bank.low_lux, kind='lux', events=self.events)),
                ('HighLevelLux', lambda: ScalarTrack(bank.high_lux, kind='lux', events=self.events)),
                ('UseLowLevelGroup', lambda: ScalarCheckBox(bank.use_low, events=self.events)),
                ('UseHighLevelGroup', lambda: ScalarCheckBox(bank.use_high, events=self.events))):
                self._add(prefix + name, factory)
            # SetBooleanInverse is called AFTER PrepareFlashRadioGroupSimple.
            radio = self.controls[prefix + 'EnableGroupOff']
            radio.inverse = True
            radio.refresh()
        return self._run(execute)

    def bank_group_checks(self):
        """fc0b10: current Low use then current High use, one ascending loop."""
        def execute():
            for index in range(8):
                bank = self.late.live_banks.banks[index]
                if bank.use_low.value:
                    self.events.append(dict(operation='bank_threshold', bank=index, field='high', value=2550))
                    bank.high_lux.set(2550)
                if bank.use_high.value:
                    self.events.append(dict(operation='bank_threshold', bank=index, field='low', value=0))
                    bank.low_lux.set(0)
        return self._run(execute)

    def refresh_bank_enabled(self, index):
        """fc1350 after this row's scalar AND group bindings are complete."""
        def execute():
            prefix = f'bank:{index}.'
            control = self.controls.get(prefix + 'SwitchActive')
            if not isinstance(control, ScalarCheckBox):
                raise SensorError('Bank enabled refresh requires the actual bound checkbox')
            bank = self.late.live_banks.banks[index]
            control.enabled = bank.allowed.value
            if not control.checked:
                bank.use_low.set(False)
                bank.use_high.set(False)
                self.bank_group_checks()
            self.controls[prefix + 'UseLowLevelGroup'].enabled = control.checked
            self.controls[prefix + 'UseHighLevelGroup'].enabled = control.checked
        return self._run(execute)

    def bind_power_state(self, name, *, descriptions):
        """Source EnumValues have actual localized descriptions in ordinal order."""
        allowed = ('PowerUpLightLevelState', 'PowerUpOccupancyState', 'PowerUpTargetGroupState',
                   'PowerUpMarginGroupState', 'PowerUpBankSwitchGroupState')
        if name not in allowed or not callable(descriptions):
            raise SensorError('Power/indicator radio requires its CURRENT EnumValues reader')
        def execute():
            attr = self._attribute(name)
            rows = descriptions(attr)
            if (not isinstance(rows, (tuple, list)) or len(rows) != attr.maximum + 1
                    or any(type(text) is not str for text in rows)):
                raise SensorError('Actual EnumValues descriptions must cover every source ordinal')
            radio = self._add(name, lambda: ScalarRadio(attr, count=len(rows), events=self.events))
            radio.descriptions = tuple(rows)
            return radio
        return self._run(execute)

    def bind_indicator_control(self, *, descriptions):
        """fa1461 exclusion3 before fa149e; native index3 clamps/writes2."""
        if not callable(descriptions):
            raise SensorError('Indicator radio requires its CURRENT EnumValues reader')
        def execute():
            attr = self._attribute('IndicatorControl')
            rows = descriptions(attr)
            if (not isinstance(rows, (tuple, list)) or len(rows) != 4
                    or any(type(text) is not str for text in rows)):
                raise SensorError('Indicator source requires four actual enum descriptions')
            radio = self._add('IndicatorControl', lambda: ScalarRadio(attr, count=3, events=self.events))
            radio.descriptions = tuple(rows[:3])
            return radio
        return self._run(execute)

    def refresh_power_enabled(self):
        """fc426c prefix, stopping before unresolved managed getter effects."""
        def execute():
            def used(name, source):
                group = self._attribute(name).value
                if group is None:
                    raise SensorError('Native power enable dereferences its CURRENT nil group')
                if self.runtime.groups.get(group.identity) is not group:
                    raise SensorError('Power enable requires its CURRENT canonical group')
                # Native IsUnused reads actual dirty/cached Address state.
                # Canonical numeric identity cannot stand for that getter.
                raise ScalarGetterRequired(ScalarGetterRequest(
                    'group_is_unused', source, name, group.identity))
            margin = bool(self._attribute('IsUsingLightLevelMarginGroup').value
                          and used('LightLevelMarginGroup', '0xfc4291'))
            self.controls['PowerUpMarginGroupState'].enabled = margin
            target = bool(self._attribute('IsUsingLightLevelTargetGroup').value
                          and used('LightLevelTargetGroup', '0xfc42d3'))
            self.controls['PowerUpTargetGroupState'].enabled = target
            # IsUsingBankSwitchLowGroup captures Count through the actual
            # managed collection before its first flag. No fixed tuple Count
            # or synthetic reverse-reference resolution is accepted here.
            raise ScalarGetterRequired(ScalarGetterRequest(
                'bank_collection_count', '0xca468b', 'LightLevelBanks'))
        return self._run(execute)

    def bind_power_preset(self, name):
        allowed = ('PowerUpTargetGroupPresetLevel', 'PowerUpMarginGroupPresetLevel',
                   'PowerUpBankSwitchGroupPresetLevel')
        if name not in allowed:
            raise SensorError('Power preset field has no admitted scalar binding source')
        return self._run(lambda: self._add(name, lambda: ScalarTrack(
            self._attribute(name), events=self.events)))

    def initialize_global_status(self, resources, *, text=None):
        """fa1a20 then fa2574: install the handler after all253 item additions."""
        if type(resources) is not StatusResources or (text is not None and type(text) is not NativeText):
            raise SensorError('Status initialization requires actual resources and NativeText')
        def execute():
            if self.status is not None:
                raise SensorError('Global status has already been initialized')
            combo = ProgrammaticCombo('cmbStatusReportInterval', NativeText() if text is None else text)
            self.status = combo
            for value in range(3, 256):
                combo.add_item(value, resources.format(value))
            attr = self._attribute('StatusReportInterval')
            def changed(control):
                value = resources.parse_generated(control.text)
                self.events.append(dict(operation='status_after_change', source='0xfa211a', value=value,
                                        click_depth=control.click_depth))
                attr.set(value)
            combo.property_on_change = changed
            target = resources.format(attr.value)
            count = len(combo.items)
            for index in range(count):
                if _text_equal(combo.items[index][1], target):
                    combo.set_index(index)
                    break
            self.inherited.global_initialized = True
            return combo
        return self._run(execute)

    def exit_control(self, name):
        def execute():
            control = self.controls.get(name)
            if control is None or not hasattr(control, 'controller'):
                raise SensorError('Source exit requires an actual bound controller')
            control.controller.exit()
        return self._run(execute)

    def apply_controller(self, name):
        def execute():
            control = self.controls.get(name)
            if control is None or not hasattr(control, 'controller'):
                raise SensorError('Source Apply requires an actual bound controller')
            control.controller.apply()
        return self._run(execute)

    def journal(self):
        return deepcopy(self.events)
