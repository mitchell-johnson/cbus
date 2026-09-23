"""Native C-Gate XML adapter tests for database CSV projection."""
import unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace

from cbus_toolkit.toolkit_database_csv import COLUMNS
from cbus_toolkit.toolkit_database_csv_native import (
    loads_native_xml_projection,
    native_xml_reply_text,
    project_native_xml_unit,
)


def oid(number):
    return '00000000-0000-0000-0000-' + str(number).zfill(12)


def scalar(parent, name, value):
    ET.SubElement(parent, name).text = str(value)


def native_xml(*, unit_type='RELAY4', area=12, missing=(), extra_unit=False,
               keye_groups=(1, 2, 255, 255, 255, 255, 255, 255, 255), with_oids=True):
    root = ET.Element('Installation')
    project = ET.SubElement(root, 'Project'); scalar(project, 'Address', 'CSVTEST')
    network = ET.SubElement(project, 'Network'); scalar(network, 'Address', 254)
    application = ET.SubElement(network, 'Application')
    if with_oids:
        scalar(application, 'OID', oid(20))
    scalar(application, 'TagName', 'Lighting'); scalar(application, 'Address', 56)
    for address in (1, 2, 3, 4, 5, 6, 7, 8, 12, 13, 255):
        if address in missing:
            continue
        group = ET.SubElement(application, 'Group')
        if with_oids:
            scalar(group, 'OID', oid(100 + address))
        scalar(group, 'TagName', '<Unused>' if address == 255 else 'Group' + str(address))
        scalar(group, 'Address', address)
    unit = ET.SubElement(network, 'Unit')
    keye = unit_type in ('KEYE1', 'KEYE2', 'KEYE3')
    if with_oids:
        scalar(unit, 'OID', oid(500))
    for name, value in (('TagName', 'OwnedUnit'), ('Address', 4),
                        ('UnitType', unit_type), ('UnitName', 'NativeUnit'),
                        ('SerialNumber', '1.2.3'),
                        ('FirmwareVersion', '2.5.00' if keye else '4.4'),
                        ('CatalogNumber', '5031NMML' if keye else 'OWNED')):
        scalar(unit, name, value)
    if unit_type == 'RELAY4':
        for name, value in (('Application', '0x38 0xff'),
                            ('AreaGroupAddress', hex(area)),
                            ('GroupAddress', ' '.join(hex(value) for value in
                                (*range(1, 9), *(255 for _ in range(8)))))):
            ET.SubElement(unit, 'PP', Name=name, Value=value)
    elif keye:
        for name, value in (('Application', '0x38 0xff'),
                            ('AreaGroupAddress', '0xff'),
                            ('SecondApplicationBlocks', '0'),
                            ('GroupAddress', ' '.join(hex(value) for value in keye_groups))):
            ET.SubElement(unit, 'PP', Name=name, Value=value)
    if extra_unit:
        other = ET.SubElement(network, 'Unit'); scalar(other, 'Address', 5)
    return ET.tostring(root, encoding='unicode')


