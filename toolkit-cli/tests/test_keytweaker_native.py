"""Provisioned native acceptance for classic-to-Neo Toolkit conversion."""
import os
from pathlib import Path
import unittest


@unittest.skipUnless(all(os.environ.get(name) for name in
                         ('CBUS_CGATE_JAVA', 'CBUS_LOCAL_CGATE_VENDOR', 'CBUS_UNITSPEC_DIR')),
                     'set CBUS_CGATE_JAVA, CBUS_LOCAL_CGATE_VENDOR and CBUS_UNITSPEC_DIR for native key acceptance')
class NativeKeyTweakerTests(unittest.TestCase):
    def test_original_literals_all_93_profiles_raw_pp_and_project_reload(self):
        from research.keytweaker_native import run
        report = run(vendor=Path(os.environ['CBUS_LOCAL_CGATE_VENDOR']),
                     java=Path(os.environ['CBUS_CGATE_JAVA']),
                     spec_dir=Path(os.environ['CBUS_UNITSPEC_DIR']))
        self.assertTrue(report['passed'])
        self.assertEqual(report['summary'], {'directions': 93, 'passed': 93})
        self.assertEqual(report['reload_verified_units'], 98)
        self.assertTrue(report['backend']['listener_ownership_verified'])
        self.assertTrue(report['backend']['cleanup_complete'])
        self.assertFalse(report['hardware_contacted'])
        self.assertFalse(report['original_toolkit_gui_executed'])


if __name__ == '__main__':
    unittest.main()
