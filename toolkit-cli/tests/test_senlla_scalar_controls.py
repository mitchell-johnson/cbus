"""Literal retained scalar control cases on SAME authored owning objects."""
import unittest

from cbus_toolkit.senlla_scalar_controls import (
    ScalarController, ScalarTrack, ScalarCheckBox, ScalarRadio,
    SENLLAScalarControls, StatusResources, ScalarGetterRequired)
from cbus_toolkit.senlla_lifecycle import (
    FlashObject, AttributeManager, IntegerAttribute, BooleanAttribute)
from cbus_toolkit.senlla_inherited_owner import UnitEnumAttribute
from cbus_toolkit.senlla_control_primitives import NativeText
from cbus_toolkit.sensors import SensorError
import test_senlla_owner as owning_cases
from test_senlla_inherited_owner import snapshot


class ScalarControllerTests(unittest.TestCase):
    def attribute(self, value=0, **kwargs):
        unit = FlashObject('authored.unit')
        return IntegerAttribute(AttributeManager(unit), value, **kwargs)

    def test_rendered_margin_clamp_retains_original_cache_and_live_value(self):
        for raw, display, dirty in ((0, 1, False), (1, 1, False), (9, 9, True),
                                    (100, 100, True), (101, 100, True), (25500, 100, True)):
            with self.subTest(raw=raw):
                attr = self.attribute(raw)
                track = ScalarTrack(attr, minimum=1, maximum=100, position=1, flash_position=True)
                self.assertEqual(track.position, display)
                self.assertEqual(track.text, str(display))
                self.assertEqual(attr.value, raw)
                self.assertEqual(track.controller.cache, str(raw))
                self.assertEqual(track.controller.dirty, dirty)
                track.controller.exit()
                self.assertEqual(attr.value, raw)
                self.assertFalse(track.controller.dirty)

    def test_post_render_current_reread_instead_of_original_display(self):
        attr = self.attribute(255)
        controller = None
        observations = []
        def renderer(text):
            observations.append((text, controller.depth))
            if text == '255':
                controller.set(100)
                attr.set(70)
        controller = ScalarController(attr, renderer)
        controller.refresh()
        self.assertEqual(observations, [('255', 1), ('70', 2)])
        self.assertEqual((controller.cache, controller.depth, attr.value), ('70', 0, 70))

    def test_apply_uses_live_before_change_and_native_failure_render(self):
        attr = self.attribute(9, minimum=1, maximum=100)
        rendered = []
        controller = ScalarController(attr, rendered.append)
        controller.refresh()
        controller.set(101)
        with self.assertRaisesRegex(SensorError, 'bounds'):
            controller.exit()
        self.assertEqual((attr.value, controller.cache, controller.depth), (9, '9', 0))
        self.assertEqual(rendered, ['9', '9'])
        def before(_, decision):
            decision.proposed = 17
        attr.before_change = before
        controller.set(25)
        controller.exit()
        self.assertEqual((attr.value, controller.cache, controller.dirty), (17, '17', False))

    def test_successful_apply_clears_dirty_even_at_gate(self):
        for gate in ('read_only', 'active', 'depth'):
            with self.subTest(gate=gate):
                attr = self.attribute(7)
                controller = ScalarController(attr, lambda _: None)
                controller.set(8)
                setattr(controller, gate, 1 if gate == 'depth' else gate == 'read_only')
                controller.apply()
                self.assertEqual(attr.value, 7)
                self.assertFalse(controller.dirty)

    def test_boolean_change_equal_cache_still_marks_dirty_then_native_equal_noop(self):
        attr = BooleanAttribute(AttributeManager(FlashObject('unit')), True)
        controller = ScalarController(attr, lambda _: None, boolean=True, mode='manual')
        controller.refresh()
        controller.set(True)
        self.assertTrue(controller.dirty)
        calls = []
        attr.publisher.subscribe(lambda _: calls.append(attr.value))
        controller.apply()
        self.assertEqual(calls, [])
        self.assertFalse(controller.dirty)

    def test_direct_radio_enum_and_inverse_boolean_preserve_same_attributes(self):
        manager = AttributeManager(FlashObject('unit'))
        attr = UnitEnumAttribute(manager, maximum=2)
        attr.set(2)
        radio = ScalarRadio(attr, count=3)
        self.assertEqual(radio.index, 2)
        radio.set_index(1)
        self.assertEqual(attr.value, 1)
        flag = BooleanAttribute(manager, True)
        inverse = ScalarRadio(flag, count=2, inverse=True)
        self.assertEqual(inverse.index, 0)
        inverse.set_index(1)
        self.assertFalse(flag.value)

    def test_radio_publication_and_equal_index_render_restore_enabled_at_tail(self):
        attr = UnitEnumAttribute(AttributeManager(FlashObject('unit')), maximum=2)
        radio = ScalarRadio(attr, count=3)
        attr.publisher.subscribe(lambda _: setattr(radio, 'enabled', False))
        radio.enabled = False
        attr.set(1)
        self.assertEqual(radio.index, 1)
        self.assertTrue(radio.enabled)
        radio.enabled = False
        radio.refresh()
        self.assertEqual(radio.index, 1)
        self.assertTrue(radio.enabled)

    def test_custom_lux_display_rounding_cache_and_typed_exit(self):
        for value, position, text in ((-1, 0, '0'), (0, 0, '0'), (1, 1, '10'),
                                      (201, 21, '210'), (2550, 255, '2550'), (2560, 255, '2550')):
            with self.subTest(value=value):
                attr = self.attribute(value)
                track = ScalarTrack(attr, kind='lux')
                self.assertEqual((track.position, track.text), (position, text))
                self.assertEqual((track.controller.cache, attr.value), (str(value), value))
                track.controller.exit()
                self.assertEqual(attr.value, value)
                track.input_position(9)
                track.controller.exit()
                self.assertEqual(attr.value, 90)

    def test_typed_input_refuses_bool_and_unsigned_overflow(self):
        controller = ScalarController(self.attribute(), lambda _: None)
        for value in (True, 1 << 31, -(1 << 31) - 1, '9'):
            with self.subTest(value=value), self.assertRaises(SensorError):
                controller.set(value)


