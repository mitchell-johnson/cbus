"""Captured original Toolkit bound Blank selections; no model-generated expected state."""
import hashlib
import json
import os
from pathlib import Path
import unittest
from cbus_toolkit.edlt_blank import EdltBlankWidget
from tests.test_edlt_lifecycle import cache
from cbus_toolkit.unitspec import UnitSpecStore
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.environ.get("CBUS_UNITSPEC_DIR"), "Select exact original unit spec for full original Blank vectors")
class BlankVectorsTests(unittest.TestCase):
    def test_original_31_cases_all_parameters_at_five_phases(self):
        path=ROOT/'research/fixtures/edlt-blank-windows-vectors.json'
        data=json.loads(path.read_text());self.assertTrue(data['source_unchanged'])
        self.assertEqual(hashlib.sha256((ROOT/'research/NativeEdltBlankProbe.cs').read_bytes()).hexdigest(),data['source_before']['probe.cs'])
        self.assertEqual(len(data['cases']),31);editor=EdltBlankWidget(UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"]).load("KEYGL5.xml"))
        self.assertEqual(hashlib.sha256((Path(os.environ["CBUS_UNITSPEC_DIR"])/"KEYGL5.xml").read_bytes()).hexdigest(),data["source_before"]["KEYGL5.xml"])
        for row in data['cases']:
            with self.subTest(case=row['name']):
                source=editor.snapshot({**data['baseline'],**row['source_changes']})
                plan=editor.plan(source,metadata=cache(editor,source),page=row['page'],position=row['position'])
                self.assertEqual(plan.slot,row['slot']);self.assertIn(0,row['original_choices'])
                wanted=source
                for stage,actual in (('after-load',plan.after_load),('after-bind',plan.after_load),('after-select',plan.after_controls),('before-save',plan.before_save),('final',{**plan.expected,**plan.changes})):
                    wanted=editor.snapshot({**wanted,**row['phase_changes'][stage]})
                    self.assertEqual(len(wanted),874);self.assertEqual(dict(actual),wanted,(row['name'],stage))
                self.assertEqual(not plan.type_changed,row['model_identity_retained'])
