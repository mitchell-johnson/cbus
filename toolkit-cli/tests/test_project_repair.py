import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from xml.dom import Node, minidom

from cbus_toolkit.project_repair import (
    ProjectRepairError, preprocess_project_xml, repair_project_xml,
    transform_project_repair_xml,
)

ROOT = Path(__file__).resolve().parents[1]


def vectors():
    return json.loads((ROOT / 'research/fixtures/project-repair-vectors.json').read_text())


def semantic_xml(data):
    """Independent comparison of parsed XML, including text/PI/comment order."""
    document = minidom.parseString(data)

    def convert(node):
        if node.nodeType == Node.DOCUMENT_NODE:
            return [convert(child) for child in node.childNodes if child.nodeType != Node.TEXT_NODE]
        if node.nodeType == Node.ELEMENT_NODE:
            attributes = sorted((attr.namespaceURI or '', attr.localName or attr.name, attr.value)
                for attr in node.attributes.values() if attr.namespaceURI != 'http://www.w3.org/2000/xmlns/')
            children = []
            for child in node.childNodes:
                value = convert(child)
                if value[0] == 'text' and children and children[-1][0] == 'text':
                    children[-1][1] += value[1]
                else:
                    children.append(value)
            return ['element', node.namespaceURI or '', node.localName or node.nodeName, attributes, children]
        if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
            return ['text', node.data]
        return [node.nodeType, node.nodeName, node.nodeValue]

    try:
        return convert(document)
    finally:
        document.unlink()


def candidate(row):
    data = bytes.fromhex(row['input_hex'])
    if row['operation'] == 'full':
        return repair_project_xml(data, line_ending=row['line_ending']).repaired_xml
    return transform_project_repair_xml(data, stage=row['operation'], line_ending=row['line_ending'])


class ProjectRepairTests(unittest.TestCase):
    def test_original_manual_lexical_newlines_and_malformed_utf8_vectors(self):
        rows = vectors()['manual_rows']
        self.assertGreaterEqual(len(rows), 3036)
        for row in rows:
            with self.subTest(case=row['id']):
                self.assertEqual(preprocess_project_xml(bytes.fromhex(row['input_hex']),
                    line_ending=row['line_ending']).hex(), row['output_hex'])

    def test_original_repair_and_tidy_transform_semantics_and_failures(self):
        rows = [row for row in vectors()['transform_rows'] if row['supported']]
        self.assertGreaterEqual(len(rows), 81)
        for row in rows:
            with self.subTest(case=row['id']):
                if row['status'] == 'ERROR':
                    with self.assertRaises(ProjectRepairError):
                        candidate(row)
                else:
                    actual, expected = candidate(row), bytes.fromhex(row['output_hex'])
                    if row['id'] == 'root-oid-repair':
                        self.assertEqual(actual, expected)
                    else:
                        self.assertEqual(semantic_xml(actual), semantic_xml(expected))

    def test_observed_xml11_and_other_encodings_are_explicitly_excluded(self):
        for row in vectors()['transform_rows']:
            if not row['supported']:
                with self.subTest(case=row['id']), self.assertRaises(ProjectRepairError):
                    candidate(row)
        for encoding in ('utf-16', 'utf-16-le', 'utf-16-be'):
            for stage in ('repair', 'tidy'):
                with self.subTest(encoding=encoding, stage=stage), self.assertRaises(ProjectRepairError):
                    transform_project_repair_xml('<Project/>'.encode(encoding), stage=stage)

    def test_character_references_remain_distinct_group_addresses(self):
        data = b'<Project><Application><Group><Address>1&#13;2</Address><TagName>CR</TagName></Group><Group><Address>1&#10;2</Address><TagName>LF</TagName></Group></Application></Project>'
        for ending in ('lf', 'crlf'):
            output = repair_project_xml(data, line_ending=ending).repaired_xml
            document = minidom.parseString(output)
            try:
                self.assertEqual([node.firstChild.data for node in document.getElementsByTagName('Address')], ['1\r2', '1\n2'])
                self.assertEqual([node.firstChild.data for node in document.getElementsByTagName('TagName')], ['CR', 'LF'])
            finally:
                document.unlink()

    def test_attribute_and_namespace_whitespace_survive_both_python_versions(self):
        data = b'<Project a="&#9;&#10;&#13;" xmlns:x="urn:a&#9;b&#10;c&#13;d"><x:X x:a="&#9;&#10;&#13;"/></Project>'
        output = repair_project_xml(data).repaired_xml
        document = minidom.parseString(output)
        try:
            project = document.getElementsByTagName('Project')[0]
            self.assertEqual(project.getAttribute('a'), '\t\n\r')
            child = document.getElementsByTagName('x:X')[0]
            self.assertEqual(child.namespaceURI, 'urn:a\tb\nc\rd')
            self.assertEqual(child.getAttributeNS(child.namespaceURI, 'a'), '\t\n\r')
        finally:
            document.unlink()

    def test_repair_is_not_a_general_well_formedness_fixer(self):
        for data in (b'<Project a="x>y"/>', b'<Project></Wrong>', b'<Project><![CDATA[a<b>c]]></Project>'):
            with self.subTest(data=data), self.assertRaises(ProjectRepairError):
                repair_project_xml(data)
        self.assertEqual(preprocess_project_xml(b'<'), b'<\n')

    def test_dtd_and_entity_expansion_are_rejected_before_dom_creation(self):
        for data in (b'<!DOCTYPE Project [<!ENTITY x "expanded">]><Project>&x;</Project>',
                     b'<!DOCTYPE Project SYSTEM "file:///nonexistent-cbus-repair-fixture"><Project/>',
                     b'<!DOCTYPE Project SYSTEM "https://invalid.example/cbus"><Project/>'):
            with self.subTest(data=data), self.assertRaises(ProjectRepairError):
                transform_project_repair_xml(data, stage='repair')

    def test_byte_depth_node_and_option_limits_fail_closed(self):
        for name in ('max_bytes', 'max_nodes', 'max_depth'):
            for bad in (False, 0, -1, 1.5, None, '8', 10**12):
                with self.subTest(name=name, bad=bad), self.assertRaises(ValueError):
                    repair_project_xml(b'<Project/>', **{name: bad})
        for data in ('<Project/>', bytearray(b'<Project/>')):
            with self.assertRaises(TypeError):
                repair_project_xml(data)
        for options in ({'max_bytes': 5}, {'max_nodes': 2}, {'max_depth': 1}):
            with self.subTest(options=options), self.assertRaises(ProjectRepairError):
                repair_project_xml(b'<Project><X/></Project>', **options)
        with self.assertRaises(ProjectRepairError):
            preprocess_project_xml(b'<<', max_bytes=2)
        with self.assertRaises(ProjectRepairError):
            transform_project_repair_xml(b'<Project/>', stage='repair', max_bytes=20)
        for bad in ('native', '', None):
            with self.assertRaises(ValueError):
                repair_project_xml(b'<Project/>', line_ending=bad)
        with self.assertRaises(ValueError):
            transform_project_repair_xml(b'<Project/>', stage='unknown')

    def test_parser_counts_attributes_comments_pi_and_text_before_dom_allocation(self):
        for data in (b'<Project a="1" b="2"/>', b'<Project><!--a--><!--b--><!--c--></Project>',
                     b'<Project><?a x?><?b y?><?c z?></Project>', b'<Project>a&amp;b&amp;c</Project>'):
            with self.subTest(data=data), patch('cbus_toolkit.project_repair.minidom.parseString') as dom:
                with self.assertRaises(ProjectRepairError):
                    transform_project_repair_xml(data, stage='repair', max_nodes=4)
                dom.assert_not_called()

    def test_output_separates_repair_from_native_format_and_load_acceptance(self):
        original = b'<Project><TagName>P</TagName></Project>'
        result = repair_project_xml(original)
        report = result.as_dict()
        self.assertEqual(report['db_version'], '2.2')
        self.assertTrue(report['repair_complete'])
        self.assertTrue(report['output_well_formed'])
        self.assertIsNone(report['native_loadable'])
        self.assertFalse(report['native_load_verified'])
        self.assertFalse(report['file_modified'])
        self.assertFalse(report['physical_io_attempted'])
        report['repair_complete'] = False
        self.assertTrue(result.as_dict()['repair_complete'])
        modern = repair_project_xml(b'<Installation><DBVersion>2.3</DBVersion><Project/></Installation>')
        self.assertEqual(modern.db_version, '2.3')
        self.assertIsNone(modern.as_dict()['native_loadable'])


