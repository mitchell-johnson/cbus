"""Synthetic saved-project DLT metadata; no house project or device involved."""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.edlt_project_labels import project_group_labels


XML = ('<Network><Address>254</Address><Application><Address>56</Address>'
       '<TagName>Lighting</TagName><Group><Address>27</Address>'
       '<TagName>Sample Group</TagName><TagsDLT><TagDLT><LanguageID>1</LanguageID>'
       '<FlavourID>1</FlavourID><TagType>TEXT</TagType>'
       '<TagValue>Synthetic Label</TagValue></TagDLT></TagsDLT></Group>'
       '</Application></Network>')


def reply(xml=XML, *, status=200):
    ending = '344 End XML Snippet' if status == 344 else '200 OK.'
    return CGateResponse(('347-' + xml, ending), ending, status)


def client_with_capability(xml=XML):
    client = Mock()
    def command(value):
        if value.startswith('DBGETXML '):
            return reply(xml)
        assert value == 'CMQTT CAPABILITIES'
        return CGateResponse(('200-{"service":"cmqttd","project":"TEST","saved_project_group_dlt_labels":true}',
                              '200 OK.'), '200 OK.', 200)
    client.command.side_effect = command
    return client


def test_one_network_xml_read_reports_saved_group_labels_without_device_claim():
    client = client_with_capability()

    result = project_group_labels(client, '//TEST/254')

    assert client.command.call_args_list[0].args == ('DBGETXML //TEST/254',)
    assert client.command.call_args_list[1].args == ('CMQTT CAPABILITIES',)
    assert result['project_snapshot_complete'] and result['device_readback'] is False
    assert result['device_label_inventory_complete'] is False
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
    client = Mock()
    client.command.return_value = CGateResponse(
        ('347-<Network>', '  <Address>254</Address>', '</Network>', '344 End XML Snippet'),
        '344 End XML Snippet', 344)
    result = project_group_labels(client, '//TEST/254')
    assert result['project_snapshot_complete'] and result['label_count'] == 0
    client.command.assert_called_once_with('DBGETXML //TEST/254')


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


def test_old_cmqttd_cannot_certify_an_empty_project_label_result():
    client = Mock()
    def command(value):
        if value.startswith('DBGETXML '):
            return reply('<Network><Address>254</Address></Network>')
        return CGateResponse(('200-{"service":"cmqttd"}', '200 OK.'), '200 OK.', 200)
    client.command.side_effect = command
    with pytest.raises(ValueError, match='not confirmed'):
        project_group_labels(client, '//TEST/254')


def test_other_project_cannot_borrow_configured_project_import_capability():
    client = client_with_capability('<Network><Address>254</Address></Network>')
    with pytest.raises(ValueError, match='requested project'):
        project_group_labels(client, '//OTHER/254')
