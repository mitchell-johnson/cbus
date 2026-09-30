"""Public CLI entrypoints for classic DLT database dynamic controls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_cli_dlt import write_spec, snapshot
from test_macros import NATIVE, NATIVE_REASON, closed_network_project, native_endpoint


def cli(*args, status=0):
    result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', *map(str, args)],
                            capture_output=True, text=True, timeout=90)
    if result.returncode != status:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout or result.stderr)


class CliControlTests(unittest.TestCase):
    def test_saved_inputs_refuse_duplicate_and_nonfinite_json(self):
        from cbus_toolkit.dlt_cli import _read_json
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.json'
            for contents in ('{"expected":{},"expected":{}}', '{"value":NaN}'):
                path.write_text(contents)
                with self.assertRaises(ValueError):
                    _read_json(path)

    def test_offline_block_allow_and_combined_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            write_spec(folder)
            source = snapshot(folder)
            base = ('dlt', '--spec-dir', folder, 'labels')
            self.assertFalse(cli(*base, 'show', '--file', source)['block_dynamic_updates'])
            blocked = cli(*base, 'plan', '--file', source, '--block-dynamic-updates', 'yes', '--variant', '8=4')
            self.assertEqual(blocked['changes']['EnableDynamicLabels'], [0])
            self.assertEqual(blocked['requested']['variants'], [[8, 4]])
            self.assertEqual(blocked['format'], 'cbus-classic-dlt-control-plan-v1')
            self.assertEqual(cli(*base, 'plan', '--file', source, '--block-dynamic-updates', 'no')['changes'], {})

    @unittest.skipUnless(NATIVE, NATIVE_REASON)
    def test_native_show_dryrun_saved_plan_and_project_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=30) as client, \
                closed_network_project(client, 'DC') as project, tempfile.TemporaryDirectory() as folder:
            network = f'//{project}/254'
            NativeDatabase(client).create_unit(network, 20, 'DltControl', 'KEYML5', '2.1.00', catalog_number='5055DL')
            prefix = ('cgate', '--host', host, '--port', port, '--timeout', '30', 'unit',
                      '--lock-address', network, '--source', f'/db{network}/p/20')
            source = Path(folder) / 'unit.json'
            cli(*prefix, 'export', source)
            plan = cli('dlt', 'labels', 'plan', '--file', source, '--block-dynamic-updates', 'yes', '--variant', '2=3')
            plan_file = Path(folder) / 'plan.json'
            plan_file.write_text(json.dumps(plan))
            preview = cli(*prefix, '--dry-run', 'dlt-labels', '--plan', plan_file)
            self.assertTrue(preview['verified'] and preview['raw_bytes_verified'])
            self.assertFalse(preview['saved'])
            self.assertFalse(cli(*prefix, 'dlt-labels', '--show')['block_dynamic_updates'])
            applied = cli(*prefix, 'dlt-labels', '--plan', plan_file)
            self.assertTrue(applied['saved'])
            self.assertTrue(cli(*prefix, 'dlt-labels', '--show')['block_dynamic_updates'])
            self.assertIn('changed since', cli(*prefix, 'dlt-labels', '--plan', plan_file, status=1)['error'])
            for extra in (('--show', '--block-dynamic-updates', 'yes'),
                          ('--plan', plan_file, '--block-dynamic-updates', 'no')):
                self.assertIn('cannot be combined', cli(*prefix, 'dlt-labels', *extra, status=1)['error'])
            client.command('PROJECT SAVE ' + project)
            client.command('PROJECT CLOSE ' + project)
            client.command('PROJECT LOAD ' + project)
            client.command('PROJECT USE ' + project)
            shown = cli(*prefix, 'dlt-labels', '--show')
            self.assertTrue(shown['block_dynamic_updates'])
            self.assertEqual(shown['slots'][1]['variant'], 3)
            allowed = cli(*prefix, 'dlt-labels', '--block-dynamic-updates', 'no')
            self.assertTrue(allowed['saved'])
            self.assertFalse(cli(*prefix, 'dlt-labels', '--show')['block_dynamic_updates'])
