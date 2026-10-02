"""Public saved-state Bytecraft L1 reports on both owned Rust backends."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

import test_cgate_project_documentation_interop as helpers
from test_cgate_barcode_database_interop import cli

VECTOR = Path(__file__).resolve().parents[1] / 'research/fixtures/project-documentor-bytecraft-l1.json'


def input_xml(vector, trap):
    """Change only invented fixture project/interface input for owned restore."""
    root = ET.fromstring(vector['native_xml'])
    project = root.find('Project')
    project.find('Address').text = 'DOCREST'
    for network in project.findall('Network'):
        interface = network.find('Interface')
        interface.find('InterfaceType').text = 'cni'
        interface.find('InterfaceAddress').text = trap
    return ET.tostring(root, encoding='utf-8')


@pytest.mark.parametrize('backend,variable', helpers.BACKENDS, ids=('mock', 'daemon'))
def test_public_database_document_l1_preserves_snapshot_and_literal_body(backend, variable, tmp_path):
    vector = json.loads(VECTOR.read_text())
    with patch.object(helpers, 'VECTOR', VECTOR), patch.object(
            helpers, 'synthetic_xml', lambda trap: input_xml(vector, trap)):
        with helpers.journey(backend, variable, tmp_path) as (owner, relay, evidence, _endpoint):
            evidence['format'] = 'cbus-project-documentation-l1-owned-v1'
            before = helpers.snapshot(owner)
            output = tmp_path / 'l1.html'
            result, call = cli(relay, evidence['calls'], 'database-document', '--project', '//DOCREST',
                               '--generated-at', '2026-10-03T12:00:00', '--output', output)
            helpers.read_only(call)
            raw = output.read_bytes()
            assert raw.startswith(b'\xef\xbb\xbf<html>\r\n') and raw.endswith(b'</html>\r\n')
            assert b'\n' not in raw.replace(b'\r\n', b'')
            assert b'Generated on: 03 Oct 2026 12:00<br />\r\n' in raw
            literal = ['Unit Address: 1<br />', 'Tagname: L1 dimmer<br />',
                'Part name: DIMPR12<br />', 'Application: <a href="#254_56">Lighting</a><br />',
                'Serial Number: 000000010001<br />', 'Firmware Version: 1.9.03<br />',
                'Notes: <br />', '<br />'] + vector['body_lines']
            assert raw.count(('\r\n'.join(literal) + '\r\n').encode()) == 1
            assert result['units'] == [{'network':254,'unit':1,'unit_type':'DIMPR12',
                                       'documentor':'TBytecraftDimmerDocumentor','status':'recovered'}]
            assert result['networks'] == [254]
            for key in ('output_56_9','input_56_8','other_56_8'):
                assert vector['group_usage'][key].encode() in raw
            # The top-level report skips Group255; direct consumer identity
            # for its dependency text is checked by the independent L1 test.
            assert b'name="254_203_255"' not in raw
            assert vector['selector_usage']['11'].encode() in raw
            assert b'name="254_202_7_11">Eleven<&></a>' in raw
            assert result['sha256'] == hashlib.sha256(raw).hexdigest()
            snapshot = '\n'.join(line.removeprefix('347-') for line in call['reply_lines'][0]
                                 if line.startswith('347-')).encode()
            assert result['source_snapshot']['sha256'] == hashlib.sha256(snapshot).hexdigest()
            assert result['source_snapshot']['requests'] == 1 and result['output_complete']
            assert not result['native_database_mutated'] and not result['physical_programming_loaded']
            assert not result['network_open_requested'] and not result['project_save_requested']
            assert not result['parity']['original_toolkit_executed']
            assert helpers.snapshot(owner) == before
