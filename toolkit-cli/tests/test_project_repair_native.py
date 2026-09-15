"""Load Python-repaired generated XML in an owned original C-Gate process.

The original REPAIR outputs are literal independent fixtures. These tests never
send REPAIR or TRANSFORM for the Python outputs and never adopt a running server.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch
from xml.dom import Node, minidom
from xml.etree import ElementTree as ET

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.project_repair import ProjectRepairError, repair_project_xml
from research.local_cgate import LocalCGate


ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'research/fixtures/project-repair-native-vectors.json'
FIXTURE_SHA256='4249fba21a15c4018b3c3c4d8b4c126697a9c990382c3bf23cec0cc51b3c98da'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def vectors():
    raw=FIXTURE.read_bytes()
    if sha(raw)!=FIXTURE_SHA256: raise AssertionError('Original native fixture hash differs')
    return json.loads(raw)['rows']


def tree(data, *, omit_oids=False):
    """Compare full known-fixture structure, excluding formatting whitespace.

    These generated inputs have no whitespace-only leaf values. Nonblank text,
    including its boundary spaces, is retained; comments/PI order is retained.
    """
    document=minidom.parseString(data)
    def convert(node):
        if node.nodeType in (Node.TEXT_NODE,Node.CDATA_SECTION_NODE):
            return ('text',node.data) if node.data.strip() else None
        if node.nodeType==Node.ELEMENT_NODE:
            if omit_oids and not node.namespaceURI and node.nodeName=='OID': return None
            attributes=tuple(sorted((a.name,a.value) for a in node.attributes.values()))
            return ('element',node.nodeName,attributes,
                    tuple(value for child in node.childNodes if (value:=convert(child)) is not None))
        if node.nodeType==Node.COMMENT_NODE: return ('comment',node.data)
        if node.nodeType==Node.PROCESSING_INSTRUCTION_NODE: return ('pi',node.target,node.data)
        return tuple(value for child in node.childNodes if (value:=convert(child)) is not None)
    try: return convert(document)
    finally: document.unlink()


def expected_native_model(data):
    """Only the literal observed group255 named-field permutation is allowed."""
    document=minidom.parseString(data); changes=[]
    try:
        for group in document.getElementsByTagName('Group'):
            elements=[child for child in group.childNodes if child.nodeType==Node.ELEMENT_NODE]
            addresses=[child for child in elements if child.nodeName=='Address']
            if len(addresses)==1 and addresses[0].firstChild.data=='255':
                assert [child.nodeName for child in elements]==['Address','TagName']
                tag=elements[1];group.removeChild(tag);group.insertBefore(tag,elements[0])
                changes.append({'group_address':'255','python':['Address','TagName'],
                                'native':['TagName','Address']})
        assert len(changes)==1
        return document.toxml(encoding='utf-8'),changes
    finally: document.unlink()


class CapturedClient(CGateClient):
    def __init__(self,*args,**kwargs):
        self.wire_lines=[]
        super().__init__(*args,**kwargs)
    def _readline(self,deadline):
        value=super()._readline(deadline); self.wire_lines.append(value); return value


def observe(row):
    """Test-only whole-child scope. Invalid portable input stops before creation."""
    source=row['source_utf8'].encode('utf-8')
    assert sha(source)==row['source_sha256']
    repaired=repair_project_xml(source)
    name=row['project_name']
    assert re.fullmatch('[A-Z][A-Z0-9_]{0,7}',name)
    parsed=ET.fromstring(repaired.repaired_xml)
    assert parsed.tag=='Installation'
    assert parsed.findtext('Project/Address')==name and parsed.findtext('Project/TagName')==name
    assert not parsed.findall('.//OID')
    service=LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
    evidence={'case':row['id'],'service':service.report,'commands':[],
              'source_sha256':sha(source),'python_output_sha256':sha(repaired.repaired_xml),
              'python_output_utf8':repaired.repaired_xml.decode('utf-8'),
              'physical_networks_opened':False,'shared_native_server_used':False,
              'native_repair_requested':False,'native_transform_requested':False,
              'passed':False}
    projects=service.work/'python repaired projects'
    try:
        projects.mkdir()
        config=service.work/'config/C-GateConfig.txt'
        config.write_text(config.read_text()+f'project.default.dir={projects}\n')
        (service.work/'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        with service:
            path=projects/(name+'.xml'); path.write_bytes(repaired.repaired_xml)
            with CapturedClient('127.0.0.1',service.port,timeout=10) as client:
                def request(command,expected):
                    allowed=(command in ('REPOSITORY LIST','PROJECT LIST') or
                             re.fullmatch(r'REPOSITORY USE [1-9][0-9]{0,3}',command) or
                             command in (f'PROJECT LOAD {name}',f'PROJECT CLOSE {name}',f'DBGETXML //{name}'))
                    assert allowed,command
                    first=len(client.wire_lines); sent=f'[{client._sequence+1}] {command}\r\n'
                    try: reply=client.command(command)
                    except CGateError as error: reply=error.response
                    evidence['commands'].append({'command':command,'request':sent,'response':client.wire_lines[first:],'code':reply.code})
                    assert reply.code==expected,(command,reply)
                    return reply
                # LIST is parsed using the accepted descriptor; selection stays
                # strictly inside this newly created disposable process.
                listing=request('REPOSITORY LIST',123)
                from cbus_toolkit.repositories import parse_repository_list
                repositories=parse_repository_list(listing)
                xml,=[item for item in repositories.repositories if item.type=='file']
                assert Path(xml.path).resolve()==projects.resolve()
                assert request('PROJECT LIST',124).lines==('124 no projects found',)
                request(f'REPOSITORY USE {xml.index}',200)
                checked=parse_repository_list(request('REPOSITORY LIST',123))
                assert checked.current_index==xml.index and checked.repositories[xml.index-1].path==str(projects)
                loaded=request(f'PROJECT LOAD {name}',row['original_load_code'])
                evidence['load_code']=loaded.code; evidence['load_response']=loaded.final
                if row['legacy']:
                    assert repaired.db_version=='2.2'
                    assert 'DBVersion is 2.2 and must be 2.3' in loaded.final
                    assert 'TRANSFORM PROJECT' in loaded.final
                    assert request('PROJECT LIST',124).lines==('124 no projects found',)
                    evidence['loadable']=False
                else:
                    assert repaired.db_version=='2.3' and loaded.code==200
                    reply=request(f'DBGETXML //{name}',344)
                    assert reply.lines[0]=='343-Begin XML snippet' and reply.lines[-1]=='344 End XML snippet'
                    assert all(line.startswith('347-') for line in reply.lines[1:-1])
                    xml_data='\n'.join(line[4:] for line in reply.lines[1:-1]).encode('utf-8')
                    actual=ET.fromstring(xml_data)
                    expected,order_changes=expected_native_model(repaired.repaired_xml)
                    assert tree(xml_data,omit_oids=True)==tree(expected)
                    oids=[node.text for node in actual.findall('.//OID')]
                    assert oids and len(oids)==len(set(oids))
                    assert all(re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',value or '') for value in oids)
                    original_oids=re.findall(r'<OID>([^<]+)</OID>',row['source_utf8'])
                    assert not set(oids).intersection(original_oids)
                    assert actual.findtext('Project/Address')==name
                    assert actual.findtext('Project/Network/Address')=='254'
                    app=actual.find('Project/Network/Application'); assert app.findtext('Address')=='56'
                    groups=[{'address':group.findtext('Address'),'name':group.findtext('TagName'),'attributes':group.attrib}
                            for group in app.findall('Group')]
                    assert groups==row['expected_groups']
                    evidence.update(loadable=True,regenerated_oid_count=len(oids),groups=groups,
                                    loaded_xml_sha256=sha(xml_data),loaded_xml_utf8=xml_data.decode('utf-8'),
                                    full_named_field_values_preserved=True,
                                    native_field_order_changes=order_changes,
                                    full_tree_matches_after_observed_field_order_normalization=True)
                    request(f'PROJECT CLOSE {name}',200)
                    assert request('PROJECT LIST',124).lines==('124 no projects found',)
                assert path.read_bytes()==repaired.repaired_xml
                assert list(projects.iterdir())==[path]
                evidence.update(staged_bytes_unchanged=True,no_native_backup_or_temporary_files=True)
            evidence['passed']=True
    except BaseException as first:
        # Preserve the original object while retaining available generated evidence.
        evidence['passed']=False
        evidence['error_type']=type(first).__name__
        try: first.project_repair_native_evidence=evidence
        except BaseException: pass
        if not service.closed: service._cleanup_preserving(first)
        folder=os.environ.get('CBUS_PROJECT_REPAIR_NATIVE_REPORT_DIR')
        if folder:
            try:
                path=Path(folder);path.mkdir(parents=True,exist_ok=True)
                (path/('failed-'+row['id']+'.json')).write_text(json.dumps(evidence,indent=2)+'\n')
            except BaseException as secondary:
                try: first.project_repair_report_error=secondary
                except BaseException: pass
        raise
    assert service.report['cleanup_complete'] and not service.work.exists()
    return evidence


class ProjectRepairNativeFixtureTests(unittest.TestCase):
    def test_pinned_original_outputs_match_python_for_all_four_repaired_cases(self):
        rows=vectors(); self.assertEqual(len(rows),5)
        for row in rows:
            with self.subTest(case=row['id']):
                source=row['source_utf8'].encode('utf-8')
                self.assertEqual(sha(source),row['source_sha256'])
                if row['invalid']: continue
                original=row['original_output_utf8'].encode('utf-8')
                self.assertEqual(sha(original),row['original_output_sha256'])
                value=repair_project_xml(source)
                self.assertEqual(tree(value.repaired_xml),tree(original))
                self.assertFalse(value.as_dict()['native_load_verified'])
                self.assertIsNone(value.as_dict()['native_loadable'])

    def test_unrepairable_source_rejected_before_any_native_service_or_socket(self):
        invalid,=[row for row in vectors() if row['invalid']]
        with patch(__name__+'.LocalCGate',side_effect=AssertionError('must not start native')) as factory, \
             patch('cbus_toolkit.cgate.socket.create_connection',side_effect=AssertionError('must not connect')):
            with self.assertRaises(ProjectRepairError) as caught: observe(invalid)
        self.assertEqual(caught.exception.stage,'repair')
        self.assertEqual(factory.call_count,0)


@unittest.skipUnless(os.environ.get('CBUS_CGATE_JAVA') and os.environ.get('CBUS_LOCAL_CGATE_VENDOR'),
                     'Select Java11/vendor for isolated original XML repository acceptance')
class NativePortableProjectRepairTests(unittest.TestCase):
    def persist(self,kind,rows):
        folder=os.environ.get('CBUS_PROJECT_REPAIR_NATIVE_REPORT_DIR')
        if folder:
            path=Path(folder);path.mkdir(parents=True,exist_ok=True)
            (path/(kind+'.json')).write_text(json.dumps({'passed':True,'cases':rows},indent=2)+'\n')

    def test_modern_python_outputs_load_full_readback_regenerated_oids_and_close(self):
        rows=[]
        for row in vectors():
            if row['invalid'] or row['legacy']: continue
            with self.subTest(case=row['id']): rows.append(observe(row))
        self.assertEqual(len(rows),3)
        self.assertTrue(all(row['loadable'] and row['service']['cleanup_complete'] for row in rows))
        self.persist('modern',rows)

    def test_legacy_python_output_requires_explicit_transform_without_repair_replay(self):
        row,=[row for row in vectors() if row['legacy']]
        result=observe(row)
        self.assertEqual(result['load_code'],408);self.assertFalse(result['loadable'])
        self.assertFalse(result['native_transform_requested']);self.assertFalse(result['native_repair_requested'])
        self.assertTrue(result['staged_bytes_unchanged']);self.assertTrue(result['service']['cleanup_complete'])
        self.persist('legacy',[result])
