"""Cold native load of every admitted synthetic database-CSV fixture.

Each committed synthetic fixture is wrapped with the Installation metadata a
C-Gate 3.4 file repository requires, cold-loaded by an owned loopback C-Gate,
read back with DBGETXML and projected again. The CSV from the native readback
must equal the CSV from the committed fixture byte for byte.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import unittest
from xml.etree import ElementTree as ET

from cbus_toolkit.cgate import CGateError
from cbus_toolkit.repositories import parse_repository_list
from cbus_toolkit.toolkit_database_csv import COLUMNS
from cbus_toolkit.toolkit_database_csv_native import project_native_xml_selection


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ('dimdn8f', 'din4-rel4-rel8', 'keygl5', 'manager-order', 'reldn8b',
            'reldn8sp', 'senpiria', 'registry-batch')
ADMITTED_TYPES = {'ANODN4', 'ANOMB8', 'DIMDN4', 'DIMDN4F', 'DIMDN8F', 'DIMDS8', 'DIMPR1',
                  'DIMPR2', 'DIMPR4', 'DSIMB8', 'KEYE3', 'KEYGL5', 'RELAY4', 'RELDB1',
                  'RELDC4', 'RELDN4', 'RELDN8', 'RELDN8B', 'RELDN8SP', 'RELMB8',
                  'SENPIRIA', 'SENPIRIB'}
JAR_SHA256 = '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630'


def digest(data):
    return sha256(data).hexdigest()


def fixture(name):
    return (ROOT / f'research/fixtures/toolkit-database-csv-{name}-synthetic.xml').read_text(
        encoding='utf-8')


def project_name(text):
    return ET.fromstring(text).findtext('Project/Address')


def native_document(text):
    """Add only the required Installation/Project/Network metadata."""
    root = ET.fromstring(text)
    for index, (tag, value) in enumerate((('DBVersion', '2.3'), ('Version', '1.0'),
                                          ('Modified', '2026-09-30T00:00:00.000+00:00'))):
        element = ET.Element(tag)
        element.text = value
        root.insert(index, element)
    project = root.find('Project')
    tag = ET.Element('TagName')
    tag.text = project.findtext('Address')
    project.insert(0, tag)
    for network in project.findall('Network'):
        tag = ET.Element('TagName')
        tag.text = 'Synthetic'
        network.insert(0, tag)
    detail = ET.SubElement(root, 'InstallationDetail')
    for name in ('SystemLocation', 'HardwarePlatform', 'Hostname', 'OSName', 'OSVersion',
                 'HardwareLocation', 'MaintenanceEmail'):
        ET.SubElement(detail, name).text = '[unknown]'
    ET.SubElement(ET.SubElement(detail, 'Installer'), 'Name').text = '[unknown]'
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            + ET.tostring(root, encoding='unicode')).encode('utf-8')


def project_csv(text):
    return project_native_xml_selection(text, project_path='//' + project_name(text),
                                        columns=COLUMNS).report.utf8_bytes


def unit_records(text):
    return sorted((unit.findtext('Address'), unit.findtext('UnitType'),
                   unit.findtext('FirmwareVersion'),
                   tuple(sorted((pp.get('Name'), pp.get('Value')) for pp in unit.findall('PP'))))
                  for unit in ET.fromstring(text).iter('Unit'))


class NativeBatchPreparationTests(unittest.TestCase):
    def test_fixtures_cover_every_admitted_native_type_and_wrapper_preserves_csv(self):
        types = set()
        for name in FIXTURES:
            with self.subTest(fixture=name):
                text = fixture(name)
                types |= {unit.findtext('UnitType') for unit in ET.fromstring(text).iter('Unit')}
                wrapped = native_document(text).decode('utf-8')
                self.assertEqual(project_csv(wrapped), project_csv(text))
                self.assertEqual(unit_records(wrapped), unit_records(text))
                self.assertIsNone(ET.fromstring(text).find('.//Interface'))
        self.assertEqual(types, ADMITTED_TYPES)

    def test_committed_native_receipt_binds_current_fixtures_and_csv(self):
        receipt = json.loads((ROOT / 'research/experiments/2026-09-30/'
                              'csv-native-batch-acceptance.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['native_cgate']['jar_sha256'], JAR_SHA256)
        self.assertFalse(receipt['physical_networks_opened'])
        self.assertFalse(receipt['original_toolkit_gui_executed'])
        self.assertEqual([row['fixture'] for row in receipt['fixtures']], list(FIXTURES))
        for row in receipt['fixtures']:
            with self.subTest(fixture=row['fixture']):
                text = fixture(row['fixture'])
                self.assertEqual(row['fixture_sha256'], digest(text.encode('utf-8')))
                self.assertEqual(row['loaded_document_sha256'], digest(native_document(text)))
                self.assertEqual(row['csv_sha256'], digest(project_csv(text)))
                self.assertTrue(row['readback_csv_equal'])


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_JAVA', 'CBUS_LOCAL_CGATE_VENDOR')),
                     'Select pinned Java11 and original C-Gate for the owned cold-load batch')
class NativeBatchColdLoadTests(unittest.TestCase):
    def test_owned_cgate_cold_loads_every_fixture_and_readback_csv_matches(self):
        from research.local_cgate import LocalCGate
        from tests.test_project_repair_native import CapturedClient

        vendor = Path(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        self.assertEqual(digest((vendor / 'cgate.jar').read_bytes()), JAR_SHA256)
        service = LocalCGate(vendor, java=os.environ['CBUS_CGATE_JAVA'])
        projects = service.work / 'csv-batch-projects'
        try:
            projects.mkdir()
            config = service.work / 'config/C-GateConfig.txt'
            config.write_text(config.read_text() + f'project.default.dir={projects}\n')
            (service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        except BaseException as error:
            service._cleanup_preserving(error)
            raise
        results, commands = [], []
        with service:
            with CapturedClient('127.0.0.1', service.port, timeout=20) as client:
                def request(command, expected):
                    self.assertTrue(command in ('REPOSITORY LIST', 'PROJECT LIST') or re.fullmatch(
                        r'REPOSITORY USE [1-9][0-9]{0,3}|PROJECT (?:LOAD|CLOSE) [A-Z][A-Z0-9_]{0,7}'
                        r'|DBGETXML //[A-Z][A-Z0-9_]{0,7}', command), command)
                    try:
                        reply = client.command(command)
                    except CGateError as error:
                        reply = error.response
                    self.assertEqual(reply.code, expected, (command, reply.lines))
                    commands.append({'command': command, 'code': reply.code})
                    return reply

                listing = parse_repository_list(request('REPOSITORY LIST', 123))
                file_repo, = [repo for repo in listing.repositories if repo.type == 'file']
                self.assertEqual(Path(file_repo.path).resolve(), projects.resolve())
                request(f'REPOSITORY USE {file_repo.index}', 200)
                for name in FIXTURES:
                    with self.subTest(fixture=name):
                        text = fixture(name)
                        project = project_name(text)
                        document = native_document(text)
                        path = projects / (project + '.xml')
                        path.write_bytes(document)
                        request(f'PROJECT LOAD {project}', 200)
                        reply = request(f'DBGETXML //{project}', 344)
                        self.assertEqual(reply.lines[0], '343-Begin XML snippet')
                        self.assertTrue(all(line.startswith('347-') for line in reply.lines[1:-1]))
                        readback = '\n'.join(line[4:] for line in reply.lines[1:-1])
                        expected = project_csv(text)
                        self.assertEqual(project_csv(readback), expected)
                        self.assertEqual(unit_records(readback), unit_records(text))
                        request(f'PROJECT CLOSE {project}', 200)
                        self.assertEqual(path.read_bytes(), document)
                        path.unlink()
                        results.append({
                            'fixture': name, 'project': project,
                            'fixture_sha256': digest(text.encode('utf-8')),
                            'loaded_document_sha256': digest(document),
                            'readback_sha256': digest(readback.encode('utf-8')),
                            'unit_types': sorted({record[1] for record in unit_records(text)}),
                            'csv_sha256': digest(expected), 'csv_bytes': len(expected),
                            'readback_csv_equal': True,
                        })
                self.assertEqual(request('PROJECT LIST', 124).lines, ('124 no projects found',))
        self.assertTrue(service.report['listener_ownership_verified'])
        self.assertTrue(service.report['cleanup_complete'])
        self.assertFalse(service.work.exists())

        report_dir = os.environ.get('CBUS_CSV_NATIVE_BATCH_REPORT_DIR')
        if report_dir:
            path = Path(report_dir)
            path.mkdir(parents=True, exist_ok=True)
            (path / 'run.json').write_text(json.dumps({
                'format': 'cbus-toolkit-csv-native-batch-run-v1',
                'service': service.report, 'fixtures': results, 'commands': commands,
                'physical_networks_opened': False, 'original_toolkit_gui_executed': False,
            }, indent=1, ensure_ascii=True) + '\n')


if __name__ == '__main__':
    unittest.main()
