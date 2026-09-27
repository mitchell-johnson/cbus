"""Retained SceneManager composition inside one ordered parent transaction."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit import cli
from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_parent_metadata import plan_native_parent_metadata
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from cbus_toolkit.edlt_scene_manager import SceneManagerCache
from tests.test_edlt import Session
from tests.test_edlt_parent_form import fixture
from tests.test_edlt_parent_transaction import measurement
from tests.test_edlt_scene_manager import cache as scene_cache, op, vectors


def scene_manager(*operations):
    return {'op': 'scene-manager', 'operations': list(operations)}


def capacity_operations():
    return (
        *(op('clear-items', scene) for scene in range(1, 9)),
        op('add-groups', groups=list(range(63))),
        op('add-groups', 2, groups=[63]),
    )


class ParentSceneManagerTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.session = Session(self.spec)
        self.raw = {
            **self.session.current,
            **{name: value for name, value in vectors()['input'].items()
               if name in self.spec.parameters},
        }
        self.source = self.editor.snapshot(self.raw)
        self.metadata = SceneManagerCache.from_dict(scene_cache())

    def requested(self):
        return (
            scene_manager(
                op('set-name-text', text='Parent scene'),
                op('set-level', item_id=1, level=77)),
            measurement(),
        )

    def test_scene_graph_and_widget_share_one_terminal_projection(self):
        manager = self.editor._editor('scene-manager')
        state = manager.load(self.source, metadata=self.metadata)
        edited = manager.edit(
            state, operations=self.requested()[0]['operations'])
        expected = manager.prepare_composition(edited.state)
        with patch.object(
                self.editor.lifecycle, 'scene_manager_crcs',
                wraps=self.editor.lifecycle.scene_manager_crcs) as crcs, \
                patch.object(
                    self.editor.lifecycle, '_prepare_composed_save',
                    wraps=self.editor.lifecycle._prepare_composed_save) as terminal:
            plan = self.editor.plan(
                self.source, metadata=self.metadata,
                operations=self.requested())
        document = plan.as_dict()
        self.assertEqual(terminal.call_count, 1)
        self.assertEqual(crcs.call_count, 1)
        self.assertEqual(
            document['operation_results'][0]['format'],
            'cbus-edlt-parent-scene-manager-operation-v1')
        self.assertEqual(document['operation_results'][1]['format'],
                         'cbus-edlt-measurement-plan-v1')
        for name, value in expected.fields.items():
            self.assertEqual(plan.after_controls[name], value, name)
        self.assertEqual(plan.before_save['SceneBucket'][:8],
                         (0, 2, 42, 1, 63, 3, 12, 77))
        self.assertEqual(
            bytes(plan.before_save['StaticTextString63']).rstrip(b'\0'),
            b'Parent scene')
        self.assertEqual(document['ownership']['scene_graph']['item_count'], 3)
        self.assertEqual(document['execution_counts'][
            'retained_scene_manager_projections'], 1)
        self.assertTrue(document['preservation'][
            'retained_scene_models_edited'])
        self.assertFalse(document[
            'original_scene_manager_parent_binding_executed'])

    def test_complete_cache_order_capacity_and_single_owner_guards(self):
        lifecycle = self.metadata.application_cache.lifecycle
        with self.assertRaisesRegex(EdltError, 'complete.*scene-manager'):
            self.editor.plan(
                self.source, metadata=lifecycle,
                operations=self.requested())
        with self.assertRaisesRegex(EdltError, 'only one scene-manager'):
            self.editor.plan(
                self.source, metadata=self.metadata,
                operations=(scene_manager(op('get-trigger')),
                            scene_manager(op('get-action'))))
        with self.assertRaisesRegex(EdltError, 'applications must precede'):
            self.editor.plan(
                self.source, metadata=self.metadata,
                operations=(scene_manager(op('get-trigger')),
                            {'op': 'applications', 'edits': []}))
        with self.assertRaisesRegex(EdltError, 'must precede every scene widget'):
            self.editor.plan(
                self.source, metadata=self.metadata,
                operations=(
                    {'op': 'scene', 'page': 1, 'position': 1, 'scene': 1},
                    scene_manager(op('get-trigger')),
                ))
        ordered = self.editor.plan(
            self.source, metadata=self.metadata,
            operations=(
                {'op': 'applications', 'edits': []},
                scene_manager(op('set-name-text', text='Final graph')),
                {'op': 'scene', 'page': 1, 'position': 1, 'scene': 1},
            ))
        self.assertEqual(
            ordered.as_dict()['operation_results'][2]['format'],
            'cbus-edlt-scene-plan-v1')
        partial = (*capacity_operations(),
                   op('add-groups', 2, groups=[64]))
        with self.assertRaisesRegex(EdltError, 'partial scene graphs'):
            self.editor.plan(
                self.source, metadata=self.metadata,
                operations=(scene_manager(*partial), measurement()))
        self.assertEqual(self.session.calls, [])

    def test_full_capacity_uses_retained_temporary_crc_tail_once(self):
        with patch.object(
                self.editor.lifecycle, 'scene_manager_crcs',
                wraps=self.editor.lifecycle.scene_manager_crcs) as crcs:
            plan = self.editor.plan(
                self.source, metadata=self.metadata,
                operations=(scene_manager(*capacity_operations()),
                            measurement()))
        document = plan.as_dict()
        self.assertEqual(crcs.call_count, 1)
        self.assertEqual(document['ownership']['scene_graph']['item_count'], 64)
        self.assertTrue(document['ownership']['scene_graph'][
            'full_capacity_temporary_crc_tail'])
        self.assertTrue(document['lifecycle']['scene_manager_composition'][
            'full_capacity_temporary_crc_tail'])
        expected = self.editor.lifecycle.scene_manager_crcs(
            plan.before_save, item_count=64)
        final = {**plan.expected, **plan.changes}
        for name, value in expected.items():
            self.assertEqual(final[name], value, name)

    def test_scene_manager_composes_with_retained_blank_and_fresh_reset_graphs(self):
        blank_source = {
            **self.source, 'NavWidgetType': (0,),
            'Widget6WidgetType': (2,),
            'Widget6WidgetByteValue6': (12,),
        }
        blank_operation = {'op': 'blank', 'page': 1, 'position': 1}
        scene_operation = scene_manager(
            op('set-name-text', text='Blank sibling'))
        for operations in ((blank_operation, scene_operation),
                           (scene_operation, blank_operation)):
            with self.subTest(order=[row['op'] for row in operations]):
                blank = self.editor.plan(
                    blank_source, metadata=self.metadata,
                    operations=operations)
                self.assertEqual(blank.as_dict()['execution_counts'][
                    'retained_blank_transitions'], 1)
                self.assertEqual(blank.as_dict()['execution_counts'][
                    'retained_scene_manager_projections'], 1)

        from tests.test_edlt_parent_blank_reset import (
            complete_spec, reset_source,
        )
        from tests.test_edlt_reset import metadata as reset_cache
        reset_editor = EdltParentTransaction(complete_spec())
        cache = SceneManagerCache.from_dict({
            'format': 'cbus-edlt-scene-manager-cache-v1',
            'application_cache': reset_cache(), 'level_labels': [],
        })
        reset = reset_editor.plan(
            reset_source(reset_editor.spec), metadata=cache,
            operations=(
                {'op': 'reset', 'active_tab': 'widgets',
                 'binding_variant': 'audited-local-wiring',
                 'dirty_parameters': ['UnitAddress']},
                scene_manager(op('set-name-text', text='Fresh scene')),
                measurement(),
            ))
        self.assertTrue(reset.as_dict()['preservation'][
            'fresh_reset_scene_models_edited'])
        self.assertEqual(reset.before_save['SceneBucket'][:5],
                         (2, 0, 255, 255, 63))

    def test_canonical_stale_guard_apply_and_unrelated_preservation(self):
        source = {**self.source, 'Opaque116': (91,), 'Opaque117': (19,)}
        plan = self.editor.plan(
            source, metadata=self.metadata, operations=self.requested())
        self.session.current = dict(self.raw)
        self.session.current['Opaque116'] = '91'
        self.session.current['Opaque117'] = '19'
        result = self.editor.apply(self.session, plan)
        self.assertTrue(result['verified'])
        self.assertEqual(self.editor.snapshot(self.session.values()),
                         {**plan.expected, **plan.changes})
        self.assertEqual(self.editor.snapshot(self.session.values())[
            'Opaque116'], (91,))
        self.assertEqual(len(self.session.calls),
                         len({name for name, _value in self.session.calls}))
        stale = Session(self.spec)
        stale.current = dict(self.raw)
        stale.current['Scene1StartAddress'] = '1'
        with self.assertRaisesRegex(EdltError, 'changed since'):
            self.editor.apply(stale, plan)
        self.assertEqual(stale.calls, [])

    def test_automatic_parent_metadata_requires_an_exact_native_project(self):
        with self.assertRaisesRegex(
                ValueError, 'exactly the selected project'):
            plan_native_parent_metadata(
                '<Installation/>', '//TEST/254/p/20', self.source,
                self.editor, self.requested())


class ParentSceneManagerCLITests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.session = Session(self.spec)
        self.raw = {
            **self.session.current,
            **{name: value for name, value in vectors()['input'].items()
               if name in self.spec.parameters},
        }
        self.session.current = dict(self.raw)
        self.source = self.editor.snapshot(self.raw)

    def invoke(self, arguments, status=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            actual = cli.main(list(map(str, arguments)))
        self.assertEqual(actual, status, stdout.getvalue() + stderr.getvalue())
        return json.loads(stdout.getvalue() or stderr.getvalue())

    def files(self, root):
        source = Path(root) / 'source.json'
        metadata = Path(root) / 'scene-cache.json'
        operations = Path(root) / 'operations.json'
        source.write_text(json.dumps(self.source), encoding='utf-8')
        metadata.write_text(json.dumps(scene_cache()), encoding='utf-8')
        operations.write_text(json.dumps([
            scene_manager(op('set-name-text', text='CLI scene')),
            measurement(),
        ]), encoding='utf-8')
        return source, metadata, operations

    def test_offline_and_native_cli_use_the_parent_transaction_path(self):
        with tempfile.TemporaryDirectory() as root:
            source, metadata, operations = self.files(root)
            with patch.object(cli, '_edlt_parent_transaction',
                              return_value=self.editor), patch(
                    'cbus_toolkit.cgate.CGateClient',
                    side_effect=AssertionError('offline plan must not connect')):
                preview = self.invoke([
                    'edlt', 'parent-transaction-plan', source,
                    '--metadata', metadata, '--operations', operations,
                ])
            self.assertEqual(preview['operation_results'][0]['format'],
                             'cbus-edlt-parent-scene-manager-operation-v1')
            self.assertFalse(preview['saved'])

            self.session.save_to_source = Mock(
                return_value=SimpleNamespace(code=200))
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(SimpleNamespace())), patch(
                    'cbus_toolkit.programming.Programmer',
                    return_value=SimpleNamespace(load=Mock(
                        return_value=nullcontext(self.session)))), patch.object(
                    cli, '_edlt_parent_transaction', return_value=self.editor):
                result = self.invoke([
                    'cgate', 'unit', '--lock-address', '//EDLTTEST/254',
                    '--source', self.session.source,
                    'edlt-parent-transaction', '--metadata', metadata,
                    '--operations', operations,
                ])
            self.assertTrue(result['verified'])
            self.assertTrue(result['saved'])
            self.session.save_to_source.assert_called_once_with()
            self.assertEqual(len(self.session.calls),
                             len({name for name, _value in self.session.calls}))


if __name__ == '__main__':
    unittest.main()
