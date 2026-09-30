"""Transactional raw PP template assignments, without parent/session mutation."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt_templates import EdltTemplate, EdltTemplateError, EdltTemplateApplyRefused, edlt_template_crc
from cbus_toolkit.edlt_template_staging import (
    EdltTemplateAssignmentTransaction, TemplateAssignmentStage, TemplatePpSnapshot, TemplateStagingError,
)


def template(rows, before=()):
    return EdltTemplate((('UnitType', 'KEYGL5'), ('FirmwareVersion', '5.5.00')) + tuple(before)
                        + (('CRC', str(edlt_template_crc(value for _, value in rows))),) + tuple(rows))


class TemplateStagingTests(unittest.TestCase):
    def test_exact_tokens_are_immutable_and_not_reconstructed_from_raw(self):
        rows = [['Value', ['', '', 'B', ''], False], ['Empty', [], True]]
        source = TemplatePpSnapshot(rows)
        rows[0][1][2] = 'MUTATED'
        self.assertEqual(source.raw, {'Value': 'B ', 'Empty': ''})
        stage = EdltTemplateAssignmentTransaction(source).stage(template([('Value', 'B ')]))
        self.assertEqual(stage.after, source)
        self.assertEqual(stage.steps[-1].disposition, 'unchanged')
        self.assertEqual(stage.after.parameters[0][1], ('', '', 'B', ''))
        with self.assertRaises(TypeError):
            stage.after.raw['Value'] = 'MUTATED'

    def test_partial_array_retains_tail_and_explicit_dirty_after_normalized_noop(self):
        source = TemplatePpSnapshot([('Value', ['0xAB', 'TAIL'], False)])
        stage = EdltTemplateAssignmentTransaction(source).stage(template([('Value', '$ab')]))
        self.assertEqual(stage.after.raw['Value'], '0xAB TAIL')
        self.assertEqual(stage.after.parameters[0][2], True)
        self.assertEqual(stage.steps[-1].disposition, 'assigned')
        self.assertEqual(stage.steps[-1].before_tokens, stage.steps[-1].after_tokens)

    def test_source_aliases_are_not_normalized_without_a_setter(self):
        source = TemplatePpSnapshot([('Value', ['$ff', '$xab', '0xffffffff'], False)])
        stage = EdltTemplateAssignmentTransaction(source).stage(template([('Value', '$ff $xab 0xffffffff')]))
        self.assertEqual(stage.after, source)
        stage = EdltTemplateAssignmentTransaction(source).stage(template([('Value', '$FF $xAB 0xffffffff')]))
        self.assertEqual(stage.after.raw['Value'], '0xFF 0xAB 0xff')

    def test_all_children_order_duplicate_assignments_application_before_membership(self):
        source = TemplatePpSnapshot([('Value', ['A', 'B', 'C'], False), ('Application', ['0x1', '0x2'], True)])
        result = template([('Value', 'X Y'), ('Value', 'Z'), ('Application', '48 202')],
                          before=[('Value', 'FIRST')])
        stage = EdltTemplateAssignmentTransaction(source).stage(result)
        self.assertEqual(stage.after.raw, {'Value': 'Z Y C', 'Application': '0x30 0xca'})
        self.assertEqual([step.setter_value for step in stage.steps if step.name == 'Value'], ['FIRST', 'X Y', 'Z'])
        self.assertEqual(len(stage.steps), len(result.fields))
        self.assertEqual(stage.steps[0].disposition, 'unknown_attribute')
        tx = EdltTemplateAssignmentTransaction(source)
        with self.assertRaises(TemplateStagingError) as caught:
            tx.stage(template([('Value', 'CHANGED'), ('Application', '48  202')]))
        self.assertFalse(caught.exception.details['candidate_published'])
        self.assertFalse(caught.exception.details['discarded_working_initializing'])
        self.assertEqual(tx.source, source)
        self.assertIsNone(tx.candidate)

    def test_application_conversion_failure_for_unknown_name_still_aborts(self):
        tx = EdltTemplateAssignmentTransaction(TemplatePpSnapshot([]))
        with self.assertRaises(TemplateStagingError):
            tx.stage(template([('Application', '48  202')]))
        self.assertEqual(tx.state, 'failed')
        self.assertFalse(tx.last_failure['discarded_working_initializing'])

    def test_whitespace_slots_and_empty_assignment_are_not_collapsed(self):
        source = TemplatePpSnapshot([('Value', ['A', 'B', 'C'], False)])
        stage = EdltTemplateAssignmentTransaction(source).stage(template([('Value', 'X  Y ')]))
        self.assertEqual(stage.after.parameters[0][1], ('X', '', 'Y', ''))
        self.assertEqual(stage.after.raw['Value'], 'X  Y ')
        stage = EdltTemplateAssignmentTransaction(source).stage(template([('Value', '')]))
        self.assertEqual(stage.after.parameters[0][1], ('', 'B', 'C'))
        self.assertEqual(stage.after.raw['Value'], 'B C')

    def test_local_stage_publish_is_atomic_after_mid_setter_failure(self):
        source = TemplatePpSnapshot([('Value', ['A', 'B', 'C'], False), ('Other', ['OLD'], False)])
        tx = EdltTemplateAssignmentTransaction(source)
        original = tx._set_value
        def fail_second(target, value):
            if value == 'X Y Z':
                target[0] = 'X'
                target[1] = 'Y'
                raise RuntimeError('injected local setter interruption')
            original(target, value)
        with patch.object(tx, '_set_value', side_effect=fail_second):
            with self.assertRaises(TemplateStagingError) as caught:
                tx.stage(template([('Other', 'CHANGED'), ('Value', 'X Y Z')]))
        self.assertEqual(tx.source.raw, {'Value': 'A B C', 'Other': 'OLD'})
        self.assertIsNone(tx.candidate)
        self.assertTrue(caught.exception.details['discarded_working_initializing'])
        self.assertTrue(caught.exception.details['source_preserved'])
        self.assertEqual(caught.exception.details['steps'][-1]['after_tokens'], ['CHANGED'])
        self.assertEqual(tx.state, 'failed')
        with self.assertRaisesRegex(EdltTemplateError, 'new transaction'):
            tx.stage(template([('Other', 'RETRY')]))

    def test_keyboard_interrupt_discards_candidate_and_preserves_original_exception(self):
        source = TemplatePpSnapshot([('Value', ['ORIGINAL'], False)])
        tx = EdltTemplateAssignmentTransaction(source)
        interrupt = KeyboardInterrupt('test interruption')
        with patch.object(tx, '_set_value', side_effect=interrupt), self.assertRaises(KeyboardInterrupt) as caught:
            tx.stage(template([('Value', 'NEW')]))
        self.assertIs(caught.exception, interrupt)
        self.assertEqual(tx.source, source)
        self.assertIsNone(tx.candidate)
        self.assertEqual(tx.last_failure['failure_type'], 'KeyboardInterrupt')
        self.assertTrue(interrupt.edlt_template_staging_evidence['source_preserved'])

    def test_receipt_failure_cannot_publish_candidate(self):
        source = TemplatePpSnapshot([('Value', ['OLD'], False)])
        tx = EdltTemplateAssignmentTransaction(source)
        def fail_receipt(_stage):
            self.assertIsNone(tx.candidate)
            self.assertEqual(tx.state, 'staging')
            raise RuntimeError('receipt generation failed')
        with patch.object(TemplateAssignmentStage, 'as_dict', fail_receipt):
            with self.assertRaises(TemplateStagingError):
                tx.stage(template([('Value', 'NEW')]))
        self.assertEqual(tx.state, 'failed')
        self.assertIsNone(tx.candidate)
        self.assertEqual(tx.source, source)

    def test_broken_failure_formatter_still_discards_and_retires_transaction(self):
        class BrokenMessage(RuntimeError):
            def __str__(self):
                raise RuntimeError('broken formatter')
        source = TemplatePpSnapshot([('Value', ['OLD'], False)])
        tx = EdltTemplateAssignmentTransaction(source)
        error = BrokenMessage()
        with patch.object(tx, '_set_value', side_effect=error), self.assertRaises(TemplateStagingError) as caught:
            tx.stage(template([('Value', 'NEW')]))
        self.assertIs(caught.exception.cause, error)
        self.assertIs(caught.exception.__cause__, error)
        self.assertEqual(tx.state, 'failed')
        self.assertIn('text unavailable', tx.last_failure['failure'])
        self.assertIsNone(tx.candidate)
        self.assertTrue(tx.cancel()['source_preserved'])

    def test_cancel_invalidates_issued_stage_and_does_not_claim_original_rollback(self):
        source = TemplatePpSnapshot([('Value', ['OLD'], False)])
        tx = EdltTemplateAssignmentTransaction(source)
        stage = tx.stage(template([('Value', 'NEW')]))
        self.assertIs(tx.validate(stage, current_source=source), stage)
        receipt = tx.cancel()
        self.assertIsNone(tx.candidate)
        self.assertEqual(tx.source, source)
        self.assertFalse(receipt['original_cancel_replayed'])
        self.assertFalse(receipt['saved'])
        with self.assertRaises(EdltTemplateError):
            tx.validate(stage, current_source=source)
        with self.assertRaises(EdltTemplateError):
            tx.stage(template([('Value', 'RETRY')]))
        self.assertEqual(tx.cancel(), receipt)

    def test_source_fingerprints_include_tokens_order_dirty_and_initializing(self):
        source = TemplatePpSnapshot([('Value', ['A', 'B'], False), ('Other', ['C'], True)])
        tx = EdltTemplateAssignmentTransaction(source)
        stage = tx.stage(template([('Value', 'X')]))
        alternatives = (
            TemplatePpSnapshot([('Value', ['A B'], False), ('Other', ['C'], True)]),
            TemplatePpSnapshot([('Other', ['C'], True), ('Value', ['A', 'B'], False)]),
            TemplatePpSnapshot([('Value', ['A', 'B'], True), ('Other', ['C'], True)]),
            replace(source, initializing=True),
        )
        for other in alternatives:
            with self.subTest(other=other), self.assertRaises(EdltTemplateError):
                tx.validate(stage, current_source=other)
            self.assertNotEqual(other.fingerprint, source.fingerprint)
        with self.assertRaises(EdltTemplateError):
            tx.validate(replace(stage), current_source=source)
        with self.assertRaises(EdltTemplateError):
            EdltTemplateAssignmentTransaction(source).validate(stage, current_source=source)

    def test_mutated_frozen_candidate_and_source_are_not_reissuable(self):
        source = TemplatePpSnapshot([('Value', ['OLD'], False)])
        tx = EdltTemplateAssignmentTransaction(source)
        stage = tx.stage(template([('Value', 'NEW')]))
        object.__setattr__(stage, 'after', TemplatePpSnapshot([('Value', ['FORGED'], True)]))
        with self.assertRaises(EdltTemplateError):
            tx.validate(stage, current_source=source)
        tx = EdltTemplateAssignmentTransaction(source)
        object.__setattr__(source, 'parameters', (('Value', ('MUTATED',), False),))
        self.assertEqual(tx.source.raw['Value'], 'OLD')
        stage = tx.stage(template([('Value', 'NEW')]))
        with self.assertRaises(EdltTemplateError):
            tx.validate(stage, current_source=source)

    def test_safe_snapshot_admission(self):
        cases = ([('Value', [None], False)], [('Value', ['A'], 1)],
                 [('Value', ['A'], False), ('Value', ['B'], False)],
                 [('x:y', ['A'], False)], [('Value', 'raw', False)],
                 [('Value', ['X'] * 65537, False)], [('Value', ['X' * 262145], False)])
        for parameters in cases:
            with self.subTest(length=len(parameters)), self.assertRaises(EdltTemplateError):
                TemplatePpSnapshot(parameters)
        with self.assertRaises(EdltTemplateError):
            EdltTemplateAssignmentTransaction(TemplatePpSnapshot([], True))

    def test_culture_sensitive_dollar_tokens_are_explicit_refusals(self):
        source = TemplatePpSnapshot([('Value', ['OLD'], False)])
        for value in ('\u200d$xab', '\u00ad$ab', '$ß', '$\u200dxab', '$i', '$Xi', '$\tx'):
            with self.subTest(value=value), self.assertRaises(TemplateStagingError):
                EdltTemplateAssignmentTransaction(source).stage(template([('Value', value)]))
        stage = EdltTemplateAssignmentTransaction(source).stage(template([('Value', '$xß')]))
        self.assertEqual(stage.after.raw['Value'], '0xß')
        stage = EdltTemplateAssignmentTransaction(source).stage(template([('Value', '$xi')]))
        self.assertEqual(stage.after.raw['Value'], '0xi')

    def test_all_apply_surfaces_refuse_without_target_or_network_access(self):
        class Poison:
            def __getattribute__(self, name):
                raise AssertionError('target touched: ' + name)
        tx = EdltTemplateAssignmentTransaction(TemplatePpSnapshot([('Value', ['OLD'], False)]))
        with patch('socket.socket', side_effect=AssertionError('network touched')):
            stage = tx.stage(template([('Value', 'NEW')]))
            for item in (tx, stage):
                with self.assertRaises(EdltTemplateApplyRefused):
                    item.apply(Poison())
        receipt = stage.as_dict()
        self.assertFalse(receipt['target_mutation_attempted'])
        self.assertFalse(receipt['external_callbacks_executed'])
        self.assertFalse(receipt['native_parameter_validation_performed'])
        self.assertTrue(receipt['local_candidate_published_atomically'])


if __name__ == '__main__':
    unittest.main()
