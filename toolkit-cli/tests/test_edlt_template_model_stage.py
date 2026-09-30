"""Post-assignment model stage: immutable inputs, graph rebuild and no I/O."""
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_lifecycle import EdltLifecycle, LifecycleCache, LifecycleMetadataError
from cbus_toolkit.edlt_reset import EdltResetControls, _RawState
from cbus_toolkit.edlt_template_model_stage import (
    EdltTemplateModelStage, SecondModelLoadStage, stage_second_model_load,
)
from cbus_toolkit.edlt_template_staging import EdltTemplateAssignmentTransaction, TemplatePpSnapshot
from tests.test_edlt_reset import fixture, metadata
from tests.test_edlt_template_staging import template


class SecondModelStageTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.raw = _RawState(self.spec.defaults()).raw()
        self.cache = LifecycleCache.from_dict(metadata()['lifecycle'])
        self.editor = EdltTemplateModelStage(self.spec)

    def stage(self, raw=None, **kwargs):
        return self.editor.stage(self.raw if raw is None else raw,
                                 metadata=self.cache, **kwargs)

    def test_second_model_load_normalizes_raw_and_keeps_before_image(self):
        self.raw.update(PrimaryApplication='0xff', InvertDisplay='1',
                        Widget6WidgetType='1', Widget6RestoreLevel='0x00')
        stage = self.stage(dirty_parameters=['UnitAddress'])
        self.assertEqual(stage.raw_before['PrimaryApplication'], '0xff')
        self.assertEqual(stage.raw_after_load['PrimaryApplication'], '0x38')
        self.assertEqual(stage.raw_after_load['InvertDisplay'], '0x0')
        self.assertEqual(stage.raw_after_load['Widget6WidgetType'], '0x0')
        self.assertEqual(stage.raw_after_load['Widget6RestoreLevel'], '0x0')
        self.assertIn('Widget6RestoreLevel', stage.dirty_after_load)
        self.assertIn('UnitAddress', stage.dirty_after_load)
        self.assertEqual(stage.dirty_before, ('UnitAddress',))
        self.assertEqual(self.raw['Widget6RestoreLevel'], '0x00')
        self.assertEqual(stage.before['PrimaryApplication'], (255,))
        self.assertEqual(stage.after_load['PrimaryApplication'], (56,))
        self.assertEqual(stage.after_load['SceneCount'], stage.before['SceneCount'])
        self.assertEqual(stage.after_load['OverallCRC'], stage.before['OverallCRC'])
        self.assertIs(self.editor.validate(stage, self.raw, metadata=self.cache,
                                           dirty_parameters=['UnitAddress']), stage)

    def test_rebuilds_fresh_graph_with_new_assignments_and_explicit_cache(self):
        self.raw.update(Widget6WidgetType='0x2', Widget6WidgetByteValue6='0x2A')
        first = self.stage()
        second_raw = {**first.raw_after_load, 'Widget6WidgetType': '0x7',
                      'Widget6WidgetByteValue1': '0xED'}
        second = self.stage(second_raw)
        self.assertEqual(first.loaded.widgets[5].model_family, 'LightingData')
        self.assertEqual(second.loaded.widgets[5].model_family, 'MRAZoneControlData')
        self.assertEqual(second.loaded.mra.source_widget, 6)
        self.assertEqual((second.loaded.mra.multiplexer, second.loaded.mra.zone), (3, 5))
        self.assertTrue(all(a is not b for a, b in zip(first.loaded.widgets, second.loaded.widgets)))
        self.assertTrue(all(a is not b for a, b in zip(first.loaded.scenes, second.loaded.scenes)))
        self.assertTrue(all(a is not b for a, b in zip(first.loaded.static_labels, second.loaded.static_labels)))
        self.assertIsNot(first.loaded.page_widget, second.loaded.page_widget)
        self.assertIsNot(first.loaded.metadata, second.loaded.metadata)
        self.assertEqual(first.raw_before['Widget6WidgetType'], '0x2')
        self.assertIs(self.editor.validate(first, self.raw, metadata=self.cache), first)

    def test_model_matches_independent_existing_lifecycle_and_raw_projection(self):
        self.raw.update(Widget2WidgetType='0x7', Widget2WidgetByteValue1='0xED',
                        Widget6WidgetType='0x2', Widget6WidgetByteValue1='0x20',
                        Widget6WidgetByteValue6='0x2A', Widget8WidgetType='0xE',
                        Widget8WidgetByteValue9='0x2A', Widget8RestoreLevel='0xAD')
        stage = self.stage()
        expected = EdltLifecycle(self.spec).load(self.raw, metadata=self.cache)
        self.assertEqual(stage.loaded.as_dict(), expected.as_dict())
        self.assertEqual(json.loads(stage.model_snapshot), expected.as_dict())
        self.assertEqual(dict(stage.after_load), dict(expected.after_load))
        self.assertEqual(self.editor.snapshot(stage.raw_after_load), dict(expected.after_load))

    def test_load_runs_once_and_never_calls_reset_controls_or_before_save(self):
        with patch.object(self.editor._lifecycle, 'load', wraps=self.editor._lifecycle.load) as load, \
             patch.object(self.editor._lifecycle, 'prepare_save', side_effect=AssertionError('save')), \
             patch.object(EdltResetControls, '_transition', side_effect=AssertionError('reset')):
            stage = self.stage()
            self.editor.validate(stage, self.raw, metadata=self.cache)
            stage.as_dict()
        self.assertEqual(load.call_count, 1)
        self.assertFalse(hasattr(self.editor, 'apply'))

    def test_receipt_describes_narrow_boundary_without_whole_parent_claim(self):
        result = self.stage().as_dict()
        for key in ('apply_allowed', 'mutation_attempted', 'saved', 'physical_device_verified',
                    'complete_parent_lifecycle_verified', 'cache_freshness_verified',
                    'caller_boundary_provenance_verified', 'original_token_arrays_reconstructed',
                    'model_state_resumption_supported'):
            self.assertIs(result[key], False)
        self.assertIn('SetupForm', result['unexecuted_phases'])
        self.assertIn('BeforeSavePPData', result['unexecuted_phases'])
        self.assertEqual(result['model']['bound_controls'], [])
        for key in ('specification_sha256', 'source_sha256', 'cache_sha256', 'dirty_sha256'):
            self.assertRegex(result[key], r'^[a-f0-9]{64}$')

    def test_copied_immutable_raw_numeric_and_model_diagnostics(self):
        stage = self.stage()
        with self.assertRaises(FrozenInstanceError):
            stage.source_sha256 = 'changed'
        for values in (stage.raw_before, stage.raw_after_load, stage.before, stage.after_load):
            with self.assertRaises(TypeError): values['Widget6WidgetType'] = 'changed'
        diagnostic = stage.as_dict()
        diagnostic['raw_before']['Widget6WidgetType'] = 'changed'
        diagnostic['model']['widgets'][5]['model_family'] = 'changed'
        self.assertNotEqual(stage.loaded.widgets[5].model_family, 'changed')
        self.assertIs(self.editor.validate(stage, self.raw, metadata=self.cache), stage)
        self.raw['Widget6WidgetType'] = '0x2'
        self.assertEqual(stage.raw_before['Widget6WidgetType'], '0xFF')

    def test_clone_foreign_and_deserialized_receipts_refused(self):
        stage = self.stage()
        for bad in (replace(stage), stage.as_dict(), None):
            with self.assertRaisesRegex(EdltError, 'intact second-model'):
                self.editor.validate(bad, self.raw, metadata=self.cache)
        foreign = EdltTemplateModelStage(self.spec)
        with self.assertRaisesRegex(EdltError, 'intact second-model'):
            foreign.validate(stage, self.raw, metadata=self.cache)

    def test_same_numeric_values_with_changed_raw_spelling_refused(self):
        stage = self.stage()
        changed = {**self.raw, 'Widget6WidgetType': '255'}
        self.assertEqual(self.editor.snapshot(changed), dict(stage.before))
        with self.assertRaisesRegex(EdltError, 'changed since model staging'):
            self.editor.validate(stage, changed, metadata=self.cache)

    def test_changed_cache_and_dirty_facts_refused_even_when_unconsumed(self):
        stage = self.stage()
        data = self.cache.as_dict()
        data['groups'][0]['levels'].append(77)
        changed = LifecycleCache.from_dict(data)
        with self.assertRaisesRegex(EdltError, 'changed since model staging'):
            self.editor.validate(stage, self.raw, metadata=changed)
        with self.assertRaisesRegex(EdltError, 'changed since model staging'):
            self.editor.validate(stage, self.raw, metadata=self.cache, dirty_parameters=['UnitAddress'])

    def test_spec_changes_invalidate_session_and_cannot_affect_copied_model(self):
        stage = self.stage()
        self.spec.parameters['UnitName'].fields['DefaultValue'] = 'CHANGED '
        with self.assertRaisesRegex(EdltError, 'Specification changed'):
            self.editor.validate(stage, self.raw, metadata=self.cache)
        with self.assertRaisesRegex(EdltError, 'Specification changed'):
            self.stage()
        self.assertEqual(stage.raw_before['UnitName'], 'NEWUNIT ')

    def test_identical_replacement_graph_and_mutated_receipt_refused(self):
        stage = self.stage()
        original = stage.loaded.widgets
        object.__setattr__(stage.loaded, 'widgets', (replace(original[0]), *original[1:]))
        with self.assertRaisesRegex(EdltError, 'issued model'):
            self.editor.validate(stage, self.raw, metadata=self.cache)
        stage = self.stage()
        object.__setattr__(stage, 'model_snapshot', '{}')
        with self.assertRaisesRegex(EdltError, 'issued model'):
            self.editor.validate(stage, self.raw, metadata=self.cache)

    def test_missing_cache_failure_does_not_mutate_input_or_dirty_state(self):
        before = dict(self.raw)
        dirty = ['UnitAddress']
        cache = LifecycleCache(tuple(a for a in self.cache.applications if a != 203),
            tuple(g for g in self.cache.groups if g.application != 203))
        with self.assertRaises(LifecycleMetadataError):
            self.editor.stage(self.raw, metadata=cache, dirty_parameters=dirty)
        self.assertEqual(self.raw, before)
        self.assertEqual(dirty, ['UnitAddress'])
        self.assertEqual(self.stage().raw_before, before)

    def test_partial_raw_projection_failure_publishes_nothing_and_preserves_inputs(self):
        before = dict(self.raw)
        def fail(_editor, state, _loaded):
            state.integer('Widget6WidgetType', 7)
            raise RuntimeError('injected raw projection failure')
        with patch.object(EdltResetControls, '_raw_load', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                self.stage()
        self.assertEqual(self.raw, before)
        self.assertEqual(self.stage().raw_before, before)

    def test_profile_requires_exact_catalogue_firmware_and_existing_layout(self):
        for kwargs in ({'catalog_number': '5055EDL2'}, {'firmware': '5.5.01'},
                       {'firmware': '5.4.00'}, {'catalog_number': None}):
            with self.assertRaises(EdltError): EdltTemplateModelStage(self.spec, **kwargs)
        for spec in (replace(self.spec, filename='OTHER.xml'),
                     replace(self.spec, metadata={'Type': 'KEYB4'})):
            with self.assertRaises(EdltError): EdltTemplateModelStage(spec)
        parameters = dict(self.spec.parameters)
        parameters['InvertDisplay'] = replace(parameters['InvertDisplay'], fields={
            **parameters['InvertDisplay'].fields, 'BitAddress': '4'})
        with self.assertRaises(EdltError): EdltTemplateModelStage(replace(self.spec, parameters=parameters))

    def test_requires_full_bounded_strict_raw_values_and_explicit_cache(self):
        for bad in ({}, {**self.raw, 'Unknown': '0'}, {k: v for k, v in self.raw.items() if k != 'UnitName'}):
            with self.assertRaises(EdltError): self.stage(bad)
        for value in (True, (1,), '0x1\n', '0x1  0x2', '0b1', '$01', '-1', '0' * 8193):
            with self.subTest(value=str(value)[:20]), self.assertRaises(EdltError):
                self.stage({**self.raw, 'EnableLevelStore': value})
        for cache in (None, self.cache.as_dict()):
            with self.assertRaisesRegex(EdltError, 'explicit LifecycleCache'):
                self.editor.stage(self.raw, metadata=cache)

    def test_rejects_raw_string_token_loss_instead_of_normalizing_it_silently(self):
        for text in (' A ', '   ', '$AB'):
            with self.subTest(text=text), self.assertRaisesRegex(EdltError, 'token information'):
                self.stage({**self.raw, 'UnitName': text})
        stage = self.stage({**self.raw, 'UnitName': 'A   '})
        self.assertEqual(stage.raw_after_load['UnitName'], 'A   ')

    def test_dirty_input_validation_and_canonical_set_fingerprint(self):
        for dirty in (['UnitAddress', 'UnitAddress'], [True], ['unknown'], {'UnitAddress'}):
            with self.assertRaises(EdltError): self.stage(dirty_parameters=dirty)
        stage = self.stage(dirty_parameters=['UnitName', 'UnitAddress'])
        self.assertEqual(stage.dirty_before, ('UnitAddress', 'UnitName'))
        self.assertIs(self.editor.validate(stage, self.raw, metadata=self.cache,
            dirty_parameters=['UnitAddress', 'UnitName']), stage)

    def test_one_shot_wrapper_returns_the_same_diagnostic_with_no_apply_path(self):
        first = self.stage()
        second = stage_second_model_load(self.spec, self.raw, metadata=self.cache)
        self.assertIsInstance(second, SecondModelLoadStage)
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertIsNot(first.loaded, second.loaded)

    def test_original_repeat_load_raw_deltas_dirty_sets_and_model_contents(self):
        path = Path(__file__).resolve().parents[1] / 'research/fixtures/edlt-template-model-original-vectors.json'
        vectors = json.loads(path.read_text())
        self.assertFalse(vectors['original_form_executed'])
        self.assertFalse(vectors['original_reset_executed'])
        self.assertFalse(vectors['original_apply_executed'])
        self.assertFalse(vectors['private_baseline_included'])
        numeric = self.editor.snapshot(self.raw)
        initial = {name: ' '.join(hex(n) for n in value) if isinstance(value, tuple) else value
                   for name, value in numeric.items()}
        initial.update(vectors['portable_initial_overrides'])
        first = self.stage(initial)
        self.assertEqual(len(first.raw_after_load), 874)
        successes = failures = 0
        for case in vectors['cases']:
            with self.subTest(case=case['id']):
                # Compare shared synthetic deltas, not private baseline hashes.
                self.assertEqual(first.as_dict()['raw_changes'], case['stages']['first']['raw_delta'])
                source = TemplatePpSnapshot([(name, value.split(' '), name in first.dirty_after_load)
                                             for name, value in first.raw_after_load.items()])
                assigned = EdltTemplateAssignmentTransaction(source).stage(template(case['assignments']))
                delta = {name: {'before': source.raw[name], 'after': value}
                         for name, value in assigned.after.raw.items() if value != source.raw[name]}
                self.assertEqual(delta, case['stages']['assigned']['raw_delta'])
                dirty = tuple(name for name, _tokens, dirty in assigned.after.parameters if dirty)
                if 'second' not in case['stages']:
                    with self.assertRaises(EdltError):
                        self.stage(assigned.after.raw, dirty_parameters=dirty)
                    self.assertEqual(first.raw_after_load, source.raw)
                    failures += 1
                    continue
                second = self.stage(assigned.after.raw, dirty_parameters=dirty)
                expected = case['stages']['second']
                self.assertEqual(second.as_dict()['raw_changes'], expected['raw_delta'])
                self.assertEqual(set(second.dirty_after_load), set(expected['state']['dirty'].split(',')))
                model = second.loaded
                self.assertEqual(','.join(f'{w.stored_type}:{w.model_family}' for w in model.widgets),
                                 expected['model']['widgets'])
                self.assertEqual(f'{model.mra.multiplexer},{model.mra.zone}', expected['model']['mra'])
                self.assertEqual(len(model.widgets), int(expected['model']['widget-count']))
                self.assertEqual(len(model.scenes), int(expected['model']['scene-count']))
                self.assertEqual(len(model.static_labels), int(expected['model']['labels-count']))
                self.assertEqual(','.join(f'{s.slot}:{s.primary_secondary}:{s.name_index}:{len(s.items)}'
                                           for s in model.scenes), expected['model']['scenes'])
                for name, pairs in (
                    ('widget', zip(first.loaded.widgets, model.widgets)),
                    ('scene', zip(first.loaded.scenes, model.scenes)),
                    ('label', zip(first.loaded.static_labels, model.static_labels)),
                ):
                    for index, (before, after) in enumerate(pairs, 0 if name == 'label' else 1):
                        self.assertIs(before is after, case['same_identity'][name + str(index)])
                self.assertIs(first.loaded.page_widget is model.page_widget, case['same_identity']['page'])
                # Original mutable BindingLists retain identity; these immutable
                # model snapshots intentionally do not expose WinForms lists.
                self.assertTrue(case['same_identity']['widget-list'])
                self.assertFalse(second.as_dict()['complete_parent_lifecycle_verified'])
                successes += 1
        self.assertEqual((successes, failures), (24, 1))


if __name__ == '__main__':
    unittest.main()
