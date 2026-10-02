"""Literal final CSV profiles through subprocesses on two owned Rust servers."""
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
from test_toolkit_database_csv_last_profiles import (
    COLUMNS, DATA, application, case, parameter, tree, unit,
)


BACKENDS = [('cgate-mock', 'CBUS_CGATE_MOCK_BIN'), ('cmqttd', 'CBUS_CMQTTD_BIN')]


def selected_binary(variable):
    supplied = os.environ.get(variable)
    if not supplied:
        pytest.skip(f'Select {variable} for the owned final CSV journey')
    binary = Path(supplied).resolve()
    assert binary.is_file() and os.access(binary, os.X_OK)
    return binary


def seed(owner, work, trap):
    root = tree()
    for network in root.find('Project').findall('Network'):
        # Use the closed nested native Interface. Direct fixture aliases must
        # never retain their original dummy endpoint alongside the trap.
        for name in ('NetworkInterfaceType', 'InterfaceType', 'InterfaceAddress'):
            for field in network.findall(name):
                network.remove(field)
        interface = ET.SubElement(network, 'Interface')
        ET.SubElement(interface, 'OID').text = str(uuid.uuid4())
        ET.SubElement(interface, 'InterfaceType').text = 'cni'
        ET.SubElement(interface, 'InterfaceAddress').text = trap
        # Project/network selection must sort numerical addresses even when
        # native storage order is the reverse of the independent literal rows.
        units = network.findall('Unit')
        for node in units:
            network.remove(node)
        network.extend(reversed(units))
    source = work / 'LASTCSV-synthetic.xml'
    source.write_bytes(ET.tostring(root, encoding='utf-8'))
    source.chmod(0o600)
    for command in ('FILE MKDIR Projects', 'FILE MKDIR Projects/archived'):
        assert owner.command(command).code == 200
    result = upload(prepare_upload('Projects/archived/LASTCSV.xml', source), owner)
    assert result['upload_completed'] and not result['project_save_requested']
    for command in ('PROJECT RESTORE LASTCSV LASTCSV.xml',
                    'PROJECT USE LASTCSV', 'PROJECT SAVE LASTCSV'):
        assert owner.command(command).code == 200
    return hashlib.sha256(source.read_bytes()).hexdigest()


def snapshot(owner):
    return xml_text(NativeDatabase(owner).get('//LASTCSV', xml=True))


@contextmanager
def journey(backend, variable, tmp_path):
    binary = selected_binary(variable)
    work = associated_work(tmp_path, 'owned')
    evidence = {
        'format': 'cbus-csv-last-profiles-owned-v1', 'backend': backend,
        'original_execution': False, 'physical_acceptance': False,
        'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
        'fixture_sha256': hashlib.sha256(DATA['fixture']['xml'].encode()).hexdigest(),
        'literal_csv_sha256': DATA['fixture']['csv_sha256'], 'calls': [], 'processes': [],
    }
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
        associated_evidence(tmp_path / 'csv-last-profiles-evidence.json', evidence)


def read_only(call):
    assert call['commands'] == ['DBGETXML //LASTCSV']
    assert call['statuses'] == [344]
    assert not call['documents']


