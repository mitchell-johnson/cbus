"""Retained model-state invariants and the exact accepted pre-refactor outputs."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_lifecycle import EdltLifecycle, LoadedEdlt, LifecycleMetadataError
from tests.test_edlt import Session
from tests.test_edlt_lifecycle import fixture, cache, literal_cases, scene_values

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'research/fixtures/edlt-lifecycle-refactor-baseline.json'
BASELINE_SHA256 = 'b704ab50770d9e0b543bb29712d9232531f7b489a1d958965defa8e2811c694c'


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                   separators=(',', ':')).encode()).hexdigest()


class LoadedModelTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltLifecycle(self.spec)
        self.original = self.editor.snapshot(Session(self.spec).values())

    def load(self, source=None, mode='complete'):
        source = self.original if source is None else source
        return self.editor.load(source, metadata=cache(self.editor, source, mode))

    def test_private_missing_action_stays_minus_one_until_save(self):
        source = {**self.original, **scene_values()}
        loaded = self.load(source, 'missing-level2')
        self.assertEqual(loaded.scenes[0].action_selector, -1)
        self.assertEqual(loaded.scenes[0].trigger.group, 42)
        self.assertIn(0, loaded.scenes[0].trigger.levels)
        self.assertEqual(loaded.after_load['SceneBucket'][:5], (2, 0, 42, 2, 26))
        plan = self.editor.prepare_save(loaded)
        self.assertEqual(plan.before_save['SceneBucket'][:5], (2, 0, 42, 0, 26))
        self.assertEqual(loaded.scenes[0].action_selector, -1)
        loaded = self.load(source, 'missing-level0-and2')
        self.assertEqual(loaded.scenes[0].action_selector, -1)
        self.assertEqual(self.editor.prepare_save(loaded).before_save['SceneBucket'][3], 255)
        default = self.load()
        self.assertEqual([s.action_selector for s in default.scenes], [-1] * 8)
        self.assertEqual([s.trigger.group for s in default.scenes], [255] * 8)

    def test_scene_items_share_cached_identity_but_scenes_remain_distinct(self):
        source = {**self.original, **scene_values((3, 2, 42, 2, 26),
                    ((0xf1, 12, 123), (0x04, 12, 45)), Scene2StartAddress=(0,))}
        loaded = self.load(source)
        first, second = loaded.scenes[:2]
        self.assertIsNot(first, second)
        self.assertEqual((first.slot, second.slot), (1, 2))
        self.assertEqual((first.source_pointer, second.source_pointer), (0, 0))
        self.assertEqual(first.primary_secondary, 1)
        reference = loaded.metadata.find(57, 12)
        self.assertIs(first.items[0].group, reference)
        self.assertIs(first.items[1].group, reference)
        self.assertIs(second.items[0].group, reference)
        self.assertEqual((first.items[0].ramp_rate, first.items[0].can_edit, first.items[0].level), (1, True, 123))
        self.assertEqual((first.items[1].ramp_rate, first.items[1].can_edit, first.items[1].level), (4, False, 45))
        plan = self.editor.prepare_save(loaded)
        self.assertEqual(plan.before_save['SceneBucket'][:11], (3, 2, 42, 2, 26, 17, 12, 123, 4, 12, 45))
        self.assertEqual(first.items[0].group.application, 57)

    def test_stored_unknown_type_is_distinct_from_actual_blank_model(self):
        source = {**self.original, 'Widget6WidgetType': (127,), 'Widget6RestoreLevel': (173,),
                  'Widget7WidgetType': (255,), 'Widget8WidgetType': (2,), 'Widget8RestoreLevel': (88,)}
        loaded = self.load(source)
        self.assertEqual(len(loaded.widgets), 21)
        widget = loaded.widgets[5]
        self.assertEqual((widget.original_type, widget.stored_type, widget.model_family), (127, 127, 'BlankData'))
        hidden = loaded.widgets[7]
        self.assertEqual((hidden.original_type, hidden.stored_type, hidden.model_family), (2, 0, 'BlankData'))
        self.assertEqual(loaded.after_load['Widget8RestoreLevel'], (0,))
        self.assertEqual(loaded.page_widget.as_dict()['identity'], 'page-widget')
        self.assertEqual(loaded.page_widget.stored_variant, 255)
        plan = self.editor.prepare_save(loaded)
        self.assertEqual(plan.before_save['Widget6RestoreLevel'], (173,))
        self.assertEqual(plan.before_save['Widget6WidgetType'], (127,))

    def test_mra_globals_are_loaded_from_surviving_models_only(self):
        source = {**self.original, 'Widget2WidgetType': (7,), 'Widget2WidgetByteValue1': (0xed,),
                  'Widget6WidgetType': (8,), 'Widget6WidgetByteValue1': (0x12,),
                  'Widget7WidgetType': (255,), 'Widget8WidgetType': (9,), 'Widget8WidgetByteValue1': (0x53,)}
        loaded = self.load(source)
        self.assertEqual(loaded.mra.as_dict(), {'source_widget': 2, 'multiplexer': 3, 'zone': 5})
        self.assertEqual(self.editor.prepare_save(loaded).before_save['Widget6WidgetByteValue1'], (0xea,))
        self.assertEqual(self.editor.prepare_save(loaded).before_save['Widget8WidgetByteValue1'], (0x53,))
        self.assertEqual(self.load().mra.as_dict(), {'source_widget': None, 'multiplexer': 0, 'zone': 0})

    def test_diagnostics_preserve_raw_static_bytes_and_invoke_no_dependency_getter(self):
        source = {**self.original, 'StaticTextString0': tuple(b'\xff\xfe\0'.ljust(64, b'\0')),
                  'StaticTextString1': tuple('Café'.encode().ljust(64, b'\0'))}
        loaded = self.load(source)
        before = self.editor.prepare_save(loaded).as_dict()
        first = loaded.as_dict()
        self.assertIsNone(first['static_labels'][0]['valid_utf8_text'])
        self.assertEqual(first['static_labels'][1]['valid_utf8_text'], 'Café')
        self.assertFalse(first['static_labels'][0]['original_invalid_utf8_text_evaluated'])
        self.assertEqual(first['bound_controls'], [])
        first['scenes'][0]['stored_action_selector'] = 123
        self.assertEqual(loaded.scenes[0].action_selector, -1)
        self.assertEqual(self.editor.prepare_save(loaded).as_dict(), before)
        self.assertEqual(loaded.static_labels[0].original_bytes, source['StaticTextString0'])

    def test_prepare_save_does_not_load_reparse_or_resolve_metadata_again(self):
        source = {**self.original, **scene_values((3, 1, 42, 2, 26), ((1, 12, 123),))}
        loaded = self.load(source)
        with patch.object(self.editor, 'load', side_effect=AssertionError('second load')), \
             patch.object(self.editor, '_scenes', side_effect=AssertionError('second scene parse')), \
             patch.object(type(loaded.metadata), 'find', side_effect=AssertionError('metadata re-resolution')):
            first = self.editor.prepare_save(loaded)
            second = self.editor.prepare_save(loaded)
        self.assertEqual(first, second)
        self.assertEqual(loaded.after_load['SceneCount'], (0,))
        self.assertEqual(first.before_save['SceneCount'], (8,))

    def test_state_is_deeply_immutable_and_foreign_or_replaced_state_is_rejected(self):
        supplied = cache(self.editor, self.original)
        loaded = self.editor.load(self.original, metadata=supplied)
        supplied['groups'].clear()
        self.assertGreater(len(loaded.metadata.groups), 0)
        with self.assertRaises(TypeError): loaded.after_load['NavWidgetType'] = (0,)
        with self.assertRaises(FrozenInstanceError): loaded.scenes[0].action_selector = 3
        with self.assertRaises(FrozenInstanceError): loaded.metadata.groups[0].exists = False
        with self.assertRaisesRegex(EdltError, 'intact loaded model'):
            self.editor.prepare_save(replace(loaded, after_load={**loaded.after_load, 'NavWidgetType': (0,)}))
        with self.assertRaisesRegex(EdltError, 'intact loaded model'):
            EdltLifecycle(self.spec).prepare_save(loaded)
        with self.assertRaisesRegex(EdltError, 'intact loaded model'):
            self.editor.prepare_save(loaded.as_dict())
        self.assertIsInstance(loaded, LoadedEdlt)

    def test_existing_preflight_failure_stage_is_preserved(self):
        source = {**self.original, **scene_values((2, 1, 42, 2, 26), ((0, 99, 123),))}
        with self.assertRaises(LifecycleMetadataError) as caught: self.load(source)
        self.assertEqual(caught.exception.original_stage, 'before_save')
        self.assertEqual(caught.exception.fact['application'], 56)
        self.assertEqual(caught.exception.fact['group'], 99)

    def test_unprintable_primary_error_cannot_replace_rollback_interrupt(self):
        class Unprintable(RuntimeError):
            def __str__(self): raise SystemExit('error formatting interrupted')
        primary = Unprintable()
        interrupted = KeyboardInterrupt('owned rollback interrupt')
        session = Session(self.spec)
        plan = self.editor.plan(self.original, metadata=cache(self.editor, self.original))
        calls = []
        def fail(name, value):
            calls.append(name)
            if len(calls) == 1: raise primary
            raise interrupted
        session.set = fail
        with self.assertRaises(KeyboardInterrupt) as caught: self.editor.apply(session, plan)
        self.assertIs(caught.exception, interrupted)
        self.assertEqual(len(calls), 2)
        self.assertEqual(interrupted.edlt_lifecycle_evidence['original_error'],
                         {'type': 'Unprintable', 'error': '<unprintable Unprintable>'})
        self.assertTrue(interrupted.edlt_lifecycle_evidence['pp_state_uncertain'])


class LifecycleBackwardEquivalenceTests(unittest.TestCase):
    def test_all_76_cases_and_2048_enable_combinations_match_frozen_outputs(self):
        raw = BASELINE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), BASELINE_SHA256)
        baseline = json.loads(raw)
        self.assertEqual(baseline['baseline_source_sha256'], '20aceb0b0165af23b97f9b7da3ef91c45a918d11e3131c5185a13fc5f8142ba5')
        expected = {row['case']: row for row in baseline['records']}
        self.assertEqual(len(expected), 2124)
        editor = EdltLifecycle(fixture())
        original = editor.snapshot(Session(fixture()).values())
        observed = set()
        def one(name, values, mode):
            row = expected[name]; observed.add(name)
            self.assertEqual(sha(values), row['input_sha256'], name)
            try: metadata = cache(editor, values, mode)
            except Exception as error:
                self.assertEqual({'type': type(error).__name__, 'error': str(error)}, row['requirements_error'], name)
                return
            self.assertEqual(sha(metadata), row['metadata_sha256'], name)
            try: result = {'plan': editor.plan(values, metadata=metadata).as_dict()}
            except Exception as error:
                result = {'type': type(error).__name__, 'error': str(error), 'details': getattr(error, 'details', None)}
            self.assertEqual(sha(result), row['result_sha256'], name)
        for label, edits, mode, negative in literal_cases(): one(label, {**original, **edits}, mode)
        for widget in (6, 7):
            for left in range(32):
                for right in range(32):
                    one(f'enable-{widget}-{left}-{right}', {**original, f'Widget{widget}WidgetType': (14,),
                        f'Widget{widget}WidgetByteValue7': (left,), f'Widget{widget}WidgetByteValue8': (right,),
                        f'Widget{widget}WidgetByteValue9': (42,)}, 'complete')
        self.assertEqual(observed, set(expected))


if __name__ == '__main__': unittest.main()
