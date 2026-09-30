"""Compare the bounded template Reset prelude to retained original Windows phases.

This consumes local evidence and an explicitly selected private specification.
It never starts an original runtime, connects to C-Gate, or attempts persistence.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt_application_cache import ApplicationCache
from cbus_toolkit.edlt_lifecycle import EdltLifecycle
from cbus_toolkit.edlt_reset import EdltResetControls
from cbus_toolkit.edlt_template_reset_prelude import EdltTemplateResetPrelude
from cbus_toolkit.edlt_template_staging import TemplatePpSnapshot
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt_reset import metadata

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/edlt-reset-windows-vectors.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(os.environ.get('CBUS_UNITSPEC_DIR'),
                     'Select the exact private original Reset specification for local fixture comparison')
class TemplateResetPreludeOriginalTests(unittest.TestCase):
    def test_all44_retained_original_resets_through_after_reset_only(self):
        document = json.loads(FIXTURE.read_text())
        self.assertEqual(document['original_execution_count'], 44)
        self.assertEqual(document['all_parameter_phase_count'], 520)
        spec_path = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve() / 'KEYGL5.xml'
        sources = [Path(__file__).resolve(), FIXTURE, spec_path,
                   ROOT / 'tests/test_edlt_reset.py']
        for source in document['sources']:
            probe = ROOT / 'research' / source['source']
            self.assertEqual(digest(probe), source['source_sha256'])
            self.assertEqual(digest(spec_path), source['input_source_hashes']['KEYGL5.xml'])
            sources.append(probe)
        sources.extend(ROOT / 'src/cbus_toolkit' / (name + '.py') for name in (
            'edlt_template_reset_prelude', 'edlt_template_model_stage', 'edlt_template_staging',
            'edlt_reset', 'edlt_lifecycle', 'edlt_application_cache', 'edlt', 'unitspec'))
        before_hashes = {str(path): digest(path) for path in sources}
        spec = UnitSpecStore(spec_path.parent).load('KEYGL5.xml')
        report = {
            'format': 'cbus-edlt-template-reset-prelude-retained-original-v1',
            'passed': False, 'fixture_sha256': digest(FIXTURE),
            'scope': 'Local comparison of bounded Reset prelude to retained original Windows phases through after-reset only',
            'original_execution_count_in_fixture': 44,
            'fresh_original_runtime_executed': False, 'native_io': False,
            'physical_device_verified': False, 'full_form_verified': False,
            'source_boundary': 'Non-initializing caller snapshot; internal model input initializes before first AfterLoad',
            'terminal_phases_excluded': ['before-save', 'final'],
            'guarded_terminal_calls': [], 'socket_connection_calls': 0,
            'cases': [],
        }
        guarded = (
            (EdltResetControls, 'plan'), (EdltResetControls, 'apply'),
            (EdltResetControls, 'configure'),
            (EdltLifecycle, 'prepare_save'), (EdltLifecycle, '_prepare_composed_save'),
            (EdltLifecycle, '_prepare_save_values'), (EdltLifecycle, 'crcs'),
            (EdltLifecycle, 'scene_manager_crcs'), (EdltLifecycle, 'apply'),
            (EdltLifecycle, 'configure'),
        )
        load = EdltLifecycle.load
        try:
            with ExitStack() as stack:
                sentinels = [stack.enter_context(patch.object(owner, name,
                    side_effect=AssertionError('Forbidden terminal call: ' + owner.__name__ + '.' + name)))
                    for owner, name in guarded]
                connections = [stack.enter_context(patch.object(owner, name,
                    side_effect=AssertionError('Forbidden network connection')))
                    for owner, name in ((socket, 'create_connection'),
                                        (socket.socket, 'connect'), (socket.socket, 'connect_ex'))]
                loads = stack.enter_context(patch.object(EdltLifecycle, 'load', autospec=True, side_effect=load))
                for row in document['cases']:
                    with self.subTest(case=row['name']):
                        raw = {**document['baseline'], **row['source_changes']}
                        dirty = set(row['phases']['input']['dirty_parameters'])
                        source = TemplatePpSnapshot(tuple(
                            (name, tuple(raw[name].split(' ')), name in dirty)
                            for name in spec.parameters), initializing=False)
                        source_fingerprint = source.fingerprint
                        cache = ApplicationCache.from_dict(metadata(row['metadata_mode']))
                        editor = EdltTemplateResetPrelude(spec)
                        load_count = loads.call_count
                        result = editor.stage(source, metadata=cache,
                            active_tab=row['active_tab'], binding_variant=row['binding_variant'])
                        self.assertEqual(loads.call_count - load_count, 2)
                        self.assertEqual(editor.state, 'staged')
                        wanted = dict(raw)
                        compared = []
                        for stage, changes in row['phases'].items():
                            self.assertNotIn(stage, ('before-save', 'final'))
                            wanted.update(changes['raw_changes'])
                            self.assertEqual(len(wanted), 874)
                            actual = result.phases[stage]
                            self.assertEqual(dict(actual.raw), wanted, stage)
                            self.assertEqual(set(actual.dirty_parameters), set(changes['dirty_parameters']), stage)
                            self.assertIs(actual.initializing, changes['initializing'], stage)
                            compared.append(stage)
                            if stage == 'after-reset':
                                break
                        self.assertEqual(compared[-1], 'after-reset')
                        self.assertNotIn('before-save', result.phases)
                        self.assertNotIn('final', result.phases)
                        self.assertEqual(dict(result.after_reset.raw), wanted)
                        self.assertFalse(result.after_reset.initializing)
                        self.assertFalse(source.initializing)
                        self.assertTrue(result.phases['input'].initializing)
                        self.assertEqual(source.fingerprint, source_fingerprint)
                        self.assertEqual(dict(source.raw), raw)
                        reset = result.reset
                        self.assertEqual(len(reset.fresh.widgets), 21)
                        self.assertEqual(len(reset.fresh.scenes), 8)
                        self.assertEqual(len(reset.fresh.static_labels), 64)
                        self.assertTrue(all(widget.stored_type == 0 and widget.model_family == 'BlankData'
                                            for widget in reset.fresh.widgets))
                        self.assertTrue(all(a is not b for a, b in zip(reset.base.widgets, reset.fresh.widgets)))
                        self.assertTrue(all(a is not b for a, b in zip(reset.base.scenes, reset.fresh.scenes)))
                        self.assertIsNot(reset.base.page_widget, reset.fresh.page_widget)
                        self.assertEqual(len(reset.widgets), 21)
                        for index, widget in enumerate(reset.widgets):
                            if index == 9:
                                self.assertIsNot(widget, reset.fresh.widgets[index])
                                self.assertEqual((widget.stored_type, widget.model_family), (10, 'TimeAndDateData'))
                            else:
                                self.assertIs(widget, reset.fresh.widgets[index])
                        self.assertEqual(tuple(wanted[name] for name in (
                            'Widget10WidgetType', 'Widget10RestoreLevel', 'Widget10WidgetByteValue1')),
                            ('0xA', '0x0', '0x2'))
                        evidence = result.as_dict()
                        for flag in ('terminal_before_save_performed', 'terminal_crc_performed',
                                     'third_model_load_performed', 'template_assignments_performed',
                                     'post_reset_callbacks_executed', 'assignment_source_attested',
                                     'automatic_assignment_chain_available', 'apply_allowed',
                                     'target_mutation_attempted', 'saved'):
                            self.assertFalse(evidence[flag], flag)
                        self.assertIs(editor.validate(result, current_source=source, metadata=cache,
                            active_tab=row['active_tab'], binding_variant=row['binding_variant']), result)
                        self.assertEqual(loads.call_count - load_count, 2)
                        report['cases'].append({'case': row['name'], 'active_tab': row['active_tab'],
                            'binding_variant': row['binding_variant'], 'metadata_mode': row['metadata_mode'],
                            'phase_count': len(compared), 'raw_parameter_comparisons': 874 * len(compared),
                            'dirty_set_comparisons': len(compared), 'initializing_flag_comparisons': len(compared),
                            'model_load_count': 2, 'graph_postconditions_verified': True,
                            'source_preserved': True})
                for sentinel in (*sentinels, *connections):
                    sentinel.assert_not_called()
                report['guarded_terminal_calls'] = [
                    {'method': owner.__name__ + '.' + name, 'calls': sentinel.call_count}
                    for (owner, name), sentinel in zip(guarded, sentinels)]
                report['socket_connection_calls'] = sum(s.call_count for s in connections)
                report['model_load_count'] = loads.call_count
            self.assertEqual(len(report['cases']), 44)
            self.assertEqual(sum(row['phase_count'] for row in report['cases']), 432)
            self.assertEqual(sum(row['raw_parameter_comparisons'] for row in report['cases']), 377568)
            self.assertEqual(report['model_load_count'], 88)
            report['source_sha256'] = {Path(path).name: value for path, value in before_hashes.items()}
            report['unchanged_inputs'] = before_hashes == {str(path): digest(path) for path in sources}
            self.assertTrue(report['unchanged_inputs'])
            report['passed'] = True
        finally:
            if os.environ.get('CBUS_EDLT_TEMPLATE_RESET_PRELUDE_REPORT'):
                output = Path(os.environ['CBUS_EDLT_TEMPLATE_RESET_PRELUDE_REPORT'])
                output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
