"""Owned local C-Gate discovery and explicit simulator write boundaries."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.verify_network import verify


class NetworkOracleGuardTests(unittest.TestCase):
    def test_invalid_requests_do_not_launch_or_inspect_a_service(self):
        with patch('research.local_cgate.LocalCGate', side_effect=AssertionError('No service launch')), \
                patch('research.verify_network.subprocess.run', side_effect=AssertionError('No service inspection')):
            for options in ({'backend': 'unknown'}, {'duration': 0}, {'duration': 121}, {'fixture': 'unknown'}):
                with self.assertRaises(ValueError): verify(**options)


@unittest.skipUnless(os.environ.get('CBUS_CGATE_JAVA') and os.environ.get('CBUS_LOCAL_CGATE_VENDOR'),
                     'Set Java and original vendor directory for owned local network acceptance')
class NativeNetworkOracleTests(unittest.TestCase):
    def test_owned_loopback_discovery_programming_bytes_and_disk_restoration(self):
        with tempfile.TemporaryDirectory() as directory:
            report = verify(backend='local', duration=10, output_dir=directory)
            destination = os.environ.get('CBUS_LOCAL_NETWORK_REPORT')
            if destination:
                path = Path(destination); path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(report, indent=2) + '\n')
            self.assertEqual(report['acceptance_status'], 'passed')
            self.assertEqual({(r['unit'], r['type'], r['state']) for r in report['discovered_units']},
                             {(4, 'KEYE1', 'ok'), (5, 'KEYGL5', 'ok'), (16, 'PC_CNIED', 'ok')})
            self.assertTrue(report['simulator_endpoint'].startswith('127.0.0.1:'))
            self.assertEqual(report['unsupported_requests'], []); self.assertEqual(report['cleanup_errors'], [])
            write = report['physical_write']
            self.assertEqual((write['original'], write['written'], write['read_back'], write['reloaded_read_back'], write['restored']),
                             ('38ff', '39ff', '39ff', '39ff', '38ff'))
            service = report['local_service']
            self.assertTrue(service['cleanup_complete']); self.assertTrue(service['process_exit_confirmed'])
            self.assertEqual(len(service['listeners']), 6)
            self.assertTrue(all(listener.startswith('127.0.0.1:') for listener in service['listeners']))
            self.assertEqual(json.loads(Path(report['report_path']).read_text()), report)


if __name__ == '__main__': unittest.main()
