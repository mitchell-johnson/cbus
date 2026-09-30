"""Native database persistence oracle for the separate classic TEXT dialog plan.

This verifies C-Gate XML behavior, not execution of the original language
collection or full original dialog. Those source/instruction receipts are
separate from this synthetic, closed-network database comparison.
"""
import json
import os
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from cbus_toolkit.dlt_language_dialog import plan_language_dialog
from cbus_toolkit.dlt_project_labels import show_project_labels
from test_macros import NATIVE, NATIVE_REASON, closed_network_project, native_endpoint


def labels(view):
    return [(row['language_id'], row['variant'], row['tag_type'], row['text']) for row in view['labels']]


@unittest.skipUnless(NATIVE, NATIVE_REASON)
class NativeLanguageDialogTests(unittest.TestCase):
    def test_legacy_identity_deletion_normalization_and_native_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import xml_text
        from research.local_cgate import JAR_SHA256
        report = {'format': 'cbus-classic-dlt-language-dialog-native-v1', 'passed': False,
                  'scope': 'Owned original C-Gate synthetic database XML only',
                  'cgate_jar_sha256': JAR_SHA256, 'original_full_dialog_executed': False,
                  'original_collection_executed': False, 'physical_hardware_verified': False, 'cases': []}
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=30) as client, \
                closed_network_project(client, 'DT') as project:
            database = NativeDatabase(client)
            network = f'//{project}/254'
            seed = ET.fromstring(xml_text(database.get(network, xml=True)))
            language_nodes = ET.SubElement(seed, 'Languages')
            for number, value in ((0, '1'), (1, 'English'), (2, 'French')):
                language = ET.SubElement(language_nodes, 'Language')
                ET.SubElement(language, 'ID').text = str(number)
                ET.SubElement(language, 'TagValue').text = value
            for app, group in ((56, 20), (202, 7)):
                application = ET.SubElement(seed, 'Application')
                ET.SubElement(application, 'TagName').text = f'Application {app}'
                ET.SubElement(application, 'Address').text = str(app)
                node = ET.SubElement(application, 'Group')
                ET.SubElement(node, 'TagName').text = f'Group {group}'
                ET.SubElement(node, 'Address').text = str(group)
                if app == 202:
                    node = ET.SubElement(node, 'Level', Value='43')
                    ET.SubElement(node, 'TagName').text = 'Action 42'
                    ET.SubElement(node, 'Address').text = '42'
                tags = ET.SubElement(node, 'TagsDLT')
                for lang, flavour, value in ((1, 0, 'Legacy first variant exceeds twenty units'),
                                              (1, 2, ''), (1, 4, 'Fourth variant also exceeds twenty units'),
                                              (2, 2, 'Unselected language retains this entire long text')):
                    tag = ET.SubElement(tags, 'TagDLT')
                    for key, field in (('LanguageID', str(lang)), ('FlavourID', str(flavour)),
                                       ('TagType', 'TEXT'), ('TagValue', value)):
                        ET.SubElement(tag, key).text = field
            self.assertEqual(database.set_xml(network, ET.tostring(seed, encoding='unicode')).code, 301)
            project_xml = lambda: xml_text(database.get('//' + project, xml=True))
            finals = {}
            for target in (network + '/56/20', network + '/202/7/42'):
                before_xml = project_xml()
                before = show_project_labels(before_xml, target)
                previous_oids = {(r['language_id'], r['variant']): r['oid'] for r in before['labels']}
                plan = plan_language_dialog(before_xml, target, 1, 3, '')
                candidate = show_project_labels(plan.candidate_xml, target)
                self.assertEqual(labels(candidate), [
                    ('1', '0', 'TEXT', 'Legacy first variant'),
                    ('1', '4', 'TEXT', 'Fourth variant also '),
                    ('2', '2', 'TEXT', 'Unselected language retains this entire long text'),
                    ('1', '3', 'TEXT', '<Default>'),
                ])
                self.assertEqual(database.set_xml(target, plan.target_xml).code, 301)
                native = show_project_labels(project_xml(), target)
                self.assertEqual(labels(native), labels(candidate))
                for row in native['labels']:
                    key = (row['language_id'], row['variant'])
                    self.assertTrue(row['oid'])
                    if key in previous_oids:
                        self.assertEqual(row['oid'], previous_oids[key])
                self.assertNotIn(('1', '2'), {(r['language_id'], r['variant']) for r in native['labels']})
                self.assertEqual(native['network_languages'], before['network_languages'])
                # Confirmed Unicode is truncated by UTF-16 units, retaining a
                # complete astral pair at the boundary. Legacy flavour0 is the
                # original finalization target for UI flavour1.
                unicode_text = '123456789012345678😀tail'
                unicode_plan = plan_language_dialog(project_xml(), target, 1, 1, unicode_text,
                                                     confirm_non_latin1=True)
                self.assertEqual(database.set_xml(target, unicode_plan.target_xml).code, 301)
                current = show_project_labels(project_xml(), target)
                first = next(r for r in current['labels'] if r['language_id'] == '1' and r['variant'] == '0')
                self.assertEqual(first['text'], '123456789012345678😀')
                self.assertEqual(first['oid'], previous_oids[('1', '0')])
                finals[target] = current
                report['cases'].append({'kind': current['kind'], 'set_status': 301,
                    'legacy_zero_oid_retained': True, 'empty_alternate_deleted': True,
                    'text_empty_input_saved_as_default': True, 'all_selected_alternates_finalized': True,
                    'other_language_preserved': True, 'network_languages_preserved': True,
                    'utf16_twenty_unit_boundary_preserved': True})
            for command in ('PROJECT SAVE ', 'PROJECT CLOSE ', 'PROJECT LOAD ', 'PROJECT USE '):
                client.command(command + project)
            for target, expected in finals.items():
                reloaded = show_project_labels(project_xml(), target)
                self.assertEqual(reloaded['labels'], expected['labels'])
                self.assertEqual(reloaded['network_languages'], expected['network_languages'])
            root = ET.fromstring(project_xml())
            level = next(root.iter('Level'))
            self.assertEqual((level.findtext('Address'), level.get('Value')), ('42', '43'))
            report['action_address_and_value_preserved'] = True
            report['project_save_close_reload_passed'] = True
            report['passed'] = True
        if os.environ.get('CBUS_DLT_DIALOG_REPORT'):
            Path(os.environ['CBUS_DLT_DIALOG_REPORT']).write_text(json.dumps(report, indent=2) + '\n')
