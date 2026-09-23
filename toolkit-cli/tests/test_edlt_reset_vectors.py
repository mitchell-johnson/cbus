"""Exact original raw/dirty Reset phases, independently recorded on Windows."""
import hashlib
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.unitspec import UnitSpecStore
from cbus_toolkit.edlt_reset import EdltResetControls
from tests.test_edlt_reset import metadata

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('CBUS_UNITSPEC_DIR'), 'Select the exact original Reset unit specification')
class ResetVectorsTests(unittest.TestCase):
    def test_all44_original_executions_520_raw_dirty_phases(self):
        document = json.loads((ROOT / 'research/fixtures/edlt-reset-windows-vectors.json').read_text())
        self.assertEqual(document['original_execution_count'], 44)
        self.assertEqual(document['all_parameter_phase_count'], 520)
        spec_path = Path(os.environ['CBUS_UNITSPEC_DIR']) / 'KEYGL5.xml'
        for source in document['sources']:
            self.assertEqual(hashlib.sha256((ROOT / 'research' / source['source']).read_bytes()).hexdigest(), source['source_sha256'])
            self.assertEqual(hashlib.sha256(spec_path.read_bytes()).hexdigest(), source['input_source_hashes']['KEYGL5.xml'])
        editor = EdltResetControls(UnitSpecStore(spec_path.parent).load('KEYGL5.xml'))
        total = 0
        for row in document['cases']:
            with self.subTest(case=row['name']):
                source = {**document['baseline'], **row['source_changes']}
                plan = editor.plan(source, metadata=metadata(row['metadata_mode']),
                    active_tab=row['active_tab'], binding_variant=row['binding_variant'],
                    dirty_parameters=row['phases']['input']['dirty_parameters'])
                wanted = dict(source)
                for stage, changes in row['phases'].items():
                    wanted.update(changes['raw_changes'])
                    self.assertEqual(len(wanted), 874)
                    self.assertEqual(dict(plan.phases[stage].raw), wanted, stage)
                    self.assertEqual(set(plan.phases[stage].dirty_parameters), set(changes['dirty_parameters']), stage)
                    self.assertIs(plan.phases[stage].initializing, changes['initializing'])
                    total += 874
        self.assertEqual(total, 454480)
