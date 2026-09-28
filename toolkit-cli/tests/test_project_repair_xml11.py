"""Source-bound XML 1.1 repair behavior from C-Gate 3.4.0.2001."""

from hashlib import sha256
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.project_repair import (
    ProjectRepairError, repair_project_xml, transform_project_repair_xml,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/project-repair-xml11-vectors.json'


def vectors():
    return json.loads(FIXTURE.read_text())


class ProjectRepairXML11Tests(unittest.TestCase):
    def test_original_xml11_direct_and_full_outcomes(self):
        fixture = vectors()
        rows = fixture['rows']
        self.assertEqual(fixture['format'], 'cbus-project-repair-xml11-original-v1')
        self.assertEqual(len(rows), 57)
        self.assertEqual(sum(row['status'] == 'OK' for row in rows), 44)
        self.assertEqual(sum(row['status'] == 'ERROR' for row in rows), 13)
        for row in rows:
            data = bytes.fromhex(row['input_hex'])
            with self.subTest(case=row['id']):
                if row['status'] == 'ERROR':
                    with self.assertRaises(ProjectRepairError) as caught:
                        self._candidate(data, row['operation'])
                    self.assertEqual(caught.exception.stage, row['expected_failure_stage'])
                else:
                    self.assertEqual(self._candidate(data, row['operation']),
                                     bytes.fromhex(row['output_hex']))

    def test_xml11_stand_ins_do_not_alias_existing_private_use_characters(self):
        source = ('<?xml version="1.1"?><Project><T>\ue000&#xE001;&#x1f;'
                  '</T></Project>').encode()
        output = transform_project_repair_xml(source, stage='tidy')
        self.assertIn('\ue000\ue001&#31;'.encode(), output)

    def test_undeclaration_spelling_inside_an_attribute_is_ordinary_text(self):
        source = b'<?xml version="1.1"?><Project note=\' xmlns:p=""\'/>'
        output = transform_project_repair_xml(source, stage='tidy')
        self.assertIn(b'note=" xmlns:p=&quot;&quot;"', output)

    @staticmethod
    def _candidate(data, operation):
        if operation == 'full':
            return repair_project_xml(data).repaired_xml
        return transform_project_repair_xml(data, stage=operation)


@unittest.skipUnless(all(os.environ.get(name) for name in (
    'CBUS_CGATE_JAVA', 'CBUS_CGATE_JAVAC', 'CBUS_LOCAL_CGATE_VENDOR')),
    'requires exact original C-Gate jar/stylesheets and Java 11')
class OriginalProjectRepairXML11Tests(unittest.TestCase):
    def test_fresh_pinned_original_matches_source_bound_vectors(self):
        from research.project_repair_original import run_original

        fixture = vectors()
        pins = fixture['source_pins']
        java = Path(os.environ['CBUS_CGATE_JAVA'])
        javac = Path(os.environ['CBUS_CGATE_JAVAC'])
        vendor = Path(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        sources = {
            'java_sha256': java,
            'javac_sha256': javac,
            'cgate_jar_sha256': vendor / 'cgate.jar',
            'repair_xslt_sha256': vendor / 'transform/repair.xslt',
            'tidy_xslt_sha256': vendor / 'transform/tidyduplicategroups.xslt',
            'probe_java_sha256': ROOT / 'research/RepairStageProbe.java',
            'harness_sha256': ROOT / 'research/project_repair_original.py',
        }
        for key, path in sources.items():
            with self.subTest(source=key):
                self.assertEqual(sha256(path.read_bytes()).hexdigest(), pins[key])
        report = run_original(fixture['rows'], java=java, javac=javac, vendor=vendor)
        self.assertEqual(report['java_exit_code'], 0)
        self.assertTrue(report['temporary_directory_removed'])
        self.assertEqual(report['class_sha256'], pins['probe_class_sha256'])
        self.assertEqual(report['stdout_sha256'], pins['native_stdout_sha256'])
        self.assertEqual(report['stderr_sha256'], pins['native_stderr_sha256'])
        for expected, actual in zip(fixture['rows'], report['rows']):
            with self.subTest(case=expected['id']):
                for key in ('status', 'output_hex', 'error'):
                    self.assertEqual(actual[key], expected[key])
