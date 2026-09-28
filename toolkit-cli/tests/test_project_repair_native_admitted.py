"""Fresh native load boundary for newly admitted project-repair XML cases.

The captured oracle documents are small bare-Project fragments. Current-format
compositions use only generated fixture material and run in an owned service.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import unittest
from xml.etree import ElementTree as ET

from cbus_toolkit.cgate import CGateError
from cbus_toolkit.project_repair import ProjectRepairError, repair_project_xml, transform_project_repair_xml
from cbus_toolkit.repositories import parse_repository_list
from research.local_cgate import LocalCGate
from tests.test_project_repair_native import CapturedClient, expected_native_model, tree


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {
    'modern': ('project-repair-native-vectors.json', '4249fba21a15c4018b3c3c4d8b4c126697a9c990382c3bf23cec0cc51b3c98da'),
    'encoding': ('project-repair-encoding-vectors.json', 'd9512bfdf248f203f7b2e5558eb736eeedd00b1ec208ec2c6230f29b3d533d3c'),
    'dtd': ('project-repair-dtd-vectors.json', '35e2c58d4f08ec2306b914210fa3603407f971daa76d1edbe000f21e0f48c4c7'),
    'xml11': ('project-repair-xml11-vectors.json', 'ac0ce71275e85dec2b6f14a075d1e25b3b4142971e91239ad261f1918bcfe75f'),
}
JAVA_SHA256 = '94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4'
JAVAC_SHA256 = '98359a0227aa21aa777b5e12214a8224df9f193fd46540b6413613e7213883f5'
PROBE_SOURCE_SHA256 = '178ef74faf32dfc424b9cb5a349a60f2fd58a21daf27aea8c17a7090592d2981'
ORIGINAL_HARNESS_SHA256 = 'ae9fe24aeda28c907f859fa630e29b975a957f8946164c68126cd8751814b363'
LOCAL_HARNESS_SHA256 = '3df3f50db74bc1321b7d8b173927d88f50082df4bc67042b0bb2446e5f99e111'
PROBE_CLASS_SHA256 = '27ad39b4faf7df3eb359bb6f7b7fbf4cc161707477e8ce6cb11a769b25c6d0db'


def digest(data):
    return sha256(data).hexdigest()


def fixture(kind):
    filename, expected = FIXTURES[kind]
    raw = (ROOT / 'research/fixtures' / filename).read_bytes()
    assert digest(raw) == expected, filename
    return json.loads(raw)['rows']


def captured(kind, case_id):
    row, = [row for row in fixture(kind) if row['id'] == case_id]
    return row


def candidate(row):
    source = bytes.fromhex(row['input_hex'])
    return (repair_project_xml(source).repaired_xml if row['operation'] == 'full'
            else transform_project_repair_xml(source, stage=row['operation']))


def prepared_cases():
    modern = captured('modern', 'RPDUP')
    base = repair_project_xml(modern['source_utf8'].encode('utf-8')).repaired_xml
    assert b'<DBVersion>2.3</DBVersion>' in base
    assert base.count(b'<TagName>First</TagName>') == 1
    assert base.count(b'RPDUP') == 2

    encoding = captured('encoding', 'windows1252-utf8-full')
    encoding_source = bytes.fromhex(encoding['input_hex'])
    assert b'encoding="windows-1252"' in encoding_source
    assert b'<TagName>\xc3\xa9</TagName>' in encoding_source
    dtd = captured('dtd', 'one-text-repair')
    dtd_source = bytes.fromhex(dtd['input_hex'])
    assert b'<!DOCTYPE Project [<!ENTITY x "safe">]>' in dtd_source
    assert b'<TagName>&x;</TagName>' in dtd_source
    xml11 = captured('xml11', 'c1-text-full')
    xml11_source = bytes.fromhex(xml11['input_hex'])
    assert b'version="1.1"' in xml11_source
    assert b'<TagName>A&#x7f;B</TagName>' in xml11_source

    return [
        {'name': 'RPENC', 'source_case': encoding['id'], 'stage': 'full',
         'expected_group': '\u00c3\u00a9',
         'source': base.replace(b'RPDUP', b'RPENC')
                       .replace(b'encoding="utf-8"', b'encoding="windows-1252"', 1)
                       .replace(b'<TagName>First</TagName>', b'<TagName>\xc3\xa9</TagName>')},
        {'name': 'RPDTD', 'source_case': dtd['id'], 'stage': 'repair',
         'expected_group': 'safe',
         'source': base.replace(b'RPDUP', b'RPDTD')
                       .replace(b'?>', b'?><!DOCTYPE Installation [<!ENTITY x "safe">]>', 1)
                       .replace(b'<TagName>First</TagName>', b'<TagName>&x;</TagName>')},
        {'name': 'RPXML11', 'source_case': xml11['id'], 'stage': 'full',
         'expected_group': 'A\x7fB',
         'source': base.replace(b'RPDUP', b'RPXML11')
                       .replace(b'version="1.0"', b'version="1.1"', 1)
                       .replace(b'<TagName>First</TagName>', b'<TagName>A&#x7f;B</TagName>')},
    ]


def prepared_rejected_case():
    modern = captured('modern', 'RPDUP')
    base = repair_project_xml(modern['source_utf8'].encode('utf-8')).repaired_xml
    row = captured('xml11', 'c0-text-hex-repair')
    source = bytes.fromhex(row['input_hex'])
    assert b'version="1.1"' in source
    assert b'<TagName>A&#x1f;B</TagName>' in source
    return {
        'name': 'RPC0', 'source_case': row['id'], 'stage': 'repair',
        'source': base.replace(b'RPDUP', b'RPC0')
                      .replace(b'version="1.0"', b'version="1.1"', 1)
                      .replace(b'<TagName>First</TagName>', b'<TagName>A&#x1f;B</TagName>'),
    }


def fragments():
    return [
        ('FRENC', captured('encoding', 'windows1252-utf8-full')),
        ('FRDTD', captured('dtd', 'one-text-repair')),
        ('FRXML11', captured('xml11', 'c1-text-full')),
    ]


class NativeAdmittedRepairTests(unittest.TestCase):
    def test_exact_captured_fragments_have_legacy_version_and_no_project_address(self):
        for name, row in fragments():
            with self.subTest(case=row['id']):
                output = candidate(row)
                self.assertEqual(row['status'], 'OK')
                self.assertEqual(output, bytes.fromhex(row['output_hex']))
                root = ET.fromstring(output)
                self.assertEqual(root.findtext('DBVersion'), '2.2')
                self.assertIsNone(root.find('Project/Address'))
                self.assertRegex(name, r'^[A-Z][A-Z0-9_]{0,7}$')

        full_dtd = captured('dtd', 'one-text-full')
        self.assertEqual(full_dtd['status'], 'ERROR')
        with self.assertRaises(ProjectRepairError) as caught:
            repair_project_xml(bytes.fromhex(full_dtd['input_hex']))
        self.assertEqual(caught.exception.stage, 'repair')

    def test_current_format_compositions_preserve_captured_features(self):
        expected = {
            'RPENC': ('5c35637e4653aa192056623f7a84cc0f4c6f8df9a699b7ab7da3d64e5b42c577', '6037350ada2d01e98a8317ffa54b9b65738436162a0d60d780f74c4ddcd51f08'),
            'RPDTD': ('0f1f16431d47beffbfefee4f4fde9c1acca39fb3b8a4dd4a33a5141812f21680', '97d13570126e44416f31d7ad38206d5bd4809b559543f251860ccf32ffdfbd1d'),
            'RPXML11': ('9b118d14900725d63389b7c73053df9793962fc0ccdb622419060882e225ef49', '23a9ff065e90b11f4beb9629d97f89f58c8e479d7452f0d4851e4c2d1939a040'),
        }
        for case in prepared_cases():
            with self.subTest(case=case['name']):
                output = (repair_project_xml(case['source']).repaired_xml if case['stage'] == 'full'
                          else transform_project_repair_xml(case['source'], stage='repair'))
                self.assertEqual((digest(case['source']), digest(output)), expected[case['name']])
                root = ET.fromstring(output)
                self.assertEqual(root.findtext('DBVersion'), '2.3')
                self.assertEqual(root.findtext('Project/Address'), case['name'])
                self.assertEqual(root.findtext('Project/Network/Application/Group/TagName'), case['expected_group'])
                self.assertNotIn(b'<!DOCTYPE', output)

        rejected = prepared_rejected_case()
        output = transform_project_repair_xml(rejected['source'], stage='repair')
        self.assertEqual(digest(rejected['source']), '03b89f5a0b3bd7a91541f64bda9b061ae66e1e4ddeee35a40055c41e592dac88')
        self.assertEqual(digest(output), '46a609a9eddb712662e03da6147d5d5e72636ccd876c6f30af84f6071d9fb156')
        self.assertIn(b'<DBVersion>2.3</DBVersion>', output)
        self.assertIn(b'<TagName>A&#31;B</TagName>', output)
        with self.assertRaises(ET.ParseError):
            ET.fromstring(output)
        with self.assertRaises(ProjectRepairError) as caught:
            repair_project_xml(rejected['source'])
        self.assertEqual(caught.exception.stage, 'tidy')


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_JAVA', 'CBUS_CGATE_JAVAC', 'CBUS_LOCAL_CGATE_VENDOR')),
                     'Select pinned Java11 and original C-Gate for fresh isolated load')
class NativeAdmittedRepairIntegrationTests(unittest.TestCase):
    def test_original_transform_and_owned_project_load_readback(self):
        from research.project_repair_original import run_original

        java = Path(os.environ['CBUS_CGATE_JAVA'])
        javac = Path(os.environ['CBUS_CGATE_JAVAC'])
        vendor = Path(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        self.assertEqual(digest(java.read_bytes()), JAVA_SHA256)
        self.assertEqual(digest(javac.read_bytes()), JAVAC_SHA256)
        self.assertEqual(digest((ROOT / 'research/RepairStageProbe.java').read_bytes()), PROBE_SOURCE_SHA256)
        self.assertEqual(digest((ROOT / 'research/project_repair_original.py').read_bytes()), ORIGINAL_HARNESS_SHA256)
        self.assertEqual(digest((ROOT / 'research/local_cgate.py').read_bytes()), LOCAL_HARNESS_SHA256)
        cases = prepared_cases()
        rejected = prepared_rejected_case()
        original = run_original([{'operation': case['stage'], 'input_hex': case['source'].hex()}
                                 for case in [*cases, rejected]],
                                java=java, javac=javac, vendor=vendor)
        self.assertEqual(original['java_exit_code'], 0)
        self.assertTrue(original['temporary_directory_removed'])
        self.assertEqual(original['class_sha256'], PROBE_CLASS_SHA256)
        for case, oracle in zip([*cases, rejected], original['rows'], strict=True):
            with self.subTest(case=case['name']):
                self.assertEqual(oracle['status'], 'OK')
                case['output'] = (repair_project_xml(case['source']).repaired_xml if case['stage'] == 'full'
                                  else transform_project_repair_xml(case['source'], stage='repair'))
                self.assertEqual(case['output'], bytes.fromhex(oracle['output_hex']))

        service = LocalCGate(vendor, java=java)
        projects = service.work / 'admitted-projects'
        try:
            projects.mkdir()
            config = service.work / 'config/C-GateConfig.txt'
            config.write_text(config.read_text() + f'project.default.dir={projects}\n')
            (service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        except BaseException as error:
            service._cleanup_preserving(error)
            raise
        results = []
        with service:
            outputs = {case['name']: case['output'] for case in cases}
            outputs[rejected['name']] = rejected['output']
            outputs.update((name, candidate(row)) for name, row in fragments())
            for name, output in outputs.items():
                (projects / (name + '.xml')).write_bytes(output)
            with CapturedClient('127.0.0.1', service.port, timeout=10) as client:
                def request(command, expected):
                    allowed = command in ('REPOSITORY LIST', 'PROJECT LIST') or re.fullmatch(
                        r'REPOSITORY USE [1-9][0-9]{0,3}|PROJECT (?:LOAD|CLOSE) [A-Z][A-Z0-9_]{0,7}|DBGETXML //[A-Z][A-Z0-9_]{0,7}', command)
                    self.assertTrue(allowed, command)
                    start = len(client.wire_lines)
                    try:
                        reply = client.command(command)
                    except CGateError as error:
                        reply = error.response
                    lines = client.wire_lines[start:]
                    self.assertEqual(reply.code, expected, (command, lines))
                    results.append({'command': command, 'code': reply.code, 'response': lines})
                    return reply

                listing = parse_repository_list(request('REPOSITORY LIST', 123))
                file_repo, = [repo for repo in listing.repositories if repo.type == 'file']
                self.assertEqual(Path(file_repo.path).resolve(), projects.resolve())
                self.assertEqual(request('PROJECT LIST', 124).lines, ('124 no projects found',))
                request(f'REPOSITORY USE {file_repo.index}', 200)
                for case in cases:
                    name = case['name']
                    request(f'PROJECT LOAD {name}', 200)
                    reply = request(f'DBGETXML //{name}', 344)
                    self.assertEqual(reply.lines[0], '343-Begin XML snippet')
                    self.assertEqual(reply.lines[-1], '344 End XML snippet')
                    self.assertTrue(all(line.startswith('347-') for line in reply.lines[1:-1]))
                    readback = '\n'.join(line[4:] for line in reply.lines[1:-1]).encode('utf-8')
                    expected, changes = expected_native_model(case['output'])
                    self.assertEqual(len(changes), 1)
                    self.assertEqual(tree(readback, omit_oids=True), tree(expected))
                    root = ET.fromstring(readback)
                    self.assertEqual(root.findtext('Project/Network/Application/Group/TagName'), case['expected_group'])
                    oids = [oid.text for oid in root.findall('.//OID')]
                    self.assertEqual(len(oids), 61)
                    self.assertEqual(len(oids), len(set(oids)))
                    case['readback_sha256'] = digest(readback)
                    case['native_oid_count'] = len(oids)
                    request(f'PROJECT CLOSE {name}', 200)
                    self.assertEqual(request('PROJECT LIST', 124).lines, ('124 no projects found',))
                malformed = request(f"PROJECT LOAD {rejected['name']}", 408)
                self.assertIn('Character reference "&#31" is an invalid XML character', malformed.final)
                self.assertEqual(request('PROJECT LIST', 124).lines, ('124 no projects found',))
                for name, row in fragments():
                    legacy_reply = request(f'PROJECT LOAD {name}', 408)
                    self.assertIn('DBVersion is 2.2 and must be 2.3', legacy_reply.final)
                    self.assertIn('TRANSFORM PROJECT', legacy_reply.final)
                    self.assertEqual(request('PROJECT LIST', 124).lines, ('124 no projects found',))
                self.assertEqual({path.name for path in projects.iterdir()},
                                 {name + '.xml' for name in outputs})
                for name, output in outputs.items():
                    self.assertEqual((projects / (name + '.xml')).read_bytes(), output)
        self.assertTrue(service.report['listener_ownership_verified'])
        self.assertTrue(service.report['cleanup_complete'])
        self.assertFalse(service.work.exists())

        report_dir = os.environ.get('CBUS_PROJECT_REPAIR_ADMITTED_REPORT_DIR')
        if report_dir:
            path = Path(report_dir)
            path.mkdir(parents=True, exist_ok=True)
            summary = {
                'format': 'cbus-project-repair-admitted-native-run-v1',
                'original_transform': {key: original[key] for key in ('class_sha256', 'line_ending', 'stdout_sha256', 'stderr_sha256', 'java_exit_code', 'temporary_directory_removed')},
                'service': service.report,
                'composites': [{key: case[key] for key in ('name', 'source_case', 'stage', 'expected_group', 'readback_sha256', 'native_oid_count')}
                               | {'source_sha256': digest(case['source']), 'output_sha256': digest(case['output'])} for case in cases],
                'rejected_current_format': {
                    'name': rejected['name'], 'source_case': rejected['source_case'], 'stage': rejected['stage'],
                    'source_sha256': digest(rejected['source']), 'output_sha256': digest(rejected['output']),
                },
                'fragments': [{'name': name, 'source_case': row['id'], 'source_sha256': digest(bytes.fromhex(row['input_hex'])),
                               'output_sha256': digest(candidate(row))} for name, row in fragments()],
                'commands': results,
                'staged_bytes_unchanged': True,
                'physical_networks_opened': False,
                'native_repair_requested': False,
                'native_transform_requested': False,
            }
            (path / 'run.json').write_text(json.dumps(summary, indent=2, ensure_ascii=True) + '\n')
