#!/usr/bin/env python3
"""Compare project TEXT plans against an owned, closed-network native C-Gate.

Only synthetic project records in an ephemeral loopback service are used.
The sanitized receipt stores assertions/digests and no vendor code or site data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import socket
import xml.etree.ElementTree as ET

from cbus_toolkit.dlt_project_labels import plan_project_labels, show_project_labels
from cgate_dbsetxml_duplicate_applications import exchange, status, xml
from local_cgate import LocalCGate, JAR_SHA256


def digest(value):
    return hashlib.sha256(value).hexdigest()


def source_facts(vendor):
    import pefile
    exe = vendor / 'toolkit/app/CBusToolkit.exe'
    raw = exe.read_bytes()
    if digest(raw) != '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab':
        raise ValueError('Original Toolkit executable digest differs')
    image = pefile.PE(data=raw)
    ranges = (
        ('TGroupTagDLTCGateAgent.AgentSave', 0x1213388, 0x4c,
         'creates the project DLT tag when needed, then updates its fields'),
        ('TGroupTagDLTCGateAgent.CreateGroupLanguageDLTTag', 0x12134e4, 0xf5,
         'Group or Level parent; ensures TagsDLT collection then creates TagDLT'),
        ('TGroupTagDLTCGateAgent.UpdateGroupLanguageDLTTag', 0x1213634, 0xdb,
         'writes LanguageID, FlavourID, TagType, TagValue then saves the project'),
    )
    literals = ((0x12135e8, 'TagsDLT'), (0x1213624, 'TagDLT'),
                (0x121371c, 'LanguageID'), (0x1213740, 'FlavourID'),
                (0x1213760, 'TagType'), (0x121377c, 'TagValue'))
    for address, value in literals:
        expected = (value + '\0').encode('utf-16-le')
        assert image.get_data(address - image.OPTIONAL_HEADER.ImageBase, len(expected)) == expected
    schema = vendor / 'cgate-decompiled/com/clipsal/cgate/tag/model/descriptors/LanguageTypeDescriptor.java'
    schema_text = schema.read_text()
    assert '"_ID", "ID", NodeType.Element' in schema_text
    assert '"_tagValue", "TagValue", NodeType.Element' in schema_text
    return {'exe_sha256': digest(raw), 'map_sha256': digest((vendor / 'toolkit/app/CBusToolkit.map').read_bytes()),
            'ranges': [{'name': name, 'va': f'0x{address:X}', 'size': size, 'meaning': meaning,
                        'sha256': digest(image.get_data(address - image.OPTIONAL_HEADER.ImageBase, size))}
                       for name, address, size, meaning in ranges],
            'literal_fields_verified': [value for _, value in literals],
            'network_language_schema_sha256': digest(schema.read_bytes()),
            'network_language_identity_field': 'ID',
            'original_gui_executed': False}


def run(vendor, java):
    facts = source_facts(vendor)
    comparisons = []
    with LocalCGate(vendor / 'cgate/app', java=java) as service:
        with socket.create_connection(('127.0.0.1', service.port), timeout=5) as sock:
            sock.settimeout(20)
            stream = sock.makefile('rwb', buffering=0)
            greeting = stream.readline().decode('utf-8')
            assert 'C-Gate' in greeting
            counter = 6500
            def call(command, document=None):
                nonlocal counter
                result = exchange(stream, counter, command, document)
                counter += 1
                return result
            def okay(command, document=None):
                result = call(command, document)
                assert status(result) < 400, (command, result['response_lines'])
                return result
            def project_xml():
                return xml(okay('DBGETXML //DTEXT'))
            for command in ('PROJECT NEW DTEXT', 'PROJECT USE DTEXT', 'DBCREATENET 254 Synthetic Cni 127.0.0.1:1'):
                okay(command)
            base = ET.fromstring(xml(okay('DBGETXML //DTEXT/254')))
            network_oid, interface_oid = base.findtext('OID'), base.findtext('Interface/OID')
            def group(app, number, level=''):
                return (f'<Application><OID>33333333-3333-4333-8333-{app:012d}</OID>'
                        f'<TagName>Application {app}</TagName><Address>{app}</Address>'
                        f'<Group><OID>44444444-4444-4444-8444-{app:012d}</OID><TagName>Group {number}</TagName>'
                        f'<Address>{number}</Address>{level}</Group></Application>')
            action = ('<Level Value="43"><OID>55555555-5555-4555-8555-000000000042</OID>'
                      '<TagName>Action 42</TagName><Address>42</Address></Level>')
            seed = (f'<Network><OID>{network_oid}</OID><TagName>Synthetic</TagName><Address>254</Address>'
                    f'<NetworkNumber>254</NetworkNumber><Interface><OID>{interface_oid}</OID>'
                    '<InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>'
                    '<Languages><Language><ID>0</ID><TagValue>1</TagValue></Language>'
                    '<Language><ID>1</ID><TagValue>English</TagValue></Language>'
                    '<Language><ID>2</ID><TagValue>French</TagValue></Language></Languages>'
                    + group(56, 1) + group(202, 7, action) + '</Network>')
            okay('DBSETXML //DTEXT/254', seed)
            for command in ('PROJECT SAVE DTEXT', 'PROJECT CLOSE DTEXT', 'PROJECT LOAD DTEXT', 'PROJECT USE DTEXT'):
                okay(command)
            expected_languages = show_project_labels(project_xml(), '//DTEXT/254/56/1')['network_languages']
            assert expected_languages == [
                {'language_id': '0', 'value': '1'}, {'language_id': '1', 'value': 'English'},
                {'language_id': '2', 'value': 'French'}]
            for target in ('//DTEXT/254/56/1', '//DTEXT/254/202/7/42'):
                initial = project_xml()
                # Exercise empty, ASCII, Latin1, BMP and supplementary Unicode,
                # both language boundaries, all four UI variants, and the local
                # 1024-character limit. These establish storage, not rendering.
                edits = [
                    {'language_id': 0, 'variant': 1, 'text': ''},
                    {'language_id': 1, 'variant': 1, 'text': 'ASCII & <label>'},
                    {'language_id': 1, 'variant': 2, 'text': 'café'},
                    {'language_id': 1, 'variant': 3, 'text': '语言 😀'},
                    {'language_id': 1, 'variant': 4, 'text': 'A' * 1024},
                    {'language_id': 255, 'variant': 4, 'text': '\t\n\r'},
                ]
                plan = plan_project_labels(initial, target, edits)
                reply = okay('DBSETXML ' + target, plan.target_xml)
                assert status(reply) == 301
                native = show_project_labels(project_xml(), target)
                assert [(r['language_id'], r['variant'], r['text']) for r in native['labels']] == [
                    (str(e['language_id']), str(e['variant']), e['text']) for e in edits]
                assert all(row['oid'] for row in native['labels'])
                assert native['network_languages'] == expected_languages
                oids = [row['oid'] for row in native['labels']]
                # Re-edit one existing record, requiring stable identity and all
                # neighbor records/Level.Value to survive native save + reload.
                update = plan_project_labels(project_xml(), target,
                    [{'language_id': 1, 'variant': 2, 'text': 'updated café'}])
                okay('DBSETXML ' + target, update.target_xml)
                updated = show_project_labels(project_xml(), target)
                assert updated['labels'] == json.loads(update.after)['labels']
                assert [row['oid'] for row in updated['labels']] == oids
                for command in ('PROJECT SAVE DTEXT', 'PROJECT CLOSE DTEXT', 'PROJECT LOAD DTEXT', 'PROJECT USE DTEXT'):
                    okay(command)
                reloaded = show_project_labels(project_xml(), target)
                assert reloaded['labels'] == updated['labels']
                assert reloaded['network_languages'] == expected_languages
                if target.endswith('/42'):
                    node = ET.fromstring(xml(okay('DBGETXML ' + target)))
                    assert node.attrib['Value'] == '43' and node.findtext('Address') == '42'
                comparisons.append({'kind': native['kind'], 'set_status': status(reply),
                                    'language_ids': [0, 1, 255], 'variants': [1, 2, 3, 4],
                                    'text_cases': ['empty', 'ASCII/XML escaping', 'Latin1', 'BMP/supplementary Unicode',
                                                   '1024 ASCII characters', 'TAB/LF/CR'],
                                    'label_count': len(native['labels']),
                                    'new_tag_oids_allocated': True, 'existing_tag_oids_retained': True,
                                    'other_variants_preserved': True, 'language_definitions_preserved': True,
                                    'save_close_load_verified': True,
                                    'action_address_and_value_preserved': native['kind'] == 'Level'})
    report = service.report
    return {'format': 'cbus-classic-dlt-project-text-native-v1', 'original': facts,
            'oracle': {'jar_sha256': JAR_SHA256, 'java_sha256': report['java_sha256'],
                       'version': '3.4.0 build 2001', 'owned_loopback_listeners': report['listener_ownership_verified'],
                       'cleanup_complete': report['cleanup_complete'], 'work_removed': report['work_removed'],
                       'process_exit_confirmed': report['process_exit_confirmed'], 'physical_endpoint': False},
            'cases': comparisons, 'labels_transferred': False, 'display_verified': False,
            'source_sha256': digest(Path(__file__).read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', required=True, type=Path)
    parser.add_argument('--java', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    receipt = run(args.vendor, args.java)
    args.output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