@unittest.skipUnless(all(os.environ.get(name) for name in ('CBUS_CGATE_JAVA', 'CBUS_CGATE_JAVAC', 'CBUS_LOCAL_CGATE_VENDOR')),
                     'requires exact original local C-Gate jar/stylesheets and Java11 JDK')
class OriginalProjectRepairTests(unittest.TestCase):
    def original(self, rows, line_ending='lf'):
        from research.project_repair_original import run_original
        report = run_original(rows, java=os.environ['CBUS_CGATE_JAVA'], javac=os.environ['CBUS_CGATE_JAVAC'],
            vendor=os.environ['CBUS_LOCAL_CGATE_VENDOR'], line_ending=line_ending)
        self.assertTrue(report['temporary_directory_removed'])
        self.assertEqual(report['java_exit_code'], 0)
        return report['rows']

    def test_fresh_original_manual_all_lf_byte_vectors(self):
        rows = [row for row in vectors()['manual_rows'] if row['line_ending'] == 'lf']
        observed = self.original(rows)
        for expected, actual in zip(rows, observed):
            with self.subTest(case=expected['id']):
                self.assertEqual(actual['status'], expected['status'])
                self.assertEqual(actual['output_hex'], expected['output_hex'])

    def test_fresh_original_windows_newline_manual_vectors(self):
        rows = [row for row in vectors()['manual_rows'] if row['line_ending'] == 'crlf']
        for expected, actual in zip(rows, self.original(rows, 'crlf')):
            with self.subTest(case=expected['id']):
                self.assertEqual(actual['status'], expected['status'])
                self.assertEqual(actual['output_hex'], expected['output_hex'])

    def test_fresh_original_both_transforms_and_full_pipeline(self):
        rows = vectors()['transform_rows']
        observed = self.original(rows)
        for expected, actual in zip(rows, observed):
            with self.subTest(case=expected['id']):
                self.assertEqual(actual['status'], expected['status'])
                self.assertEqual(actual['output_hex'], expected['output_hex'])


if __name__ == '__main__':
    unittest.main()