class SENLLAScalarControlsTests(unittest.TestCase):
    def owner(self, raw=None):
        owner, _, _ = owning_cases.SENLLAOwnerLoadTest.owner(self, raw)
        owner.load()
        return owner, SENLLAScalarControls(owner.late)

    def test_source_target_cap_is_direct_before_maintenance_install(self):
        owner, controls = self.owner(snapshot(PECTargetLux=[255], PECMarginLux=[255],
            LightLevelTargetGroup=[255], LightLevelMarginGroup=[255]))
        attr = owner.late.attribute('LightLevelTargetLux')
        margin = controls.bind_light_margin()
        target = controls.bind_light_target()
        seen = []
        attr.publisher.subscribe(lambda _: seen.append((attr.value, owner.runtime.unit.depth)))
        self.assertEqual(controls.initialize_light_target_text(), '2000')
        self.assertEqual(seen, [(200, 1)])
        self.assertEqual((attr.value, target.position), (200, 200))
        self.assertEqual(owner.late.attribute('LightLevelMarginPerc').value, 100)
        self.assertEqual(margin.controller.cache, '100')
        self.assertEqual(owner.raw.expected['PECTargetLux'], (255,))
        self.assertEqual(owner.raw.expected['PECMarginLux'], (255,))

    def test_captured_target_edit_value_survives_cancelled_native_setter(self):
        owner, controls = self.owner(snapshot(PECTargetLux=[201], PECMarginLux=[20],
            LightLevelTargetGroup=[255], LightLevelMarginGroup=[255]))
        attr = owner.late.attribute('LightLevelTargetLux')
        def cancel(_, decision):
            decision.changed = False
        attr.before_change = cancel
        self.assertEqual(controls.initialize_light_target_text(), '2000')
        self.assertEqual(attr.value, 201)
        self.assertEqual(owner.late.attribute('LightLevelMarginPerc').value, 10)

    def test_status0_to2_real_combo_callback_and_preserve3_to255(self):
        # Authored resource provider tests cache/control order. Its text is
        # not native catalogue data or Windows GUI acceptance.
        resources = StatusResources(lambda: ' ticks', lambda: 'disabled')
        for raw in (0, 1, 2, 3, 4, 25, 255):
            with self.subTest(raw=raw):
                owner, controls = self.owner(snapshot(StatusReportInterval=[raw]))
                combo = controls.initialize_global_status(resources, text=NativeText())
                attr = owner.inherited_owner.unit_attribute('StatusReportInterval')
                self.assertEqual((attr.value, combo.item_index), (max(raw, 3), max(raw, 3) - 3))
                self.assertEqual(combo.text, str(max(raw, 3)) + ' ticks')
                self.assertEqual(len(combo.items), 253)
                self.assertEqual(controls.journal()[-1]['click_depth'], 1)
                self.assertEqual(owner.raw.expected['StatusReportInterval'], (raw,))
                self.assertTrue(owner.inherited_owner.global_initialized)

    def test_bank_row_order_clears_current_row_before_all_bank_thresholds(self):
        owner, controls = self.owner(snapshot(LightLevelTargetGroup=[255], LightLevelMarginGroup=[255],
            LightLevelStore1=[100] * 8, LightLevelStore2=[20] * 8))
        banks = owner.late.live_banks.banks
        for bank in banks:
            bank.use_low.set(True)
            bank.use_high.set(True)
        for index in range(8):
            controls.bind_bank(index)
            controls.refresh_bank_enabled(index)
        self.assertEqual((banks[0].low_lux.value, banks[0].high_lux.value), (200, 1000))
        self.assertEqual([(b.low_lux.value, b.high_lux.value) for b in banks[1:]], [(0, 2550)] * 7)
        self.assertEqual([(b.use_low.value, b.use_high.value) for b in banks], [(False, False)] * 8)
        self.assertIs(controls.controls['bank:0.LowLevelLux'].controller.attribute, banks[0].low_lux)

    def test_threshold_loop_rereads_high_use_after_low_side_actual_callback(self):
        owner, controls = self.owner()
        bank = owner.late.live_banks.banks[0]
        bank.use_low.set(True)
        bank.use_high.set(True)
        bank.high_lux.publisher.subscribe(lambda _: bank.use_high.set(False))
        controls.bank_group_checks()
        self.assertEqual(bank.high_lux.value, 2550)
        self.assertFalse(bank.use_high.value)
        # The second predicate is current, so Low setter is skipped.
        self.assertEqual(bank.low_lux.value, 0)
        self.assertEqual([(e['field'], e['value']) for e in controls.events
                          if e['operation'] == 'bank_threshold'], [('high', 2550)])

    def test_boolean_bound_checked_state_current_setter_and_live_publication(self):
        owner, controls = self.owner()
        state = []
        checkbox = controls.bind_boolean('LightLevelMaintActive', checked_changed=state.append)
        attr = owner.late.attribute('LightLevelMaintActive')
        self.assertIs(checkbox.controller.attribute, attr)
        checkbox.input(True)
        self.assertTrue(attr.value)
        self.assertTrue(owner.runtime.graph.maintenance_active)
        self.assertEqual(state[-1], True)
        self.assertEqual(checkbox.controller.depth, 0)

    def test_power_sources_actual_descriptors_and_preset_exit_not_all_apply(self):
        owner, controls = self.owner(snapshot(PowerUpTargetGroupLevel=[25], PowerUpMarginGroupLevel=[35]))
        radio = controls.bind_power_state('PowerUpTargetGroupState',
                                         descriptions=lambda attr: ('authored.0', 'authored.1'))
        self.assertIs(radio.attribute, owner.late.attribute('PowerUpTargetGroupState'))
        radio.set_index(1)
        first = controls.bind_power_preset('PowerUpTargetGroupPresetLevel')
        second = controls.bind_power_preset('PowerUpMarginGroupPresetLevel')
        first.input_position(70)
        second.input_position(80)
        controls.exit_control('PowerUpTargetGroupPresetLevel')
        self.assertEqual(owner.late.attribute('PowerUpTargetGroupPresetLevel').value, 70)
        self.assertEqual(owner.late.attribute('PowerUpMarginGroupPresetLevel').value, 35)
        self.assertTrue(second.controller.dirty)

    def test_indicator_last_enum_row_is_excluded_and_loaded3_becomes2(self):
        owner, controls = self.owner(snapshot(IndicatorControl=[3]))
        radio = controls.bind_indicator_control(descriptions=lambda _: ('a', 'b', 'c', 'd'))
        self.assertEqual((radio.count, radio.index, radio.attribute.value), (3, 2, 2))
        self.assertEqual(owner.raw.expected['IndicatorControl'], (3,))

    def test_power_enable_prefix_stops_at_actual_address_or_collection_getter(self):
        cases = ((True, False, 'group_is_unused', '0xfc4291', 'LightLevelMarginGroup'),
                 (False, True, 'group_is_unused', '0xfc42d3', 'LightLevelTargetGroup'),
                 (False, False, 'bank_collection_count', '0xca468b', 'LightLevelBanks'))
        for margin, target, kind, source, field in cases:
            with self.subTest(margin=margin, target=target):
                owner, controls = self.owner()
                for prefix in ('Target', 'Margin', 'BankSwitch'):
                    controls.bind_power_state('PowerUp' + prefix + 'GroupState',
                                             descriptions=lambda _: ('a', 'b'))
                owner.late.attribute('IsUsingLightLevelMarginGroup').set(margin)
                owner.late.attribute('IsUsingLightLevelTargetGroup').set(target)
                with self.assertRaises(ScalarGetterRequired) as caught:
                    controls.refresh_power_enabled()
                request = caught.exception.request
                self.assertEqual((request.kind, request.source, request.field), (kind, source, field))
                if kind == 'group_is_unused':
                    # The actual target-use callback has already selected
                    # its current canonical group0; margin retains unused255.
                    self.assertEqual(request.identity, (56, 255 if margin else 0))
                else:
                    self.assertIsNone(request.identity)
                self.assertEqual(controls.controls['PowerUpMarginGroupState'].enabled, margin)
                self.assertEqual(controls.controls['PowerUpTargetGroupState'].enabled,
                                 True if margin else target)
                self.assertTrue(controls.controls['PowerUpBankSwitchGroupState'].enabled)
                detached = request.as_dict()
                detached['kind'] = 'modified'
                self.assertEqual(request.kind, kind)
                self.assertTrue(owner.runtime.failed)

    def test_invalid_or_repeated_bindings_refuse_and_journal_is_detached(self):
        owner, controls = self.owner()
        controls.bind_light_target()
        saved = controls.journal()
        saved.clear()
        self.assertTrue(controls.journal())
        with self.assertRaisesRegex(SensorError, 'already exists'):
            controls.bind_light_target()
        self.assertTrue(owner.runtime.failed)


if __name__ == '__main__':
    unittest.main()
