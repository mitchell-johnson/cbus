"""Reset CLI raw exports, tab context, finalization and native persistence."""
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
import io, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from cbus_toolkit import cli
from cbus_toolkit.edlt_reset import EdltResetControls, _RawState
from tests.test_edlt import Session
from tests.test_edlt_reset import fixture, metadata


class ResetCLITests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltResetControls(self.spec)
        self.session = Session(self.spec)
        self.session.current = _RawState(self.editor.defaults).raw()
        self.session.current.update(NavWidgetType='0x1', Widget6WidgetType='0x2',
            Widget6WidgetByteValue6='0x2a', Widget6RestoreLevel='0xad', EnableLevelStore='0x1')
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.source, self.cache = self.folder/'source.json', self.folder/'cache.json'
        self.source.write_text(json.dumps(self.editor.raw_document(self.session.values())))
        self.cache.write_text(json.dumps(metadata()))

    def flags(self, tab='general'):
        return ('--metadata', self.cache, '--active-tab', tab, '--binding-variant', 'audited-local-wiring')

    def invoke(self, args, status=0):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err): actual = cli.main(list(map(str, args)))
        self.assertEqual(actual, status, out.getvalue()+err.getvalue())
        return json.loads(out.getvalue() or err.getvalue())

    def test_offline_raw_exports_tabs_dirty_flags_and_parent_spec_option(self):
        with patch('cbus_toolkit.edlt_reset_cli.editor', return_value=self.editor), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline must not connect')):
            for tab in ('widgets', 'general', 'standby', 'colour'):
                result = self.invoke(('edlt', 'reset-plan', self.source, *self.flags(tab), '--dirty-parameter', 'UnitAddress'))
                self.assertFalse(result['saved']); self.assertFalse(result['physical_factory_reset_performed'])
                self.assertEqual(result['terminal_navigation_raw'], '0x0' if tab in ('widgets', 'general') else '0xFF')
                self.assertEqual(result['initial_dirty_parameters'], ['UnitAddress'])
                self.assertEqual(result['phases']['after-reset']['raw']['Widget10WidgetByteValue1'], '0x2')
            native = self.editor.raw_document(self.session.values()); native['format'] = 'cbus-cli-parameters-v1'
            self.source.write_text(json.dumps(native))
            self.assertTrue(self.invoke(('edlt', 'reset-plan', self.source, *self.flags()))['model_cycle_complete'])
        args = cli.build_parser().parse_args(list(map(str, ('edlt', '--spec-dir', self.folder, 'reset-plan', self.source, *self.flags()))))
        self.assertEqual(args.spec_dir, self.folder)

    def test_strict_raw_cache_and_dirty_inputs_reject_without_commands(self):
        flags = ('edlt', 'reset-plan', self.source, *self.flags())
        valid = self.editor.raw_document(self.session.values())
        with patch('cbus_toolkit.edlt_reset_cli.editor', return_value=self.editor), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Invalid input cannot connect')):
            for text, message in (('{"format":1,"format":2}', 'Duplicate JSON key'),
                (json.dumps(self.session.values()), 'raw eDLT parameter export'),
                (json.dumps({**valid, 'firmware': '1'}), 'raw eDLT parameter export'),
                (json.dumps({**valid, 'parameters': {**valid['parameters'], 'EnableLevelStore': [1]}}), 'raw PP strings')):
                self.source.write_text(text); self.assertIn(message, self.invoke(flags, 1)['error'])
            self.source.write_text(json.dumps(valid))
            self.assertIn('distinct dirty', self.invoke((*flags, '--dirty-parameter', 'UnitAddress', '--dirty-parameter', 'UnitAddress'), 1)['error'])
            self.assertIn('unknown', self.invoke((*flags, '--dirty-parameter', 'Unknown'), 1)['error'])
            for text, message in (('{"a":1,"a":2}', 'Duplicate JSON key'), ('[NaN]', 'Non-finite JSON')):
                self.cache.write_text(text); self.assertIn(message, self.invoke(flags, 1)['error'])

    def test_partial_staging_save_and_cleanup_errors_keep_raw_reset_evidence(self):
        class RejectEvidence(KeyboardInterrupt):
            def __setattr__(self, name, value):
                if name.startswith('edlt_'): raise SystemExit('Cannot attach evidence')
                super().__setattr__(name, value)
        for phase in ('configure', 'readback', 'save', 'cleanup', 'connection_cleanup'):
            for kind in (OSError, RejectEvidence):
                with self.subTest(phase=phase, kind=kind.__name__):
                    editor = EdltResetControls(self.spec); session = Session(self.spec)
                    session.current = dict(self.session.current); error = kind('Owned finalization fault')
                    original, completed = editor.configure, []
                    if phase == 'configure': session.set = Mock(side_effect=error)
                    def configure(*args, **kwargs):
                        result = original(*args, **kwargs); completed.append(result)
                        if phase == 'readback': session.values = Mock(side_effect=error)
                        return result
                    session.save_to_source = Mock(side_effect=error if phase == 'save' else None, return_value=object())
                    @contextmanager
                    def context():
                        yield session
                        if phase == 'cleanup': raise error
                    @contextmanager
                    def connection():
                        yield SimpleNamespace()
                        if phase == 'connection_cleanup': raise error
                    with patch.object(editor, 'configure', side_effect=configure), \
                            patch.object(cli, '_edlt_reset', return_value=editor), \
                            patch('cbus_toolkit.cgate.CGateClient', return_value=connection()), \
                            patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=context()))):
                        result = self.invoke(('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                            'edlt-reset-controls', *self.flags()), 130 if isinstance(error, KeyboardInterrupt) else 1)
                    evidence = result['edlt_reset_evidence']
                    self.assertEqual(evidence['failure_phase'], phase)
                    self.assertFalse(evidence['operation_completed'])
                    self.assertEqual(evidence['saved'], phase in ('cleanup', 'connection_cleanup'))
                    self.assertEqual(evidence['save_attempted'], phase not in ('configure', 'readback'))
                    self.assertEqual(evidence['save_outcome_uncertain'], phase == 'save')
                    self.assertEqual(evidence['terminal_navigation_raw'], '0x0')
                    if phase == 'configure': session.save_to_source.assert_not_called()
                    else: self.assertEqual(evidence['phases'], completed[0]['phases'])

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'), 'Set owned C-Gate and original specification')
    def test_native_raw_export_preview_full_save_close_load_and_destination_guard(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeProjects, NativeDatabase
        from cbus_toolkit.programming import Programmer
        host, port = os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20033'))
        project = 'RC'+uuid4().hex[:6].upper(); network = '//'+project+'/254'; source = '/db'+network+'/p/20'
        def call(*args, status=0):
            result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, status, result.stdout+result.stderr)
            return json.loads(result.stdout or result.stderr)
        args = ('cgate', '--host', host, '--port', port, '--timeout', 30, 'unit', '--lock-address', network, '--source', source)
        with CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Reset_CLI', 'Cni', '127.0.0.1:1')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                with Programmer(client).load(network, source) as session:
                    session.reset_defaults(); session.set('NavWidgetType', '1'); session.set('UnitName', 'OLDUNIT ')
                    session.save_to_source()
                projects.operation('save', project)
                self.source.unlink(); call(*args, 'export', self.source)
                original = call(*args, 'show')
                plan = call('edlt', 'reset-plan', self.source, *self.flags())
                preview = call(*args, '--dry-run', 'edlt-reset-controls', *self.flags())
                self.assertFalse(preview['saved']); self.assertTrue(preview['verified'])
                self.assertEqual(plan['changes'], preview['changes'])
                self.assertEqual(call(*args, 'show'), original)
                saved = call(*args, 'edlt-reset-controls', *self.flags())
                self.assertTrue(saved['saved']); self.assertEqual(len(saved['parameters']), 874)
                self.assertEqual(saved['parameters'], preview['parameters'])
                self.assertIn('database destinations only', call(*args, '--destination', network+'/p/20', 'edlt-reset-controls', *self.flags(), status=1)['error'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(call(*args, 'show'), saved['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
            finally:
                try: projects.operation('close', project)
                finally: projects.operation('delete', project)
