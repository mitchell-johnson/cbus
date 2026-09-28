"""Source-bound original cases for XML 1.1 combined with internal DTDs."""

from hashlib import sha256
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.project_repair import (
    ProjectRepairError, repair_project_xml, transform_project_repair_xml,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/project-repair-dtd-xml11-vectors.json'
CAPTURE = ROOT / 'research/capture_project_repair_dtd_xml11.py'


def vectors():
    return json.loads(FIXTURE.read_text())


class ProjectRepairDTDXML11Tests(unittest.TestCase):
    def test_pinned_intersection_outcomes(self):
        fixture = vectors()
        self.assertEqual(fixture['format'], 'cbus-project-repair-dtd-xml11-original-v1')
        self.assertEqual(fixture['capture_script_sha256'], sha256(CAPTURE.read_bytes()).hexdigest())
        self.assertTrue(fixture['temporary_directory_removed'])
        self.assertEqual(fixture['java_exit_code'], 0)
        self.assertEqual(len(fixture['rows']), 9)
        self.assertEqual(sum(row['status'] == 'OK' for row in fixture['rows']), 6)
        for row in fixture['rows']:
            with self.subTest(case=row['id']):
                data = bytes.fromhex(row['input_hex'])
                if row['status'] == 'ERROR':
                    self.assertEqual(row['operation'], 'full')
                    with self.assertRaises(ProjectRepairError) as caught:
                        repair_project_xml(data)
                    self.assertEqual(caught.exception.stage, 'repair')
                else:
                    observed = transform_project_repair_xml(data, stage=row['operation'])
                    self.assertEqual(observed, bytes.fromhex(row['output_hex']))


@unittest.skipUnless(all(os.environ.get(name) for name in (
    'CBUS_CGATE_JAVA', 'CBUS_CGATE_JAVAC', 'CBUS_LOCAL_CGATE_VENDOR')),
    'requires exact original C-Gate jar/stylesheets and Java 11')
class OriginalProjectRepairDTDXML11Tests(unittest.TestCase):
    def test_fresh_pinned_original_matches_fixture(self):
        from research.project_repair_original import run_original

        fixture = vectors()
        java = Path(os.environ['CBUS_CGATE_JAVA'])
        javac = Path(os.environ['CBUS_CGATE_JAVAC'])
        vendor = Path(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        sources = {
            'java': java,
            'javac': javac,
            'cgate.jar': vendor / 'cgate.jar',
            'repair.xslt': vendor / 'transform/repair.xslt',
            'tidyduplicategroups.xslt': vendor / 'transform/tidyduplicategroups.xslt',
            'RepairStageProbe.java': ROOT / 'research/RepairStageProbe.java',
            'project_repair_original.py': ROOT / 'research/project_repair_original.py',
        }
        for name, source in sources.items():
            with self.subTest(source=name):
                self.assertEqual(sha256(source.read_bytes()).hexdigest(),
                                 fixture['source_pins'][name])
        cases = [{key: row[key] for key in ('id', 'input_hex', 'operation')}
                 for row in fixture['rows']]
        report = run_original(cases, java=java, javac=javac, vendor=vendor)
        self.assertEqual(report['java_exit_code'], 0)
        self.assertTrue(report['temporary_directory_removed'])
        self.assertEqual(report['class_sha256'], fixture['probe_class_sha256'])
        self.assertEqual(report['stdout_sha256'], fixture['stdout_sha256'])
        self.assertEqual(report['stderr_sha256'], fixture['stderr_sha256'])
        for native, expected in zip(report['rows'], fixture['rows']):
            with self.subTest(case=expected['id']):
                for key in ('status', 'output_hex', 'error', 'response'):
                    self.assertEqual(native[key], expected[key])
