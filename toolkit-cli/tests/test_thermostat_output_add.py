"""Direct output Add outcomes on the shared graph, with literal oracles."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

from cbus_toolkit.thermostat_remote_references import (plan_remote_references,
    validate_remote_plan, verify_project_preservation)
from cbus_toolkit.thermostat_templates import ThermostatTemplateError
from cbus_toolkit.unitspec import UnitSpecStore
from test_thermostat_output_groups import FIELDS, raw_values, seed, materialize
from test_thermostat_remote_references import PATH, oid, node
from test_thermostat_settings import _spec


def add(parameter='HeatStage1Output', *, outcome='accept', **edits):
    return dict(op='add-output-group', parameter=parameter, outcome=outcome, **edits)


def select(parameter, address):
    return dict(op='select-output-group', parameter=parameter, address=address)


class OutputAddTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for family in ('THERMOSTATA', 'THERMOSTATB'):
            (self.folder / (family + '.xml')).write_text(_spec(family, set(raw_values())))
        self.store = UnitSpecStore(self.folder)

    def plan(self, operations=(), *, kind='PC_TSA5', raw=None, apps=None, xml=None, prompts=None):
        raw = raw_values() if raw is None else raw
        if xml is None:
            root = ET.fromstring(seed(kind, raw, apps))
            root.find('./Project/TagName').text = 'Thermostat Project'
            xml = ET.tostring(root, encoding='unicode')
        return plan_remote_references(self.store, kind, raw, {}, project_xml=xml,
            unit_path=PATH, output_operations=operations, level_prompts=prompts)

    def test_cancel_default_explicit_address_and_two_add_allocation(self):
        p = self.plan([add(outcome='cancel'), add(), add('HeatStage2Output', address=8),
                       add('HeatStage3Output', name=' \t Third heat \r\n')],
            apps={56: {0: 'Retain zero', 2: 'Retain two', 255: '<Unused>'}, 172: {7: 'Zone'}, 203: {}})
        self.assertEqual([(c.application, c.address, c.name) for c in p.creations],
                         [(56, 1, 'Group 1'), (56, 8, 'Group 8'), (56, 3, 'Third heat')])
        self.assertTrue(all(c.output_add is True for c in p.creations))
        self.assertTrue(all(c['output_add'] is True for c in p.as_dict()['planned_creations']))
        view = p.as_dict()['output_projection']
        self.assertEqual([r['first_free_address'] for r in view['add_dialogs']], [1, 1, 3, 3])
        self.assertEqual([r['seeded_name'] for r in view['add_dialogs']], ['Group 1', 'Group 1', 'Group 3', 'Group 3'])
        self.assertEqual([r['address_selected_name'] for r in view['add_dialogs']], [None, 'Group 1', 'Group 8', 'Group 3'])
        self.assertEqual([r['name'] for r in view['add_dialogs']], [None, 'Group 1', 'Group 8', 'Third heat'])
        self.assertEqual([r['position'] for r in view['operations']], [1, 2, 3, 4])
        self.assertEqual([r['object_created'] for r in view['add_dialogs']], [False, True, True, True])
        self.assertEqual(view['add_dialogs'][0]['identity'], oid('group:56:255'))
        self.assertEqual(p.output_requested_parameters, ('HeatStage1Output', 'HeatStage2Output', 'HeatStage3Output'))
        self.assertEqual(p.output_expected, {name: {'HeatStage1Output': 1, 'HeatStage2Output': 8,
                                                  'HeatStage3Output': 3}.get(name, 255) for name in FIELDS})
        self.assertEqual(validate_remote_plan(self.store, p), p)

    def test_select_add_select_preserves_creation_and_fan_history(self):
        raw = raw_values(CoolFanLowOutput=20, CoolFanMediumOutput=21, CoolFanHighOutput=22)
        apps = {56: {20: 'Low', 21: 'Medium', 22: 'High', 255: '<Unused>'}, 172: {7: 'Zone'}, 203: {}}
        p = self.plan([select('CoolFanLowOutput', 255), select('CoolFanMediumOutput', 20),
                      add('CoolFanLowOutput'), select('CoolFanLowOutput', 21)], raw=raw, apps=apps)
        self.assertEqual([(c.kind, c.application, c.address, c.name) for c in p.creations], [('Group', 56, 0, 'Group 0')])
        self.assertEqual([p.output_expected[n] for n in ('CoolFanLowOutput', 'CoolFanMediumOutput', 'CoolFanHighOutput')], [21, 20, 22])
        view = p.as_dict()['output_projection']
        self.assertEqual([r['op'] for r in view['operations']], ['select-output-group', 'select-output-group',
                                                               'add-output-group', 'select-output-group'])
        self.assertEqual([r['position'] for r in view['selections']], [1, 2, 4])
        self.assertEqual(view['operations'][3]['previous_identity'], 'planned-group:56:0')
        root, receipts = materialize(p)
        self.assertTrue(verify_project_preservation(p.project_xml, ET.tostring(root, encoding='unicode'), PATH,
            changed_parameters=p.expected, created_oids=receipts, graph_operations=p.graph_operations)['preserved'])
        with self.assertRaisesRegex(ThermostatTemplateError, 'Fan selector excludes'):
            self.plan([select('CoolFanLowOutput', 21), add('CoolFanLowOutput')], raw=raw, apps=apps)

    def test_all_23_selectors_add_literal_addresses_and_gates(self):
        p = self.plan([add(name) for name in FIELDS])
        self.assertEqual(p.output_expected, dict(zip(FIELDS, range(23))))
        self.assertEqual([(c.address, c.name) for c in p.creations], [(n, 'Group ' + str(n)) for n in range(23)])
        for kind in ('PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5'):
            with self.subTest(kind=kind):
                self.assertEqual(self.plan([add()], kind=kind).output_expected['HeatStage1Output'], 0)
                for target, enabled in [('DamperZone1Output', kind.startswith('PC_TSA')),
                                        ('InternalRelay1GroupNumber', kind.endswith('5'))]:
                    if enabled:
                        self.assertEqual(self.plan([add(target)], kind=kind).output_expected[target], 0)
                    else:
                        with self.assertRaisesRegex(ThermostatTemplateError, 'hidden or disabled'):
                            self.plan([add(target)], kind=kind)
        for raw, target in [(raw_values(ControlledZones=0), 'InternalRelay1GroupNumber'),
                            (raw_values(InternalPlantType=0), 'HeatStage1Output'),
                            (raw_values(InternalPlantType=1), 'CoolStage1Output'),
                            (raw_values(InternalPlantZones=1), 'DamperZone1Output'),
                            *[(raw_values(InternalPlantType=8), n) for n in
                              ('HeatFanLowOutput', 'HeatFanMediumOutput', 'HeatFanHighOutput')]]:
            with self.subTest(target=target, raw=raw), self.assertRaisesRegex(ThermostatTemplateError, 'hidden or disabled'):
                self.plan([add(target)], raw=raw)

    def test_complete_load_before_add_and_shared_remote_level_owner(self):
        raw = raw_values(ApplicationNumber=203, RemoteSetbackControlSource=2, RemoteSetbackOnGroup=21,
            RemoteSetbackOffGroup=22, CoolStage1Output=0, EvapProgramEnabled=1, RemoteScheduleEnable=1,
            RemoteScheduleOnGroup=12, RemoteScheduleOffGroup=13, RemoteScheduleOverrideGroup=14)
        p = self.plan([add('CoolStage2Output'), add('HeatStage2Output')], raw=raw,
            apps={172: {7: 'Zone'}, 203: {255: '<Unused>'}}, prompts={'setback': 'accept', 'schedule': 'accept'})
        self.assertEqual([(c.application, c.address, c.name) for c in p.creations], [
            (203, 21, 'Enable Network Variable 21'), (203, 22, 'Enable Network Variable 22'),
            (203, 0, '[CG07] Y (heat/cool)'), (203, 12, 'Enable Network Variable 12'),
            (203, 13, 'Enable Network Variable 13'), (203, 14, 'Enable Network Variable 14'),
            (203, 1, 'Enable Network Variable 1'), (203, 2, 'Enable Network Variable 2')])
        self.assertTrue(all(c.kind == 'Group' for c in p.creations))
        self.assertEqual([c.output_add for c in p.creations], [False] * 6 + [True, True])
        self.assertNotIn('output_add', p.creations[0].as_dict())
        self.assertEqual([r['first_free_address'] for r in p.as_dict()['output_projection']['add_dialogs']], [1, 2])
        self.assertEqual(len(p.level_creations), 155)
        self.assertEqual([r.group for r in p.level_creations[::31]], [21, 22, 12, 13, 14])
        self.assertEqual(p.output_expected['CoolStage2Output'], 1)
        self.assertEqual(p.output_expected['HeatStage2Output'], 2)
        self.assertEqual(validate_remote_plan(self.store, p), p)

    def test_cancel_noop_and_slave_damper_add_graph_only(self):
        cancel = self.plan([add(outcome='cancel')])
        self.assertFalse(cancel.apply_would_mutate)
        self.assertEqual(cancel.output_requested_parameters, ())
        collision = {56: {5: 'Group 0', 255: '<Unused>'}, 172: {7: 'Zone'}, 203: {}}
        cancelled = self.plan([add(outcome='cancel')], apps=collision)
        self.assertFalse(cancelled.apply_would_mutate)
        self.assertEqual(cancelled.as_dict()['output_projection']['add_dialogs'][0]['seeded_name'], 'Group 0')
        with self.assertRaisesRegex(ThermostatTemplateError, '2203'):
            self.plan([add()], apps=collision)
        p = self.plan([add('DamperZone1Output')], raw=raw_values(ControlledZones=0))
        self.assertFalse(p.pp_mutation_required)
        self.assertTrue(p.graph_mutation_required)
        self.assertEqual(p.output_expected['DamperZone1Output'], 255)
        self.assertEqual(p.as_dict()['output_projection']['resolved_references']['DamperZone1Output']['address'], 0)
        self.assertEqual(p.output_requested_parameters, ('DamperZone1Output',))
        q = self.plan([add(), select('HeatStage1Output', 255)])
        self.assertFalse(q.pp_mutation_required)
        self.assertTrue(q.graph_mutation_required)
        self.assertEqual(q.output_requested_parameters, ('HeatStage1Output',))

    def test_project_tag_name_is_exact_and_consumed_only_on_accept(self):
        root = ET.fromstring(seed())
        project = root.find('Project')
        project.remove(project.find('TagName'))
        missing = ET.tostring(root, encoding='unicode')
        self.assertFalse(self.plan([add(outcome='cancel')], xml=missing).apply_would_mutate)
        with self.assertRaisesRegex(ThermostatTemplateError, 'Project.TagName'):
            self.plan([add()], xml=missing)
        for mutation in ('duplicate', 'structured', 'namespace'):
            bad = ET.fromstring(seed())
            tag = bad.find('./Project/TagName')
            if mutation == 'duplicate': ET.SubElement(bad.find('Project'), 'TagName').text = 'Other'
            elif mutation == 'structured': ET.SubElement(tag, 'Nested').text = 'Other'
            else: tag.set('xmlns', 'urn:lookalike')
            with self.subTest(mutation=mutation), self.assertRaises(ThermostatTemplateError):
                self.plan([add()], xml=ET.tostring(bad, encoding='unicode'))
        with self.assertRaisesRegex(ThermostatTemplateError, '2204'):
            self.plan([add(name='  Thermostat Project ')])
        self.assertEqual(self.plan([add(name='thermostat project')]).creations[0].name, 'thermostat project')
        self.assertEqual(self.plan([add(name='REMOTE')]).creations[0].name, 'REMOTE')

    def test_source_trim_uppercase_utf16_and_native_name_boundary(self):
        for name, expected in [(' \t Room \r\n', 'Room'), ('\U0001f321' * 16, '\U0001f321' * 16),
                               ('A' * 32, 'A' * 32), ('\u00a0Room\u00a0', '\u00a0Room\u00a0'),
                               ('Double  spaces', 'Double  spaces'), ('\u00a0', '\u00a0')]:
            with self.subTest(name=name):
                self.assertEqual(self.plan([add(name=name)]).creations[0].name, expected)
        for name in (' \t\r\n', 'A' * 33, ' ' + 'A' * 32, '\U0001f321' * 16 + ' ', '\ud800',
                     'A\x00B', 'A\nB', 'A\x7fB', 'A\ufffeB'):
            with self.subTest(name=repr(name)), self.assertRaises(ThermostatTemplateError):
                self.plan([add(name=name)])
        apps = {56: {255: '<Unused>', 10: 'ASCII Name', 11: 'é'}, 172: {7: 'Zone'}, 203: {}}
        with self.assertRaisesRegex(ThermostatTemplateError, '2203'):
            self.plan([add(name='ascii NAME')], apps=apps)
        self.assertEqual(self.plan([add(name='É')], apps=apps).creations[0].name, 'É')
        self.assertEqual(self.plan([add(name='<Unused>')], apps={56: {255: 'Custom unused'},
            172: {7: 'Zone'}, 203: {}}).creations[0].name, '<Unused>')

    def test_evolving_name_inventory_and_later_invalid_parent_refuse_full_plan(self):
        with self.assertRaisesRegex(ThermostatTemplateError, '2203'):
            self.plan([add(name='New Name'), add('HeatStage2Output', name='new name')])
        with self.assertRaisesRegex(ThermostatTemplateError, 'duplicate heating'):
            self.plan([add(), select('HeatStage2Output', 0)])
        with self.assertRaisesRegex(ThermostatTemplateError, 'existing group'):
            self.plan([select('HeatStage1Output', 0), add()])
        raw = raw_values(HeatStage1Output=30)
        apps = {56: {30: '[CG07] old', 255: '<Unused>'}, 172: {7: 'Zone'}, 203: {}}
        with self.assertRaisesRegex(ThermostatTemplateError, '2203'):
            self.plan([add('HeatStage2Output', name='[cg07] y (HEAT/COOL)')], raw=raw, apps=apps)
        p = self.plan([add('HeatStage2Output', name='[CG07] old')], raw=raw, apps=apps)
        self.assertEqual([r.action for r in p.graph_operations], ['rename', 'create'])
        self.assertEqual(p.creations[0].name, '[CG07] old')

    def test_no_free_address_also_prevents_opening_cancel(self):
        apps = {56: {i: 'Retained ' + str(i) for i in range(255)}, 172: {7: 'Zone'}, 203: {}}
        for outcome in ('accept', 'cancel'):
            with self.subTest(outcome=outcome), self.assertRaisesRegex(ThermostatTemplateError, '2271'):
                self.plan([add(outcome=outcome)], apps=apps)
        apps[56].pop(254)
        p = self.plan([add()], apps=apps)
        self.assertEqual((p.creations[-1].address, p.creations[-1].name), (254, 'Group 254'))
        self.assertEqual(p.as_dict()['output_projection']['add_dialogs'][0]['free_address_count'], 1)

    def test_strict_operation_shapes_and_legacy_selection_contract(self):
        invalid = [None, {}, 'add', {'op': 'unknown'}, {'op': 'add-output-group'},
            add(outcome=True), add(outcome='cancel', address=1), add(outcome='cancel', name='No'),
            add(address=True), add(address=1.0), add(address='1'), add(address=255), add(address=-1),
            add(name=None), add(parameter=[]), add(extra=1), select('HeatStage1Output', True),
            dict(select('HeatStage1Output', 255), extra=1)]
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ThermostatTemplateError): self.plan([row])
        for history in ({}, 'history', [add()] * 257):
            with self.subTest(history=type(history).__name__), self.assertRaises(ThermostatTemplateError):
                self.plan(history)
        old = plan_remote_references(self.store, 'PC_TSA5', raw_values(), {}, project_xml=seed(),
            unit_path=PATH, output_selections=[{'parameter': 'HeatStage1Output', 'address': '0xff'}])
        new = self.plan([select('HeatStage1Output', '0xff')], xml=seed())
        self.assertEqual(old.expected, new.expected)
        self.assertEqual(old.graph_operations, new.graph_operations)
        self.assertNotIn('output_operations', old.as_dict())
        self.assertNotIn('operations', old.as_dict()['output_projection'])
        self.assertEqual(old.as_dict()['output_selections'], [{'parameter': 'HeatStage1Output', 'address': 255}])
        self.assertEqual(old.output_requested_parameters, ('HeatStage1Output',))
        self.assertEqual(new.as_dict()['output_operations'], [select('HeatStage1Output', 255)])
        with self.assertRaisesRegex(ThermostatTemplateError, 'mutually exclusive'):
            plan_remote_references(self.store, 'PC_TSA5', raw_values(), {}, project_xml=seed(),
                unit_path=PATH, output_selections=[], output_operations=[])

    def test_issued_history_replay_rejects_all_derived_and_input_tampering(self):
        p = self.plan([add(), select('HeatStage1Output', 255)])
        view = p.as_dict()['output_projection']
        bad_view = dict(view, add_dialogs=[dict(view['add_dialogs'][0], first_free_address=7)])
        created = replace(p.creations[0], name='Smuggled')
        for altered in (replace(p, output_operations=[]), replace(p, output_operations=('not JSON',)),
                        replace(p, output_operations=(json.dumps(add(address=True)),)),
                        replace(p, output_operations=(json.dumps(add(address=8)),)),
                        replace(p, output_projection_json=json.dumps(bad_view)),
                        replace(p, creations=(created,), graph_operations=(created,)),
                        replace(p, output_values=(('HeatStage1Output', 0),)),
                        replace(p, project_xml=p.project_xml.replace('Thermostat Project', 'Other Project'))):
            with self.subTest(altered=repr(altered.output_operations)), self.assertRaises(ThermostatTemplateError):
                validate_remote_plan(self.store, altered)
        for flag in (False, 1, 0, 'true'):
            row = replace(p.creations[0], output_add=flag)
            with self.subTest(flag=flag), self.assertRaises(ThermostatTemplateError):
                validate_remote_plan(self.store, replace(p, creations=(row,), graph_operations=(row,)))

    def test_every_intermediate_control_address_must_fit_selected_specification(self):
        spec_path = self.folder / 'THERMOSTATA.xml'
        spec = ET.fromstring(spec_path.read_text())
        spec.find("./Parameters/Param[Name='HeatStage1Output']/MinValue").text = '$0A'
        spec_path.write_text(ET.tostring(spec, encoding='unicode'))
        apps = {56: {9: 'Below minimum', 255: '<Unused>'}, 172: {7: 'Zone'}, 203: {}}
        for first in (select('HeatStage1Output', 9), add(), add(address=8)):
            with self.subTest(first=first), self.assertRaisesRegex(ThermostatTemplateError, 'HeatStage1Output'):
                self.plan([first, select('HeatStage1Output', 255)], apps=apps)
        # Cancellation never assigns its below-minimum provisional address.
        self.assertFalse(self.plan([add(outcome='cancel')], apps=apps).apply_would_mutate)
        apps[56].update({n: 'Retain ' + str(n) for n in range(9)})
        p = self.plan([add(), select('HeatStage1Output', 255)], apps=apps)
        self.assertEqual(p.creations[0].address, 10)
        self.assertFalse(p.pp_mutation_required)

    def test_full_preservation_after_add_then_selection_elsewhere(self):
        p = self.plan([add(name='Created and retained'), select('HeatStage1Output', 255)])
        root, receipts = materialize(p)
        after = ET.tostring(root, encoding='unicode')
        def verify(text):
            return verify_project_preservation(p.project_xml, text, PATH, changed_parameters=p.expected,
                created_oids=receipts, graph_operations=p.graph_operations)
        self.assertTrue(verify(after)['preserved'])
        for mutation in ('created-name', 'created-oid', 'unplanned-group', 'retained-level', 'opaque-group', 'tag-attribute'):
            altered = ET.fromstring(after)
            app = altered.find("./Project/Network/Application[Address='56']")
            created = app.find("Group[Address='0']")
            retained = app.find("Group[Address='255']")
            if mutation == 'created-name': created.find('TagName').text = 'Changed'
            elif mutation == 'created-oid': created.find('OID').text = oid('wrong-created')
            elif mutation == 'unplanned-group': node(app, 'Group', 9, 'Extra', oid('unplanned'))
            elif mutation == 'retained-level': retained.find('Level').set('Value', '199')
            elif mutation == 'opaque-group': retained.set('Opaque', 'Changed')
            else: retained.find('TagName').set('Opaque', 'Changed')
            with self.subTest(mutation=mutation), self.assertRaises(ThermostatTemplateError):
                verify(ET.tostring(altered, encoding='unicode'))

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_TOOLKIT_MAP'),
                         'Explicit original EXE/MAP required for static source verification')
    def test_optional_static_source(self):
        research = Path(__file__).parents[1] / 'research'
        sys.path.insert(0, str(research))
        self.addCleanup(sys.path.remove, str(research))
        from thermostat_output_add_static import inspect
        result = inspect(Path(os.environ['CBUS_TOOLKIT_EXE']), Path(os.environ['CBUS_TOOLKIT_MAP']))
        fixture = json.loads((research / 'fixtures/thermostat-output-add-source-review.json').read_text())
        self.assertEqual(result, fixture)
        self.assertFalse(result['original_executed'])


if __name__ == '__main__':
    unittest.main()
