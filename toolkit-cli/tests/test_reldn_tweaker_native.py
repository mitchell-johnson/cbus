"""Provisioned native acceptance for the bounded Toolkit RELDN conversion path."""
import os
from pathlib import Path
import unittest


@unittest.skipUnless(all(os.environ.get(name) for name in
                         ('CBUS_CGATE_JAVA', 'CBUS_LOCAL_CGATE_VENDOR', 'CBUS_UNITSPEC_DIR')),
                     'set CBUS_CGATE_JAVA, CBUS_LOCAL_CGATE_VENDOR and CBUS_UNITSPEC_DIR for native RELDN acceptance')
class NativeReldnTweakerTests(unittest.TestCase):
    def test_original_vectors_raw_pp_source_preservation_and_project_reload(self):
        from research.reldn_tweaker_native import run
        report = run(vendor=Path(os.environ['CBUS_LOCAL_CGATE_VENDOR']),
                     java=Path(os.environ['CBUS_CGATE_JAVA']),
                     spec_dir=Path(os.environ['CBUS_UNITSPEC_DIR']))
        self.assertTrue(report['passed'])
        self.assertEqual(report['summary'], {'directions': 8, 'converted': 7, 'refused_short_original_source': 1})
        self.assertFalse(report['requested_directions_complete'])
        self.assertTrue(report['backend']['listener_ownership_verified'])
        self.assertTrue(report['backend']['cleanup_complete'])
        self.assertFalse(report['hardware_contacted'])
        self.assertFalse(report['original_toolkit_gui_executed'])


if __name__ == '__main__':
    unittest.main()
