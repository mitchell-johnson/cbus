"""Full PP/control comparisons against captured original Windows results."""
import hashlib
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.edlt_restore_levels import EdltRestoreLevels
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt_restore_levels import metadata

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('CBUS_UNITSPEC_DIR'), 'Set exact vendor specification for full original preset vectors')
class RestoreWindowsVectorTests(unittest.TestCase):
    def test_all_original_pp_phases_and_actual_control_visibility(self):
        path = ROOT / 'research/fixtures/edlt-restore-levels-windows-vectors.json'
        document = json.loads(path.read_text())
        self.assertEqual(document['format'], 'cbus-edlt-restore-windows-vectors-v1')
        self.assertEqual(len(document['vectors']), 64); self.assertEqual(len(document['exclusions']), 20)
        specs = Path(os.environ['CBUS_UNITSPEC_DIR'])
        digest = hashlib.sha256((specs / 'KEYGL5.xml').read_bytes()).hexdigest()
        self.assertTrue(all(row['input_sha256']['KEYGL5.xml'] == digest for row in document['observations']))
        editor = EdltRestoreLevels(UnitSpecStore(specs).load('KEYGL5.xml'))
        for row in document['vectors']:
            with self.subTest(case=row['case']):
                source = editor.snapshot({**document['baseline'], **row['initial']})
                plan = editor.plan(source, metadata=metadata(editor, source, row['cache']), **row['options'])
                actual = {'after_load': plan.after_load, 'after_controls': plan.after_controls,
                          'before_save': plan.before_save, 'final': {**plan.expected, **plan.changes}}
                for phase, changes in row['phases'].items():
                    wanted = editor.snapshot({**source, **changes})
                    self.assertEqual(len(wanted), 874)
                    self.assertEqual(dict(actual[phase]), wanted, phase)
                controls = plan.as_dict()['controls']
                self.assertEqual(len(controls), 16)
                for expected, observed in zip(row['controls'], controls):
                    self.assertEqual(expected['widget'], observed['widget'])
                    self.assertEqual(expected['visible'], observed['visible'])
                    self.assertEqual(expected['group_name'], observed['group_name'])
                    self.assertEqual(expected['level'], observed['level_after_controls'])
                    self.assertEqual(expected['stored_level'], observed['level_after_controls'])


if __name__ == '__main__': unittest.main()
