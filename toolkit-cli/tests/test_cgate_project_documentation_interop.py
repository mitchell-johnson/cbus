"""Public read-only documentation journeys on owned Rust backends."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.file_transfer import prepare_upload, upload
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.programming import xml_text
from test_cgate_barcode_database_interop import FaultGate, cli, graph
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend,
)

VECTOR = Path(__file__).resolve().parents[2] / 'rust/testdata/vectors/project_documentation_remaining.json'
DATA = json.loads(VECTOR.read_text())
BACKENDS = [('cgate-mock', 'CBUS_CGATE_MOCK_BIN'), ('cmqttd', 'CBUS_CMQTTD_BIN')]


def element(parent, name, value):
    ET.SubElement(parent, name).text = str(value)


def synthetic_xml(trap):
    """Input construction only; every report expectation remains literal."""
    root = ET.Element('Installation')
    project = ET.SubElement(root, 'Project')
    element(project, 'Address', 'DOCREST')
    element(project, 'TagName', 'DOCREST')
    for address, name in [(254, 'Synthetic Local'), (1, 'Remote')]:
        network = ET.SubElement(project, 'Network')
        element(network, 'OID', uuid.uuid4())
        element(network, 'Address', address)
        element(network, 'NetworkNumber', address)
        element(network, 'TagName', name)
        interface = ET.SubElement(network, 'Interface')
        element(interface, 'OID', uuid.uuid4())
        element(interface, 'InterfaceType', 'cni')
        element(interface, 'InterfaceAddress', trap)
        if address == 1:
            continue
        for row in DATA['applications']:
            application = ET.SubElement(network, 'Application')
            for field, value in [('OID', uuid.uuid4()), ('Address', row['address']),
                                 ('TagName', row['name'])]:
                element(application, field, value)
            for item in row['groups']:
                group = ET.SubElement(application, 'Group')
                for field, value in [('OID', uuid.uuid4()), ('Address', item['address']),
                                     ('TagName', item['name'])]:
                    element(group, field, value)
                for action in item['levels']:
                    level = ET.SubElement(group, 'Level', Value=str(action['value']))
                    for field, value in [('OID', uuid.uuid4()), ('Address', action['address']),
                                         ('TagName', action['name'])]:
                        element(level, field, value)
        for index, case in enumerate(DATA['cases']):
            row = case['unit']
            unit = ET.SubElement(network, 'Unit')
            for field, value in [('OID', uuid.uuid4()), ('Address', index + 3),
                                 ('TagName', case['id']), ('UnitType', row['unit_type']),
                                 ('FirmwareVersion', row['firmware']), ('UnitName', row['unit_name']),
                                 ('SerialNumber', row['serial']), ('Description', row['description'])]:
                element(unit, field, value)
            for name, values in row['parameters'].items():
                ET.SubElement(unit, 'PP', Name=name,
                              Value=values if isinstance(values, str) else ' '.join(map(str, values)))
            for name, value in row['fields'].items():
                element(unit, name, value)
    return ET.tostring(root, encoding='utf-8')


def snapshot(owner):
    return xml_text(NativeDatabase(owner).get('//DOCREST', xml=True))


@contextmanager
def journey(backend, variable, tmp_path):
    supplied = os.environ.get(variable)
    if not supplied:
        pytest.skip('Select ' + variable + ' for owned project documentation')
    binary = Path(supplied).resolve()
    assert binary.is_file() and os.access(binary, os.X_OK)
    work = associated_work(tmp_path, 'owned')
    evidence = {'format': 'cbus-project-documentation-owned-v1', 'backend': backend,
                'original_execution': False, 'physical_acceptance': False,
                'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                'vector_sha256': hashlib.sha256(VECTOR.read_bytes()).hexdigest(),
                'calls': [], 'processes': []}
    relay = None
    try:
        with no_contact_trap() as trap, owned_backend(backend, binary, work) as (endpoint, record):
            evidence['processes'].append(record)
            source = work / 'DOCREST-invented.xml'
            source.write_bytes(synthetic_xml(trap)); source.chmod(0o600)
            evidence['provisioned_xml_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
            with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                for command in ('FILE MKDIR Projects', 'FILE MKDIR Projects/archived'):
                    assert owner.command(command).code == 200
                assert upload(prepare_upload('Projects/archived/DOCREST.xml', source), owner)['upload_completed']
                for command in ('PROJECT RESTORE DOCREST DOCREST.xml', 'PROJECT USE DOCREST',
                                'PROJECT SAVE DOCREST'):
                    assert owner.command(command).code == 200
                yield owner, relay, evidence, endpoint
        evidence['closed_graph_trap_contacts'] = 0
    finally:
        if relay is not None:
            evidence['wires'] = relay.evidence()
        associated_evidence(tmp_path / 'project-documentation-evidence.json', evidence)


def read_only(call):
    assert call['commands'] == ['DBGETXML //DOCREST']
    assert call['statuses'] == [344]


def literal_bodies(raw, result):
    assert raw.startswith(b'\xef\xbb\xbf<html>\r\n') and raw.endswith(b'</html>\r\n')
    assert b'\n' not in raw.replace(b'\r\n', b'')
    assert b'Generated on: 02 Oct 2026 12:00<br />\r\n' in raw
    for index, case in enumerate(DATA['cases']):
        assert ('\r\n'.join(case['body_lines']) + '\r\n').encode() in raw
        assert result['units'][index] == {
            'network': 254, 'unit': index + 3, 'unit_type': case['unit']['unit_type'],
            'documentor': 'T' + case['family'] + 'Documentor', 'status': 'recovered',
        }
    assert b'name="254_202_7_11">L11</a>' in raw
    assert result['sha256'] == hashlib.sha256(raw).hexdigest()
    assert not result['parity']['original_toolkit_executed']


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock', 'daemon'))
def test_public_database_document_snapshot_and_literal_bodies(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, _endpoint):
        before = snapshot(owner)
        for name, extra, networks in [('all', [], [1, 254]), ('local', ['--network', '254'], [254])]:
            output = tmp_path / (name + '.html')
            result, call = cli(relay, evidence['calls'], 'database-document', '--project', '//DOCREST',
                               '--generated-at', DATA['generated_at'], '--output', output, *extra)
            read_only(call)
            literal_bodies(output.read_bytes(), result)
            raw_snapshot = '\n'.join(line.split('347-', 1)[1] for line in call['reply_lines'][0]
                                     if line.startswith('347-')).encode()
            assert result['source_snapshot']['sha256'] == hashlib.sha256(raw_snapshot).hexdigest()
            assert result['source_snapshot']['requests'] == 1 and result['networks'] == networks
            assert result['output_complete'] and not result['native_database_mutated']
            assert not result['physical_programming_loaded'] and not result['network_open_requested']
            assert not result['project_save_requested']
            assert snapshot(owner) == before
        preserved = (tmp_path / 'all.html').read_bytes()
        _result, call = cli(relay, evidence['calls'], 'database-document', '--project', '//DOCREST',
                            '--output', tmp_path / 'all.html', expected=1, connections=0)
        assert not call['commands'] and (tmp_path / 'all.html').read_bytes() == preserved
        assert graph(snapshot(owner)) == graph(before)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock', 'daemon'))
def test_public_database_document_absent_network_is_atomic(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, _endpoint):
        before = snapshot(owner); output = tmp_path / 'never.html'
        result, call = cli(relay, evidence['calls'], 'database-document', '--project', '//DOCREST',
                           '--network', '2', '--output', output, expected=1)
        read_only(call)
        assert 'absent' in result['error'] and not output.exists()
        assert snapshot(owner) == before


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock', 'daemon'))
def test_public_database_document_lost_snapshot_has_no_output_or_retry(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, _relay, evidence, endpoint):
        before = snapshot(owner)
        with FaultGate(endpoint, 'DBGETXML', 'drop') as fault:
            output = tmp_path / 'lost.html'
            _result, call = cli(fault, evidence['calls'], 'database-document', '--project', '//DOCREST',
                                '--output', output, expected=1, complete=False)
            assert call['commands'] == ['DBGETXML //DOCREST']
            assert fault.matches == 1 and len(fault.rows) == 1
            assert bytes.fromhex(fault.rows[0]['lost_backend_terminal_hex']).decode().endswith(
                '344 End XML snippet\r\n')
            assert not output.exists()
        evidence['lost_snapshot_wires'] = fault.evidence()
        assert graph(snapshot(owner)) == graph(before)


def test_public_offline_native_document_uses_the_same_literal_bodies(tmp_path):
    source = tmp_path / 'saved.xml'
    source.write_bytes(synthetic_xml('127.0.0.1:1'))
    output = tmp_path / 'saved.html'
    args = [sys.executable, '-m', 'cbus_toolkit', 'project', 'document', str(source),
            '--native-xml', '--generated-at', DATA['generated_at'], '--output', str(output)]
    process = subprocess.run(args, capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, (process.stdout, process.stderr)
    literal_bodies(output.read_bytes(), json.loads(process.stdout))
