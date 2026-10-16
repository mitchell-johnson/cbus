"""Literal remote reference rules with a complete synthetic project graph."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import UUID, uuid5
from xml.etree import ElementTree as ET

from cbus_toolkit.thermostat_remote_references import (plan_remote_references, project_fingerprint,
    snapshot_project, validate_remote_plan, verify_project_preservation)
from cbus_toolkit.thermostat_templates import ThermostatTemplateError
from cbus_toolkit.unitspec import UnitSpecStore
from test_thermostat_settings import _spec

PATH = '//REMOTE/11/p/20'
RAW = {'ApplicationNumber': '56', 'RemoteSetbackControlSource': '0', 'RemoteSetbackOnGroup': '30',
    'RemoteSetbackOffGroup': '31', 'EvapProgramEnabled': '0', 'NonEvapProgramEnabled': '0',
    'RemoteScheduleEnable': '0', 'RemoteScheduleOnGroup': '32', 'RemoteScheduleOffGroup': '33',
    'RemoteScheduleOverrideGroup': '34', 'PlantCycleTime': '10'}


def oid(name):
    return str(uuid5(UUID('8c32e90e-5bd5-4352-8d1e-fcc5e99e89dc'), name))


def node(parent, kind, address, name='', identity=None):
    row = ET.SubElement(parent, kind)
    for key, value in [('OID', identity or oid(kind + ':' + str(address))), ('Address', address), ('TagName', name)]:
        ET.SubElement(row, key).text = str(value)
    return row


def project(kind='PC_TSA', applications=None, raw=None):
    root = ET.Element('Installation')
    p = node(root, 'Project', 'REMOTE', identity=oid('project'))
    config = ET.SubElement(p, 'Config')
    ET.SubElement(config, 'OID').text = oid('config')
    ET.SubElement(config, 'Property', Name='retain', Value='exact')
    n = node(p, 'Network', 11, identity=oid('network'))
    u = node(n, 'Unit', 20, identity=oid('unit'))
    for key, value in [('UnitType', kind), ('FirmwareVersion', '2.0.00'), ('CatalogNumber', 'synthetic')]:
        ET.SubElement(u, key).text = value
    for name, value in (raw or RAW).items():
        ET.SubElement(u, 'PP', Name=name, Value=value)
    ET.SubElement(u, '{urn:remote:fixture}Opaque', token='keep').text = 'unit metadata Ω'
    sibling = node(n, 'Unit', 21, identity=oid('sibling'))
    ET.SubElement(sibling, 'PP', Name='Opaque', Value='unchanged')
    for app_address, groups in (applications or {}).items():
        app = node(n, 'Application', app_address, 'Retained app', oid('app:' + str(app_address)))
        for address in groups:
            g = node(app, 'NetVar' if app_address == 203 else 'Group', address, 'Retained group',
                     oid(f'group:{app_address}:{address}'))
            level = node(g, 'Level', 7, 'Keep level', oid(f'level:{app_address}:{address}'))
            level.set('Value', '17')
            ET.SubElement(level, '{urn:remote:fixture}Opaque').text = 'preserve'
    return ET.tostring(root, encoding='unicode')


def apply_graph(plan, alias=True):
    root = ET.fromstring(plan.project_xml)
    network = root.find('./Project/Network')
    receipts = {}
    for c in plan.creations:
        identity = oid('new:' + repr(c.key))
        if c.kind == 'Application':
            node(network, 'Application', c.address, c.name, identity)
        else:
            app = next(a for a in network.findall('Application') if a.findtext('Address') == str(c.application))
            node(app, 'NetVar' if alias and c.application == 203 else 'Group', c.address, c.name, identity)
        receipts[c.key] = identity
    for row in network.find('Unit').findall('PP'):
        if row.get('Name') in plan.expected:
            row.set('Value', str(plan.expected[row.get('Name')]))
    return root, receipts


class RemoteReferenceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for family in ('THERMOSTATA', 'THERMOSTATB'):
            (self.folder / (family + '.xml')).write_text(_spec(family, set(RAW)))
        self.store = UnitSpecStore(self.folder)

    def plan(self, kind='PC_TSA', raw=None, edits=None, apps=None):
        raw = dict(RAW) if raw is None else raw
        return plan_remote_references(self.store, kind, raw, edits or {},
            project_xml=project(kind, apps, raw), unit_path=PATH)

    def test_enabled_joint_order_identity_reuse_and_nonremote_composition(self):
        edits = {'RemoteSetbackControlSource': 2, 'RemoteSetbackOnGroup': 21, 'RemoteSetbackOffGroup': 22,
                 'EvapProgramEnabled': 1, 'RemoteScheduleOnGroup': 12, 'RemoteScheduleOffGroup': 13,
                 'RemoteScheduleOverrideGroup': 14, 'PlantCycleTime': 23}
        p = self.plan(edits=edits)
        self.assertEqual([(c.kind, c.application, c.address, c.name) for c in p.creations], [
            ('Application', 203, 203, 'Enable Control'), ('Group', 203, 21, 'Enable Network Variable 21'),
            ('Group', 203, 22, 'Enable Network Variable 22'), ('Group', 203, 12, 'Enable Network Variable 12'),
            ('Group', 203, 13, 'Enable Network Variable 13'), ('Group', 203, 14, 'Enable Network Variable 14')])
        self.assertEqual(p.expected, {k: v for k, v in edits.items() if k != 'PlantCycleTime'} |
                         {'RemoteScheduleEnable': 1, 'NonEvapProgramEnabled': 0})
        self.assertEqual([r['role'] for r in p.as_dict()['getters'] if r['getter'] == 'GroupByAddress'],
                         ['setback_on', 'setback_off', 'schedule_on', 'schedule_off', 'schedule_override'])
        self.assertEqual(validate_remote_plan(self.store, p), p)
        self.assertNotIn('<Installation', json.dumps(p.as_dict()))
        p = self.plan(edits=edits, apps={203: [21, 12]})
        self.assertEqual([(c.application, c.address) for c in p.creations], [(203, 22), (203, 13), (203, 14)])
        self.assertEqual(p.as_dict()['resolved_roles']['setback_on']['identity'], oid('group:203:21'))

    def test_graph_only_disabled_lookup_and_real_unused_group(self):
        raw = dict(RAW, RemoteSetbackControlSource='2', RemoteSetbackOnGroup='21', RemoteSetbackOffGroup='22',
                   EvapProgramEnabled='1', RemoteScheduleEnable='1', RemoteScheduleOnGroup='12',
                   RemoteScheduleOffGroup='13', RemoteScheduleOverrideGroup='14')
        p = self.plan(raw=raw)
        self.assertFalse(p.pp_mutation_required)
        self.assertTrue(p.graph_mutation_required and p.apply_would_mutate)
        self.assertFalse(self.plan(raw=raw, apps={203: [21, 22, 12, 13, 14]}).apply_would_mutate)
        p = self.plan()
        self.assertEqual([(c.kind, c.address) for c in p.creations], [('Application', 203)])
        self.assertFalse(p.pp_mutation_required)
        self.assertEqual([r['create'] for r in p.as_dict()['getters'] if r['getter'] == 'GroupByAddress'], [False] * 3)
        self.assertIsNone(p.as_dict()['resolved_roles']['schedule_on'])
        self.assertEqual(self.plan(apps={203: [255]}).as_dict()['resolved_roles']['schedule_on']['identity'], oid('group:203:255'))
        p = self.plan('PC_TSB', edits={'RemoteSetbackControlSource': 2, 'RemoteSetbackOnGroup': 0, 'RemoteSetbackOffGroup': 255})
        self.assertEqual([c.name for c in p.creations], ['Enable Control', 'Enable Network Variable 0', '<Unused>'])

    def test_all_aliases_source1_and_cross_application_identity(self):
        for kind in ('PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5'):
            with self.subTest(kind=kind):
                p = self.plan(kind, edits={'RemoteSetbackControlSource': 1, 'RemoteSetbackOnGroup': 12,
                                          'RemoteSetbackOffGroup': 255}, apps={56: [12], 203: []})
                self.assertEqual([(c.application, c.address, c.name) for c in p.creations], [(56, 255, '<Unused>')])
                self.assertEqual(p.as_dict()['getters'][0]['getter'], 'ApplicationObject')
                if kind.startswith('PC_TSB'):
                    self.assertNotIn('RemoteScheduleEnable', p.expected)
        p = self.plan(edits={'RemoteSetbackControlSource': 1, 'RemoteSetbackOnGroup': 12, 'RemoteSetbackOffGroup': 13,
            'NonEvapProgramEnabled': 1, 'RemoteScheduleOnGroup': 12, 'RemoteScheduleOffGroup': 13,
            'RemoteScheduleOverrideGroup': 14}, apps={56: [], 203: []})
        self.assertEqual([(c.application, c.address) for c in p.creations], [(56, 12), (56, 13), (203, 12), (203, 13), (203, 14)])
        p = self.plan('PC_TSB', raw=dict(RAW, ApplicationNumber='203'), edits={
            'RemoteSetbackControlSource': 1, 'RemoteSetbackOnGroup': 12, 'RemoteSetbackOffGroup': 13}, apps={203: []})
        self.assertEqual(p.as_dict()['getters'][0]['getter'], 'ApplicationObject')

    def test_program_normalization_and_form_validation(self):
        for evap, nonevap, enabled in [(0, 0, 0), (2, 0, 0), (1, 0, 1), (0, 2, 1), (255, 255, 1)]:
            with self.subTest(evap=evap, nonevap=nonevap):
                p = self.plan(raw=dict(RAW, EvapProgramEnabled=str(evap), NonEvapProgramEnabled=str(nonevap),
                    RemoteScheduleEnable='255', RemoteScheduleOnGroup='12', RemoteScheduleOffGroup='13', RemoteScheduleOverrideGroup='14'))
                self.assertEqual((p.expected['RemoteScheduleEnable'], p.expected['EvapProgramEnabled'],
                    p.expected['NonEvapProgramEnabled']), (enabled, int(evap == 1), int(nonevap > 0)))
                self.assertEqual(tuple(p.expected[n] for n in ('RemoteScheduleOnGroup', 'RemoteScheduleOffGroup',
                    'RemoteScheduleOverrideGroup')), (12, 13, 14) if enabled else (32, 33, 34))
        cases = [
            {'RemoteSetbackControlSource': 3},
            {'RemoteSetbackControlSource': 2, 'RemoteSetbackOnGroup': 12, 'RemoteSetbackOffGroup': 12},
            {'RemoteSetbackControlSource': 2, 'RemoteSetbackOnGroup': 255, 'RemoteSetbackOffGroup': 255},
            {'EvapProgramEnabled': 1, 'RemoteScheduleOnGroup': 12, 'RemoteScheduleOffGroup': 12, 'RemoteScheduleOverrideGroup': 255},
            {'EvapProgramEnabled': 1, 'RemoteScheduleOnGroup': 12, 'RemoteScheduleOffGroup': 13, 'RemoteScheduleOverrideGroup': 255},
            {'RemoteSetbackControlSource': 2, 'RemoteSetbackOnGroup': 12, 'RemoteSetbackOffGroup': 15,
             'EvapProgramEnabled': 1, 'RemoteScheduleOnGroup': 12, 'RemoteScheduleOffGroup': 13, 'RemoteScheduleOverrideGroup': 14},
            {'RemoteScheduleEnable': 1}, {'RemoteSetbackControlSource': True}, {'RemoteSetbackOnGroup': 1.0},
            {'RemoteSetbackOnGroup': 256}, {'ApplicationNumber': 56}]
        for edits in cases:
            with self.subTest(edits=edits), self.assertRaises(ThermostatTemplateError):
                self.plan(edits=edits)
        with self.assertRaisesRegex(ThermostatTemplateError, 'to exist'):
            self.plan(edits={'RemoteSetbackControlSource': 1})
        with self.assertRaises(ThermostatTemplateError):
            self.plan('PC_TSB', edits={'RemoteScheduleOnGroup': 12})

    def test_strict_replay_schema_and_complete_graph_admission(self):
        p = self.plan(edits={'EvapProgramEnabled': 1})
        for broken in [replace(p, owned_values=p.owned_values + (('PlantCycleTime', 77),)), replace(p, creations=()),
                       replace(p, getters_json='[]'), replace(p, graph=replace(p.graph, all_oids=()))]:
            with self.subTest(tamper=broken), self.assertRaises(ThermostatTemplateError):
                validate_remote_plan(self.store, broken)
        with self.assertRaisesRegex(ThermostatTemplateError, 'Stored project PP differs'):
            plan_remote_references(self.store, 'PC_TSA', dict(RAW, RemoteSetbackOnGroup='99'), {},
                                   project_xml=project(), unit_path=PATH)
        for mutation in ('duplicate-app', 'duplicate-group', 'duplicate-oid', 'missing-oid', 'identity', 'other-network'):
            root = ET.fromstring(project(applications={56: [12]}))
            network = root.find('./Project/Network')
            if mutation == 'duplicate-app':
                node(network, 'Application', 56, identity=oid('other-app'))
            elif mutation == 'duplicate-group':
                node(network.find('Application'), 'Group', 12, identity=oid('other-group'))
            elif mutation == 'duplicate-oid':
                network.find('Application/OID').text = oid('unit')
            elif mutation == 'missing-oid':
                sibling = network.findall('Unit')[1]; sibling.remove(sibling.find('OID'))
            elif mutation == 'identity':
                network.find('Unit/UnitType').text = 'PC_TSB'
            else:
                other = node(root.find('Project'), 'Network', 12, identity=oid('other-network'))
                node(other, 'Application', 56, identity=oid('app:other:1'))
                node(other, 'Application', 56, identity=oid('app:other:2'))
            with self.subTest(mutation=mutation), self.assertRaises(ThermostatTemplateError):
                plan_remote_references(self.store, 'PC_TSA', RAW, {}, project_xml=ET.tostring(root, encoding='unicode'), unit_path=PATH)
        text = (self.folder / 'THERMOSTATA.xml').read_text().replace('<Type>THERMOSTATA</Type>', '<Type>OTHER</Type>')
        (self.folder / 'THERMOSTATA.xml').write_text(text)
        with self.assertRaises(ThermostatTemplateError):
            plan_remote_references(UnitSpecStore(self.folder), 'PC_TSA', RAW, {}, project_xml=project(), unit_path=PATH)

    def test_firmware_bounds_replayed_and_project_oid_export_omission(self):
        p = self.plan()
        spec = self.folder / 'THERMOSTATA.xml'
        original = spec.read_text()
        for maximum in ('1', '8'):
            spec.write_text(original.replace('<MaxVersion>9</MaxVersion>', '<MaxVersion>' + maximum + '</MaxVersion>'))
            with self.subTest(maximum=maximum), self.assertRaises(ThermostatTemplateError):
                validate_remote_plan(UnitSpecStore(self.folder), p)
        root = ET.fromstring(p.project_xml)
        project_node = root.find('Project')
        project_node.remove(project_node.find('OID'))
        graph = snapshot_project(ET.tostring(root, encoding='unicode'), PATH)
        self.assertNotIn(oid('project'), graph.all_oids)
        ET.SubElement(project_node, 'OID').text = oid('unit')
        with self.assertRaises(ThermostatTemplateError):
            snapshot_project(ET.tostring(root, encoding='unicode'), PATH)

    def test_full_preservation_allows_only_owned_changes_and_pp_order(self):
        p = self.plan(edits={'RemoteSetbackControlSource': 2, 'RemoteSetbackOnGroup': 21,
                            'RemoteSetbackOffGroup': 255, 'EvapProgramEnabled': 1}, apps={56: [12]})
        root, receipts = apply_graph(p)
        unit = root.find('./Project/Network/Unit')
        rows = unit.findall('PP')
        for row in rows:
            unit.remove(row)
        for row in sorted(rows, key=lambda r: r.get('Name')):
            unit.append(row)
        root.find('./Project/Config/OID').text = oid('config-reloaded')
        ET.SubElement(root.find('./Project/Network/Application/Group/Level'), 'TagsDLT')
        after = ET.tostring(root, encoding='unicode')
        self.assertTrue(verify_project_preservation(p.project_xml, after, PATH,
            changed_parameters=p.expected, created_oids=receipts)['preserved'])
        for mutation in ('group-tag', 'level-value', 'opaque', 'unrelated-pp', 'pp-extra-attribute',
                         'owned-pp-attribute', 'new-level', 'new-group'):
            root = ET.fromstring(after)
            app = root.find('./Project/Network/Application')
            if mutation == 'group-tag':
                app.find('Group/TagName').text = 'tampered'
            elif mutation == 'level-value':
                app.find('Group/Level').set('Value', '19')
            elif mutation == 'opaque':
                app.find('Group/Level/{urn:remote:fixture}Opaque').text = 'changed'
            elif mutation in ('unrelated-pp', 'pp-extra-attribute'):
                row = root.find('./Project/Network/Unit/PP[@Name="PlantCycleTime"]')
                row.set('Value' if mutation == 'unrelated-pp' else 'Opaque', '12')
            elif mutation == 'owned-pp-attribute':
                root.find('./Project/Network/Unit/PP[@Name="RemoteSetbackOnGroup"]').set('Opaque', 'changed')
            else:
                target = next(a for a in root.findall('./Project/Network/Application') if a.findtext('Address') == '203')
                node(target.find('NetVar') if mutation == 'new-level' else target,
                     'Level' if mutation == 'new-level' else 'NetVar', 200, identity=oid('unexpected'))
            with self.subTest(mutation=mutation), self.assertRaises(ThermostatTemplateError):
                verify_project_preservation(p.project_xml, ET.tostring(root, encoding='unicode'), PATH,
                                            changed_parameters=p.expected, created_oids=receipts)
        changed = ET.fromstring(p.project_xml)
        changed.find('./Project/Network/Application/Group/TagName').text = 'different'
        self.assertNotEqual(project_fingerprint(p.project_xml, PATH), project_fingerprint(ET.tostring(changed, encoding='unicode'), PATH))
        self.assertEqual(len(snapshot_project(p.project_xml, PATH).all_oids), 7)

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_TOOLKIT_MAP'),
                         'Explicit original EXE/MAP required for static source verification')
    def test_optional_static_source(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'research'))
        from thermostat_remote_references_static import inspect
        result = inspect(Path(os.environ['CBUS_TOOLKIT_EXE']), Path(os.environ['CBUS_TOOLKIT_MAP']))
        self.assertFalse(result['original_executed'])
        self.assertFalse(result['physical_io'])
        self.assertTrue(all(result['checks'].values()))
