"""Retain source findings without promoting application migration to support."""
import importlib
import json
import os
from pathlib import Path
import sys
import unittest


RESEARCH = Path(__file__).resolve().parents[1] / 'research'
COMPONENTS = ('change', 'events', 'order', 'selector')


def receipt(component):
    return json.loads((RESEARCH / 'fixtures' /
        ('thermostat-application-' + component + '-source-review.json')).read_text())


class ApplicationSourceTests(unittest.TestCase):
    def test_source_evidence_does_not_claim_execution(self):
        for component in COMPONENTS:
            with self.subTest(component=component):
                value = receipt(component)
                self.assertEqual(value['original_exe_sha256'],
                    '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab')
                self.assertEqual(value['original_map_sha256'],
                    'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb')
                self.assertIs(value['original_executed'], False)
                self.assertIs(value['physical_io'], False)
                self.assertTrue(value['checks'])
                self.assertTrue(all(value['checks'].values()))
                self.assertNotIn('/Users/', json.dumps(value))
                self.assertNotIn('/Volumes/', json.dumps(value))
        self.assertIs(receipt('change')['boundary']['implementation_complete'], False)

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_TOOLKIT_MAP'),
                         'optional static inspection requires the pinned original EXE/MAP')
    def test_static_findings_match_original(self):
        sys.path.insert(0, str(RESEARCH))
        self.addCleanup(sys.path.remove, str(RESEARCH))
        for component in COMPONENTS:
            with self.subTest(component=component):
                module = importlib.import_module('thermostat_application_' + component + '_static')
                actual = module.inspect(Path(os.environ['CBUS_TOOLKIT_EXE']),
                                        Path(os.environ['CBUS_TOOLKIT_MAP']))
                self.assertEqual(actual, receipt(component))
