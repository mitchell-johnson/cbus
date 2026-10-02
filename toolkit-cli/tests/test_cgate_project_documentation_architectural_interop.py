"""Literal architectural reports through the installed public database-document CLI.

Reuses owned TCP processes and a closed fake CNI. Invented inputs and retained
literal cells do not establish original generated HTML or hardware acceptance.
"""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import test_cgate_project_documentation_interop as helpers
from test_cgate_barcode_database_interop import cli

VECTOR = Path(__file__).resolve().parents[1] / 'research/fixtures/project-documentor-architectural-literal.json'


def corpus():
    source = json.loads(VECTOR.read_text())
    return {'generated_at': '2026-10-02T12:00:00',
            'applications': source['network']['applications'],
            'cases': [{'id': case['id'],
                       'family': 'ArchitecturalDimmer',
                       'body_lines': case['body_lines'],
                       'unit': {'unit_type': case['unit_type'], 'firmware': case['firmware'],
                                'unit_name': case['unit_type'], 'serial': '', 'description': '',
                                'parameters': case['parameters'], 'fields': {}}}
                      for case in source['cases']]}


@pytest.mark.parametrize('backend,variable', helpers.BACKENDS, ids=('mock', 'daemon'))
def test_public_database_document_architectural_families_preserves_snapshot(backend, variable, tmp_path):
    data = corpus()
    with patch.object(helpers, 'DATA', data), patch.object(helpers, 'VECTOR', VECTOR):
        with helpers.journey(backend, variable, tmp_path) as (owner, relay, evidence, _endpoint):
            evidence['format'] = 'cbus-project-documentation-architectural-owned-v1'
            before = helpers.snapshot(owner)
            output = tmp_path / 'architectural.html'
            result, call = cli(relay, evidence['calls'], 'database-document', '--project', '//DOCREST',
                               '--generated-at', data['generated_at'], '--network', '254', '--output', output)
            helpers.read_only(call)
            raw = output.read_bytes()
            assert raw.startswith(b'\xef\xbb\xbf<html>\r\n') and raw.endswith(b'</html>\r\n')
            assert b'\n' not in raw.replace(b'\r\n', b'')
            assert b'Generated on: 02 Oct 2026 12:00<br />\r\n' in raw
            for index, case in enumerate(data['cases']):
                assert ('\r\n'.join(case['body_lines']) + '\r\n').encode() in raw
                assert result['units'][index] == {
                    'network': 254, 'unit': index + 3, 'unit_type': case['unit']['unit_type'],
                    'documentor': 'T' + case['family'] + 'Documentor', 'status': 'recovered'}
            assert b'name="254_202_6_9"' in raw
            assert result['sha256'] == hashlib.sha256(raw).hexdigest()
            assert not result['parity']['original_toolkit_executed']
            assert len(result['units']) == 4
            assert helpers.snapshot(owner) == before