def literal_bytes(rows):
    # All rows are authored in the source-derived vector, never obtained from
    # project_native_xml_unit or another production report producer.
    return ('\r\n'.join(rows) + '\r\n\r\n').encode('utf-8')


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock', 'daemon'))
def test_public_csv_last_profiles_all_literals_and_ordered_selection(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, _endpoint):
        before = snapshot(owner)
        rows, units = DATA['fixture']['rows'], DATA['fixture']['units']
        assert len(units) == 62
        assert hashlib.sha256(literal_bytes(rows)).hexdigest() == DATA['fixture']['csv_sha256']
        cases = [('project', ['--project', '//LASTCSV'], rows),
                 ('network', ['--network', '//LASTCSV/254'], rows),
                 ('ordered', ['--units', units[-1]['path'], units[0]['path'], units[31]['path']],
                  [rows[0], units[-1]['row'], units[0]['row'], units[31]['row']])]
        cases.extend(('unit-' + str(index), [row['path']], [rows[0], row['row']])
                     for index, row in enumerate(units))
        for name, flags, expected in cases:
            output = tmp_path / (name + '.csv')
            result, call = cli(relay, evidence['calls'], 'database-csv', *flags,
                               '--columns', *COLUMNS, '--output', output)
            read_only(call)
            assert not result['native_database_mutated']
            assert result['report']['unit_count'] == len(expected) - 1
            payload = output.read_bytes()
            assert payload == literal_bytes(expected)
            if name in ('project', 'network'):
                assert hashlib.sha256(payload).hexdigest() == DATA['fixture']['csv_sha256']
            assert graph(snapshot(owner)) == graph(before)
        original = (tmp_path / 'project.csv').read_bytes()
        _result, call = cli(relay, evidence['calls'], 'database-csv', '--project', '//LASTCSV',
                            '--output', tmp_path / 'project.csv', expected=1, connections=0)
        assert not call['commands'] and (tmp_path / 'project.csv').read_bytes() == original
        assert graph(snapshot(owner)) == graph(before)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock', 'daemon'))
@pytest.mark.parametrize('fault', (
    'bad-profile', 'missing-application', 'missing-secondary-input-group',
    'missing-unused-temperature-group', 'bad-fan-route',
))
def test_public_csv_last_profiles_refusal_is_atomic(backend, variable, fault, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, relay, evidence, _endpoint):
        root = ET.fromstring(snapshot(owner))
        last = DATA['fixture']['units'][-1]
        target = unit(root, last['path'])
        path = last['path']
        if fault == 'bad-profile':
            target.find('UnitType').text = 'UNRECOVERED_LAST_CSV'
        elif fault == 'missing-application':
            parameter(target, 'Application').set('Value', '56 58')
        elif fault == 'bad-fan-route':
            parameter(target, 'OutputGroupSecondary').set('Value', '2 ' + '0 ' * 14 + '0')
        else:
            if fault == 'missing-secondary-input-group':
                app, address = 57, '8'
            else:
                app, address = 25, '255'
            owner_app = application(root, app)
            owner_app.remove(next(group for group in owner_app.findall('Group')
                                  if group.findtext('Address') == address))
            target = root.find('Project/Network')
            path = '//LASTCSV/254'
        response = owner.command_document('DBSETXML ' + path, ET.tostring(target, encoding='unicode'))
        assert response.code == 301
        before = snapshot(owner)
        output = tmp_path / 'never.csv'
        _result, call = cli(relay, evidence['calls'], 'database-csv', '--project', '//LASTCSV',
                            '--columns', *COLUMNS, '--output', output, expected=1)
        read_only(call)
        assert not output.exists() and graph(snapshot(owner)) == graph(before)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock', 'daemon'))
def test_public_csv_last_profiles_lost_snapshot_is_terminal_without_replay(backend, variable, tmp_path):
    with journey(backend, variable, tmp_path) as (owner, _relay, evidence, endpoint):
        before = snapshot(owner)
        with FaultGate(endpoint, 'DBGETXML', 'drop') as fault:
            output = tmp_path / 'lost.csv'
            _result, call = cli(fault, evidence['calls'], 'database-csv', '--project', '//LASTCSV',
                                '--columns', *COLUMNS, '--output', output, expected=1, complete=False)
            assert call['commands'] == ['DBGETXML //LASTCSV']
            assert call['statuses'] == [None]
            assert fault.matches == 1 and len(fault.rows) == 1
            lost = bytes.fromhex(fault.rows[0]['lost_backend_terminal_hex']).decode()
            assert lost.endswith('344 End XML snippet\r\n')
            assert not output.exists()
        evidence['lost_snapshot_wires'] = fault.evidence()
        assert graph(snapshot(owner)) == graph(before)
