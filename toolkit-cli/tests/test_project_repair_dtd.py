"""Exact original internal-DTD repair vectors and pre-DOM safety bounds."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.project_repair import (
    ProjectRepairError, preprocess_project_xml, repair_project_xml,
    transform_project_repair_xml,
)
from cbus_toolkit.project_repair_cli import ProjectRepairFileError, ProjectRepairFileOperation


FIXTURE = Path(__file__).resolve().parents[1] / 'research/fixtures/project-repair-dtd-vectors.json'
FIXTURE_SHA256 = '35e2c58d4f08ec2306b914210fa3603407f971daa76d1edbe000f21e0f48c4c7'


class ProjectRepairDTDTests(unittest.TestCase):
    def test_pinned_original_direct_and_full_outcomes(self):
        raw = FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), FIXTURE_SHA256)
        fixture = json.loads(raw)
        self.assertEqual(fixture['target'], 'original C-Gate 3.4.0.2001 repair methods')
        self.assertEqual(fixture['original']['java_exit_code'], 0)
        self.assertTrue(fixture['original']['temporary_directory_removed'])
        rows = fixture['rows']
        self.assertEqual(len(rows), 36)
        self.assertEqual(sum(row['status'] == 'OK' for row in rows), 26)
        for row in rows:
            with self.subTest(case=row['id']):
                source = bytes.fromhex(row['input_hex'])
                expected = bytes.fromhex(row['output_hex'])
                if row['operation'] == 'full':
                    call = lambda: repair_project_xml(source).repaired_xml
                else:
                    call = lambda: transform_project_repair_xml(source, stage=row['operation'])
                if row['status'] == 'OK':
                    self.assertEqual(call(), expected)
                    self.assertNotIn(b'<!DOCTYPE', expected)
                else:
                    self.assertEqual(row['operation'], 'full')
                    self.assertEqual(preprocess_project_xml(source), expected)
                    with self.assertRaises(ProjectRepairError) as caught:
                        call()
                    self.assertEqual(caught.exception.stage, 'repair')

    def test_external_and_parameter_entities_stop_before_dom(self):
        samples = (
            b'<!DOCTYPE Project SYSTEM "file:///nonexistent-cbus-repair-fixture"><Project/>',
            b'<!DOCTYPE Project [<!ENTITY x SYSTEM "file:///nonexistent-cbus-repair-fixture">]><Project>&x;</Project>',
            b'<!DOCTYPE Project [<!ENTITY x PUBLIC "id" "https://invalid.example/entity">]><Project/>',
            b'<!DOCTYPE Project [<!NOTATION n SYSTEM "file:///nonexistent-cbus-repair-fixture"><!ENTITY x SYSTEM "file:///nonexistent-cbus-repair-fixture" NDATA n>]><Project/>',
            b'<!DOCTYPE Project [<!ENTITY % x "unused">]><Project/>',
        )
        for source in samples:
            with self.subTest(source=source), patch('cbus_toolkit.project_repair.minidom.parseString') as dom, \
                 patch('cbus_toolkit.project_repair.expatbuilder.ExpatBuilderNS') as builder:
                with self.assertRaises(ProjectRepairError):
                    transform_project_repair_xml(source, stage='tidy')
                dom.assert_not_called()
                builder.assert_not_called()

    def test_expansion_and_entity_count_limits_stop_before_dom(self):
        nested = (b'<!DOCTYPE Project [<!ENTITY a "1234567890">'
                  b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
                  b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
                  b'<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">]><Project>&d;</Project>')
        default_attributes = (b'<!DOCTYPE Project [<!ENTITY x "' + b'A' * 700 +
                              b'"><!ATTLIST Project a CDATA "&x;" b CDATA "&x;">]><Project/>')
        too_many = (b'<!DOCTYPE Project [' +
                    b''.join(f'<!ENTITY e{i} "x">'.encode() for i in range(257)) +
                    b']><Project/>')
        for source, options in ((nested, {'max_bytes': 1024}),
                                (default_attributes, {'max_bytes': 1024}),
                                (too_many, {})):
            with self.subTest(case=source[:60]), patch('cbus_toolkit.project_repair.minidom.parseString') as dom, \
                 patch('cbus_toolkit.project_repair.expatbuilder.ExpatBuilderNS') as builder:
                with self.assertRaises(ProjectRepairError):
                    transform_project_repair_xml(source, stage='repair', **options)
                dom.assert_not_called()
                builder.assert_not_called()

    def test_entity_markup_obeys_node_bound_before_dom(self):
        source = (b'<!DOCTYPE Project [<!ENTITY x "<A/><A/><A/><A/>">]>'
                  b'<Project>&x;</Project>')
        with patch('cbus_toolkit.project_repair.minidom.parseString') as dom:
            with self.assertRaises(ProjectRepairError) as caught:
                transform_project_repair_xml(source, stage='tidy', max_nodes=5)
            self.assertEqual(caught.exception.stage, 'tidy')
            dom.assert_not_called()

    def test_full_file_boundary_writes_only_a_supported_doctype_result(self):
        rows = {row['id']: row for row in json.loads(FIXTURE.read_bytes())['rows']}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / 'source.xml', root / 'repaired.xml'
            successful = rows['no-subset-full']
            source.write_bytes(bytes.fromhex(successful['input_hex']))
            result = ProjectRepairFileOperation().run(source, output=target)
            self.assertTrue(result['complete'])
            self.assertEqual(target.read_bytes(), bytes.fromhex(successful['output_hex']))
            target.unlink()
            rejected = rows['one-text-full']
            original = bytes.fromhex(rejected['input_hex'])
            source.write_bytes(original)
            with self.assertRaises(ProjectRepairFileError) as caught:
                ProjectRepairFileOperation().run(source, output=target)
            self.assertEqual(caught.exception.details['repair_failure_stage'], 'repair')
            self.assertFalse(caught.exception.details['output_create_attempted'])
            self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), original)
