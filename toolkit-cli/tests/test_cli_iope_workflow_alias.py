"""Registered IOPE workflow alias against the standalone synthetic workflow."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import xml.etree.ElementTree as ET

from cbus_toolkit import cli as shared
from cbus_toolkit import iope_workflow_cli as standalone
from cbus_toolkit import iope_output_settings as output
from test_iope_workflow_cli import Context, fixture, session


class IopeWorkflowAliasTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.editor = output.IopeOutputSettings(fixture())
        self.pp = session()
        self.snapshot = self.folder / 'snapshot.json'
        self.edits = self.folder / 'edits.json'
        self.plan = self.folder / 'plan.json'
        self.snapshot.write_text(json.dumps({
            'format': 'cbus-cli-parameters-v1', 'unit_type': self.pp.unit_type,
            'firmware': self.pp.firmware, 'catalog_number': self.pp.catalog_number,
            'parameters': self.pp.values()}))
        self.edits.write_text(json.dumps({'channels': {'1': {'min_percent': 50}}}))

    def parse_pair(self, arguments):
        return (shared.build_parser().parse_args(['iope-workflow', *arguments]),
                standalone.parser().parse_args(arguments))

    def database_arguments(self, *options):
        return ['--spec-dir', str(self.folder), 'output', 'database',
                '--host', '127.0.0.1', '--port', '1',
                '--source', '/db//SYNTH/254/p/20', '--lock-address', '//SYNTH/254', *options]

    def test_all_families_share_options_and_existing_iope_settings_stays_registered(self):
        for family in ('environment', 'output', 'logic', 'join-recovery', 'block-timer',
                       'join-groups', 'scene-selectors', 'scene-levels'):
            with self.subTest(family=family):
                alias, direct = self.parse_pair([
                    '--spec-dir', str(self.folder), family, 'database', '--host', '127.0.0.1',
                    '--port', '1', '--timeout', '9', '--source', '/db//SYNTH/254/p/20',
                    '--lock-address', '//SYNTH/254', '--plan', str(self.plan),
                    '--dry-run', '--exclusive-project'])
                self.assertEqual(alias.area, 'iope-workflow')
                for name, value in vars(direct).items():
                    self.assertEqual(getattr(alias, name), value, name)
        existing = shared.build_parser().parse_args(['iope-settings', 'show', str(self.snapshot)])
        self.assertEqual(existing.area, 'iope-settings')
        self.assertEqual(existing.file, self.snapshot)
        with patch('cbus_toolkit.iope_cli.offline', return_value=({'legacy': True}, 0)) as legacy:
            self.assertEqual(shared.run(existing), ({'legacy': True}, 0))
            legacy.assert_called_once_with(existing)

    def test_registered_show_and_plan_equal_standalone_without_connection_or_snapshot_mutation(self):
        original = self.snapshot.read_bytes()
        for action in ('show', 'plan'):
            arguments = ['--spec-dir', str(self.folder), 'output', action, str(self.snapshot)]
            if action == 'plan':
                arguments += ['--edits', str(self.edits)]
            alias, direct = self.parse_pair(arguments)
            with self.subTest(action=action), \
                    patch.object(standalone, '_editor', return_value=(output, self.editor)), \
                    patch('cbus_toolkit.cgate.CGateClient') as client:
                registered = shared.run(alias)
                self.assertEqual(registered, standalone.run(direct))
                self.assertEqual(registered[1], 0)
                if action == 'plan':
                    self.assertEqual(registered[0]['changes']['MinDimmingLevel'], [127, 0, 0, 0])
                    self.assertFalse(registered[0]['saved'])
                client.assert_not_called()
                self.assertEqual(self.snapshot.read_bytes(), original)

    def test_registered_main_json_matches_standalone_main_plan(self):
        arguments = ['--spec-dir', str(self.folder), 'output', 'plan', str(self.snapshot),
                     '--edits', str(self.edits)]
        receipts = []
        with patch.object(standalone, '_editor', return_value=(output, self.editor)), \
                patch('cbus_toolkit.cgate.CGateClient') as client:
            for main, prefix in ((shared.main, ['iope-workflow']), (standalone.main, [])):
                out, err = io.StringIO(), io.StringIO()
                with self.subTest(entry=main.__module__), redirect_stdout(out), redirect_stderr(err):
                    self.assertEqual(main([*prefix, *arguments]), 0)
                self.assertEqual(err.getvalue(), '')
                receipts.append(json.loads(out.getvalue()))
            client.assert_not_called()
        self.assertEqual(receipts[0], receipts[1])
        self.assertEqual(receipts[0]['changes']['MinDimmingLevel'], [127, 0, 0, 0])
        self.assertFalse(receipts[0]['saved'])

    def test_invalid_database_target_and_ownership_refuse_before_client(self):
        cases = [
            self.database_arguments('--show', '--source', '//SYNTH/254/p/20'),
            self.database_arguments('--show', '--lock-address', '//OTHER/254'),
            self.database_arguments('--plan', str(self.plan)),
            self.database_arguments('--show', '--dry-run'),
        ]
        for arguments in cases:
            alias, direct = self.parse_pair(arguments)
            with self.subTest(arguments=arguments), patch('cbus_toolkit.cgate.CGateClient') as client:
                with self.assertRaises(ValueError) as registered:
                    shared.run(alias)
                with self.assertRaises(ValueError) as separate:
                    standalone.run(direct)
                self.assertEqual(str(registered.exception), str(separate.exception))
                client.assert_not_called()
                self.assertFalse(self.plan.exists())

    def test_forged_saved_plan_refuses_before_client_through_both_entry_points(self):
        plan = self.editor.plan(self.pp.values(),
            identity=(self.pp.unit_type, self.pp.firmware, self.pp.catalog_number),
            channels={1: {'min_percent': 50}}).as_dict()
        plan['changes']['RestrikeDelay'] = [3]
        self.plan.write_text(json.dumps(plan))
        before = self.plan.read_bytes()
        alias, direct = self.parse_pair(self.database_arguments('--plan', str(self.plan), '--exclusive-project'))
        with patch.object(standalone, '_editor', return_value=(output, self.editor)), \
                patch('cbus_toolkit.cgate.CGateClient') as client:
            for run, selected in ((shared.run, alias), (standalone.run, direct)):
                with self.subTest(entry=run.__module__), self.assertRaisesRegex(ValueError, 'canonical'):
                    run(selected)
                client.assert_not_called()
            self.assertEqual(self.plan.read_bytes(), before)

    def test_registered_dry_run_matches_standalone_staging_without_saves(self):
        plan = self.editor.plan(self.pp.values(),
            identity=(self.pp.unit_type, self.pp.firmware, self.pp.catalog_number),
            channels={1: {'min_percent': 50}}).as_dict()
        self.plan.write_text(json.dumps(plan))
        alias, direct = self.parse_pair(self.database_arguments(
            '--plan', str(self.plan), '--exclusive-project', '--dry-run'))
        results = []
        for run, selected in ((shared.run, alias), (standalone.run, direct)):
            pp = session()
            pp.save_to_source = MagicMock()
            with self.subTest(entry=run.__module__), \
                    patch.object(standalone, '_editor', return_value=(output, self.editor)), \
                    patch.object(standalone, '_closed', return_value=ET.Element('Network')), \
                    patch('cbus_toolkit.cgate.CGateClient') as client, \
                    patch('cbus_toolkit.programming.Programmer') as programmer, \
                    patch('cbus_toolkit.native.NativeProjects') as projects:
                programmer.return_value.load.return_value = Context(pp)
                results.append(run(selected))
                self.assertEqual(results[-1][1], 0)
                self.assertTrue(results[-1][0]['dry_run'])
                self.assertFalse(results[-1][0]['saved'])
                self.assertFalse(results[-1][0]['pp_save_attempted'])
                self.assertFalse(results[-1][0]['project_save_attempted'])
                self.assertEqual(pp.values()['MinDimmingLevel'], '127 0 0 0')
                pp.save_to_source.assert_not_called()
                projects.return_value.operation.assert_not_called()
                client.return_value.__enter__.return_value.command.assert_not_called()
        self.assertEqual(results[0], results[1])

    def test_both_parsers_reject_mixed_read_and_plan_options(self):
        for parser, prefix in ((shared.build_parser(), ['iope-workflow']), (standalone.parser(), [])):
            with self.subTest(parser=parser.prog), redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as caught:
                parser.parse_args([*prefix, *self.database_arguments('--show', '--plan', str(self.plan))])
            self.assertEqual(caught.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
