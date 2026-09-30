"""Issued terminal model projection, failure isolation and no Apply boundary."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import CRC_RANGES, EdltError
from cbus_toolkit.edlt_lifecycle import LifecycleCache
from cbus_toolkit.edlt_reset import _RawState
from cbus_toolkit.edlt_template_lifecycle_stage import EdltTemplateLifecycleStage
from cbus_toolkit.edlt_template_model_stage import EdltTemplateModelStage
from cbus_toolkit.edlt_template_staging import TemplatePpSnapshot
from cbus_toolkit.edlt_template_terminal_stage import (
    EdltTemplateTerminalStage, TemplateTerminalStageError, TemplateTerminalApplyRefused,
)
from cbus_toolkit.edlt_templates import EdltTemplateError
from tests.test_edlt_reset import fixture, metadata
from tests.test_edlt_template_staging import template


class TerminalStageTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.raw = _RawState(self.spec.defaults()).raw()
        self.raw.update(Widget6WidgetType='0x2', Widget6WidgetByteValue6='0x2a',
                        Widget6WidgetByteValue12='0x0', SceneCount='0x0')
        self.cache = LifecycleCache.from_dict(metadata()['lifecycle'])
        self.model = EdltTemplateModelStage(self.spec)
        self.upstream = self.model.stage(self.raw, metadata=self.cache, dirty_parameters=['UnitAddress'])
        self.editor = EdltTemplateTerminalStage(self.model)

    def stage(self, **kwargs):
        return self.editor.stage(self.upstream, **{'current_source': self.raw,
            'metadata': self.cache, 'dirty_parameters': ['UnitAddress'], **kwargs})

    def validate(self, receipt, **kwargs):
        return self.editor.validate(receipt, **{'current_source': self.raw,
            'metadata': self.cache, 'dirty_parameters': ['UnitAddress'], **kwargs})

    def test_terminal_uses_exact_retained_model_once_without_load(self):
        original = self.upstream.as_dict()
        with patch.object(self.model._lifecycle, 'load', side_effect=AssertionError('reload')), \
             patch.object(self.model._lifecycle, 'prepare_save', wraps=self.model._lifecycle.prepare_save) as prepare, \
             patch.object(self.model._lifecycle, 'crcs', wraps=self.model._lifecycle.crcs) as crcs:
            receipt = self.stage()
            self.assertIs(self.validate(receipt), receipt)
            self.assertEqual(prepare.call_count, 1)
            self.assertIs(prepare.call_args.args[0], self.upstream.loaded)
            self.assertEqual(crcs.call_count, 1)
        self.assertEqual(original, self.upstream.as_dict())
        self.assertEqual(receipt.final['SceneCount'], (8,))
        self.assertEqual(receipt.final['Widget6WidgetByteValue12'], (1,))
        self.assertEqual(receipt.final['Widget7WidgetType'], (255,))
        self.assertEqual(receipt.final['Application'], (56, 57))
        self.assertEqual(len(receipt.final), 874)
        self.assertEqual(set(receipt.crcs), set(CRC_RANGES))
        self.assertEqual(dict(receipt.crcs), self.model._lifecycle.crcs(receipt.before_crc))
        self.assertEqual(self.model.snapshot(receipt.rendered_parameters), dict(receipt.final))

    def test_lifecycle_receipt_chain_including_upstream_cancel(self):
        source = TemplatePpSnapshot([(n, v.split(' '), False) for n, v in self.raw.items()])
        issuer = EdltTemplateLifecycleStage(self.spec)
        upstream = issuer.stage(template([('Widget6WidgetType', '0x2')]), source=source, metadata=self.cache)
        editor = EdltTemplateTerminalStage(issuer)
        receipt = editor.stage(upstream, current_source=source, metadata=self.cache)
        self.assertIs(editor.validate(receipt, current_source=source, metadata=self.cache), receipt)
        issuer.cancel()
        with self.assertRaisesRegex(EdltTemplateError, 'intact active'):
            editor.validate(receipt, current_source=source, metadata=self.cache)

    def test_receipt_is_immutable_and_honest_about_unexecuted_terminal_validators(self):
        receipt = self.stage()
        for name in ('after_load', 'before_crc', 'final', 'rendered_parameters', 'crcs'):
            with self.assertRaises(TypeError): getattr(receipt, name)['UnitAddress'] = 'changed'
        result = receipt.as_dict()
        result['final']['UnitAddress'][0] = 1
        self.assertNotEqual(receipt.final['UnitAddress'], (1,))
        for flag in ('original_save_validation_verified', 'active_control_flush_verified',
                     'complete_parent_lifecycle_verified', 'apply_allowed', 'saved',
                     'target_mutation_attempted', 'save_dispatched', 'original_raw_terminal_spelling_verified'):
            self.assertIs(result[flag], False)
        for stage in ('FrmBaseUnit.ValidateSerialNumber', 'ValidateSceneWidgetConfig', 'EDLTUnit.IsValid'):
            self.assertIn(stage, result['unexecuted_phases'])
        self.assertIs(self.validate(receipt), receipt)

    def test_foreign_cloned_serialized_and_mutated_receipts_refused(self):
        receipt = self.stage()
        for other in (replace(receipt), receipt.as_dict(), None):
            with self.assertRaisesRegex(EdltTemplateError, 'intact active terminal'):
                self.validate(other)
        foreign = EdltTemplateTerminalStage(self.model)
        with self.assertRaisesRegex(EdltTemplateError, 'intact active terminal'):
            foreign.validate(receipt, current_source=self.raw, metadata=self.cache)
        object.__setattr__(receipt, 'model_plan', '{}')
        with self.assertRaisesRegex(EdltTemplateError, 'issued projection'): self.validate(receipt)

    def test_schema_source_cache_dirty_and_retained_graph_changes_refused(self):
        receipt = self.stage()
        with self.assertRaisesRegex(EdltError, 'changed since model staging'):
            self.validate(receipt, current_source={**self.raw, 'Widget6WidgetType': '2'})
        with self.assertRaisesRegex(EdltError, 'changed since model staging'):
            self.validate(receipt, dirty_parameters=[])
        cache = self.cache.as_dict(); cache['groups'][0]['levels'].append(77)
        with self.assertRaisesRegex(EdltError, 'changed since model staging'):
            self.validate(receipt, metadata=LifecycleCache.from_dict(cache))
        widgets = self.upstream.loaded.widgets
        object.__setattr__(self.upstream.loaded, 'widgets', (replace(widgets[0]), *widgets[1:]))
        with self.assertRaisesRegex(EdltError, 'issued model'): self.validate(receipt)
        object.__setattr__(self.upstream.loaded, 'widgets', widgets)
        self.spec.parameters['UnitName'].fields['DefaultValue'] = 'OTHER   '
        with self.assertRaisesRegex(EdltError, 'Specification changed'): self.validate(receipt)

    def test_replaced_upstream_rejected_before_terminal_projection(self):
        self.upstream = replace(self.upstream)
        with patch.object(self.model._lifecycle, 'prepare_save', side_effect=AssertionError('projection')):
            with self.assertRaises(TemplateTerminalStageError) as caught: self.stage()
        self.assertEqual(caught.exception.details['phase'], 'upstream_validation')
        self.assertEqual(self.editor.state, 'failed')
        self.assertIsNone(self.editor.candidate)

    def test_preparation_failure_discards_output_and_preserves_upstream(self):
        before = self.upstream.as_dict()
        with patch.object(self.model._lifecycle, 'prepare_save', side_effect=ValueError('injected')):
            with self.assertRaises(TemplateTerminalStageError) as caught: self.stage()
        self.assertEqual(caught.exception.details['phase'], 'retained_before_save_and_crc')
        self.assertFalse(caught.exception.details['candidate_published'])
        caught.exception.details['status'] = 'tampered'
        self.assertEqual(self.editor.last_failure['status'], 'failed')
        self.assertEqual(before, self.upstream.as_dict())
        self.assertIsNone(self.editor.candidate)
        with self.assertRaisesRegex(EdltTemplateError, 'no longer open'): self.stage()

    def test_upstream_change_during_preparation_is_refused_after_projection(self):
        prepare = self.model._lifecycle.prepare_save
        def changed(loaded):
            result = prepare(loaded)
            object.__setattr__(self.upstream, 'model_snapshot', '{}')
            return result
        with patch.object(self.model._lifecycle, 'prepare_save', side_effect=changed):
            with self.assertRaises(TemplateTerminalStageError) as caught: self.stage()
        self.assertEqual(caught.exception.details['phase'], 'terminal_projection_validation')
        self.assertIsNone(self.editor.candidate)

    def test_incomplete_or_foreign_plan_is_not_published(self):
        plan = self.model._lifecycle.prepare_save(self.upstream.loaded)
        bad = replace(plan, expected={k: v for k, v in plan.expected.items() if k != 'UnitAddress'})
        with patch.object(self.model._lifecycle, 'prepare_save', return_value=bad):
            with self.assertRaisesRegex(TemplateTerminalStageError, 'differs from'): self.stage()
        self.assertIsNone(self.editor.candidate)

    def test_interrupt_has_evidence_and_no_candidate(self):
        error = KeyboardInterrupt('owned interruption')
        with patch.object(self.model._lifecycle, 'prepare_save', side_effect=error):
            with self.assertRaises(KeyboardInterrupt) as caught: self.stage()
        self.assertIs(caught.exception, error)
        self.assertFalse(error.edlt_template_terminal_stage_evidence['candidate_published'])
        self.assertIsNone(self.editor.candidate)
        self.assertEqual(self.editor.state, 'failed')

    def test_terminal_cancel_invalidates_output_without_cancelling_upstream(self):
        receipt = self.stage()
        self.assertFalse(self.editor.cancel()['upstream_issuer_cancelled'])
        self.assertIsNone(self.editor.candidate)
        with self.assertRaisesRegex(EdltTemplateError, 'intact active terminal'): self.validate(receipt)
        self.model.validate(self.upstream, self.raw, metadata=self.cache, dirty_parameters=['UnitAddress'])
        with self.assertRaisesRegex(EdltTemplateError, 'no longer open'): self.stage()

    def test_nonattachable_interrupt_preserves_original_and_issuer_failure(self):
        class Nonattachable(KeyboardInterrupt):
            def __setattr__(self, name, value): raise RuntimeError('no attributes')
        error = Nonattachable('owned interruption')
        with patch.object(self.model._lifecycle, 'prepare_save', side_effect=error):
            with self.assertRaises(Nonattachable) as caught: self.stage()
        self.assertIs(caught.exception, error)
        self.assertEqual(self.editor.last_failure['phase'], 'retained_before_save_and_crc')
        self.assertFalse(self.editor.last_failure['candidate_published'])

    def test_reentrant_staging_and_cancel_are_refused_before_projection(self):
        prepare = self.model._lifecycle.prepare_save
        def reenter(loaded):
            self.assertEqual(self.editor.state, 'staging')
            self.assertIsNone(self.editor.candidate)
            with self.assertRaisesRegex(EdltTemplateError, 'no longer open'): self.stage()
            with self.assertRaisesRegex(EdltTemplateError, 'Cannot cancel'): self.editor.cancel()
            return prepare(loaded)
        with patch.object(self.model._lifecycle, 'prepare_save', side_effect=reenter) as call:
            receipt = self.stage()
        self.assertEqual(call.call_count, 1)
        self.assertIs(self.validate(receipt), receipt)

    def test_apply_refuses_before_any_target_access(self):
        receipt = self.stage()
        class Target:
            def __getattribute__(self, name): raise AssertionError('target accessed')
        for action in (receipt.apply, self.editor.apply):
            with self.assertRaises(TemplateTerminalApplyRefused) as caught: action(Target())
            self.assertFalse(caught.exception.details['target_mutation_attempted'])
        for issuer in (None, self.model._lifecycle, self.upstream):
            with self.assertRaises(EdltTemplateError): EdltTemplateTerminalStage(issuer)


if __name__ == '__main__': unittest.main()
