"""Guarded native missing-Area creation tests."""
import unittest
import xml.etree.ElementTree as ET

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.toolkit_database_csv import COLUMNS
from cbus_toolkit.toolkit_database_csv_area import (
    MissingAreaGroupError,
    NativeCSVAreaGroups,
    plan_missing_area_group,
)
from cbus_toolkit.toolkit_database_csv_native import project_native_xml_unit
from tests.test_toolkit_database_csv_native import native_xml, oid


def reply(code=200, message='OK.'):
    separator = ' '
    line = str(code) + separator + message
    return CGateResponse((line,), line, code)


class AreaClient:
    def __init__(self):
        self.commands = []
        self.created = False
        self.connected = True
        self.backups = set()
        self.saves = 0
        self.fail_save = False

    def xml(self):
        root = ET.fromstring(native_xml(area=13, missing=(13,)))
        if self.created:
            app = root.find('.//Application')
            group = ET.SubElement(app, 'Group')
            for name, value in (('OID', oid(913)), ('TagName', 'Group 13'), ('Address', 13)):
                ET.SubElement(group, name).text = str(value)
        return ET.tostring(root, encoding='unicode')

    def command(self, command):
        self.commands.append(command)
        if command == 'DBGETXML //CSVTEST':
            text = self.xml()
            return CGateResponse(('343-Begin XML snippet', '347-' + text,
                                  '344 End XML snippet'), '344 End XML snippet', 344)
        if command == 'PROJECT SAVE CSVTEST':
            self.saves += 1
            if self.fail_save and self.saves == 2:
                raise OSError('save failed')
            return reply()
        if command.startswith('PROJECT COPY CSVTEST '):
            backup = command.rsplit(' ', 1)[1]
            if backup in self.backups:
                return reply(400, 'exists')
            self.backups.add(backup)
            return reply()
        if command == 'DBADDSAFE //CSVTEST/254/56 Group 13 Group 13':
            if self.created:
                return reply(400, 'exists')
            self.created = True
            return reply(301, 'OID=' + oid(913))
        if command == 'DBDELETE //CSVTEST/254/56/13':
            self.created = False
            return reply()
        if command in ('PROJECT USE CSVTEST', 'PROJECT CLOSE CSVTEST', 'PROJECT LOAD CSVTEST'):
            return reply()
        raise AssertionError(command)


class MissingAreaGroupTests(unittest.TestCase):
    def test_plan_admits_only_exact_archived_b03_shape(self):
        text = native_xml(area=13, missing=(13,))
        plan = plan_missing_area_group(text, '//CSVTEST/254/p/4')
        self.assertEqual((plan.application, plan.address, plan.tag), (56, 13, 'Group 13'))
        self.assertEqual(len(plan.source_network_sha256), 64)
        for changed in (text.replace('OwnedUnit', 'Other', 1),
                        text.replace('Group12', 'Area', 1), native_xml(area=12)):
            with self.subTest():
                with self.assertRaises(ValueError):
                    plan_missing_area_group(changed, '//CSVTEST/254/p/4')

    def test_apply_backs_up_adds_saves_reloads_and_projects_area13(self):
        client = AreaClient(); manager = NativeCSVAreaGroups(client)
        result = manager.apply(manager.plan('//CSVTEST/254/p/4'), backup_project='BACKUP')
        self.assertTrue(result.as_dict()['reload_verified'])
        self.assertEqual(result.group_oid, oid(913))
        projected = project_native_xml_unit(result.final_xml, '//CSVTEST/254/p/4', columns=COLUMNS)
        self.assertTrue(projected.complete)
        self.assertIn(',Group 13,', projected.report.rows[1])
        self.assertEqual(client.commands.count('DBADDSAFE //CSVTEST/254/56 Group 13 Group 13'), 1)
        self.assertLess(client.commands.index('PROJECT COPY CSVTEST BACKUP'),
                        client.commands.index('DBADDSAFE //CSVTEST/254/56 Group 13 Group 13'))
        self.assertEqual(client.commands.count('PROJECT SAVE CSVTEST'), 2)
        self.assertEqual(client.commands[-2:], ['PROJECT LOAD CSVTEST', 'DBGETXML //CSVTEST'])

    def test_save_failure_removes_created_group_and_restores_source(self):
        client = AreaClient(); client.fail_save = True
        manager = NativeCSVAreaGroups(client); plan = manager.plan('//CSVTEST/254/p/4')
        with self.assertRaises(MissingAreaGroupError) as caught:
            manager.apply(plan, backup_project='BACKUP')
        self.assertTrue(caught.exception.details['mutation_attempted'])
        self.assertEqual(caught.exception.details['rollback_errors'], [])
        self.assertFalse(client.created)
        restored = plan_missing_area_group(client.xml(), '//CSVTEST/254/p/4')
        self.assertEqual(restored.source_network_sha256, plan.source_network_sha256)
        self.assertEqual(client.commands.count('DBDELETE //CSVTEST/254/56/13'), 1)


if __name__ == '__main__':
    unittest.main()
