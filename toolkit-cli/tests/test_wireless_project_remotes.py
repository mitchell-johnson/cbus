"""Literal project metadata cases; no native service, PP session or radio."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.wireless_project_remotes import (
    FrozenRemoteProject, RemoteCatalogue, RemoteCreationPlan, RemoteCreationError,
    RemoteCreationApplyError, plan_project_remote, apply_project_remote, preview_project_remote,
)


CATALOGUE = b'''<CBusUnits><Units><Unit><CatalogNumber>5888TXBA</CatalogNumber>
<FirmwareRevisions><Revision><UnitType>WTXU</UnitType><MinVersion>0</MinVersion>
<MaxVersion>9</MaxVersion><UnitSpecName>WTXU.xml</UnitSpecName><ClassName>CBusPCI</ClassName>
<IsDefault>true</IsDefault></Revision></FirmwareRevisions><InputCount>0</InputCount>
<OutputCount>0</OutputCount><GroupCount>0</GroupCount><IsAddressable>false</IsAddressable>
</Unit></Units></CBusUnits>'''


def unit(address, tag, *, serial='', kind='WTXU', firmware='0'):
    return (f'<Unit><Address>{address}</Address><TagName>{tag}</TagName>'
            f'<UnitType>{kind}</UnitType><FirmwareVersion>{firmware}</FirmwareVersion>'
            f'<SerialNumber>{serial}</SerialNumber></Unit>')


def project(*units, gateway=True):
    original = (unit(200, 'Gateway', kind='WGATE5F', firmware='2.4.00') if gateway else '')
    # Existing opaque PP and nested content must remain exactly unchanged.
    original = original.replace('</Unit>', '<PP><RemoteIdentity1>1 2 3 4</RemoteIdentity1>'
                                '<Unknown name="opaque">  retained  </Unknown></PP></Unit>')
    return ('<Project><Address>TEST</Address><TagName>Synthetic</TagName>'
            '<UnknownRoot version="1"><Data>keep</Data></UnknownRoot>'
            '<Network><Address>254</Address><TagName>Source</TagName>'
            + original + ''.join(units) + '</Network>'
            '<Network><Address>123</Address><TagName>Other</TagName>'
            + unit(100, 'Remote 01', serial='42.7') + '</Network></Project>').encode()


def plan(payload=None, serial='70179.836'):
    return plan_project_remote(FrozenRemoteProject.from_xml(payload or project()),
                               source_network=254, gateway_address=200, serial=serial,
                               catalogue=RemoteCatalogue.from_xml(CATALOGUE))


def reply(code, lines=None):
    lines = tuple(lines or (f'{code} OK',))
    return CGateResponse(lines, lines[-1], code)


class DatabasePeer:
    def __init__(self, payload=None, *, fail_save=None, fail_set=None, corrupt=False):
        self.root = ET.fromstring(payload or project())
        self.commands, self.saved_rows = [], []
        self.fail_save, self.fail_set, self.corrupt = fail_save, fail_set, corrupt

    def command(self, command):
        self.commands.append(command)
        if command.startswith('DBGETXML '):
            text = ET.tostring(self.root, encoding='unicode')
            return reply(344, ('347-' + text, '344 OK'))
        if command.startswith('DBADDSAFE '):
            _, _, kind, address, tag = command.split(' ', 4)
            assert kind == 'Unit'
            source = self.root.findall('Network')[0]
            row = ET.SubElement(source, 'Unit')
            for name, value in (('OID', '12345678-1234-1234-1234-123456789012'),
                                ('Address', address), ('TagName', tag)):
                ET.SubElement(row, name).text = value
            return reply(301, ('301 OID=12345678-1234-1234-1234-123456789012',))
        if command.startswith('DBSETSAFE '):
            _, path, value = command.split(' ', 2)
            field = path.rsplit('/', 1)[1]
            if field == self.fail_set:
                raise OSError('lost metadata reply')
            row = self.root.findall('Network')[0].findall('Unit')[-1]
            target = row.find(field)
            if target is None:
                target = ET.SubElement(row, field)
            target.text = value
            if self.corrupt and field == 'CatalogNumber':
                self.root.find('UnknownRoot/Data').text = 'changed'
            return reply(200)
        if command == 'PROJECT SAVE TEST':
            self.saved_rows.append(deepcopy(self.root.findall('Network')[0].findall('Unit')[-1]))
            if len(self.saved_rows) == self.fail_save:
                raise OSError('lost save reply')
            return reply(200)
        raise AssertionError('Unexpected command: ' + command)


class RemoteCreationTest(unittest.TestCase):
    def apply(self, peer, selected=None):
        with patch('cbus_toolkit.wireless_project_remotes._closed'):
            return apply_project_remote(peer, selected or plan(), exclusive_project=True)

    def test_literal_first_gap_address_and_case_sensitive_name(self):
        selected = plan(project(unit(102, 'Remote 03'), unit(100, 'Remote 01'), unit(50, 'remote 02')))
        self.assertEqual((selected.address, selected.tag_name), (101, 'Remote 02'))
        # Another network's Remote01/serial42.7 does not affect source allocation.
        self.assertEqual((plan(serial='42.7').address, plan().tag_name), (100, 'Remote 01'))

    def test_name_width_grows_and_255_is_available(self):
        rows = [unit(a, f'Remote {i:02d}') for i, a in enumerate(range(100, 255), 1) if a != 200]
        selected = plan(project(*rows))
        self.assertEqual(selected.address, 255)
        self.assertEqual(selected.tag_name, 'Remote 101')

    def test_exhaustion_does_not_fall_back_to_zero(self):
        with self.assertRaisesRegex(RemoteCreationError, '100..255'):
            plan(project(*(unit(a, f'U{a}') for a in range(100, 256) if a != 200)))

    def test_profile_and_selection_refusals(self):
        for payload in (project().replace(b'WGATE5F', b'WGATE5N'),
                        project().replace(b'2.4.00', b'2.5.00'), project(gateway=False)):
            with self.subTest(payload=payload[:50]), self.assertRaises(RemoteCreationError):
                plan(payload)
        for field, value in (('source_network', True), ('source_network', 255),
                             ('gateway_address', 255), ('gateway_address', 17)):
            args = dict(source_network=254, gateway_address=200, serial='1.2',
                        catalogue=RemoteCatalogue.from_xml(CATALOGUE))
            args[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(RemoteCreationError):
                plan_project_remote(FrozenRemoteProject.from_xml(project()), **args)

    def test_unknown_noncanonical_and_duplicate_serials_refuse(self):
        for value in ('0.0', '1048575.4095', '1048576.0', '1.4096', '00000001.0002',
                      '11223344', 42, '1.2\nDBDELETE //TEST', None):
            with self.subTest(serial=value), self.assertRaises(RemoteCreationError):
                plan(serial=value)
        for value in ('70179.836', '00070179.0836', 'broken'):
            with self.subTest(existing=value), self.assertRaises(RemoteCreationError):
                plan(project(unit(100, 'Existing', serial=value)))

    def test_duplicate_database_facts_fail_closed(self):
        for rows in ((unit(100, 'A'), unit(100, 'B')),
                     (unit(100, 'A'), unit(101, 'A')),
                     (unit(100, 'A', serial='9.8'), unit(101, 'B', serial='9.8'))):
            with self.subTest(rows=rows), self.assertRaises(RemoteCreationError):
                plan(project(*rows))

    def test_frozen_projection_is_immutable_and_roundtrips(self):
        selected = plan()
        with self.assertRaises(FrozenInstanceError):
            selected.project.payload = b''
        data = selected.as_dict()
        copied = RemoteCreationPlan.from_dict(json.loads(json.dumps(data)))
        self.assertEqual(copied.as_dict(), data)
        for key, value in (('created_address', 0), ('tag_name', 'Hijacked'),
                           ('project_save_stages', ['constructor']), ('pp_initialized', True)):
            bad = deepcopy(data)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(RemoteCreationError):
                RemoteCreationPlan.from_dict(bad)

    def test_snapshot_and_catalogue_integrity(self):
        selected = plan()
        bad = selected.project.as_dict()
        bad['xml'] = bad['xml'].replace('keep', 'changed')
        with self.assertRaisesRegex(RemoteCreationError, 'fingerprint'):
            FrozenRemoteProject.from_dict(bad)
        for payload in (b'<!DOCTYPE Project><Project/>', b'<Project>', b'\xff', b''):
            with self.subTest(payload=payload), self.assertRaises(RemoteCreationError):
                FrozenRemoteProject.from_xml(payload)
        for old, new in ((b'5888TXBA', b'5888TXBA*'), (b'WTXU.xml', b'WTXU2.xml'),
                         (b'<MinVersion>0', b'<MinVersion>1'), (b'<InputCount>0', b'<InputCount>1'),
                         (b'<IsAddressable>false', b'<IsAddressable>true')):
            with self.subTest(old=old), self.assertRaises(RemoteCreationError):
                RemoteCatalogue.from_xml(CATALOGUE.replace(old, new))
        duplicate = CATALOGUE.replace(b'</Units>', CATALOGUE.split(b'<Units>')[1].split(b'</Units>')[0] + b'</Units>')
        with self.assertRaises(RemoteCreationError):
            RemoteCatalogue.from_xml(duplicate)
        for extra in ('<CatalogNumber>5888TXBA</CatalogNumber>',
                      '<CatalogNumber>5888*</CatalogNumber>',
                      '<CatalogNumber>OTHER</CatalogNumber><AlternativeCatalogNumbers>'
                      '5888TXBA</AlternativeCatalogNumbers>'):
            payload = CATALOGUE.replace(b'</Units>', ('<Unit>' + extra + '</Unit></Units>').encode())
            with self.subTest(extra=extra), self.assertRaisesRegex(RemoteCreationError, 'Ambiguous'):
                RemoteCatalogue.from_xml(payload)

    def test_utf16_entity_and_command_size_caps_fail_closed(self):
        hostile = '<!DOCTYPE Project [<!ENTITY x "evil">]><Project><Address>&x;</Address></Project>'
        for encoding in ('utf-16-le', 'utf-16-be', 'utf-16'):
            with self.subTest(encoding=encoding), self.assertRaises(RemoteCreationError):
                FrozenRemoteProject.from_xml(hostile.encode(encoding))
        selected = plan()
        with patch('cbus_toolkit.wireless_project_remotes.MAX_PROJECT_XML_BYTES', 20):
            with self.assertRaisesRegex(RemoteCreationError, 'size cap'):
                FrozenRemoteProject.from_xml(project())
        with patch('cbus_toolkit.wireless_project_remotes.MAX_CATALOGUE_XML_BYTES', 20):
            with self.assertRaisesRegex(RemoteCreationError, 'size cap'):
                RemoteCatalogue.from_xml(CATALOGUE)
        with patch('cbus_toolkit.wireless_project_remotes.MAX_PLAN_JSON_BYTES', 20):
            with self.assertRaisesRegex(RemoteCreationError, 'size cap'):
                selected.as_dict()

    def test_native_config_oid_allowance_is_narrow_and_postsave_only(self):
        from cbus_toolkit.wireless_project_remotes import _preserved_tree
        original = ET.fromstring('''<Project><Config><Application>cgate</Application>
          <OID>12345678-1234-1234-1234-123456789012</OID><Property>
          <OID>aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa</OID><Name>foo</Name><Value>bar</Value>
          </Property></Config><Config><Application>other</Application>
          <OID>cccccccc-cccc-cccc-cccc-cccccccccccc</OID></Config><Unit>
          <OID>dddddddd-dddd-dddd-dddd-dddddddddddd</OID></Unit></Project>''')
        changed = deepcopy(original)
        changed.find('Config/OID').text = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
        changed.find('Config/Property/OID').text = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
        self.assertNotEqual(_preserved_tree(deepcopy(original)), _preserved_tree(deepcopy(changed)))
        self.assertEqual(_preserved_tree(deepcopy(original), allow_config_oids=True),
                         _preserved_tree(deepcopy(changed), allow_config_oids=True))
        for path in ('Config/Property/Name', 'Config/Property/Value', 'Unit/OID'):
            candidate = deepcopy(changed)
            candidate.find(path).text = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
            with self.subTest(path=path):
                self.assertNotEqual(_preserved_tree(deepcopy(original), allow_config_oids=True),
                                    _preserved_tree(candidate, allow_config_oids=True))
        changed.findall('Config')[1].find('OID').text = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        self.assertNotEqual(_preserved_tree(deepcopy(original), allow_config_oids=True),
                            _preserved_tree(changed, allow_config_oids=True))

    def test_preview_only_reads_and_stale_preview_refuses(self):
        peer = DatabasePeer()
        with patch('cbus_toolkit.wireless_project_remotes._closed'):
            result = preview_project_remote(peer, plan(), exclusive_project=True)
        self.assertTrue(result['dry_run'])
        self.assertTrue(result['preflight_verified'])
        self.assertFalse(result['saved'])
        self.assertEqual(peer.commands, ['DBGETXML //TEST', 'DBGETXML //TEST'])
        stale = DatabasePeer(project().replace(b'keep', b'changed'))
        with self.assertRaises(RemoteCreationError):
            preview_project_remote(stale, plan(), exclusive_project=True)
        self.assertEqual(stale.commands, ['DBGETXML //TEST'])

    def test_apply_three_distinct_save_boundaries_without_pp(self):
        peer = DatabasePeer()
        result = self.apply(peer)
        self.assertTrue(result['saved'])
        self.assertTrue(result['preserved_existing_project'])
        self.assertEqual([r['stage'] for r in result['project_save_attempts']],
                         ['constructor', 'database_agent', 'creation_caller'])
        self.assertTrue(all(r['completed'] for r in result['project_save_attempts']))
        first, second, third = peer.saved_rows
        self.assertEqual({c.tag: c.text or '' for c in first}, {
            'OID': '12345678-1234-1234-1234-123456789012', 'Address': '100',
            'TagName': 'Remote 01', 'UnitType': 'WTXU', 'FirmwareVersion': '0', 'UnitName': 'REMOTE'})
        self.assertEqual(second.findtext('SerialNumber'), '70179.836')
        self.assertEqual(second.findtext('CatalogNumber'), '5888TXBA')
        self.assertEqual(ET.tostring(second), ET.tostring(third))
        self.assertFalse(any(c.startswith(('PP ', 'NET ', 'DBDELETE')) for c in peer.commands))
        self.assertFalse(any('/TagName ' in c or '/State ' in c for c in peer.commands))

    def test_every_uncertain_save_stops_without_readback_rollback_or_replay(self):
        for number in (1, 2, 3):
            with self.subTest(number=number):
                peer = DatabasePeer(fail_save=number)
                with self.assertRaises(RemoteCreationApplyError) as raised:
                    self.apply(peer)
                details = raised.exception.details
                self.assertEqual(len(details['project_save_attempts']), number)
                self.assertEqual(sum(r['completed'] for r in details['project_save_attempts']), number - 1)
                self.assertTrue(details['uncertain_save'])
                self.assertFalse(details['saved'])
                self.assertFalse(details['retry_performed'])
                self.assertFalse(details['rollback_performed'])
                self.assertEqual(peer.commands[-1], 'PROJECT SAVE TEST')

    def test_metadata_failure_stops_without_a_later_save(self):
        for field, saves in (('UnitName', 0), ('SerialNumber', 1), ('CatalogNumber', 1)):
            with self.subTest(field=field):
                peer = DatabasePeer(fail_set=field)
                with self.assertRaises(RemoteCreationApplyError) as raised:
                    self.apply(peer)
                self.assertEqual(len(peer.saved_rows), saves)
                self.assertIn('/' + field + ' ', peer.commands[-1])
                self.assertFalse(raised.exception.details['uncertain_save'])

    def test_created_oid_must_match_the_native_add_receipt(self):
        peer = DatabasePeer()
        original_command = peer.command

        def replaced_oid(command):
            response = original_command(command)
            if command.startswith('DBADDSAFE '):
                return reply(301, ('301 OID=ffffffff-ffff-ffff-ffff-ffffffffffff',))
            return response

        peer.command = replaced_oid
        with self.assertRaisesRegex(RemoteCreationApplyError, 'OID differs'):
            self.apply(peer)
        self.assertEqual(peer.saved_rows, [])

    def test_stale_full_project_including_opaque_data_refuses_before_mutation(self):
        for old, new in ((b'keep', b'changed'), (b'1 2 3 4', b'1 2 3 5'),
                         (b'Remote 01', b'Other Remote')):
            with self.subTest(old=old):
                peer = DatabasePeer(project().replace(old, new))
                with self.assertRaisesRegex(RemoteCreationError, 'changed'):
                    self.apply(peer)
                self.assertEqual(peer.commands, ['DBGETXML //TEST'])

    def test_preservation_failure_after_first_save_does_not_save_again(self):
        peer = DatabasePeer(corrupt=True)
        with self.assertRaises(RemoteCreationApplyError) as raised:
            self.apply(peer)
        self.assertEqual(len(peer.saved_rows), 1)
        self.assertFalse(raised.exception.details['preserved_existing_project'])
        self.assertFalse(raised.exception.details['saved'])

    def test_exclusive_ownership_required_before_any_io(self):
        peer = DatabasePeer()
        with self.assertRaises(RemoteCreationError):
            apply_project_remote(peer, plan())
        self.assertEqual(peer.commands, [])

    def test_open_network_refuses_before_mutation(self):
        peer = DatabasePeer()
        with patch('cbus_toolkit.wireless_project_remotes._closed',
                   side_effect=RemoteCreationError('Every project network must be closed and idle')):
            with self.assertRaisesRegex(RemoteCreationError, 'closed'):
                apply_project_remote(peer, plan(), exclusive_project=True)
        self.assertEqual(peer.commands, ['DBGETXML //TEST'])


if __name__ == '__main__':
    unittest.main()
