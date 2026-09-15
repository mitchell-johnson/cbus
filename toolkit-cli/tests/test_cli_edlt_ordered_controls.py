"""Ordered Applications/Corridor CLI plans, guards and native persistence."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from cbus_toolkit import cli
from cbus_toolkit.edlt_applications import EdltApplications
from cbus_toolkit.edlt_corridor import EdltCorridor
from tests.test_edlt_applications import cache_for
from tests.test_edlt_corridor import fixture, cache as corridor_cache
from tests.test_edlt import Session

class OrderedControlCLITests(unittest.TestCase):
    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error): actual = cli.main(list(map(str, args)))
        self.assertEqual(actual, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def subprocess_cli(self, *args, status=0):
        command = [sys.executable, '-m', 'cbus_toolkit']
        result = subprocess.run([*command, *map(str, args)], capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_application_sequence_and_corridor_timer(self):
        spec = fixture(); session = Session(spec)
        for kind, editor, flags in (
            ('applications', EdltApplications(spec), ('--select', 'secondary=255', '--select', 'primary=57', '--select', 'secondary=56')),
            ('corridor', EdltCorridor(spec), ('--edit', 'link_group=42', '--edit', 'office_group=1', '--edit', 'seconds=256'))):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder, \
                    patch.object(cli, '_edlt_' + kind, return_value=editor), \
                    patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline must not connect')):
                values = editor.snapshot(session.values())
                cache = cache_for(editor, values) if kind == 'applications' else corridor_cache()
                path = Path(folder) / 'parameters.json'; path.write_text(json.dumps(values))
                metadata = Path(folder) / 'cache.json'; metadata.write_text(json.dumps(cache.as_dict()))
                result = self.invoke(('edlt', kind + '-plan', path, '--metadata', metadata, *flags))
                self.assertFalse(result['saved']); self.assertFalse(result['physical_device_verified'])
                if kind == 'applications':
                    self.assertEqual(result['changes']['Application'], [57, 56])
                    self.assertEqual([edit['field'] for edit in result['edits']], ['secondary', 'primary', 'secondary'])
                else:
                    self.assertEqual(result['timer']['displayed_seconds'], 256)
                    self.assertEqual(result['timer']['stored_seconds'], 255)
                    self.assertEqual(result['corridor']['office_group'], 1)

    def test_invalid_metadata_and_edits_never_enter_programming_context(self):
        spec = fixture(); session = Session(spec)
        for kind, editor, bad in (('applications', EdltApplications(spec), ('--select', 'primary=256')),
                                  ('corridor', EdltCorridor(spec), ('--edit', 'seconds=65536'))):
            context = Mock(); context.__enter__ = Mock(side_effect=AssertionError('No programming context'))
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder, \
                    patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                    patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=context))), \
                    patch.object(cli, '_edlt_' + kind, return_value=editor):
                path = Path(folder) / 'cache.json'; path.write_text('{"format":"x","format":"y"}')
                args = ('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                        'edlt-' + kind, '--metadata', path)
                self.assertIn('Duplicate key', self.invoke(args, status=1)['error'])
                path.unlink(); self.invoke((*args, *bad), status=1)
                context.__enter__.assert_not_called()

    def test_interrupt_retains_phase_evidence_and_never_saves(self):
        spec = fixture()
        for kind, editor in (('applications', EdltApplications(spec)), ('corridor', EdltCorridor(spec))):
            session = Session(spec); calls = []
            def fail(name, value): calls.append(name); raise KeyboardInterrupt('Owned programming interruption')
            session.set = fail; session.save_to_source = Mock(side_effect=AssertionError('No save after interrupt'))
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder, \
                    patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                    patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=nullcontext(session)))), \
                    patch.object(cli, '_edlt_' + kind, return_value=editor):
                cache = cache_for(editor, session.values()) if kind == 'applications' else corridor_cache()
                path = Path(folder) / 'cache.json'; path.write_text(json.dumps(cache.as_dict()))
                result = self.invoke(('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                    'edlt-' + kind, '--metadata', path), status=130)
                evidence = result['edlt_' + kind + '_evidence']
                self.assertEqual(evidence['attempted_parameters'], calls); self.assertEqual(len(calls), 1)
                self.assertTrue(evidence['pp_state_uncertain']); self.assertFalse(evidence['saved'])
                session.save_to_source.assert_not_called()

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set owned native C-Gate and exact unit specification')
    def test_native_dry_run_destination_guard_save_close_load_and_full_readback(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer
        from cbus_toolkit.unitspec import UnitSpecStore
        spec = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYGL5.xml')
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20033'))
        for kind, editor, flags in (
            ('applications', EdltApplications(spec), ('--select', 'secondary=255', '--select', 'primary=57', '--select', 'secondary=56')),
            ('corridor', EdltCorridor(spec), ('--edit', 'link_group=12', '--edit', 'office_group=1', '--edit', 'seconds=256'))):
            project = 'OC' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/20'
            args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit', '--lock-address', network, '--source', source)
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
                projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
                try:
                    database.create_network(project, 254, 'Ordered_Control_CLI', 'Cni', '127.0.0.1:1')
                    database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                    with Programmer(client).load(network, source) as session:
                        session.reset_defaults(); session.set('Widget6WidgetType', '2'); session.set('Widget6WidgetByteValue6', '42')
                        session.set('SecondaryApplication', '57'); session.set('Widget6WidgetByteValue1', '128'); session.save_to_source()
                    projects.operation('save', project)
                    original = self.subprocess_cli(*args, 'show')
                    export = Path(folder) / 'parameters.json'; self.subprocess_cli(*args, 'export', export)
                    cache = cache_for(editor, original) if kind == 'applications' else corridor_cache()
                    metadata = Path(folder) / 'cache.json'; metadata.write_text(json.dumps(cache.as_dict()))
                    options = ('--metadata', metadata, *flags)
                    plan = self.subprocess_cli('edlt', kind + '-plan', export, *options)
                    preview = self.subprocess_cli(*args, '--dry-run', 'edlt-' + kind, *options)
                    self.assertTrue(preview['verified']); self.assertFalse(preview['saved'])
                    self.assertEqual(preview['changes'], plan['changes']); self.assertEqual(preview['phases'], plan['phases'])
                    self.assertEqual(self.subprocess_cli(*args, 'show'), original)
                    result = self.subprocess_cli(*args, 'edlt-' + kind, *options)
                    self.assertTrue(result['saved']); self.assertEqual(result['parameters'], preview['parameters'])
                    self.assertEqual(len(result['parameters']), 874)
                    self.assertIn('database destinations only', self.subprocess_cli(*args, '--destination', network + '/p/20',
                        'edlt-' + kind, *options, status=1)['error'])
                    for operation in ('save', 'close', 'load'): projects.operation(operation, project)
                    self.assertEqual(self.subprocess_cli(*args, 'show'), result['parameters'])
                    self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                finally:
                    projects.operation('close', project); projects.operation('delete', project)


if __name__ == '__main__': unittest.main()
