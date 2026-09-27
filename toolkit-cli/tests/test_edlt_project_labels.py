"""Synthetic saved-project DLT metadata; no house project or device involved."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.edlt_project_labels import project_group_labels


XML = ('<Network><Address>254</Address><Application><Address>56</Address>'
       '<TagName>Lighting</TagName><Group><Address>27</Address>'
       '<TagName>Sample Group</TagName><TagsDLT><TagDLT><LanguageID>1</LanguageID>'
       '<FlavourID>1</FlavourID><TagType>TEXT</TagType>'
       '<TagValue>Synthetic Label</TagValue></TagDLT></TagsDLT></Group>'
       '</Application></Network>')
REPOSITORY = Path(__file__).resolve().parents[2]
NATIVE_CAPABILITY = (REPOSITORY / 'rust/testdata/fixtures/'
                     'native_cgate_cmqtt_capability_vm.json')
NATIVE_CAPABILITY_SCRIPT = (REPOSITORY / 'toolkit-cli/research/experiments/'
                            '2026-09-28/cgate-cmqtt-capability-vm-capture.ps1')


def reply(xml=XML, *, status=200):
    ending = '344 End XML Snippet' if status == 344 else '200 OK.'
    return CGateResponse(('347-' + xml, ending), ending, status)


def client_with_capability(xml=XML, *, status=200):
    client = Mock()
    def command(value):
        if value.startswith('DBGETXML '):
            return reply(xml, status=status)
        assert value == 'CMQTT CAPABILITIES'
        return CGateResponse(('200-{"service":"cmqttd","project":"TEST","saved_project_group_dlt_labels":true}',
                              '200 OK.'), '200 OK.', 200)
    client.command.side_effect = command
    return client


@pytest.mark.parametrize('status', [200, 344])
def test_one_network_xml_read_reports_saved_group_labels_without_device_claim(status):
    client = client_with_capability(status=status)

    result = project_group_labels(client, '//TEST/254')

    assert client.command.call_args_list[0].args == ('DBGETXML //TEST/254',)
    assert client.command.call_args_list[1].args == ('CMQTT CAPABILITIES',)
    assert result['project_snapshot_complete'] and result['device_readback'] is False
    assert result['device_label_inventory_complete'] is False
    assert result['cmqttd_import_capability_verified'] is True
    assert result['source'] == 'cgate-dbgetxml-saved-project'
    assert result['scope'] == 'network-group-tagsdlt'
    assert result['application_count'] == result['group_count'] == result['label_count'] == 1
    assert result['labels'] == [{
        'path': '//TEST/254/56/27', 'application': 56,
        'application_name': 'Lighting', 'group': 27,
        'group_name': 'Sample Group', 'language_id': 1,
        'flavour_id': 1, 'tag_type': 'TEXT', 'tag_value': 'Synthetic Label',
    }]
    assert len(result['xml_sha256']) == 64


def test_native_344_multiline_xml_is_accepted():
    native = json.loads(NATIVE_CAPABILITY.read_text(encoding='utf-8'))
    assert native['jar_sha256'] == ('3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630')
    assert native['capture_script_sha256'] == hashlib.sha256(NATIVE_CAPABILITY_SCRIPT.read_bytes()).hexdigest()
    assert native['capability_response_lines'] == ['[1] 400 Syntax Error.\r\n']
    assert native['noop_response_lines'] == ['[2] 200 OK.\r\n']
    assert native['ipv4_default_routes_during'] == 0
    assert native['cleanup']['process_exit_confirmed']
    assert native['cleanup']['original_home_restored']
    client = Mock()
    client.greeting = native['greeting'].removesuffix('\r\n')
    def command(value):
        if value == 'DBGETXML //TEST/254':
            return CGateResponse(
                ('347-<Network>', '  <Address>254</Address>', '</Network>',
                 '344 End XML Snippet'), '344 End XML Snippet', 344)
        assert value == 'CMQTT CAPABILITIES'
        payload = native['capability_response_lines'][0].removeprefix('[1] ').removesuffix('\r\n')
        raise CGateError(CGateResponse((payload,), payload, 400))
    client.command.side_effect = command
    result = project_group_labels(client, '//TEST/254')
    assert result['project_snapshot_complete'] and result['label_count'] == 0
    assert result['cmqttd_import_capability_verified'] is False
    assert [call.args for call in client.command.call_args_list] == [
        ('DBGETXML //TEST/254',), ('CMQTT CAPABILITIES',)]


@pytest.mark.parametrize(('xml', 'message'), [
    (XML.replace('<Address>254</Address>', '<Address>253</Address>', 1), 'does not match'),
    (XML.replace('<FlavourID>1</FlavourID>', '<FlavourID>5</FlavourID>'), 'flavour'),
    (XML.replace('</Group>', '</Group><Group><Address>27</Address><TagName>Duplicate</TagName></Group>'), 'duplicate groups'),
    (XML.replace('<TagValue>Synthetic Label</TagValue>', '<TagValue>' + 'x' * 1025 + '</TagValue>'), 'field length'),
    ('<!DOCTYPE Network><Network><Address>254</Address></Network>', 'DTD'),
])
def test_rejects_untrustworthy_network_xml(xml, message):
    client = client_with_capability(xml)
    with pytest.raises(ValueError, match=message):
        project_group_labels(client, '//TEST/254')


def test_invalid_address_rejected_before_database_read():
    client = Mock()
    with pytest.raises(ValueError):
        project_group_labels(client, '//TEST/256')
    client.command.assert_not_called()


@pytest.mark.parametrize('status', [200, 344])
def test_old_cmqttd_cannot_certify_an_empty_project_label_result(status):
    client = Mock()
    def command(value):
        if value.startswith('DBGETXML '):
            return reply('<Network><Address>254</Address></Network>', status=status)
        return CGateResponse(('200-{"service":"cmqttd"}', '200 OK.'), '200 OK.', 200)
    client.command.side_effect = command
    with pytest.raises(ValueError, match='not confirmed'):
        project_group_labels(client, '//TEST/254')


def test_unidentified_service_cannot_bypass_import_capability_with_344_xml():
    client = Mock()
    client.greeting = '201 cmqttd C-Gate service ready'
    def command(value):
        if value.startswith('DBGETXML '):
            return reply('<Network><Address>254</Address></Network>', status=344)
        raise CGateError(CGateResponse(('400 Unknown command',), '400 Unknown command', 400))
    client.command.side_effect = command
    with pytest.raises(ValueError, match='could not be verified'):
        project_group_labels(client, '//TEST/254')


def test_other_project_cannot_borrow_configured_project_import_capability():
    client = client_with_capability('<Network><Address>254</Address></Network>')
    with pytest.raises(ValueError, match='requested project'):
        project_group_labels(client, '//OTHER/254')
