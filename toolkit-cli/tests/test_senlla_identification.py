"""Source component cases; no original or Windows edit-window acceptance."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cbus_toolkit.senlla_identification import (
    IdentificationWindowRequired, ProgrammaticStringEdit,
    SENLLAIdentificationName, StringController, cbus_name_character, filter_cbus_name)
from cbus_toolkit.senlla_inherited_owner import SENLLAInheritedOwner, UnitStringAttribute
from cbus_toolkit.senlla_lifecycle import AttributeManager, FlashObject
from cbus_toolkit.senlla_project_bridge import SENLLAProjectBridge
from cbus_toolkit.sensors import SensorError
from test_senlla_inherited_owner import document, english_metadata_name, snapshot


class StringControlTests(unittest.TestCase):
    def attribute(self, value=''):
        return UnitStringAttribute(AttributeManager(FlashObject('owned-unit')), value)

    def test_activation_reads_current_attribute_after_nested_render_setter(self):
        attr = self.attribute('BEFORE')
        seen = []
        holder = {}
        def render(value):
            control = holder['controller']
            seen.append((value, control.depth))
            if value == 'BEFORE':
                attr.set('AFTER')
        control = StringController(attr, render)
        holder['controller'] = control
        control.set_active(True)
        self.assertEqual(seen, [('BEFORE', 2), ('AFTER', 3)])
        self.assertEqual(control.cache, 'AFTER')
        self.assertFalse(control.dirty)
        self.assertEqual(control.depth, 0)
        control.set_active(True)
        self.assertEqual(seen[-1], ('AFTER', 2))

    def test_render_restores_cache_without_erasing_callback_dirty(self):
        attr = self.attribute('CURRENT')
        edit = ProgrammaticStringEdit(attr)
        edit.controller.set_active(True)
        self.assertEqual(edit.text, 'CURRENT')
        self.assertEqual(edit.controller.cache, 'CURRENT')
        self.assertTrue(edit.controller.dirty)
        self.assertEqual(edit.controller.depth, 0)
        # The model attribute is unchanged; an equal Apply clears dirty.
        edit.controller.apply()
        self.assertEqual(attr._value, 'CURRENT')
        self.assertFalse(edit.controller.dirty)

    def test_utf16_exact_text_and_pending_cache_do_not_clamp_or_uppercase(self):
        attr = self.attribute()
        edit = ProgrammaticStringEdit(attr)
        edit.set_text('lowercase exceeds eight')
        self.assertEqual(edit.text, 'lowercase exceeds eight')
        self.assertEqual(edit.controller.cache, edit.text)
        self.assertEqual(attr._value, '')
        before = len(edit.events)
        edit.set_text(edit.text)
        self.assertEqual(len(edit.events), before)

    def test_apply_gates_clear_dirty_but_leave_actual_model_until_admitted(self):
        for gate in ('inactive', 'read_only', 'locked'):
            with self.subTest(gate=gate):
                attr = self.attribute('MODEL')
                control = StringController(attr, lambda _: None)
                control.set_active(True)
                control.set('PENDING')
                if gate == 'inactive':
                    control.set_active(False)
                elif gate == 'read_only':
                    control.read_only = True
                else:
                    control.depth = 1
                control.apply()
                self.assertEqual(attr._value, 'MODEL')
                self.assertFalse(control.dirty)

    def test_apply_failure_refreshes_current_value_and_balances_lock(self):
        attr = self.attribute('KEEP')
        control = StringController(attr, lambda _: None)
        control.set_active(True)
        attr.maximum = 4
        control.set('TOO LONG')
        with self.assertRaisesRegex(SensorError, 'UTF-16 maximum'):
            control.apply()
        self.assertEqual((attr._value, control.cache, control.depth), ('KEEP', 'KEEP', 0))
        self.assertFalse(control.dirty)


class IdentificationNameTests(unittest.TestCase):
    def owner(self, *, tag='KEEP', name='VALID', notification=None):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'owned.xml'
        bridge = SENLLAProjectBridge.from_document(document(path), 254, 42,
            storage_path=path, metadata_name=english_metadata_name,
            creation_dispatch=lambda request, bridge, runtime: None,
            tag_name_dispatch=notification)
        owner = SENLLAInheritedOwner(snapshot(), bridge)
        # Authored current metadata/control inputs, not a native DFM rendering.
        owner.tag_name._value = tag
        owner.unit_attribute('CBusUnitName').set(name)
        return owner

    def test_character_vectors_filter_utf16_units_without_case_conversion(self):
        vectors = {'MIXED_99': 'MIXED_99', 'Aa B_<C>9z!': 'AB_C9!',
                   'newunit': '', 'NewUnit': 'NU', '<>a b': '', '': '',
                   'A-B_C9!': 'A-B_C9!', 'A\U0001f601B\ud800C': 'ABC'}
        for text, expected in vectors.items():
            with self.subTest(text=text):
                self.assertEqual(filter_cbus_name(text), expected)
        self.assertEqual([unit for unit in range(65536) if cbus_name_character(unit)],
                         [unit for unit in range(33, 97) if unit not in (60, 62)])

    def test_fresh_binding_reaches_real_selection_even_for_valid_text(self):
        owner = self.owner()
        form = SENLLAIdentificationName(owner)
        with self.assertRaises(IdentificationWindowRequired) as caught:
            form.prepare_name()
        self.assertEqual(caught.exception.source, '0x6855de')
        self.assertEqual(form.edit.text, 'VALID')
        self.assertEqual(form.edit.controller.cache, 'VALID')
        self.assertTrue(form.edit.controller.dirty)
        self.assertEqual(form.edit.controller.depth, 0)
        self.assertEqual(owner.tag_name._value, 'KEEP')
        self.assertTrue(owner.runtime.failed)
        self.assertFalse(form.state()['complete_identification'])

    def test_direct_exit_keeps_nonempty_case_sensitive_tag_without_pp_apply(self):
        for tag, getter_count in (('KEEP', 2), ('newunit', 2), ('NewUnit', 2)):
            with self.subTest(tag=tag):
                owner = self.owner(tag=tag)
                form = SENLLAIdentificationName(owner, initial_control_text='VALID')
                form.edit.controller.set('PENDING')
                form.exit_handler()
                self.assertEqual(owner.tag_name._value, tag)
                self.assertEqual(owner.unit_attribute('CBusUnitName')._value, 'VALID')
                self.assertTrue(form.edit.controller.dirty)
                self.assertEqual(len([event for event in form.events
                                      if event['operation'] == 'tag_name_getter']), getter_count)

    def test_direct_exit_writes_actual_tag_only_for_empty_or_literal_fallback(self):
        for tag, getter_count in (('', 1), ('NEWUNIT', 2)):
            with self.subTest(tag=tag):
                observed = []
                owner = self.owner(tag=tag,
                    notification=lambda owner, bridge: observed.append(owner.tag_name._value))
                form = SENLLAIdentificationName(owner, initial_control_text='VALID')
                form.exit_handler()
                self.assertEqual(owner.tag_name._value, 'VALID')
                self.assertEqual(observed, ['VALID'])
                self.assertEqual(len([event for event in form.events
                                      if event['operation'] == 'tag_name_getter']), getter_count)
                self.assertIs(form.edit.controller.attribute, owner.unit_attribute('CBusUnitName'))

    def test_cleanup_stops_before_tag_getters_when_settext_reaches_window(self):
        for text, expected in (('Aa B_<C>9z!', 'AB_C9!'), ('lowercase', 'NEWUNIT'),
                               ('', 'NEWUNIT')):
            with self.subTest(text=text):
                owner = self.owner(tag='')
                form = SENLLAIdentificationName(owner, initial_control_text=text)
                with self.assertRaises(IdentificationWindowRequired):
                    form.exit_handler()
                self.assertEqual(form.edit.text, expected)
                self.assertEqual(form.edit.controller.cache, expected)
                self.assertEqual(owner.tag_name._value, '')
                self.assertFalse(any(event['operation'] == 'tag_name_getter'
                                     for event in form.events))

    def test_real_exit_runs_tag_notification_before_apply_hits_window(self):
        observed = []
        owner = self.owner(tag='', notification=lambda owner, bridge:
            observed.append(('tag', owner.unit_attribute('CBusUnitName')._value)))
        form = SENLLAIdentificationName(owner, initial_control_text='VALID')
        form.edit.controller.set_active(True)
        form.edit.controller.set('PENDING')
        # An authored already-valid display keeps direct Exit's SetText equal.
        with self.assertRaises(IdentificationWindowRequired):
            form.do_exit()
        self.assertEqual(observed, [('tag', 'VALID')])
        self.assertEqual(owner.tag_name._value, 'VALID')
        self.assertEqual(owner.unit_attribute('CBusUnitName')._value, 'PENDING')
        self.assertEqual(form.edit.text, 'PENDING')
        self.assertFalse(form.edit.controller.dirty)
        self.assertTrue(owner.runtime.failed)

    def test_missing_tag_notification_owner_interrupts_before_unitname_apply(self):
        owner = self.owner(tag='')
        form = SENLLAIdentificationName(owner, initial_control_text='VALID')
        form.edit.controller.set_active(True)
        form.edit.controller.set('PENDING')
        with self.assertRaisesRegex(SensorError, 'notification/timer owner'):
            form.do_exit()
        self.assertEqual(owner.tag_name._value, 'VALID')
        self.assertEqual(owner.unit_attribute('CBusUnitName')._value, 'VALID')
        self.assertTrue(form.edit.controller.dirty)
        self.assertTrue(owner.runtime.failed)


if __name__ == '__main__':
    unittest.main()
