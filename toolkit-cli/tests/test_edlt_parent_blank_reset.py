"""Blank and fresh-graph Reset inside one ordered eDLT parent save."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from cbus_toolkit import cli
from cbus_toolkit.edlt import EdltApplyError, EdltError, _field
from cbus_toolkit.edlt_parent_transaction import (
    CRC_FIELDS, EdltParentTransaction, normalize_operations,
)
from cbus_toolkit.edlt_reset import EdltResetControls, _RawState
from tests.test_edlt import Session
from tests.test_edlt_parent_form import fixture as parent_fixture
from tests.test_edlt_parent_transaction import measurement, transaction_cache
from tests.test_edlt_reset import fixture as reset_fixture, metadata as reset_cache


def complete_spec():
    """Synthetic complete schema joining existing exact-layout test fixtures."""
    base = reset_fixture()
    extended = parent_fixture()
    parameters = dict(base.parameters)
    additions = [name for name in extended.parameters if name not in parameters]
    padding = [name for name in parameters if name.startswith('OwnedPadding')]
    for name in padding[:len(additions)]:
        del parameters[name]
    for name, parameter in extended.parameters.items():
        # Reset's captured constructor contract requires these exact uppercase
        # FF defaults; the extended panel fixture intentionally starts blank.
        if name != 'NavWidgetType' and not name.endswith('WidgetType'):
            parameters[name] = parameter
    assert len(parameters) == 874
    return replace(base, parameters=parameters)


def reset_source(spec):
    reset = EdltResetControls(spec)
    raw = _RawState(reset.defaults).raw()
    raw.update(
        NavWidgetType='0x1', Widget6WidgetType='0x2',
        Widget6WidgetByteValue6='0x2a', Widget6RestoreLevel='0xad',
        Widget6WidgetByteValue31='0xab', EnableLevelStore='0x1',
        UnitAddress='0x14', SerialNumber='0x1 0x2 0x3 0x4',
        Project='OWNED   ', NetworkAddress='0xFE',
    )
    return raw


def reset_operations():
    return (
        {'op': 'reset', 'active_tab': 'widgets',
         'binding_variant': 'audited-local-wiring',
         'dirty_parameters': ['UnitAddress']},
        measurement(1),
    )


class ParentBlankTests(unittest.TestCase):
    def setUp(self):
        self.spec = parent_fixture()
        self.editor = EdltParentTransaction(self.spec)
        self.session = Session(self.spec)
        self.source = self.editor.snapshot(self.session.values())
        self.source.update({
            'NavWidgetType': (0,), _field(6): (2,),
            'Widget6RestoreLevel': (88,), _field(6, 31): (173,),
        })
        self.session.current.update({
            'NavWidgetType': '0', _field(6): '2',
            'Widget6RestoreLevel': '88', _field(6, 31): '173',
        })
        self.metadata = transaction_cache(self.editor, self.source)

    def test_blank_reserves_one_slot_and_shares_one_terminal_projection(self):
        operations = (
            {'op': 'blank', 'page': 1, 'position': 1}, measurement(2),
        )
        with patch.object(
                self.editor.lifecycle, 'crcs',
                wraps=self.editor.lifecycle.crcs) as crcs, patch.object(
                    self.editor.lifecycle, '_prepare_composed_save',
                    wraps=self.editor.lifecycle._prepare_composed_save) as terminal:
            plan = self.editor.plan(
                self.source, metadata=self.metadata, operations=operations)
        document = plan.as_dict()
        self.assertEqual(crcs.call_count, 1)
        self.assertEqual(terminal.call_count, 1)
        self.assertEqual([row['format'] for row in document['operation_results']], [
            'cbus-edlt-blanked-model-v1',
            'cbus-edlt-measurement-plan-v1',
        ])
        blank = document['operation_results'][0]
        self.assertEqual(blank['reserved_widget_slots'], [6])
        self.assertEqual(len(blank['owned_parameters']), 33)
        self.assertEqual(blank['mutated_parameters'], [
            'Widget6RestoreLevel', 'Widget6WidgetType'])
        self.assertEqual(plan.after_controls[_field(6)], (0,))
        self.assertEqual(plan.after_controls['Widget6RestoreLevel'], (0,))
        self.assertEqual(plan.after_controls[_field(6, 31)], (173,))
        self.assertEqual(plan.after_controls[_field(7)], (12,))
        self.assertEqual(len(document['lifecycle']['blank_transitions']), 1)
        self.assertEqual(document['execution_counts']['retained_blank_transitions'], 1)
        self.assertEqual(document['execution_counts']['terminal_crc_passes'], 1)
        self.assertEqual(set(document['phases']['crc']), set(CRC_FIELDS))
        self.assertFalse(document['original_interactive_blank_reset_sequence_executed'])

    def test_blank_overlap_and_invalid_post_reset_order_fail_before_io(self):
        bad = (
            ({'op': 'blank', 'page': 1, 'position': 1}, measurement(1)),
            ({'op': 'blank', 'page': 1, 'position': 1},
             {'op': 'blank', 'page': 1, 'position': 1}),
        )
        for operations in bad:
            with self.subTest(operations=operations), self.assertRaisesRegex(
                    EdltError, 'Duplicate widget byte ownership'):
                self.editor.configure(
                    self.session, metadata=self.metadata,
                    operations=operations)
            self.assertEqual(self.session.calls, [])
        multiple = {**self.source, 'NavWidgetType': (1,)}
        metadata = transaction_cache(self.editor, multiple)
        with self.assertRaisesRegex(EdltError, 'navigation'):
            self.editor.plan(
                multiple, metadata=metadata,
                operations=(
                    {'op': 'blank', 'page': 1, 'position': 5},
                    measurement(1, page_mode='multiple'),
                ))
        with self.assertRaisesRegex(EdltError, 'immediately follow'):
            normalize_operations((
                {'op': 'reset', 'active_tab': 'widgets',
                 'binding_variant': 'base-c3'},
                measurement(1),
                {'op': 'blank', 'page': 1, 'position': 1},
            ))


class ParentResetTests(unittest.TestCase):
    def setUp(self):
        self.spec = complete_spec()
        self.editor = EdltParentTransaction(self.spec)
        self.raw = reset_source(self.spec)
        self.metadata = reset_cache()

    def plan(self):
        return self.editor.plan(
            self.raw, metadata=self.metadata,
            operations=reset_operations())

    def session(self):
        session = Session(self.spec)
        session.current = dict(self.raw)
        return session

    def test_reset_is_first_fresh_baseline_then_later_widget_and_one_crc(self):
        with patch.object(
                self.editor.lifecycle, 'crcs',
                wraps=self.editor.lifecycle.crcs) as crcs, patch.object(
                    self.editor.lifecycle, '_prepare_composed_save',
                    wraps=self.editor.lifecycle._prepare_composed_save) as terminal:
            plan = self.plan()
        document = plan.as_dict()
        self.assertEqual(crcs.call_count, 1)
        self.assertEqual(terminal.call_count, 1)
        self.assertEqual([row['format'] for row in document['operation_results']], [
            'cbus-edlt-parent-reset-operation-v1',
            'cbus-edlt-measurement-plan-v1',
        ])
        reset = document['operation_results'][0]
        self.assertEqual(reset['raw_phase_order'][-1], 'after-reset')
        self.assertTrue(reset['terminal_save_deferred_to_parent'])
        self.assertTrue(reset['terminal_crc_deferred_to_parent'])
        self.assertEqual(reset['new_widget_models'], 21)
        self.assertEqual(reset['new_scene_models'], 8)
        self.assertFalse(reset['old_scene_references_retained'])
        self.assertEqual(plan.after_controls[_field(6)], (12,))
        self.assertEqual(plan.after_controls[_field(10)], (10,))
        self.assertEqual(plan.before_save[_field(11)], (255,))
        final = {**plan.expected, **plan.changes}
        for name in ('UnitAddress', 'SerialNumber', 'Project', 'NetworkAddress'):
            self.assertEqual(final[name], plan.expected[name])
        counts = document['execution_counts']
        self.assertEqual(counts['retained_load_models'], 1)
        self.assertEqual(counts['reset_fresh_model_loads'], 1)
        self.assertEqual(counts['reset_graph_replacements'], 1)
        self.assertEqual(counts['terminal_normalization_passes'], 1)
        self.assertEqual(counts['terminal_crc_passes'], 1)
        self.assertTrue(document['ownership']['reset_baseline_parameters'])
        self.assertTrue(document['ownership'][
            'reset_baseline_overridden_by_later_controls'])
        self.assertTrue(document['preservation']['fresh_reset_scene_models'])
        self.assertFalse(document['preservation']['retained_scene_models'])

    def test_reset_order_raw_cache_and_fresh_graph_boundary_are_executable(self):
        reset = reset_operations()[0]
        with self.assertRaisesRegex(EdltError, 'operation 1'):
            normalize_operations((measurement(), reset))
        with self.assertRaisesRegex(EdltError, 'only one reset'):
            normalize_operations((reset, reset))
        self.assertEqual(
            [row['op'] for row in normalize_operations((
                reset, {'op': 'blank', 'page': 1, 'position': 5}))],
            ['reset', 'blank'])
        with self.assertRaisesRegex(EdltError, 'application-cache'):
            self.editor.plan(
                self.raw, metadata=self.metadata['lifecycle'],
                operations=reset_operations())
        decoded = self.editor.snapshot(self.raw)
        with self.assertRaisesRegex(EdltError, 'raw PP strings'):
            self.editor.plan(
                decoded, metadata=self.metadata,
                operations=reset_operations())

    def test_reset_plan_canonical_raw_stale_guard_apply_and_exact_rollback(self):
        plan = self.plan()
        stale = self.session()
        stale.current['NavWidgetType'] = '0x01'
        with self.assertRaisesRegex(EdltError, 'changed since'):
            self.editor.apply(stale, plan)
        self.assertEqual(stale.calls, [])

        session = self.session()
        original_set = session.set
        failure = OSError('parent Reset staged write failed')
        attempts = 0

        def fail_second(name, value):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise failure
            return original_set(name, value)

        with patch.object(session, 'set', side_effect=fail_second):
            with self.assertRaises(EdltApplyError) as caught:
                self.editor.apply(session, plan)
        self.assertIs(caught.exception.cause, failure)
        self.assertEqual(session.current, self.raw)

        session = self.session()
        result = self.editor.apply(session, plan)
        self.assertTrue(result['verified'])
        writes = [name for name, _value in session.calls]
        self.assertEqual(len(writes), len(set(writes)))
        self.assertEqual(self.editor.snapshot(session.values()),
                         {**plan.expected, **plan.changes})

    def test_reset_then_blank_binds_widget10_on_the_issued_fresh_graph(self):
        operations = (
            reset_operations()[0],
            {'op': 'blank', 'page': 1, 'position': 5},
            measurement(1),
        )
        plan = self.editor.plan(
            self.raw, metadata=self.metadata, operations=operations)
        document = plan.as_dict()
        blank = document['operation_results'][1]
        self.assertEqual(blank['format'], 'cbus-edlt-blanked-model-v1')
        self.assertEqual(blank['slot'], 10)
        self.assertTrue(blank['type_changed'])
        self.assertTrue(blank['parent_panel_binding'][
            'fresh_reset_graph_bound'])
        self.assertEqual(plan.after_controls[_field(10)], (0,))
        self.assertEqual(plan.after_controls['Widget10RestoreLevel'], (0,))
        self.assertEqual(document['execution_counts'][
            'fresh_reset_blank_transitions'], 1)
        self.assertEqual(document['execution_counts'][
            'retained_blank_transitions'], 0)
        self.assertTrue(document['reused_fresh_reset_blank_transition'])
        self.assertEqual(document['execution_counts'][
            'terminal_normalization_passes'], 1)
        self.assertEqual(document['execution_counts']['terminal_crc_passes'], 1)

        session = self.session()
        result = self.editor.apply(session, plan)
        self.assertTrue(result['verified'])
        self.assertEqual(self.editor.snapshot(session.values()),
                         {**plan.expected, **plan.changes})


class ParentBlankResetCLITests(unittest.TestCase):
    def invoke(self, arguments, status=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            actual = cli.main(list(map(str, arguments)))
        self.assertEqual(actual, status, stdout.getvalue() + stderr.getvalue())
        return json.loads(stdout.getvalue() or stderr.getvalue())

    def files(self, root):
        spec = complete_spec()
        editor = EdltParentTransaction(spec)
        raw = reset_source(spec)
        source = Path(root) / 'source.json'
        metadata = Path(root) / 'metadata.json'
        operations = Path(root) / 'operations.json'
        source.write_text(json.dumps({
            'format': 'cbus-cli-parameters-v1', 'unit_type': 'KEYGL5',
            'firmware': '5.5.00', 'catalog_number': '5055EDL',
            'parameters': raw,
        }))
        metadata.write_text(json.dumps(reset_cache()))
        operations.write_text(json.dumps(reset_operations()))
        session = Session(spec)
        session.current = dict(raw)
        return editor, session, source, metadata, operations

    def test_offline_blank_parent_cli_exposes_retained_transition(self):
        with tempfile.TemporaryDirectory() as root:
            spec = parent_fixture()
            editor = EdltParentTransaction(spec)
            session = Session(spec)
            values = editor.snapshot(session.values())
            values.update({
                'NavWidgetType': (0,), _field(6): (2,),
                'Widget6RestoreLevel': (77,),
            })
            source = Path(root) / 'blank-source.json'
            metadata = Path(root) / 'blank-metadata.json'
            operations = Path(root) / 'blank-operations.json'
            source.write_text(json.dumps(values))
            metadata.write_text(json.dumps(transaction_cache(editor, values)))
            operations.write_text(json.dumps((
                {'op': 'blank', 'page': 1, 'position': 1}, measurement(2))))
            with patch.object(cli, '_edlt_parent_transaction',
                              return_value=editor), patch(
                    'cbus_toolkit.cgate.CGateClient',
                    side_effect=AssertionError('offline plan must not connect')):
                result = self.invoke((
                    'edlt', 'parent-transaction-plan', source,
                    '--metadata', metadata, '--operations', operations))
            self.assertEqual(result['operation_results'][0]['format'],
                             'cbus-edlt-blanked-model-v1')
            self.assertEqual(result['execution_counts'][
                'retained_blank_transitions'], 1)

    def test_offline_and_native_reset_parent_cli_use_one_save(self):
        with tempfile.TemporaryDirectory() as root:
            editor, session, source, metadata, operations = self.files(root)
            with patch.object(cli, '_edlt_parent_transaction',
                              return_value=editor), patch(
                    'cbus_toolkit.cgate.CGateClient',
                    side_effect=AssertionError('offline plan must not connect')):
                preview = self.invoke((
                    'edlt', 'parent-transaction-plan', source,
                    '--metadata', metadata, '--operations', operations))
            self.assertEqual(preview['operation_results'][0]['format'],
                             'cbus-edlt-parent-reset-operation-v1')
            self.assertEqual(preview['execution_counts'][
                'terminal_crc_passes'], 1)

            session.save_to_source = Mock(return_value=SimpleNamespace(code=200))
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(SimpleNamespace())), patch(
                    'cbus_toolkit.programming.Programmer',
                    return_value=SimpleNamespace(load=Mock(
                        return_value=nullcontext(session)))), patch.object(
                    cli, '_edlt_parent_transaction', return_value=editor):
                result = self.invoke((
                    'cgate', 'unit', '--lock-address', '//RESET/254',
                    '--source', session.source, 'edlt-parent-transaction',
                    '--metadata', metadata, '--operations', operations))
            self.assertTrue(result['verified'])
            self.assertTrue(result['saved'])
            session.save_to_source.assert_called_once_with()

    def test_reset_parent_save_failure_is_uncertain_and_never_retried(self):
        with tempfile.TemporaryDirectory() as root:
            editor, session, _source, metadata, operations = self.files(root)
            session.save_to_source = Mock(
                side_effect=RuntimeError('SAVE reply lost'))
            with patch('cbus_toolkit.cgate.CGateClient',
                       return_value=nullcontext(SimpleNamespace())), patch(
                    'cbus_toolkit.programming.Programmer',
                    return_value=SimpleNamespace(load=Mock(
                        return_value=nullcontext(session)))), patch.object(
                    cli, '_edlt_parent_transaction', return_value=editor):
                result = self.invoke((
                    'cgate', 'unit', '--lock-address', '//RESET/254',
                    '--source', session.source, 'edlt-parent-transaction',
                    '--metadata', metadata, '--operations', operations), status=1)
            evidence = result['edlt_parent_transaction_evidence']
            self.assertTrue(evidence['verified'])
            self.assertTrue(evidence['save_outcome_uncertain'])
            self.assertEqual(evidence['database_save_calls_attempted'], 1)
            self.assertEqual(evidence['automatic_retries'], 0)
            session.save_to_source.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
