"""Public ST7 saved-report journeys against both owned loopback backends."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

import test_cgate_project_documentation_interop as helpers
from test_cgate_barcode_database_interop import cli

VECTOR = Path(__file__).resolve().parents[1] / 'research/fixtures/project-documentor-st7-light-level.json'


def input_xml(vector, trap):
    """Change only the invented native fixture's closed Interface address."""
    root = ET.fromstring(vector['native_xml'])
    for network in root.findall('./Project/Network'):
        interface = network.find('Interface')
        interface.find('InterfaceType').text = 'cni'
        interface.find('InterfaceAddress').text = trap
    return ET.tostring(root, encoding='utf-8')


@pytest.mark.parametrize('backend,variable', helpers.BACKENDS, ids=('mock','daemon'))
def test_public_database_document_st7_zero_timers_stored_scenes_and_direct_roles(backend, variable, tmp_path):
    vector = json.loads(VECTOR.read_text())
    with patch.object(helpers,'VECTOR',VECTOR), patch.object(helpers,'synthetic_xml',lambda trap:input_xml(vector,trap)):
        with helpers.journey(backend,variable,tmp_path) as (owner,relay,evidence,_endpoint):
            evidence['format'] = 'cbus-project-documentation-st7-light-level-owned-v1'
            before = helpers.snapshot(owner)
            # Both stores retain complete packed scene/key state. The public
            # CLI's single snapshot projection consumes the selected report.
            assert 'SceneTable' in before and '162 164 166 168 170 172 174 176' in before
            output = tmp_path/'st7.html'
            result, call = cli(relay,evidence['calls'],'database-document','--project','//DOCREST',
                '--generated-at','2026-10-03T12:00:00','--output',output)
            helpers.read_only(call)
            raw = output.read_bytes()
            assert raw.startswith(b'\xef\xbb\xbf<html>\r\n') and raw.endswith(b'</html>\r\n')
            assert b'\n' not in raw.replace(b'\r\n',b'')
            assert b'Generated on: 03 Oct 2026 12:00<br />\r\n' in raw
            for case in vector['cases']:
                unit = case['unit']
                literal = [f"Unit Address: {unit['address']}<br />",f"Tagname: {unit['name']}<br />",
                    'Part name: Synthetic<br />',
                    ('Application: Unused<br />' if case['id']=='unused-objects' else
                     'Application: <a href="#254_56">Primary</a><br />'),
                    ('Secondary Application: Unused<br />' if case['id']=='unused-objects' else
                     'Secondary Application: <a href="#254_56">Primary</a><br />' if case['id']=='coincident-roles' else
                     'Secondary Application: <a href="#254_57">Secondary</a><br />'),
                    f"Serial Number: {unit['serial']}<br />",'Firmware Version: 2.0.01<br />',
                    'Notes: Invented stored ST7 state<br />','<br />']+case['body_lines']
                assert raw.count(('\r\n'.join(literal)+'\r\n').encode()) == 1
            assert result['units'] == [{'network':254,'unit':case['unit']['address'],'unit_type':'SENLL',
                'documentor':'TST7LightLevelSensorDocumentor','status':'recovered'} for case in vector['cases']]
            assert result['networks'] == [254] and result['output_complete']
            assert b'Level Group<br/>On/Off Group' in raw
            assert b'Light Level Broadcast Group<br/>Enable Group' in raw
            assert b'Block (Unused)' not in raw and b'Light Level Maintenance' not in raw
            assert b'<li />Trigger Scene' not in raw
            assert result['sha256'] == hashlib.sha256(raw).hexdigest()
            snapshot = '\n'.join(line.removeprefix('347-') for line in call['reply_lines'][0]
                if line.startswith('347-')).encode()
            assert result['source_snapshot']['sha256'] == hashlib.sha256(snapshot).hexdigest()
            assert result['source_snapshot']['requests'] == 1
            assert not result['native_database_mutated'] and not result['physical_programming_loaded']
            assert not result['network_open_requested'] and not result['project_save_requested']
            assert not result['parity']['original_toolkit_executed']
            assert helpers.snapshot(owner) == before
        assert evidence['closed_graph_trap_contacts'] == 0
