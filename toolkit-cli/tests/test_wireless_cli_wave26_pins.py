"""Wave-26 offline pins for wireless CLI guards (P5.07).

Narrow pin over ``toolkit-cli/src/cbus_toolkit/wireless_cli.py`` only.
Each test pins a branch with zero prior exact-symbol refs (verified via
grep -rn across tests/ before writing):
- ``gateway_settings``: grep -rn "gateway_settings" tests/*.py -> 0 hits.
- ``connection_settings``: grep -rn "connection_settings" tests/*.py -> 0 hits.
- ``globals_settings``: grep -rn "globals_settings" tests/*.py -> 0 hits.
- ``_bounded_xml``: grep -rn "_bounded_xml" tests/*.py -> 0 hits (the only
  "bounded_xml" hit is the unrelated "bounded_xml_wire_line" live-project
  test name in test_toolkit_database_csv_project_export.py).

Pure argparse-namespace and tmp-file guards only; no hardware, vendor EXE,
C-Gate server, or decoded vendor spec is required.
"""
from types import SimpleNamespace
import unittest

from cbus_toolkit.wireless_cli import (
    _bounded_xml,
    connection_settings,
    gateway_settings,
    globals_settings,
)


def _gateway_args(**overrides):
    base = {'mode': None, 'remote': None, 'serial': None,
            'remote_keys': [], 'remote_slots': []}
    base.update(overrides)
    return SimpleNamespace(**base)


def _connection_args(**overrides):
    base = {'application1': None, 'application2': None,
            'status_monitor_application': None, 'adjacent_network': None,
            'synchronise_to_wired': None, 'destination_network': None}
    base.update(overrides)
    return SimpleNamespace(**base)


def _globals_args(**overrides):
    base = {'key_enable_mask': [], 'learn_mode': None, 'house_code': None,
            'network_learn': None, 'key_mask_allowed': None,
            'key_mask_save': None, 'reset_learned': False}
    base.update(overrides)
    return SimpleNamespace(**base)


class WirelessCliWave26Pins(unittest.TestCase):
    def test_gateway_settings_refuses_duplicate_remote_key(self):
        args = _gateway_args(remote_keys=['1=group:1', '1=group:2'])
        with self.assertRaisesRegex(ValueError, r'--remote-key 1 was selected more than once'):
            gateway_settings(args)
        args = _gateway_args(remote_slots=['3=group:1', '3=group:2'])
        with self.assertRaisesRegex(ValueError, r'--remote-slot 3 was selected more than once'):
            gateway_settings(args)
        args = _gateway_args(serial='none')
        self.assertEqual(gateway_settings(args), {'serial': None})

    def test_gateway_settings_refuses_malformed_pair(self):
        for bad in ('noequals', 'x=group:1', '1=  '):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, r'uses N=VALUE'):
                    gateway_settings(_gateway_args(remote_keys=[bad]))

    def test_connection_settings_coerces_toggles_and_none_destination(self):
        args = _connection_args(application1=56, adjacent_network='off',
                                synchronise_to_wired='on',
                                destination_network='none')
        self.assertEqual(connection_settings(args),
                         {'application1': 56, 'adjacent_network': False,
                          'synchronise_to_wired': True,
                          'destination_network': None})
        with self.assertRaisesRegex(ValueError, 'Expected an integer'):
            connection_settings(_connection_args(destination_network='bogus'))

    def test_globals_settings_refuses_duplicate_mask_and_coerces_learn(self):
        args = _globals_args(key_enable_mask=['2=0x10', '2=0x20'])
        with self.assertRaisesRegex(ValueError, r'--key-enable-mask 2 was selected more than once'):
            globals_settings(args)
        args = _globals_args(network_learn='off', reset_learned=True,
                             key_enable_mask=['1=16'])
        self.assertEqual(globals_settings(args),
                         {'network_learn': False, 'key_enable_masks': {1: 16},
                          'reset_learned': True})

    def test_bounded_xml_enforces_size_cap_offline(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.xml'
            path.write_bytes(b'<x/>')
            self.assertEqual(_bounded_xml(path, 4), b'<x/>')
            path.write_bytes(b'12345')
            with self.assertRaisesRegex(ValueError, 'exceeds the command size cap'):
                _bounded_xml(path, 4)


if __name__ == '__main__':
    unittest.main()
