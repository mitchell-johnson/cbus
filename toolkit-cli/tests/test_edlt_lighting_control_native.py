"""Native source-issued Lighting callbacks through a single parent save."""
from dataclasses import replace
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_parent_metadata import plan_native_parent_metadata
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from tests.test_edlt import Session
from tests.test_edlt_parent_form import fixture
from tests.test_edlt_parent_metadata import (
    FakeProgrammer, MetadataClient, NativeSession, oid)
from tests.test_edlt_parent_transaction import lighting, measurement


class NativeLightingControlTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.client = MetadataClient(self.spec)
        self.client.applications[56]['groups'][12] = {
            'oid': oid(1200), 'tag': 'Owned group',
            'tags': [{'variant': i, 'type': 'TEXT', 'value': 'Owned variant ' + str(i)}
                     for i in range(4)]}

    def plan(self, controls, **kwargs):
        operations = [measurement(), lighting(label_text=None, label_controls=controls)]
        return plan_native_parent_metadata(self.client.xml(), '//TEST/254/p/20',
            self.editor.snapshot(self.client.values), self.editor, operations, **kwargs)

    def test_dynamic_selection_is_bound_to_exact_source_variant_and_type(self):
        plan = self.plan([{'target': 'label', 'type': 10, 'events': [
            {'event': 'selected-row', 'index': 2, 'identity': 'label:56/12/2', 'value': 2}]}])
        self.assertEqual(plan.parent_plan.after_controls['Widget7WidgetByteValue1'], (0x10,))
        self.assertEqual(plan.parent_plan.after_controls['Widget7WidgetByteValue13'], (2,))
        receipt = plan.parent_plan.as_dict()['operation_results'][1]['label_controls']
        self.assertEqual(receipt['binding']['dynamic_rows'][2]['name'], 'Owned variant 2')
        self.assertFalse(receipt['pending'])
        self.assertFalse(receipt['original_host_executed'])

    def test_committed_static_text_reuses_shared_names_and_canonical_apply(self):
        plan = self.plan([{'target': 'label', 'type': 3, 'events': [
            {'event': 'input', 'text': 'Owned control text'}, {'event': 'enter'}]}])
        self.assertEqual(plan.parent_plan.after_controls['Widget7WidgetByteValue13'], (63,))
        self.assertEqual(plan.parent_plan.after_controls['StaticTextString63'][:18], tuple(b'Owned control text'))
        session = Session(self.spec)
        session.current = dict(self.client.values)
        result = self.editor.apply(session, plan.parent_plan)
        self.assertTrue(result['verified'])
        from cbus_toolkit.edlt_parent_metadata import NativeEdltParentTransaction
        manager = NativeEdltParentTransaction(self.client, self.editor,
            programmer=FakeProgrammer(NativeSession(self.spec, self.client)))
        owned = manager.plan('//TEST/254/p/20', operations=plan.operations, exclusive_project=True)
        saved = manager.apply(owned).as_dict()
        self.assertTrue(saved['saved'])
        self.assertEqual(self.client.commands.count('PP SAVE'), 1)

    def test_pending_text_and_forged_variant_refuse_before_mutation(self):
        cases = ([{'target': 'label', 'type': 3, 'events': [
                    {'event': 'input', 'text': 'Pending'}, {'event': 'close'}]}],
                 [{'target': 'label', 'type': 10, 'events': [
                    {'event': 'selected-row', 'index': 2, 'identity': 'label:56/12/1', 'value': 2}]}])
        before = self.client.xml()
        for controls in cases:
            with self.subTest(controls=controls), self.assertRaises(EdltError):
                self.plan(controls)
        self.assertEqual(self.client.xml(), before)
        self.assertEqual(self.client.commands, [])

    def test_detached_or_modified_binding_cannot_be_used_for_apply(self):
        plan = self.plan([{'target': 'label', 'type': 10, 'events': []}])
        binding = plan.parent_plan.lighting_label_bindings[0]
        session = Session(self.spec)
        session.current = dict(self.client.values)
        tampered = replace(plan.parent_plan, lighting_label_bindings=(replace(binding, group=13),))
        with self.assertRaises(EdltError):
            self.editor.apply(session, tampered)
        self.assertEqual(session.calls, [])


if __name__ == '__main__':
    unittest.main()
