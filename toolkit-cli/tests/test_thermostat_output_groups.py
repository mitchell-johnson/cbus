"""Literal ordinary output-group load, selection and graph-preservation cases."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

from cbus_toolkit.thermostat_remote_references import (RemoteCreation, RemoteGroupRename,
    plan_remote_references, validate_remote_plan, verify_project_preservation)
from cbus_toolkit.thermostat_templates import ThermostatTemplateError
from cbus_toolkit.thermostat_post_load import _default_name
from cbus_toolkit.unitspec import UnitSpecStore
from test_thermostat_remote_references import RAW, PATH, project, node, oid
from test_thermostat_settings import _spec


FIELDS = ('CoolActivationOutput', 'CoolStage1Output', 'CoolStage2Output', 'CoolStage3Output',
    'CoolFanLowOutput', 'CoolFanMediumOutput', 'CoolFanHighOutput', 'HeatActivationOutput',
    'HeatStage1Output', 'HeatStage2Output', 'HeatStage3Output', 'HeatFanLowOutput',
    'HeatFanMediumOutput', 'HeatFanHighOutput', 'DamperZone1Output', 'DamperZone2Output',
    'DamperZone3Output', 'DamperZone4Output', 'InternalRelay1GroupNumber', 'InternalRelay2GroupNumber',
    'InternalRelay3GroupNumber', 'InternalRelay4GroupNumber', 'InternalRelay5GroupNumber')


def raw_values(**changes):
    values = dict(RAW, **{name: '255' for name in FIELDS})
    values.update(ZoneGroup='7', InstallationCode='1', ControlledZones='3',
                  InternalPlantType='3', InternalPlantZones='3')
    return values | {name: str(value) for name, value in changes.items()}


def seed(kind='PC_TSA5', raw=None, apps=None):
    raw = raw_values() if raw is None else raw
    apps = {56: {255: '<Unused>'}, 203: {}, 172: {7: 'Existing zone'}} if apps is None else apps
    root = ET.fromstring(project(kind, {app: list(groups) for app, groups in apps.items()}, raw))
    for application in root.findall('./Project/Network/Application'):
        address = int(application.findtext('Address'))
        for group in list(application):
            if group.tag in ('Group', 'NetVar'):
                group.find('TagName').text = apps[address][int(group.findtext('Address'))]
                group.set('Opaque', 'retain group attributes')
                ET.SubElement(group, 'Description').text = 'retain description'
    return ET.tostring(root, encoding='unicode')


def materialize(plan):
    root = ET.fromstring(plan.project_xml)
    network = root.find('./Project/Network')
    receipts = {}
    for row in plan.graph_operations:
        if type(row) is RemoteCreation:
            identity = oid('output-created:' + repr(row.key))
            if row.kind == 'Application':
                node(network, 'Application', row.address, row.name, identity)
            else:
                app = next(app for app in network.findall('Application')
                           if int(app.findtext('Address')) == row.application)
                node(app, 'NetVar' if row.application == 203 else 'Group', row.address, row.name, identity)
            receipts[row.key] = identity
        else:
            app = next(app for app in network.findall('Application')
                       if int(app.findtext('Address')) == row.application)
            group = next(group for group in app if group.tag in ('Group', 'NetVar')
                         and int(group.findtext('Address')) == row.address)
            group.find('TagName').text = row.name
    for pp in network.find('Unit').findall('PP'):
        if pp.get('Name') in plan.expected:
            pp.set('Value', str(plan.expected[pp.get('Name')]))
    return root, receipts


class OutputGroupTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for family in ('THERMOSTATA', 'THERMOSTATB'):
            (self.folder / (family + '.xml')).write_text(_spec(family, set(raw_values())))
        self.store = UnitSpecStore(self.folder)

    def plan(self, *, kind='PC_TSA5', raw=None, apps=None, selections=(), edits=None, xml=None):
        raw = raw_values() if raw is None else raw
        return plan_remote_references(self.store, kind, raw, edits or {},
            project_xml=xml or seed(kind, raw, apps), unit_path=PATH, output_selections=selections)

    def test_all_aliases_empty_history_ordinary_load_and_old_profile(self):
        for kind in ('PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5'):
            with self.subTest(kind=kind):
                p = self.plan(kind=kind)
                self.assertEqual(p.output_expected, {name: 255 for name in FIELDS})
                self.assertFalse(p.apply_would_mutate)
                self.assertEqual(validate_remote_plan(self.store, p), p)
                self.assertEqual(p.as_dict()['output_selections'], [])
                view = p.as_dict()['output_projection']
                self.assertEqual(view['prefix'], '[CG07]')
                self.assertEqual(view['selectors_enabled']['InternalRelay1GroupNumber'], kind.endswith('5'))
                self.assertEqual(view['selectors_enabled']['DamperZone1Output'], kind.startswith('PC_TSA'))
        old = self.plan(selections=None, raw=dict(RAW), apps={203: {}})
        self.assertIsNone(old.as_dict()['output_projection'])
        self.assertEqual(old.output_expected, {})

    def test_shared_graph_getter_and_mutation_order(self):
        raw = raw_values(ApplicationNumber=203, RemoteSetbackControlSource=2,
            RemoteSetbackOnGroup=21, RemoteSetbackOffGroup=22, CoolStage1Output=40,
            HeatStage1Output=41, InternalRelay1GroupNumber=44, EvapProgramEnabled=1,
            RemoteScheduleOnGroup=12, RemoteScheduleOffGroup=13, RemoteScheduleOverrideGroup=14)
        p = self.plan(raw=raw, apps={203: {}})
        self.assertEqual([(c.kind, c.application, c.address, c.name) for c in p.creations], [
            ('Application', 172, 172, 'Air Conditioning'), ('Group', 172, 7, 'Communication Group 7'),
            ('Group', 203, 21, 'Enable Network Variable 21'), ('Group', 203, 22, 'Enable Network Variable 22'),
            ('Group', 203, 255, '<Unused>'), ('Group', 203, 40, '[CG07] Y (heat/cool)'),
            ('Group', 203, 44, 'Enable Network Variable 44'), ('Group', 203, 12, 'Enable Network Variable 12'),
            ('Group', 203, 13, 'Enable Network Variable 13'), ('Group', 203, 14, 'Enable Network Variable 14')])
        self.assertEqual(p.output_expected['CoolStage1Output'], 40)
        self.assertEqual(p.output_expected['HeatStage1Output'], 40)
        roles = [row['role'] for row in p.as_dict()['getters'] if row['getter'] == 'GroupByAddress']
        self.assertLess(roles.index('setback_off'), roles.index('CoolActivation'))
        self.assertLess(roles.index('InternalRelay5'), roles.index('schedule_on'))
        root, receipts = materialize(p)
        self.assertTrue(verify_project_preservation(p.project_xml, ET.tostring(root, encoding='unicode'), PATH,
            changed_parameters=p.expected, created_oids=receipts, graph_operations=p.graph_operations)['preserved'])

    def test_all_fields_loaded_owned_and_selected_in_one_history(self):
        raw = raw_values(**dict(zip(FIELDS, range(30, 53))))
        apps = {56: {address: 'Existing ' + str(address) for address in range(30, 53)},
                172: {7: 'Zone'}, 203: {}}
        apps[56].update({address: 'Selected ' + str(address) for address in range(100, 123)})
        p = self.plan(raw=raw, apps=apps,
            selections=[{'parameter': name, 'address': address} for name, address in zip(FIELDS, range(100, 123))])
        self.assertEqual(p.output_expected, dict(zip(FIELDS, range(100, 123))))
        self.assertEqual(len(p.as_dict()['output_projection']['selections']), 23)
        self.assertEqual(p.graph_operations, ())
        self.assertEqual(p.as_dict()['output_projection']['loaded_references']['InternalRelay5GroupNumber']['address'], 52)
        for kind in ('PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5'):
            with self.subTest(kind=kind):
                p = self.plan(kind=kind, raw=raw, apps=apps)
                expected = dict(zip(FIELDS, range(30, 53)))
                if kind.startswith('PC_TSB'):
                    expected.update({name: 255 for name in FIELDS[14:18]})
                self.assertEqual(p.output_expected, expected)
                self.assertEqual(p.graph_operations, ())

    def test_missing_application_catalogue_and_actual_zone_group_prerequisite(self):
        for application, name in ((48, '48'), (49, '49'), (56, 'Lighting'), (94, '94'),
                                  (95, 'DALI'), (203, 'Enable Control')):
            with self.subTest(application=application):
                p = self.plan(kind='PC_TSB5', raw=raw_values(ApplicationNumber=application, ZoneGroup=255), apps={})
                self.assertEqual([(c.kind, c.application, c.address, c.name) for c in p.creations], [
                    ('Application', 172, 172, 'Air Conditioning'), ('Group', 172, 255, '<Unused>'),
                    ('Application', application, application, name), ('Group', application, 255, '<Unused>')])
                self.assertEqual(p.as_dict()['output_projection']['prefix'], '[CG255]')
                root, receipts = materialize(p)
                self.assertTrue(verify_project_preservation(p.project_xml, ET.tostring(root, encoding='unicode'), PATH,
                    changed_parameters=p.expected, created_oids=receipts, graph_operations=p.graph_operations)['preserved'])
        # Same candidate source1 consumes the new selected application, whereas
        # the older explicitly bounded remote-only profile still requires it.
        p = self.plan(kind='PC_TSB5', raw=raw_values(RemoteSetbackControlSource=1,
            RemoteSetbackOnGroup=21, RemoteSetbackOffGroup=22), apps={})
        self.assertEqual([c.address for c in p.creations], [172, 7, 56, 21, 22, 255])

    def test_existing_prefix_renames_and_missing_case_insensitive_reuse(self):
        raw = raw_values(CoolStage1Output=40, HeatStage1Output=41, CoolFanLowOutput=42,
                         DamperZone1Output=43, ZoneGroup=137)
        apps = {56: {255: '<Unused>', 40: '[CG137] old output', 41: 'User heating Ω',
                     43: '[CG137] retained damper', 50: '[cg137] g (fan)'}, 172: {137: 'Zone'}, 203: {}}
        # Name equality changes ASCII letters only. Unrelated Unicode names
        # do not make this unique generated-name lookup depend on sort order.
        p = self.plan(raw=raw, apps=apps)
        self.assertEqual(p.output_expected['CoolFanLowOutput'], 50)
        self.assertEqual(p.as_dict()['output_projection']['resolved_references']['HeatStage1Output']['name'],
                         'User heating Ω')
        self.assertEqual([(r.address, r.previous_name, r.name) for r in p.renames],
                         [(40, '[CG137] old output', '[CG137] Y (heat/cool)')])
        self.assertEqual(p.output_expected['DamperZone1Output'], 43)
        self.assertEqual(p.as_dict()['output_projection']['resolved_references']['DamperZone1Output']['name'],
                         '[CG137] retained damper')
        # An already-resolved prefix object is renamed directly even if a
        # different group already bears its generated name.
        apps[56][51] = '[CG137] Y (heat/cool)'
        self.assertEqual(self.plan(raw=raw, apps=apps).output_expected['CoolStage1Output'], 40)
        apps[56][52] = '[CG137] G (fan)'
        with self.assertRaisesRegex(ThermostatTemplateError, 'ambiguous'):
            self.plan(raw=raw, apps=apps)

    def test_same_object_rename_history_and_preservation(self):
        raw = raw_values(CoolStage1Output=40, HeatStage1Output=40, InternalPlantType=6)
        apps = {56: {255: '<Unused>', 40: '[CG07] old'}, 172: {7: 'Zone'}, 203: {}}
        p = self.plan(raw=raw, apps=apps)
        self.assertEqual([(r.previous_name, r.name) for r in p.renames],
                         [('[CG07] old', '[CG07] pump'), ('[CG07] pump', '[CG07] W (heat)')])
        self.assertEqual(p.output_expected['CoolStage1Output'], 40)
        self.assertEqual(p.as_dict()['output_projection']['resolved_references']['CoolStage1Output']['name'],
                         '[CG07] W (heat)')
        root, receipts = materialize(p)
        after = ET.tostring(root, encoding='unicode')
        def verify(text=after, ops=p.graph_operations):
            return verify_project_preservation(p.project_xml, text, PATH, changed_parameters=p.expected,
                                               created_oids=receipts, graph_operations=ops)
        self.assertEqual(verify()['renamed_groups'][0]['previous_name'], '[CG07] old')
        for mutation in ('tag', 'description', 'level', 'oid', 'group-attribute', 'tag-attribute'):
            altered = ET.fromstring(after)
            group = altered.find("./Project/Network/Application[Address='56']/Group[Address='40']")
            if mutation == 'tag': group.find('TagName').text = 'unplanned'
            elif mutation == 'description': group.find('Description').text = 'drift'
            elif mutation == 'level': group.find('Level').set('Value', '9')
            elif mutation == 'oid': group.find('OID').text = oid('wrong')
            elif mutation == 'group-attribute': group.set('Opaque', 'drift')
            else: group.find('TagName').set('Opaque', 'drift')
            with self.subTest(mutation=mutation), self.assertRaises(ThermostatTemplateError):
                verify(ET.tostring(altered, encoding='unicode'))
        with self.assertRaises(ThermostatTemplateError):
            verify(ops=tuple(reversed(p.graph_operations)))
        for altered in (replace(p.renames[0], previous_name='different'),
                        replace(p.renames[0], identity=oid('another-group'))):
            with self.subTest(altered=altered), self.assertRaises(ThermostatTemplateError):
                verify(ops=(altered,) + p.graph_operations[1:])
        verify_project_preservation(after, after, PATH, changed_parameters=(), created_oids={})

    def test_ordered_fan_swap_requires_temporary_unused(self):
        raw = raw_values(CoolFanLowOutput=10, CoolFanMediumOutput=11)
        apps = {56: {255: '<Unused>', 10: 'Low', 11: 'Medium'}, 172: {7: 'Zone'}, 203: {}}
        bad = [{'parameter': 'CoolFanLowOutput', 'address': 11},
               {'parameter': 'CoolFanMediumOutput', 'address': 10}]
        with self.assertRaisesRegex(ThermostatTemplateError, 'another speed'):
            self.plan(raw=raw, apps=apps, selections=bad)
        history = [{'parameter': 'CoolFanLowOutput', 'address': 255},
                   {'parameter': 'CoolFanMediumOutput', 'address': '10'},
                   {'parameter': 'CoolFanLowOutput', 'address': 11}]
        p = self.plan(raw=raw, apps=apps, selections=history)
        self.assertEqual((p.output_expected['CoolFanLowOutput'], p.output_expected['CoolFanMediumOutput']), (11, 10))
        self.assertEqual([s['address'] for s in p.as_dict()['output_selections']], [255, 10, 11])
        self.assertEqual([s['position'] for s in p.as_dict()['output_projection']['selections']], [1, 2, 3])
        self.assertEqual(validate_remote_plan(self.store, p), p)

    def test_final_validation_after_selection_and_cross_collection_sharing(self):
        raw = raw_values(CoolStage1Output=10, CoolStage2Output=10)
        apps = {56: {255: '<Unused>', 10: 'Shared', 11: 'Other'}, 172: {7: 'Zone'}, 203: {}}
        with self.assertRaisesRegex(ThermostatTemplateError, 'duplicate cooling'):
            self.plan(raw=raw, apps=apps)
        p = self.plan(raw=raw, apps=apps, selections=[{'parameter': 'CoolStage2Output', 'address': 11},
            {'parameter': 'HeatStage1Output', 'address': 10}, {'parameter': 'InternalRelay1GroupNumber', 'address': 10},
            {'parameter': 'InternalRelay2GroupNumber', 'address': 10}])
        self.assertEqual([p.output_expected[n] for n in ('CoolStage1Output', 'HeatStage1Output',
            'InternalRelay1GroupNumber', 'InternalRelay2GroupNumber')], [10] * 4)
        for field in ('HeatStage2Output', 'DamperZone2Output'):
            changes = {'HeatStage1Output': 10} if field.startswith('Heat') else {'DamperZone1Output': 10}
            with self.assertRaisesRegex(ThermostatTemplateError, 'duplicate'):
                self.plan(raw=raw_values(**changes), apps=apps,
                          selections=[{'parameter': field, 'address': 10}])

    def test_control_gates_slave_projection_and_basic_damper_load(self):
        apps = {56: {255: '<Unused>', 10: 'Chosen'}, 172: {7: 'Zone'}, 203: {}}
        for kind, changes, field in [
            ('PC_TSA', {}, 'InternalRelay1GroupNumber'), ('PC_TSB', {}, 'InternalRelay1GroupNumber'),
            ('PC_TSA5', {'ControlledZones': 0}, 'InternalRelay1GroupNumber'),
            ('PC_TSB5', {}, 'DamperZone1Output'), ('PC_TSA5', {'InternalPlantZones': 1}, 'DamperZone1Output'),
            ('PC_TSA5', {'InternalPlantType': 4}, 'CoolStage1Output'),
            ('PC_TSA5', {'InternalPlantType': 2}, 'HeatStage1Output'),
            ('PC_TSA5', {'InternalPlantType': 8}, 'HeatFanLowOutput')]:
            with self.subTest(kind=kind, changes=changes, field=field), self.assertRaisesRegex(
                    ThermostatTemplateError, 'hidden or disabled'):
                self.plan(kind=kind, raw=raw_values(**changes), apps=apps,
                          selections=[{'parameter': field, 'address': 10}])
        p = self.plan(raw=raw_values(ControlledZones=0), apps=apps,
                      selections=[{'parameter': 'DamperZone4Output', 'address': 10}])
        self.assertEqual(p.output_expected['DamperZone4Output'], 255)
        self.assertEqual(p.as_dict()['output_projection']['resolved_references']['DamperZone4Output']['address'], 10)
        p = self.plan(kind='PC_TSB5', raw=raw_values(DamperZone1Output=10), apps=apps)
        self.assertEqual(p.output_expected['DamperZone1Output'], 255)
        # Raw8 with an output used by the converter becomes virtual11.
        p = self.plan(raw=raw_values(InternalPlantType=8, CoolStage1Output=10), apps=apps,
                      selections=[{'parameter': 'HeatFanHighOutput', 'address': 10}])
        self.assertEqual(p.as_dict()['output_projection']['virtual_plant_type'], 11)

    def test_default_installation_cases_and_absent_selection_refusal(self):
        for code, expected in [(0, '[CG07] Y (heat/cool)'), (1, '[CG07] Y (heat/cool)'),
                               (3, '[CG07] Y1 (cool/heat)'), (255, '[CG07] Y (heat/cool)')]:
            with self.subTest(code=code):
                p = self.plan(raw=raw_values(InstallationCode=code, CoolStage1Output=40))
                self.assertEqual(p.creations[0].name, expected)
        with self.assertRaisesRegex(ThermostatTemplateError, 'existing group'):
            self.plan(selections=[{'parameter': 'CoolStage1Output', 'address': 40}])
        with self.assertRaisesRegex(ThermostatTemplateError, '0..11'):
            self.plan(raw=raw_values(InternalPlantType=128))

    def test_strict_history_schema_dependency_and_replay(self):
        for history in ({}, True, [{'parameter': 'Unknown', 'address': 1}],
                        [{'parameter': 'CoolStage1Output', 'address': True}],
                        [{'parameter': 'CoolStage1Output', 'address': 1.5}],
                        [{'parameter': 'CoolStage1Output', 'address': 256}],
                        [{'parameter': 'CoolStage1Output', 'address': 1, 'extra': 0}]):
            with self.subTest(history=history), self.assertRaises(ThermostatTemplateError):
                self.plan(selections=history)
        with self.assertRaisesRegex(ThermostatTemplateError, 'not admitted'):
            self.plan(edits={'CoolStage1Output': 40})
        p = self.plan(raw=raw_values(CoolStage1Output=40))
        for broken in (replace(p, graph_operations=()), replace(p, output_values=()),
                       replace(p, output_projection_json='{}'), replace(p, output_selections=None),
                       replace(p, owned_values=p.owned_values + (('Invented', 1),))):
            with self.subTest(tamper=broken.output_projection_json), self.assertRaises(ThermostatTemplateError):
                validate_remote_plan(self.store, broken)
        with self.assertRaisesRegex(ThermostatTemplateError, 'Stored project PP differs'):
            self.plan(raw=raw_values(ZoneGroup=8), xml=seed())
        spec = self.folder / 'THERMOSTATA.xml'
        spec.write_text(spec.read_text().replace('<MinVersion>0</MinVersion>', '<MinVersion>3</MinVersion>'))
        with self.assertRaisesRegex(ThermostatTemplateError, 'firmware'):
            validate_remote_plan(UnitSpecStore(self.folder), p)

    def test_complete_source_extracted_default_label_table(self):
        # This oracle is extracted from the retained EXE, independently of
        # thermostat_post_load.DEFAULT_NAMES. Exercise every source case,
        # including the installation-specific branches and absent defaults.
        fixture = Path(__file__).parents[1] / 'research/fixtures/thermostat-output-groups-source-review.json'
        source = json.loads(fixture.read_text())['default_labels']
        actual, expected = {}, {}
        for role, plants in source.items():
            for plant, cases in plants.items():
                for case in cases:
                    key = (role, int(plant), case['installation'])
                    actual[key] = _default_name(*key)
                    expected[key] = case['label']
        self.assertEqual(actual, expected)
        self.assertEqual(len(source), 14)

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_TOOLKIT_MAP'),
                         'Explicit original EXE/MAP required for static source verification')
    def test_optional_static_source(self):
        research = Path(__file__).parents[1] / 'research'
        sys.path.insert(0, str(research))
        self.addCleanup(sys.path.remove, str(research))
        from thermostat_output_groups_static import inspect
        result = inspect(Path(os.environ['CBUS_TOOLKIT_EXE']), Path(os.environ['CBUS_TOOLKIT_MAP']))
        fixture = json.loads((research / 'fixtures/thermostat-output-groups-source-review.json').read_text())
        self.assertEqual(result, fixture)
        self.assertFalse(result['original_executed'])


if __name__ == '__main__':
    unittest.main()
