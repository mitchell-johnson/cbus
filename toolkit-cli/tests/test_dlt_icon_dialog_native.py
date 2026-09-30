"""Closed-network original C-Gate persistence for the bounded ICON dialog.

Original action/collection evidence is separate. These synthetic database
observations establish storage, not the original UI or icon rendering.
"""
import json
import os
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from cbus_toolkit.dlt_icon_dialog import plan_icon_dialog
from cbus_toolkit.dlt_project_labels import show_project_labels
from test_macros import NATIVE, NATIVE_REASON, closed_network_project, native_endpoint


def labels(view):
    return [(row['language_id'], row['variant'], row['tag_type'], row['text']) for row in view['labels']]


def add_tag(parent, language, variant, kind, value):
    tag = ET.SubElement(parent, 'TagDLT')
    for name, field in (('LanguageID', str(language)), ('FlavourID', str(variant)),
                        ('TagType', kind), ('TagValue', value)):
        ET.SubElement(tag, name).text = field


@unittest.skipUnless(NATIVE, NATIVE_REASON)
class NativeIconDialogTests(unittest.TestCase):
    def test_icon_action_type_changes_and_whole_language_survive_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import xml_text
        from research.local_cgate import JAR_SHA256, service_backend
        if service_backend() != 'local':
            self.skipTest('ICON dialog oracle requires the owned local native backend')
        report = {'format': 'cbus-classic-dlt-icon-dialog-native-v1', 'passed': False,
                  'scope': 'Owned original C-Gate synthetic database XML only',
                  'cgate_jar_sha256': JAR_SHA256, 'original_full_dialog_executed': False,
                  'original_collection_executed': False, 'physical_hardware_verified': False,
                  'icon_rendering_verified': False, 'network_opened': False, 'cases': []}
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=30) as client, \
                closed_network_project(client, 'IC') as project:
            database = NativeDatabase(client)
            network = f'//{project}/254'
            seed = ET.fromstring(xml_text(database.get(network, xml=True)))
            language_nodes = ET.SubElement(seed, 'Languages')
            for number, value in ((0, '1'), (1, 'English'), (202, 'Pictograms')):
                language = ET.SubElement(language_nodes, 'Language')
                ET.SubElement(language, 'ID').text = str(number)
                ET.SubElement(language, 'TagValue').text = value
            applications = {}
            for app in (56, 202):
                application = ET.SubElement(seed, 'Application')
                ET.SubElement(application, 'TagName').text = f'Application {app}'
                ET.SubElement(application, 'Address').text = str(app)
                applications[app] = application
            for app, address in ((56, 20), (202, 7)):
                node = ET.SubElement(applications[app], 'Group')
                ET.SubElement(node, 'TagName').text = f'Group {address}'
                ET.SubElement(node, 'Address').text = str(address)
                if app == 202:
                    node = ET.SubElement(node, 'Level', Value='43')
                    ET.SubElement(node, 'TagName').text = 'Action 42'
                    ET.SubElement(node, 'Address').text = '42'
                tags = ET.SubElement(node, 'TagsDLT')
                add_tag(tags, 202, 0, 'TEXT', '1')
                add_tag(tags, 202, 2, 'ICON', '')
                add_tag(tags, 202, 4, 'TEXT', 'Other selected text exceeds twenty units')
                add_tag(tags, 1, 2, 'FONT', 'Foreign font context is preserved exactly')
                add_tag(tags, 202, 5, 'DYNAMIC', 'Out-of-range variant remains opaque')
            for address in (21, 22):
                node = ET.SubElement(applications[56], 'Group')
                ET.SubElement(node, 'TagName').text = f'Group {address}'
                ET.SubElement(node, 'Address').text = str(address)
                if address == 22:
                    tags = ET.SubElement(node, 'TagsDLT')
                    add_tag(tags, 202, 0, 'ICON', '91')
                    add_tag(tags, 202, 1, 'TEXT', '1')
            self.assertEqual(database.set_xml(network, ET.tostring(seed, encoding='unicode')).code, 301)
            project_xml = lambda: xml_text(database.get('//' + project, xml=True))
            finals = {}
            for target in (network + '/56/20', network + '/202/7/42'):
                before_xml = project_xml()
                before = show_project_labels(before_xml, target)
                old_oids = {(row['language_id'], row['variant']): row['oid'] for row in before['labels']}
                plan = plan_icon_dialog(before_xml, target, 202, 3, 91)
                candidate = show_project_labels(plan.candidate_xml, target)
                self.assertEqual(labels(candidate), [
                    ('202', '0', 'TEXT', '1'),
                    ('202', '4', 'TEXT', 'Other selected text '),
                    ('1', '2', 'FONT', 'Foreign font context is preserved exactly'),
                    ('202', '5', 'DYNAMIC', 'Out-of-range variant remains opaque'),
                    ('202', '3', 'ICON', '91'),
                ])
                self.assertEqual(database.set_xml(target, plan.target_xml).code, 301)
                native = show_project_labels(project_xml(), target)
                self.assertEqual(labels(native), labels(candidate))
                for row in native['labels']:
                    key = (row['language_id'], row['variant'])
                    self.assertTrue(row['oid'])
                    if key in old_oids:
                        self.assertEqual(row['oid'], old_oids[key])
                self.assertEqual(native['network_languages'], before['network_languages'])
                # UI flavour1 resolves legacy0; the value is already "1", so
                # this must still persist the TEXT -> ICON type-only change.
                converted = plan_icon_dialog(project_xml(), target, 202, 1, 1)
                self.assertEqual(database.set_xml(target, converted.target_xml).code, 301)
                current = show_project_labels(project_xml(), target)
                first = next(row for row in current['labels'] if row['language_id'] == '202' and row['variant'] == '0')
                self.assertEqual((first['tag_type'], first['text'], first['oid']), ('ICON', '1', old_oids[('202', '0')]))
                finals[target] = current
                report['cases'].append({'kind': current['kind'], 'set_status': 301,
                    'legacy_zero_oid_retained': True, 'same_value_type_change_persisted': True,
                    'empty_icon_alternate_deleted': True, 'other_selected_text_normalized': True,
                    'builtin_icon_created': 91, 'foreign_font_and_out_of_range_dynamic_preserved': True,
                    'network_languages_preserved': True})
            target = network + '/56/21'
            fresh = plan_icon_dialog(project_xml(), target, 202, 2, 91)
            self.assertEqual(database.set_xml(target, fresh.target_xml).code, 301)
            current = show_project_labels(project_xml(), target)
            self.assertEqual(labels(current), [('202', '2', 'ICON', '91')])
            self.assertTrue(current['labels'][0]['oid'])
            finals[target] = current
            report['cases'].append({'kind': 'Group', 'missing_first_icon_stays_absent': True,
                                    'owner_display_context_not_required': True, 'builtin_icon_created': 91})
            target = network + '/56/22'
            before = show_project_labels(project_xml(), target)
            exact = plan_icon_dialog(project_xml(), target, 202, 1, 91)
            self.assertEqual(database.set_xml(target, exact.target_xml).code, 301)
            current = show_project_labels(project_xml(), target)
            self.assertEqual(labels(current), [('202', '0', 'ICON', '91'), ('202', '1', 'ICON', '91')])
            self.assertEqual([row['oid'] for row in current['labels']], [row['oid'] for row in before['labels']])
            finals[target] = current
            report['cases'].append({'kind': 'Group', 'exact_first_selected_over_legacy': True,
                                    'shadowed_legacy_unchanged': True, 'both_oids_retained': True})
            for command in ('PROJECT SAVE ', 'PROJECT CLOSE ', 'PROJECT LOAD ', 'PROJECT USE '):
                client.command(command + project)
            for target, expected in finals.items():
                reloaded = show_project_labels(project_xml(), target)
                self.assertEqual(reloaded['labels'], expected['labels'])
                self.assertEqual(reloaded['network_languages'], expected['network_languages'])
            level = next(ET.fromstring(project_xml()).iter('Level'))
            self.assertEqual((level.findtext('Address'), level.get('Value')), ('42', '43'))
            report['action_address_and_value_preserved'] = True
            report['project_save_close_reload_passed'] = True
            report['passed'] = True
        if os.environ.get('CBUS_DLT_ICON_DIALOG_REPORT'):
            Path(os.environ['CBUS_DLT_ICON_DIALOG_REPORT']).write_text(json.dumps(report, indent=2) + '\n')
