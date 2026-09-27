"""Read-only project CSV through each Rust server, on synthetic loopback data."""
import os
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.programming import xml_text
from research.cgate_dbsetxml_unit_differential import owned_server
from tests import test_toolkit_database_csv_project_export as project_tests


@pytest.mark.parametrize('product,variable', [
    ('cgate-mock', 'CBUS_CGATE_MOCK_BIN'), ('cmqttd', 'CBUS_CMQTTD_BIN')])
@pytest.mark.parametrize('selection', ['project', 'network', 'unit'])
def test_csv_snapshot_through_rust_server(product, variable, selection, tmp_path):
    configured = os.environ.get(variable)
    if not configured:
        pytest.skip(f'Set {variable} to an explicitly built Rust binary')
    binary = Path(configured)
    assert binary.is_file() and os.access(binary, os.X_OK)
    source_networks = ET.fromstring(project_tests.project_xml(oids=True)).findall('Project/Network')
    with owned_server(product, binary) as port:
        with CGateClient('127.0.0.1', port, timeout=5) as client:
            assert client.command('PROJECT NEW CSVTEST').code == 200
            for source in source_networks:
                address = source.findtext('Address')
                assert client.command(f'DBCREATENET {address} Owned{address} Cni 127.0.0.1:1').code == 200
                network = ET.fromstring(xml_text(client.command(f'DBGETXML //CSVTEST/{address}')))
                for child in source:
                    if child.tag not in ('Application', 'Unit'):
                        continue
                    # Fixture OIDs are synthetic and made unique across networks.
                    for oid in child.iter('OID'):
                        oid.text = str(uuid.uuid5(uuid.NAMESPACE_URL, f'csv-project/{address}/{oid.text}'))
                    network.append(child)
                reply = client.command_document(f'DBSETXML //CSVTEST/{address}',
                                                ET.tostring(network, encoding='unicode'))
                assert reply.code == 301
            before = xml_text(client.command('DBGETXML //CSVTEST'))
        # Native snapshots may normalize network order; use that actual snapshot
        # to require coverage of both networks without claiming Toolkit order.
        networks = ET.fromstring(before).findall('Project/Network')
        expected_paths = [f'//CSVTEST/{network.findtext("Address")}/p/{unit.findtext("Address")}'
                          for network in networks for unit in network.findall('Unit')]
        expected_paths = expected_paths if selection == 'project' else ['//CSVTEST/254/p/4']
        flags = (['--project', '//CSVTEST'] if selection == 'project' else
                 ['--network', '//CSVTEST/254'] if selection == 'network' else
                 ['//CSVTEST/254/p/4'])
        output = tmp_path / 'whole.csv'
        code, result = project_tests.invoke(['cgate', '--host', '127.0.0.1', '--port', port,
            'database-csv', *flags, '--columns', 'address', 'tag_name',
            '--output', output], offline=False)
        assert code == 0, result
        if selection == 'unit':
            assert result['projection']['unit_path'] == expected_paths[0]
        else:
            assert result['projection']['unit_paths'] == expected_paths
            assert result['projection']['original_manager_enumeration_verified'] is False
        assert result['native_database_mutated'] is False
        assert result['report']['unit_count'] == len(expected_paths)
        assert b'4,First,\r\n' in output.read_bytes()
        if selection == 'project':
            assert set(expected_paths) == {'//CSVTEST/254/p/4', '//CSVTEST/1/p/4'}
            assert b'4,"Second, ""room""",\r\n' in output.read_bytes()
        with CGateClient('127.0.0.1', port, timeout=5) as client:
            assert xml_text(client.command('DBGETXML //CSVTEST')) == before
