"""Read-only public wireless reports against both owned Rust backends."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

import test_cgate_project_documentation_interop as helpers
from test_cgate_barcode_database_interop import cli
from cbus_toolkit.project_documentation import select_documentor

VECTOR = Path(__file__).resolve().parents[1] / 'research/fixtures/project-documentor-wireless.json'


def input_xml(vector, trap):
    root = ET.fromstring(vector['native_xml'])
    project = root.find('Project')
    project.find('Address').text = 'DOCREST'
    for network in project.findall('Network'):
        interface = network.find('Interface')
        if interface is None:
            interface = ET.SubElement(network, 'Interface')
            ET.SubElement(interface, 'InterfaceType')
            ET.SubElement(interface, 'InterfaceAddress')
        interface.find('InterfaceType').text = 'cni'
        interface.find('InterfaceAddress').text = trap
    return ET.tostring(root, encoding='utf-8')


@pytest.mark.parametrize('backend,variable', helpers.BACKENDS, ids=('mock', 'daemon'))
def test_public_database_document_wireless_families_preserves_snapshot(backend, variable, tmp_path):
    vector = json.loads(VECTOR.read_text())
    with patch.object(helpers, 'VECTOR', VECTOR), patch.object(
            helpers, 'synthetic_xml', lambda trap: input_xml(vector, trap)):
        with helpers.journey(backend, variable, tmp_path) as (owner, relay, evidence, _endpoint):
            evidence['format'] = 'cbus-project-documentation-wireless-owned-v1'
            before = helpers.snapshot(owner)
            output = tmp_path / 'wireless.html'
            result, call = cli(relay, evidence['calls'], 'database-document', '--project', '//DOCREST',
                               '--generated-at', '2026-10-03T12:00:00', '--output', output)
            helpers.read_only(call)
            raw = output.read_bytes()
            assert raw.startswith(b'\xef\xbb\xbf<html>\r\n') and raw.endswith(b'</html>\r\n')
            assert b'\n' not in raw.replace(b'\r\n', b'')
            assert b'Generated on: 03 Oct 2026 12:00<br />\r\n' in raw
            assert result['networks'] == [2, 3, 4, 254]
            rows = ET.fromstring(vector['native_xml']).find('Project/Network').findall('Unit')
            for index, row in enumerate(rows):
                address = int(row.findtext('Address'))
                assert ('\r\n'.join(vector['body_lines'][str(address)]) + '\r\n').encode() in raw
                assert result['units'][index] == {
                    'network': 254, 'unit': address, 'unit_type': row.findtext('UnitType'),
                    'documentor': 'T' + select_documentor(row.findtext('UnitType'), row.findtext('FirmwareVersion'))
                    + 'Documentor', 'status': 'recovered'}
            for description in (vector['group_usage']['input_56_8'],
                                vector['selector_usage']['input_11'],
                                vector['selector_usage']['gateway_11']):
                assert description.encode() in raw
            assert result['sha256'] == hashlib.sha256(raw).hexdigest()
            assert not result['parity']['original_toolkit_executed']
            assert len(result['units']) == 10
            assert helpers.snapshot(owner) == before
