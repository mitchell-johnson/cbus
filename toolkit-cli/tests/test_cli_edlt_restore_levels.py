"""Offline preset plans and database-only native CLI persistence."""
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
from cbus_toolkit.edlt_restore_levels import EdltRestoreLevels
from tests.test_edlt import Session
from tests.test_edlt_restore_levels import fixture, metadata


class RestoreLevelsCLITests(unittest.TestCase):
    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error): code = cli.main(list(map(str, args)))
        self.assertEqual(code, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_plan_names_sync_and_missing_metadata_without_io(self):
        spec = fixture(); editor = EdltRestoreLevels(spec); session = Session(spec)
        values = editor.snapshot(session.values())
        values.update({'Widget6WidgetType': (2,), 'Widget6WidgetByteValue6': (42,)})
        with tempfile.TemporaryDirectory() as directory, patch.object(cli, '_edlt_restore_levels', return_value=editor), \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline must not connect')):
            path = Path(directory) / 'values.json'; path.write_text(json.dumps(values))
            cache = Path(directory) / 'cache.json'; document = metadata(editor, values); cache.write_text(json.dumps(document))
            args = ('edlt', 'restore-levels-plan', path, '--metadata', cache, '--widget', 6, '--level', 42, '--synchronise')
            plan = self.invoke(args)
            self.assertEqual(plan['event_target_widgets'], list(range(6, 22)))
            self.assertEqual(set(plan['phases']), {'after_load', 'controls', 'before_save', 'crc'})
            self.assertFalse(plan['saved']); self.assertFalse(plan['physical_device_verified'])
            cache.write_text(json.dumps({**document, 'groups': []}))
            error = self.invoke(args, status=1)
            self.assertEqual(error['type'], 'LifecycleMetadataError'); self.assertEqual(error['original_stage'], 'controls')

    def test_invalid_metadata_and_options_rejected_before_pp_context(self):
        spec = fixture(); editor = EdltRestoreLevels(spec); session = Session(spec)
        context = Mock(); context.__enter__ = Mock(side_effect=AssertionError('No PP context'))
        with tempfile.TemporaryDirectory() as directory, \
                patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=context))), \
                patch.object(cli, '_edlt_restore_levels', return_value=editor):
            cache = Path(directory) / 'cache.json'
            args = ('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                    'edlt-restore-levels', '--metadata', cache)
            for raw, wanted in (('{"groups":[],"groups":[]}', 'Duplicate key'), (' ' * (2 * 1024 * 1024 + 1), 'exceeds 2 MiB')):
                cache.write_text(raw); self.assertIn(wanted, self.invoke(args, status=1)['error'])
            cache.write_text(json.dumps(metadata(editor, session.values())))
            for extra in (('--widget', 6), ('--level', 42), ('--synchronise',), ('--widget', 5, '--level', 42)):
                self.invoke((*args, *extra), status=1)
            context.__enter__.assert_not_called()

    def test_interrupt_keeps_original_phase_evidence_and_does_not_save(self):
        spec = fixture(); editor = EdltRestoreLevels(spec); session = Session(spec); calls = []
        def fail(name, value):
            calls.append(name); session.current[name] = value; session.connected = False
            raise KeyboardInterrupt('Preset SET interrupted')
        session.set = fail; session.save_to_source = Mock(side_effect=AssertionError('No save after interrupt'))
        with tempfile.TemporaryDirectory() as directory, \
                patch('cbus_toolkit.cgate.CGateClient', return_value=nullcontext(SimpleNamespace())), \
                patch('cbus_toolkit.programming.Programmer', return_value=SimpleNamespace(load=Mock(return_value=nullcontext(session)))), \
                patch.object(cli, '_edlt_restore_levels', return_value=editor):
            cache = Path(directory) / 'cache.json'; cache.write_text(json.dumps(metadata(editor, session.values())))
            result = self.invoke(('cgate', 'unit', '--lock-address', '//EDLTTEST/254', '--source', session.source,
                'edlt-restore-levels', '--metadata', cache), status=130)
        evidence = result['edlt_restore_levels_evidence']; self.assertEqual(len(calls), 1)
        self.assertEqual(evidence['attempted_parameters'], calls); self.assertTrue(evidence['pp_state_uncertain'])
        self.assertFalse(evidence['saved']); self.assertFalse(evidence['verified'])
        session.save_to_source.assert_not_called()

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),
                         'Set native C-Gate and specifications for preset CLI acceptance')
    def test_native_preview_full_parameter_save_reload_and_destination_guard(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer
        from cbus_toolkit.unitspec import UnitSpecStore
        editor = EdltRestoreLevels(UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYGL5.xml'))
        project = 'RC' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/20'
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        args = ('cgate', '--host', host, '--port', port, '--timeout', 20, 'unit', '--lock-address', network, '--source', source)
        with tempfile.TemporaryDirectory() as directory, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project)
            try:
                database.create_network(project, 254, 'Preset_CLI', 'Cni', '127.0.0.1:29999')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                with Programmer(client).load(network, source) as session:
                    session.reset_defaults(); session.set('Widget6WidgetType', '2'); session.set('Widget6WidgetByteValue6', '42')
                    session.save_to_source()
                projects.operation('save', project)
                original = self.cli(*args, 'show'); path = Path(directory) / 'original.json'; self.cli(*args, 'export', path)
                cache = Path(directory) / 'cache.json'; cache.write_text(json.dumps(metadata(editor, original)))
                options = ('--metadata', cache, '--widget', 6, '--level', 42, '--synchronise')
                plan = self.cli('edlt', 'restore-levels-plan', path, *options)
                preview = self.cli(*args, '--dry-run', 'edlt-restore-levels', *options)
                self.assertTrue(preview['verified']); self.assertFalse(preview['saved'])
                self.assertEqual(preview['changes'], plan['changes']); self.assertEqual(preview['phases'], plan['phases'])
                self.assertEqual(self.cli(*args, 'show'), original)
                result = self.cli(*args, 'edlt-restore-levels', *options)
                self.assertTrue(result['saved']); self.assertEqual(result['parameters'], preview['parameters'])
                self.assertEqual(len(result['parameters']), 874)
                self.assertEqual(int(result['parameters']['Widget6RestoreLevel'], 0), 42)
                self.assertEqual(int(result['parameters']['Widget7RestoreLevel'], 0), 0)
                self.assertEqual(int(result['parameters']['Widget21RestoreLevel'], 0), 42)
                self.assertIn('database destinations only', self.cli(*args, '--destination', network + '/p/20',
                    'edlt-restore-levels', *options, status=1)['error'])
                for action in ('save', 'close', 'load'): projects.operation(action, project)
                self.assertEqual(self.cli(*args, 'show'), result['parameters'])
                self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
            finally:
                projects.operation('close', project); projects.operation('delete', project)


if __name__ == '__main__': unittest.main()
