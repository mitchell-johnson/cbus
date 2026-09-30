"""All-or-nothing local assignment/model composition and cancellation."""
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_lifecycle import LifecycleCache
from cbus_toolkit.edlt_reset import _RawState
from cbus_toolkit.edlt_templates import EdltTemplate, EdltTemplateError
from cbus_toolkit.edlt_template_staging import TemplatePpSnapshot
from cbus_toolkit.edlt_template_model_stage import EdltTemplateModelStage
from cbus_toolkit.edlt_template_lifecycle_stage import (
    EdltTemplateLifecycleStage, TemplateLifecycleStageError, TemplateLifecycleApplyRefused,
)
from tests.test_edlt_reset import fixture, metadata
from tests.test_edlt_template_staging import template


class LifecycleStageTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        raw = _RawState(self.spec.defaults()).raw()
        self.source = TemplatePpSnapshot([(name, value.split(' '), False) for name, value in raw.items()])
        self.cache = LifecycleCache.from_dict(metadata()['lifecycle'])
        self.template = template([('Widget6WidgetType', '0x2'), ('Widget6WidgetByteValue6', '0x2a'),
                                  ('StaticTextString0', '0x41')])
        self.editor = EdltTemplateLifecycleStage(self.spec)

    def stage(self, **kwargs):
        return self.editor.stage(self.template, **{'source': self.source, 'metadata': self.cache, **kwargs})

    def test_assignment_and_fresh_model_published_as_one_immutable_candidate(self):
        candidate = self.stage()
        self.assertEqual(self.editor.state, 'staged')
        self.assertIs(self.editor.candidate, candidate)
        self.assertEqual(candidate.source, self.source)
        self.assertEqual(candidate.assignment.after.raw['Widget6WidgetType'], '0x2')
        self.assertEqual(candidate.second_model.loaded.widgets[5].model_family, 'LightingData')
        self.assertEqual(candidate.second_model.raw_before, candidate.assignment.after.raw)
        self.assertEqual(candidate.second_model.before['StaticTextString0'][:5], (65, 105, 103, 104, 116))
        self.assertIn('StaticTextString0', candidate.second_model.dirty_before)
        self.assertIs(self.editor.validate(candidate, current_source=self.source, metadata=self.cache), candidate)
        with self.assertRaises(EdltTemplateError): self.stage()
        result = candidate.as_dict()
        self.assertTrue(result['local_candidate_published_atomically'])
        self.assertFalse(result['source_boundary_observed_by_this_API'])
        self.assertFalse(result['complete_parent_lifecycle_verified'])
        self.assertFalse(result['apply_allowed'])
        self.assertFalse(result['saved'])

    def test_failed_cache_after_assignment_discards_entire_candidate(self):
        before = self.source.as_dict()
        missing = LifecycleCache(tuple(a for a in self.cache.applications if a != 203),
            tuple(g for g in self.cache.groups if g.application != 203))
        with self.assertRaises(TemplateLifecycleStageError) as caught:
            self.stage(metadata=missing)
        self.assertEqual(caught.exception.details['phase'], 'second_model_load')
        self.assertTrue(caught.exception.details['local_assignment_discarded'])
        self.assertFalse(caught.exception.details['candidate_published'])
        self.assertEqual(self.source.as_dict(), before)
        self.assertIsNone(self.editor.candidate)
        self.assertIsNone(self.editor._assignment.candidate)
        self.assertEqual(self.editor._assignment.state, 'cancelled')
        self.assertEqual(self.editor.state, 'failed')
        with self.assertRaises(EdltTemplateError): self.stage()

    def test_assignment_failure_preserves_completed_step_evidence_and_source(self):
        self.template = template([('Widget6WidgetType', '0x2'), ('Application', '48  202')])
        with self.assertRaises(TemplateLifecycleStageError) as caught:
            self.stage()
        self.assertEqual(caught.exception.details['phase'], 'ordered_assignments')
        self.assertGreater(caught.exception.details['assignment_failure']['completed_child_count'], 0)
        self.assertEqual(self.source.raw['Widget6WidgetType'], '0xFF')
        self.assertIsNone(self.editor.candidate)

    def test_lossy_token_seam_is_refused_before_model_load(self):
        rows = list(self.source.parameters)
        index = next(i for i, row in enumerate(rows) if row[0] == 'UnitAddress')
        name, tokens, dirty = rows[index]
        rows[index] = (name, ('', *tokens), dirty)
        source = TemplatePpSnapshot(rows)
        self.assertEqual(source.raw, self.source.raw)
        with patch.object(self.editor._model, 'stage', side_effect=AssertionError('model must not run')):
            with self.assertRaises(TemplateLifecycleStageError) as caught:
                self.stage(source=source)
        self.assertEqual(caught.exception.details['phase'], 'raw_to_model_seam')
        self.assertIsNone(self.editor.candidate)

    def test_cancel_invalidates_held_receipt_and_discards_local_work(self):
        candidate = self.stage()
        cancel = self.editor.cancel()
        self.assertTrue(cancel['local_candidate_discarded'])
        self.assertFalse(cancel['original_cancel_replayed'])
        self.assertIsNone(self.editor.candidate)
        self.assertIsNone(self.editor._assignment.candidate)
        with self.assertRaisesRegex(EdltTemplateError, 'intact active'):
            self.editor.validate(candidate, current_source=self.source, metadata=self.cache)
        with self.assertRaises(EdltTemplateError): self.stage()
        # A held diagnostic remains immutable/readable but cannot resume.
        self.assertEqual(candidate.second_model.loaded.widgets[5].model_family, 'LightingData')

    def test_cancel_open_stage_is_terminal_and_preserves_no_target_claim(self):
        result = self.editor.cancel()
        self.assertIsNone(result['source_sha256'])
        self.assertFalse(result['target_mutation_attempted'])
        with self.assertRaises(EdltTemplateError): self.stage()

    def test_stale_source_token_order_and_cache_are_refused(self):
        candidate = self.stage()
        reordered = TemplatePpSnapshot(tuple(reversed(self.source.parameters)))
        with self.assertRaisesRegex(EdltTemplateError, 'Source PP tokens'):
            self.editor.validate(candidate, current_source=reordered, metadata=self.cache)
        changed = self.cache.as_dict()
        changed['groups'][0]['levels'].append(77)
        with self.assertRaisesRegex(EdltError, 'changed since model staging'):
            self.editor.validate(candidate, current_source=self.source,
                                 metadata=LifecycleCache.from_dict(changed))

    def test_replaced_and_foreign_candidates_refused(self):
        candidate = self.stage()
        for bad in (replace(candidate), candidate.as_dict(), None):
            with self.assertRaisesRegex(EdltTemplateError, 'intact active'):
                self.editor.validate(bad, current_source=self.source, metadata=self.cache)
        foreign = EdltTemplateLifecycleStage(self.spec)
        with self.assertRaisesRegex(EdltTemplateError, 'intact active'):
            foreign.validate(candidate, current_source=self.source, metadata=self.cache)

    def test_interrupt_during_second_load_discards_assignment_and_propagates(self):
        interruption = KeyboardInterrupt('owned interruption')
        with patch.object(self.editor._model, 'stage', side_effect=interruption):
            with self.assertRaises(KeyboardInterrupt) as caught:
                self.stage()
        self.assertIs(caught.exception, interruption)
        self.assertEqual(interruption.edlt_template_lifecycle_stage_evidence['phase'], 'second_model_load')
        self.assertIsNone(self.editor.candidate)
        self.assertIsNone(self.editor._assignment.candidate)
        self.assertEqual(self.editor.state, 'failed')

    def test_apply_refusal_before_any_target_access_even_with_valid_candidate(self):
        candidate = self.stage()
        class Target:
            def __getattribute__(self, name):
                raise AssertionError('target accessed: ' + name)
        for apply in (self.editor.apply, candidate.apply):
            with self.assertRaises(TemplateLifecycleApplyRefused) as caught:
                apply(Target())
            details = caught.exception.details
            self.assertFalse(details['target_mutation_attempted'])
            self.assertIn('SetupForm', ' '.join(details['blockers']))
            self.assertIn('ResetUnit(true)', ' '.join(details['blockers']))

    def test_failure_diagnostics_are_detached_from_internal_evidence(self):
        with self.assertRaises(TemplateLifecycleStageError) as caught:
            self.stage(metadata=None)
        caught.exception.details['status'] = 'tampered'
        self.editor.last_failure['status'] = 'tampered'
        self.assertEqual(self.editor.last_failure['status'], 'failed')

    def test_cross_firmware_refused_before_assignments_with_original_difference(self):
        other = EdltTemplate(tuple((name, '5.6.00' if name == 'FirmwareVersion' else value)
                                   for name, value in self.template.fields))
        with self.assertRaisesRegex(EdltTemplateError, 'original importer did not enforce'):
            self.editor.stage(other, source=self.source, metadata=self.cache)
        self.assertEqual(self.editor.state, 'open')
        self.assertIsNone(self.editor.candidate)
        self.assertIsNone(self.editor._assignment)

    def test_combined_boundary_matches_original_model_cases_and_discards_malformed_case(self):
        vectors = json.loads((Path(__file__).resolve().parents[1] /
            'research/fixtures/edlt-template-model-original-vectors.json').read_text())
        model = EdltTemplateModelStage(self.spec)
        numeric = model.snapshot(self.source.raw)
        raw = {name: ' '.join(hex(n) for n in value) if isinstance(value, tuple) else value
               for name, value in numeric.items()}
        raw.update(vectors['portable_initial_overrides'])
        first = model.stage(raw, metadata=self.cache)
        source = TemplatePpSnapshot([(name, value.split(' '), name in first.dirty_after_load)
                                     for name, value in first.raw_after_load.items()])
        selected = {'hidden-tail-constructor', 'mra-first-widget', 'retained-array-tail',
                    'scene-replacement', 'second-load-malformed-widget'}
        seen = set()
        for case in vectors['cases']:
            if case['id'] not in selected:
                continue
            seen.add(case['id'])
            with self.subTest(case=case['id']):
                engine = EdltTemplateLifecycleStage(self.spec)
                if 'second' not in case['stages']:
                    with self.assertRaises(TemplateLifecycleStageError):
                        engine.stage(template(case['assignments']), source=source, metadata=self.cache)
                    self.assertIsNone(engine.candidate)
                    self.assertEqual(engine.last_failure['phase'], 'second_model_load')
                    self.assertTrue(engine.last_failure['source_preserved'])
                    continue
                candidate = engine.stage(template(case['assignments']), source=source, metadata=self.cache)
                self.assertEqual(candidate.second_model.as_dict()['raw_changes'],
                                 case['stages']['second']['raw_delta'])
                self.assertEqual(set(candidate.second_model.dirty_after_load),
                                 set(case['stages']['second']['state']['dirty'].split(',')))
                self.assertIs(engine.validate(candidate, current_source=source, metadata=self.cache), candidate)
                self.assertFalse(candidate.as_dict()['apply_allowed'])
        self.assertEqual(seen, selected)


if __name__ == '__main__':
    unittest.main()
