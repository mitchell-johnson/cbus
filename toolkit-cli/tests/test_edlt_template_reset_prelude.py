"""Reset provenance stops before the additional template parent callbacks."""
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_application_cache import ApplicationCache
from cbus_toolkit.edlt_lifecycle import EdltLifecycle
from cbus_toolkit.edlt_reset import _RawState
from cbus_toolkit.edlt_template_staging import TemplatePpSnapshot
from cbus_toolkit.edlt_template_reset_prelude import (
    EdltTemplateResetPrelude, TemplateResetPreludeError, TemplateResetPreludeApplyRefused,
)
from tests.test_edlt_reset import fixture, metadata


class ResetPreludeTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        raw = _RawState(self.spec.defaults()).raw()
        raw.update(NavWidgetType='0x1', Widget6WidgetType='0x2',
                   Widget6WidgetByteValue6='0x2A', Widget6RestoreLevel='0xad',
                   EnableLevelStore='0x1')
        self.source = TemplatePpSnapshot([(name, value.split(' '), name == 'UnitAddress')
                                         for name, value in raw.items()])
        self.metadata = ApplicationCache.from_dict(metadata())
        self.editor = EdltTemplateResetPrelude(self.spec)

    def stage(self, **kwargs):
        return self.editor.stage(self.source, **{'metadata': self.metadata, 'active_tab': 'general',
                                                 'binding_variant': 'audited-local-wiring', **kwargs})

    def validate(self, candidate, **kwargs):
        return self.editor.validate(candidate, **{'current_source': self.source, 'metadata': self.metadata,
            'active_tab': 'general', 'binding_variant': 'audited-local-wiring', **kwargs})

    def test_exact_reset_tokens_dirty_flags_and_time_date_postconditions(self):
        candidate = self.stage()
        phase = candidate.phases['after-reset']
        self.assertEqual(candidate.source, self.source)
        self.assertIsNot(candidate.source, self.source)
        self.assertEqual(candidate.after_reset.parameters, tuple(
            (name, phase.tokens[name], name in phase.dirty_parameters) for name in self.spec.parameters))
        self.assertFalse(candidate.after_reset.initializing)
        self.assertEqual(candidate.after_reset.raw['Widget10WidgetType'], '0xA')
        self.assertEqual(candidate.after_reset.raw['Widget10WidgetByteValue1'], '0x2')
        self.assertEqual(candidate.after_reset.raw['Widget10RestoreLevel'], '0x0')
        self.assertEqual(candidate.after_reset.raw['NavWidgetType'], '0x0')
        self.assertIn('UnitAddress', phase.dirty_parameters)
        self.assertTrue(all(w.stored_type == 0 for w in candidate.reset.fresh.widgets))
        self.assertEqual(candidate.reset.widgets[9].model_family, 'TimeAndDateData')
        self.assertEqual(candidate.reset.after_controls, self.editor._reset.snapshot(candidate.after_reset.raw))
        self.assertIs(self.validate(candidate), candidate)

    def test_exactly_two_model_loads_no_terminal_save_no_automatic_assignment_chain(self):
        with patch.object(self.editor._reset.lifecycle, 'load', wraps=self.editor._reset.lifecycle.load) as load, \
             patch.object(self.editor._reset.lifecycle, 'prepare_save', side_effect=AssertionError('save')), \
             patch.object(self.editor._reset, 'plan', side_effect=AssertionError('plan')):
            candidate = self.stage()
            self.validate(candidate)
        self.assertEqual(load.call_count, 2)
        self.assertNotIn('before-save', candidate.phases)
        self.assertNotIn('final', candidate.phases)
        for name in ('OverallCRC', 'GlobalParameterCRC', 'WidgetsCRC', 'StaticTextCRC', 'ScenesCheckSum'):
            self.assertEqual(candidate.after_reset.raw[name], candidate.phases['component-reset-defaults'].raw[name])
        document = candidate.as_dict()
        self.assertEqual(document['model_load_count'], 2)
        for name in ('terminal_before_save_performed', 'terminal_crc_performed', 'third_model_load_performed',
                     'template_assignments_performed', 'post_reset_callbacks_executed', 'assignment_source_attested',
                     'automatic_assignment_chain_available', 'reset_result_boolean_used',
                     'original_reset_result_boolean_observed', 'apply_allowed', 'saved', 'original_form_executed'):
            self.assertIs(document[name], False)
        self.assertEqual(document['callback_obligations_status'], 'unresolved')
        self.assertIn('PopulateWidgetPanels', ' '.join(document['unresolved_callbacks']))
        self.assertIn('BeforeChangePpAttributes', ' '.join(document['unresolved_callbacks']))
        self.assertFalse(candidate.source.initializing)
        self.assertTrue(candidate.phases['input'].initializing)
        self.assertIn('not an arbitrary already-loaded Toolkit history', document['input_scope'])

    def test_original_tab_boundaries_remain_explicit(self):
        for tab in ('widgets', 'general', 'standby', 'colour'):
            for binding in ('base-c3', 'audited-local-wiring'):
                with self.subTest(tab=tab, binding=binding):
                    engine = EdltTemplateResetPrelude(self.spec)
                    candidate = engine.stage(self.source, metadata=self.metadata, active_tab=tab,
                                              binding_variant=binding)
                    self.assertEqual(candidate.after_reset.raw['NavWidgetType'],
                                     '0x0' if tab in ('widgets', 'general') else '0xFF')
                    self.assertEqual('audited-local-wiring' in candidate.phases, binding == 'audited-local-wiring')

    def test_source_spec_cache_and_control_context_are_bound(self):
        candidate = self.stage()
        for kwargs in ({'active_tab': 'widgets'}, {'binding_variant': 'base-c3'}):
            with self.assertRaisesRegex(EdltError, 'changed since Reset prelude'):
                self.validate(candidate, **kwargs)
        changed = self.metadata.as_dict()
        changed['applications'][0]['name'] = 'Changed name'
        with self.assertRaisesRegex(EdltError, 'changed since Reset prelude'):
            self.validate(candidate, metadata=ApplicationCache.from_dict(changed))
        source = TemplatePpSnapshot([(name, tokens, not dirty if name == 'UnitAddress' else dirty)
                                      for name, tokens, dirty in self.source.parameters])
        with self.assertRaisesRegex(EdltError, 'changed since Reset prelude'):
            self.validate(candidate, current_source=source)
        self.spec.parameters['UnitName'].fields['DefaultValue'] = 'CHANGED '
        with self.assertRaisesRegex(EdltError, 'Specification changed'):
            self.validate(candidate)

    def test_receipt_and_nested_phase_immutability_and_detached_diagnostics(self):
        candidate = self.stage()
        with self.assertRaises(FrozenInstanceError): candidate.active_tab = 'widgets'
        with self.assertRaises(TypeError): candidate.phases['after-reset'] = None
        with self.assertRaises(TypeError): candidate.phases['after-reset'].tokens['Widget10WidgetType'] = ('0',)
        report = candidate.as_dict()
        report['unresolved_callbacks'].clear()
        report['after_reset']['parameters'].clear()
        self.assertEqual(len(candidate.after_reset.parameters), 874)
        self.assertIs(self.validate(candidate), candidate)

    def test_foreign_cloned_and_mutated_graph_receipts_are_rejected(self):
        candidate = self.stage()
        for bad in (replace(candidate), candidate.as_dict(), None):
            with self.assertRaisesRegex(EdltError, 'intact active Reset'):
                self.validate(bad)
        foreign = EdltTemplateResetPrelude(self.spec)
        with self.assertRaisesRegex(EdltError, 'intact active Reset'):
            foreign.validate(candidate, current_source=self.source, metadata=self.metadata,
                             active_tab='general', binding_variant='audited-local-wiring')
        old = candidate.reset.widgets
        object.__setattr__(candidate.reset, 'widgets', (*old[:9], replace(old[9]), *old[10:]))
        with self.assertRaisesRegex(EdltError, 'issued phases or retained graph'):
            self.validate(candidate)

    def test_postconditions_detect_corrupted_time_date_and_default_phase_without_boolean(self):
        for changed_phase, name, value in (
            ('after-reset', 'Widget10WidgetType', ('0x0',)),
            ('component-reset-defaults', 'EnableLevelStore', ('0x1',)),
            ('component-zero-byte1', 'Widget1WidgetByteValue1', ('0x1',)),
        ):
            with self.subTest(phase=changed_phase):
                engine = EdltTemplateResetPrelude(self.spec)
                prepare = engine._reset.prepare_unit_reset
                def corrupted(*args, **kwargs):
                    result = prepare(*args, **kwargs)
                    phase = result[3].raw_phases[changed_phase]
                    object.__setattr__(phase, 'tokens', {**phase.tokens, name: value})
                    return result
                with patch.object(engine._reset, 'prepare_unit_reset', side_effect=corrupted):
                    with self.assertRaises(TemplateResetPreludeError) as caught:
                        engine.stage(self.source, metadata=self.metadata, active_tab='general',
                                     binding_variant='audited-local-wiring')
                self.assertEqual(caught.exception.details['phase'], 'reset_postconditions')
                self.assertFalse(caught.exception.details['candidate_published'])
                self.assertIsNone(engine.candidate)

    def test_changed_reset_context_cannot_issue_falsely_source_bound_receipt(self):
        prepare = self.editor._reset.prepare_unit_reset
        def unrelated(*args, **kwargs):
            result = prepare(*args, **kwargs)
            object.__setattr__(result[3].context, 'expected_raw', {**result[3].context.expected_raw, 'UnitName': 'OTHER   '})
            return result
        with patch.object(self.editor._reset, 'prepare_unit_reset', side_effect=unrelated):
            with self.assertRaisesRegex(TemplateResetPreludeError, 'supplied source/cache/control'):
                self.stage()
        self.assertIsNone(self.editor.candidate)

    def test_unsupported_initial_context_is_refused_without_rewriting_navigation(self):
        for field, value in (('NavWidgetType', '0xFF'), ('Widget6WidgetType', '0x3')):
            rows = [(name, (value,) if name == field else tokens, dirty)
                    for name, tokens, dirty in self.source.parameters]
            source = TemplatePpSnapshot(rows)
            engine = EdltTemplateResetPrelude(self.spec)
            with self.assertRaises(TemplateResetPreludeError):
                engine.stage(source, metadata=self.metadata, active_tab='general', binding_variant='base-c3')
            self.assertEqual(source.raw[field], value)
            self.assertIsNone(engine.candidate)

    def test_source_order_initializing_and_hidden_tokens_rejected(self):
        hidden = [(name, ('', *tokens) if name == 'UnitAddress' else tokens, dirty)
                  for name, tokens, dirty in self.source.parameters]
        for source in (TemplatePpSnapshot(tuple(reversed(self.source.parameters))),
                       TemplatePpSnapshot(self.source.parameters, True), TemplatePpSnapshot(hidden)):
            engine = EdltTemplateResetPrelude(self.spec)
            with self.assertRaises(TemplateResetPreludeError) as caught:
                engine.stage(source, metadata=self.metadata, active_tab='general', binding_variant='base-c3')
            self.assertEqual(caught.exception.details['phase'], 'input_validation')
            self.assertIsNone(engine.candidate)

    def test_cancel_and_interrupt_never_publish_or_resume(self):
        candidate = self.stage()
        cancelled = self.editor.cancel()
        self.assertFalse(cancelled['original_cancel_replayed'])
        self.assertIsNone(self.editor.candidate)
        with self.assertRaises(EdltError): self.validate(candidate)
        with self.assertRaises(EdltError): self.stage()
        engine = EdltTemplateResetPrelude(self.spec)
        error = KeyboardInterrupt('owned interruption')
        with patch.object(engine._reset, 'prepare_unit_reset', side_effect=error):
            with self.assertRaises(KeyboardInterrupt) as caught:
                engine.stage(self.source, metadata=self.metadata, active_tab='general', binding_variant='base-c3')
        self.assertIs(caught.exception, error)
        self.assertFalse(error.edlt_template_reset_prelude_evidence['candidate_published'])
        self.assertEqual(engine.state, 'failed')
        self.assertIsNone(engine.candidate)

    def test_apply_always_refuses_before_target_access(self):
        candidate = self.stage()
        class Target:
            def __getattribute__(self, name): raise AssertionError('target accessed: ' + name)
        for apply in (self.editor.apply, candidate.apply):
            with self.assertRaises(TemplateResetPreludeApplyRefused) as caught:
                apply(Target())
            self.assertFalse(caught.exception.details['target_mutation_attempted'])
            self.assertFalse(caught.exception.details['assignment_source_attested'])

    def test_profile_and_complete_original_reset_schema_required(self):
        for options in ({'firmware': '5.5.01'}, {'catalog_number': '5055EDL2'}):
            with self.assertRaises(EdltError): EdltTemplateResetPrelude(self.spec, **options)
        parameters = dict(self.spec.parameters)
        parameters.pop('OwnedPadding873')
        with self.assertRaises(EdltError): EdltTemplateResetPrelude(replace(self.spec, parameters=parameters))

    def test_lifecycle_pointer_cannot_change_after_receipt_issue(self):
        candidate = self.stage()
        self.editor._reset.lifecycle = EdltLifecycle(self.editor._spec)
        with self.assertRaisesRegex(EdltError, 'Specification changed'):
            self.validate(candidate)

    def test_candidate_property_never_exposes_a_nonstaged_receipt(self):
        candidate = self.stage()
        self.editor._state = 'staging'
        self.assertIsNone(self.editor.candidate)
        self.editor._state = 'staged'
        self.assertIs(self.editor.candidate, candidate)


if __name__ == '__main__':
    unittest.main()