class NativeXMLCSVProjectionTests(unittest.TestCase):
    def test_relay_existing_area_projects_native_scalars_and_six_groups(self):
        outcome = project_native_xml_unit(native_xml(), '//CSVTEST/254/p/4',
            columns=('group_7', 'secondary', 'area', 'group_1', 'tag_name',
                     'address', 'primary', 'part_name', 'group_6'))
        self.assertTrue(outcome.complete)
        self.assertEqual(outcome.cached.columns,
            ('address', 'part_name', 'tag_name', 'primary', 'secondary',
             'area', 'group_1', 'group_6', 'group_7'))
        self.assertEqual(outcome.report.rows, (
            'Unit Address,Part Name,Tag Name,Primary Application,Secondary Application,Area,Group 1,Group 6,Group 7,',
            '4,NativeUnit,OwnedUnit,Lighting,,Group12,Group1,Group6,<N/A>,'))
        self.assertFalse(outcome.as_dict()['native_database_mutated'])

    def test_relay_unused_area_and_generic_eight_group_profile(self):
        relay = project_native_xml_unit(native_xml(area=255), '//CSVTEST/254/p/4', columns=COLUMNS)
        self.assertIn(',<Unused>,Group1,Group2,Group3,Group4,Group5,Group6,<N/A>,', relay.report.rows[1])
        generic = project_native_xml_unit(native_xml(unit_type='OWNED_UNKNOWN'),
                                          '//CSVTEST/254/p/4', columns=COLUMNS)
        self.assertEqual(generic.cached.selected_class, 'TCBusUnitGeneric')
        self.assertIn(',<Unused>,Group1,Group2,Group3,Group4,Group5,Group6,Group7,Group8,',
                      generic.report.rows[1])

    def test_keye_projects_all_nine_slots_without_collapsing_unused_references(self):
        outcome = project_native_xml_unit(native_xml(unit_type='KEYE2', with_oids=False),
                                          '//CSVTEST/254/p/4', columns=COLUMNS)
        self.assertTrue(outcome.complete)
        self.assertEqual(outcome.cached.selected_class, 'TKEYEx')
        self.assertEqual(len(outcome.cached.unit.group_identities), 9)
        self.assertEqual(outcome.cached.unit.identity, '//CSVTEST/254/p/4')
        self.assertEqual(outcome.cached.unit.group_identities[2:],
                         ('//CSVTEST/254/56/255',) * 7)
        self.assertEqual(outcome.cached.groups[-1].oid, '')
        fields = outcome.report.rows[1].split(',')
        self.assertEqual(fields[9:18],
            ['<Unused>', 'Group1', 'Group2', *('<Unused>' for _ in range(6))])
        self.assertEqual(fields[18:26], ['<N/A>'] * 8)

    def test_keye_profile_rejects_secondary_and_area_shapes_not_yet_admitted(self):
        text = native_xml(unit_type='KEYE1')
        for old, new in (('Name="SecondApplicationBlocks" Value="0"',
                          'Name="SecondApplicationBlocks" Value="1"'),
                         ('Name="AreaGroupAddress" Value="0xff"',
                          'Name="AreaGroupAddress" Value="0xc"')):
            with self.subTest(new=new):
                with self.assertRaises(ValueError):
                    project_native_xml_unit(text.replace(old, new),
                                            '//CSVTEST/254/p/4', columns=COLUMNS)

    def test_missing_area_group_requires_unperformed_native_mutation(self):
        with self.assertRaisesRegex(ValueError, 'unperformed database mutation'):
            project_native_xml_unit(native_xml(area=13, missing=(13,)),
                                    '//CSVTEST/254/p/4', columns=COLUMNS)
        completed = project_native_xml_unit(native_xml(area=13), '//CSVTEST/254/p/4', columns=COLUMNS)
        self.assertTrue(completed.complete)
        self.assertIn(',Group13,', completed.report.rows[1])

    def test_selected_path_allows_other_units_but_rejects_ambiguity_and_bad_profile(self):
        outcome = project_native_xml_unit(native_xml(extra_unit=True),
                                          '//CSVTEST/254/p/4', columns=('address',))
        self.assertEqual(outcome.report.rows[1], '4,')
        for text, path in ((native_xml(), '//OTHER/254/p/4'),
                           (native_xml(unit_type='KEY4'), '//CSVTEST/254/p/4')):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    project_native_xml_unit(text, path, columns=COLUMNS)

    def test_bounded_loader_rejects_declarations_and_detaches_hash(self):
        raw = native_xml().encode()
        outcome = loads_native_xml_projection(raw, '//CSVTEST/254/p/4', columns=('address',))
        self.assertEqual(len(outcome.xml_sha256), 64)
        with self.assertRaises(ValueError):
            loads_native_xml_projection(b'<!DOCTYPE x><Installation/>',
                                        '//CSVTEST/254/p/4', columns=COLUMNS)

    def test_native_reply_keeps_statusless_multiline_xml_payload(self):
        reply = SimpleNamespace(lines=(
            '343-Begin XML snippet', '347-<?xml version="1.0"?>',
            '<Installation>', '<Project/>', '</Installation>', '344 End XML snippet'))
        self.assertEqual(native_xml_reply_text(reply),
                         '<?xml version="1.0"?>\n<Installation>\n<Project/>\n</Installation>')
        with self.assertRaises(ValueError):
            native_xml_reply_text(SimpleNamespace(lines=('343-Begin XML snippet',
                '347-<Installation>', '342 unexpected', '344 End XML snippet')))


if __name__ == '__main__':
    unittest.main()
