"""CLI acceptance for offline thermostat scheduling selection and composition."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit import thermostat_scheduling_cli as boundary


def write_state(directory, name='state.json', *, groups=(), on=None, off=None, override=None, enabled=True,
                save_lock=0, pending_save=False):
    path = directory / name
    path.write_text(json.dumps({'groups': list(groups),
                                'roles': {'on': on, 'off': off, 'override': override},
                                'enabled': enabled, 'save_lock': save_lock,
                                'pending_save': pending_save}), encoding='utf-8')
    return path


def group(identity, address, levels=()):
    return {'identity': identity, 'address': address, 'levels': list(levels)}


class ThermostatSchedulingCLITests(unittest.TestCase):
    def execute(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), patch('socket.create_connection', side_effect=AssertionError('Unexpected network')):
            code = cli.main(args)
        text = stdout.getvalue() or stderr.getvalue()
        return code, json.loads(text)

    def test_selected_and_required_over_supplied_state(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_state(root, groups=[group('a', 1)], on='a', enabled=True)
            code, selected = self.execute(['thermostat-scheduling', 'selected', str(path)])
            self.assertEqual(code, 0)
            self.assertTrue(selected['value'])
            self.assertIn('Supplied resolved', selected['scope'])
            code, required = self.execute(['thermostat-scheduling', 'required', str(path)])
            self.assertEqual(code, 0)
            self.assertTrue(required['value'])
            self.assertTrue(any(e.get('event') == 'find' for e in required['semantic_events']))

    def test_unused_sentinel_and_empty_share_negative_outcome(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unused = write_state(root, 'unused.json', groups=[group('a', 255)], on='a', enabled=True)
            empty = write_state(root, 'empty.json', groups=[], enabled=True)
            code, first = self.execute(['thermostat-scheduling', 'selected', str(unused)])
            self.assertEqual(code, 0)
            self.assertFalse(first['value'])
            code, second = self.execute(['thermostat-scheduling', 'selected', str(empty)])
            self.assertEqual(code, 0)
            self.assertEqual(first['value'], second['value'])

    def test_malformed_state_missing_file_and_duplicates_are_errors(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, result = self.execute(['thermostat-scheduling', 'selected', str(root / 'absent.json')])
            self.assertEqual(code, 1)
            self.assertIn('Cannot read', result['error'])
            broken = root / 'broken.json'
            broken.write_text('{not json', encoding='utf-8')
            code, result = self.execute(['thermostat-scheduling', 'selected', str(broken)])
            self.assertEqual(code, 1)
            dup = write_state(root, 'dup.json', groups=[group('a', 1), group('b', 1)], on='a', enabled=True)
            code, result = self.execute(['thermostat-scheduling', 'selected', str(dup)])
            self.assertEqual(code, 1)
            self.assertIn('unique', result['error'])

    def test_direct_boundary_rejects_unknown_area_and_action(self):
        from types import SimpleNamespace
        with self.assertRaises(ValueError):
            boundary.run(SimpleNamespace(area='wrong', action='selected', state=None))
        with self.assertRaises(ValueError):
            boundary.run(SimpleNamespace(area='thermostat-scheduling', action='wrong', state=None))

    def test_create_levels_direct_composes_without_save_providers(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_state(root, groups=[group('a', 1)], on='a', enabled=True)
            code, result = self.execute(['thermostat-scheduling', 'create-levels', str(path),
                                         '--policy', 'direct'])
            self.assertEqual(code, 0)
            self.assertTrue(result['complete'])
            self.assertEqual(result['operation'], 'create_remote_schedule_levels')
            self.assertEqual(result['policy'], 'direct')
            self.assertEqual(len(result['roles']), 1)
            self.assertEqual(result['roles'][0]['action'], 'Enable')
            self.assertFalse(result['native_persistence_verified'])
            self.assertIn('no save providers', result['scope'].lower() if isinstance(result['scope'], str) else result['scope'])

    def test_create_levels_button_disabled_is_noop_with_complete(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_state(root, groups=[group('a', 1)], on='a', enabled=False)
            code, result = self.execute(['thermostat-scheduling', 'create-levels', str(path)])
            self.assertEqual(code, 0)
            self.assertTrue(result['complete'])
            self.assertEqual(result['roles'], [])
            self.assertEqual(result['events'], [{'event': 'enabled', 'value': False}])

    def test_create_levels_rejects_unknown_policy_before_reading_state(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                cli.main(['thermostat-scheduling', 'create-levels', 'state.json',
                          '--policy', 'sometimes'])
        self.assertEqual(error.exception.code, 2)

    def test_end_save_lock_releases_caller_owned_lock(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_state(root, groups=[group('a', 1)], on='a', enabled=True,
                               save_lock=1, pending_save=True)
            code, result = self.execute(['thermostat-scheduling', 'end-save-lock', str(path)])
            self.assertEqual(code, 0)
            self.assertTrue(result['complete'])
            self.assertEqual(result['operation'], 'end_save_lock')
            self.assertEqual(result['state']['save_lock'], 0)
            self.assertFalse(result['state']['pending_save'])

    def test_end_save_lock_without_lock_is_error(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_state(root, groups=[group('a', 1)], on='a', enabled=True)
            code, result = self.execute(['thermostat-scheduling', 'end-save-lock', str(path)])
            self.assertEqual(code, 1)
            self.assertIn('save lock', result['error'].lower())


if __name__ == '__main__':
    unittest.main()
