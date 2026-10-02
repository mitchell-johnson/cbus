"""Public NeoPro CSV on explicitly owned Rust servers, with literal wire proof.

The input, units and applications are synthetic. Project restore provisions a
database only; neither report generation nor its failed reads may touch PCI.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
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
from test_toolkit_database_csv_neopro import COLUMNS, DATA, tree


BACKENDS = [('cgate-mock', 'CBUS_CGATE_MOCK_BIN'), ('cmqttd', 'CBUS_CMQTTD_BIN')]


def selected_binary(variable):
    supplied = os.environ.get(variable)
    if not supplied:
        pytest.skip(f'Select {variable} for the owned NeoPro CSV journey')
    binary = Path(supplied).resolve()
    assert binary.is_file() and os.access(binary, os.X_OK), variable
    return binary


def seed(owner, work, trap):
    root = tree()
    ET.SubElement(root, 'DBVersion').text = '2.3'
    project = root.find('Project')
    ET.SubElement(project, 'OID').text = str(uuid.uuid4())
    ET.SubElement(project, 'TagName').text = 'NEOCSV'
    for network in project.findall('Network'):
        ET.SubElement(network, 'OID').text = str(uuid.uuid4())
        ET.SubElement(network, 'TagName').text = 'Synthetic network ' + network.findtext('Address')
        interface = ET.SubElement(network, 'Interface')
        ET.SubElement(interface, 'OID').text = str(uuid.uuid4())
        ET.SubElement(interface, 'InterfaceType').text = 'cni'
        ET.SubElement(interface, 'InterfaceAddress').text = trap
        for app in network.findall('Application'):
            ET.SubElement(app, 'OID').text = str(uuid.uuid4())
    source = work/'NEOCSV-synthetic.xml'
    source.write_bytes(ET.tostring(root, encoding='utf-8'))
    source.chmod(0o600)
    for command in ('FILE MKDIR Projects', 'FILE MKDIR Projects/archived'):
        assert owner.command(command).code == 200
    result = upload(prepare_upload('Projects/archived/NEOCSV.xml', source), owner)
    assert result['upload_completed'] and not result['project_save_requested']
    for command in ('PROJECT RESTORE NEOCSV NEOCSV.xml', 'PROJECT USE NEOCSV', 'PROJECT SAVE NEOCSV'):
        assert owner.command(command).code == 200
    return hashlib.sha256(source.read_bytes()).hexdigest()


def snapshot(owner):
    return xml_text(NativeDatabase(owner).get('//NEOCSV', xml=True))


@contextmanager
def journey(backend, variable, tmp_path):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'owned')
    evidence = {'format':'cbus-neopro-csv-owned-v1', 'backend':backend,
                'original_execution':False, 'physical_acceptance':False,
                'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
                'fixture_sha256':DATA['fixture']['xml_sha256'], 'calls':[], 'processes':[]}
    relay = None
    try:
        with no_contact_trap() as trap, owned_backend(backend, binary, work) as (endpoint, record):
            evidence['processes'].append(record)
            with CGateClient(*endpoint, timeout=15) as owner, RecordedGate(endpoint) as relay:
                evidence['provisioned_xml_sha256'] = seed(owner, work, trap)
                yield owner, relay, evidence, endpoint
        evidence['closed_graph_trap_contacts'] = 0
    finally:
        if relay is not None:
            evidence['wires'] = relay.evidence()
        associated_evidence(tmp_path/'neopro-csv-evidence.json', evidence)


def read_only(call):
    assert call['commands'] == ['DBGETXML //NEOCSV']
    assert call['statuses'] == [344]


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
def test_public_neopro_csv_project_network_selection_on_owned_backend(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, _endpoint):
        before = snapshot(owner)
        cases = [
            ('project', ['--project','//NEOCSV'], DATA['fixture']['csv_rows']),
            ('network', ['--network','//NEOCSV/254'], DATA['fixture']['csv_rows'][:-1]),
            ('selection', ['--units','//NEOCSV/11/p/8','//NEOCSV/254/p/3'],
             [DATA['fixture']['csv_rows'][0], DATA['fixture']['csv_rows'][4], DATA['fixture']['csv_rows'][1]]),
        ]
        for name, flags, rows in cases:
            output=tmp_path/(name+'.csv')
            result, call=cli(relay, evidence['calls'], 'database-csv', *flags,
                            '--columns', *COLUMNS, '--output', output)
            read_only(call)
            assert result['native_database_mutated'] is False
            assert result['report']['unit_count']==len(rows)-1
            assert output.read_bytes()==('\r\n'.join(rows)+'\r\n\r\n').encode()
            assert snapshot(owner)==before
        # Existing outputs refuse before opening the server connection.
        original=(tmp_path/'project.csv').read_bytes()
        _result, call=cli(relay, evidence['calls'], 'database-csv', '--project','//NEOCSV',
                         '--output', tmp_path/'project.csv', expected=1, connections=0)
        assert call['commands']==[]
        assert (tmp_path/'project.csv').read_bytes()==original
        assert snapshot(owner)==before


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
def test_public_neopro_csv_late_unsupported_profile_refuses_atomically(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, _endpoint):
        assert NativeDatabase(owner).set('//NEOCSV/11/p/8/FirmwareVersion','2.5.01').code==200
        before=snapshot(owner)
        output=tmp_path/'never.csv'
        _result, call=cli(relay, evidence['calls'], 'database-csv', '--project','//NEOCSV',
                         '--columns', *COLUMNS, '--output', output, expected=1)
        read_only(call)
        assert not output.exists()
        assert snapshot(owner)==before


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=['mock','daemon'])
def test_public_neopro_csv_lost_snapshot_terminal_is_not_retried(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, _relay, evidence, endpoint):
        before=snapshot(owner)
        with FaultGate(endpoint, 'DBGETXML','drop') as fault:
            output=tmp_path/'lost.csv'
            _result, call=cli(fault, evidence['calls'], 'database-csv', '--project','//NEOCSV',
                             '--output', output, expected=1, complete=False)
            assert call['commands']==['DBGETXML //NEOCSV']
            assert fault.matches==1
            assert len(fault.rows)==1
            assert bytes.fromhex(fault.rows[0]['lost_backend_terminal_hex']).decode().endswith('344 End XML snippet\r\n')
            assert not output.exists()
        evidence['lost_snapshot_wires']=fault.evidence()
        assert graph(snapshot(owner))==graph(before)
